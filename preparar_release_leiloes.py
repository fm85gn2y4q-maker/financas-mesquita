"""Comprime o acervo de leilões e imprime o que vai para a release e a imagem.

Irmão do `preparar_release.py`, e separado dele por um motivo que não é
cerimônia: os dois leem bancos diferentes e resumem conteúdos diferentes. O
resumo daquele conta linhas de SICONFI e bens de patrimônio; o deste tem de
contar martelos e, sobretudo, **quantos lotes ficaram sem identificação** — que
é o número que diz se o acervo publicado presta.

    python preparar_release_leiloes.py 1.0.0
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "dados" / "leiloes.db"
BLOCO = 4 * 1024 * 1024


def _resumo(caminho: Path) -> str:
    digestor = hashlib.sha256()
    with caminho.open("rb") as fluxo:
        for bloco in iter(lambda: fluxo.read(BLOCO), b""):
            digestor.update(bloco)
    return digestor.hexdigest()


def _numeros(banco: Path) -> str:
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        lotes = con.execute("SELECT count(*) FROM lote").fetchone()[0]
        leiloes = con.execute("SELECT count(*) FROM leilao").fetchone()[0]
        casas = con.execute("SELECT count(*) FROM casa").fetchone()[0]
        martelos = con.execute(
            "SELECT count(*) FROM lote WHERE preco_martelo IS NOT NULL").fetchone()[0]
        indefinidos = con.execute(
            "SELECT count(*) FROM identificacao_indefinida").fetchone()[0]
        densas = con.execute(
            """SELECT count(*) FROM (SELECT i.chave FROM identificacao i
               JOIN lote l ON l.id = i.lote_id WHERE l.preco_martelo IS NOT NULL
               GROUP BY i.chave HAVING count(*) >= 5)""").fetchone()[0]
        de, ate = con.execute(
            "SELECT min(data_pregao), max(data_pregao) FROM leilao").fetchone()
    finally:
        con.close()

    pct = f"{100 * indefinidos / lotes:.0f}%" if lotes else "—"
    return (f"{lotes} lotes de {leiloes} leilões e {casas} casas ({de}–{ate}), "
            f"{martelos} com martelo, {densas} peças com cinco martelos ou mais "
            f"— só essas recebem nota. {indefinidos} lotes ({pct}) ficaram sem "
            f"identificação e exigem leitura humana.")


def conferir_que_nao_ha_catalogo(banco: Path) -> None:
    """Recusa publicar acervo que carregue catálogo de terceiro dentro.

    O catálogo AGA é obra protegida, com proibição expressa de reprodução
    (Lei 9.610/1998), e a cópia do usuário é de uso pessoal. Este script existe
    para gerar **asset público de release no GitHub**, servido depois por um
    conector cuja aprovação de OAuth é automática. Publicar o catálogo por aqui
    o transformaria de cópia pessoal em distribuição.

    A separação em `dados/catalogo.db` já evita isso por desenho. Esta função
    existe para o caso de alguém — inclusive eu, numa refatoração futura —
    resolver "simplificar" juntando os dois bancos: a partir daí a publicação
    passaria a redistribuir a obra, e nada avisaria.
    """
    con = sqlite3.connect(f"file:{banco}?mode=ro", uri=True)
    try:
        tabelas = {t for (t,) in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()

    intrusas = tabelas & {"moeda", "preco", "catalogo_moeda", "catalogo_preco"}
    if intrusas:
        raise SystemExit(
            f"ABORTADO: o acervo de leilões contém tabela de catálogo "
            f"({', '.join(sorted(intrusas))}).\n"
            f"  O catálogo AGA é obra protegida e a sua cópia é de uso pessoal. "
            f"Esta release é\n"
            f"  um arquivo PÚBLICO no GitHub — publicá-lo aqui seria "
            f"distribuição, que a obra proíbe.\n"
            f"  O catálogo tem banco próprio, `dados/catalogo.db`, que não se "
            f"publica.")


def preparar(versao: str,
             repositorio: str = "fm85gn2y4q-maker/financas-mesquita") -> int:
    if not BANCO.exists():
        print(f"Acervo não encontrado em {BANCO}.\n"
              f"  Rode `python coletar_leiloesbr.py` e `python "
              f"construir_leiloes.py` antes — e, se for a primeira vez nesta\n"
              f"  máquina, `python descobrir_leiloesbr.py` antes dos dois.",
              file=sys.stderr)
        return 1

    # Rodar com o servidor no ar deixaria o -wal por fora, e o acervo publicado
    # sairia sem as últimas escritas — silenciosamente.
    if BANCO.with_name(BANCO.name + "-wal").exists():
        print("AVISO: há um -wal ao lado do banco. Feche o que estiver "
              "escrevendo nele\n       (servidor, ingestão) e rode de novo, ou "
              "o acervo publicado sairá\n       sem as últimas alterações.",
              file=sys.stderr)

    conferir_que_nao_ha_catalogo(BANCO)

    destino = RAIZ / "dist" / f"leiloes-numismatica-v{versao}.db.gz"
    destino.parent.mkdir(parents=True, exist_ok=True)

    print(f"Comprimindo {BANCO.stat().st_size / 1048576:.1f} MB…")
    with BANCO.open("rb") as entrada, gzip.open(destino, "wb", compresslevel=9) as saida:
        shutil.copyfileobj(entrada, saida, length=BLOCO)

    digest = _resumo(destino)
    url = (f"https://github.com/{repositorio}/releases/download/"
           f"leiloes-v{versao}/{destino.name}")
    resumo = _numeros(BANCO)

    print(f"\n{destino}  ({destino.stat().st_size / 1048576:.1f} MB)")
    print(f"conteúdo: {resumo}\n")
    # A tag leva o prefixo `leiloes-` porque as duas releases moram no mesmo
    # repositório: sem ele, publicar o acervo de leilões como v1.0.0 colidiria
    # com a tag do acervo financeiro.
    print("1. Publique a release e anexe o .gz:\n")
    print(f'   gh release create leiloes-v{versao} "{destino}" \\')
    print(f'     --title "Acervo de leilões v{versao}" --notes "{resumo}"\n')
    print("2. Troque estas duas linhas no Dockerfile.leiloes:\n")
    print(f"   ARG ACERVO={url}")
    print(f"   ARG ACERVO_SHA256={digest}\n")
    print("3. Commite o Dockerfile.leiloes. O Render reconstrói e confere o hash.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    raise SystemExit(preparar(sys.argv[1], *sys.argv[2:3]))
