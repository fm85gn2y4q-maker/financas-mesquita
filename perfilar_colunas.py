"""Perfila cada coluna de um relatório: o que ela contém, de fato.

Serve para dois fins. Sozinho, já torna a coluna sem nome utilizável — saber
que a posição 9 é CNPJ em 99,8% das linhas vale quase tanto quanto o rótulo.
E é a CONFERÊNCIA de qualquer rótulo proposto: nome que não bate com o perfil
está errado, por mais plausível que soe.

Uso:  python perfilar_colunas.py <regra_arquivo> [amostra]
"""

from __future__ import annotations

import csv
import io
import re
import sys
from collections import Counter
from pathlib import Path

BRUTOS = Path(__file__).resolve().parent / "dados_brutos" / "portal_relatorios"

FORMAS = [
    ("data", re.compile(r"^\d{2}/\d{2}/\d{4}$")),
    ("valor", re.compile(r"^-?\d{1,3}(\.\d{3})*,\d{2}$")),
    ("cnpj", re.compile(r"^\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}$")),
    ("cpf", re.compile(r"^\d{3}\.?\d{3}\.?\d{3}-?\d{2}$")),
    ("url", re.compile(r"^https?://")),
    ("ano", re.compile(r"^(19|20)\d{2}$")),
    ("inteiro", re.compile(r"^\d{1,6}$")),
    ("processo", re.compile(r"^\d{1,3}/\d{1,6}/\d{2,4}$")),
    ("numero_barra_ano", re.compile(r"^\d{1,6}/\d{2,4}$")),
]


def forma(v: str) -> str:
    v = (v or "").strip()
    if not v:
        return "vazio"
    for nome, padrao in FORMAS:
        if padrao.match(v):
            return nome
    return "texto"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    arq = BRUTOS / f"{sys.argv[1]}.json"
    amostra = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
    if not arq.exists():
        raise SystemExit(f"não encontrei {arq}")

    linhas = [l for l in csv.reader(io.StringIO(arq.read_bytes().decode("latin-1")))
              if any((c or "").strip() for c in l)]
    largura = Counter(len(l) for l in linhas).most_common(1)[0][0]
    linhas = [l for l in linhas if len(l) == largura][:amostra]

    print(f"{arq.stem}: {len(linhas)} linhas de largura {largura} "
          f"(de {sum(1 for _ in linhas)} amostradas)\n")
    print(f"{'pos':>4}  {'forma dominante':<22}{'distintos':>10}  exemplos")
    print("-" * 100)
    for pos in range(largura):
        col = [l[pos] for l in linhas]
        formas = Counter(forma(v) for v in col)
        (dom, n), *_ = formas.most_common()
        distintos = len({(v or "").strip() for v in col})
        exemplos = [v.strip()[:26] for v in col if (v or "").strip()][:3]
        pct = 100 * n / len(col)
        print(f"{pos:>4}  {dom + f' {pct:.0f}%':<22}{distintos:>10}  "
              f"{' | '.join(exemplos)}")


if __name__ == "__main__":
    main()
