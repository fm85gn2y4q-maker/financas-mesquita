"""Servidor MCP do acervo de leilões de numismática e filatelia.

Fala os dois transportes pelo mesmo motivo que o servidor do acervo financeiro:
o Claude conversa por stdio com um processo local, e o ChatGPT só aceita
servidor remoto por HTTP, com `search` e `fetch` nessa exata assinatura.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .acervo import Acervo, Custos

_LOCAIS = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"]


def seguranca_de_transporte(dominios: list[str] | None) -> TransportSecuritySettings:
    """Política de Host/Origin aceitos. Repetida aqui, e não importada do
    servidor financeiro, para que este pacote se empacote sozinho."""
    hosts = list(_LOCAIS)
    origens = [f"http://{h}" for h in _LOCAIS if "*" not in h]
    for dominio in dominios or []:
        limpo = dominio.strip().removeprefix("https://").removeprefix("http://")
        limpo = limpo.rstrip("/")
        if not limpo:
            continue
        hosts += [limpo, f"{limpo}:*"]
        origens.append(f"https://{limpo}")
    if dominios:
        origens += ["https://chatgpt.com", "https://chat.openai.com"]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=hosts,
        allowed_origins=origens,
    )


INSTRUCOES = """
Acervo de leilões de numismática e filatelia brasileiras, montado a partir do
portal LeilõesBR e das casas que anunciam nele. A referência de preço é o
martelo observado no próprio portal — não há catálogo ingerido, e nenhum preço
aqui vem de outra fonte.

Como responder:
- Entregue a peça, a conta e a ressalva. Não cite nomes de ferramentas nem
  identificadores internos. Apresente links como "[Lote](url)" e ponto.
- Chame `cobertura_do_acervo` quando precisar do alcance da base, e declare os
  limites que afetarem a resposta.

A REGRA QUE NÃO PODE SER QUEBRADA: ISTO LÊ A DESCRIÇÃO, NÃO A PEÇA

Num acervo de jurisprudência o risco é a proveniência; num de legislação, a
vigência; no acervo financeiro, a divergência entre fontes. Aqui é a
**identificação**.

O lote é descrito em texto livre por quem quer vendê-lo. "1000 Réis 1913,
prata, Soberba" parece identificação completa e não é: em 1913 foram cunhadas
duas séries distintas, com faixas de preço próprias. Este acervo se recusa a
identificar peça que a descrição não determine — esses lotes saem em
`lotes_para_ler`, sem margem calculada, e é isso que deve ser dito ao usuário.

**Nunca apresente margem sobre lote que o acervo não identificou.** E nunca
apresente margem nenhuma sem dizer sobre quantos martelos ela se apoia: o campo
`n` vem em toda conta, e mediana de cinco martelos e mediana de sessenta têm a
mesma aparência na tela.

QUATRO ARMADILHAS QUE PRODUZEM RESPOSTA IMPECÁVEL E ERRADA

1. **A margem depende de um número que o usuário tem de fornecer.** A conta usa
   `fracao_revendedor` — quanto o revendedor paga sobre o preço de mercado. O
   padrão é 0,50 e é um chute conservador. Pergunte ao usuário qual é a dele
   antes de apresentar qualquer lista como acionável; mudar 0,50 para 0,30
   costuma zerar a lista inteira.

2. **O martelo não é o custo.** Comissão do leiloeiro (5%, art. 24 do Decreto
   21.981/1932), taxa administrativa da casa, frete e seguro. A conta já soma
   isso em `custo_total_de_arremate` — apresente esse número, não o lance.

3. **Autenticidade não está aqui.** Peça descrita como genuína e que não é
   produz a MELHOR oportunidade da lista, porque o lance está baixo justamente
   por isso. Toda resposta que recomende um lote precisa dizer que ninguém viu
   a peça.

4. **Comparável envelhece.** Metal precioso acompanha a cotação do metal. Leia
   `periodo_dos_comparaveis` antes de usar uma mediana, e diga a data.

O QUE ESTE ACERVO NÃO SABE

Autenticidade, estado real, procedência, e tudo que se negocia fora deste
portal. Busca vazia aqui não é prova de que a peça não exista nem de que não
tenha mercado — chame `pontos_cegos` antes de concluir ausência.
"""


def construir(
    banco: str | Path | None = None,
    dominios: list[str] | None = None,
    **ajustes: Any,
) -> FastMCP:
    acervo = Acervo(banco)

    mcp = FastMCP(
        "leiloes-numismatica",
        instructions=INSTRUCOES,
        transport_security=seguranca_de_transporte(dominios),
        **ajustes,
    )

    def _com_custos(comissao, taxa_administrativa, frete, fracao_revendedor) -> Acervo:
        """Aplica os custos que o usuário passar, mantendo o resto do padrão."""
        mudancas = {k: v for k, v in {
            "comissao": comissao, "taxa_administrativa": taxa_administrativa,
            "frete": frete, "fracao_revendedor": fracao_revendedor,
        }.items() if v is not None}
        if not mudancas:
            return acervo
        return Acervo(acervo.caminho, custos=replace(acervo.custos, **mudancas))

    @mcp.tool()
    def cobertura_do_acervo() -> dict[str, Any]:
        """Alcance da base: quantos leilões, de que casas e de que datas, quantos
        lotes foram identificados, e sobre quantas peças há martelo suficiente
        para comparar."""
        return acervo.cobertura()

    @mcp.tool()
    def pontos_cegos() -> dict[str, Any]:
        """O que se sabe que falta. Chame antes de concluir que uma peça não tem
        mercado — busca vazia não é prova de ausência."""
        return acervo.pontos_cegos()

    @mcp.tool()
    def oportunidades(margem_minima: float = 0.25, n_minimo: int = 5,
                      especie: str | None = None, uf: str | None = None,
                      valor_maximo: float | None = None, limite: int = 25,
                      comissao: float | None = None,
                      taxa_administrativa: float | None = None,
                      frete: float | None = None,
                      fracao_revendedor: float | None = None) -> dict[str, Any]:
        """Lotes ABERTOS cujo lance pedido está abaixo do que a peça arrematou.

        Ordena por margem esperada, já descontados comissão, taxa e frete. Só
        pontua lote identificado cuja peça tenha ao menos `n_minimo` martelos no
        acervo; o que ficou de fora sai contado, não escondido.

        `especie` aceita 'moeda', 'selo' ou 'cédula'. `fracao_revendedor` é o
        que o seu comprador paga sobre o preço de mercado — passe o seu número,
        porque o padrão de 0,50 é chute e move a lista inteira.
        """
        return _com_custos(comissao, taxa_administrativa, frete,
                           fracao_revendedor).oportunidades(
            margem_minima=margem_minima, n_minimo=n_minimo, especie=especie,
            uf=uf, valor_maximo=valor_maximo, limite=limite)

    @mcp.tool()
    def lotes_para_ler(limite: int = 40, so_abertos: bool = True) -> dict[str, Any]:
        """Lotes abertos que o acervo NÃO conseguiu identificar, com o motivo.

        É a consulta mais útil para quem caça peça esquecida: o lote que a
        máquina não classifica é o mesmo que não aparece em filtro nenhum do
        portal, e por isso chega ao pregão com poucos olhos em cima. Nenhum
        deles tem margem calculada — exigem ver a foto."""
        return acervo.lotes_para_ler(limite=limite, so_abertos=so_abertos)

    @mcp.tool()
    def historico_da_peca(termo: str, limite: int = 15) -> dict[str, Any]:
        """O que uma peça vem fazendo de martelo, por estado de conservação.

        Aceita código de catálogo (KM 474, Bentes 123.01, RHM C-9), denominação
        ou parte da chave. A mesma moeda em MBC e em FC sai como duas entradas,
        porque são duas mercadorias."""
        return acervo.historico(termo, limite=limite)

    @mcp.tool()
    def pesquisar_lotes(consulta: str, situacao: str | None = None,
                        limite: int = 30) -> dict[str, Any]:
        """Busca no texto dos lotes. `situacao`: aberto, arrematado,
        nao_arrematado ou retirado."""
        return acervo.pesquisar(consulta, situacao=situacao, limite=limite)

    @mcp.tool()
    def search(query: str) -> list[dict[str, Any]]:
        """Busca ampla no acervo."""
        return [{"id": f"lote:{a['id']}", "title": a["titulo"] or "",
                 "text": f"{a['casa']} · {a['situacao']} · "
                         f"{(a['descricao'] or '')[:400]}",
                 "url": a["url"] or ""}
                for a in acervo.pesquisar(query, limite=20)["achados"]]

    @mcp.tool()
    def fetch(id: str) -> dict[str, Any]:
        """Devolve o registro completo de um resultado da busca."""
        if id.startswith("lote:"):
            linhas = acervo._linhas(
                """SELECT l.*, c.nome casa, a.data_pregao, i.chave, i.confianca,
                          i.estado, x.motivo motivo_indefinicao
                   FROM lote l JOIN leilao a ON a.id = l.leilao_id
                   JOIN casa c ON c.id = a.casa_id
                   LEFT JOIN identificacao i ON i.lote_id = l.id
                   LEFT JOIN identificacao_indefinida x ON x.lote_id = l.id
                   WHERE l.id = ?""", int(id[5:]))
            if linhas:
                lote = linhas[0]
                return {"id": id, "title": lote["titulo"],
                        "text": json.dumps(lote, ensure_ascii=False),
                        "url": lote["url"] or ""}
        return {"id": id, "title": "não encontrado", "text": "", "url": ""}

    return mcp


def main() -> None:  # pragma: no cover - conveniência
    from .__main__ import main as entrada

    raise SystemExit(entrada())


if __name__ == "__main__":
    main()
