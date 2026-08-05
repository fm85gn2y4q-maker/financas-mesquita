"""Testes dos relatórios do portal. Cada um guarda um erro que a medição pegou.

Pulam sozinhos enquanto a ingestão não tiver rodado, para não confundir
"ainda não ingeri" com "quebrou".
"""

from __future__ import annotations

import json

import pytest

from financas.acervo import Acervo


@pytest.fixture(scope="module")
def a() -> Acervo:
    return Acervo()


@pytest.fixture(scope="module", autouse=True)
def _exige_ingestao(a):
    if not a.relatorios_disponiveis():
        pytest.skip("relatórios ainda não ingeridos")


def test_cobertura_lista_os_relatorios(a):
    rels = a.cobertura()["relatorios_do_portal"]
    assert rels, "nenhum relatório declarado na cobertura"
    nomes = {r["regra"] for r in rels}
    assert any("despesa" in n for n in nomes), nomes
    for r in rels:
        assert r["coletado_em"] and r["coletado_em"] != "desconhecido"


def test_nenhuma_coluna_ganha_nome(a):
    """A regra central destes relatórios: o portal não exporta cabeçalho, e
    inventar rótulo por posição produz erro de atribuição, não lacuna."""
    r = a.pesquisar_relatorios("contrato", limite=5)
    assert r["achados"], "busca não achou nada"
    for achado in r["achados"]:
        assert isinstance(achado["colunas"], list)
        # colunas é vetor posicional — nunca um dicionário com rótulos
        assert not isinstance(achado["colunas"], dict)
    assert "SEM NOME" in r["como_ler"]


def test_derivados_apontam_a_posicao(a):
    """Derivado sem posição é inconferível: quem lê não consegue voltar à
    linha crua para checar de onde saiu."""
    r = a.pesquisar_relatorios("contrato", limite=20)
    vistos = 0
    for achado in r["achados"]:
        for d in achado["derivados"]:
            vistos += 1
            assert d["campo"] in {"cnpj_cpf", "data", "url", "valor"}
            assert 0 <= d["posicao"] < len(achado["colunas"])
            # o valor derivado tem de estar mesmo naquela posição
            assert d["valor"].strip() in (achado["colunas"][d["posicao"]] or "")
    assert vistos, "nenhum campo derivado em 20 linhas"


def test_pagamentos_por_documento_e_por_texto(a):
    """Aceitar CNPJ com e sem pontuação, e não confundir os dois caminhos."""
    r = a.pagamentos_a("33.683.111/0001-07")
    assert r["procurado"]
    assert "por_documento" in r and "por_texto" in r
    for item in r["por_documento"]:
        assert isinstance(item["colunas"], list)


def test_pontos_cegos_declara_a_falta_de_cabecalho(a):
    p = a.pontos_cegos()
    assert "relatorios_sem_nome_de_coluna" in p
    assert "cabeçalho" in p["relatorios_sem_nome_de_coluna"].lower()


def test_busca_vazia_nao_vira_ausencia(a):
    r = a.pesquisar_relatorios('"empresa que certamente nao existe ltda"')
    assert r["achados"] == []
    assert r["como_ler"], "resposta vazia sem instrução de leitura"
