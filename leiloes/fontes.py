"""Coleta comum aos leilões. O que veio da rede fica intocado.

Mesma regra do acervo financeiro: grava-se a resposta crua e um manifesto com
a data e o sha256 ao lado dela. Aqui a data de coleta importa por um motivo
próprio — o lote muda de estado durante o pregão. O mesmo lote é "aberto" às
14h e "arrematado" às 14h05, e um preço sem hora de coleta não diz se é lance
corrente ou martelo final.

Diferença em relação ao acervo financeiro: ali as fontes são portais públicos
que esperam robô. Aqui são sites comerciais de terceiros. Por isso a coleta
é lenta de propósito (ver ESPERA), manda User-Agent identificável com contato,
e o coletor confere robots.txt antes de varrer. Coleta rápida demais derruba o
site da casa e queima o acesso — não é escrúpulo, é a diferença entre ter e
não ter o acervo no mês que vem.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BRUTOS = RAIZ / "dados_brutos"

# A plataforma. `www2` é espelho do mesmo catálogo e responde igual; serve de
# alternativa quando o principal está fora.
PORTAL = "https://www.leiloesbr.com.br"
PORTAL_ESPELHO = "https://www2.leiloesbr.com.br"

# Segundos entre requisições. Não baixe isto sem falar com a casa: o portal é
# ASP clássico servindo página inteira a cada clique, e a varredura completa do
# catálogo são milhares de páginas.
ESPERA = float(os.environ.get("LEILOES_ESPERA", "2.5"))

CONTATO = os.environ.get("LEILOES_CONTATO", "")
USER_AGENT = (
    f"rastreador-leiloes/0.1 (pesquisa de mercado numismático; "
    f"{CONTATO or 'defina LEILOES_CONTATO com um e-mail de contato'})"
)

_ultima_requisicao = 0.0
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def permitido(url: str) -> bool:
    """Confere o robots.txt do host antes de buscar.

    Falha aberta de propósito: host sem robots.txt, ou com robots.txt que não
    responde, é tratado como permitido — é o que a norma do arquivo determina.
    O que NÃO se faz é ignorar um Disallow que existe.
    """
    partes = urllib.parse.urlsplit(url)
    base = f"{partes.scheme}://{partes.netloc}"
    if base not in _robots:
        leitor = urllib.robotparser.RobotFileParser()
        leitor.set_url(f"{base}/robots.txt")
        try:
            leitor.read()
        except Exception:
            leitor.allow_all = True
        _robots[base] = leitor
    return _robots[base].can_fetch(USER_AGENT, url)


def baixar(url: str, tentativas: int = 4, espera: float = 3.0,
           respeitar_robots: bool = True) -> bytes:
    """GET com repetição e intervalo mínimo entre chamadas.

    Pegar só urllib.error não basta — o servidor derruba a conexão sem resposta
    sob carga, e isso sobe como http.client.RemoteDisconnected, que não é
    URLError. Mesma lição que o coletor do PNCP aprendeu perdendo uma coleta.
    """
    global _ultima_requisicao
    if respeitar_robots and not permitido(url):
        raise PermissionError(f"robots.txt do host proíbe: {url}")

    ultimo_erro: Exception | None = None
    for n in range(tentativas):
        intervalo = time.monotonic() - _ultima_requisicao
        if intervalo < ESPERA:
            time.sleep(ESPERA - intervalo)
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Accept-Language": "pt-BR,pt;q=0.9",
        })
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                _ultima_requisicao = time.monotonic()
                return resp.read()
        except (urllib.error.URLError, http.client.HTTPException, OSError) as e:
            _ultima_requisicao = time.monotonic()
            ultimo_erro = e
            if n < tentativas - 1:
                time.sleep(espera * (n + 1))
    raise RuntimeError(f"falhou após {tentativas} tentativas: {url}") from ultimo_erro


def texto(conteudo: bytes) -> str:
    """Decodifica. O portal é ASP antigo e serve latin-1 com frequência; tentar
    só utf-8 corrompe todo acento, e acento corrompido quebra a identificação
    da peça — "Réis" vira "R?is" e deixa de casar com o comparável."""
    for codec in ("utf-8", "cp1252", "latin-1"):
        try:
            return conteudo.decode(codec)
        except UnicodeDecodeError:
            continue
    return conteudo.decode("utf-8", errors="replace")


def gravar_bruto(fonte: str, nome: str, conteudo: bytes, url: str) -> Path:
    """Grava a resposta crua e anota origem, data e sha256 ao lado dela."""
    destino = BRUTOS / fonte
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / nome
    caminho.write_bytes(conteudo)

    with (destino / "manifesto.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "arquivo": caminho.name,
            "url": url,
            "coletado_em": agora(),
            "bytes": len(conteudo),
            "sha256": hashlib.sha256(conteudo).hexdigest(),
        }, ensure_ascii=False) + "\n")
    return caminho
