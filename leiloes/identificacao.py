"""Lê a descrição de um lote e diz QUAL peça é — ou declara que não sabe.

Este é o núcleo do acervo, e o lugar onde ele pode errar caro. Nos leilões de
numismática e filatelia o lote é descrito em texto livre por quem quer vender,
não por quem quer catalogar. "1000 Réis 1913, prata, soberba" parece uma
identificação completa e não é: em 1913 o Brasil cunhou DUAS séries distintas,
e os martelos de uma não servem de comparável para a outra.

A regra da casa vale aqui como vale no SICONFI do acervo financeiro: onde o
vínculo não se prova, ele NÃO é presumido. Uma peça que a descrição não
determina sai com `confianca='indefinida'` e um motivo legível, e o motor de
assimetria se recusa a pontuá-la. Preferimos um lote sem nota a um lote com
nota errada — a nota errada é a que faz alguém dar lance.

O que se extrai, e de onde:

    codigo de catálogo   KM#, Bentes, Amato, RHM, Scott — quando o próprio
                         texto o traz. Nunca deduzido.
    ano                  algarismo de quatro casas, com a armadilha do "1000
                         réis" desarmada (ver _anos).
    denominação          inclusive a notação de mil-réis, 1$000 = 1000 réis.
    metal                ouro, prata, níquel, bronze, cobre, alumínio, aço.
    grau                 escala brasileira (FC, S, MBC, BC, R, U) e a Sheldon
                         das encapsuladoras (NGC/PCGS MS-65 etc.).

O que NÃO se extrai, de propósito: preço de catálogo e raridade. Nenhum dos
dois está na descrição do lote, e ambos viriam de memória — que é justamente
a fonte que este repositório não aceita em lugar nenhum.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent

# --------------------------------------------------------------------- escalas

# Escala brasileira, do melhor para o pior. O número é ORDEM, não preço: serve
# para dizer que MBC é pior que S e para achar o grau vizinho. Interpolar preço
# entre graus com ele seria inventar o multiplicador, e o multiplicador entre
# MBC e FC muda de moeda para moeda — é a diferença entre dobrar e vintuplicar.
GRAUS_BR: dict[str, int] = {
    "FC": 70, "S/FC": 65, "S": 60, "MBC/S": 52, "MBC": 45,
    "BC/MBC": 38, "BC": 30, "R/BC": 22, "R": 15, "U": 8,
}

# Sheldon, usada pelas encapsuladoras. MS/PF 60-70, AU 50-58, XF 40-45,
# VF 20-35, F 12-15, VG 8-10, G 4-6.
SHELDON = re.compile(
    r"\b(NGC|PCGS|PMG|SGS|ANACS|ICG)?\s*"
    r"(MS|PF|PR|PL|AU|XF|EF|VF|VG|AG|F|G)\s*[-–]?\s*(\d{1,2})\b",
    re.IGNORECASE)

# Os tokens da escala brasileira aparecem soltos no meio da frase. A busca é
# por palavra inteira: sem \b, o "S" de "Soberba" casa dentro de "Prata".
_GRAU_BR = re.compile(
    r"(?<![A-Za-zÀ-ÿ/])(FC|S/FC|MBC/S|BC/MBC|R/BC|MBC|BC|SOB|FE|S|R|U)"
    r"(?![A-Za-zÀ-ÿ/])")

# Por extenso — é como a maioria das casas escreve.
GRAU_POR_EXTENSO = {
    "flor de cunho": "FC", "soberba": "S", "muito bem conservada": "MBC",
    "muito bem conservado": "MBC", "bem conservada": "BC", "bem conservado": "BC",
    "regular": "R", "utilizada": "U", "utilizado": "U",
}

# ------------------------------------------------------------------- catálogos

# Cada padrão devolve (catalogo, codigo). Só reconhece o código que o texto
# TRAZ — nenhum destes converte um catálogo em outro, porque a equivalência
# entre KM e Bentes não é biunívoca e não está neste acervo.
CATALOGOS: list[tuple[str, re.Pattern[str]]] = [
    ("KM",      re.compile(r"\bKM\s*#?\s*[-–]?\s*(\d{1,4}[a-zA-Z]?(?:\.\d{1,2})?)\b")),
    ("Bentes",  re.compile(r"\bBentes\s*#?\s*[-–]?\s*(\d{1,3}\.\d{1,3}[a-zA-Z]?)\b",
                           re.IGNORECASE)),
    ("Amato",   re.compile(r"\bAmato\s*#?\s*[-–]?\s*([A-Z]?[-–]?\d{1,4}[a-zA-Z]?)\b",
                           re.IGNORECASE)),
    ("RHM",     re.compile(r"\bRHM\s*#?\s*[-–]?\s*([CAODTVEP]?)\s*[-–]?\s*(\d{1,4}[a-zA-Z]?)\b",
                           re.IGNORECASE)),
    ("Scott",   re.compile(r"\bScott\s*#?\s*[-–]?\s*(\d{1,4}[a-zA-Z]?)\b", re.IGNORECASE)),
    ("Gomes",   re.compile(r"\bGomes\s*#?\s*[-–]?\s*(\d{1,4}[a-zA-Z]?)\b", re.IGNORECASE)),
    # Citação genérica "Cat.<sigla>.<número>", que as casas usam para catálogos
    # que este acervo não conhece pelo nome. Colhida de título real de lote:
    #   "Moeda do Brasil - 1.000 Réis 1888 - Prata - … - Cat.AI.P.654"
    #
    # A sigla é guardada como veio, SEM traduzir para um catálogo conhecido: não
    # se sabe o que "AI.P" designa, e adivinhar produziria equivalência falsa
    # entre catálogos. Para o comparável basta que a citação seja estável — dois
    # lotes que citem o mesmo código são a mesma peça, qualquer que seja a obra.
    ("Cat",     re.compile(r"\bCat\.?\s*([A-Z][A-Za-z]{0,4}(?:\.[A-Z][A-Za-z]{0,4})*"
                           r"\.?\s*\d{1,5}[a-zA-Z]?)\b")),
]

# --------------------------------------------------------------------- léxicos

METAIS = {
    "ouro": "ouro", "au": "ouro", "prata": "prata", "ag": "prata",
    "niquel": "níquel", "cuproniquel": "cuproníquel", "cupro-niquel": "cuproníquel",
    "bronze": "bronze", "bronze-aluminio": "bronze-alumínio",
    "cobre": "cobre", "aluminio": "alumínio", "aco": "aço",
    "latao": "latão", "bimetalica": "bimetálica", "bimetalico": "bimetálica",
}

# Notação de mil-réis: 1$000 é mil réis, 20$000 é vinte mil réis. Aparece muito
# em lote de Império, e sem ela a denominação sai vazia justamente nas peças
# mais caras do acervo.
_MIL_REIS = re.compile(r"\b(\d{1,3})\$(\d{3})\b")

# O ponto de milhar tem de vir ANTES da forma sem ponto na alternância, e isso
# não é estilo: sem ele, "1.000 Réis" casava só "000 Réis" e a peça saía como
# "0 réis". O erro alcançava justamente as moedas caras — 1.000, 2.000, 6.400,
# 12.800 réis, que é como o Império e a Colônia se escrevem —, e produzia chave
# de comparação errada em silêncio. Achado no primeiro título real de lote que
# este acervo viu: "Moeda do Brasil - 1.000 Réis 1888 - Prata".
_DENOMINACAO = re.compile(
    r"\b(\d{1,3}(?:\.\d{3})+|\d{1,6})\s*"
    r"(r[ée]is|centavos?|cruzeiros?\s*novos?|cruzeiros?|"
    r"cruzados?\s*novos?|cruzados?|reais?)\b", re.IGNORECASE)

# Ano de cunho. O recorte 1500-2029 é largo de propósito (há lote colonial), e
# a exclusão à direita desarma a armadilha central: em "1000 Réis 1913" o 1000
# NÃO é ano, e em "5000 Reis" o 5000 tampouco. Sem o lookahead negativo, todo
# lote de mil-réis ganhava um ano inventado — e ano inventado casa comparável
# de peça errada, que é o modo mais caro de errar neste acervo.
_ANO = re.compile(r"\b(1[5-9]\d{2}|20[0-2]\d)\b(?!\s*(?:r[ée]is|reis|\$))",
                  re.IGNORECASE)

# Filatelia: o que separa um selo de uma moeda no mesmo pregão.
_SELO = re.compile(
    r"\b(selos?|filatel|carimbo|sobrecarga|denteado|n[aã]o[- ]denteado|"
    r"picotad|goma|charneira|bloco|s[ée]rie completa|envelope|"
    r"primeiro dia|FDC|olho[- ]de[- ]boi|inclinados?|bissect)\b", re.IGNORECASE)
_CEDULA = re.compile(r"\b(c[ée]dula|nota|papel[- ]moeda|estampa)\b", re.IGNORECASE)

# O eixo de conservação do selo NÃO é a escala da moeda. Em filatelia o que
# define a faixa de preço é o estado da goma, e "novo sem charneira" pode valer
# múltiplos de "novo com charneira" da mesma emissão. Medir selo com FC/S/MBC
# seria aplicar a régua de outro mercado.
#
# A ordem desta lista é a ordem de teste, e ela importa: "sem charneira" tem de
# ser vista antes de "charneira", senão toda peça sem charneira é lida como
# tendo uma — que é o erro que transforma a peça cara na barata.
ESTADO_SELO: list[tuple[str, tuple[str, ...]]] = [
    ("novo sem charneira", ("sem charneira", "mnh", "n/n", " nn ", "goma integra",
                            "goma original intacta")),
    ("novo com charneira", ("com charneira", "charneira", " mh ", "vestigio de charneira")),
    ("sem goma",           ("sem goma", "regomado", "regomada", "sem cola")),
    ("primeiro dia",       ("primeiro dia", " fdc", "envelope comemorativo")),
    ("usado",              ("usado", "usada", "carimbado", "carimbada", "circulado",
                            "circulada", "obliterado", "obliterada")),
]


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def _carregar_armadilhas() -> list[dict[str, Any]]:
    """Casos medidos em que a descrição típica NÃO determina a peça.

    Fica em arquivo, e não no código, porque a lista cresce com o que o próprio
    acervo mostrar: toda vez que dois lotes com a mesma descrição arrematarem
    em faixas incompatíveis, há uma armadilha nova a declarar aqui.
    """
    caminho = RAIZ / "armadilhas.json"
    if not caminho.exists():
        return []
    return json.loads(caminho.read_text(encoding="utf-8"))


ARMADILHAS = _carregar_armadilhas()


# ------------------------------------------------------------------- extração

def _graus(texto: str) -> tuple[str | None, str | None, int | None]:
    """Devolve (grau_br, certificadora, nota_sheldon).

    A peça encapsulada é outro produto que a mesma peça solta: o grau vem
    garantido por terceiro e o mercado paga por isso. Por isso a certificadora
    sai em campo próprio, e não diluída dentro do grau.
    """
    certificadora = nota = None
    m = SHELDON.search(texto)
    if m:
        certificadora = (m.group(1) or "").upper() or None
        nota = int(m.group(3))
        # "MS" sem casa não é grau; "MS-65" é. E 71+ não existe na escala.
        if not 1 <= nota <= 70:
            certificadora = nota = None

    sem_acento = _sem_acento(texto).lower()
    for frase, sigla in GRAU_POR_EXTENSO.items():
        if frase in sem_acento:
            return sigla, certificadora, nota

    achados = [g.upper() for g in _GRAU_BR.findall(texto)]
    # "SOB" e "FE" são grafias correntes de Soberba e Flor de Cunho.
    achados = ["S" if g == "SOB" else "FC" if g == "FE" else g for g in achados]
    validos = [g for g in achados if g in GRAUS_BR]
    if not validos:
        return None, certificadora, nota
    # Havendo mais de um, fica o PIOR: a casa que escreve "MBC/S" ou lista dois
    # graus está descrevendo o pior lado da peça, e supor o melhor é o erro que
    # infla a margem esperada.
    return min(validos, key=lambda g: GRAUS_BR[g]), certificadora, nota


def _codigos(texto: str) -> list[dict[str, str]]:
    achados = []
    for catalogo, padrao in CATALOGOS:
        for m in padrao.finditer(texto):
            grupos = [g for g in m.groups() if g]
            codigo = "-".join(g.upper().strip("-–") for g in grupos)
            achados.append({"catalogo": catalogo, "codigo": codigo,
                            "trecho": m.group(0).strip()})
    return achados


def _denominacao(texto: str) -> str | None:
    m = _MIL_REIS.search(texto)
    if m:
        return f"{int(m.group(1)) * 1000 + int(m.group(2))} réis"
    m = _DENOMINACAO.search(texto)
    if m:
        unidade = _sem_acento(m.group(2)).lower().rstrip("s")
        unidade = {"rei": "réis", "centavo": "centavos", "real": "réis",
                   "cruzeiro": "cruzeiros", "cruzado": "cruzados",
                   "cruzeiro novo": "cruzeiros novos",
                   "cruzado novo": "cruzados novos"}.get(unidade, m.group(2).lower())
        # A unidade é canonizada antes de concordar, e não depois: o texto da
        # casa escreve "1 Cruzeiro" e "1 cruzeiros" indiferentemente, e a chave
        # do comparável tem de sair igual nos dois casos.
        quantidade = int(m.group(1).replace(".", ""))
        if quantidade == 1 and unidade.endswith("s") and unidade != "réis":
            unidade = unidade[:-1] if " " not in unidade else \
                unidade.replace("s ", " ", 1).rstrip("s")
        return f"{quantidade} {unidade}"
    return None


def _metal(texto: str) -> str | None:
    sem_acento = _sem_acento(texto).lower()
    for chave, nome in METAIS.items():
        if re.search(rf"\b{re.escape(chave)}\b", sem_acento):
            return nome
    return None


def _anos(texto: str) -> list[int]:
    return sorted({int(a) for a in _ANO.findall(texto)})


def _especie(texto: str) -> str:
    if _SELO.search(texto):
        return "selo"
    if _CEDULA.search(texto):
        return "cédula"
    return "moeda"


def _estado_filatelico(texto: str) -> str | None:
    sem_acento = f" {_sem_acento(texto).lower()} "
    for estado, marcas in ESTADO_SELO:
        if any(m in sem_acento for m in marcas):
            return estado
    return None


def _estado(especie: str, texto: str, grau: str | None,
            certificadora: str | None, nota: int | None) -> str | None:
    """O eixo de conservação da espécie — a segunda metade da chave.

    Duas peças só são o mesmo produto se forem a mesma peça NO MESMO ESTADO.
    Sem estado não há chave, e sem chave não há comparável: é o mesmo motivo
    pelo qual o acervo financeiro não soma subfunção de uma coluna contra
    função de outra.
    """
    if especie == "selo":
        return _estado_filatelico(texto)
    if nota is not None:
        return f"{certificadora or 'slab'}{nota}"
    return grau


def _armadilha(dados: dict[str, Any], texto: str) -> dict[str, Any] | None:
    """Confere a peça contra a lista de ambiguidades declaradas."""
    sem_acento = _sem_acento(texto).lower()
    for regra in ARMADILHAS:
        quando = regra.get("quando", {})
        if "ano" in quando and quando["ano"] not in dados["anos"]:
            continue
        if "especie" in quando and quando["especie"] != dados["especie"]:
            continue
        if "denominacao_em" in quando:
            if dados["denominacao"] not in quando["denominacao_em"]:
                continue
        if "texto_contem" in quando:
            if not any(t in sem_acento for t in quando["texto_contem"]):
                continue
        # A armadilha só desarma se o discriminante estiver escrito.
        if any(d in sem_acento for d in regra.get("desarmada_por", [])):
            continue
        return regra
    return None


def identificar(titulo: str, descricao: str = "") -> dict[str, Any]:
    """Identifica a peça de um lote. Nunca levanta; devolve o que provou.

    `confianca` é o que o motor de assimetria lê antes de decidir se pontua:

        firme       o texto traz código de catálogo E grau. É comparável.
        provavel    sem código, mas com espécie, ano, denominação e grau.
                    É comparável contra peças da mesma chave, com ressalva.
        indefinida  falta o que determina a peça, ou ela cai numa armadilha
                    declarada. NÃO é comparável, e não recebe nota.
    """
    texto = f"{titulo}\n{descricao}".strip()
    especie = _especie(texto)
    # A escala FC/S/MBC é de moeda e cédula. Rodá-la sobre um selo colhe o "S"
    # e o "U" soltos de qualquer frase e inventa um grau que a filatelia nem
    # usa — por isso ela não roda sobre selo.
    grau, certificadora, nota = (None, None, None) if especie == "selo" \
        else _graus(texto)
    dados: dict[str, Any] = {
        "especie": especie,
        "codigos": _codigos(texto),
        "anos": _anos(texto),
        "denominacao": _denominacao(texto),
        "metal": _metal(texto),
        "grau": grau,
        "certificadora": certificadora,
        "nota_certificada": nota,
        "estado": _estado(especie, texto, grau, certificadora, nota),
    }

    # Cada espécie se identifica por um conjunto próprio de campos. Exigir ano
    # e denominação de um selo — que se identifica pelo código de catálogo —
    # jogava fora a filatelia inteira na primeira versão deste arquivo.
    faltas: list[str] = []
    if not dados["estado"]:
        faltas.append("nenhum estado de conservação declarado"
                      + (" (goma/charneira/usado)" if especie == "selo"
                         else " (FC, S, MBC… ou grau de encapsuladora)"))
    if especie == "moeda":
        if not dados["anos"]:
            faltas.append("nenhum ano de cunho no texto")
        if not dados["denominacao"]:
            faltas.append("nenhuma denominação reconhecível")
    elif especie == "selo":
        if not dados["codigos"] and not dados["anos"]:
            faltas.append("nem código de catálogo nem ano de emissão — não há "
                          "por onde saber qual selo é")
    elif especie == "cédula":
        tem_discriminante = re.search(r"\b(estampa|assinaturas?|s[ée]rie)\b",
                                      texto, re.IGNORECASE)
        if not dados["codigos"] and not tem_discriminante and not dados["anos"]:
            faltas.append("sem código, sem estampa/série e sem ano — a cédula "
                          "não está determinada")
    if len(dados["anos"]) > 1:
        faltas.append(f"mais de um ano no texto ({dados['anos']}) — provável "
                      f"lote com várias peças, que não tem peça única a comparar")

    armadilha = _armadilha(dados, texto)
    if armadilha:
        dados["confianca"] = "indefinida"
        dados["motivo"] = armadilha["motivo"]
        dados["desarma_com"] = armadilha.get("desarmada_por", [])
    elif faltas:
        dados["confianca"] = "indefinida"
        dados["motivo"] = ("a descrição não determina a peça: "
                           + "; ".join(faltas) + ".")
    elif dados["codigos"]:
        dados["confianca"] = "firme"
        dados["motivo"] = None
    else:
        dados["confianca"] = "provavel"
        dados["motivo"] = ("sem código de catálogo no texto — a peça foi montada "
                           "a partir de espécie, ano, denominação, metal e grau. "
                           "Confira contra o catálogo antes de dar lance.")

    dados["chave"] = chave_da_peca(dados)
    return dados


def chave_da_peca(dados: dict[str, Any]) -> str | None:
    """A chave sob a qual dois lotes são o MESMO produto.

    Sem grau não há chave: a mesma moeda em MBC e em FC são mercadorias
    diferentes, e somá-las na mesma distribuição produz uma mediana que não
    descreve nenhuma das duas. Foi por isso que a chave não é só o código.
    """
    if dados.get("confianca") == "indefinida":
        return None
    estado = dados.get("estado")
    if not estado:
        return None

    if dados.get("codigos"):
        c = dados["codigos"][0]
        return f"{c['catalogo']}:{c['codigo']}|{estado}"

    partes = [dados["especie"],
              str(dados["anos"][0]) if dados["anos"] else "?",
              dados.get("denominacao") or "?",
              dados.get("metal") or "?"]
    return "|".join(partes) + f"|{estado}"


def grau_vizinho(grau: str) -> list[str]:
    """Graus imediatamente acima e abaixo, para exibir o comparável adjacente.

    Existe para MOSTRAR, nunca para converter. O acervo não guarda multiplicador
    entre graus porque ele não é constante entre peças, e aplicar um médio faria
    a nota parecer precisa exatamente onde ela é chute.
    """
    if grau not in GRAUS_BR:
        return []
    ordenados = sorted(GRAUS_BR, key=lambda g: GRAUS_BR[g])
    i = ordenados.index(grau)
    return [g for g in (ordenados[i - 1] if i > 0 else None,
                        ordenados[i + 1] if i + 1 < len(ordenados) else None) if g]
