"""A publicação do acervo de leilões: OAuth, imagem e Blueprint.

O que se testa aqui não é lógica — é **coerência entre arquivos**. O servidor
lê uma variável de ambiente, o `render.yaml` declara outra e o aviso do log
nomeia uma terceira: cada um está certo isoladamente, e o conjunto não
funciona. É um modo de falhar que não aparece em teste de unidade nenhum e só
se manifesta em produção, na forma de "pede autorização o tempo todo e ninguém
sabe por quê".
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from leiloes.autenticacao import ESCOPO, VARIAVEL_DO_SEGREDO, montar

RAIZ = Path(__file__).resolve().parent.parent


def test_o_aviso_nomeia_a_variavel_que_este_servidor_le(caplog):
    """A cicatriz que este teste existe para não repetir.

    Este módulo é a terceira cópia. Na anterior, o aviso continuou dizendo
    `EMENTARIO_SEGREDO_OAUTH` — nome do acervo de onde ele veio, e variável que
    o servidor nunca leu. Quem seguisse o aviso definiria a coisa errada, o
    alerta continuaria aparecendo, e nada explicaria por quê.
    """
    with caplog.at_level(logging.WARNING, logger="leiloes.autenticacao"):
        montar("https://exemplo.onrender.com", None)

    assert caplog.records, "montar() sem segredo tem de avisar"
    aviso = caplog.records[0].getMessage()
    assert VARIAVEL_DO_SEGREDO in aviso, aviso
    # E a variável tem de ser deste acervo, não herdada de outro.
    assert VARIAVEL_DO_SEGREDO.startswith("LEILOES_"), VARIAVEL_DO_SEGREDO


def test_o_main_le_exatamente_essa_variavel():
    fonte = (RAIZ / "leiloes" / "__main__.py").read_text(encoding="utf-8")
    lidas = set(re.findall(r"os\.environ\.get\(\s*[\"']([A-Z_]+)[\"']", fonte))
    lidas |= {"VARIAVEL_DO_SEGREDO"} if "os.environ.get(VARIAVEL_DO_SEGREDO)" \
        in fonte else set()
    assert "VARIAVEL_DO_SEGREDO" in lidas, (
        "o __main__ tem de ler a constante, e não uma string escrita à mão — "
        "foi a string escrita à mão que deixou a cópia anterior apontando para "
        "a variável errada")


def test_o_escopo_nao_e_o_do_acervo_financeiro():
    """Dois conectores no mesmo cliente, com o mesmo escopo, disputam a mesma
    autorização. Trocar o escopo depois invalida quem já conectou."""
    from financas.autenticacao import ESCOPO as ESCOPO_FINANCEIRO

    assert ESCOPO != ESCOPO_FINANCEIRO
    assert ESCOPO == "leiloes-numismatica"


def test_o_blueprint_declara_as_variaveis_que_o_servidor_le():
    """`render.yaml` e o servidor têm de falar dos mesmos nomes."""
    blueprint = (RAIZ / "render.yaml").read_text(encoding="utf-8")
    for variavel in (VARIAVEL_DO_SEGREDO, "LEILOES_DOMINIOS", "LEILOES_URL_PUBLICA"):
        assert variavel in blueprint, f"{variavel} não está no render.yaml"
    assert "Dockerfile.leiloes" in blueprint


def test_a_imagem_aponta_para_o_banco_que_o_acervo_procura():
    """LEILOES_DB errado sobe o serviço e só falha na primeira consulta."""
    imagem = (RAIZ / "Dockerfile.leiloes").read_text(encoding="utf-8")
    assert "LEILOES_DB=/app/dados/leiloes.db" in imagem
    assert "dados/leiloes.db" in imagem      # o destino do instalar_acervo
    assert 'CMD ["python", "-m", "leiloes", "--http"]' in imagem
    # armadilhas.json tem de viajar na imagem: sem ele o servidor identifica
    # peça que não deveria.
    assert "COPY leiloes/ ./leiloes/" in imagem


def test_a_imagem_nasce_sem_acervo_declarado():
    """Os ARG vazios são de propósito: o build para com mensagem explícita, em
    vez de subir imagem sem acervo que só falha na primeira consulta."""
    imagem = (RAIZ / "Dockerfile.leiloes").read_text(encoding="utf-8")
    assert re.search(r"^ARG ACERVO=\s*$", imagem, re.MULTILINE)
    assert re.search(r"^ARG ACERVO_SHA256=\s*$", imagem, re.MULTILINE)


def test_oauth_so_e_montado_quando_ha_url_publica(tmp_path):
    """O Claude conecta sem OAuth; montá-lo sem URL pública produziria
    metadados apontando para endereços que ninguém alcança."""
    import sqlite3

    import construir_leiloes
    from leiloes.servidor import construir

    banco = tmp_path / "leiloes.db"
    sqlite3.connect(banco).executescript(construir_leiloes.ESQUEMA)

    assert construir(banco).settings.auth is None
    com_oauth = construir(banco, url_publica="https://exemplo.onrender.com",
                          segredo_oauth="segredo-de-teste")
    assert com_oauth.settings.auth is not None
    assert com_oauth.settings.auth.required_scopes == [ESCOPO]


def test_o_resumo_da_release_conta_o_que_ficou_sem_identificacao(tmp_path):
    """O número que diz se o acervo publicado presta não é o total de lotes."""
    import json

    import construir_leiloes
    import preparar_release_leiloes

    brutos = tmp_path / "dados_brutos" / "leiloesbr"
    brutos.mkdir(parents=True)
    banco = tmp_path / "leiloes.db"
    (brutos / "leilao-1.json").write_text(json.dumps({
        "leilao": {"id": "1", "casa": "Casa", "data_pregao": "2026-05-10",
                   "url": "http://x", "uf": "RJ"},
        "lotes": [
            {"numero": 1, "titulo": "Moeda 20 Réis 1869 bronze MBC KM# 474",
             "situacao": "arrematado", "preco_martelo": 900.0,
             "data_resultado": "2026-05-10"},
            {"numero": 2, "titulo": "1000 Réis 1913, prata, Soberba",
             "situacao": "aberto"},
        ],
        "coletado_em": "2026-08-16T12:00:00+00:00",
    }, ensure_ascii=False), encoding="utf-8")

    construir_leiloes.BRUTOS = brutos
    construir_leiloes.DESTINO = banco
    construir_leiloes.construir()

    resumo = preparar_release_leiloes._numeros(banco)
    assert "1 lotes (50%) ficaram sem identificação" in resumo
    assert "2 lotes" in resumo
