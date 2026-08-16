"""O servidor de leilões sobe, negocia e responde? É o que quebra ao plugar."""

from __future__ import annotations

import json
import sys

import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

FERRAMENTAS_ESPERADAS = {
    "cobertura_do_acervo", "pontos_cegos", "oportunidades", "lotes_para_ler",
    "historico_da_peca", "pesquisar_lotes",
    # exigidas pelo ChatGPT, com esta exata assinatura
    "search", "fetch",
}


@pytest.fixture(scope="module")
def parametros(tmp_path_factory) -> StdioServerParameters:
    """Sobe o servidor contra um acervo mínimo próprio, montado do zero.

    O servidor não pode depender do banco que estiver na máquina: em máquina
    sem coleta ele nasceria com FileNotFoundError e o teste passaria a medir a
    ausência do banco em vez do servidor.
    """
    import construir_leiloes

    raiz = tmp_path_factory.mktemp("acervo")
    brutos = raiz / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    banco = raiz / "dados" / "leiloes.db"

    lotes = [{"numero": n, "titulo": "Moeda 20 Réis 1869 bronze MBC KM# 474",
              "descricao": "Bronze do Império.", "url": f"http://x/{n}",
              "foto_url": None, "lance_inicial": 100.0, "estimativa_min": None,
              "estimativa_max": None, "situacao": "arrematado",
              "preco_martelo": 1000.0 + n, "data_resultado": "2026-05-10"}
             for n in range(1, 7)]
    lotes.append({"numero": 7, "titulo": "1000 Réis 1913, prata, Soberba",
                  "descricao": "", "url": "http://x/7", "foto_url": None,
                  "lance_inicial": 50.0, "estimativa_min": None,
                  "estimativa_max": None, "situacao": "aberto",
                  "preco_martelo": None, "data_resultado": None})
    lotes.append({"numero": 8, "titulo": "Moeda 20 Réis 1869 bronze MBC KM# 474",
                  "descricao": "", "url": "http://x/8", "foto_url": None,
                  "lance_inicial": 200.0, "estimativa_min": None,
                  "estimativa_max": None, "situacao": "aberto",
                  "preco_martelo": None, "data_resultado": None})

    (brutos / "leilao-1.json").write_text(json.dumps({
        "leilao": {"id": "1", "casa": "Casa de Teste", "casa_site": None,
                   "titulo": "Leilão 1", "data_pregao": "2026-05-10",
                   "url": "http://x", "cidade": "Rio de Janeiro", "uf": "RJ"},
        "lotes": lotes, "coletado_em": "2026-08-16T12:00:00+00:00",
    }, ensure_ascii=False), encoding="utf-8")

    construir_leiloes.BRUTOS = brutos
    construir_leiloes.DESTINO = banco
    construir_leiloes.construir()

    return StdioServerParameters(command=sys.executable, args=["-m", "leiloes"],
                                 env={"LEILOES_DB": str(banco),
                                      "PATH": "/usr/bin:/bin:/usr/local/bin",
                                      "PYTHONPATH": str(__import__("pathlib")
                                                        .Path.cwd())})


@pytest.mark.anyio
async def test_negocia_e_lista_ferramentas(parametros):
    async with stdio_client(parametros) as (ler, escrever):
        async with ClientSession(ler, escrever) as s:
            init = await s.initialize()
            assert init.serverInfo.name == "leiloes-numismatica"
            nomes = {t.name for t in (await s.list_tools()).tools}
            assert FERRAMENTAS_ESPERADAS <= nomes, FERRAMENTAS_ESPERADAS - nomes


@pytest.mark.anyio
async def test_oportunidades_declara_a_base_da_conta(parametros):
    async with stdio_client(parametros) as (ler, escrever):
        async with ClientSession(ler, escrever) as s:
            await s.initialize()
            r = await s.call_tool("oportunidades",
                                  {"margem_minima": 0.05, "n_minimo": 5})
            d = json.loads(r.content[0].text)
            assert d["achados"], d
            achado = d["achados"][0]
            assert achado["base_da_conta"]["n"] == 6
            assert achado["dinheiro"]["custo_total_de_arremate"] > \
                achado["dinheiro"]["lance_pedido"]
            # O lote sem identificação não pode sumir da resposta.
            assert d["lotes_abertos_sem_identificacao"] == 1


@pytest.mark.anyio
async def test_a_fracao_do_revendedor_chega_pela_ferramenta(parametros):
    """É o parâmetro que move a lista inteira; se não passar, a nota é fantasia."""
    async with stdio_client(parametros) as (ler, escrever):
        async with ClientSession(ler, escrever) as s:
            await s.initialize()
            r = await s.call_tool("oportunidades",
                                  {"margem_minima": 0.05, "n_minimo": 5,
                                   "fracao_revendedor": 0.20})
            d = json.loads(r.content[0].text)
            assert d["achados"] == []
            assert d["parametros"]["custos"]["fracao_revendedor"] == 0.20


@pytest.mark.anyio
async def test_lote_indefinido_sai_com_o_motivo(parametros):
    async with stdio_client(parametros) as (ler, escrever):
        async with ClientSession(ler, escrever) as s:
            await s.initialize()
            r = await s.call_tool("lotes_para_ler", {})
            d = json.loads(r.content[0].text)
            assert len(d["achados"]) == 1
            assert "1913" in d["achados"][0]["motivo"]
