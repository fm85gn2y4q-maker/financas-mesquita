"""Coleta os demonstrativos do SICONFI/Tesouro para Mesquita.

É a espinha dorsal do acervo: a série oficial e conferível de receita, despesa,
RCL, pessoal e dívida. Vem do que o próprio Município declarou ao Tesouro, o que
lhe dá um peso que a tela do portal não tem.

Medido em 04/08/2026:
  - omitir `no_anexo` devolve TODOS os anexos de uma vez (RREO 2135 itens num
    bimestre, RGF 395 num quadrimestre, DCA 1238 num exercício). Um pedido por
    período, não um por anexo.
  - a série do DCA começa em 2013; 2010-2012 devolvem zero.
  - **o RGF não traz o campo `demonstrativo`** (o RREO e o DCA trazem). Quem
    lê o valor do payload perde 7.161 linhas num balde "?" sem receber erro.
    O demonstrativo tem de ser carimbado a partir do nome do arquivo, na
    ingestão — aqui não, porque o que veio da rede fica intocado.

E a armadilha que decide o esquema, medida no Anexo 02: **a hierarquia
função/subfunção do SICONFI só existe na ORDEM das linhas.** Nada no registro
diz de quem ele é filho. "Administração Geral" aparece sete vezes no mesmo
anexo e na mesma coluna, cada vez sob uma função diferente, com valores de
R$ 30 mil a R$ 59,9 milhões. Somar por nome da conta junta o que não se junta.
Por isso a ingestão preserva a posição de cada linha na resposta.

Uso:  python coletar_siconfi.py [--desde 2013]
"""

from __future__ import annotations

import argparse
import json
from datetime import date

from fontes import IBGE, baixar, gravar_bruto

BASE = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt"

# Antes disso o ente não tem entrega no SICONFI (medido: 2010-2012 = 0 itens).
PRIMEIRO_EXERCICIO = 2013


def _pedir(caminho: str, nome: str, **params) -> int:
    params["id_ente"] = IBGE
    url = f"{BASE}/{caminho}?" + "&".join(f"{k}={v}" for k, v in params.items())
    bruto = baixar(url)
    itens = json.loads(bruto).get("items", [])
    if itens:
        gravar_bruto("siconfi", nome, bruto, url)
    return len(itens)


def coletar(desde: int) -> None:
    ate = date.today().year
    total = 0

    for ano in range(desde, ate + 1):
        # DCA — Declaração de Contas Anuais. Um por exercício, o balanço fechado.
        n = _pedir("dca", f"dca_{ano}", an_exercicio=ano, co_tipo_demonstrativo="DCA")
        print(f"DCA  {ano}          {n:>6} itens")
        total += n

        # RREO — bimestral, seis por exercício. É onde está a execução corrente.
        for periodo in range(1, 7):
            n = _pedir("rreo", f"rreo_{ano}_b{periodo}", an_exercicio=ano,
                       nr_periodo=periodo, co_tipo_demonstrativo="RREO", co_esfera="M")
            if n:
                print(f"RREO {ano} bim. {periodo}  {n:>6} itens")
            total += n

        # RGF — quadrimestral para o Executivo municipal. Pessoal e dívida.
        for periodo in range(1, 4):
            n = _pedir("rgf", f"rgf_{ano}_q{periodo}", an_exercicio=ano,
                       in_periodicidade="Q", nr_periodo=periodo,
                       co_tipo_demonstrativo="RGF", co_poder="E")
            if n:
                print(f"RGF  {ano} quad. {periodo} {n:>6} itens")
            total += n

    print(f"\ntotal: {total} itens em dados_brutos/siconfi/")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--desde", type=int, default=PRIMEIRO_EXERCICIO)
    coletar(p.parse_args().desde)
