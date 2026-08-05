"""Instala o acervo comprimido no lugar onde o servidor o procura.

Aceita as duas origens. Este projeto usa a URL, porque o acervo comprimido passa
dos 50 MB em que o GitHub adverte, e cresce a cada coleta — o que faria o
histórico do Git engordar para sempre. O acervo de legislação, com 21 MB, viaja
dentro do repositório; a diferença é de tamanho, não de método.

    python instalar_acervo.py https://…/financas-mesquita-v1.0.0.db.gz \
        dados/acervo.db <sha256>     # asset de release: é o que a imagem usa
    python instalar_acervo.py dist/financas-mesquita-v1.0.0.db.gz \
        dados/acervo.db <sha256>     # arquivo local, para conferir antes

Em qualquer das duas, o sha256 é conferido **antes** de descomprimir. É o que
fecha a cadeia `versão fixa → hash declarado → conferência no build → falha
fechada`: divergindo o arquivo, a construção para em vez de subir um acervo
diferente daquele que foi testado.
"""

from __future__ import annotations

import gzip
import hashlib
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

BLOCO = 4 * 1024 * 1024


def _resumo(caminho: Path) -> str:
    """Hash em blocos: o arquivo tem 84 MB e não precisa ir todo à memória."""
    digestor = hashlib.sha256()
    with caminho.open("rb") as fluxo:
        for bloco in iter(lambda: fluxo.read(BLOCO), b""):
            digestor.update(bloco)
    return digestor.hexdigest()


def instalar(origem: str, destino: Path, esperado: str | None = None) -> None:
    # O Dockerfile passa ARG vazio enquanto a primeira release não existe.
    # Parar aqui, com o motivo dito, é melhor que seguir: uma imagem sem acervo
    # sobe normalmente e só falha na primeira consulta do usuário.
    if not origem.strip():
        raise SystemExit(
            "ACERVO vazio: nenhuma release publicada ainda.\n"
            "  Rode `python preparar_release.py <versão>`, publique o .gz e\n"
            "  preencha ARG ACERVO e ARG ACERVO_SHA256 no Dockerfile."
        )

    destino.parent.mkdir(parents=True, exist_ok=True)

    local = Path(origem)
    if local.is_file():
        comprimido, temporario = local, False
        print(f"Usando {local} ({local.stat().st_size / 1048576:.1f} MB)",
              file=sys.stderr)
    else:
        print(f"Baixando {origem}", file=sys.stderr)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".gz") as arquivo:
            comprimido = Path(arquivo.name)
        temporario = True
        with urllib.request.urlopen(origem, timeout=300) as resposta:
            with comprimido.open("wb") as saida:
                shutil.copyfileobj(resposta, saida, length=BLOCO)

    try:
        if esperado:
            obtido = _resumo(comprimido)
            if obtido != esperado:
                raise SystemExit(
                    f"Conferência falhou.\n  esperado: {esperado}\n  obtido:   {obtido}"
                )
            print("Integridade conferida.", file=sys.stderr)

        with gzip.open(comprimido, "rb") as entrada, destino.open("wb") as saida:
            shutil.copyfileobj(entrada, saida, length=BLOCO)
    finally:
        if temporario:
            comprimido.unlink(missing_ok=True)

    print(f"Acervo em {destino} ({destino.stat().st_size / 1048576:.1f} MB)",
          file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    instalar(sys.argv[1], Path(sys.argv[2]),
             sys.argv[3] if len(sys.argv) > 3 else None)
