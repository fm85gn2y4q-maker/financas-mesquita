"""Ingere os relatórios "Dados Abertos" do portal no acervo.

A DECISÃO DE ESQUEMA, E POR QUE ELA É ESTA:

**Nenhum destes CSV traz cabeçalho.** Medido nos 85 arquivos coletados: a
primeira linha é dado, sempre. E a largura varia dentro do mesmo relatório —
a despesa tem 34 colunas em 30.685 linhas, 17 em dez e 2 em seis.

Sem cabeçalho, nomear coluna por posição é chutar. E chute aqui não produz
lacuna, produz **erro de atribuição**: uma coluna rotulada "valor" que na
verdade é outra coisa sai bem formatada, passa em qualquer teste de contagem e
entra numa peça. É exatamente o risco que este acervo existe para evitar.

Por isso a linha é guardada **posicional e sem nome**, e o servidor é obrigado
a dizer isso a quem perguntar. O que se pode afirmar sem inventar nada é o que
se prova pelo formato do próprio conteúdo — CNPJ tem 14 dígitos, data tem
dd/mm/aaaa, link começa com https. Esses campos são derivados por padrão, não
por posição, e ficam à parte, marcados como derivados.

Uso:  python ingerir_relatorios.py
"""

from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BRUTOS = RAIZ / "dados_brutos" / "portal_relatorios"
BANCO = RAIZ / "dados" / "acervo.db"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS relatorio_linha (
    id          INTEGER PRIMARY KEY,
    regra       TEXT NOT NULL,   -- a regra do portal que gerou o arquivo
    exercicio   INTEGER,         -- NULL = chamada sem filtro de ano
    arquivo     TEXT NOT NULL,
    ordem       INTEGER NOT NULL,
    n_colunas   INTEGER NOT NULL,
    -- Vetor posicional. NÃO há nome de coluna: o portal não o exporta.
    colunas     TEXT NOT NULL,
    coletado_em TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rel_regra ON relatorio_linha(regra, exercicio);

-- Campos DERIVADOS do conteúdo, por formato — não por posição. Só entram aqui
-- os que o próprio texto prova: CNPJ/CPF pelo tamanho e dígitos, data pelo
-- padrão, link pelo esquema. Cada um guarda a POSIÇÃO de onde saiu, para que
-- se possa conferir na linha crua.
CREATE TABLE IF NOT EXISTS relatorio_derivado (
    linha_id  INTEGER NOT NULL REFERENCES relatorio_linha(id),
    campo     TEXT NOT NULL,     -- 'cnpj_cpf' | 'data' | 'url' | 'valor'
    valor     TEXT NOT NULL,
    posicao   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_der_campo ON relatorio_derivado(campo, valor);
CREATE INDEX IF NOT EXISTS ix_der_linha ON relatorio_derivado(linha_id);

CREATE VIRTUAL TABLE IF NOT EXISTS relatorio_fts USING fts5(
    texto, content='', tokenize="unicode61 remove_diacritics 2"
);
"""

# CPF/CNPJ com ou sem pontuação. O portal escreve dos dois jeitos, e no mesmo
# acervo: em `contratos` sai `33683111000107`, na despesa sai
# `26.651.036/0001-29`. A primeira versão daqui exigia dígitos puros e derivou
# 13.994 documentos em 2,9 milhões de linhas — `pagamentos_a` ficava cego
# justamente na despesa, que é onde está o pagamento.
#
# O valor guardado é sempre só os dígitos, para que a busca não dependa da
# forma como o portal escreveu naquela tela.
DOC = re.compile(r"^[\s.]*(\d{3}\.?\d{3}\.?\d{3}-?\d{2}"
                 r"|\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2})[\s.]*$")
DATA = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})\s*$")
URL = re.compile(r"^\s*(https?://\S+)\s*$")
# Valor em formato brasileiro: 1.234.567,89 — exige a vírgula decimal, para não
# capturar número de processo nem código.
VALOR = re.compile(r"^\s*-?\d{1,3}(?:\.\d{3})*,\d{2}\s*$")


def _derivados(colunas: list[str]):
    for pos, bruto in enumerate(colunas):
        v = (bruto or "").strip()
        if not v:
            continue
        if m := DATA.match(v):
            yield "data", m.group(1), pos
        elif m := URL.match(v):
            yield "url", m.group(1), pos
        elif VALOR.match(v):
            yield "valor", v, pos
        elif m := DOC.match(v):
            yield "cnpj_cpf", re.sub(r"\D", "", m.group(1)), pos


def _manifesto() -> dict[str, str]:
    caminho = BRUTOS / "manifesto.jsonl"
    ultimo: dict[str, str] = {}
    if not caminho.exists():
        return ultimo
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if linha.strip():
            r = json.loads(linha)
            if r["coletado_em"] >= ultimo.get(r["arquivo"], ""):
                ultimo[r["arquivo"]] = r["coletado_em"]
    return ultimo


def main() -> None:
    if not BANCO.exists():
        raise SystemExit("Rode `python construir_acervo.py` antes.")
    con = sqlite3.connect(BANCO)
    con.executescript(ESQUEMA)
    con.execute("DELETE FROM relatorio_derivado")
    con.execute("DELETE FROM relatorio_linha")
    con.execute("DELETE FROM relatorio_fts")

    manifesto = _manifesto()
    total = derivados = 0

    for arq in sorted(BRUTOS.glob("*.json")):
        nome = arq.stem
        m = re.search(r"_(\d{4})$", nome)
        exercicio = int(m.group(1)) if m else None
        regra = re.sub(r"_\d{4}$", "", nome)
        coletado = manifesto.get(arq.name, "desconhecido")

        # Em lotes, e não de uma vez: o maior arquivo tem 126 MB, e uma lista
        # de listas com o CSV inteiro mais as cópias em JSON passaria de um
        # gigabyte de memória por arquivo. O ganho de velocidade de fazer tudo
        # junto não paga o risco de morrer no meio da ingestão.
        texto = arq.read_bytes().decode("latin-1")
        leitor = csv.reader(io.StringIO(texto))
        do_arquivo = 0
        lote: list[tuple] = []

        def descarregar() -> None:
            nonlocal lote, total, derivados
            if not lote:
                return
            con.executemany(
                """INSERT INTO relatorio_linha
                   (regra, exercicio, arquivo, ordem, n_colunas, colunas,
                    coletado_em) VALUES (?,?,?,?,?,?,?)""", lote)
            primeiro = con.execute(
                "SELECT max(id) - ? + 1 FROM relatorio_linha",
                (len(lote),)).fetchone()[0]
            deriv, fts = [], []
            for i, reg in enumerate(lote):
                lid = primeiro + i
                cols = json.loads(reg[5])
                for campo, valor, pos in _derivados(cols):
                    deriv.append((lid, campo, valor, pos))
                fts.append((lid, " ".join(c for c in cols if c)))
            con.executemany("INSERT INTO relatorio_derivado VALUES (?,?,?,?)", deriv)
            con.executemany(
                "INSERT INTO relatorio_fts(rowid, texto) VALUES (?,?)", fts)
            total += len(lote)
            derivados += len(deriv)
            lote = []

        for ordem, cols in enumerate(leitor):
            if not any((c or "").strip() for c in cols):
                continue
            lote.append((regra, exercicio, arq.name, ordem, len(cols),
                         json.dumps(cols, ensure_ascii=False), coletado))
            do_arquivo += 1
            if len(lote) >= 20_000:
                descarregar()
                con.commit()
        descarregar()
        con.commit()
        del texto
        print(f"  {nome:<52} {do_arquivo:>8} linhas")

    con.commit()
    print(f"\nrelatorio_linha    {total:>10,}".replace(",", "."))
    print(f"relatorio_derivado {derivados:>10,}".replace(",", "."))
    for campo, n in con.execute(
            "SELECT campo, count(*) FROM relatorio_derivado GROUP BY campo ORDER BY 2 DESC"):
        print(f"   {campo:<12} {n:>10,}".replace(",", "."))
    con.close()
    print(f"\n{BANCO} — {BANCO.stat().st_size / 1048576:.0f} MB")


if __name__ == "__main__":
    main()
