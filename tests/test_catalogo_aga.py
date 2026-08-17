"""A ingestão do Catálogo AGA e o seu acoplamento ao acervo de leilões.

O texto de teste abaixo é SINTÉTICO, escrito no formato da obra — não há
trecho do catálogo real neste repositório, e não pode haver: é obra protegida
(Lei 9.610/1998) e a cópia de quem a tem é de uso pessoal. O que se testa é a
máquina de leitura, e ela é testável sem reproduzir a obra.
"""

from __future__ import annotations

import sqlite3

import pytest

from ingerir_catalogo_aga import ingerir

# Duas tabelas com cabeçalhos DIFERENTES, que é a armadilha central da obra:
# a primeira cota BC/MBC/SOB, a segunda MBC/SOB/FC.
CATALOGO = """
   CATÁLOGO AGA DE MOEDAS BRASILEIRAS                     1.568 AO PRESENTE   30

                                   Colônia
         D. João V - O Magnânimo (1706-1750)
               Casa da moeda da Bahia (1714-1751)
                           Letra monetária B

                                        3.200 Réis

                                   Ouro – 7,17 g – D 26,0 mm
                     Com letras monetárias B. Quarto tipo de escudo.

Núm.      Data           Quantidades Observações          BC              MBC             SOB
 150      1727       B                                 31.000,00       82.500,00       165.000,00
 151      1729       B - ÚNICA                          RRRRR           RRRRR           RRRRR

ALEXANDRE GUIMARÃES ALVES     *   alexandregalves8@gmail.com    *   LANÇAMENTO - JANEIRO 2020

                                   Reino Unido
         D. João VI - O Clemente (1818-1822)
               Casa da moeda do Rio de Janeiro (1818-1822)
                           Letra monetária R

                                          80 Réis

       ¼ de pataca - Prata – Borda tulipada – 2,24 g – D 20,0 mm – E 0,90 mm

Núm.    Data               Quantidades Observações                MBC          SOB          FC
 633    1818    R - Quant. 5.157                                 600,00      1.200,00    2.200,00

                  Pesos das moedas de prata - Réis
Valor        Datas               Letra Monet.             Peso em g            Teor
80           1695 a   1833       Sem letra, P, R e B      2.24                 .917
960          1810 a   1834       R, B e M                 De 26,8 a 27,1       .896 a .905
2.000        1922                Sem letra                7.90                 .500/.900
"""


@pytest.fixture
def catalogo(tmp_path):
    origem = tmp_path / "aga.txt"
    origem.write_text(CATALOGO, encoding="utf-8")
    banco = tmp_path / "catalogo.db"
    ingerir(origem, banco)
    con = sqlite3.connect(banco)
    con.row_factory = sqlite3.Row
    return con


def _precos(con, numero, metal):
    return {r["grau"]: (r["valor"], r["raridade"]) for r in con.execute(
        """SELECT p.grau, p.valor, p.raridade FROM preco p JOIN moeda m
           ON m.id = p.moeda_id WHERE m.numero = ? AND m.metal = ?""",
        (numero, metal))}


def test_o_cabecalho_de_cada_tabela_manda_no_grau(catalogo):
    """A armadilha central: as colunas mudam no meio da obra. Assumir um
    conjunto fixo desloca TODO preço em um grau — o de FC entra como SOB — e o
    resultado sai com aparência impecável."""
    ouro = _precos(catalogo, 150, "Ouro")
    assert ouro["BC"][0] == 31000.0
    assert ouro["MBC"][0] == 82500.0
    assert ouro["S"][0] == 165000.0       # SOB da obra é S no acervo
    assert "FC" not in ouro               # esta tabela não cota FC

    prata = _precos(catalogo, 633, "Prata")
    assert prata["MBC"][0] == 600.0
    assert prata["S"][0] == 1200.0
    assert prata["FC"][0] == 2200.0
    assert "BC" not in prata              # esta tabela não cota BC


def test_o_numero_aga_nao_e_unico_e_o_metal_faz_parte_da_chave(catalogo):
    """Medido na obra real: 1.139 números aparecem em mais de um verbete,
    porque a numeração reinicia a cada seção de metal. "AGA 633" sem o metal
    não identifica peça nenhuma."""
    colunas = {d[1] for d in catalogo.execute("PRAGMA table_info(moeda)")}
    assert "metal" in colunas
    indice = catalogo.execute(
        "SELECT sql FROM sqlite_master WHERE name='moeda'").fetchone()[0]
    assert "UNIQUE (catalogo, metal, numero" in indice


def test_a_raridade_entra_sem_preco_e_nao_como_zero(catalogo):
    """RRRRR não é preço baixo nem faltante: é a obra dizendo que não arrisca
    cotar. Virar 0,00 faria a peça mais rara parecer a mais barata."""
    unica = _precos(catalogo, 151, "Ouro")
    assert unica["MBC"] == (None, "RRRRR")
    assert all(valor is None for valor, _ in unica.values())


def test_a_denominacao_sai_normalizada_como_o_acervo_a_escreve(catalogo):
    """A obra escreve "3.200 Réis"; a identificação do lote produz "3200 réis".
    Sem a normalização o casamento falha em toda peça acima de mil réis — que
    são justamente as caras."""
    linha = catalogo.execute(
        "SELECT denominacao, denominacao_norm FROM moeda WHERE numero=150").fetchone()
    assert linha["denominacao"] == "3.200 réis"
    assert linha["denominacao_norm"] == "3200 réis"


def test_o_contexto_da_pagina_desce_para_o_verbete(catalogo):
    linha = catalogo.execute(
        "SELECT * FROM moeda WHERE numero=633 AND metal='Prata'").fetchone()
    assert linha["ano"] == 1818
    assert linha["casa_da_moeda"] == "Rio de Janeiro"
    assert linha["letra"] == "R"
    assert linha["peso_g"] == 2.24
    assert linha["diametro_mm"] == 20.0
    assert linha["tiragem"] == 5157
    assert linha["periodo"] == "Reino Unido"


def test_o_rodape_da_pagina_nao_vira_verbete(catalogo):
    assert catalogo.execute(
        "SELECT count(*) FROM moeda WHERE observacoes LIKE '%ALEXANDRE%'"
    ).fetchone()[0] == 0


def test_a_licenca_fica_gravada_no_banco(catalogo):
    licenca = catalogo.execute(
        "SELECT valor FROM fonte WHERE chave='licenca'").fetchone()[0]
    assert "NÃO PUBLICAR" in licenca


# ------------------------------------------------- acoplamento ao acervo

def test_o_acervo_funciona_sem_catalogo(tmp_path, monkeypatch):
    """O catálogo é opcional: quem não o tem usa o acervo igual."""
    import construir_leiloes
    from leiloes.acervo import Acervo

    brutos = tmp_path / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    banco = tmp_path / "dados" / "leiloes.db"
    monkeypatch.setattr(construir_leiloes, "BRUTOS", brutos)
    monkeypatch.setattr(construir_leiloes, "DESTINO", banco)
    monkeypatch.delenv("CATALOGO_DB", raising=False)

    import json
    (brutos / "leilao-1.json").write_text(json.dumps({
        "leilao": {"id": "1", "casa": "Casa", "data_pregao": "2026-05-10",
                   "url": "http://x", "uf": "RJ"},
        "lotes": [{"numero": 1, "titulo": "Moeda 80 Réis 1818 prata S",
                   "situacao": "aberto", "lance_inicial": 100.0}],
        "coletado_em": "2026-08-16T12:00:00+00:00"}, ensure_ascii=False),
        encoding="utf-8")
    construir_leiloes.construir()

    acervo = Acervo(banco)
    assert acervo.catalogo is None
    assert acervo.catalogo_da_peca(1818, "prata", "80 réis") is None


def test_o_catalogo_declara_quando_nao_sabe_qual_verbete(tmp_path, monkeypatch):
    """Mesma denominação, mesmo ano e mesmo metal existem em casas da moeda
    diferentes. Escolher uma calado seria inventar a casa."""
    import json

    import construir_leiloes
    from leiloes.acervo import Acervo

    origem = tmp_path / "aga.txt"
    origem.write_text(CATALOGO.replace(" 151      1729       B - ÚNICA",
                                       " 151      1727       B - outra casa"),
                      encoding="utf-8")
    dados = tmp_path / "dados"
    dados.mkdir()
    ingerir(origem, dados / "catalogo.db")

    brutos = tmp_path / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    monkeypatch.setattr(construir_leiloes, "BRUTOS", brutos)
    monkeypatch.setattr(construir_leiloes, "DESTINO", dados / "leiloes.db")
    monkeypatch.delenv("CATALOGO_DB", raising=False)
    (brutos / "leilao-1.json").write_text(json.dumps({
        "leilao": {"id": "1", "casa": "Casa", "data_pregao": "2026-05-10",
                   "url": "http://x", "uf": "RJ"},
        "lotes": [{"numero": 1, "titulo": "Moeda 3200 Réis 1727 ouro MBC",
                   "situacao": "aberto", "lance_inicial": 100.0}],
        "coletado_em": "2026-08-16T12:00:00+00:00"}, ensure_ascii=False),
        encoding="utf-8")
    construir_leiloes.construir()

    acervo = Acervo(dados / "leiloes.db")
    assert acervo.catalogo is not None
    ref = acervo.catalogo_da_peca(1727, "ouro", "3200 réis")
    assert ref["ambiguo"] is True
    assert len(ref["verbetes"]) == 2
    assert "não escolhe" in ref["como_ler"]
    assert "não entra na margem" in ref["como_ler"]


def test_a_release_recusa_publicar_catalogo_junto(tmp_path):
    """A obra proíbe reprodução, e este script gera arquivo PÚBLICO no GitHub.

    A separação em banco próprio já evita o problema por desenho; esta guarda
    existe para o caso de alguém 'simplificar' juntando os dois bancos numa
    refatoração futura — a partir daí a publicação redistribuiria a obra, e
    nada avisaria.
    """
    import preparar_release_leiloes

    banco = tmp_path / "leiloes.db"
    con = sqlite3.connect(banco)
    con.executescript("CREATE TABLE lote (id INTEGER); "
                      "CREATE TABLE moeda (id INTEGER);")
    con.commit()
    con.close()

    with pytest.raises(SystemExit) as erro:
        preparar_release_leiloes.conferir_que_nao_ha_catalogo(banco)
    assert "obra protegida" in str(erro.value)
    assert "moeda" in str(erro.value)


# ------------------------------------- apêndices de peso e teor

def _teor(con, denominacao):
    return con.execute(
        "SELECT * FROM teor WHERE denominacao_norm = ?", (denominacao,)).fetchone()


def test_o_teor_sai_dos_apendices_de_peso(catalogo):
    """A obra TEM teor — em apêndices próprios, e não na ficha de cada peça.
    Eu havia afirmado que não tinha, procurando no lugar errado."""
    linha = _teor(catalogo, "80 réis")
    assert linha["teor"] == 0.917
    assert linha["peso_g"] == 2.24
    assert linha["metal"] == "Prata"
    assert linha["ano_de"] == 1695 and linha["ano_ate"] == 1833
    assert "apêndice" in linha["fonte"]


def test_faixa_de_teor_e_lida_e_vale_o_menor(catalogo):
    """A regressão que quase custou a peça mais negociada do Império.

    O 960 réis vem com peso e teor em FAIXA — "De 26,8 a 27,1" e ".896 a .905".
    A primeira versão exigia um número só em cada campo e pulou a linha em
    silêncio, deixando justamente a prata imperial mais comum sem teor.
    """
    linha = _teor(catalogo, "960 réis")
    assert linha is not None, "o 960 réis não pode sumir do apêndice"
    assert linha["teor"] == 0.896        # o menor da faixa
    assert linha["peso_g"] == 26.8       # idem
    assert ".896 e .905" in linha["letras"]


def test_o_separador_decimal_do_apendice_e_o_ponto(catalogo):
    """Os dois formatos convivem na obra: preço em "31.000,00" e peso em
    "7.90". Usar o conversor brasileiro nos dois transformava 7,90 g em 790 g —
    cem vezes mais prata do que a moeda tem, num acervo cujo piso é o metal."""
    assert _teor(catalogo, "2000 réis")["peso_g"] == 7.90
    assert _teor(catalogo, "80 réis")["peso_g"] == 2.24


def test_teor_barrado_tambem_e_faixa(catalogo):
    """".500/.900" é faixa escrita com barra, e vale o menor pelo mesmo motivo."""
    assert _teor(catalogo, "2000 réis")["teor"] == 0.500


def test_o_acervo_le_o_teor_do_catalogo_sem_arquivo_nenhum(tmp_path, monkeypatch):
    """Com catálogo ingerido, `teores.json` deixa de ser obrigatório."""
    import json

    import construir_leiloes
    from leiloes.acervo import Acervo

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
    monkeypatch.delenv("TEORES_JSON", raising=False)
    (brutos / "leilao-1.json").write_text(json.dumps({
        "leilao": {"id": "1", "casa": "Casa", "data_pregao": "2026-09-01",
                   "url": "http://x", "uf": "RJ"},
        "lotes": [{"numero": 1, "titulo": "Moeda 960 Réis 1820 prata MBC",
                   "situacao": "aberto", "lance_inicial": 100.0, "lances": 0}],
        "coletado_em": "2026-08-16T12:00:00+00:00"}, ensure_ascii=False),
        encoding="utf-8")
    construir_leiloes.construir()

    acervo = Acervo(dados / "leiloes.db")
    tabela = acervo._teores()
    assert acervo._teor_de(tabela["prata"], "960 réis", 1820)["teor"] == 0.896
    # E fora da faixa de datas, não vale.
    assert acervo._teor_de(tabela["prata"], "960 réis", 1900) is None
