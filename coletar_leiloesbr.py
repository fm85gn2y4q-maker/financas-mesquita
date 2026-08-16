"""Varre o LeilõesBR e as casas que anunciam nele. Grava o cru e o normalizado.

ESTADO DESTE ARQUIVO — leia antes de rodar
------------------------------------------
Os padrões abaixo foram escritos SEM acesso ao portal: o ambiente onde este
arquivo nasceu tem a saída de rede bloqueada para leiloesbr.com.br. Eles são
uma hipótese sobre a marcação, não uma medição dela.

Por isso a ordem obrigatória na primeira vez, em máquina que alcance o portal:

    python descobrir_leiloesbr.py --leilao <id>    # mede a página real
    # corrija PADROES aqui com o relatório na mão
    python coletar_leiloesbr.py --leilao <id>      # varre um leilão só
    python construir_leiloes.py

O `descobrir` diz, padrão por padrão, qual casou e qual não. Padrão que não
casa NÃO derruba a coleta — devolve campo vazio, o lote entra sem preço e some
das contas em silêncio. É o modo mais caro de errar aqui, e é por isso que
`coletar` aborta quando a taxa de campos vazios passa de LIMITE_VAZIO.

Por que a extração é por RÓTULO e não por seletor de HTML
--------------------------------------------------------
Site ASP dessa geração reescreve a marcação com frequência e sem aviso — troca
de tabela para div, muda classe, renumera célula. Seletor posicional quebra
calado a cada mudança dessas. O rótulo visível ("Lance inicial:", "Arrematado
por:") é o que o portal NÃO muda, porque é o que o cliente lê. Extrair do texto
renderizado custa um pouco de precisão e paga em não quebrar todo mês.

Uso:  python coletar_leiloesbr.py                 # catálogo corrente
      python coletar_leiloesbr.py --leilao 61318  # um leilão
      python coletar_leiloesbr.py --paginas 5     # fundo do catálogo
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
from pathlib import Path
from typing import Any

from leiloes import fontes

# Fração de lotes sem preço a partir da qual a coleta aborta em vez de gravar.
# Coleta que grava lixo é pior que coleta que falha: a falha se vê.
LIMITE_VAZIO = 0.6

# --------------------------------------------------------------------- padrões
#
# HIPÓTESE, não medição. Confira cada um com `descobrir_leiloesbr.py`.
PADROES: dict[str, re.Pattern[str]] = {
    "numero_do_lote": re.compile(r"\bLote\s*n?[ºo°]?\s*:?\s*(\d{1,5})\b",
                                 re.IGNORECASE),
    "lance_inicial": re.compile(
        r"(?:lance\s+(?:inicial|m[íi]nimo)|inicial|abertura)\s*:?\s*"
        r"R\$\s*([\d.]{1,12},\d{2})", re.IGNORECASE),
    "martelo": re.compile(
        r"(?:arrematado(?:\s+por)?|vendido(?:\s+por)?|lance\s+vencedor|"
        r"valor\s+de\s+arremate)\s*:?\s*R\$\s*([\d.]{1,12},\d{2})", re.IGNORECASE),
    "estimativa": re.compile(
        r"(?:estimativa|avalia[çc][ãa]o)\s*:?\s*R\$\s*([\d.]{1,12},\d{2})"
        r"(?:\s*(?:a|-|até)\s*R\$\s*([\d.]{1,12},\d{2}))?", re.IGNORECASE),
    "nao_arrematado": re.compile(
        r"\b(n[ãa]o\s+arrematado|sem\s+lance|n[ãa]o\s+vendido|deserto)\b",
        re.IGNORECASE),
    "data_pregao": re.compile(
        r"\b(\d{2})/(\d{2})/(\d{4})(?:\s*[àa]s?\s*\d{1,2}[:h]\d{2})?"),
}

# Formatos de URL vistos em resultados públicos do portal. `abre_catalogo.asp`
# carrega o id do leilão no terceiro campo, separado por barra vertical:
#   abre_catalogo.asp?t=1|http://www.casa.com.br|61318|30317899
URL_LEILAO = re.compile(
    r"(?:leilao|abre_catalogo)\.asp\?[^\"'>]*?(?:Num=|%7C|\|)(\d{4,8})",
    re.IGNORECASE)
URL_LOTE = re.compile(r"(lote\.asp\?[^\"'>]+)", re.IGNORECASE)

_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_QUEBRAS = re.compile(r"<(br|/p|/div|/tr|/td|/li|/h\d)\b[^>]*>", re.IGNORECASE)


def so_texto(html: str) -> str:
    """HTML → texto visível, com as quebras de bloco preservadas.

    As quebras importam: sem elas "Lote 12" e "Lance inicial" de lotes
    diferentes se encostam numa linha só, e a divisão por lote — que é feita
    pelo rótulo "Lote" — passa a juntar o preço de um com o título do outro.
    """
    html = _TAGS.sub(" ", html)
    html = _QUEBRAS.sub("\n", html)
    html = re.sub(r"<[^>]+>", " ", html)
    texto = _html.unescape(html)
    texto = re.sub(r"[ \t\r\f\v]+", " ", texto)
    return re.sub(r"\n\s*\n+", "\n", texto).strip()


def reais(valor: str | None) -> float | None:
    """"1.234,56" → 1234.56. O separador brasileiro invertido é a forma
    silenciosa de errar por mil: "1.234" lido como float dá 1,234."""
    if not valor:
        return None
    try:
        return float(valor.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _data_iso(texto: str) -> str | None:
    m = PADROES["data_pregao"].search(texto)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def analisar_lote(bloco: str) -> dict[str, Any] | None:
    """Um bloco de texto → um lote. Devolve None se nem o número achou."""
    m = PADROES["numero_do_lote"].search(bloco)
    if not m:
        return None

    martelo = PADROES["martelo"].search(bloco)
    estimativa = PADROES["estimativa"].search(bloco)
    if martelo:
        situacao = "arrematado"
    elif PADROES["nao_arrematado"].search(bloco):
        situacao = "nao_arrematado"
    else:
        situacao = "aberto"

    # O título é a primeira linha com substância depois do número do lote; a
    # descrição é o resto. Não é elegante e é o que sobrevive à troca de
    # marcação: nenhuma das duas depende de tag nenhuma.
    linhas = [ln.strip() for ln in bloco[m.end():].split("\n") if ln.strip()]
    uteis = [ln for ln in linhas if len(ln) > 3 and not ln.lower().startswith("r$")]
    return {
        "numero": int(m.group(1)),
        "titulo": uteis[0] if uteis else f"Lote {m.group(1)}",
        "descricao": " ".join(uteis[1:])[:4000],
        "lance_inicial": reais(PADROES["lance_inicial"].search(bloco)
                               and PADROES["lance_inicial"].search(bloco).group(1)),
        "estimativa_min": reais(estimativa.group(1)) if estimativa else None,
        "estimativa_max": reais(estimativa.group(2)) if estimativa else None,
        "situacao": situacao,
        "preco_martelo": reais(martelo.group(1)) if martelo else None,
        "data_resultado": _data_iso(bloco) if martelo else None,
    }


def analisar_pagina(html: str) -> list[dict[str, Any]]:
    """Divide a página pelo rótulo "Lote" e analisa cada pedaço."""
    texto = so_texto(html)
    blocos = re.split(r"(?=\bLote\s*n?[ºo°]?\s*:?\s*\d{1,5}\b)", texto,
                      flags=re.IGNORECASE)
    lotes = [lote for bloco in blocos if (lote := analisar_lote(bloco))]
    # O mesmo número pode reaparecer (miniatura no topo e ficha embaixo). Fica
    # a ocorrência mais rica: a que tem preço.
    por_numero: dict[int, dict[str, Any]] = {}
    for lote in lotes:
        anterior = por_numero.get(lote["numero"])
        if not anterior or (lote["preco_martelo"] or lote["lance_inicial"]):
            if not anterior or len(lote["descricao"]) >= len(anterior["descricao"]):
                por_numero[lote["numero"]] = lote
    return [por_numero[n] for n in sorted(por_numero)]


def ids_de_leilao(html: str) -> list[str]:
    vistos: dict[str, None] = {}
    for id_ in URL_LEILAO.findall(_html.unescape(html)):
        vistos.setdefault(id_, None)
    return list(vistos)


def coletar_leilao(id_leilao: str) -> dict[str, Any] | None:
    url = f"{fontes.PORTAL}/leilao.asp?Num={id_leilao}"
    bruto = fontes.baixar(url)
    fontes.gravar_bruto("leiloesbr", f"leilao-{id_leilao}.html", bruto, url)
    html = fontes.texto(bruto)

    lotes = analisar_pagina(html)
    if not lotes:
        print(f"  leilão {id_leilao}: nenhum lote reconhecido — "
              f"confira PADROES contra o HTML gravado")
        return None

    texto = so_texto(html)
    cabecalho = texto[:600]
    casa = next((ln.strip() for ln in cabecalho.split("\n")
                 if len(ln.strip()) > 4), f"casa-{id_leilao}")
    return {
        "leilao": {"id": id_leilao, "casa": casa, "casa_site": None,
                   "titulo": cabecalho.split("\n")[0][:200],
                   "data_pregao": _data_iso(cabecalho), "url": url,
                   "cidade": None, "uf": None},
        "lotes": lotes,
        "coletado_em": fontes.agora(),
    }


def coletar(leiloes: list[str] | None = None, paginas: int = 3) -> None:
    destino = Path(fontes.BRUTOS) / "leiloesbr"
    destino.mkdir(parents=True, exist_ok=True)

    if not leiloes:
        leiloes = []
        for pagina in range(1, paginas + 1):
            url = f"{fontes.PORTAL}/catalogo.asp?pag={pagina}"
            bruto = fontes.baixar(url)
            fontes.gravar_bruto("leiloesbr", f"catalogo-{pagina}.html", bruto, url)
            achados = ids_de_leilao(fontes.texto(bruto))
            print(f"catálogo página {pagina}: {len(achados)} leilões")
            if not achados:
                break
            leiloes += [i for i in achados if i not in leiloes]

    if not leiloes:
        raise SystemExit(
            "Nenhum leilão achado no catálogo. Rode `descobrir_leiloesbr.py`: "
            "ou o formato de URL mudou, ou a página exige sessão.")

    total = vazios = 0
    for id_leilao in leiloes:
        dados = coletar_leilao(id_leilao)
        if not dados:
            continue
        (destino / f"leilao-{id_leilao}.json").write_text(
            json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        sem_preco = sum(1 for l in dados["lotes"]
                        if l["lance_inicial"] is None and l["preco_martelo"] is None)
        total += len(dados["lotes"])
        vazios += sem_preco
        print(f"  leilão {id_leilao}: {len(dados['lotes'])} lotes "
              f"({sem_preco} sem preço)")

    if total and vazios / total > LIMITE_VAZIO:
        raise SystemExit(
            f"\nABORTADO: {vazios} de {total} lotes ({100 * vazios / total:.0f}%) "
            f"saíram sem preço nenhum. Isso não é catálogo pobre, é padrão que "
            f"não casa. Os arquivos crus estão em {destino} — rode "
            f"`descobrir_leiloesbr.py` e corrija PADROES antes de construir o "
            f"acervo com isto.")

    print(f"\n{total} lotes de {len(leiloes)} leilões em {destino}")
    print("Agora: python construir_leiloes.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--leilao", action="append", dest="leiloes",
                        help="id de um leilão; pode repetir")
    parser.add_argument("--paginas", type=int, default=3,
                        help="páginas do catálogo a varrer (padrão: 3)")
    args = parser.parse_args()
    coletar(args.leiloes, args.paginas)
