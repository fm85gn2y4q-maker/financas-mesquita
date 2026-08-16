"""Catálogo AGA de Moedas Brasileiras (texto extraído do PDF) → dados/catalogo.db

    python ingerir_catalogo_aga.py <arquivo.txt>

BANCO SEPARADO, E ISSO NÃO É ARRUMAÇÃO
--------------------------------------
O catálogo NÃO entra em `dados/leiloes.db`. Vai para `dados/catalogo.db`, que
nunca é publicado, e `preparar_release_leiloes.py` se recusa a gerar release se
achar tabela de catálogo dentro do acervo de leilões.

O motivo está escrito na página 2 da própria obra:

    TODOS OS DIREITOS RESERVADOS. PROIBIDA A REPRODUÇÃO OU DISTRIBUIÇÃO TOTAL
    OU PARCIAL DESTA OBRA, DE QUALQUER FORMA, MEIO ELETRÔNICO, MECÂNICO, OU
    QUALQUER OUTRO, SEM A PERMISSÃO DO AUTOR. (Lei 9.610/1998)

Usar a sua cópia na sua máquina é uma coisa. O caminho de publicação deste
repositório é outra: ele sobe o acervo como **asset público de release no
GitHub** e o serve por um conector cuja aprovação de OAuth é automática. Nesse
caminho, o catálogo deixaria de ser a sua cópia e viraria distribuição — que é
exatamente o que a obra proíbe. A separação existe para que isso não aconteça
por descuido de arquitetura.

A ARMADILHA DESTA OBRA: AS COLUNAS DE CONSERVAÇÃO MUDAM NO MEIO DO CATÁLOGO
--------------------------------------------------------------------------
Medido nas 764 tabelas do arquivo:

    460 tabelas   Núm. Data ... BC  MBC SOB     (colonial e império)
    304 tabelas   Núm. Data ... MBC SOB FC      (republicano)

Assumir um conjunto fixo desloca TODO preço em um grau — o valor de FC entra
como SOB, o de SOB como MBC. O erro é sistemático, silencioso, e o resultado
tem aparência impecável. Por isso o cabeçalho de CADA tabela é lido, e linha
cujo cabeçalho não foi reconhecido é contada e descartada, nunca adivinhada.

O QUE ESTE CATÁLOGO É, E O QUE ELE NÃO É
----------------------------------------
É **preço de catálogo**, que não é preço de varejo nem preço de liquidação
rápida — os três divergem, e em peça rara divergem muitas vezes. O acervo de
leilões continua medindo martelo observado; o catálogo entra ao lado, como
segunda referência, e para duas coisas que o martelo não dá:

    identificação   número AGA, tiragem, letra monetária, peso e diâmetro
    raridade        os códigos R…RRRRR, onde a obra nem arrisca preço
"""

from __future__ import annotations

import re
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "dados" / "catalogo.db"

ESQUEMA = """
CREATE TABLE moeda (
    id            INTEGER PRIMARY KEY,
    catalogo      TEXT NOT NULL,      -- 'AGA'
    numero        INTEGER NOT NULL,   -- o número do verbete
    ano           INTEGER,
    denominacao   TEXT,
    -- Mesma denominação, escrita como o acervo de leilões a escreve: a obra usa
    -- "6.400 réis" e a identificação do lote produz "6400 réis". Sem esta
    -- coluna o casamento falha em toda peça acima de mil réis — que são
    -- justamente as caras.
    denominacao_norm TEXT,
    metal         TEXT,
    peso_g        REAL,
    diametro_mm   REAL,
    casa_da_moeda TEXT,
    letra         TEXT,               -- letra monetária (B, R, …)
    tiragem       INTEGER,
    periodo       TEXT,               -- Colônia, Império, República…
    especificacao TEXT,
    observacoes   TEXT,
    -- O metal entra na chave porque **o número AGA não é único**: ele reinicia
    -- a cada seção de metal da obra. Medido: 1.139 números aparecem em mais de
    -- um verbete, e o 633 é ouro de 1816, prata de 1818, cobre de 1816 E aço
    -- de 1993. Um lote que cite "AGA 633" sem dizer o metal não está
    -- identificado — está apenas numerado.
    UNIQUE (catalogo, metal, numero, ano, observacoes)
);

-- Um preço por GRAU, e não três colunas fixas: as colunas mudam ao longo da
-- obra, e formato longo é o que impede o deslocamento de grau.
CREATE TABLE preco (
    moeda_id      INTEGER REFERENCES moeda(id),
    grau          TEXT NOT NULL,      -- BC | MBC | S (SOB) | FC
    valor         REAL,               -- nulo quando a obra só declara raridade
    raridade      TEXT,               -- R, RR, RRR… ou ÚNICA
    PRIMARY KEY (moeda_id, grau)
);

CREATE INDEX ix_moeda_ano ON moeda(ano);
CREATE INDEX ix_moeda_casamento ON moeda(ano, metal, denominacao_norm);

CREATE TABLE fonte (
    chave TEXT PRIMARY KEY,
    valor TEXT
);
"""

# "SOB" é como a obra escreve Soberba; o acervo de leilões usa "S". A tradução
# acontece aqui, uma vez, para que a chave do comparável case.
GRAUS = {"BC": "BC", "MBC": "MBC", "SOB": "S", "FC": "FC", "S": "S"}

_CABECALHO = re.compile(
    r"^\s*N[úu]m\.\s+(?:Data\s+)?(?:Quantidades?\s*(?:produzidas\s*e)?\s*)?"
    r"Observa[çc][õo]es\s+(BC|MBC|SOB|FC)\s+(BC|MBC|SOB|FC)\s+(BC|MBC|SOB|FC)\s*$",
    re.IGNORECASE)

_VALOR = r"(?:\d{1,3}(?:\.\d{3})*,\d{2}|R{1,6}|[ÚU]NICA|-{1,3})"
_LINHA = re.compile(
    rf"^\s*(\d{{1,4}})\s+(1[5-9]\d{{2}}|20[0-2]\d)?\s*(.*?)\s+"
    rf"({_VALOR})\s+({_VALOR})\s+({_VALOR})\s*$")

_DENOMINACAO = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{3})*|\d+)\s*(R[ée]is|Centavos?|Cruzeiros?(?:\s+Novos?)?|"
    r"Cruzados?(?:\s+Novos?)?|Reais?|Real)\s*$", re.IGNORECASE)
# Peso e diâmetro saem em buscas SEPARADAS, e isso é correção de um bug que
# não dava erro: numa expressão só, `[^\n]*?(?:(\d+[,.]\d+)\s*g)?` tem grupo
# opcional depois de quantificador preguiçoso, e o grupo casa VAZIO na hora.
# Resultado: peso e diâmetro nulos nos 4.483 verbetes, sem uma linha de aviso.
_ESPECIFICACAO = re.compile(
    r"\b(Ouro|Prata|Cobre|Bronze|N[íi]quel|Cupro[- ]?n[íi]quel|A[çc]o|Lat[ãa]o|"
    r"Alum[íi]nio|Bimet[áa]lic[ao])\b", re.IGNORECASE)
_PESO = re.compile(r"(\d+[,.]\d+)\s*g\b")
_DIAMETRO = re.compile(r"\bD\s*(\d+[,.]\d+)\s*mm")
_CASA = re.compile(r"Casa da moeda d[eoa]s?\s+(.+?)\s*(?:\(|$)", re.IGNORECASE)
_LETRA = re.compile(r"Letra monet[áa]ria\s+([A-Z](?:\s*[e,]\s*[A-Z])*)", re.IGNORECASE)
_TIRAGEM = re.compile(r"Quant\.?\s*([\d.]+)", re.IGNORECASE)
_PERIODO = re.compile(r"^\s*(Col[óo]nia|Reino Unido|Imp[ée]rio|Rep[úu]blica)\b",
                      re.IGNORECASE)
_RODAPE = re.compile(r"ALEXANDRE GUIMAR|CAT[ÁA]LOGO AGA DE MOEDAS", re.IGNORECASE)


def _normalizar(denominacao: str | None) -> str | None:
    """"6.400 réis" → "6400 réis", que é como a identificação do lote escreve."""
    if not denominacao:
        return None
    return re.sub(r"(\d)\.(\d)", r"\1\2", denominacao).strip().lower()


def _numero(texto: str) -> float | None:
    try:
        return float(texto.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def ingerir(origem: Path, destino: Path = DESTINO) -> None:
    linhas = origem.read_text(encoding="utf-8", errors="replace").splitlines()

    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino.unlink()
    con = sqlite3.connect(destino)
    con.executescript(ESQUEMA)

    contexto = {"periodo": None, "casa": None, "letra": None,
                "denominacao": None, "especificacao": None,
                "metal": None, "peso": None, "diametro": None}
    graus: list[str] | None = None
    moeda_id = 0
    sem_cabecalho = 0
    tabelas = 0

    for linha in linhas:
        if _RODAPE.search(linha):
            continue

        if (m := _CABECALHO.match(linha)):
            graus = [GRAUS[g.upper()] for g in m.groups()]
            tabelas += 1
            continue

        if (m := _PERIODO.match(linha.strip())) and len(linha.strip()) < 60:
            contexto["periodo"] = m.group(1)
        if (m := _CASA.search(linha)):
            contexto["casa"] = m.group(1).strip()
        if (m := _LETRA.search(linha)):
            contexto["letra"] = m.group(1).strip()
        if (m := _DENOMINACAO.match(linha)):
            contexto["denominacao"] = f"{m.group(1)} {m.group(2).lower()}"
            # Denominação nova encerra a tabela anterior: sem isto, uma linha
            # solta depois da tabela herdaria os graus da tabela passada.
            graus = None
        if ("–" in linha or "-" in linha) and len(linha) < 200:
            if (m := _ESPECIFICACAO.search(linha)):
                contexto["especificacao"] = linha.strip()
                contexto["metal"] = m.group(1).capitalize()
                peso = _PESO.search(linha)
                diametro = _DIAMETRO.search(linha)
                contexto["peso"] = _numero(peso.group(1)) if peso else None
                contexto["diametro"] = _numero(diametro.group(1)) if diametro else None

        if not (m := _LINHA.match(linha)):
            continue
        if graus is None:
            # Linha com cara de verbete sem cabeçalho lido antes dela. NÃO se
            # adivinha o grau: conta-se e descarta-se.
            sem_cabecalho += 1
            continue

        numero, ano, meio, *valores = m.groups()
        tiragem = _TIRAGEM.search(meio or "")
        moeda_id += 1
        con.execute(
            "INSERT OR IGNORE INTO moeda VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (moeda_id, "AGA", int(numero), int(ano) if ano else None,
             contexto["denominacao"], _normalizar(contexto["denominacao"]),
             contexto["metal"], contexto["peso"],
             contexto["diametro"], contexto["casa"], contexto["letra"],
             int(tiragem.group(1).replace(".", "")) if tiragem else None,
             contexto["periodo"], contexto["especificacao"],
             (meio or "").strip() or None))

        for grau, valor in zip(graus, valores):
            bruto = valor.strip().upper()
            if re.fullmatch(r"R{1,6}", bruto) or bruto.startswith(("Ú", "U")):
                con.execute("INSERT OR REPLACE INTO preco VALUES (?,?,?,?)",
                            (moeda_id, grau, None, bruto))
            elif (v := _numero(bruto)) is not None:
                con.execute("INSERT OR REPLACE INTO preco VALUES (?,?,?,?)",
                            (moeda_id, grau, v, None))

    con.execute("INSERT OR REPLACE INTO fonte VALUES ('obra', ?)",
                ("Catálogo AGA de Moedas Brasileiras, 1568 ao presente — "
                 "Alexandre Guimarães Alves, janeiro/2020",))
    con.execute("INSERT OR REPLACE INTO fonte VALUES ('arquivo', ?)", (origem.name,))
    con.execute(
        "INSERT OR REPLACE INTO fonte VALUES ('licenca', ?)",
        ("Obra protegida, todos os direitos reservados (Lei 9.610/1998). Cópia "
         "de uso pessoal. NÃO PUBLICAR este banco nem incluí-lo em release.",))
    con.commit()

    verbetes = con.execute("SELECT count(*) FROM moeda").fetchone()[0]
    precos = con.execute("SELECT count(*) FROM preco WHERE valor IS NOT NULL").fetchone()[0]
    raros = con.execute("SELECT count(*) FROM preco WHERE raridade IS NOT NULL").fetchone()[0]
    com_tiragem = con.execute(
        "SELECT count(*) FROM moeda WHERE tiragem IS NOT NULL").fetchone()[0]
    por_grau = con.execute(
        "SELECT grau, count(*) FROM preco GROUP BY grau ORDER BY 2 DESC").fetchall()

    print(f"tabelas lidas       {tabelas:>7}")
    print(f"verbetes            {verbetes:>7}")
    print(f"  com tiragem       {com_tiragem:>7}")
    print(f"cotações            {precos:>7}")
    print(f"  só raridade       {raros:>7}  (a obra não arrisca preço)")
    print(f"por grau            {', '.join(f'{g}: {n}' for g, n in por_grau)}")
    if sem_cabecalho:
        print(f"\n{sem_cabecalho} linhas com forma de verbete foram DESCARTADAS "
              f"por não haver cabeçalho de grau lido antes delas. Não foram "
              f"adivinhadas: grau errado desloca o preço inteiro.")
    print(f"\n{destino}")
    print("Este banco NÃO é publicável — obra protegida, cópia de uso pessoal.")
    con.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    ingerir(Path(sys.argv[1]))
