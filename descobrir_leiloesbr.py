"""Mapeia a estrutura real do portal ANTES de varrer, e grava o relatório.

Existe pelo mesmo motivo que `descobrir_relatorios.py` existe no acervo
financeiro: não se escreve extrator contra HTML que não se leu. O portal é ASP
clássico, muda de marcação sem aviso, e um seletor chutado não falha — ele
devolve campo vazio ou, pior, o campo do vizinho, e a coleta segue gravando
lixo com aparência de dado.

Rode isto primeiro, numa máquina que alcance o portal. Ele:

  1. lê o robots.txt e diz o que é permitido varrer;
  2. baixa o catálogo, as três buscas e (opcionalmente) um leilão, e grava
     tudo cru;
  3. lista os padrões de URL que achou, com quantas vezes cada um apareceu;
  4. **decodifica as categorias** que o portal usa no parâmetro `tp` — é
     assim que se descobre o nome exato de "Numismática" e "Filatelia" para
     filtrar a busca;
  5. testa os padrões de texto do coletor contra a página real e diz quais
     casaram;
  6. escreve `dados_brutos/leiloesbr/descoberta.json`.

O que ele NÃO faz é adivinhar. Padrão que não casar sai no relatório como não
casado, para ser corrigido em `coletar_leiloesbr.py` com a página na mão.

Uso:  python descobrir_leiloesbr.py
      python descobrir_leiloesbr.py --leilao 61318
"""

from __future__ import annotations

import argparse
import binascii
import json
import re
import urllib.parse
from collections import Counter
from pathlib import Path
from typing import Any

from coletar_leiloesbr import (MARCA_DE_LOTE, PADROES, URL_LOTE, analisar_busca,
                               so_texto, url_de_busca)
from leiloes import fontes

CATALOGO = f"{fontes.PORTAL}/catalogo.asp"

# O `tp` do portal é o nome da categoria em hexadecimal cp1252, entre barras.
_CATEGORIA = re.compile(r"tp=(?:%7C|\|)([0-9A-Fa-f]{2,200})(?:%7C|\|)")


def _urls(html: str) -> Counter[str]:
    """Agrupa os links pelo FORMATO, não pelo valor: `lote.asp?L=<n>` conta
    junto, e o que interessa é qual formato domina a página."""
    formatos: Counter[str] = Counter()
    for href in re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE):
        formato = re.sub(r"\d+", "<n>", href.split("#")[0])
        if ".asp" in formato.lower():
            formatos[formato] += 1
    return formatos


def _categorias(html: str) -> list[str]:
    """Decodifica os nomes de categoria embutidos nos links da página.

    É a descoberta que mais economiza trabalho: sem ela, filtrar a busca por
    Numismática vira adivinhação do nome exato — e nome errado não dá erro,
    devolve busca vazia, que passa por "não há peça nesta categoria".
    """
    nomes: dict[str, None] = {}
    for hexa in _CATEGORIA.findall(urllib.parse.unquote(html)):
        try:
            nome = binascii.unhexlify(hexa).decode("cp1252")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if nome.isprintable() and 2 < len(nome) < 60:
            nomes.setdefault(nome, None)
    return list(nomes)


def _testar_padroes(texto: str) -> dict[str, Any]:
    return {nome: {"casou": bool(achados := padrao.findall(texto)),
                   "quantas_vezes": len(achados),
                   "primeiros": [str(a) for a in achados[:3]]}
            for nome, padrao in PADROES.items()}


def descobrir(leilao: str | None = None) -> None:
    relatorio: dict[str, Any] = {"coletado_em": fontes.agora(), "paginas": {}}

    print(f"robots.txt de {fontes.PORTAL}")
    for alvo in (CATALOGO, f"{fontes.PORTAL}/{fontes.BUSCA_ABERTOS}",
                 f"{fontes.PORTAL}/{fontes.BUSCA_POS}",
                 f"{fontes.PORTAL}/lote.asp"):
        permitido = fontes.permitido(alvo)
        print(f"  {'permitido ' if permitido else 'PROIBIDO  '} {alvo}")
        relatorio.setdefault("robots", {})[alvo] = permitido

    if not fontes.permitido(CATALOGO):
        raise SystemExit(
            "\nO robots.txt do portal proíbe varrer o catálogo. Pare aqui e "
            "fale com a plataforma antes de seguir: há casas que liberam acesso "
            "a quem pede, e um acervo montado contra o robots.txt não se "
            "sustenta nem tecnicamente nem no resto.")

    alvos = [
        ("catalogo", CATALOGO),
        ("busca_abertos", url_de_busca(fontes.BUSCA_ABERTOS)),
        ("busca_pos", url_de_busca(fontes.BUSCA_POS, pesquisa="*")),
        ("busca_geral", url_de_busca(fontes.BUSCA_GERAL)),
    ]
    if leilao:
        alvos.append(("leilao", f"{fontes.PORTAL}/leilao.asp?Num={leilao}"))

    categorias: dict[str, None] = {}
    for nome, url in alvos:
        print(f"\n{url}")
        try:
            bruto = fontes.baixar(url)
        except Exception as erro:                     # noqa: BLE001
            print(f"  falhou: {erro}")
            relatorio["paginas"][nome] = {"url": url, "erro": str(erro)}
            continue

        fontes.gravar_bruto("leiloesbr", f"descoberta-{nome}.html", bruto, url)
        html = fontes.texto(bruto)
        texto = so_texto(html)

        formatos = _urls(html)
        padroes = _testar_padroes(texto)
        achados_de_busca = analisar_busca(html, "aberto")
        for c in _categorias(html):
            categorias.setdefault(c, None)

        relatorio["paginas"][nome] = {
            "url": url, "bytes": len(bruto),
            "codificacao_legivel": "�" not in html[:5000],
            "formatos_de_url": formatos.most_common(15),
            "links_de_lote": len(URL_LOTE.findall(html)),
            # Se "Fazer Lance" aparece mas URL_LOTE não casa, o nome do .asp da
            # ficha é outro — e é essa a informação que falta medir.
            "marcas_fazer_lance": len(MARCA_DE_LOTE.findall(texto)),
            "hrefs_com_asp_e_id": sorted({
                h for h in re.findall(r'href\s*=\s*["\']([^"\']*\.asp\?[^"\']+)["\']',
                                      html, re.IGNORECASE)
                if re.search(r"=\d{3,}", h)})[:12],
            "lotes_reconhecidos_pela_busca": len(achados_de_busca),
            "primeiro_lote": achados_de_busca[0] if achados_de_busca else None,
            "padroes_de_texto": padroes,
            "amostra_do_texto": texto[:1200],
        }

        print(f"  {len(bruto)} bytes; {len(URL_LOTE.findall(html))} links de lote; "
              f"{len(achados_de_busca)} lotes reconhecidos")
        for formato, n in formatos.most_common(6):
            print(f"    {n:>4}x  {formato}")
        for chave, r in padroes.items():
            print(f"    {'ok  ' if r['casou'] else 'NÃO '} {chave:<16} "
                  f"{r['quantas_vezes']:>3}x  {r['primeiros']}")

    relatorio["categorias"] = list(categorias)
    if categorias:
        print(f"\nCategorias do portal ({len(categorias)}):")
        for c in sorted(categorias):
            marca = "  <<<" if re.search(r"numism|filatel|moeda|selo|c[ée]dula",
                                         c, re.IGNORECASE) else ""
            print(f"    {c}{marca}")
        print("\n  Use o nome EXATO em --categoria; ele vira `tp` codificado "
              "em cp1252.")
    else:
        print("\nNenhuma categoria decodificada — o filtro por categoria pode "
              "não estar nesta página. Procure `tp=` no HTML gravado.")

    destino = Path(fontes.BRUTOS) / "leiloesbr" / "descoberta.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=1),
                       encoding="utf-8")

    nao_casaram = {nome for pagina in relatorio["paginas"].values()
                   for nome, r in pagina.get("padroes_de_texto", {}).items()
                   if not r["casou"]}
    sem_lote = [n for n, p in relatorio["paginas"].items()
                if n.startswith("busca") and not p.get("lotes_reconhecidos_pela_busca")]

    print(f"\n{destino}")
    if sem_lote:
        print(f"\nATENÇÃO: as buscas {', '.join(sem_lote)} não devolveram lote "
              f"reconhecível. Ou exigem sessão, ou o link da peça tem outro "
              f"nome — ajuste URL_LOTE e ANCORA_LOTE em coletar_leiloesbr.py "
              f"olhando o HTML gravado.")
    if nao_casaram:
        print(f"\nATENÇÃO: {len(nao_casaram)} padrões não casaram em página "
              f"nenhuma ({', '.join(sorted(nao_casaram))}). Padrão que não casa "
              f"devolve campo vazio, e campo vazio vira lote sem preço — que "
              f"some da conta em silêncio.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--leilao", help="id de um leilão para inspecionar a "
                                         "página de lotes")
    descobrir(parser.parse_args().leilao)
