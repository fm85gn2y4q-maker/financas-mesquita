"""Comprime o acervo e imprime o que vai para o Dockerfile e para a release.

O banco tem ~100 MB, e comprimido ainda passa dos 50 MB em que o GitHub adverte.
Não entra no Git: vai como asset de release, e a imagem o busca na construção
conferindo o sha256. Divergindo o arquivo publicado do declarado, o build falha
em vez de subir um acervo diferente daquele que foi testado.

    python preparar_release.py 1.0.0
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "dados" / "acervo.db"
BLOCO = 4 * 1024 * 1024


def _resumo(caminho: Path) -> str:
    digestor = hashlib.sha256()
    with caminho.open("rb") as fluxo:
        for bloco in iter(lambda: fluxo.read(BLOCO), b""):
            digestor.update(bloco)
    return digestor.hexdigest()


def _numeros(banco: Path) -> str:
    """Os números entram na descrição da release — é o que identifica a coleta.

    Vão junto as datas de coleta de cada fonte. Neste acervo elas não são
    detalhe de auditoria: o mesmo fato aparece em fontes diferentes com números
    diferentes, e a data de corte de cada uma é o que explica a divergência.
    """
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        siconfi, de, ate = con.execute(
            "SELECT COUNT(*), MIN(exercicio), MAX(exercicio) FROM siconfi_linha"
        ).fetchone()
        pncp = con.execute("SELECT COUNT(*) FROM pncp_documento").fetchone()[0]
        bens = con.execute("SELECT COUNT(*) FROM patrimonio_bem").fetchone()[0]
        coletas = con.execute(
            "SELECT fonte, MAX(coletado_em) FROM coleta GROUP BY fonte ORDER BY 1"
        ).fetchall()
    finally:
        con.close()
    datas = "; ".join(f"{f} em {d[:10]}" for f, d in coletas)
    return (f"{siconfi} linhas do SICONFI ({de}-{ate}), {pncp} documentos do "
            f"PNCP, {bens} bens de patrimônio. Coleta: {datas}")


def preparar(versao: str,
             repositorio: str = "fm85gn2y4q-maker/financas-mesquita") -> int:
    if not BANCO.exists():
        print(f"Acervo não encontrado em {BANCO}. Rode `python construir_acervo.py`.",
              file=sys.stderr)
        return 1

    # Rodar com o servidor no ar deixaria o -wal por fora e o acervo publicado
    # sairia sem as últimas escritas — silenciosamente. O esquema abre em WAL.
    if BANCO.with_name(BANCO.name + "-wal").exists():
        print("AVISO: há um -wal ao lado do banco. Feche o que estiver escrevendo\n"
              "       nele (servidor, ingestão) e rode de novo, ou o acervo\n"
              "       publicado sairá sem as últimas alterações.",
              file=sys.stderr)

    destino = RAIZ / "dist" / f"financas-mesquita-v{versao}.db.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)

    print(f"Comprimindo {BANCO.stat().st_size / 1048576:.0f} MB…")
    with BANCO.open("rb") as entrada, gzip.open(destino, "wb", compresslevel=9) as saida:
        shutil.copyfileobj(entrada, saida, length=BLOCO)

    digest = _resumo(destino)
    url = (f"https://github.com/{repositorio}/releases/download/"
           f"v{versao}/{destino.name}")
    resumo = _numeros(BANCO)

    print(f"\n{destino}  ({destino.stat().st_size / 1048576:.1f} MB)")
    print(f"conteúdo: {resumo}\n")
    print("1. Publique a release e anexe o .gz:\n")
    print(f'   gh release create v{versao} "{destino}" \\')
    print(f'     --title "Acervo v{versao}" --notes "{resumo}"\n')
    print("2. Troque estas duas linhas no Dockerfile:\n")
    print(f"   ARG ACERVO={url}")
    print(f"   ARG ACERVO_SHA256={digest}\n")
    print("3. Commite o Dockerfile. O Render reconstrói e confere o hash.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    raise SystemExit(preparar(sys.argv[1], *sys.argv[2:3]))
