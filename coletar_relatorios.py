"""Coleta os relatórios "Dados Abertos" do Portal da Transparência de Mesquita.

É a via oficial de exportação da própria tela — CSV, XLS ou ODS — acionada pela
regra Java que o portal usa quando alguém clica em "Relatório". Sem captcha e
sem autenticação nesta rota; a tela de Despesas tem captcha na ENTRADA do
formulário, mas a regra de relatório é outra coisa, e este script testa cada uma
e declara o que respondeu.

    POST /webrun/executeRule.do?action=executeRule&pType=2
         &ruleName=<regra>&sys=LAI&formID=<form>&P_0..P_n=<filtros>
      → caminho de WFRReports\\Generated\\<GUID>.CSV
      → servido em /ver20240713/WFRReports/Generated/<GUID>.CSV

As assinaturas vêm de `descobrir_relatorios.py`, que as lê do próprio pacote de
regras do portal. Rode-o antes.

Uso:  python coletar_relatorios.py --sondar          # só mede o que responde
      python coletar_relatorios.py                   # coleta de verdade
"""

from __future__ import annotations

import argparse
import csv
import http.cookiejar
import io
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

from fontes import gravar_bruto

BASE = "https://transparencia.mesquita.rj.gov.br/webrun/"
PUBLICO = "https://transparencia.mesquita.rj.gov.br/ver20240713/WFRReports/Generated/"
RAIZ = Path(__file__).resolve().parent
ASSINATURAS = RAIZ / "dados" / "relatorios.json"

CSV_ = "7"          # 2=PDF 4=TXT 5=XLS 6=RTF 7=CSV 8=ODT 9=CALC
FORM_PADRAO = "464569294"   # o de contratos; serve de portador para a chamada
UA = {"User-Agent": "financas-mesquita/0.1 (Procuradoria-Geral de Mesquita-RJ)"}

# Nomes de parâmetro que aceitam o exercício.
ANUAIS = {"ANO", "LOA_ANO", "EXERCICIO"}

# Remuneração NOMINAL de servidor — 357.671 linhas e 60 MB só na variante
# "Completo". É dado pessoal, e o acervo é publicado num repositório público:
# o fato de a Prefeitura divulgar no portal dela não decide, por si, o que se
# pode redistribuir num pacote sob outra identidade.
#
# **Decidido pelo Procurador em 05/08/2026: coletar e publicar junto**, pela
# leitura de que é transparência ativa já pública sob a LAI. A ressalva foi
# levantada antes e a decisão é dele; fica registrada aqui para que não pareça
# distração de quem leu o código depois.
#
# `--sem-folha-nominal` continua existindo para quem precisar montar um pacote
# sem esses dados (uma release enxuta, por exemplo).
FOLHA_NOMINAL = {
    "URL Relatorio - ServidoresxBrutoxLiquido",
    "URL Relatorio - ServidoresxBrutoxLiquido Camara",
    "URL Relatorio - ServidoresxBrutoxLiquido(Completo)",
    "URL Relatorio - ServidoresxBrutoxLiquido(Completo) - CF",
    "URL Relatorio - ServidoresxBrutoxLiquido(Completo) - Novo",
    "URL Relatorio - ServidoresxBrutoxLiquidoPrevide (Completo)",
}


def abrir_sessao(tentativas: int = 5) -> urllib.request.OpenerDirector:
    """Abre o formulário para ganhar sessão, com repetição.

    Sem repetição aqui, um soluço de rede na PRIMEIRA requisição derruba a
    execução inteira antes de coletar qualquer coisa — foi o que aconteceu
    rodando dois coletores em paralelo: `getaddrinfo failed` logo na abertura,
    e as duas horas seguintes de trabalho se perderam por causa de um DNS que
    voltou a responder em segundos.
    """
    ultimo: Exception | None = None
    for n in range(tentativas):
        try:
            op = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            op.addheaders = list(UA.items())
            for u in (f"{BASE}form.jsp?sys=LAI&action=openform&formID={FORM_PADRAO}",
                      f"{BASE}openform.do?sys=LAI&action=openform&formID={FORM_PADRAO}"):
                op.open(u, timeout=180).read()
            return op
        except Exception as e:                              # noqa: BLE001
            ultimo = e
            print(f"  sessão falhou ({e}); nova tentativa em {15 * (n + 1)}s")
            time.sleep(15 * (n + 1))
    raise SystemExit(f"não abriu sessão após {tentativas} tentativas: {ultimo}")


def gerar(op, regra: str, params: list[str], ano: str = "") -> tuple[str | None, str]:
    """Aciona a regra e devolve (url do arquivo, diagnóstico)."""
    q = {"action": "executeRule", "pType": "2", "ruleName": regra,
         "sys": "LAI", "formID": FORM_PADRAO, "parentRID": "",
         "decodedParams": "true"}
    for i, nome in enumerate(params):
        if re.fullmatch(r"Relatorio|RELATORIO|TIPO_RELATORIO", nome):
            q[f"P_{i}"] = CSV_
        elif nome in ANUAIS:
            q[f"P_{i}"] = ano
        else:
            q[f"P_{i}"] = ""

    try:
        # Gerar o relatório é a parte lenta: o servidor monta o arquivo inteiro
        # antes de responder com o caminho.
        resp = op.open(f"{BASE}executeRule.do?" + urllib.parse.urlencode(q),
                       data=b"", timeout=1800).read().decode("latin-1", "replace")
    except Exception as e:                                  # noqa: BLE001
        return None, f"falha de rede: {e}"

    if "WFRReports" in resp:
        arquivo = resp.split("WFRReports")[1].split("'")[0]
        arquivo = arquivo.replace("\\\\", "\\").split("\\")[-1]
        return PUBLICO + arquivo, "ok"

    # Erro tratado devolve mensagem legível dentro de showErrorMessage
    m = re.search(r'showErrorMessage\("[^"]*","([^"]*)"', resp)
    if m:
        return None, f"recusado: {m.group(1)}"
    if "captcha" in resp.lower() or "recaptcha" in resp.lower():
        return None, "exige captcha"
    return None, f"sem link (resposta de {len(resp)} caracteres)"


def baixar(op, url: str, tentativas: int = 3) -> bytes:
    """Baixa o arquivo gerado, com folga de tempo e repetição.

    O limite tem de ser generoso: `Consulta Programa Projeto Ação` devolve
    126 MB numa chamada só, e `ServidoresxBrutoxLiquido(Completo)` 60 MB. Com
    600 s a leitura estourava no meio e o relatório inteiro se perdia depois de
    o servidor já o ter gerado — desperdício dos dois lados.
    """
    ultimo: Exception | None = None
    for n in range(tentativas):
        try:
            return op.open(url, timeout=1800).read()
        except Exception as e:                              # noqa: BLE001
            ultimo = e
            time.sleep(10 * (n + 1))
    raise RuntimeError(f"não baixou após {tentativas} tentativas: {ultimo}")


def linhas_do_csv(bruto: bytes) -> int:
    return sum(1 for _ in csv.reader(io.StringIO(bruto.decode("latin-1"))))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sondar", action="store_true",
                   help="só mede o que responde, sem gravar")
    p.add_argument("--desde", type=int, default=2015)
    p.add_argument("--sem-folha-nominal", action="store_true",
                   help="exclui a remuneração nominal de servidor (dado "
                        "pessoal; ver FOLHA_NOMINAL)")
    p.add_argument("--so", metavar="TRECHO",
                   help="roda só as regras cujo nome contenha este trecho")
    args = p.parse_args()

    if not ASSINATURAS.exists():
        raise SystemExit("Rode `python descobrir_relatorios.py` antes.")
    assinaturas: dict[str, list[str]] = json.loads(
        ASSINATURAS.read_text(encoding="utf-8"))

    op = abrir_sessao()
    ate = date.today().year

    print(f"{'regra':<52}{'linhas':>9}  situação")
    print("-" * 92)
    vivos: dict[str, list[str]] = {}

    for regra in sorted(assinaturas):
        if args.so and args.so.lower() not in regra.lower():
            continue
        if regra in FOLHA_NOMINAL and args.sem_folha_nominal:
            print(f"{regra[:50]:<52}{'—':>9}  fora: remuneração nominal")
            continue
        params = assinaturas[regra]
        url, diag = gerar(op, regra, params)
        if not url:
            print(f"{regra[:50]:<52}{'—':>9}  {diag}")
            # Falhar SEM filtro não prova que a regra não sirva: medido,
            # `Consulta Programa Projeto Ação` devolve 500 na chamada sem ano e
            # funciona pedindo exercício a exercício. Antes, ela caía aqui e
            # nunca chegava à varredura anual — a regra mais volumosa do portal
            # ficava de fora por causa de uma chamada que ninguém precisava.
            if any(x in ANUAIS for x in params):
                vivos[regra] = params
            continue
        try:
            bruto = baixar(op, url)
            n = linhas_do_csv(bruto)
        except Exception as e:                              # noqa: BLE001
            print(f"{regra[:50]:<52}{'—':>9}  gerou mas não baixou: {e}")
            continue
        print(f"{regra[:50]:<52}{n:>9}  {len(bruto)/1024:.0f} KB")
        if n > 1:
            vivos[regra] = params
        if not args.sondar:
            nome = re.sub(r"[^A-Za-z0-9]+", "_", regra).strip("_").lower()
            gravar_bruto("portal_relatorios", nome, bruto, url)
        time.sleep(1)

    print(f"\n{len(vivos)} de {len(assinaturas)} regras devolveram dados.")

    if args.sondar:
        return

    # Segunda passada: ano a ano, onde a assinatura aceita exercício.
    print("\nvarrendo por exercício as que aceitam ano…")
    for regra, params in vivos.items():
        if not any(x in ANUAIS for x in params):
            continue
        nome = re.sub(r"[^A-Za-z0-9]+", "_", regra).strip("_").lower()
        for ano in range(args.desde, ate + 1):
            url, diag = gerar(op, regra, params, str(ano))
            if not url:
                continue
            try:
                bruto = baixar(op, url)
            except Exception:                               # noqa: BLE001
                continue
            n = linhas_do_csv(bruto)
            if n > 1:
                gravar_bruto("portal_relatorios", f"{nome}_{ano}", bruto, url)
                print(f"  {regra[:44]:<46} {ano}: {n:>7} linhas")
            time.sleep(1)


if __name__ == "__main__":
    main()
