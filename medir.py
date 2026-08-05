"""Fase 1 do GUIA-NOVO-ACERVO: medir o pressuposto antes de criar a tabela.

Não constrói nada. Responde, contra os dados crus já baixados, às perguntas que
decidem o esquema:

  1. O que é uma linha em cada fonte?
  2. Duas linhas com os mesmos campos são o mesmo objeto? (chave candidata)
  3. Onde estão os buracos de cobertura?

A pergunta 2 é a cara de errar. No SICONFI a suspeita é que
(demonstrativo, exercício, período, anexo, coluna, conta) não baste — o campo
`rotulo` separa entregas distintas do mesmo anexo, e achatá-lo somaria valores
que não se somam.

Uso:  python medir.py
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

BRUTOS = Path(__file__).resolve().parent / "dados_brutos"


def _carregar(caminho: Path) -> list[dict]:
    dados = json.loads(caminho.read_text(encoding="utf-8"))
    if isinstance(dados, list):
        return dados
    return dados.get("items") or dados.get("dados") or []


def medir_siconfi() -> None:
    print("=" * 72)
    print("SICONFI")
    print("=" * 72)

    arquivos = sorted((BRUTOS / "siconfi").glob("*.json"))
    if not arquivos:
        print("  nada coletado ainda")
        return

    total = 0
    por_demonstrativo: Counter = Counter()
    anos: defaultdict = defaultdict(set)
    rotulos: Counter = Counter()

    # Chave candidata mínima × chave com rótulo: se a primeira colidir e a
    # segunda não, o rótulo é dimensão obrigatória e não pode sair do esquema.
    colisoes_sem_rotulo = 0
    colisoes_com_rotulo = 0

    for arq in arquivos:
        itens = _carregar(arq)
        total += len(itens)
        vistas_sem, vistas_com = set(), set()
        for it in itens:
            dem = it.get("demonstrativo") or ("DCA" if "dca" in arq.name else "?")
            por_demonstrativo[dem] += 1
            anos[dem].add(it.get("exercicio"))
            rotulos[it.get("rotulo")] += 1

            sem = (dem, it.get("exercicio"), it.get("periodo"), it.get("anexo"),
                   it.get("coluna"), it.get("cod_conta"))
            com = sem + (it.get("rotulo"), it.get("co_poder"))
            if sem in vistas_sem:
                colisoes_sem_rotulo += 1
            vistas_sem.add(sem)
            if com in vistas_com:
                colisoes_com_rotulo += 1
            vistas_com.add(com)

    print(f"  arquivos: {len(arquivos)}   linhas: {total:,}".replace(",", "."))
    for dem, n in sorted(por_demonstrativo.items()):
        faixa = sorted(x for x in anos[dem] if x)
        print(f"    {dem:<6} {n:>8,} linhas   {faixa[0]}-{faixa[-1]}".replace(",", "."))

    print(f"\n  rótulos distintos: {len(rotulos)}")
    for r, n in rotulos.most_common(8):
        print(f"    {str(r):<40} {n:>8,}".replace(",", "."))

    print(f"\n  PERGUNTA 2 — a chave sem rótulo/poder colide? {colisoes_sem_rotulo:,} vezes"
          .replace(",", "."))
    print(f"                a chave com rótulo/poder colide? {colisoes_com_rotulo:,} vezes"
          .replace(",", "."))
    if colisoes_sem_rotulo and not colisoes_com_rotulo:
        print("  → rótulo e poder são dimensão obrigatória. Sem eles o acervo soma"
              "\n    valores que não se somam.")
    elif colisoes_com_rotulo:
        print("  → ainda colide COM rótulo: há dimensão que eu não identifiquei."
              "\n    NÃO criar a tabela antes de achá-la.")


def medir_pncp() -> None:
    print()
    print("=" * 72)
    print("PNCP")
    print("=" * 72)
    for arq in sorted((BRUTOS / "pncp").glob("*.json")):
        itens = _carregar(arq)
        anos = Counter(i.get("ano") for i in itens)
        orgaos = Counter(i.get("orgao_nome") for i in itens)
        print(f"  {arq.stem:<10} {len(itens):>4} registros")
        for o, n in orgaos.most_common():
            print(f"      {o:<32} {n}")
        print(f"      por ano: {dict(sorted(anos.items()))}")


def medir_portal() -> None:
    print()
    print("=" * 72)
    print("PORTAL")
    print("=" * 72)
    for arq in sorted((BRUTOS / "portal").glob("*.json")):
        itens = _carregar(arq)
        print(f"  {arq.stem:<28} {len(itens):>7,} registros".replace(",", "."))

    # Patrimônio: a pergunta 2 aqui é se a plaqueta identifica o bem.
    plaquetas = sorted((BRUTOS / "portal").glob("patrimonio_*.json"))
    if plaquetas:
        itens = _carregar(plaquetas[-1])
        chaves = Counter((i.get("BEN_PLAQUETA") or "").strip() for i in itens)
        repetidas = {k: v for k, v in chaves.items() if v > 1 and k}
        vazias = chaves.get("", 0)
        print(f"\n  PERGUNTA 2 — patrimônio ({plaquetas[-1].stem}):")
        print(f"    bens: {len(itens):,}".replace(",", "."))
        print(f"    plaquetas vazias: {vazias:,}".replace(",", "."))
        print(f"    plaquetas repetidas: {len(repetidas):,} "
              f"(somando {sum(repetidas.values()):,} linhas)".replace(",", "."))
        if repetidas:
            exemplo = next(iter(repetidas))
            print(f"    → a plaqueta NÃO identifica o bem sozinha. Ex.: {exemplo!r} "
                  f"aparece {repetidas[exemplo]}×")


if __name__ == "__main__":
    medir_siconfi()
    medir_pncp()
    medir_portal()
