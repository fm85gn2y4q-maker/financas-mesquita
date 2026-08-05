"""Recalcula `relatorio_derivado` a partir do que já está no banco.

Os derivados saem das colunas, e as colunas já estão em `relatorio_linha` — não
é preciso reler 750 MB de CSV para corrigir a extração. Este script existe
porque a regra de CPF/CNPJ estava exigindo dígitos puros e perdia todo documento
escrito com pontuação, que é como a despesa o escreve.

Imprime o diff: quanto havia antes, quanto há depois, e por campo.

Uso:  python rederivar.py
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ingerir_relatorios import _derivados

BANCO = Path(__file__).resolve().parent / "dados" / "acervo.db"


def main() -> None:
    con = sqlite3.connect(BANCO)
    antes = dict(con.execute(
        "SELECT campo, count(*) FROM relatorio_derivado GROUP BY campo"))
    print("antes:", {k: f"{v:,}".replace(",", ".") for k, v in antes.items()})

    con.execute("DELETE FROM relatorio_derivado")
    total = 0
    lote: list[tuple] = []
    for lid, colunas in con.execute(
            "SELECT id, colunas FROM relatorio_linha ORDER BY id"):
        for campo, valor, pos in _derivados(json.loads(colunas)):
            lote.append((lid, campo, valor, pos))
        if len(lote) >= 100_000:
            con.executemany("INSERT INTO relatorio_derivado VALUES (?,?,?,?)", lote)
            total += len(lote)
            lote = []
    if lote:
        con.executemany("INSERT INTO relatorio_derivado VALUES (?,?,?,?)", lote)
        total += len(lote)
    con.commit()

    depois = dict(con.execute(
        "SELECT campo, count(*) FROM relatorio_derivado GROUP BY campo"))
    print("depois:", {k: f"{v:,}".replace(",", ".") for k, v in depois.items()})
    print("\ndiferença por campo:")
    for campo in sorted(set(antes) | set(depois)):
        d = depois.get(campo, 0) - antes.get(campo, 0)
        print(f"  {campo:<12} {d:+,}".replace(",", "."))

    docs = con.execute(
        "SELECT count(DISTINCT valor) FROM relatorio_derivado "
        "WHERE campo='cnpj_cpf'").fetchone()[0]
    print(f"\ndocumentos distintos: {docs:,}".replace(",", "."))
    con.close()


if __name__ == "__main__":
    main()
