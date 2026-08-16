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


def test_o_codificador_reproduz_os_enderecos_do_proprio_portal():
    """A única validação de verdade que este acervo tem contra o site.

    Cada par abaixo foi colhido de endereço PÚBLICO INDEXADO do LeilõesBR — o
    hexadecimal veio do site, e o nome é o título da página. Se o codificador
    reproduz o hexadecimal a partir do nome, ele fala a língua do portal.
    """
    do_portal = {
        "Numismática - Moedas": "4E756D69736DE174696361202D204D6F65646173",
        "Numismática - Moedas do Brasil":
            "4E756D69736DE174696361202D204D6F6564617320646F2042726173696C",
        "Numismática - Moedas Estrangeiras":
            "4E756D69736DE174696361202D204D6F656461732045737472616E676569726173",
        "Numismática - Moeda Romana":
            "4E756D69736DE174696361202D204D6F65646120526F6D616E61",
        "Numismática - Cédulas": "4E756D69736DE174696361202D2043E964756C6173",
        "Numismática - Cédulas Brasileiras":
            "4E756D69736DE174696361202D2043E964756C61732042726173696C6569726173",
        "Filatelia": "46696C6174656C6961",
        "Cinema": "43696E656D61",
        "Memorabilia & Efêmera": "4D656D6F726162696C69612026204566EA6D657261",
    }
    for nome, hexa in do_portal.items():
        assert fontes.categoria_hex(nome) == f"|{hexa}|", nome


def test_numismatica_sozinha_nao_e_categoria_do_portal():
    """A armadilha medida: o portal só usa "Numismática - <sub>". Pedir
    "Numismática" devolve busca VAZIA, que passa por "não há peça na
    categoria" — e não por "a categoria não existe"."""
    assert "Numismática" not in fontes.CATEGORIAS_OBSERVADAS["numismatica"]
    assert all(c.startswith("Numismática - ")
               for c in fontes.CATEGORIAS_OBSERVADAS["numismatica"])


def test_o_segmento_expande_para_todas_as_subcategorias():
    """Sem isto, varrer numismática exigiria saber de cor oito nomes exatos."""
    assert len(fontes.categorias_do_segmento("numismatica")) == 8
    assert fontes.categorias_do_segmento("numismática") == \
        fontes.categorias_do_segmento("numismatica")
    assert fontes.categorias_do_segmento("filatelia") == ("Filatelia",)


def test_segmento_desconhecido_diz_quais_existem():
    import pytest as _pytest

    with _pytest.raises(SystemExit) as erro:
        fontes.categorias_do_segmento("mobiliário")
    assert "numismatica" in str(erro.value)


def test_a_galeria_e_a_uf_vao_em_texto_e_nao_em_hexadecimal():
    """Medido: o portal traz `default.asp?ga=Brasil+Moedas+Leilões` e `uf=*`.
    Codificar `ga` como se fosse `tp` devolveria busca vazia."""
    url = url_de_busca(fontes.BUSCA_ABERTOS, uf="RJ", galeria="Brasil Moedas")
    assert "uf=RJ" in url
    assert "ga=Brasil+Moedas" in url


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
