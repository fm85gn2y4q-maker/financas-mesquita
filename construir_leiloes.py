"""dados_brutos/leiloesbr/ → dados/leiloes.db

Mesma divisão do acervo financeiro: coletar não interpreta, construir não vai
à rede. Este script lê o cru gravado pelo coletor, identifica cada lote e monta
o banco que o servidor MCP serve.

A identificação roda AQUI, e não na coleta, de propósito. As regras de
identificação mudam — cada armadilha nova descoberta em `armadilhas.json` é uma
regra a mais —, e quando mudam é preciso reprocessar o acervo inteiro sem
voltar à rede. Se a identificação tivesse ficado no coletor, toda correção de
regra custaria uma nova varredura de milhares de páginas.

O contrato do arquivo cru está em `coletar_leiloesbr.py`.

Uso:  python construir_leiloes.py
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections import Counter
from pathlib import Path

from leiloes.identificacao import identificar

RAIZ = Path(__file__).resolve().parent
BRUTOS = RAIZ / "dados_brutos" / "leiloesbr"
DESTINO = RAIZ / "dados" / "leiloes.db"

ESQUEMA = """
CREATE TABLE casa (
    id            TEXT PRIMARY KEY,   -- slug do nome, estável entre coletas
    nome          TEXT NOT NULL,
    site          TEXT,
    cidade        TEXT,
    uf            TEXT
);

CREATE TABLE leilao (
    id            TEXT PRIMARY KEY,   -- id do próprio portal
    casa_id       TEXT REFERENCES casa(id),
    titulo        TEXT,
    data_pregao   TEXT,               -- ISO, YYYY-MM-DD
    url           TEXT,
    total_lotes   INTEGER,
    coletado_em   TEXT NOT NULL
);

CREATE TABLE lote (
    id            INTEGER PRIMARY KEY,
    leilao_id     TEXT REFERENCES leilao(id),
    numero        INTEGER,
    titulo        TEXT NOT NULL,
    descricao     TEXT,
    url           TEXT,
    foto_url      TEXT,
    lance_inicial REAL,
    estimativa_min REAL,
    estimativa_max REAL,
    -- aberto | arrematado | nao_arrematado | retirado
    situacao      TEXT NOT NULL,
    preco_martelo REAL,
    data_resultado TEXT,
    coletado_em   TEXT NOT NULL,
    UNIQUE (leilao_id, numero)
);

-- A peça que o lote É, quando a descrição determina.
CREATE TABLE identificacao (
    lote_id       INTEGER PRIMARY KEY REFERENCES lote(id),
    chave         TEXT NOT NULL,      -- peça + estado; é por ela que se compara
    confianca     TEXT NOT NULL,      -- firme | provavel
    especie       TEXT,
    catalogo      TEXT,
    codigo        TEXT,
    ano           INTEGER,
    denominacao   TEXT,
    metal         TEXT,
    estado        TEXT,               -- grau (moeda/cédula) ou goma (selo)
    certificadora TEXT,
    nota_certificada INTEGER,
    ressalva      TEXT
);

-- O lote que a descrição NÃO determina. Existe como tabela própria, e não como
-- ausência na tabela acima, pelo mesmo motivo que `nivel='indefinido'` existe
-- no acervo financeiro: sem ela, o lote não identificado some do acervo e a
-- lacuna passa por inexistência. São estes os lotes que exigem olho humano.
CREATE TABLE identificacao_indefinida (
    lote_id       INTEGER PRIMARY KEY REFERENCES lote(id),
    motivo        TEXT NOT NULL,
    desarma_com   TEXT                -- JSON: termos que resolveriam a dúvida
);

CREATE INDEX ix_identificacao_chave ON identificacao(chave);
CREATE INDEX ix_lote_situacao ON lote(situacao);
CREATE INDEX ix_lote_leilao ON lote(leilao_id);

CREATE VIRTUAL TABLE lote_fts USING fts5(
    titulo, descricao, content='lote', content_rowid='id', tokenize='unicode61'
);

-- Frequência de cada termo do acervo. Serve a uma coisa só: achar o lote cuja
-- grafia divergiu do resto do catálogo. O lote com "Reís" no lugar de "Réis"
-- não aparece na busca de ninguém, e é exatamente ali que mora o lance baixo.
CREATE TABLE vocabulario (
    token         TEXT PRIMARY KEY,
    ocorrencias   INTEGER NOT NULL
);

CREATE TABLE coleta (
    chave         TEXT PRIMARY KEY,
    valor         TEXT
);
"""


def slug(nome: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", nome or "")
                         if unicodedata.category(c) != "Mn")
    return "-".join(sem_acento.lower().split()) or "sem-nome"


def _tokens(texto: str) -> list[str]:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto or "")
                         if unicodedata.category(c) != "Mn").lower()
    return [t for t in "".join(c if c.isalnum() else " " for c in sem_acento).split()
            if len(t) >= 4 and not t.isdigit()]


def construir() -> None:
    arquivos = sorted(BRUTOS.glob("leilao-*.json"))
    if not arquivos:
        raise SystemExit(
            f"Nada em {BRUTOS}. Rode `python coletar_leiloesbr.py` antes — e veja "
            f"`python descobrir_leiloesbr.py` se for a primeira vez nesta máquina.")

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    if DESTINO.exists():
        DESTINO.unlink()
    con = sqlite3.connect(DESTINO)
    con.executescript(ESQUEMA)

    vocabulario: Counter[str] = Counter()
    lote_id = 0
    firmes = provaveis = indefinidos = 0

    for arquivo in arquivos:
        dados = json.loads(arquivo.read_text(encoding="utf-8"))
        leilao = dados["leilao"]
        coletado_em = dados.get("coletado_em") or leilao.get("coletado_em")

        casa_id = slug(leilao.get("casa", ""))
        con.execute("INSERT OR IGNORE INTO casa VALUES (?,?,?,?,?)",
                    (casa_id, leilao.get("casa"), leilao.get("casa_site"),
                     leilao.get("cidade"), leilao.get("uf")))
        con.execute("INSERT OR REPLACE INTO leilao VALUES (?,?,?,?,?,?,?)",
                    (str(leilao["id"]), casa_id, leilao.get("titulo"),
                     leilao.get("data_pregao"), leilao.get("url"),
                     len(dados["lotes"]), coletado_em))

        for bruto in dados["lotes"]:
            lote_id += 1
            titulo = bruto.get("titulo") or ""
            descricao = bruto.get("descricao") or ""
            con.execute(
                "INSERT OR REPLACE INTO lote VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lote_id, str(leilao["id"]), bruto.get("numero"), titulo, descricao,
                 bruto.get("url"), bruto.get("foto_url"), bruto.get("lance_inicial"),
                 bruto.get("estimativa_min"), bruto.get("estimativa_max"),
                 bruto.get("situacao") or "aberto", bruto.get("preco_martelo"),
                 bruto.get("data_resultado"), bruto.get("coletado_em") or coletado_em))

            vocabulario.update(_tokens(f"{titulo} {descricao}"))

            peca = identificar(titulo, descricao)
            if peca["confianca"] == "indefinida":
                indefinidos += 1
                con.execute("INSERT OR REPLACE INTO identificacao_indefinida "
                            "VALUES (?,?,?)",
                            (lote_id, peca["motivo"],
                             json.dumps(peca.get("desarma_com") or [],
                                        ensure_ascii=False)))
                continue

            firmes += peca["confianca"] == "firme"
            provaveis += peca["confianca"] == "provavel"
            codigo = peca["codigos"][0] if peca["codigos"] else {}
            con.execute(
                "INSERT OR REPLACE INTO identificacao VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (lote_id, peca["chave"], peca["confianca"], peca["especie"],
                 codigo.get("catalogo"), codigo.get("codigo"),
                 peca["anos"][0] if peca["anos"] else None,
                 peca["denominacao"], peca["metal"], peca["estado"],
                 peca["certificadora"], peca["nota_certificada"], peca["motivo"]))

    con.executemany("INSERT INTO vocabulario VALUES (?,?)", vocabulario.items())
    con.execute("INSERT INTO lote_fts(rowid, titulo, descricao) "
                "SELECT id, titulo, descricao FROM lote")
    con.execute("INSERT OR REPLACE INTO coleta VALUES ('construido_em', datetime('now'))")
    con.execute("INSERT OR REPLACE INTO coleta VALUES ('arquivos_lidos', ?)",
                (str(len(arquivos)),))
    con.commit()

    total = firmes + provaveis + indefinidos
    arrematados = con.execute(
        "SELECT count(*) FROM lote WHERE situacao='arrematado' "
        "AND preco_martelo IS NOT NULL").fetchone()[0]
    comparaveis = con.execute(
        """SELECT count(DISTINCT i.chave) FROM identificacao i
           JOIN lote l ON l.id = i.lote_id
           WHERE l.situacao='arrematado' AND l.preco_martelo IS NOT NULL""").fetchone()[0]

    print(f"leilões          {len(arquivos):>7}")
    print(f"lotes            {total:>7}")
    print(f"  identificados  {firmes + provaveis:>7}  "
          f"({firmes} firmes, {provaveis} prováveis)")
    print(f"  indefinidos    {indefinidos:>7}  "
          f"({100 * indefinidos / total:.0f}% — exigem leitura humana)")
    print(f"martelos gravados{arrematados:>7}")
    print(f"peças comparáveis{comparaveis:>7}  (chaves distintas com martelo)")
    print(f"\n{DESTINO}")
    con.close()


if __name__ == "__main__":
    construir()
