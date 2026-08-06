"""Carrega `colunas.json` na tabela `relatorio_coluna` do acervo.

O mapeamento é conferido à mão, e é assim de propósito. A tentativa de deduzi-lo
sozinho — gerar o mesmo relatório em PDF e casar rótulo com posição pelo valor —
está em `nomear_colunas.py` e NÃO chegou a resultado confiável: o PDF expõe
cerca de metade dos campos, e as datas de um contrato (assinatura, início,
vencimento, publicação) têm a mesma forma e às vezes o mesmo valor, de modo que
o casamento por valor nomeava a coluna errada com aparência perfeita. Três
versões depois, a cobertura era de 3 colunas em 23. Está registrado ali.

O que ficou de útil daquela via: o PDF, que deu os rótulos oficiais, e
`perfilar_colunas.py`, que confere qualquer rótulo proposto contra o conteúdo
real da coluna.

Uso:  python carregar_colunas.py
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
# Respeita ACERVO_DB, como o servidor: o núcleo publicado é outro arquivo, e
# carregar duas vezes no mesmo banco por engano é fácil de não perceber.
BANCO = Path(os.environ.get("ACERVO_DB") or RAIZ / "dados" / "acervo.db")
MAPA = RAIZ / "colunas.json"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS relatorio_coluna (
    regra      TEXT NOT NULL,
    posicao    INTEGER NOT NULL,
    rotulo     TEXT NOT NULL,
    origem     TEXT NOT NULL,
    PRIMARY KEY (regra, posicao)
);
CREATE TABLE IF NOT EXISTS relatorio_coluna_indefinida (
    regra    TEXT NOT NULL,
    posicao  INTEGER NOT NULL,
    motivo   TEXT NOT NULL,
    PRIMARY KEY (regra, posicao)
);
"""


def main() -> None:
    if not BANCO.exists():
        raise SystemExit("Rode `python construir_acervo.py` antes.")
    dados = json.loads(MAPA.read_text(encoding="utf-8"))
    con = sqlite3.connect(BANCO)
    # A tabela pode existir da tentativa automática, com outro formato.
    con.execute("DROP TABLE IF EXISTS relatorio_coluna")
    con.executescript(ESQUEMA)

    for regra, bloco in dados.items():
        if regra.startswith("_"):
            continue
        colunas = bloco.get("colunas", {})
        con.executemany(
            "INSERT OR REPLACE INTO relatorio_coluna VALUES (?,?,?,?)",
            [(regra, int(pos), rotulo, bloco.get("_fonte", "conferido"))
             for pos, rotulo in colunas.items()])
        indefinidas = bloco.get("_nao_determinado", {})
        con.executemany(
            "INSERT OR REPLACE INTO relatorio_coluna_indefinida VALUES (?,?,?)",
            [(regra, int(pos), motivo) for pos, motivo in indefinidas.items()])
        print(f"{regra:<40} {len(colunas):>3} nomeadas, "
              f"{len(indefinidas):>2} declaradamente indefinidas")

    con.commit()
    con.close()


if __name__ == "__main__":
    main()
