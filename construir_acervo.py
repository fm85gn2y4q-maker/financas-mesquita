"""Constrói `dados/acervo.db` a partir do que está em dados_brutos/.

Transformação determinística sobre o cru — nunca vai à rede. Pode rodar quantas
vezes for preciso (fase 3 do GUIA-NOVO-ACERVO: a ingestão foi refeita de cinco a
oito vezes nos outros acervos).

DECISÕES DE ESQUEMA, cada uma vinda de uma medição, não de suposição:

1. `siconfi_linha.ordem` existe porque a hierarquia função/subfunção do SICONFI
   **só está na ordem das linhas**. "Administração Geral" aparece sete vezes no
   mesmo anexo e coluna, sob funções diferentes, e nada no registro diz de quem
   ela é filha. Sem `ordem` as linhas viram indistinguíveis e a soma por nome
   junta o que não se junta.

2. `siconfi_linha.demonstrativo` é carimbado do nome do arquivo, não lido do
   payload: o RGF não traz esse campo, e ler do payload perde 7.161 linhas em
   silêncio.

3. `siconfi_linha.nivel` é DERIVADO e depois CONFERIDO. A derivação usa o fato
   de domínio (as 28 funções de governo da Portaria MOG 42/1999); a conferência
   testa se cada função bate com a soma das subfunções que a seguem. Onde não
   bater, o nível fica 'indefinido' — declarado, não chutado.

4. `patrimonio_bem` não tem chave natural: 1.600 plaquetas se repetem, somando
   3.200 linhas. E é fotografia única — o parâmetro `ano` da API é ignorado.

Uso:  python construir_acervo.py
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BRUTOS = RAIZ / "dados_brutos"
BANCO = RAIZ / "dados" / "acervo.db"

# Portaria MOG 42/1999. É o fato de domínio que separa função de subfunção —
# nenhum ajuste de heurística sobre os nomes faria isso com segurança.
FUNCOES_DE_GOVERNO = {
    "Legislativa", "Judiciária", "Essencial à Justiça", "Administração",
    "Defesa Nacional", "Segurança Pública", "Relações Exteriores",
    "Assistência Social", "Previdência Social", "Saúde", "Trabalho",
    "Educação", "Cultura", "Direitos da Cidadania", "Urbanismo", "Habitação",
    "Saneamento", "Gestão Ambiental", "Ciência e Tecnologia", "Agricultura",
    "Organização Agrária", "Indústria", "Comércio e Serviços", "Comunicações",
    "Energia", "Transporte", "Desporto e Lazer", "Encargos Especiais",
}

ESQUEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS coleta (
    fonte        TEXT NOT NULL,
    arquivo      TEXT NOT NULL,
    url          TEXT NOT NULL,
    coletado_em  TEXT NOT NULL,
    sha256       TEXT NOT NULL,
    PRIMARY KEY (fonte, arquivo, coletado_em)
);

CREATE TABLE IF NOT EXISTS siconfi_linha (
    id             INTEGER PRIMARY KEY,
    arquivo        TEXT NOT NULL,
    demonstrativo  TEXT NOT NULL,   -- carimbado do nome do arquivo
    exercicio      INTEGER,
    periodo        INTEGER,
    periodicidade  TEXT,
    co_poder       TEXT,
    anexo          TEXT,
    rotulo         TEXT,
    coluna         TEXT,
    cod_conta      TEXT,
    conta          TEXT,
    valor          REAL,
    ordem          INTEGER NOT NULL, -- posição na resposta; é dimensão, não enfeite
    -- 'funcao' | 'subfuncao' | 'indefinido' | 'fora_de_hierarquia'
    --   indefinido        = está num anexo com hierarquia, mas a conferência da
    --                       soma não fechou. É lacuna real, e tem de aparecer.
    --   fora_de_hierarquia= o anexo não tem função/subfunção nenhuma (receita,
    --                       RGF, DCA). Não é falha: é a natureza do anexo.
    -- Achatar os dois no mesmo rótulo esconderia a lacuna dentro do normal.
    nivel          TEXT NOT NULL,
    funcao_pai     TEXT,             -- só quando a conferência da soma fechou
    coletado_em    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_siconfi_conta ON siconfi_linha(conta);
CREATE INDEX IF NOT EXISTS ix_siconfi_periodo
    ON siconfi_linha(demonstrativo, exercicio, periodo);

CREATE TABLE IF NOT EXISTS pncp_documento (
    id                   INTEGER PRIMARY KEY,
    tipo                 TEXT NOT NULL,
    numero_controle_pncp TEXT,
    orgao_nome           TEXT,
    orgao_cnpj           TEXT,
    unidade_nome         TEXT,
    ano                  TEXT,
    titulo               TEXT,
    descricao            TEXT,
    modalidade           TEXT,
    situacao             TEXT,
    data_publicacao      TEXT,
    data_assinatura      TEXT,
    data_inicio_vigencia TEXT,
    data_fim_vigencia    TEXT,
    valor_global         REAL,
    cancelado            INTEGER,
    item_url             TEXT,
    coletado_em          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patrimonio_bem (
    id                     INTEGER PRIMARY KEY,
    plaqueta               TEXT,      -- NÃO identifica: 1.600 se repetem
    item                   TEXT,
    unidade                TEXT,
    centro_custo           TEXT,
    localizacao            TEXT,
    fornecedor             TEXT,
    data_posse             TEXT,
    valor_atual            REAL,
    tipo                   TEXT,
    situacao               TEXT,
    tipo_baixa             TEXT,
    data_baixa             TEXT,
    classificador_numero   TEXT,
    classificador_descricao TEXT,
    estado_conservacao     TEXT,
    coletado_em            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_patrimonio_forn ON patrimonio_bem(fornecedor);

CREATE TABLE IF NOT EXISTS obra (
    id           INTEGER PRIMARY KEY,
    exercicio    INTEGER,
    dados        TEXT NOT NULL,   -- o registro cru; o formato varia por ano
    coletado_em  TEXT NOT NULL
);

-- O mapa do portal. Serve de índice do que EXISTE mas não está neste acervo —
-- é o insumo da ferramenta de pontos cegos.
CREATE TABLE IF NOT EXISTS portal_tela (
    id           INTEGER PRIMARY KEY,
    serv         INTEGER,
    categoria    TEXT,
    descricao    TEXT,
    link         TEXT,
    no_acervo    INTEGER NOT NULL DEFAULT 0,
    coletado_em  TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS busca USING fts5(
    texto, tabela UNINDEXED, ref UNINDEXED, tokenize = "unicode61 remove_diacritics 2"
);
"""


def _manifesto(fonte: str) -> dict[str, dict]:
    """Última coleta de cada arquivo, pela data — o manifesto é append-only."""
    caminho = BRUTOS / fonte / "manifesto.jsonl"
    ultimo: dict[str, dict] = {}
    if not caminho.exists():
        return ultimo
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        reg = json.loads(linha)
        anterior = ultimo.get(reg["arquivo"])
        if anterior is None or reg["coletado_em"] >= anterior["coletado_em"]:
            ultimo[reg["arquivo"]] = reg
    return ultimo


def _classificar_niveis(linhas: list[dict]) -> None:
    """Deriva função/subfunção pela ordem e confere pela soma.

    A derivação sozinha não basta: ela diz que 'Saúde' é função, mas não prova
    que as sete linhas seguintes são filhas dela. A conferência é a soma — se
    o valor da função bate com a soma das subfunções até a próxima função, o
    vínculo está provado e `funcao_pai` é preenchido. Não batendo, o nível fica
    'indefinido' e o pai fica nulo: melhor lacuna declarada que vínculo inventado.
    """
    funcao_atual: dict | None = None
    filhas: list[dict] = []

    def fechar() -> None:
        if funcao_atual is None:
            return
        soma = sum(f["valor"] or 0 for f in filhas)
        alvo = funcao_atual["valor"] or 0
        # Tolerância de centavos: os valores vêm arredondados na origem.
        if filhas and abs(soma - alvo) < 0.05 * max(abs(alvo), 1) and abs(soma - alvo) < 1000:
            for f in filhas:
                f["nivel"] = "subfuncao"
                f["funcao_pai"] = funcao_atual["conta"]
        else:
            for f in filhas:
                f["nivel"] = "indefinido"

    for linha in linhas:
        linha.setdefault("nivel", "indefinido")
        linha.setdefault("funcao_pai", None)
        if linha["conta"] in FUNCOES_DE_GOVERNO:
            fechar()
            funcao_atual, filhas = linha, []
            linha["nivel"] = "funcao"
        elif funcao_atual is not None:
            filhas.append(linha)
    fechar()


def ingerir_siconfi(con: sqlite3.Connection) -> int:
    manifesto = _manifesto("siconfi")
    total = 0
    for arq in sorted((BRUTOS / "siconfi").glob("*.json")):
        itens = json.loads(arq.read_text(encoding="utf-8")).get("items", [])
        if not itens:
            continue
        # Carimbo do demonstrativo: o RGF não o traz no payload.
        demonstrativo = re.match(r"([a-z]+)_", arq.name).group(1).upper()
        coletado = manifesto.get(arq.name, {}).get("coletado_em", "desconhecido")

        # A classificação é por (anexo, coluna): a ordem só tem sentido dentro
        # de uma mesma coluna do mesmo anexo.
        blocos: dict[tuple, list[dict]] = {}
        for pos, it in enumerate(itens):
            it["_ordem"] = pos
            blocos.setdefault((it.get("anexo"), it.get("coluna"), it.get("rotulo")), []).append(it)
        for bloco in blocos.values():
            _classificar_niveis(bloco)

        con.executemany(
            """INSERT INTO siconfi_linha
               (arquivo, demonstrativo, exercicio, periodo, periodicidade, co_poder,
                anexo, rotulo, coluna, cod_conta, conta, valor, ordem, nivel,
                funcao_pai, coletado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(arq.name, demonstrativo, it.get("exercicio"), it.get("periodo"),
              it.get("periodicidade"), it.get("co_poder"), it.get("anexo"),
              it.get("rotulo"), it.get("coluna"), it.get("cod_conta"), it.get("conta"),
              it.get("valor"), it["_ordem"], it["nivel"], it.get("funcao_pai"),
              coletado) for it in itens])
        total += len(itens)
    return total


def ingerir_pncp(con: sqlite3.Connection) -> int:
    manifesto = _manifesto("pncp")
    total = 0
    for arq in sorted((BRUTOS / "pncp").glob("*.json")):
        itens = json.loads(arq.read_text(encoding="utf-8"))
        coletado = manifesto.get(arq.name, {}).get("coletado_em", "desconhecido")
        con.executemany(
            """INSERT INTO pncp_documento
               (tipo, numero_controle_pncp, orgao_nome, orgao_cnpj, unidade_nome, ano,
                titulo, descricao, modalidade, situacao, data_publicacao,
                data_assinatura, data_inicio_vigencia, data_fim_vigencia,
                valor_global, cancelado, item_url, coletado_em)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(arq.stem, i.get("numero_controle_pncp"), i.get("orgao_nome"),
              i.get("orgao_cnpj"), i.get("unidade_nome"), i.get("ano"), i.get("title"),
              i.get("description"), i.get("modalidade_licitacao_nome"),
              i.get("situacao_nome"), i.get("data_publicacao_pncp"),
              i.get("data_assinatura"), i.get("data_inicio_vigencia"),
              i.get("data_fim_vigencia"), i.get("valor_global"),
              1 if i.get("cancelado") else 0, i.get("item_url"), coletado)
             for i in itens])
        total += len(itens)
    return total


def ingerir_patrimonio(con: sqlite3.Connection) -> int:
    arq = BRUTOS / "portal" / "patrimonio.json"
    if not arq.exists():
        return 0
    coletado = _manifesto("portal").get(arq.name, {}).get("coletado_em", "desconhecido")
    itens = json.loads(arq.read_text(encoding="utf-8")).get("dados", [])

    def num(v):
        if v in (None, ""):
            return None
        try:
            return float(str(v).replace(".", "").replace(",", ".")) if isinstance(v, str) else float(v)
        except ValueError:
            return None

    con.executemany(
        """INSERT INTO patrimonio_bem
           (plaqueta, item, unidade, centro_custo, localizacao, fornecedor,
            data_posse, valor_atual, tipo, situacao, tipo_baixa, data_baixa,
            classificador_numero, classificador_descricao, estado_conservacao,
            coletado_em) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [((i.get("BEN_PLAQUETA") or "").strip(), i.get("ITE_NOME"), i.get("UNI_NOME"),
          i.get("CENTRO_CUSTO"), i.get("LOC_DESCRICAO"), i.get("FORNECEDOR"),
          i.get("BEN_DATA_POSSE"), num(i.get("VALOR_ATUAL")), i.get("TIPO"),
          i.get("SITUACAO"), i.get("TIPO_BAIXA"), i.get("BAI_DATA"),
          i.get("CLASSIFICADOR_NUMERO"), i.get("CLASSIFICADOR_DESCRICAO"),
          i.get("ESTADO_CONSERVACAO"), coletado) for i in itens])
    return len(itens)


def ingerir_obras_e_mapa(con: sqlite3.Connection) -> tuple[int, int]:
    manifesto = _manifesto("portal")
    obras = 0
    for arq in sorted((BRUTOS / "portal").glob("obras_*.json")):
        coletado = manifesto.get(arq.name, {}).get("coletado_em", "desconhecido")
        exercicio = int(arq.stem.split("_")[-1])
        itens = json.loads(arq.read_text(encoding="utf-8")).get("dados", [])
        con.executemany("INSERT INTO obra (exercicio, dados, coletado_em) VALUES (?,?,?)",
                        [(exercicio, json.dumps(i, ensure_ascii=False), coletado) for i in itens])
        obras += len(itens)

    arq = BRUTOS / "portal" / "busca_avancada.json"
    telas = 0
    if arq.exists():
        coletado = manifesto.get(arq.name, {}).get("coletado_em", "desconhecido")
        vistos = set()
        registros = []
        for i in json.loads(arq.read_text(encoding="utf-8")).get("dados", []):
            link = i.get("link_sitemap") or ""
            m = re.search(r"transparencia\.mesquita\.rj\.gov\.br/\?serv=(\d+)$", link)
            serv = int(m.group(1)) if m else None
            chave = (serv, link, i.get("Descricao"))
            if chave in vistos:
                continue
            vistos.add(chave)
            desc = re.sub(r"<[^>]+>", "", (i.get("Descricao") or "").replace("&nbsp;", " ")).strip()
            registros.append((serv, i.get("Categoria"), desc, link, coletado))
        con.executemany(
            """INSERT INTO portal_tela (serv, categoria, descricao, link, coletado_em)
               VALUES (?,?,?,?,?)""", registros)
        telas = len(registros)
    return obras, telas


def indexar_busca(con: sqlite3.Connection) -> None:
    con.execute("DELETE FROM busca")
    con.execute("""INSERT INTO busca (texto, tabela, ref)
                   SELECT coalesce(titulo,'') || ' ' || coalesce(descricao,''),
                          'pncp_documento', id FROM pncp_documento""")
    con.execute("""INSERT INTO busca (texto, tabela, ref)
                   SELECT coalesce(item,'') || ' ' || coalesce(fornecedor,'') || ' ' ||
                          coalesce(classificador_descricao,''),
                          'patrimonio_bem', id FROM patrimonio_bem""")
    con.execute("""INSERT INTO busca (texto, tabela, ref)
                   SELECT coalesce(categoria,'') || ' ' || coalesce(descricao,''),
                          'portal_tela', id FROM portal_tela""")


def main() -> None:
    BANCO.parent.mkdir(parents=True, exist_ok=True)
    if BANCO.exists():
        BANCO.unlink()
    con = sqlite3.connect(BANCO)
    con.executescript(ESQUEMA)

    for fonte in ("siconfi", "pncp", "portal"):
        for reg in _manifesto(fonte).values():
            con.execute("INSERT OR REPLACE INTO coleta VALUES (?,?,?,?,?)",
                        (fonte, reg["arquivo"], reg["url"], reg["coletado_em"], reg["sha256"]))

    n_sic = ingerir_siconfi(con)
    # Só depois de tudo ingerido dá para saber quais anexos têm hierarquia.
    con.execute("""UPDATE siconfi_linha SET nivel = 'fora_de_hierarquia'
                   WHERE nivel = 'indefinido' AND anexo NOT IN
                     (SELECT DISTINCT anexo FROM siconfi_linha WHERE nivel = 'funcao')""")
    n_pncp = ingerir_pncp(con)
    n_pat = ingerir_patrimonio(con)
    n_obr, n_tel = ingerir_obras_e_mapa(con)
    indexar_busca(con)
    con.commit()

    print(f"siconfi_linha    {n_sic:>8,}".replace(",", "."))
    print(f"pncp_documento   {n_pncp:>8,}".replace(",", "."))
    print(f"patrimonio_bem   {n_pat:>8,}".replace(",", "."))
    print(f"obra             {n_obr:>8,}".replace(",", "."))
    print(f"portal_tela      {n_tel:>8,}".replace(",", "."))

    niveis = con.execute("""SELECT nivel, count(*) FROM siconfi_linha
                            GROUP BY nivel ORDER BY 2 DESC""").fetchall()
    print("\nclassificação de nível no SICONFI:")
    for nivel, n in niveis:
        print(f"  {nivel:<12} {n:>8,}".replace(",", "."))
    con.close()
    print(f"\n{BANCO} — {BANCO.stat().st_size/1024/1024:.1f} MB")


if __name__ == "__main__":
    main()
