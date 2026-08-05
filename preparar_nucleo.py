"""Monta `dados/nucleo.db` — o recorte publicável do acervo.

O acervo inteiro tem 2,8 GB e não cabe numa release única. O corte segue o peso
medido: a folha nominal (5 variantes) são 1.826.424 linhas e 457 MB de texto, e
`Programa Projeto Ação` outras 669.527 linhas e 253 MB — juntas, 86% do volume.
Fora elas sobram 409.149 linhas e 109 MB, que é onde está o que se pergunta no
dia a dia: despesa nota a nota com favorecido e CNPJ, contratos, receita,
editais, dispensas, diárias, cargos e obras, mais SICONFI, PNCP e patrimônio.

O núcleo NÃO é um acervo diferente: é o mesmo esquema, com menos linhas. Por
isso o servidor não precisa saber qual dos dois abriu — `cobertura_do_acervo`
lista o que existe, e `pontos_cegos` declara o que ficou de fora.

Uso:  python preparar_nucleo.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
COMPLETO = RAIZ / "dados" / "acervo.db"
NUCLEO = RAIZ / "dados" / "nucleo.db"

# O que fica de fora, por volume. Casado contra `regra`, que é o nome do
# arquivo coletado — não contra o nome da regra do portal.
FORA = ("%servidoresxbrutoxliquido%", "%programa_projeto%")

# Tabelas copiadas inteiras.
INTEIRAS = ("coleta", "siconfi_linha", "pncp_documento", "patrimonio_bem",
            "obra", "portal_tela")


def main() -> None:
    if not COMPLETO.exists():
        raise SystemExit(f"acervo não encontrado: {COMPLETO}")
    NUCLEO.unlink(missing_ok=True)

    con = sqlite3.connect(NUCLEO)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute(f"ATTACH DATABASE '{COMPLETO.as_posix()}' AS cheio")

    # Recria o esquema exatamente como está no acervo completo, para que o
    # servidor não precise distinguir os dois.
    for (sql,) in con.execute(
            "SELECT sql FROM cheio.sqlite_master WHERE sql IS NOT NULL "
            "AND name NOT LIKE 'sqlite_%'"):
        try:
            con.execute(sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                print(f"  aviso ao recriar: {e}")

    for tabela in INTEIRAS:
        con.execute(f"INSERT INTO {tabela} SELECT * FROM cheio.{tabela}")
        n = con.execute(f"SELECT count(*) FROM {tabela}").fetchone()[0]
        print(f"  {tabela:<22} {n:>10,}".replace(",", "."))

    condicao = " AND ".join(f"regra NOT LIKE '{p}'" for p in FORA)
    con.execute(f"INSERT INTO relatorio_linha SELECT * FROM cheio.relatorio_linha "
                f"WHERE {condicao}")
    n = con.execute("SELECT count(*) FROM relatorio_linha").fetchone()[0]
    print(f"  {'relatorio_linha':<22} {n:>10,}".replace(",", "."))

    con.execute("""INSERT INTO relatorio_derivado
                   SELECT d.* FROM cheio.relatorio_derivado d
                   JOIN relatorio_linha l ON l.id = d.linha_id""")
    n = con.execute("SELECT count(*) FROM relatorio_derivado").fetchone()[0]
    print(f"  {'relatorio_derivado':<22} {n:>10,}".replace(",", "."))

    # O FTS é de conteúdo externo (`content=''`): não se copia com SELECT *,
    # tem de ser reindexado a partir das linhas que sobraram.
    print("  reindexando a busca…")
    con.execute("DELETE FROM relatorio_fts")
    con.execute("""INSERT INTO relatorio_fts(rowid, texto)
                   SELECT id, replace(replace(replace(colunas,'","',' '),
                                              '["',''), '"]','')
                   FROM relatorio_linha""")
    con.execute("DELETE FROM busca")
    con.execute("INSERT INTO busca(texto, tabela, ref) "
                "SELECT texto, tabela, ref FROM cheio.busca")

    con.commit()
    con.execute("DETACH DATABASE cheio")
    print("  compactando…")
    con.execute("VACUUM")
    con.close()

    print(f"\n{NUCLEO} — {NUCLEO.stat().st_size / 1048576:.0f} MB "
          f"(completo: {COMPLETO.stat().st_size / 1048576:.0f} MB)")


if __name__ == "__main__":
    main()
