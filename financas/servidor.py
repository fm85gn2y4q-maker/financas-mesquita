"""Servidor MCP do acervo financeiro de Mesquita/RJ.

Fala os dois transportes porque os clientes divergem: o Claude conversa por
stdio com um processo local, enquanto o ChatGPT só aceita servidor remoto por
HTTP — e exige as ferramentas `search` e `fetch` com essa exata assinatura.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .acervo import Acervo

_LOCAIS = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"]


def seguranca_de_transporte(dominios: list[str] | None) -> TransportSecuritySettings:
    """Monta a política de Host/Origin aceitos.

    O SDK bloqueia por padrão qualquer Host que não seja local — é proteção
    contra DNS rebinding, e sem ela um site malicioso poderia falar com o
    servidor pelo navegador da vítima. Servir por um endereço público exige
    declarar o domínio aqui; não há curinga, a comparação é exata.
    """
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
Acervo financeiro do Município de Mesquita/RJ, montado a partir de TRÊS fontes
distintas: o SICONFI/Tesouro Nacional (a série oficial que o Município declarou),
o PNCP (o que ele divulgou de licitações e contratos) e a API aberta do Portal da
Transparência da Prefeitura (patrimônio, obras e o mapa do portal).

Como responder ao procurador:
- Entregue o número e a análise, não o funcionamento da ferramenta. Não cite
  nomes de tools, identificadores internos nem estrutura de URL. Apresente links
  como "[Inteiro teor](url)" e ponto.
- Chame `cobertura_do_acervo` quando precisar do alcance da base, e declare os
  limites que afetarem a resposta.

A REGRA QUE NÃO PODE SER QUEBRADA: DE QUE FONTE, E DE QUANDO

Num acervo de jurisprudência o risco é a proveniência; num de legislação, a
vigência; num diário oficial, a republicação. Aqui é a **divergência entre
fontes sobre o mesmo fato**.

O mesmo contrato pode aparecer como extrato no Diário Oficial, como registro no
PNCP, como empenho na tela de despesas e como bem no patrimônio — com valores e
datas que não batem, porque cada fonte tem recorte e data de corte próprios.
Nenhuma delas é "a verdade"; cada uma é uma declaração datada.

Por isso: **nunca apresente um valor sem dizer de qual fonte ele veio e em que
data foi coletado.** Todo resultado traz `coletado_em`. Um número deste acervo
citado sem procedência é um número que ninguém consegue conferir depois.

E quando as fontes divergirem, diga que divergem. Escolher calado a que parece
mais alta ou mais redonda é o erro que este acervo existe para evitar.

TRÊS ARMADILHAS MEDIDAS, QUE PRODUZEM RESPOSTA IMPECÁVEL E ERRADA

1. **A hierarquia do SICONFI só existe na ordem das linhas.** No RREO-Anexo 02,
   "Administração Geral" aparece sete vezes no mesmo anexo e na mesma coluna,
   cada vez sob uma função diferente, com valores de R$ 30 mil a R$ 59,9 milhões.
   Nada no registro diz de quem ela é filha. **Nunca some por nome de conta.**
   Para despesa por função use `despesa_por_funcao`, que só agrega onde o
   vínculo foi provado pela soma, e devolve à parte as linhas em que não fechou.

2. **O patrimônio é fotografia única, não série.** A API do portal ignora o
   parâmetro de ano: pedir 2021 e 2026 devolve arquivos byte a byte idênticos.
   Não existe evolução patrimonial nesta base. Qualquer comparação entre
   exercícios feita com ela é artefato da coleta, não fato do Município.

3. **O PNCP tem pouquíssimo de Mesquita, e isso é achado, não lacuna de
   coleta.** A ausência de um contrato no PNCP não prova que ele não exista —
   prova que não foi divulgado lá. Antes de afirmar descumprimento, confirme os
   números em `cobertura_do_acervo` e considere que a divulgação no PNCP é
   exigida pela Lei 14.133/2021.

4. **Os relatórios do portal não têm nome de coluna.** Medido nos arquivos
   coletados: nenhum traz cabeçalho, a primeira linha é dado, e a largura varia
   dentro do mesmo relatório — a despesa tem 34 colunas em 30.685 linhas e 17
   em dez. **Nunca rotule uma coluna pela posição.** Uma coluna chamada "valor"
   que na verdade é outra coisa sai bem formatada, passa em qualquer conferência
   de contagem e entra numa peça. Cite pelo conteúdo e pela posição — "a 12ª
   coluna traz 33683111000107" —, e prefira o campo `derivados`, que só contém
   o que o formato do próprio texto prova: CNPJ/CPF, data, valor e link.

O QUE ESTE ACERVO TEM, E COMO CHEGOU AQUI

Além do SICONFI, do PNCP e do patrimônio, o acervo traz os relatórios que o
próprio Portal da Transparência exporta na opção "Dados Abertos" — despesa nota
a nota com favorecido e CNPJ, receita, contratos, avisos e editais, dispensas,
diárias, cargos e folha. Use `pesquisar_relatorios` para procurar neles e
`pagamentos_a` para rastrear um favorecido por nome ou documento em todos ao
mesmo tempo.

O QUE ESTE ACERVO NÃO TEM

O Diário Oficial é outro acervo, com servidor próprio. E sete das 37 regras de
relatório do portal não respondem sem parâmetro específico — não foram
coletadas. Não encontrar um pagamento aqui não significa que ele não ocorreu.

Chame `pontos_cegos` antes de concluir que algo não existe.
"""

def construir(
    banco: str | Path | None = None,
    dominios: list[str] | None = None,
    url_publica: str | None = None,
    segredo_oauth: str | None = None,
    **ajustes: Any,
) -> FastMCP:
    acervo = Acervo(banco)

    # O ChatGPT recusa servidor MCP sem OAuth; o Claude conecta sem. O fluxo só
    # é montado quando há URL pública, porque os metadados precisam apontar
    # para endereços que o cliente alcance.
    if url_publica:
        from .autenticacao import montar

        provedor, definicoes = montar(url_publica, segredo_oauth)
        ajustes |= {"auth_server_provider": provedor, "auth": definicoes}

    mcp = FastMCP(
        "financas-mesquita",
        instructions=INSTRUCOES,
        transport_security=seguranca_de_transporte(dominios),
        **ajustes,
    )

    def _obter() -> Acervo:
        return acervo

    @mcp.tool()
    def cobertura_do_acervo() -> dict[str, Any]:
        """Alcance da base: o que há de cada fonte, de que exercícios, e o que
        reconhecidamente não está aqui."""
        return _obter().cobertura()


    @mcp.tool()
    def pontos_cegos() -> dict[str, Any]:
        """O que se sabe que falta ou que não pôde ser resolvido. Chame antes de
        concluir que um dado não existe — busca vazia não é prova de ausência."""
        return _obter().pontos_cegos()


    @mcp.tool()
    def serie_do_tesouro(conta: str | None = None, demonstrativo: str | None = None,
                         anexo: str | None = None, coluna: str | None = None,
                         exercicio: int | None = None, limite: int = 60) -> list[dict[str, Any]]:
        """Linhas do SICONFI (RREO, RGF, DCA) declaradas pelo Município ao Tesouro.

        `demonstrativo` aceita RREO, RGF ou DCA. Cada linha traz `nivel` e `ordem`:
        quando `nivel` for 'indefinido', a linha está numa hierarquia que não fechou
        e não pode ser agregada.
        """
        return _obter().serie(conta=conta, demonstrativo=demonstrativo, anexo=anexo,
                              coluna=coluna, exercicio=exercicio, limite=limite)


    @mcp.tool()
    def despesa_por_funcao(exercicio: int, periodo: int = 6,
                           coluna: str = "DOTAÇÃO ATUALIZADA (a)") -> dict[str, Any]:
        """Despesa por função e subfunção num bimestre do RREO, agregando SÓ onde o
        vínculo função→subfunção foi provado pela conferência da soma. As linhas em
        que não fechou voltam em `nao_vinculadas`, sem serem somadas a nada.

        `coluna` é o estágio da execução e é comparada por igualdade exata —
        "DESPESAS EMPENHADAS ATÉ O BIMESTRE (b)", "DESPESAS LIQUIDADAS ATÉ O
        BIMESTRE (d)", "DOTAÇÃO ATUALIZADA (a)". Errando o nome, a resposta traz
        a lista das que existem naquele período em vez de vir vazia."""
        return _obter().despesa_por_funcao(exercicio, periodo, coluna)


    @mcp.tool()
    def contratacoes_no_pncp(tipo: str | None = None, termo: str | None = None,
                             ano: str | None = None, limite: int = 50) -> list[dict[str, Any]]:
        """Editais, contratos e atas que Mesquita divulgou no PNCP.
        `tipo` aceita edital, contrato, ata ou pca."""
        return _obter().contratacoes(tipo=tipo, termo=termo, ano=ano, limite=limite)


    @mcp.tool()
    def bens_do_patrimonio(termo: str | None = None, fornecedor: str | None = None,
                           unidade: str | None = None, limite: int = 50) -> list[dict[str, Any]]:
        """Bens patrimoniais do Município. Fotografia de uma data só — veja
        `coletado_em`. A plaqueta não identifica o bem sozinha: 1.600 delas se
        repetem no acervo."""
        return _obter().bens(termo=termo, fornecedor=fornecedor, unidade=unidade,
                             limite=limite)


    @mcp.tool()
    def pesquisar_relatorios(consulta: str, regra: str | None = None,
                             exercicio: int | None = None,
                             limite: int = 30) -> dict[str, Any]:
        """Procura no texto dos relatórios que o portal exporta como "Dados
        Abertos" — despesa nota a nota, receita, contratos, editais, dispensas,
        diárias, cargos e folha.

        As linhas voltam SEM nome de coluna, porque o portal não exporta
        cabeçalho: é um vetor posicional. O campo `derivados` traz o que o
        formato do conteúdo prova (CNPJ/CPF, data, valor, link), com a posição
        de onde saiu. `regra` filtra por relatório — veja os nomes em
        `cobertura_do_acervo`."""
        return _obter().pesquisar_relatorios(consulta=consulta, regra=regra,
                                             exercicio=exercicio, limite=limite)

    @mcp.tool()
    def pagamentos_a(quem: str, limite: int = 40) -> dict[str, Any]:
        """Rastreia um favorecido em todos os relatórios do portal ao mesmo
        tempo, por nome ou por CPF/CNPJ. Aceita o documento com ou sem
        pontuação. Responde "a quem se pagou", que o SICONFI não responde."""
        return _obter().pagamentos_a(quem, limite=limite)

    @mcp.tool()
    def conciliar_fornecedor(nome: str) -> dict[str, Any]:
        """Põe lado a lado o que cada fonte diz sobre um mesmo fornecedor ou
        contratado, com a data de coleta de cada uma. Não decide quem está certo:
        mostra onde divergem e onde ainda é preciso procurar."""
        return _obter().conciliar(nome)


    # --- ferramentas exigidas pelo ChatGPT, com esta exata assinatura --------------

    @mcp.tool()
    def search(query: str) -> list[dict[str, Any]]:
        """Busca ampla no acervo."""
        a = _obter()
        achados: list[dict[str, Any]] = []
        for d in a.contratacoes(termo=query, limite=15):
            achados.append({"id": f"pncp:{d['numero_controle_pncp']}",
                            "title": d["titulo"] or "", "text": (d["descricao"] or "")[:600],
                            "url": d["url"]})
        for b in a.bens(termo=query, limite=10):
            achados.append({"id": f"bem:{b['plaqueta']}",
                            "title": (b["item"] or "")[:120],
                            "text": f"{b['unidade']} · {b['fornecedor']} · "
                                    f"R$ {b['valor_atual']} · coletado em {b['coletado_em']}",
                            "url": ""})
        return achados


    @mcp.tool()
    def fetch(id: str) -> dict[str, Any]:
        """Devolve o registro completo de um resultado da busca."""
        a = _obter()
        if id.startswith("pncp:"):
            for d in a.contratacoes(limite=500):
                if d["numero_controle_pncp"] == id[5:]:
                    return {"id": id, "title": d["titulo"], "text": json.dumps(d, ensure_ascii=False),
                            "url": d["url"]}
        if id.startswith("bem:"):
            for b in a.bens(limite=100000):
                if b["plaqueta"] == id[4:]:
                    return {"id": id, "title": b["item"],
                            "text": json.dumps(b, ensure_ascii=False), "url": ""}
        return {"id": id, "title": "não encontrado", "text": "", "url": ""}


    return mcp


def main() -> None:  # pragma: no cover - conveniência
    """Atalho para `python -m financas`. A entrada de verdade é __main__."""
    from .__main__ import main as entrada

    raise SystemExit(entrada())


if __name__ == "__main__":
    main()
