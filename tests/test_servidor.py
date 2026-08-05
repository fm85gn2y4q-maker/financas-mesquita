"""O servidor sobe, negocia e responde? É o que quebra na hora de plugar."""

from __future__ import annotations

import json
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FERRAMENTAS_ESPERADAS = {
    "cobertura_do_acervo", "pontos_cegos", "serie_do_tesouro",
    "despesa_por_funcao", "contratacoes_no_pncp", "bens_do_patrimonio",
    "conciliar_fornecedor",
    # exigidas pelo ChatGPT, com esta exata assinatura
    "search", "fetch",
}


@pytest.fixture(scope="module")
def parametros() -> StdioServerParameters:
    return StdioServerParameters(command=sys.executable, args=["-m", "financas"])


@pytest.mark.anyio
async def test_negocia_e_lista_ferramentas(parametros):
    async with stdio_client(parametros) as (ler, escrever):
        async with ClientSession(ler, escrever) as s:
            init = await s.initialize()
            assert init.serverInfo.name == "financas-mesquita"
            nomes = {t.name for t in (await s.list_tools()).tools}
            assert FERRAMENTAS_ESPERADAS <= nomes, FERRAMENTAS_ESPERADAS - nomes


@pytest.mark.anyio
async def test_coluna_errada_devolve_as_que_existem(parametros):
    """Antes da fábrica, o padrão da ferramenta era uma coluna inexistente e a
    resposta vinha vazia sem dizer por quê."""
    async with stdio_client(parametros) as (ler, escrever):
        async with ClientSession(ler, escrever) as s:
            await s.initialize()
            r = await s.call_tool("despesa_por_funcao",
                                  {"exercicio": 2025, "periodo": 6,
                                   "coluna": "COLUNA QUE NAO EXISTE"})
            d = json.loads(r.content[0].text)
            assert "erro" in d and d["colunas_disponiveis"]


@pytest.mark.anyio
async def test_padrao_da_ferramenta_funciona(parametros):
    """O valor padrão de `coluna` tem de existir no acervo — do contrário a
    ferramenta nasce quebrada para quem a chama sem argumentos."""
    async with stdio_client(parametros) as (ler, escrever):
        async with ClientSession(ler, escrever) as s:
            await s.initialize()
            r = await s.call_tool("despesa_por_funcao",
                                  {"exercicio": 2025, "periodo": 6})
            d = json.loads(r.content[0].text)
            assert "erro" not in d, d.get("colunas_disponiveis")
            assert d["blocos"]


@pytest.mark.anyio
async def test_cobertura_declara_os_limites(parametros):
    async with stdio_client(parametros) as (ler, escrever):
        async with ClientSession(ler, escrever) as s:
            await s.initialize()
            c = json.loads((await s.call_tool("cobertura_do_acervo", {})).content[0].text)
            assert c["siconfi"]["linhas"] > 100_000
            assert c["patrimonio"]["aviso_sobre_o_total"]
            assert c["o_que_NAO_esta_aqui"], "nenhuma ausência declarada"
