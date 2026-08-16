"""O acervo de leilões: identificação, construção e motor de assimetria.

Estes testes rodam sem rede. O que eles cobrem é tudo que fica DEPOIS do
coletor — identificação, chave de comparação, custos, mediana e a recusa a
pontuar —, que é onde o acervo pode errar caro. O coletor tem teste próprio
com HTML gravado, em `test_coletor_leiloes.py`.
"""

from __future__ import annotations

import json

import pytest

from leiloes.acervo import Acervo, Custos
from leiloes.identificacao import chave_da_peca, identificar


# --------------------------------------------------------------- identificação

def test_codigo_de_catalogo_e_grau_dao_identificacao_firme():
    peca = identificar("Moeda 20 Réis 1869 bronze MBC KM# 474")
    assert peca["confianca"] == "firme"
    assert peca["chave"] == "KM:474|MBC"
    assert peca["anos"] == [1869]


def test_denominacao_em_mil_reis_e_lida():
    peca = identificar("Moeda de ouro 20$000 1851 - Bentes 123.01 - FC")
    assert peca["denominacao"] == "20000 réis"
    assert peca["chave"] == "Bentes:123.01|FC"


def test_o_numero_da_denominacao_nao_vira_ano():
    """A armadilha central: em "1000 Réis 1913" o 1000 não é ano de cunho.

    Sem o desarme, todo lote de mil-réis ganhava um ano inventado — e ano
    errado casa o lote com o comparável de outra peça, que é a forma mais cara
    de errar neste acervo.
    """
    peca = identificar("1000 Réis 1913 Estrelas, prata, Soberba")
    assert peca["anos"] == [1913]


def test_a_mesma_peca_escrita_de_dois_jeitos_da_a_mesma_chave():
    """Se a chave não sair igual, o comparável não casa e a peça fica sem base."""
    a = identificar("Moeda 1 Cruzeiro 1942 PCGS MS-65")
    b = identificar("Moeda 1 Cruzeiros 1942 PCGS MS-65")
    assert a["chave"] is not None
    assert a["chave"] == b["chave"]


def test_1913_sem_a_serie_fica_indefinido():
    peca = identificar("1000 Réis 1913, prata, Soberba")
    assert peca["confianca"] == "indefinida"
    assert peca["chave"] is None
    assert "1913" in peca["motivo"]


def test_replica_nunca_recebe_chave():
    peca = identificar("Réplica moeda 1000 Réis 1922 Independência, FC")
    assert peca["confianca"] == "indefinida"
    assert peca["chave"] is None


def test_selo_se_identifica_por_catalogo_e_goma_sem_precisar_de_ano():
    """Selo não tem ano de cunho no texto nem grau na escala da moeda. A
    primeira versão exigia os dois e jogava a filatelia inteira fora."""
    peca = identificar("Selo RHM C-123 novo, sem charneira")
    assert peca["confianca"] == "firme"
    assert peca["estado"] == "novo sem charneira"


def test_selo_novo_sem_dizer_a_goma_fica_indefinido():
    peca = identificar("Selo RHM C-123 novo")
    assert peca["confianca"] == "indefinida"


def test_sem_charneira_nao_e_lido_como_com_charneira():
    """A ordem do teste importa: "sem charneira" contém "charneira"."""
    assert identificar("Selo RHM C-9 novo, sem charneira")["estado"] \
        == "novo sem charneira"
    assert identificar("Selo RHM C-9 novo, com charneira")["estado"] \
        == "novo com charneira"


def test_lote_com_varios_anos_nao_tem_peca_unica():
    peca = identificar("Lote com moedas de 1922, 1935 e 1942, FC")
    assert peca["confianca"] == "indefinida"


def test_entre_dois_graus_fica_o_pior():
    """Supor o melhor lado da peça infla a margem esperada."""
    assert identificar("Moeda 400 Réis 1901 níquel, MBC/S")["estado"] == "MBC/S"
    assert identificar("Moeda 400 Réis 1901 níquel, MBC, quase S")["estado"] == "MBC"


def test_peca_sem_estado_nao_tem_chave():
    assert chave_da_peca({"confianca": "provavel", "especie": "moeda",
                          "anos": [1900], "codigos": [], "estado": None}) is None


# ------------------------------------------------------------------- fixtures

def _leilao(id_, casa, data, lotes, uf="RJ"):
    return {
        "leilao": {"id": id_, "casa": casa, "casa_site": f"http://{casa}.com.br",
                   "titulo": f"Leilão {id_}", "data_pregao": data,
                   "url": f"https://www.leiloesbr.com.br/leilao.asp?Num={id_}",
                   "cidade": "Rio de Janeiro", "uf": uf},
        "lotes": lotes,
        "coletado_em": "2026-08-16T12:00:00+00:00",
    }


def _lote(numero, titulo, **kw):
    base = {"numero": numero, "titulo": titulo, "descricao": kw.pop("descricao", ""),
            "url": f"https://www.leiloesbr.com.br/lote.asp?L={numero}",
            "foto_url": kw.pop("foto_url", "http://x/f.jpg"),
            "lance_inicial": None, "estimativa_min": None, "estimativa_max": None,
            "situacao": "aberto", "preco_martelo": None, "data_resultado": None}
    base.update(kw)
    return base


@pytest.fixture
def acervo(tmp_path, monkeypatch):
    """Seis martelos de uma mesma peça, mais lotes abertos para o motor medir."""
    import construir_leiloes

    brutos = tmp_path / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    destino = tmp_path / "dados" / "leiloes.db"
    monkeypatch.setattr(construir_leiloes, "BRUTOS", brutos)
    monkeypatch.setattr(construir_leiloes, "DESTINO", destino)

    vendidos = [
        _lote(n, "Moeda 20 Réis 1869 bronze MBC KM# 474",
              descricao="Peça de bronze do Império, reverso limpo, sem soldas.",
              situacao="arrematado", preco_martelo=preco,
              data_resultado=f"2026-0{n}-10")
        for n, preco in enumerate([900, 1000, 1050, 980, 1100, 1020], start=1)
    ]
    historico = _leilao("101", "Moderna Leiloes", "2026-06-10", vendidos)

    abertos = [
        # Barato para o que a peça faz: deve aparecer.
        _lote(1, "Moeda 20 Réis 1869 bronze MBC KM# 474", lance_inicial=300.0,
              descricao="Bronze."),
        # No preço: não deve aparecer.
        _lote(2, "Moeda 20 Réis 1869 bronze MBC KM# 474", lance_inicial=560.0,
              descricao="Bronze, boa peça, reverso íntegro, procedência de coleção."),
        # Sem comparável no acervo.
        _lote(3, "Moeda 2000 Réis 1935 prata FC KM# 535", lance_inicial=100.0),
        # Sem identificação: não pode receber nota.
        _lote(4, "1000 Réis 1913, prata, Soberba", lance_inicial=50.0),
    ]
    aberto = _leilao("202", "Antigo Moderno", "2026-09-01", abertos)

    for nome, dados in (("leilao-101.json", historico), ("leilao-202.json", aberto)):
        (brutos / nome).write_text(json.dumps(dados, ensure_ascii=False),
                                   encoding="utf-8")

    construir_leiloes.construir()
    return Acervo(destino)


# --------------------------------------------------------------------- acervo

def test_construcao_separa_identificado_de_indefinido(acervo):
    cobertura = acervo.cobertura()
    assert cobertura["lotes"]["total"] == 10
    assert cobertura["identificacao"]["indefinidos"] == 1


def test_comparaveis_usam_mediana_e_declaram_o_periodo(acervo):
    base = acervo.comparaveis("KM:474|MBC")
    assert base["n"] == 6
    assert base["mediana"] == 1010
    assert base["periodo_dos_comparaveis"]["de"] == "2026-01-10"


def test_o_custo_de_arremate_nao_e_o_lance(acervo):
    """Comissão, taxa e frete são a diferença entre a margem real e a fantasia."""
    custos = Custos(comissao=0.05, taxa_administrativa=0.05, frete=45.0)
    assert custos.custo_de_arremate(1000) == pytest.approx(1145.0)


def test_oportunidade_aparece_com_a_conta_completa(acervo):
    saida = acervo.oportunidades(margem_minima=0.10, n_minimo=5)
    achados = saida["achados"]
    assert len(achados) == 1

    achado = achados[0]
    assert achado["peca"]["chave"] == "KM:474|MBC"
    assert achado["dinheiro"]["lance_pedido"] == 300.0
    # 300 * 1,10 + 45 = 375; revenda = 1010 * 0,5 = 505; margem = 130.
    assert achado["dinheiro"]["custo_total_de_arremate"] == pytest.approx(375.0)
    assert achado["dinheiro"]["margem"] == pytest.approx(130.0)
    assert achado["base_da_conta"]["n"] == 6


def test_lote_no_preco_nao_vira_oportunidade(acervo):
    saida = acervo.oportunidades(margem_minima=0.10, n_minimo=5)
    assert all(a["dinheiro"]["lance_pedido"] != 560.0 for a in saida["achados"])


def test_peca_sem_comparavel_nao_recebe_nota_e_e_contada(acervo):
    saida = acervo.oportunidades(margem_minima=0.10, n_minimo=5)
    assert saida["descartados_por_falta_de_comparavel"] == 1
    assert all("1935" not in a["lote"]["titulo"] for a in saida["achados"])


def test_lote_indefinido_fica_fora_da_lista_mas_e_declarado(acervo):
    """O ponto cego não pode sumir: sem a contagem, a lista curta passa por
    mercado sem oportunidade."""
    saida = acervo.oportunidades(margem_minima=0.10, n_minimo=5)
    assert saida["lotes_abertos_sem_identificacao"] == 1
    assert "lotes_para_ler" in saida["como_ler"]

    fila = acervo.lotes_para_ler()
    assert len(fila["achados"]) == 1
    assert "1913" in fila["achados"][0]["motivo"]


def test_a_fracao_do_revendedor_move_a_lista_inteira(acervo):
    """É a variável mais sensível do motor, e a única que ninguém publica."""
    magro = Acervo(acervo.caminho, custos=Custos(fracao_revendedor=0.30))
    assert magro.oportunidades(margem_minima=0.10, n_minimo=5)["achados"] == []


def test_lote_de_pos_pregao_entra_na_lista_e_sai_sinalizado(tmp_path, monkeypatch):
    """O que não arrematou e ficou à venda depois é peça que o mercado já
    esqueceu uma vez. Deixá-lo fora excluiria justamente o alvo da busca."""
    import construir_leiloes

    brutos = tmp_path / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    destino = tmp_path / "dados" / "leiloes.db"
    monkeypatch.setattr(construir_leiloes, "BRUTOS", brutos)
    monkeypatch.setattr(construir_leiloes, "DESTINO", destino)

    lotes = [_lote(n, "Moeda 20 Réis 1869 bronze MBC KM# 474",
                   descricao="Bronze do Império, reverso limpo, sem soldas.",
                   situacao="arrematado", preco_martelo=1000.0 + n,
                   data_resultado="2026-03-10") for n in range(1, 7)]
    lotes.append(_lote(50, "Moeda 20 Réis 1869 bronze MBC KM# 474",
                       situacao="pos_pregao", lance_inicial=250.0))
    (brutos / "leilao-1.json").write_text(
        json.dumps(_leilao("1", "Casa", "2026-03-10", lotes), ensure_ascii=False),
        encoding="utf-8")
    construir_leiloes.construir()

    saida = Acervo(destino).oportunidades(margem_minima=0.10, n_minimo=5)
    assert len(saida["achados"]) == 1
    achado = saida["achados"][0]
    assert achado["lote"]["situacao"] == "pos_pregao"
    assert any("pós-pregão" in s for s in achado["por_que_pode_estar_esquecido"])


@pytest.fixture
def acervo_com_erro_de_grafia(tmp_path, monkeypatch):
    """Um catálogo onde "bronze" é corrente e um lote escreve "bronse"."""
    import construir_leiloes

    brutos = tmp_path / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    destino = tmp_path / "dados" / "leiloes.db"
    monkeypatch.setattr(construir_leiloes, "BRUTOS", brutos)
    monkeypatch.setattr(construir_leiloes, "DESTINO", destino)

    lotes = [_lote(n, f"Moeda 2 Cruzeiros {1936 + n} bronze MBC KM# 558",
                   descricao="Bronze de cunho firme.", situacao="arrematado",
                   preco_martelo=180.0 + n, data_resultado="2026-03-10")
             for n in range(1, 26)]
    lotes.append(_lote(90, "Moeda 2 Cruzeiros 1942 bronse MBC KM# 558",
                       lance_inicial=40.0))
    (brutos / "leilao-1.json").write_text(
        json.dumps(_leilao("1", "Casa", "2026-03-10", lotes), ensure_ascii=False),
        encoding="utf-8")
    construir_leiloes.construir()
    return Acervo(destino)


def test_erro_de_uma_letra_e_detectado(acervo_com_erro_de_grafia):
    """A regressão que o demo pegou: com `difflib` e corte em 0,86, "bronse"
    contra "bronze" dava 0,833 e o sinal NUNCA disparava — justamente na classe
    de erro mais comum, e em silêncio."""
    achados = acervo_com_erro_de_grafia._grafia_divergente(
        "Moeda 2 Cruzeiros 1942 bronse MBC KM# 558")
    assert achados == [{"escrito": "bronse", "corrente_no_catalogo": "bronze"}]


def test_palavra_correta_nao_vira_erro_de_grafia(acervo_com_erro_de_grafia):
    """O sinal só vale se não disparar no lote bem escrito."""
    assert acervo_com_erro_de_grafia._grafia_divergente(
        "Moeda 2 Cruzeiros 1942 bronze MBC KM# 558") == []


def test_descricao_curta_e_sinalizada(acervo):
    achado = acervo.oportunidades(margem_minima=0.10, n_minimo=5)["achados"][0]
    assert any("descrição curta" in s
               for s in achado["por_que_pode_estar_esquecido"])
