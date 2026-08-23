"""Mede a lacuna de publicação no PNCP cruzando com o Diário Oficial.

A pergunta: o Município divulgou no PNCP o que ele mesmo publicou no seu Diário?

O Diário é a fonte de comparação certa porque nele está o volume — extratos de
contrato, de aditivo e de ata de registro de preços saem ali desde 2015. Mas os
extratos NÃO estão segmentados no acervo do Diário (não têm cabeçalho numerado
no padrão dos atos), então é preciso extraí-los do texto da página.

TRÊS CUIDADOS, cada um vindo de uma medição:

1. **O vocabulário varia, e buscar uma forma só perde quase tudo.** "extrato de
   contrato" acha 162 páginas; a forma dominante é "EXTRATO DE TERMO DE
   CONTRATO", com 650 ocorrências, e há 172 formas distintas de cabeçalho.

2. **Cabeçalho e citação têm a mesma forma.** "EXTRATO NO DIÁRIO OFICIAL. VALOR
   TOTAL: R$ …" e "EXTRATO CONTRATUAL NO VEÍCULO OFICIAL DE DIVULGAÇÃO" são
   cláusulas de dentro do contrato, não cabeçalhos de extrato. Contá-las infla
   o Diário e exagera a lacuna — erro que favorece a conclusão que se quer, e
   por isso o mais perigoso aqui.

3. **Republicação é rotina no Diário de Mesquita.** O mesmo extrato sai duas
   vezes. Por isso conta-se o contrato distinto (tipo + número + ano), e a
   contagem crua de ocorrências vem junto, para que a diferença fique à vista.

E o recorte temporal, que decide se o número significa alguma coisa: a Lei
14.133/2021 só passou a ser de uso obrigatório em **01/01/2024** (art. 191, com
a prorrogação da LC 198/2023). Contrato regido pela Lei 8.666/93, assinado antes
disso, não tinha de ir ao PNCP — e seus aditivos seguem o regime de origem.
Por isso o confronto que vale é de 2024 em diante; a série inteira aparece só
para dar contexto.

Uso:  python cruzar_dom.py
"""

from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path

def _banco_do_dom() -> Path:
    """O acervo do Diário mudou de disco em 23/08/2026 — e este caminho era fixo.

    Estava escrito com a letra `C:` e o nome do usuário dentro, sem alternativa:
    mover a pasta para o HD externo quebraria este script em silêncio, na
    primeira execução depois da mudança. Segue a mesma ordem que o servidor do
    `diarios-mesquita` já usa — variável de ambiente, HD externo, casa.
    """
    do_ambiente = os.environ.get("DIARIOS_BANCO")
    candidatos = ([Path(do_ambiente)] if do_ambiente else []) + [
        Path("D:/Mesquita_Diarios_Oficiais/acervo.db"),
        Path.home() / "Mesquita_Diarios_Oficiais" / "acervo.db",
    ]
    for caminho in candidatos:
        if caminho.exists():
            return caminho
    # Nenhum existe: devolve o primeiro para a mensagem de erro citar um
    # caminho concreto, em vez de falhar com `None`.
    return candidatos[0]


DOM = _banco_do_dom()
ACERVO = Path(__file__).resolve().parent / "dados" / "acervo.db"

# Primeiro exercício em que a divulgação no PNCP é exigível de todo contrato.
PRIMEIRO_ANO_EXIGIVEL = 2024

# Desligável só para comparar com o extrator sem junção de páginas — é assim
# que se mede o efeito de uma correção registro a registro, e não pelo total.
JUNTAR_PAGINAS = True

CABECALHO = re.compile(r"^[ \t]*(EXTRATO\b[^\n]{0,70})$", re.IGNORECASE | re.MULTILINE)

# Formas que TÊM cara de cabeçalho e não são: são cláusulas de dentro do
# contrato, falando da própria publicação. Validar antes de delimitar (o
# candidato descartado tarde já serviu de fronteira para o anterior).
CITACAO = re.compile(
    r"EXTRATO\s+(NO|NA|CONTRATUAL|DESTE|DA?\s+PRESENTE)\b"
    # a janela precisa ser larga: "extrato do contrato no instrumento de
    # imprensa oficial" põe 31 caracteres entre as duas palavras, e com 20
    # a cláusula passava por cabeçalho.
    r"|EXTRATO\b.{0,45}?(VE[IÍ]CULO|IMPRENSA|JORNAL|DI[ÁA]RIO\s+OFICIAL)"
    r"|EXTRATO\s+D[OA]S\b", re.IGNORECASE)

# Um cabeçalho de extrato é escrito em caixa alta neste Diário; a cláusula
# citada, não. Medir antes de aplicar: o mesmo critério, no acervo de
# legislação, descartava 15% dos atos legítimos e teve de ser abandonado.
def _e_caixa_alta(linha: str) -> bool:
    letras = [c for c in linha if c.isalpha()]
    if not letras:
        return False
    return sum(1 for c in letras if c.isupper()) / len(letras) >= 0.8

TIPOS = [
    # ordem importa: 'termo aditivo' antes de 'contrato', porque o cabeçalho do
    # aditivo quase sempre menciona o contrato a que adita.
    ("aditivo", re.compile(r"ADITIV|APOSTILAMENT|RERRATIFICA", re.IGNORECASE)),
    ("rescisao", re.compile(r"RESCIS", re.IGNORECASE)),
    ("ata", re.compile(r"ATA\s+DE\s+REGISTRO", re.IGNORECASE)),
    ("convenio", re.compile(r"CONV[EÊ]NIO|COOPERA[ÇC][AÃ]O|CREDENCIAMENT",
                            re.IGNORECASE)),
    ("divida", re.compile(r"RECONHECIMENTO\s+DE\s+D[IÍ]VIDA", re.IGNORECASE)),
    ("contrato", re.compile(r"CONTRATO|CONTRATUAL", re.IGNORECASE)),
]

# O identificador vem logo abaixo do cabeçalho: "… Nº 008/2025."
#
# A pontuação tem de ser tratada com folga. A primeira versão era
# `N[ºO°\.]?\s*` — uma classe com UM símbolo opcional — e o Diário escreve
# "CONTRATO ADMINISTRATIVO Nº. 034/2025", com ponto DEPOIS do `º`. Resultado:
# 7 dos 18 contratos que o PNCP registra não eram achados no Diário, e a lacuna
# medida saía inflada. O erro só apareceu na conferência de sentido inverso —
# nenhuma contagem agregada o denunciaria.
# A pontuação varia nas duas posições, e cada variante me custou registros:
#   "Nº 008/2025"   "Nº. 034/2025"   "N.º 019/2006"   "N° 042/2011"
# Por isso ponto opcional ANTES e DEPOIS do ordinal, em vez de uma classe de
# um símbolo só.
NUMERO = re.compile(r"N\s*\.?\s*[ºO°]?\s*\.?\s*(\d{1,4})\s*/\s*(\d{4})",
                    re.IGNORECASE)

# E há extrato que dispensa o "Nº": "CONTRATO DE LOCAÇÃO 005/2015. PARTES: …".
# Só se usa quando o padrão principal falha, e exige a palavra do tipo logo
# antes, para não capturar número de processo ou de lei que passe por perto.
NUMERO_SEM_N = re.compile(
    r"(?:CONTRATO|ATA|TERMO|CONV[EÊ]NIO|ADITIVO|LOCA[ÇC][AÃ]O)[^\d\n]{0,40}?"
    r"(\d{1,4})\s*/\s*(\d{4})", re.IGNORECASE)


def _numero(corpo: str) -> tuple[int, int] | None:
    m = NUMERO.search(corpo) or NUMERO_SEM_N.search(corpo)
    return (int(m.group(1)), int(m.group(2))) if m else None
ASSINATURA = re.compile(r"DATA\s+DE\s+ASSINATURA:?\s*(\d{2}/\d{2}/\d{4})",
                        re.IGNORECASE)

# O regime legal é o que decide se o PNCP era exigível daquele contrato, e o
# próprio extrato costuma declará-lo em "FUNDAMENTO LEGAL". Medido: em 2024 o
# Município ainda assinava sob a Lei 8.666/93 em 100 extratos contra 9 sob a
# 14.133 — sem essa separação, o confronto de 2024 mede a transição de regime e
# não o cumprimento do dever de divulgar.
LEI_14133 = re.compile(r"14\.?133")
LEI_8666 = re.compile(r"8\.?666")


def _regime(corpo: str) -> str:
    if LEI_14133.search(corpo):
        return "14.133"
    if LEI_8666.search(corpo):
        return "8.666"
    return "nao_declarado"


# Toda página do Diário abre com expediente:
#   www.mesquita.rj.gov.br / E-mail: … / <nº da página>
#   Mesquita, Terça-feira, 23 de agosto de 2018 | Nº 00581.
# Ao juntar páginas, isso entra no meio do extrato. Precisa sair por dois
# motivos: come metade da janela de 260 caracteres onde se procura o número, e
# traz um "Nº 00581" que é o número da EDIÇÃO. Ele não casa o padrão de
# identificador (que exige NNN/AAAA), mas depender disso seria contar com sorte.
EXPEDIENTE = re.compile(r"^.{0,300}?\|\s*N[ºO°]?\s*\d{3,6}\.?\s*",
                        re.DOTALL | re.IGNORECASE)


def _sem_expediente(texto: str) -> str:
    return EXPEDIENTE.sub("", texto, count=1)


def _achatar(texto: str) -> str:
    """O PDF quebra linha no meio da frase (extração em coluna). Sem achatar,
    nenhum regex de número funciona."""
    return re.sub(r"\s+", " ", texto)


def _classificar(cabecalho: str, corpo: str) -> str:
    alvo = f"{cabecalho} {corpo[:200]}"
    for nome, padrao in TIPOS:
        if padrao.search(alvo):
            return nome
    return "outro"


def extrair_do_diario() -> list[dict]:
    con = sqlite3.connect(f"file:{DOM}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    linhas = con.execute("""SELECT p.id, p.edicao_id, p.pagina, p.texto, p.origem,
                                   e.data, e.numero edicao
                            FROM pagina_fts f
                            JOIN pagina p ON p.id = f.rowid
                            JOIN edicao e ON e.id = p.edicao_id
                            WHERE pagina_fts MATCH 'extrato'""").fetchall()

    # O extrato pode começar no rodapé de uma página e continuar na seguinte —
    # e a seguinte não contém a palavra "extrato", então não vem na consulta
    # acima. Daí carregar o início de TODAS as páginas.
    seguinte = {(r["edicao_id"], r["pagina"]): r["inicio"] for r in con.execute(
        "SELECT edicao_id, pagina, substr(texto, 1, 900) inicio FROM pagina")}

    extratos: list[dict] = []
    for linha in linhas:
        texto = linha["texto"]
        # Fase 1: achar candidatos e VALIDAR antes de usar como fronteira.
        validos = [m for m in CABECALHO.finditer(texto)
                   if not CITACAO.search(m.group(1))]
        for i, m in enumerate(validos):
            ultimo = i + 1 == len(validos)
            fim = len(texto) if ultimo else validos[i + 1].start()
            corpo = _achatar(texto[m.end():fim])
            cabecalho = re.sub(r"\s+", " ", m.group(1).strip())
            if not _e_caixa_alta(cabecalho):
                continue

            # Só o ÚLTIMO extrato da página pode continuar na seguinte, e só se
            # o que sobrou for curto demais para trazer o identificador. Estender
            # os que já estão completos arriscaria colar neles a sobra de outro
            # ato que abra a página seguinte — trocar o número é pior que perdê-lo.
            if JUNTAR_PAGINAS and ultimo and len(corpo.strip()) < 260:
                proxima = seguinte.get((linha["edicao_id"], linha["pagina"] + 1))
                if proxima:
                    continuacao = _sem_expediente(proxima)
                    # a continuação termina onde começar outro extrato
                    corte = CABECALHO.search(continuacao)
                    if corte:
                        continuacao = continuacao[:corte.start()]
                    corpo = (corpo + " " + _achatar(continuacao)).strip()
            # A janela de 260 caracteres é deliberada. Além dela o texto já é
            # de outro ato — medido: um extrato sem número próprio "achava" o
            # "AVISO DE LICITAÇÃO CONVITE Nº 005/2015" a 816 caracteres e
            # levaria o número alheio. Perder o número é lacuna; trocá-lo por
            # outro é falsificação.
            # O identificador às vezes está no próprio cabeçalho
            # ("EXTRATO CONTRATO DE LOCAÇÃO N° 092/2024") e às vezes só no
            # corpo. Procurar nos dois, cabeçalho primeiro.
            num = _numero(cabecalho) or _numero(corpo[:260])
            ass = ASSINATURA.search(corpo)
            extratos.append({
                "data_edicao": linha["data"],
                "ano_edicao": int(linha["data"][:4]),
                "origem": linha["origem"],
                "cabecalho": cabecalho,
                "tipo": _classificar(m.group(1), corpo),
                "numero": num[0] if num else None,
                "ano_ato": num[1] if num else None,
                "assinatura": ass.group(1) if ass else None,
                "regime": _regime(corpo),
            })
    return extratos


TITULO_NUM = re.compile(r"n[ºo°\.]?\s*(\d{1,4})\s*/\s*(\d{4})", re.IGNORECASE)


def documentos_do_pncp() -> list[dict]:
    con = sqlite3.connect(f"file:{ACERVO}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    saida = []
    for r in con.execute(
            """SELECT tipo, ano, titulo, numero_controle_pncp, data_assinatura,
                      valor_global, descricao
               FROM pncp_documento WHERE orgao_nome = 'MUNICIPIO DE MESQUITA'"""):
        m = TITULO_NUM.search(r["titulo"] or "")
        saida.append({**dict(r),
                      "numero": int(m.group(1)) if m else None,
                      "ano_ato": int(m.group(2)) if m else int(r["ano"])})
    return saida


def conferir_subconjunto(extratos: list[dict], pncp: list[dict]) -> None:
    """A validação que vale mais que a contagem agregada.

    Se o extrator do Diário presta, todo contrato que está no PNCP tem de estar
    também no Diário — a publicação no Diário é anterior e mais antiga que a
    obrigação do PNCP. Achar no PNCP algo que o Diário não tem não prova lacuna
    nenhuma: prova que o meu extrator está cego, e que a lacuna medida está
    inflada pelo lado errado.
    """
    no_dom = {(e["tipo"], e["numero"], e["ano_ato"]) for e in extratos
              if e["numero"] is not None}
    print("\n" + "=" * 78)
    print("VALIDAÇÃO — o que está no PNCP aparece no Diário?")
    print("=" * 78)
    faltando = []
    for d in pncp:
        if d["tipo"] not in ("contrato", "ata") or d["numero"] is None:
            continue
        if (d["tipo"], d["numero"], d["ano_ato"]) not in no_dom:
            faltando.append(d)
    achados = sum(1 for d in pncp if d["tipo"] in ("contrato", "ata")
                  and d["numero"] is not None) - len(faltando)
    print(f"  encontrados no Diário: {achados}")
    print(f"  NÃO encontrados:       {len(faltando)}")
    for d in faltando[:10]:
        print(f"     {d['tipo']:<9} {d['titulo']:<28} "
              f"assinado {d['data_assinatura']}")
    if faltando:
        print("  → cada um destes é ponto cego do extrator do Diário, não lacuna")
        print("    do Município. A porcentagem abaixo está subestimada na mesma")
        print("    medida, e não deve ser citada sem esta ressalva.")


def main() -> None:
    extratos = extrair_do_diario()
    pncp_docs = documentos_do_pncp()
    pncp: dict[tuple[str, str], int] = defaultdict(int)
    for d in pncp_docs:
        pncp[(d["tipo"], str(d["ano_ato"]))] += 1

    print(f"Extratos localizados no Diário Oficial: {len(extratos):,}".replace(",", "."))
    sem_numero = sum(1 for e in extratos if e["numero"] is None)
    ocr = sum(1 for e in extratos if e["origem"] != "pdf")
    print(f"  sem número identificável: {sem_numero:,} "
          f"({100*sem_numero/len(extratos):.1f}%)".replace(",", "."))
    print(f"  em página reconhecida por OCR: {ocr:,}".replace(",", "."))

    print("\nPor tipo:")
    por_tipo: dict[str, int] = defaultdict(int)
    for e in extratos:
        por_tipo[e["tipo"]] += 1
    for tipo, n in sorted(por_tipo.items(), key=lambda x: -x[1]):
        print(f"  {tipo:<12} {n:>6}")

    # --- o confronto -------------------------------------------------------
    # Unidade: o ato distinto (tipo + número + ano), não a ocorrência, porque
    # republicação é rotina neste Diário.
    conferir_subconjunto(extratos, pncp_docs)

    print("\n" + "=" * 78)
    print("CONFRONTO — atos distintos no Diário Oficial × registros no PNCP")
    print("=" * 78)
    print("Agrupado pelo ANO DO ATO (008/2025 conta em 2025 mesmo que publicado")
    print("em 2026), porque é assim que o PNCP numera. Agrupar pelo ano da")
    print("edição deslocaria os dois lados um em relação ao outro.\n")
    print(f"{'ano':<6}{'tipo':<11}{'DOM (distintos)':>17}{'DOM (ocorr.)':>14}"
          f"{'PNCP':>7}{'lacuna':>9}")
    print("-" * 78)

    mapa_pncp = {"contrato": "contrato", "ata": "ata"}
    total_dom = total_pncp = 0

    for ano in range(2015, 2027):
        for tipo in ("contrato", "ata", "aditivo"):
            do_ano = [e for e in extratos
                      if e["ano_ato"] == ano and e["tipo"] == tipo]
            if not do_ano:
                continue
            distintos = {(e["tipo"], e["numero"], e["ano_ato"]) for e in do_ano}
            n_pncp = pncp.get((mapa_pncp.get(tipo, tipo), str(ano)), 0)
            exigivel = ano >= PRIMEIRO_ANO_EXIGIVEL and tipo in mapa_pncp
            if exigivel:
                lacuna = len(distintos) - n_pncp
                marca = f"{lacuna:>9}" if lacuna > 0 else f"{'—':>9}"
                total_dom += len(distintos)
                total_pncp += n_pncp
            else:
                marca = f"{'n/e':>9}"
            print(f"{ano:<6}{tipo:<11}{len(distintos):>17}{len(do_ano):>14}"
                  f"{n_pncp:>7}{marca}")

    print("-" * 78)
    print(f"Bruto, de {PRIMEIRO_ANO_EXIGIVEL} em diante: {total_dom} contratos e "
          f"atas distintos no Diário, {total_pncp} no PNCP.")
    print("\n'n/e' = não exigível: antes de 2024 a Lei 14.133/2021 ainda não era")
    print("de uso obrigatório, e aditivo segue o regime do contrato de origem.")

    # --- o confronto que de fato se sustenta -------------------------------
    print("\n" + "=" * 78)
    print("O CONFRONTO QUE SE SUSTENTA — só contratos que declaram a Lei 14.133")
    print("=" * 78)
    print("O número bruto acima mede a transição de regime junto com o dever de")
    print("divulgar, e por isso exagera. Contrato regido pela Lei 8.666/93 não")
    print("tinha de ir ao PNCP. Abaixo, os contratos separados pelo regime que o")
    print("próprio extrato declara.\n")
    print(f"{'ano':<6}{'14.133':>9}{'8.666':>8}{'não declara':>13}{'PNCP':>7}"
          f"{'lacuna mín.':>13}")
    print("-" * 78)

    # O abatimento tem de ser feito contrato a contrato, não por subtração de
    # totais. Medido: dos 20 registros do PNCP, dois são "Empenho nº …" (o
    # art. 95 da Lei 14.133 admite substituir o termo de contrato pela nota de
    # empenho, e por isso eles não têm extrato de contrato no Diário), um
    # corresponde a contrato que declara a Lei 8.666 e dois a contratos que não
    # declaram regime. Subtrair 20 da coluna 14.133 abateria cinco vezes da
    # coluna errada e encolheria a lacuna sem razão.
    indice_dom = {}
    for e in extratos:
        if e["tipo"] == "contrato" and e["numero"] is not None:
            indice_dom.setdefault((e["numero"], e["ano_ato"]), set()).add(e["regime"])

    abatimento: dict[int, int] = defaultdict(int)
    empenhos = fora_do_14133 = 0
    for d in pncp_docs:
        if d["tipo"] != "contrato":
            continue
        # A checagem do empenho vem ANTES da do número: "Empenho nº 035" não
        # traz "/ano", então cairia fora por falta de número e sumiria da
        # contagem em vez de ser explicado.
        if re.search(r"empenho", d["titulo"] or "", re.IGNORECASE):
            empenhos += 1
            continue
        if d["numero"] is None:
            continue
        if "14.133" in indice_dom.get((d["numero"], d["ano_ato"]), set()):
            abatimento[d["ano_ato"]] += 1
        else:
            fora_do_14133 += 1

    for ano in range(PRIMEIRO_ANO_EXIGIVEL, 2027):
        do_ano = [e for e in extratos
                  if e["ano_ato"] == ano and e["tipo"] == "contrato"]
        if not do_ano:
            continue
        por_regime: dict[str, set] = defaultdict(set)
        for e in do_ano:
            por_regime[e["regime"]].add((e["numero"], e["ano_ato"]))
        n_pncp = pncp.get(("contrato", str(ano)), 0)
        lacuna = max(0, len(por_regime["14.133"]) - abatimento[ano])
        print(f"{ano:<6}{len(por_regime['14.133']):>9}{len(por_regime['8.666']):>8}"
              f"{len(por_regime['nao_declarado']):>13}{n_pncp:>7}{lacuna:>13}")

    print("-" * 78)
    total_14133 = sum(len({(e["numero"], e["ano_ato"]) for e in extratos
                           if e["tipo"] == "contrato" and e["ano_ato"] == ano
                           and e["regime"] == "14.133"})
                      for ano in range(PRIMEIRO_ANO_EXIGIVEL, 2027))
    total_abatido = sum(abatimento.values())
    print(f"Contratos que declaram a Lei 14.133 de {PRIMEIRO_ANO_EXIGIVEL} "
          f"em diante: {total_14133}")
    print(f"  desses, localizados no PNCP:  {total_abatido}")
    print(f"  NÃO localizados no PNCP:      {total_14133 - total_abatido}")
    print(f"\nDos {len([d for d in pncp_docs if d['tipo']=='contrato'])} registros "
          f"de contrato no PNCP, {empenhos} são notas de empenho (art. 95 da Lei")
    print(f"14.133 — sem termo de contrato, logo sem extrato no Diário) e "
          f"{fora_do_14133} correspondem")
    print("a contratos que no Diário declaram a Lei 8.666 ou não declaram regime.")
    print("\nA coluna 'lacuna mín.' é piso, não estimativa: deixa de fora os")
    print("contratos que não declaram regime — qualquer um deles pode ser da")
    print("14.133 e estar faltando também. O número real é maior ou igual a ele.")
    print("\nDois limites do lado do Diário, ambos empurrando o resultado para baixo:")
    sem_num = sum(1 for e in extratos if e['numero'] is None)
    print(f"  · {sem_num} extratos ({100*sem_num/len(extratos):.1f}%) não têm número")
    print("    identificável e não entram em nenhuma contagem de distintos;")
    print("  · extratos de tipos diferentes com o mesmo número (contrato")
    print("    administrativo e contrato de locação) colapsam num só.")


if __name__ == "__main__":
    main()
