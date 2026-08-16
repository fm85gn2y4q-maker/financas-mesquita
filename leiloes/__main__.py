"""Entrada do servidor MCP do acervo de leilões.

    python -m leiloes                  # stdio, para o Claude
    python -m leiloes --http           # HTTP em 127.0.0.1:8768
"""

from __future__ import annotations

import argparse
import os
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m leiloes",
        description="Servidor MCP sobre o acervo de leilões de numismática.",
    )
    parser.add_argument("--http", action="store_true",
                        help="serve por HTTP em vez de stdio")
    parser.add_argument("--host", default=os.environ.get("LEILOES_HOST", "127.0.0.1"))
    # 8768 para não colidir com o servidor financeiro, que usa 8767.
    parser.add_argument("--porta", type=int, default=int(os.environ.get("PORT", "8768")))
    parser.add_argument("--banco", help="caminho do SQLite (padrão: dados/leiloes.db, "
                                        "ou o que estiver em LEILOES_DB)")
    parser.add_argument("--dominio", action="append", metavar="HOST",
                        help="domínio público por onde o servidor será acessado. "
                             "Sem isto, só requisições locais passam. Pode repetir.")
    parser.add_argument("--url-publica", metavar="URL",
                        help="endereço público completo. Ativa o fluxo OAuth, "
                             "exigido pelo ChatGPT. O Claude conecta sem isto.")
    args = parser.parse_args(argv)

    from .autenticacao import VARIAVEL_DO_SEGREDO
    from .servidor import construir

    dominios = list(args.dominio or [])
    dominios += [d.strip() for d in
                 os.environ.get("LEILOES_DOMINIOS", "").split(",") if d.strip()]

    url_publica = args.url_publica or os.environ.get("LEILOES_URL_PUBLICA")
    if url_publica and not url_publica.startswith(("http://", "https://")):
        url_publica = f"https://{url_publica}"

    ajustes = {"host": args.host, "port": args.porta} if args.http else {}
    try:
        servidor = construir(args.banco, dominios=dominios or None,
                             url_publica=url_publica,
                             segredo_oauth=os.environ.get(VARIAVEL_DO_SEGREDO),
                             **ajustes)
    except FileNotFoundError as erro:
        print(f"Erro: {erro}\nRode `python construir_leiloes.py` antes.",
              file=sys.stderr)
        return 1

    if args.http:
        alcance = ", ".join(dominios) if dominios else "somente local"
        print(f"Leilões em http://{args.host}:{args.porta}/mcp  ({alcance})",
              file=sys.stderr)

    servidor.run(transport="streamable-http" if args.http else "stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
