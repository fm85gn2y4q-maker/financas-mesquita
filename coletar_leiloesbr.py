"""Varre o LeilõesBR. Grava o cru e o normalizado.

TRÊS ROTAS, TRÊS PERGUNTAS DIFERENTES
-------------------------------------
    --abertos     `busca_andamento.asp` — tudo que está em pregão AGORA. É o
                  que se pode comprar, e é a rota principal. Com pesquisa
                  vazia, enumera o portal inteiro, página por página.

    --pos         `buscapos.asp` — o que NÃO arrematou e ficou à venda depois
                  do pregão. Para quem caça peça esquecida é o filão mais
                  direto que o portal tem: o vendedor já viu o mercado recusar
                  o preço dele uma vez.

    --historico   `catalogo.asp` → `leilao.asp` — os pregões já realizados. Não
                  serve para comprar; serve para ter martelo, que é a base de
                  comparação sem a qual nada aqui recebe nota.

Confundir as três é confundir o que se pode comprar com o que já foi vendido.
A rota de histórico é a que alimenta a mediana; as outras duas alimentam a
lista de oportunidades.

DUAS ETAPAS, PARA NÃO TORRAR A COLETA NUMA VARREDURA SÓ
------------------------------------------------------
A página de resultados traz título, preço e link — barato, e suficiente para
identificar a maioria das peças. A ficha completa de cada lote custa uma
requisição a mais, e a 2,5 s cada uma isso são horas.

Por isso a etapa 2 (`--aprofundar`) é opcional e seletiva: busca a ficha só dos
lotes que a etapa 1 não conseguiu identificar. São justamente os que precisam
de mais texto — e, não por acaso, os que costumam esconder a oportunidade.

ESTADO DOS PADRÕES DE EXTRAÇÃO — leia antes de rodar
----------------------------------------------------
Os endereços e o parâmetro de categoria vieram de páginas públicas indexadas do
próprio portal, e são fato. Os padrões de TEXTO abaixo, não: foram escritos sem
acesso ao site, porque o ambiente onde nasceram tem a saída de rede bloqueada
para leiloesbr.com.br. São hipótese sobre a marcação.

Na primeira vez, em máquina que alcance o portal:

    python descobrir_leiloesbr.py           # mede as páginas reais
    # corrija PADROES aqui com o relatório na mão
    python coletar_leiloesbr.py --abertos --categoria Numismática --paginas 3
    python construir_leiloes.py

Uso:
    python coletar_leiloesbr.py --abertos                      # tudo em pregão
    python coletar_leiloesbr.py --abertos --categoria Filatelia
    python coletar_leiloesbr.py --abertos --busca "bentes"
    python coletar_leiloesbr.py --pos                          # pós-pregão
    python coletar_leiloesbr.py --historico --paginas 5        # martelos
    python coletar_leiloesbr.py --leilao 61318                 # um leilão só
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from leiloes import fontes

# Fração de lotes sem preço a partir da qual a coleta aborta em vez de gravar.
# Coleta que grava lixo é pior que coleta que falha: a falha se vê.
LIMITE_VAZIO = 0.6

# Teto de páginas por varredura. O portal tem catálogo grande — há endereço
# público indexado com `pag=1283` —, e sem teto uma varredura distraída passa a
# noite batendo no site de terceiro.
PAGINAS_PADRAO = 20

# --------------------------------------------------------------------- padrões
#
# HIPÓTESE, não medição. Confira cada um com `descobrir_leiloesbr.py`.
PADROES: dict[str, re.Pattern[str]] = {
    "numero_do_lote": re.compile(r"\bLote\s*n?[ºo°]?\s*:?\s*(\d{1,5})\b",
                                 re.IGNORECASE),
    "lance_inicial": re.compile(
        r"(?:lance\s+(?:inicial|m[íi]nimo|atual)|inicial|abertura)\s*:?\s*"
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
    "qualquer_preco": re.compile(r"R\$\s*([\d.]{1,12},\d{2})"),
    # Contagem de lances. "sem lance" é a peneira de peça esquecida, e ela só
    # vale se a AUSÊNCIA de contagem não for confundida com zero — por isso o
    # campo fica nulo quando nenhum destes casa, e nunca 0 por omissão.
    "lances": re.compile(
        r"(\d{1,4})\s*lances?\b|\blances?\s*:?\s*(\d{1,4})\b", re.IGNORECASE),
    "sem_lance": re.compile(
        r"\b(sem\s+lances?|nenhum\s+lance|aguardando\s+lances?|"
        r"seja\s+o\s+primeiro)\b", re.IGNORECASE),
    "data_pregao": re.compile(
        r"\b(\d{2})/(\d{2})/(\d{4})(?:\s*[àa]s?\s*\d{1,2}[:h]\d{2})?"),
}

# Formatos de URL do portal, colhidos de páginas públicas indexadas.
# `abre_catalogo.asp` carrega o id do leilão no terceiro campo, separado por
# barra vertical:
#   abre_catalogo.asp?t=1|http://www.casa.com.br|61318|30317899
URL_LEILAO = re.compile(
    r"(?:leilao|abre_catalogo)\.asp\?[^\"'>]*?(?:Num=|%7C|\|)(\d{4,8})",
    re.IGNORECASE)
URL_LOTE = re.compile(r"((?:peca|lote|item)\.asp\?[^\"'>\s]+)", re.IGNORECASE)
ANCORA_LOTE = re.compile(
    r"(?=<a[^>]+href=[\"'][^\"']*(?:peca|lote|item)\.asp)", re.IGNORECASE)

# O portal chama a ficha do lote de "página da peça", e nela há o botão "Fazer
# Lance" — descrito no próprio "Como Comprar" do site. É o marcador mais
# estável de que uma página É uma ficha de lote, porque é o que faz o site
# funcionar; o nome do arquivo .asp, esse, ainda não foi medido.
MARCA_DE_LOTE = re.compile(r"\bfazer\s+lance\b", re.IGNORECASE)

_IMAGEM = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.IGNORECASE)

_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
_QUEBRAS = re.compile(r"<(br|/p|/div|/tr|/td|/li|/h\d)\b[^>]*>", re.IGNORECASE)


def _absoluta(caminho: str) -> str:
    """URL relativa gravada no acervo não abre em lugar nenhum depois."""
    caminho = _html.unescape(caminho)
    if caminho.startswith(("http://", "https://")):
        return caminho
    return f"{fontes.PORTAL}/{caminho.lstrip('/')}"


def so_texto(html: str) -> str:
    """HTML → texto visível, com as quebras de bloco preservadas.

    As quebras importam: sem elas "Lote 12" e "Lance inicial" de lotes
    diferentes se encostam numa linha só, e a divisão por lote passa a juntar o
    preço de um com o título do outro.
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


def _lances(texto: str) -> int | None:
    """Quantos lances o lote recebeu, ou None quando a página não diz.

    None e 0 são coisas diferentes e não podem se misturar: "sem lance" é a
    peneira de peça esquecida, e devolver 0 para lote cuja contagem não foi
    publicada encheria a lista justamente de lotes disputados.
    """
    if PADROES["sem_lance"].search(texto):
        return 0
    if (m := PADROES["lances"].search(texto)):
        return int(m.group(1) or m.group(2))
    return None


def _data_iso(texto: str) -> str | None:
    m = PADROES["data_pregao"].search(texto)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


# ------------------------------------------------------------- páginas de lote

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

    inicial = PADROES["lance_inicial"].search(bloco)
    linhas = [ln.strip() for ln in bloco[m.end():].split("\n") if ln.strip()]
    uteis = [ln for ln in linhas if len(ln) > 3 and not ln.lower().startswith("r$")]
    return {
        "numero": int(m.group(1)),
        "titulo": uteis[0] if uteis else f"Lote {m.group(1)}",
        "descricao": " ".join(uteis[1:])[:4000],
        "lance_inicial": reais(inicial.group(1)) if inicial else None,
        "estimativa_min": reais(estimativa.group(1)) if estimativa else None,
        "estimativa_max": reais(estimativa.group(2)) if estimativa else None,
        "situacao": situacao,
        "lances": _lances(bloco),
        "preco_martelo": reais(martelo.group(1)) if martelo else None,
        "data_resultado": _data_iso(bloco) if martelo else None,
    }


def analisar_pagina(html: str) -> list[dict[str, Any]]:
    """Divide a página de um leilão pelo rótulo "Lote" e analisa cada pedaço."""
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


# ---------------------------------------------------------- páginas de busca

def analisar_busca(html: str, situacao: str) -> list[dict[str, Any]]:
    """Resultado de busca → lotes.

    A divisão aqui NÃO é pelo rótulo "Lote", e sim pelo LINK de cada peça. Numa
    grade de resultados o rótulo pode nem aparecer — o cartão mostra foto,
    título e preço —, enquanto o link para a ficha existe sempre, porque é ele
    que faz a página funcionar. Dividir pelo que o site precisa que exista é
    mais estável do que dividir pelo que ele escolhe exibir.
    """
    por_caminho: dict[str, dict[str, Any]] = {}

    for parte in ANCORA_LOTE.split(html)[1:]:
        m = URL_LOTE.search(parte)
        if not m:
            continue
        caminho = _html.unescape(m.group(1))

        # Só até o próximo link: sem o corte, o texto do cartão seguinte entra
        # neste e o preço de um lote cola no título do outro.
        texto = so_texto(parte)
        linhas = [ln.strip() for ln in texto.split("\n") if ln.strip()]
        uteis = [ln for ln in linhas
                 if len(ln) > 3 and not ln.lower().startswith("r$")
                 and not re.fullmatch(r"[\d\W]+", ln)]

        preco = PADROES["lance_inicial"].search(texto) \
            or PADROES["qualquer_preco"].search(texto)
        numero = PADROES["numero_do_lote"].search(texto)
        foto = _IMAGEM.search(parte)

        # O MESMO lote costuma aparecer em dois links seguidos no cartão: a
        # foto e o título. Ficar com a primeira ocorrência dava um lote sem
        # título e sem preço — os dois estão na segunda. Por isso as
        # ocorrências são FUNDIDAS, e não escolhidas: cada uma traz um pedaço.
        # É a mesma lição que `analisar_pagina` já tinha aprendido com a
        # miniatura no topo da página do leilão, e que este trecho repetiu.
        lote = por_caminho.setdefault(caminho, {
            "numero": None, "titulo": None, "descricao": "",
            "url": f"{fontes.PORTAL}/{caminho.lstrip('/')}",
            "foto_url": None, "lance_inicial": None,
            "estimativa_min": None, "estimativa_max": None,
            "situacao": situacao, "lances": None,
            "preco_martelo": None, "data_resultado": None,
        })
        if lote["numero"] is None and numero:
            lote["numero"] = int(numero.group(1))
        if lote["lance_inicial"] is None and preco:
            lote["lance_inicial"] = reais(preco.group(1))
        if lote["foto_url"] is None and foto:
            lote["foto_url"] = _absoluta(foto.group(1))
        if lote["lances"] is None:
            lote["lances"] = _lances(texto)
        if uteis and len(uteis[0]) > len(lote["titulo"] or ""):
            lote["titulo"] = uteis[0]
            lote["descricao"] = " ".join(uteis[1:3])[:1000]

    for caminho, lote in por_caminho.items():
        lote["titulo"] = lote["titulo"] or caminho
    return list(por_caminho.values())


def url_de_busca(endpoint: str, pesquisa: str = "", categoria: str | None = None,
                 pagina: int = 1, uf: str | None = None,
                 galeria: str | None = None) -> str:
    """Monta o endereço da busca.

    `tp` vai em hexadecimal cp1252; `ga` (a galeria) e `uf` vão em texto
    simples — medido em endereços públicos do portal, que trazem
    `default.asp?ga=Brasil+Moedas+Leilões` e `busca_andamento.asp?uf=*`.
    Codificar `ga` como se fosse `tp` devolveria busca vazia.
    """
    parametros: dict[str, Any] = {
        "pesquisa": pesquisa, "gbl": "0", "b": "0", "pag": pagina,
        "tp": fontes.categoria_hex(categoria) if categoria else "|"}
    if uf:
        parametros["uf"] = uf
    if galeria:
        parametros["ga"] = galeria
    return f"{fontes.PORTAL}/{endpoint}?{urlencode(parametros)}"


def coletar_busca(endpoint: str, situacao: str, pesquisa: str = "",
                  categoria: str | None = None, paginas: int = PAGINAS_PADRAO,
                  uf: str | None = None) -> list[dict[str, Any]]:
    """Percorre a busca paginada até acabar. Grava o cru de cada página."""
    lotes: list[dict[str, Any]] = []
    vistos: set[str] = set()
    esgotou = False
    rotulo = re.sub(r"\W+", "-", categoria or "tudo").strip("-").lower()

    for pagina in range(1, paginas + 1):
        url = url_de_busca(endpoint, pesquisa, categoria, pagina, uf)
        bruto = fontes.baixar(url)
        fontes.gravar_bruto(
            "leiloesbr",
            f"busca-{endpoint.split('.')[0]}-{rotulo}-{pagina:04d}.html",
            bruto, url)

        achados = analisar_busca(fontes.texto(bruto), situacao)
        novos = [a for a in achados if a["url"] not in vistos]
        vistos.update(a["url"] for a in novos)
        lotes += novos

        print(f"  página {pagina:>3}: {len(achados):>3} lotes, "
              f"{len(novos):>3} novos  (acumulado {len(lotes)})")

        # Duas paradas, e a segunda é a que importa: ASP costuma GRAMPEAR o
        # número de página ao máximo existente em vez de devolver vazio. Sem
        # esta guarda, a varredura repete a última página até o teto, parecendo
        # que está coletando.
        if not achados:
            esgotou = True
            break
        if not novos:
            print("  a página repetiu o que já veio — fim do resultado")
            esgotou = True
            break

    # Teto batido não pode passar em silêncio. Uma subcategoria do portal
    # chega a milhares de peças — "Numismática - Moedas do Brasil" aparecia com
    # 4.529 num endereço indexado —, e uma varredura truncada tem exatamente a
    # mesma aparência de uma completa. Cobertura parcial não declarada vira
    # conclusão errada sobre o mercado.
    if not esgotou:
        print(f"  AVISO: parou no teto de {paginas} páginas SEM esgotar o "
              f"resultado. O que veio é recorte, não a categoria inteira — "
              f"suba --paginas para varrer o resto.")

    return lotes


# --------------------------------------------------------- páginas de leilão

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


# ------------------------------------------------------------------- gravação

def _gravar(nome: str, leilao: dict[str, Any], lotes: list[dict[str, Any]],
            destino: Path) -> int:
    if not lotes:
        return 0
    (destino / f"leilao-{nome}.json").write_text(
        json.dumps({"leilao": leilao, "lotes": lotes,
                    "coletado_em": fontes.agora()},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return len(lotes)


def coletar(rotas: list[str], pesquisa: str = "",
            categorias: list[str] | None = None,
            leiloes: list[str] | None = None, paginas: int = PAGINAS_PADRAO,
            uf: str | None = None) -> None:
    destino = Path(fontes.BRUTOS) / "leiloesbr"
    destino.mkdir(parents=True, exist_ok=True)
    total = vazios = 0
    # Sem categoria, varre tudo; o `None` da lista é o "sem filtro".
    alvos: list[str | None] = list(categorias) if categorias else [None]

    for rota, endpoint, situacao, termo in (
            ("abertos", fontes.BUSCA_ABERTOS, "aberto", pesquisa),
            ("pos", fontes.BUSCA_POS, "pos_pregao", pesquisa or "*")):
        if rota not in rotas:
            continue
        for categoria in alvos:
            print(f"{'Leilões em andamento' if rota == 'abertos' else 'Venda pós-pregão'}"
                  f"{f' — {categoria}' if categoria else ''}"
                  f"{f' — {uf}' if uf else ''}"
                  f"{f' — termo {termo!r}' if termo and termo != '*' else ''}")
            lotes = coletar_busca(endpoint, situacao, termo, categoria,
                                  paginas, uf)
            if not lotes:
                continue
            # A busca devolve peças de MUITOS leilões, e a página de resultado
            # não diz de qual casa é cada uma. Declarar isso é melhor que
            # inventar: a casa fica nomeada como desconhecida até que a ficha
            # do lote a informe.
            nome = re.sub(r"\W+", "-", f"{rota}-{categoria or 'tudo'}").strip("-").lower()
            total += _gravar(f"busca-{nome}", {
                "id": f"busca-{nome}",
                "casa": "(casa não identificada na busca)", "casa_site": None,
                "titulo": f"Busca — {categoria or 'todas as categorias'}",
                "data_pregao": None,
                "url": url_de_busca(endpoint, termo, categoria, uf=uf),
                "cidade": None, "uf": uf}, lotes, destino)
            vazios += sum(1 for l in lotes if l["lance_inicial"] is None)

    if "historico" in rotas or leiloes:
        if not leiloes:
            leiloes = []
            for pagina in range(1, paginas + 1):
                url = f"{fontes.PORTAL}/catalogo.asp?pag={pagina}"
                bruto = fontes.baixar(url)
                fontes.gravar_bruto("leiloesbr", f"catalogo-{pagina}.html",
                                    bruto, url)
                achados = ids_de_leilao(fontes.texto(bruto))
                print(f"catálogo página {pagina}: {len(achados)} leilões")
                if not achados:
                    break
                leiloes += [i for i in achados if i not in leiloes]

        for id_leilao in leiloes:
            dados = coletar_leilao(id_leilao)
            if not dados:
                continue
            (destino / f"leilao-{id_leilao}.json").write_text(
                json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
            sem_preco = sum(1 for l in dados["lotes"]
                            if l["lance_inicial"] is None
                            and l["preco_martelo"] is None)
            total += len(dados["lotes"])
            vazios += sem_preco
            print(f"  leilão {id_leilao}: {len(dados['lotes'])} lotes "
                  f"({sem_preco} sem preço)")

    if not total:
        raise SystemExit(
            "\nNenhum lote coletado. Rode `descobrir_leiloesbr.py`: ou o "
            "formato mudou, ou a busca exige sessão, ou os padrões de texto "
            "não casam com a marcação atual.")

    if vazios / total > LIMITE_VAZIO:
        raise SystemExit(
            f"\nABORTADO: {vazios} de {total} lotes ({100 * vazios / total:.0f}%) "
            f"saíram sem preço nenhum. Isso não é catálogo pobre, é padrão que "
            f"não casa. Os arquivos crus estão em {destino} — rode "
            f"`descobrir_leiloesbr.py` e corrija PADROES antes de construir o "
            f"acervo com isto.")

    print(f"\n{total} lotes em {destino}")
    print("Agora: python construir_leiloes.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--abertos", action="store_true",
                        help="busca nos leilões em andamento (rota principal)")
    parser.add_argument("--pos", action="store_true",
                        help="busca na venda pós-pregão — o que não arrematou")
    parser.add_argument("--historico", action="store_true",
                        help="varre o catálogo para colher martelos passados, "
                             "que são a base de comparação")
    parser.add_argument("--segmento", help="varre TODAS as subcategorias do "
                                           "segmento: numismatica ou filatelia")
    parser.add_argument("--categoria", action="append", dest="categorias",
                        help="nome EXATO de uma categoria do portal, ex.: "
                             "'Numismática - Moedas do Brasil'. Pode repetir. "
                             "Cuidado: 'Numismática' sozinha NÃO existe, e "
                             "nome inexistente devolve busca vazia sem avisar.")
    parser.add_argument("--uf", help="sigla do estado, para filtrar a busca")
    parser.add_argument("--busca", default="", help="termo de pesquisa")
    parser.add_argument("--leilao", action="append", dest="leiloes",
                        help="id de um leilão; pode repetir")
    parser.add_argument("--paginas", type=int, default=PAGINAS_PADRAO,
                        help=f"teto de páginas por rota (padrão: {PAGINAS_PADRAO})")
    args = parser.parse_args()

    rotas = [r for r, ligada in (("abertos", args.abertos), ("pos", args.pos),
                                 ("historico", args.historico)) if ligada]
    if not rotas and not args.leiloes:
        rotas = ["abertos"]

    categorias = list(args.categorias or [])
    if args.segmento:
        categorias += [c for c in fontes.categorias_do_segmento(args.segmento)
                       if c not in categorias]
    coletar(rotas, args.busca, categorias, args.leiloes, args.paginas, args.uf)
