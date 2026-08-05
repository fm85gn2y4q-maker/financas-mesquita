"""Coleta o que Mesquita publicou no Portal Nacional de Contratações Públicas.

O volume aqui é pequeno, e isso é o achado, não o defeito: medido em 04/08/2026,
o Município tinha 41 editais e 20 contratos no PNCP desde que foi validado, em
28/07/2021 — contra milhares de atos de licitação no portal municipal e no
Diário Oficial no mesmo período. A divulgação no PNCP é exigida pela Lei
14.133/2021. A lacuna é matéria de conformidade; conferir antes de afirmar.

DUAS ARMADILHAS, ambas medidas, ambas silenciosas:

1. A API documentada `/api/consulta/v1/...` responde 504 de forma crônica —
   falhou em todas as tentativas, inclusive sem filtro nenhum. A rota que
   funciona é `/api/search/`.
2. O `/api/search/` **ignora** o parâmetro `orgao_cnpj` e devolve 200 com o
   Brasil inteiro (3,9 milhões de registros) como se tivesse filtrado. Os
   filtros que valem são `orgaos=<id interno>` e `municipios=<id interno>`, e o
   id do município **não** é o código IBGE. Por isso conferir_resultado() aborta
   quando aparece órgão de fora: filtro que não filtra e responde 200 é o pior
   modo de errar.

Uso:  python coletar_pncp.py
"""

from __future__ import annotations

import json

from fontes import PNCP_MUNICIPIO_ID, baixar, gravar_bruto

BUSCA = "https://pncp.gov.br/api/search/"
TIPOS = ["edital", "contrato", "ata", "pca"]

# Tudo que o PNCP devolver fora desta lista significa que o filtro não pegou.
ORGAOS_ESPERADOS = {"MUNICIPIO DE MESQUITA", "CAMARA MUNICIPAL DE MESQUITA"}


def conferir_resultado(itens: list[dict], tipo: str) -> None:
    intrusos = {i.get("orgao_nome") for i in itens} - ORGAOS_ESPERADOS
    if intrusos:
        raise SystemExit(
            f"ABORTADO em '{tipo}': o filtro do PNCP não pegou. "
            f"Vieram órgãos de fora de Mesquita: {sorted(intrusos)[:5]}. "
            "Conferir os parâmetros antes de gravar qualquer coisa."
        )


def coletar() -> None:
    for tipo in TIPOS:
        itens: list[dict] = []
        pagina = 1
        while True:
            url = (f"{BUSCA}?tipos_documento={tipo}&ordenacao=-data&status=todos"
                   f"&municipios={PNCP_MUNICIPIO_ID}&pagina={pagina}&tam_pagina=50")
            dados = json.loads(baixar(url))
            lote = dados.get("items", [])
            if not lote:
                break
            itens.extend(lote)
            if len(itens) >= dados.get("total", 0):
                break
            pagina += 1

        conferir_resultado(itens, tipo)

        if itens:
            gravar_bruto("pncp", tipo,
                         json.dumps(itens, ensure_ascii=False, indent=1).encode(),
                         f"{BUSCA}?tipos_documento={tipo}&municipios={PNCP_MUNICIPIO_ID}")

        por_orgao: dict[str, int] = {}
        for i in itens:
            por_orgao[i.get("orgao_nome", "?")] = por_orgao.get(i.get("orgao_nome", "?"), 0) + 1
        detalhe = "; ".join(f"{k}: {v}" for k, v in sorted(por_orgao.items())) or "nenhum"
        print(f"{tipo:<9} {len(itens):>4} registros   ({detalhe})")


if __name__ == "__main__":
    coletar()
