"""A peneira do valor intrínseco: custo de arremate abaixo do metal da peça.

É a única peneira deste acervo cujo piso não depende da opinião de ninguém.
Por isso ela é a que mais precisa se recusar a calcular onde não sabe: sem
peso, sem teor ou sem cotação, o resultado não é aproximado — é inventado.
"""

from __future__ import annotations

import json

import pytest

from ingerir_catalogo_aga import ingerir
from leiloes.acervo import Acervo, Custos

CATALOGO = """
                                   Império
         D. Pedro II (1831-1889)
               Casa da moeda do Rio de Janeiro
                           Letra monetária R

                                         2.000 Réis

                    Prata – 25,50 g – D 37,0 mm

Núm.      Data           Quantidades Observações          BC              MBC             SOB
 900      1852       R - Quant. 1.000                       100,00         200,00        400,00
"""


def _acervo(tmp_path, monkeypatch, lotes, teores=None):
    import construir_leiloes

    dados = tmp_path / "dados"
    dados.mkdir()
    origem = tmp_path / "aga.txt"
    origem.write_text(CATALOGO, encoding="utf-8")
    ingerir(origem, dados / "catalogo.db")

    brutos = tmp_path / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    monkeypatch.setattr(construir_leiloes, "BRUTOS", brutos)
    monkeypatch.setattr(construir_leiloes, "DESTINO", dados / "leiloes.db")
    monkeypatch.delenv("CATALOGO_DB", raising=False)
    (brutos / "leilao-1.json").write_text(json.dumps({
        "leilao": {"id": "1", "casa": "Casa", "data_pregao": "2026-09-01",
                   "url": "http://x", "uf": "RJ"},
        "lotes": lotes, "coletado_em": "2026-08-16T12:00:00+00:00",
    }, ensure_ascii=False), encoding="utf-8")
    construir_leiloes.construir()

    if teores is not None:
        # Passa pelo CARREGADOR de verdade, e não por monkeypatch do método:
        # o filtro que descarta entrada sem fonte mora nele, e substituí-lo
        # deixaria justamente esse filtro sem teste.
        caminho = tmp_path / "teores.json"
        caminho.write_text(json.dumps(teores, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setenv("TEORES_JSON", str(caminho))

    return Acervo(dados / "leiloes.db",
                  custos=Custos(comissao=0.05, taxa_administrativa=0.05, frete=0.0))


def _lote(numero, **kw):
    base = {"numero": numero, "titulo": "Moeda 2000 Réis 1852 prata MBC",
            "descricao": "Prata do Império.", "url": f"http://x/{numero}",
            "situacao": "aberto", "lance_inicial": 100.0, "lances": 0}
    base.update(kw)
    return base


TEOR = {"prata": {"2000 réis|1849-1889": {"teor": 0.900,
                                          "fonte": "teste, não é fonte real"}}}


def test_peca_abaixo_do_metal_aparece_com_a_conta(tmp_path, monkeypatch):
    # 25,50 g × 0,900 = 22,95 g de prata fina. A R$ 6,00/g → R$ 137,70.
    # Custo de 100 × 1,10 = R$ 110,00. Fica abaixo: é achado.
    acervo = _acervo(tmp_path, monkeypatch, [_lote(1)], TEOR)
    saida = acervo.abaixo_do_metal({"prata": 6.00}, periodo="imperio")

    assert len(saida["achados"]) == 1
    d = saida["achados"][0]["dinheiro"]
    assert d["metal_fino_g"] == pytest.approx(22.95)
    assert d["valor_do_metal"] == pytest.approx(137.70)
    assert d["custo_total_de_arremate"] == pytest.approx(110.0)
    # 1 − 110,00/137,70 = 0,2012
    assert d["desconto_sobre_o_metal"] == pytest.approx(0.201, abs=0.001)


def test_o_custo_de_arremate_e_que_conta_nao_o_lance(tmp_path, monkeypatch):
    """A R$ 130 de lance a peça ainda pareceria barata contra 137,70 — mas o
    custo real é 143, acima do metal. Comparar lance com metal é o erro."""
    acervo = _acervo(tmp_path, monkeypatch, [_lote(1, lance_inicial=130.0)], TEOR)
    assert acervo.abaixo_do_metal({"prata": 6.00})["achados"] == []


def test_sem_teor_declarado_a_peca_nao_entra_e_e_listada(tmp_path, monkeypatch):
    """Peso bruto não é prata fina. Sem teor, a conta não se faz — e o que
    ficou de fora tem de aparecer, senão a lista curta passa por mercado sem
    oportunidade."""
    acervo = _acervo(tmp_path, monkeypatch, [_lote(1)], {"prata": {}})
    saida = acervo.abaixo_do_metal({"prata": 6.00})

    assert saida["achados"] == []
    assert saida["sem_teor_declarado"] == {"2000 réis (1852)": 1}
    assert "teores.json" in saida["como_ler"]


def test_teor_sem_fonte_declarada_nao_conta(tmp_path, monkeypatch):
    """Número posto 'só para testar' não pode virar base de decisão de compra."""
    sem_fonte = {"prata": {"2000 réis|1849-1889": {"teor": 0.900, "fonte": ""}}}
    acervo = _acervo(tmp_path, monkeypatch, [_lote(1)], sem_fonte)
    saida = acervo.abaixo_do_metal({"prata": 6.00})
    assert saida["achados"] == []
    assert saida["sem_teor_declarado"] == {"2000 réis (1852)": 1}


def test_lote_com_lance_fica_de_fora_quando_se_pede_sem_lance(tmp_path, monkeypatch):
    acervo = _acervo(tmp_path, monkeypatch, [_lote(1, lances=3)], TEOR)
    assert acervo.abaixo_do_metal({"prata": 6.00}, sem_lance=True)["achados"] == []
    assert acervo.abaixo_do_metal({"prata": 6.00}, sem_lance=False)["achados"]


def test_contagem_desconhecida_nao_e_tratada_como_zero(tmp_path, monkeypatch):
    """`lances` nulo é "não sei", e "sem lance" é peneira de peça esquecida:
    tratar desconhecido como zero encheria a lista de lotes disputados."""
    acervo = _acervo(tmp_path, monkeypatch, [_lote(1, lances=None)], TEOR)
    assert acervo.abaixo_do_metal({"prata": 6.00}, sem_lance=True)["achados"] == []
    assert acervo.abaixo_do_metal({"prata": 6.00}, sem_lance=False)["achados"]


def test_o_periodo_recorta_por_ano(tmp_path, monkeypatch):
    acervo = _acervo(tmp_path, monkeypatch, [_lote(1)], TEOR)
    assert acervo.abaixo_do_metal({"prata": 6.00}, periodo="imperio")["achados"]
    assert acervo.abaixo_do_metal({"prata": 6.00}, periodo="republica")["achados"] == []
    assert "periodos" in acervo.abaixo_do_metal({"prata": 6.00}, periodo="barroco")


def test_sem_cotacao_a_peneira_se_recusa(tmp_path, monkeypatch):
    acervo = _acervo(tmp_path, monkeypatch, [_lote(1)], TEOR)
    assert "erro" in acervo.abaixo_do_metal({})
    assert "erro" in acervo.abaixo_do_metal({"prata": 0})


def test_sem_catalogo_a_peneira_se_recusa(tmp_path, monkeypatch):
    """Sem peso não há valor de metal, e o peso vem do catálogo."""
    import construir_leiloes

    dados = tmp_path / "dados"
    dados.mkdir()
    brutos = tmp_path / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    monkeypatch.setattr(construir_leiloes, "BRUTOS", brutos)
    monkeypatch.setattr(construir_leiloes, "DESTINO", dados / "leiloes.db")
    monkeypatch.delenv("CATALOGO_DB", raising=False)
    (brutos / "leilao-1.json").write_text(json.dumps({
        "leilao": {"id": "1", "casa": "Casa", "data_pregao": "2026-09-01",
                   "url": "http://x", "uf": "RJ"},
        "lotes": [_lote(1)], "coletado_em": "2026-08-16T12:00:00+00:00",
    }, ensure_ascii=False), encoding="utf-8")
    construir_leiloes.construir()

    saida = Acervo(dados / "leiloes.db").abaixo_do_metal({"prata": 6.00})
    assert "catálogo" in saida["erro"]
