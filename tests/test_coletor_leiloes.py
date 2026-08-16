"""O extrator de lotes, contra HTML de mentira.

O QUE ESTES TESTES PROVAM, E O QUE NÃO PROVAM

Provam a máquina: que o separador de blocos não mistura o preço de um lote com
o título do vizinho, que o real brasileiro não é lido com o separador
invertido, que lote arrematado e lote deserto saem com situações distintas.

NÃO provam que os padrões casam com o LeilõesBR de verdade. O HTML abaixo foi
escrito à mão, sem acesso ao portal, e um teste que só confirma a hipótese de
quem o escreveu não é evidência de nada. A medição do portal real é o que
`descobrir_leiloesbr.py` faz, numa máquina que o alcance.
"""

from __future__ import annotations

from coletar_leiloesbr import analisar_pagina, ids_de_leilao, reais, so_texto

PAGINA = """
<html><head><style>.x{color:red}</style></head><body>
<h1>Antigo Moderno Leil&otilde;es &mdash; 42&ordm; Leil&atilde;o de Numism&aacute;tica</h1>
<p>Preg&atilde;o em 01/09/2026 &agrave;s 20:00</p>
<table>
 <tr><td>Lote n&ordm; 1</td></tr>
 <tr><td>Moeda 20 R&eacute;is 1869 bronze MBC KM# 474</td></tr>
 <tr><td>Bronze do Imp&eacute;rio, reverso limpo.</td></tr>
 <tr><td>Lance inicial: R$ 1.234,56</td></tr>
</table>
<table>
 <tr><td>Lote n&ordm; 2</td></tr>
 <tr><td>Moeda 400 R&eacute;is 1901 n&iacute;quel MBC</td></tr>
 <tr><td>Arrematado por: R$ 2.000,00 em 01/09/2026</td></tr>
</table>
<table>
 <tr><td>Lote n&ordm; 3</td></tr>
 <tr><td>Selo RHM C-9 novo, sem charneira</td></tr>
 <tr><td>N&atilde;o arrematado</td></tr>
</table>
<script>var x = "Lote 999 R$ 1,00";</script>
</body></html>
"""


def test_script_e_style_nao_viram_lote():
    """O `var x = "Lote 999"` do script não pode entrar como lote 999."""
    assert "var x" not in so_texto(PAGINA)
    assert all(lote["numero"] != 999 for lote in analisar_pagina(PAGINA))


def test_cada_lote_fica_com_o_proprio_titulo_e_o_proprio_preco():
    lotes = analisar_pagina(PAGINA)
    assert [l["numero"] for l in lotes] == [1, 2, 3]
    assert "20 Réis 1869" in lotes[0]["titulo"]
    assert lotes[0]["lance_inicial"] == 1234.56
    # O preço do lote 2 não pode vazar para o lote 1.
    assert lotes[0]["preco_martelo"] is None


def test_o_separador_decimal_brasileiro_nao_e_lido_ao_contrario():
    """"1.234,56" lido como float americano dá 1,234 — erro de mil vezes."""
    assert reais("1.234,56") == 1234.56
    assert reais("2.000,00") == 2000.0
    assert reais(None) is None
    assert reais("não é preço") is None


def test_arrematado_deserto_e_aberto_saem_com_situacoes_distintas():
    lotes = {l["numero"]: l for l in analisar_pagina(PAGINA)}
    assert lotes[1]["situacao"] == "aberto"
    assert lotes[2]["situacao"] == "arrematado"
    assert lotes[2]["preco_martelo"] == 2000.0
    assert lotes[2]["data_resultado"] == "2026-09-01"
    assert lotes[3]["situacao"] == "nao_arrematado"


def test_as_entidades_html_sao_desfeitas():
    """`R&eacute;is` que sobrevive como entidade não casa com nenhum comparável."""
    lotes = analisar_pagina(PAGINA)
    assert "&eacute;" not in lotes[0]["titulo"]
    assert "Réis" in lotes[0]["titulo"]


def test_id_de_leilao_sai_dos_dois_formatos_de_url():
    html = ('<a href="leilao.asp?Num=61318">a</a>'
            '<a href="abre_catalogo.asp?t=1%7Chttp://x.com.br%7C61562%7C30276974">b</a>')
    assert ids_de_leilao(html) == ["61318", "61562"]
