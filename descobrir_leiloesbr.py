"""Mapeia a estrutura real do portal ANTES de varrer, e grava o relatório.

Existe pelo mesmo motivo que `descobrir_relatorios.py` existe no acervo
financeiro: não se escreve extrator contra HTML que não se leu. O portal é ASP
clássico, muda de marcação sem aviso, e um seletor chutado não falha — ele
devolve campo vazio ou, pior, o campo do vizinho, e a coleta segue gravando
lixo com aparência de dado.

Rode isto primeiro, numa máquina que alcance o portal. Ele:

  1. lê o robots.txt e diz o que é permitido varrer;
  2. baixa uma página de catálogo e uma de lote e grava as duas cruas;
  3. lista os padrões de URL que achou, com quantas vezes cada um apareceu;
  4. testa os padrões de texto que o coletor usa (lance, martelo, número do
     lote) contra a página real e diz quais casaram;
  5. escreve `dados_brutos/leiloesbr/descoberta.json`.

O que ele NÃO faz é adivinhar. Padrão que não casar sai no relatório como não
casado, para ser corrigido em `coletar_leiloesbr.py` com a página na mão.

Uso:  python descobrir_leiloesbr.py
      python descobrir_leiloesbr.py --leilao 61318
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from coletar_leiloesbr import PADROES, so_texto
from leiloes import fontes

CATALOGO = f"{fontes.PORTAL}/catalogo.asp"


def _urls(html: str) -> Counter[str]:
    """Agrupa os links pelo FORMATO, não pelo valor: `lote.asp?L=<n>` conta
    junto, e o que interessa é qual formato domina a página."""
    formatos: Counter[str] = Counter()
    for href in re.findall(r'href\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE):
        formato = re.sub(r"\d+", "<n>", href.split("#")[0])
        if ".asp" in formato.lower() or "leilao" in formato.lower():
            formatos[formato] += 1
    return formatos


def _testar_padroes(texto: str) -> dict[str, Any]:
    resultado = {}
    for nome, padrao in PADROES.items():
        achados = padrao.findall(texto)
        resultado[nome] = {"casou": bool(achados),
                           "quantas_vezes": len(achados),
                           "primeiros": [str(a) for a in achados[:3]]}
    return resultado


def descobrir(leilao: str | None = None) -> None:
    relatorio: dict[str, Any] = {"coletado_em": fontes.agora(), "paginas": {}}

    print(f"robots.txt de {fontes.PORTAL}")
    for alvo in (CATALOGO, f"{fontes.PORTAL}/abre_catalogo.asp",
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

    alvos = [("catalogo", CATALOGO)]
    if leilao:
        alvos.append(("leilao", f"{fontes.PORTAL}/leilao.asp?Num={leilao}"))

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
        relatorio["paginas"][nome] = {
            "url": url, "bytes": len(bruto),
            "codificacao_legivel": "�" not in html[:5000],
            "formatos_de_url": formatos.most_common(15),
            "padroes_de_texto": padroes,
            "amostra_do_texto": texto[:1200],
        }

        print(f"  {len(bruto)} bytes; formatos de URL mais frequentes:")
        for formato, n in formatos.most_common(8):
            print(f"    {n:>4}x  {formato}")
        print("  padrões de texto do coletor:")
        for chave, r in padroes.items():
            marca = "ok  " if r["casou"] else "NÃO "
            print(f"    {marca} {chave:<16} {r['quantas_vezes']:>3}x  "
                  f"{r['primeiros']}")

    destino = Path(fontes.BRUTOS) / "leiloesbr" / "descoberta.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(relatorio, ensure_ascii=False, indent=1),
                       encoding="utf-8")

    nao_casaram = [nome for pagina in relatorio["paginas"].values()
                   for nome, r in pagina.get("padroes_de_texto", {}).items()
                   if not r["casou"]]
    print(f"\n{destino}")
    if nao_casaram:
        print(f"\nATENÇÃO: {len(set(nao_casaram))} padrões não casaram "
              f"({', '.join(sorted(set(nao_casaram)))}). Abra o HTML cru gravado "
              f"ao lado do relatório e corrija PADROES em coletar_leiloesbr.py "
              f"antes de varrer. Padrão que não casa devolve campo vazio, e "
              f"campo vazio vira lote sem preço — que some da conta em silêncio.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--leilao", help="id de um leilão para inspecionar a "
                                         "página de lotes")
    descobrir(parser.parse_args().leilao)
