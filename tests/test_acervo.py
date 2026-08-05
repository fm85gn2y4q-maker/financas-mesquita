"""Testes de aceitação. Cada um guarda um erro que a medição já pegou uma vez."""

from __future__ import annotations

import pytest

from financas.acervo import Acervo


@pytest.fixture(scope="module")
def a() -> Acervo:
    return Acervo()


def test_cobertura_declara_o_que_falta(a):
    """O acervo tem de declarar as ausências, não só o que possui.

    Este teste já exigiu a palavra "captcha", de quando eu supunha que ela
    fechava o financeiro do portal. Fechava só a ENTRADA do formulário de
    despesas: a exportação "Dados Abertos" sai por outra rota, sem captcha.
    O teste falhou quando a afirmação caiu — que é para o que ele serve.
    """
    c = a.cobertura()
    assert c["siconfi"]["linhas"] > 100_000
    faltas = c["o_que_NAO_esta_aqui"]
    assert faltas, "cobertura sem nenhuma ausência declarada"
    assert any("diário oficial" in s.lower() for s in faltas), faltas


def test_hierarquia_do_siconfi_nao_e_inventada(a):
    """A conferência pela soma não pode ser trocada por 'a linha anterior era
    uma função, logo esta é filha dela'. Onde não fechou, fica declarado.

    Roda em TODAS as colunas do período, porque foi justamente o cruzamento
    entre colunas que produziu a primeira agregação errada.
    """
    achou_alguma = False
    for coluna in a.colunas_da_despesa(2025, 6):
        r = a.despesa_por_funcao(2025, 6, coluna)
        for bloco in r["blocos"]:
            for f in bloco["funcoes"]:
                if not f["subfuncoes"]:
                    continue
                achou_alguma = True
                soma = sum(s["valor"] or 0 for s in f["subfuncoes"])
                assert abs(soma - (f["valor"] or 0)) < 1000, (
                    f"{coluna} / {f['funcao']}: agregada sem que a soma feche "
                    f"({soma} vs {f['valor']})")
            if bloco["nao_vinculadas"]:
                assert r["aviso"], "há linhas não vinculadas e nenhum aviso"
    assert achou_alguma, "nenhuma função com subfunções em 2025"


def test_coluna_inexistente_nao_devolve_vazio_silencioso(a):
    r = a.despesa_por_funcao(2025, 6, "DESPESAS EMPENHADAS")
    assert "erro" in r and r["colunas_disponiveis"]


def test_administracao_geral_nao_colapsa(a):
    """O caso que motivou o campo `ordem`: o mesmo nome de conta sob funções
    diferentes tem de continuar sendo linhas distintas.

    A `ordem` é única dentro de (arquivo, anexo, coluna, rótulo) — não no
    acervo inteiro. Por isso o teste fixa período e rótulo.
    """
    linhas = [x for x in a.serie(conta="Administração Geral", anexo="RREO-Anexo 02",
                                 exercicio=2015, limite=400)
              if x["coluna"] == "DOTAÇÃO INICIAL" and x["periodo"] == 1]
    assert linhas, "a conta sumiu do acervo"

    # Em 2015 o rótulo vem nulo; em exercícios recentes, não. Agrupar por ele
    # em vez de supor um valor.
    por_rotulo: dict = {}
    for x in linhas:
        por_rotulo.setdefault(x["rotulo"], []).append(x)

    assert any(len(v) > 1 for v in por_rotulo.values()), "colapsou numa só"
    for rotulo, bloco in por_rotulo.items():
        assert len({x["ordem"] for x in bloco}) == len(bloco), (
            f"ordem não distingue as linhas do rótulo {rotulo!r}")
        if len(bloco) > 1:
            assert len({x["valor"] for x in bloco}) > 1


def test_toda_resposta_traz_data_de_coleta(a):
    """A regra central do acervo: número sem procedência não sai daqui."""
    for linha in a.serie(demonstrativo="RREO", limite=5):
        assert linha["coletado_em"] and linha["coletado_em"] != "desconhecido"
    for doc in a.contratacoes(limite=5):
        assert doc["coletado_em"]
    for bem in a.bens(limite=5):
        assert bem["coletado_em"]


def test_somatorio_do_patrimonio_nunca_sai_sozinho(a):
    """R$ 32,7 bi somados num Município de orçamento R$ 682 mi. O número é o que
    o cadastro diz; citá-lo sem a concentração é que seria falso."""
    p = a.cobertura()["patrimonio"]
    assert p["aviso_sobre_o_total"]
    assert p["bens_acima_de_100_milhoes"]["quantidade"] > 0
    # A concentração tem de ser gritante o bastante para justificar o aviso.
    assert p["bens_acima_de_100_milhoes"]["valor_somado"] > 0.5 * p["valor_somado"]
    assert p["mediana_do_valor"] < 100_000


def test_patrimonio_declara_que_nao_e_serie(a):
    assert "fotografia" in a.cobertura()["patrimonio"]["natureza"].lower()
    assert "fotografia" in a.pontos_cegos()["patrimonio"].lower()


def test_conciliar_nao_afirma_ausencia(a):
    r = a.conciliar("empresa que certamente nao existe ltda")
    assert r["pncp"]["encontrados"] == 0
    # Não achar em duas fontes não pode virar "não existe".
    assert r["onde_mais_procurar"]
    assert "não é ausência do fato" in r["como_ler"]
