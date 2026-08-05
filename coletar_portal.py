"""Coleta o que a API aberta do Portal da Transparência de Mesquita entrega.

`GET /sincronia/apidados.rule?sys=LAI&api=<nome>&ano=<inteiro>` — sem
autenticação, com limite por IP.

O QUE ESTA API **NÃO** TEM, e é a razão de o acervo ter três fontes: despesa,
receita, licitação, contrato e folha não estão aqui. Sondei 58 nomes prováveis
em 04/08/2026; todos devolveram "Não foi encontrada a API informada". Essas
telas são formulários Softwell Maker com CAPTCHA na entrada, e a saída legítima
para elas é a exportação "Dados Abertos" (CSV/XLS/ODS) da própria tela, ou o
modo API do portal, cuja chave se pede à Subsecretaria de Tecnologia da
Informação.

O catálogo publicado tem 16 conjuntos. Dois respondem sem estar documentados —
`patrimonio` e `obras` — e são justamente os que interessam a este acervo.

Uso:  python coletar_portal.py
"""

from __future__ import annotations

import json
from datetime import date

from fontes import baixar, gravar_bruto

API = "https://transparencia.mesquita.rj.gov.br/sincronia/apidados.rule?sys=LAI"

# O parâmetro `ano` É IGNORADO por parte dos conjuntos, e em silêncio.
# Medido em 04/08/2026: pedi `patrimonio` de 2021 a 2026 e os seis arquivos
# saíram BYTE A BYTE IDÊNTICOS — mesmo sha256, 69.792 bens, 49,1 MB cada.
# Não é a evolução do patrimônio ano a ano: é a mesma fotografia seis vezes.
# Quem montasse série histórica com isso concluiria que o patrimônio do
# Município não mudou em cinco anos — achado inteiramente fabricado pela coleta.
#
# Por isso o conjunto declara se o ano significa alguma coisa nele.
# Para os anuais de verdade (`obras`, `relatorios_estatisticos`) as contagens
# variam por ano, o que confirma que ali o filtro pega.
ANUAIS = ["obras", "relatorios_estatisticos"]
FOTOGRAFIA = ["patrimonio", "busca_avancada"]

PRIMEIRO_EXERCICIO = 2021


def coletar() -> None:
    ate = date.today().year

    for conjunto in FOTOGRAFIA:
        url = f"{API}&api={conjunto}&ano={ate}"
        bruto = baixar(url)
        dados = json.loads(bruto)
        if dados.get("status") != "sucess":
            print(f"{conjunto:<22} — {dados.get('retorno', 'vazio')}")
            continue
        # Sem sufixo de ano no nome: o arquivo é uma fotografia, e o que a data
        # dele significa está no manifesto, em `coletado_em`.
        gravar_bruto("portal", conjunto, bruto, url)
        print(f"{conjunto:<22} fotografia  {len(dados.get('dados', [])):>6} registros")

    for conjunto in ANUAIS:
        for ano in range(PRIMEIRO_EXERCICIO, ate + 1):
            url = f"{API}&api={conjunto}&ano={ano}"
            bruto = baixar(url)
            dados = json.loads(bruto)

            if dados.get("status") != "sucess":
                # "Não existem registros para esse filtro" é resposta legítima:
                # o exercício simplesmente não tem dado. Não é falha de coleta.
                print(f"{conjunto:<22} {ano}  — {dados.get('retorno', 'vazio')}")
                continue

            linhas = dados.get("dados", [])
            gravar_bruto("portal", f"{conjunto}_{ano}", bruto, url)
            print(f"{conjunto:<22} {ano}  {len(linhas):>6} registros")


if __name__ == "__main__":
    coletar()
