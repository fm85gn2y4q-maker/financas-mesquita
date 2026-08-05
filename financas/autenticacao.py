"""OAuth para clientes que exigem o fluxo — o caso do ChatGPT.

O Claude conecta a um servidor MCP sem autenticação. O ChatGPT não: antes de
falar com o servidor ele procura os metadados de OAuth e desiste se não os
achar ("does not implement OAuth"). Este módulo fornece o que ele espera.

Tudo aqui é **sem estado**. Código de autorização, token e até o `client_id`
são cargas assinadas por HMAC, e não entradas numa tabela. O motivo é
prático: hospedagem gratuita desliga o serviço por inatividade, e um provedor
que guardasse autorizações em memória as perderia a cada soneca — o conector
pediria nova autorização o dia inteiro.

Aviso que não cabe esconder: a aprovação é automática. Quem chegar à URL
completa o fluxo e recebe um token. Isso protege contra chamada sem token, não
contra quem conhece o endereço — é aceitável para o Diário Oficial de
Mesquita, que a Prefeitura já publica na internet, e **não** para acervo de obra protegida.

O segredo de assinatura vem de `FINANCAS_SEGREDO_OAUTH`. Sem ele, cada partida do
processo sorteia um novo, e toda autorização concedida antes deixa de valer —
o que na hospedagem gratuita significa reautorizar depois de cada hibernação.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any
from urllib.parse import urlencode, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl, AnyUrl

log = logging.getLogger(__name__)

# Rótulo do escopo anunciado nos metadados de OAuth. Aparece na tela de
# autorização e para quem inspeciona o conector, então tem de dizer a verdade
# sobre o acervo — este módulo chegou aqui por cópia, e veio com o rótulo do
# acervo de origem.
#
# Trocar este valor invalida as autorizações já concedidas: `required_scopes`
# entra na conferência do token. Se for mudar depois de alguém já ter conectado,
# a extensão e o conector precisam ser reautorizados.
ESCOPO = "financas-mesquita"
VALIDADE_CODIGO = 300               # 5 min: só atravessa o redirecionamento
VALIDADE_ACESSO = 60 * 60 * 12      # 12 h
VALIDADE_ATUALIZACAO = 60 * 60 * 24 * 90


def _codificar(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode().rstrip("=")


def _decodificar(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


class Selo:
    """Assina e confere cargas, para que elas dispensem armazenamento."""

    def __init__(self, segredo: str) -> None:
        self._segredo = segredo.encode()

    def selar(self, tipo: str, carga: dict[str, Any], validade: int | None) -> str:
        corpo: dict[str, Any] = {"t": tipo, **carga}
        if validade is not None:
            corpo["exp"] = int(time.time()) + validade
        bruto = json.dumps(corpo, separators=(",", ":"), sort_keys=True).encode()
        assinatura = hmac.new(self._segredo, bruto, hashlib.sha256).digest()[:16]
        return f"{_codificar(bruto)}.{_codificar(assinatura)}"

    def abrir(self, tipo: str, selo: str) -> dict[str, Any] | None:
        try:
            corpo_codificado, assinatura_codificada = selo.split(".", 1)
            bruto = _decodificar(corpo_codificado)
            recebida = _decodificar(assinatura_codificada)
        except Exception:  # noqa: BLE001 - entrada arbitrária, qualquer erro é recusa
            return None

        esperada = hmac.new(self._segredo, bruto, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(esperada, recebida):
            return None

        try:
            corpo = json.loads(bruto)
        except json.JSONDecodeError:
            return None

        # O tipo impede que um código de autorização seja apresentado como
        # token de acesso: ambos são assinados pela mesma chave.
        if corpo.get("t") != tipo:
            return None
        if "exp" in corpo and corpo["exp"] < time.time():
            return None
        return corpo


class ProvedorOAuth(OAuthAuthorizationServerProvider):
    """Servidor de autorização mínimo, sem banco e sem sessão."""

    def __init__(self, selo: Selo) -> None:
        self._selo = selo

    # -- cliente ----------------------------------------------------------

    def _segredo_do_cliente(self, client_id: str) -> str:
        return self._selo.selar("segredo", {"c": client_id}, None)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        # O identificador carrega o próprio cadastro. O SDK devolve ao cliente
        # o objeto alterado aqui, então trocar o `client_id` neste ponto basta
        # para dispensar qualquer tabela de clientes.
        client_info.client_id = self._selo.selar(
            "cliente",
            {
                "r": [str(u) for u in client_info.redirect_uris],
                "n": client_info.client_name or "",
                "m": client_info.token_endpoint_auth_method or "client_secret_post",
            },
            None,
        )
        if client_info.token_endpoint_auth_method == "none":
            client_info.client_secret = None
        else:
            client_info.client_secret = self._segredo_do_cliente(client_info.client_id)
        client_info.client_secret_expires_at = None
        client_info.scope = ESCOPO

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        dados = self._selo.abrir("cliente", client_id)
        if dados is None:
            return None
        metodo = dados.get("m") or "client_secret_post"
        return OAuthClientInformationFull(
            client_id=client_id,
            client_secret=None if metodo == "none" else self._segredo_do_cliente(client_id),
            redirect_uris=[AnyUrl(u) for u in dados["r"]],
            token_endpoint_auth_method=metodo,
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            client_name=dados.get("n") or None,
            scope=ESCOPO,
        )

    # -- autorização ------------------------------------------------------

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        codigo = self._selo.selar(
            "codigo",
            {
                "c": client.client_id,
                "u": str(params.redirect_uri),
                "e": params.redirect_uri_provided_explicitly,
                "d": params.code_challenge,
                "s": params.scopes or [ESCOPO],
                "rs": params.resource,
            },
            VALIDADE_CODIGO,
        )
        consulta: dict[str, str] = {"code": codigo}
        if params.state:
            consulta["state"] = params.state
        separador = "&" if urlparse(str(params.redirect_uri)).query else "?"
        return f"{params.redirect_uri}{separador}{urlencode(consulta)}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        dados = self._selo.abrir("codigo", authorization_code)
        if dados is None or dados["c"] != client.client_id:
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=dados["s"],
            expires_at=float(dados["exp"]),
            client_id=client.client_id,
            code_challenge=dados["d"],
            redirect_uri=AnyUrl(dados["u"]),
            redirect_uri_provided_explicitly=dados["e"],
            resource=dados.get("rs"),
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        return self._emitir(
            client.client_id, authorization_code.scopes, authorization_code.resource
        )

    # -- tokens -----------------------------------------------------------

    def _emitir(self, client_id: str, escopos: list[str], recurso: str | None) -> OAuthToken:
        carga = {"c": client_id, "s": escopos, "rs": recurso}
        return OAuthToken(
            access_token=self._selo.selar("acesso", carga, VALIDADE_ACESSO),
            expires_in=VALIDADE_ACESSO,
            scope=" ".join(escopos),
            refresh_token=self._selo.selar("atualizacao", carga, VALIDADE_ATUALIZACAO),
        )

    async def load_access_token(self, token: str) -> AccessToken | None:
        dados = self._selo.abrir("acesso", token)
        if dados is None:
            return None
        return AccessToken(
            token=token,
            client_id=dados["c"],
            scopes=dados["s"],
            expires_at=dados.get("exp"),
            resource=dados.get("rs"),
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        dados = self._selo.abrir("atualizacao", refresh_token)
        if dados is None or dados["c"] != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=dados["s"],
            expires_at=dados.get("exp"),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        dados = self._selo.abrir("atualizacao", refresh_token.token) or {}
        return self._emitir(client.client_id, scopes or refresh_token.scopes,
                            dados.get("rs"))

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Sem efeito, e é honesto dizer por quê.

        Token assinado vale enquanto não expirar: não há registro para apagar.
        Revogar de verdade exigiria uma lista de descartados — ou seja, estado,
        que é justamente o que este desenho evita. Para cortar todo o acesso,
        troque `FINANCAS_SEGREDO_OAUTH`: as assinaturas antigas param de valer.
        """
        log.info("Pedido de revogação recebido; tokens assinados expiram por conta própria.")


def montar(url_publica: str, segredo: str | None) -> tuple[ProvedorOAuth, AuthSettings]:
    """Prepara provedor e configuração para uma URL pública."""
    base = url_publica.rstrip("/")
    if not segredo:
        segredo = secrets.token_urlsafe(32)
        # O nome da variável neste aviso importa: é por ele que quem opera o
        # serviço vai procurar o que definir. Ficou `EMENTARIO_SEGREDO_OAUTH`
        # por herança do projeto de onde este módulo veio — variável que este
        # servidor nunca leu. Quem seguisse o aviso definiria a coisa errada e
        # o alerta continuaria aparecendo, sem explicação.
        log.warning(
            "FINANCAS_SEGREDO_OAUTH não definido: usando um segredo temporário. "
            "As autorizações concedidas agora deixam de valer quando o serviço "
            "reiniciar — e no plano gratuito ele reinicia a cada hibernação."
        )

    definicoes = AuthSettings(
        issuer_url=AnyHttpUrl(base),
        resource_server_url=AnyHttpUrl(f"{base}/mcp"),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=[ESCOPO],
            default_scopes=[ESCOPO],
        ),
        required_scopes=[ESCOPO],
    )
    return ProvedorOAuth(Selo(segredo)), definicoes

