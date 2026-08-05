"""Consultas ao acervo. Toda resposta carrega fonte e data de coleta.

Não é preciosismo: este acervo tem três fontes que falam do mesmo Município com
recortes e datas de corte diferentes, e um número sem procedência não pode ser
conciliado com nada nem levado a uma peça.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "dados" / "acervo.db"


def _reais(valor: float | None) -> str:
    """Formata em padrão brasileiro. Existe para que a troca de separador
    alcance só o número, e nunca o texto em volta dele."""
    if valor is None:
        return "—"
    return f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def _pct(valor: float, casas: int = 1) -> str:
    return f"{valor:.{casas}f}".replace(".", ",") + "%"


class Acervo:
    def __init__(self, caminho: str | Path | None = None) -> None:
        self.caminho = Path(caminho or os.environ.get("ACERVO_DB") or CAMINHO_PADRAO)
        if not self.caminho.exists():
            raise FileNotFoundError(f"acervo não encontrado: {self.caminho}")
        self.con = sqlite3.connect(f"file:{self.caminho}?mode=ro", uri=True,
                                   check_same_thread=False)
        self.con.row_factory = sqlite3.Row

    def _linhas(self, sql: str, *params) -> list[dict[str, Any]]:
        return [dict(r) for r in self.con.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------ alcance

    def cobertura(self) -> dict[str, Any]:
        con = self.con
        sic = con.execute("""SELECT count(*) n, min(exercicio) de, max(exercicio) ate
                             FROM siconfi_linha""").fetchone()
        demonstrativos = self._linhas(
            """SELECT demonstrativo, count(*) linhas, min(exercicio) de,
                      max(exercicio) ate
               FROM siconfi_linha GROUP BY demonstrativo ORDER BY 2 DESC""")
        pncp = self._linhas(
            """SELECT tipo, orgao_nome, count(*) n, min(ano) de, max(ano) ate
               FROM pncp_documento GROUP BY tipo, orgao_nome ORDER BY tipo""")
        pat = con.execute("""SELECT count(*) n, max(coletado_em) em,
                                    sum(valor_atual) valor FROM patrimonio_bem""").fetchone()
        # O somatório do patrimônio não pode sair sozinho. Medido: R$ 32,7 bi,
        # 48× a receita anual do Município, e 1,5% dos bens carregam 96% disso —
        # imóveis e obras de infraestrutura avaliados entre R$ 100 mi e R$ 2,4 bi
        # cada, enquanto a mediana dos bens móveis é R$ 7.239. Não sei dizer se a
        # avaliação está errada ou se é critério contábil do Município; sei que
        # citar o total sem isso produz uma afirmação que não se sustenta.
        grandes = con.execute("""SELECT count(*), coalesce(sum(valor_atual),0)
                                 FROM patrimonio_bem WHERE valor_atual >= 1e8""").fetchone()
        mediana = con.execute("""SELECT valor_atual FROM patrimonio_bem
                                 WHERE valor_atual IS NOT NULL
                                 ORDER BY valor_atual
                                 LIMIT 1 OFFSET (SELECT count(*)/2 FROM patrimonio_bem
                                                 WHERE valor_atual IS NOT NULL)"""
                              ).fetchone()[0]
        return {
            "municipio": "Mesquita/RJ (IBGE 3302858, CNPJ 04132090000125)",
            "siconfi": {"linhas": sic["n"], "exercicios": f"{sic['de']}-{sic['ate']}",
                        "por_demonstrativo": demonstrativos},
            "pncp": {"documentos": pncp},
            "patrimonio": {
                "bens": pat["n"],
                "valor_somado": pat["valor"],
                "mediana_do_valor": mediana,
                "bens_acima_de_100_milhoes": {"quantidade": grandes[0],
                                              "valor_somado": grandes[1]},
                "coletado_em": pat["em"],
                "natureza": "fotografia única, não série histórica",
                # A troca de separador vale SÓ para o número. Aplicá-la à frase
                # inteira — que foi o que eu fiz na primeira versão — inverte
                # toda vírgula e todo ponto do texto, e o aviso chega ao
                # procurador assim: "…centenas de milhões. enquanto a mediana
                # dos bens é R$ 7.239,00, O somatório supera…". Aviso quebrado
                # é aviso que ninguém lê.
                "aviso_sobre_o_total": (
                    f"NÃO cite o valor somado sem esta ressalva: {grandes[0]} bens "
                    f"({_pct(100 * grandes[0] / pat['n'])} do total) respondem por "
                    f"{_pct(100 * grandes[1] / pat['valor'], 0)} do valor — imóveis "
                    f"e obras de infraestrutura avaliados na casa das centenas de "
                    f"milhões, enquanto a mediana dos bens é R$ {_reais(mediana)}. "
                    f"O somatório supera em muitas vezes a receita anual do "
                    f"Município. Pode ser critério de avaliação, pode ser erro de "
                    f"cadastro: este acervo não sabe qual, e não deve escolher."),
            },
            "obras": con.execute("SELECT count(*) FROM obra").fetchone()[0],
            "telas_mapeadas_no_portal": con.execute(
                "SELECT count(*) FROM portal_tela").fetchone()[0],
            "relatorios_do_portal": self.relatorios_disponiveis(),
            "o_que_NAO_esta_aqui": [
                "Diário Oficial: é outro acervo, com servidor próprio.",
                "Sete das 37 regras de relatório do portal não respondem sem "
                "parâmetro específico e ainda não foram coletadas.",
            ],
        }

    def pontos_cegos(self) -> dict[str, Any]:
        """O que se sabe que falta. Sem isso, uma busca vazia parece resposta."""
        con = self.con
        indefinidas = con.execute(
            "SELECT count(*) FROM siconfi_linha WHERE nivel='indefinido'").fetchone()[0]
        anexo02 = con.execute(
            "SELECT count(*) FROM siconfi_linha WHERE anexo='RREO-Anexo 02'").fetchone()[0]
        categorias_sem_dado = self._linhas(
            """SELECT categoria, count(*) telas FROM portal_tela
               WHERE categoria IN ('Despesas','Receitas','Licitações','Contratos',
                                   'Folha','Orçamentos','Convênios','Emenda Parlamentar',
                                   'diariasEpassagens','renuncias')
               GROUP BY categoria ORDER BY 2 DESC""")
        return {
            "siconfi_hierarquia_nao_resolvida": {
                "linhas": indefinidas,
                "de_um_total_no_anexo_02": anexo02,
                "explicacao": "No RREO-Anexo 02 a hierarquia função/subfunção só "
                              "existe na ordem das linhas. Onde a soma das subfunções "
                              "não fechou com a função, o vínculo NÃO foi inventado: "
                              "essas linhas ficam com nivel='indefinido' e não devem "
                              "ser agregadas por função.",
            },
            "pncp_lacuna_de_publicacao": {
                "explicacao": "O Município publicou pouquíssimo no PNCP. Isso é "
                              "achado de conformidade, não falha desta coleta — "
                              "confira em cobertura_do_acervo os números por tipo. "
                              "A ausência de um contrato no PNCP não significa que "
                              "ele não exista: significa que não foi lá divulgado.",
            },
            "relatorios_sem_nome_de_coluna": (
                "Os relatórios do portal vêm SEM CABEÇALHO — medido nos 85 "
                "arquivos coletados, a primeira linha é dado, sempre. E a "
                "largura varia dentro do mesmo relatório: a despesa tem 34 "
                "colunas em 30.685 linhas e 17 em dez. Não há como nomear "
                "coluna por posição sem chutar, e chute aqui produz erro de "
                "atribuição, não lacuna. Use `derivados`, que são provados pelo "
                "formato do conteúdo."),
            "telas_do_portal_fora_do_acervo": categorias_sem_dado,
            "patrimonio": "Fotografia única. Não há série histórica: a API do portal "
                          "ignora o parâmetro de ano e devolve sempre o mesmo conjunto. "
                          "Qualquer comparação entre exercícios feita com ela é falsa.",
        }

    # ------------------------------------------------------------------ SICONFI

    def serie(self, conta: str | None = None, demonstrativo: str | None = None,
              anexo: str | None = None, coluna: str | None = None,
              exercicio: int | None = None, limite: int = 60) -> list[dict[str, Any]]:
        sql = ["SELECT demonstrativo, exercicio, periodo, periodicidade, anexo, rotulo,",
               "       coluna, cod_conta, conta, valor, nivel, funcao_pai, ordem,",
               "       coletado_em FROM siconfi_linha WHERE 1=1"]
        p: list[Any] = []
        if conta:
            sql.append("AND conta LIKE ?"); p.append(f"%{conta}%")
        if demonstrativo:
            sql.append("AND demonstrativo = ?"); p.append(demonstrativo.upper())
        if anexo:
            sql.append("AND anexo LIKE ?"); p.append(f"%{anexo}%")
        if coluna:
            sql.append("AND coluna LIKE ?"); p.append(f"%{coluna}%")
        if exercicio:
            sql.append("AND exercicio = ?"); p.append(exercicio)
        sql.append("ORDER BY exercicio, periodo, anexo, ordem LIMIT ?"); p.append(limite)
        return self._linhas(" ".join(sql), *p)

    def colunas_da_despesa(self, exercicio: int, periodo: int = 6) -> list[str]:
        return [r["coluna"] for r in self._linhas(
            """SELECT DISTINCT coluna FROM siconfi_linha
               WHERE anexo='RREO-Anexo 02' AND exercicio=? AND periodo=?
               ORDER BY coluna""", exercicio, periodo)]

    def despesa_por_funcao(self, exercicio: int, periodo: int = 6,
                           coluna: str = "DOTAÇÃO ATUALIZADA (a)") -> dict[str, Any]:
        """A única consulta que pode agregar por função — e só onde o vínculo
        foi provado pela soma. As linhas 'indefinido' vêm à parte, não somadas.

        `coluna` é comparada por igualdade EXATA, de propósito. Com LIKE, o
        termo "DESPESAS EMPENHADAS" casava ao mesmo tempo "No Bimestre" e "Até
        o Bimestre", e as subfunções de uma coluna eram somadas contra a função
        da outra: a função Legislativa de 2025 fechava em R$ 10,97 milhões
        contra subfunções somando R$ 1,82 milhão. O resultado tinha aparência
        perfeita. Se a coluna pedida não existir, a resposta lista as que há.
        """
        disponiveis = self.colunas_da_despesa(exercicio, periodo)
        if coluna not in disponiveis:
            return {"exercicio": exercicio, "periodo": periodo,
                    "erro": f"coluna {coluna!r} não existe neste período",
                    "colunas_disponiveis": disponiveis}

        # O rótulo separa entregas distintas do mesmo anexo (exceto
        # intra-orçamentárias, intra, total geral). Vincular através dele
        # somaria universos diferentes.
        linhas = self._linhas(
            """SELECT conta, valor, nivel, funcao_pai, rotulo, ordem, coletado_em
               FROM siconfi_linha
               WHERE anexo='RREO-Anexo 02' AND exercicio=? AND periodo=?
                 AND coluna=? ORDER BY rotulo, ordem""",
            exercicio, periodo, coluna)

        blocos: dict[Any, dict[str, Any]] = {}
        for linha in linhas:
            bloco = blocos.setdefault(linha["rotulo"],
                                      {"rotulo": linha["rotulo"], "funcoes": [],
                                       "nao_vinculadas": []})
            if linha["nivel"] == "funcao":
                bloco["funcoes"].append({"funcao": linha["conta"], "valor": linha["valor"],
                                         "coletado_em": linha["coletado_em"],
                                         "subfuncoes": []})
            elif linha["nivel"] == "subfuncao":
                for f in reversed(bloco["funcoes"]):
                    if f["funcao"] == linha["funcao_pai"]:
                        f["subfuncoes"].append({"subfuncao": linha["conta"],
                                                "valor": linha["valor"]})
                        break
            elif linha["nivel"] == "indefinido":
                bloco["nao_vinculadas"].append({"conta": linha["conta"],
                                                "valor": linha["valor"]})

        soltas = sum(len(b["nao_vinculadas"]) for b in blocos.values())
        return {
            "exercicio": exercicio, "periodo": periodo, "coluna": coluna,
            "colunas_disponiveis": disponiveis,
            "blocos": list(blocos.values()),
            "aviso": ("As linhas em 'nao_vinculadas' NÃO entram em nenhuma função: "
                      "a conferência pela soma não fechou e o vínculo não foi "
                      "presumido. Não as agregue sem saber a que função pertencem.")
            if soltas else None,
        }

    # --------------------------------------------------------------------- PNCP

    def contratacoes(self, tipo: str | None = None, termo: str | None = None,
                     ano: str | None = None, limite: int = 50) -> list[dict[str, Any]]:
        sql = ["SELECT tipo, numero_controle_pncp, orgao_nome, ano, titulo, descricao,",
               "       modalidade, situacao, data_publicacao, data_assinatura,",
               "       data_inicio_vigencia, data_fim_vigencia, valor_global, cancelado,",
               "       'https://pncp.gov.br' || item_url url, coletado_em",
               "FROM pncp_documento WHERE 1=1"]
        p: list[Any] = []
        if tipo:
            sql.append("AND tipo = ?"); p.append(tipo)
        if ano:
            sql.append("AND ano = ?"); p.append(str(ano))
        if termo:
            sql.append("AND (titulo LIKE ? OR descricao LIKE ?)")
            p += [f"%{termo}%", f"%{termo}%"]
        sql.append("ORDER BY data_publicacao DESC LIMIT ?"); p.append(limite)
        return self._linhas(" ".join(sql), *p)

    # --------------------------------------------------------------- patrimônio

    def bens(self, termo: str | None = None, fornecedor: str | None = None,
             unidade: str | None = None, limite: int = 50) -> list[dict[str, Any]]:
        sql = ["SELECT plaqueta, item, unidade, centro_custo, localizacao, fornecedor,",
               "       data_posse, valor_atual, situacao, estado_conservacao,",
               "       classificador_descricao, coletado_em",
               "FROM patrimonio_bem WHERE 1=1"]
        p: list[Any] = []
        if termo:
            sql.append("AND item LIKE ?"); p.append(f"%{termo}%")
        if fornecedor:
            sql.append("AND fornecedor LIKE ?"); p.append(f"%{fornecedor}%")
        if unidade:
            sql.append("AND unidade LIKE ?"); p.append(f"%{unidade}%")
        sql.append("ORDER BY valor_atual DESC LIMIT ?"); p.append(limite)
        return self._linhas(" ".join(sql), *p)

    # ------------------------------------------------- relatórios do portal

    def _tem_relatorios(self) -> bool:
        return bool(self.con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='relatorio_linha'").fetchone())

    def relatorios_disponiveis(self) -> list[dict[str, Any]]:
        if not self._tem_relatorios():
            return []
        return self._linhas(
            """SELECT regra, count(*) linhas,
                      count(DISTINCT exercicio) exercicios,
                      min(exercicio) de, max(exercicio) ate,
                      max(coletado_em) coletado_em
               FROM relatorio_linha GROUP BY regra ORDER BY 2 DESC""")

    def pesquisar_relatorios(self, consulta: str, regra: str | None = None,
                             exercicio: int | None = None,
                             limite: int = 30) -> dict[str, Any]:
        """Busca no texto das linhas dos relatórios do portal.

        Devolve a linha como VETOR POSICIONAL, porque o portal não exporta nome
        de coluna, e os campos que o próprio conteúdo prova (CNPJ, data, valor,
        link) à parte, com a posição de onde saíram.
        """
        if not self._tem_relatorios():
            return {"erro": "os relatórios do portal ainda não foram ingeridos"}

        sql = ["""SELECT l.id, l.regra, l.exercicio, l.ordem, l.colunas,
                         l.coletado_em
                  FROM relatorio_fts f JOIN relatorio_linha l ON l.id = f.rowid
                  WHERE relatorio_fts MATCH ?"""]
        p: list[Any] = [consulta]
        if regra:
            sql.append("AND l.regra LIKE ?"); p.append(f"%{regra}%")
        if exercicio:
            sql.append("AND l.exercicio = ?"); p.append(exercicio)
        sql.append("ORDER BY rank LIMIT ?"); p.append(limite)

        achados = []
        for r in self._linhas(" ".join(sql), *p):
            derivados = self._linhas(
                """SELECT campo, valor, posicao FROM relatorio_derivado
                   WHERE linha_id = ? ORDER BY posicao""", r["id"])
            achados.append({
                "regra": r["regra"], "exercicio": r["exercicio"],
                "linha_no_arquivo": r["ordem"],
                "colunas": json.loads(r["colunas"]),
                "derivados": derivados,
                "coletado_em": r["coletado_em"],
            })
        return {
            "consulta": consulta,
            "achados": achados,
            "como_ler": (
                "As colunas vêm SEM NOME: o portal não exporta cabeçalho, e "
                "nomeá-las por posição seria chute. Cite pelo conteúdo e pela "
                "posição ('a 12ª coluna traz 33683111000107'), nunca invente o "
                "rótulo. Os itens em `derivados` são os que o formato do "
                "próprio texto prova — CNPJ/CPF, data, valor e link — e trazem "
                "a posição de onde saíram, para conferência na linha crua."),
        }

    def pagamentos_a(self, quem: str, limite: int = 40) -> dict[str, Any]:
        """Procura um favorecido em TODOS os relatórios, por nome ou documento."""
        if not self._tem_relatorios():
            return {"erro": "os relatórios do portal ainda não foram ingeridos"}

        so_digitos = "".join(c for c in quem if c.isdigit())
        por_documento = []
        if len(so_digitos) in (11, 14):
            por_documento = self._linhas(
                """SELECT l.regra, l.exercicio, l.colunas, l.coletado_em
                   FROM relatorio_derivado d JOIN relatorio_linha l ON l.id = d.linha_id
                   WHERE d.campo = 'cnpj_cpf' AND d.valor = ?
                   ORDER BY l.regra, l.exercicio LIMIT ?""", so_digitos, limite)

        texto = self.pesquisar_relatorios(f'"{quem}"', limite=limite)
        return {
            "procurado": quem,
            "por_documento": [{"regra": r["regra"], "exercicio": r["exercicio"],
                               "colunas": json.loads(r["colunas"]),
                               "coletado_em": r["coletado_em"]}
                              for r in por_documento],
            "por_texto": texto.get("achados", []),
            "como_ler": texto.get("como_ler"),
        }

    # ---------------------------------------------------------------- conciliar

    def conciliar(self, nome: str) -> dict[str, Any]:
        """O que CADA fonte diz sobre um mesmo fornecedor/contratado.

        É a ferramenta central deste acervo. Ela não decide quem está certo —
        põe as versões lado a lado e mostra de que fonte e de que data cada uma
        veio. Divergência aqui é informação, não erro a ser escondido.
        """
        no_pncp = self._linhas(
            """SELECT tipo, numero_controle_pncp, titulo, descricao, valor_global,
                      data_assinatura, situacao, 'https://pncp.gov.br' || item_url url,
                      coletado_em
               FROM pncp_documento WHERE descricao LIKE ? OR titulo LIKE ?
               ORDER BY data_publicacao DESC LIMIT 30""", f"%{nome}%", f"%{nome}%")
        no_patrimonio = self._linhas(
            """SELECT count(*) bens, sum(valor_atual) valor_somado,
                      min(data_posse) primeira_posse, max(data_posse) ultima_posse,
                      max(coletado_em) coletado_em
               FROM patrimonio_bem WHERE fornecedor LIKE ?""", f"%{nome}%")
        return {
            "procurado": nome,
            "pncp": {"encontrados": len(no_pncp), "documentos": no_pncp},
            "patrimonio": no_patrimonio[0] if no_patrimonio else {},
            "onde_mais_procurar": [
                "Diário Oficial do Município (acervo próprio): extratos de contrato, "
                "avisos de licitação e atas de registro de preços — é onde está o "
                "volume que o PNCP não tem.",
                "Portal da Transparência, tela de despesas: empenho, liquidação e "
                "pagamento por favorecido. Não está neste acervo.",
            ],
            "como_ler": "Ausência em uma fonte não é ausência do fato. O PNCP só "
                        "tem o que o Município lá divulgou, e ele divulgou pouco; "
                        "o patrimônio é fotografia de um dia só.",
        }
