"""A rota de busca do portal: categorias, paginação e a grade de resultados.

O que se testa aqui é a máquina, contra HTML escrito à mão. Os ENDEREÇOS e o
formato do parâmetro de categoria, esses são fato: vieram de páginas públicas
indexadas do próprio portal. A marcação da grade, não — a medição dela é o que
`descobrir_leiloesbr.py` faz numa máquina que alcance o site.
"""

from __future__ import annotations

from coletar_leiloesbr import analisar_busca, url_de_busca
from leiloes import fontes

# Grade de resultados: cartão com link, título e preço. Sem o rótulo "Lote",
# que numa busca pode nem aparecer.
GRADE = """
<div class="grade">
 <div class="cartao">
  <a href="/peca.asp?P=884411"><img src="/f/884411.jpg"></a>
  <a href="/peca.asp?P=884411">Moeda 20 R&eacute;is 1869 bronze MBC KM# 474</a>
  <span>Lance inicial: R$ 1.234,56</span>
 </div>
 <div class="cartao">
  <a href="/peca.asp?P=884412">Selo RHM C-9 novo, sem charneira</a>
  <span>Lance inicial: R$ 690,00</span>
 </div>
 <div class="cartao">
  <a href="peca.asp?P=884413">Moeda de ouro 20$000 1851 - Bentes 123.01 - FC</a>
  <span>R$ 4.200,00</span>
 </div>
</div>
"""


def test_a_categoria_e_hexadecimal_em_cp1252():
    """Medido em endereços públicos do portal: tp=|43696E656D61| é "Cinema", e
    o ê de "Efêmera" aparece como EA — um byte, cp1252. Em UTF-8 seria C3AA, e
    o nome errado não dá erro: devolve busca vazia, que passa por "não há peça
    nesta categoria"."""
    assert fontes.categoria_hex("Cinema") == "|43696E656D61|"
    assert fontes.categoria_hex("Memorabilia & Efêmera") == \
        "|4D656D6F726162696C69612026204566EA6D657261|"
    # "Numismática" tem á, que em cp1252 é E1 — um byte. Em UTF-8 seriam dois.
    assert "E1" in fontes.categoria_hex("Numismática")
    assert fontes.categoria_hex("Numismática") == "|4E756D69736DE174696361|"


def test_a_url_de_busca_leva_a_categoria_codificada():
    url = url_de_busca(fontes.BUSCA_ABERTOS, categoria="Filatelia")
    assert "busca_andamento.asp" in url
    assert "tp=%7C46696C6174656C6961%7C" in url
    assert "pesquisa=" in url


def test_busca_sem_categoria_nao_manda_filtro():
    url = url_de_busca(fontes.BUSCA_ABERTOS)
    assert "tp=%7C&" in url or url.endswith("tp=%7C")


def test_a_grade_e_dividida_pelo_link_e_nao_pelo_rotulo():
    """Numa grade o rótulo "Lote" pode não existir; o link da peça existe
    sempre, porque é ele que faz a página funcionar."""
    lotes = analisar_busca(GRADE, "aberto")
    assert len(lotes) == 3
    assert "20 Réis 1869" in lotes[0]["titulo"]
    assert lotes[0]["lance_inicial"] == 1234.56
    assert lotes[1]["lance_inicial"] == 690.0
    # Sem rótulo de preço, vale qualquer valor em reais do cartão.
    assert lotes[2]["lance_inicial"] == 4200.0


def test_o_preco_de_um_cartao_nao_vaza_para_o_outro():
    lotes = analisar_busca(GRADE, "aberto")
    assert [l["lance_inicial"] for l in lotes] == [1234.56, 690.0, 4200.0]


def test_o_mesmo_link_repetido_no_cartao_nao_vira_dois_lotes():
    """O primeiro cartão tem dois links para a mesma peça — foto e título."""
    assert len(analisar_busca(GRADE, "aberto")) == 3


def test_as_duas_ocorrencias_do_cartao_sao_fundidas():
    """A regressão: ficando com a PRIMEIRA ocorrência, o lote saía sem título e
    sem preço, porque ambos estão no segundo link. Cada ocorrência traz um
    pedaço — a da foto traz a imagem, a do título traz título e preço."""
    primeiro = analisar_busca(GRADE, "aberto")[0]
    assert "20 Réis 1869" in primeiro["titulo"]      # veio do link do título
    assert primeiro["lance_inicial"] == 1234.56      # veio do mesmo bloco
    assert primeiro["foto_url"].endswith("/f/884411.jpg")   # veio do link da foto


def test_lote_sem_foto_fica_sem_foto():
    """O sinal "sem foto" só vale se a ausência for real."""
    lotes = analisar_busca(GRADE, "aberto")
    assert lotes[1]["foto_url"] is None


def test_a_situacao_vem_da_rota_e_nao_do_texto():
    """A grade não diz se o lote está em pregão ou em venda pós-pregão; quem
    sabe isso é o endpoint de onde ela veio."""
    assert all(l["situacao"] == "pos_pregao"
               for l in analisar_busca(GRADE, "pos_pregao"))


def test_a_url_do_lote_fica_absoluta():
    """URL relativa gravada no acervo não abre em lugar nenhum depois."""
    for lote in analisar_busca(GRADE, "aberto"):
        assert lote["url"].startswith("https://www.leiloesbr.com.br/")
