"""Identificadores do Município e utilitários de coleta comuns às três fontes.

Regra da casa (fase 3 do GUIA-NOVO-ACERVO): o que veio da rede fica intocado.
Estes utilitários gravam a resposta crua e um manifesto com a data da coleta.
A data importa mais aqui do que nos outros acervos: neste, o mesmo fato aparece
em fontes diferentes com números diferentes, e um valor sem data de coleta não
pode ser conciliado com nada.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Mesquita/RJ. Conferidos em 04/08/2026 no próprio SICONFI (endpoint tt/entes),
# que é a forma barata de achar o CNPJ de qualquer município brasileiro.
IBGE = 3302858
CNPJ = "04132090000125"

# Ids internos do PNCP. NÃO são o código IBGE, e o PNCP ignora em silêncio o
# filtro por CNPJ — devolve 200 com o Brasil inteiro. Ver conferir_orgao().
PNCP_ORGAO_ID = 91907
PNCP_MUNICIPIO_ID = 3218

RAIZ = Path(__file__).resolve().parent
BRUTOS = RAIZ / "dados_brutos"

USER_AGENT = (
    "financas-mesquita/0.1 (Procuradoria-Geral do Município de Mesquita-RJ; "
    "coleta de dados públicos)"
)


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def baixar(url: str, tentativas: int = 4, espera: float = 3.0) -> bytes:
    """GET com repetição. O PNCP devolve 504 com frequência e o portal municipal
    tem limite por IP; ambos passam na segunda ou terceira tentativa.

    Pegar só urllib.error não basta: o PNCP também derruba a conexão sem
    resposta, e isso sobe como http.client.RemoteDisconnected, que não é
    URLError. Custou uma coleta interrompida na primeira execução."""
    ultimo_erro: Exception | None = None
    for n in range(tentativas):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return resp.read()
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            ultimo_erro = e
            if n < tentativas - 1:
                time.sleep(espera * (n + 1))
    raise RuntimeError(f"falhou após {tentativas} tentativas: {url}") from ultimo_erro


def gravar_bruto(fonte: str, nome: str, conteudo: bytes, url: str) -> Path:
    """Grava a resposta crua e anota origem, data e sha256 ao lado dela."""
    destino = BRUTOS / fonte
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / f"{nome}.json"
    caminho.write_bytes(conteudo)

    manifesto = destino / "manifesto.jsonl"
    with manifesto.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "arquivo": caminho.name,
            "url": url,
            "coletado_em": agora(),
            "bytes": len(conteudo),
            "sha256": hashlib.sha256(conteudo).hexdigest(),
        }, ensure_ascii=False) + "\n")
    return caminho
