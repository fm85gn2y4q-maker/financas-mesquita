"""Descobre as regras de relatório do portal E a assinatura de cada uma.

O portal expõe, sem captcha e sem autenticação, um gerador de relatórios em
CSV/XLS/ODS — a opção que a própria tela chama de "Dados Abertos":

    POST /webrun/executeRule.do?action=executeRule&pType=2
         &ruleName=<regra>&sys=LAI&formID=<form>&P_0..P_n=<filtros>
      → devolve o caminho de WFRReports\\Generated\\<GUID>.CSV
      → servido em /ver20240713/WFRReports/Generated/<GUID>.CSV

As regras são **Java**, executadas no servidor: não são declaradas em
`webrunRules.js`, só aparecem como literal no ponto de chamada. Procurá-las
entre os `this.ruleName` devolve zero — foi o primeiro erro aqui.

A assinatura importa porque um dos parâmetros é o FORMATO do relatório
(2=PDF, 4=TXT, 5=XLS, 6=RTF, 7=CSV, 8=ODT, 9=CALC) e a posição dele muda de
regra para regra. Ela se lê no próprio ponto de chamada, que passa
`this.context['NOME']` na ordem.

Grava `dados/relatorios.json`.

Uso:  python descobrir_relatorios.py
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

BASE = "https://transparencia.mesquita.rj.gov.br/webrun/"
UA = {"User-Agent": "financas-mesquita/0.1 (PGM Mesquita)"}
SAIDA = Path(__file__).resolve().parent / "dados" / "relatorios.json"

# executeSyncJavaRule.call(this, this.getSystem(), this.getForm(), 'NOME', [args])
#
# A lista de argumentos NÃO pode ser casada com `[^\]]*`: cada argumento é
# `this.context['ANO']`, que já contém um `]`. A primeira versão daqui parava no
# primeiro colchete e não achava assinatura nenhuma — zero regras, sem erro.
CHAMADA = re.compile(
    r"executeSyncJavaRule\.call\(\s*this,\s*this\.getSystem\(\),\s*"
    r"this\.getForm\(\),\s*'((?:[^'\\]|\\.)+)'\s*,\s*\[(.*?)\]\s*\)",
    re.DOTALL)

CONTEXTO = re.compile(r"this\.context\['([^']+)'\]")


def baixar(url: str, enc: str = "latin-1") -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read().decode(enc, "replace")


def main() -> None:
    js = baixar(BASE + "jsRule/system_lai/webrunRules.js")

    assinaturas: dict[str, list[str]] = {}
    for m in CHAMADA.finditer(js):
        nome, args = m.group(1), m.group(2)
        if not re.search(r"URL\s+Relat", nome, re.I):
            continue
        params = CONTEXTO.findall(args)
        # Fica a assinatura mais longa vista: chamadas parciais existem.
        if len(params) > len(assinaturas.get(nome, [])):
            assinaturas[nome] = params

    print(f"regras de relatório com assinatura legível: {len(assinaturas)}\n")
    for nome in sorted(assinaturas):
        params = assinaturas[nome]
        formato = [i for i, p in enumerate(params)
                   if re.fullmatch(r"Relatorio|RELATORIO|TIPO_RELATORIO", p)]
        marca = f"  → formato em P_{formato[0]}" if formato else "  → SEM parâmetro de formato"
        print(f"{nome}")
        print(f"   {len(params)} params: {', '.join(params)}")
        print(f"  {marca}\n")

    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(json.dumps(assinaturas, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    print(f"gravado em {SAIDA}")


if __name__ == "__main__":
    main()
