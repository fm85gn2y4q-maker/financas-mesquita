"""Acervo de leilões de numismática e filatelia brasileiras.

    python descobrir_leiloesbr.py    # mede a estrutura real do portal
    python coletar_leiloesbr.py      # varre o catálogo e grava o cru
    python construir_leiloes.py      # dados_brutos/ → dados/leiloes.db
    python -m leiloes                # servidor MCP (stdio)
"""

__all__ = ["Acervo", "Custos"]


def __getattr__(nome: str):
    """Adiado de propósito: `leiloes.fontes` e `leiloes.identificacao` são
    usados pelos coletores, que rodam sem o acervo construído. Importar o
    Acervo aqui exigiria o banco só para coletar."""
    if nome in __all__:
        from .acervo import Acervo, Custos

        return {"Acervo": Acervo, "Custos": Custos}[nome]
    raise AttributeError(nome)
