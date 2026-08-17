"""Consultas ao acervo de leilões, e o motor de assimetria.

Toda resposta carrega a data de coleta e o número de comparáveis que a
sustenta. Não é preciosismo: uma mediana feita de três martelos e uma feita de
sessenta têm a mesma aparência na tela e valem coisas muito diferentes na hora
de dar lance.

O QUE ESTE ACERVO MEDE, E O QUE ELE NÃO MEDE

Ele mede uma coisa só: a distância entre o lance pedido num lote aberto e o
que peças da MESMA chave — mesma peça, mesmo estado — arremataram neste mesmo
portal. É uma medida de mercado observado, não de valor.

Ele NÃO mede autenticidade, e é bom que isso fique dito antes de qualquer
número: o acervo lê a descrição que o vendedor escreveu. Uma peça descrita
como genuína e que não é produz aqui a melhor oportunidade da lista, porque o
lance está baixo justamente por isso. Nenhuma consulta deste servidor
substitui ver a peça.

AS QUATRO ARMADILHAS DESTE ACERVO

1. **O martelo não é o custo.** Quem arremata paga comissão do leiloeiro (5%,
   art. 24 do Decreto 21.981/1932, para bens móveis) mais a taxa administrativa
   que a casa cobrar, mais frete e seguro. Comparar lance pedido contra martelo
   alheio sem somar isso infla toda margem em dois dígitos. Ver `Custos`.

2. **Estado é produto, não adjetivo.** A mesma moeda em MBC e em FC são
   mercadorias distintas com liquidez distinta. Por isso a chave do comparável
   inclui o estado, e por isso não há conversão entre graus neste acervo: o
   multiplicador de MBC para FC não é constante entre peças, e um multiplicador
   médio faria a nota parecer precisa exatamente onde ela seria chute.

3. **O lote não vendido é informação, não ausência.** Uma peça que não
   arrematou por R$ 800 diz que o mercado não pagou 800 naquele dia. Some-a aos
   martelos e a mediana sobe; ignore-a e o teto desaparece. Aqui ela sai em
   campo próprio, `nao_arrematados`, sem entrar na mediana.

4. **Poucos comparáveis não são comparáveis.** Abaixo de `n_minimo` o acervo
   se recusa a pontuar e diz por quê, em vez de devolver uma mediana de dois
   martelos com cara de estatística.
"""

from __future__ import annotations

import json
import os
import sqlite3
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

CAMINHO_PADRAO = Path(__file__).resolve().parent.parent / "dados" / "leiloes.db"


@dataclass(frozen=True)
class Custos:
    """O que separa o martelo do dinheiro que sai e do que entra.

    Os padrões são conservadores e configuráveis. Confira-os contra o edital da
    casa antes de dar lance: a taxa administrativa varia entre casas e não está
    em lei nenhuma, e há casa que cobra por lote e não por percentual.
    """
    # Comissão do leiloeiro sobre bens móveis: 5%, art. 24 do Decreto
    # 21.981/1932. É piso legal, e o edital pode declarar mais.
    comissao: float = 0.05
    # Taxa administrativa da casa. Não é lei; 5% é o que se pratica com mais
    # frequência no portal. CONFIRA NO EDITAL.
    taxa_administrativa: float = 0.05
    # Frete e seguro por lote, em reais. Peça pequena e leve; ajuste.
    frete: float = 45.0
    # O que o revendedor paga sobre o preço que a peça faz em leilão. É a
    # variável mais sensível de todas e a única que ninguém publica — meça a
    # sua contra os negócios que você de fato fizer, e não confie no padrão.
    fracao_revendedor: float = 0.50

    def custo_de_arremate(self, lance: float) -> float:
        return lance * (1 + self.comissao + self.taxa_administrativa) + self.frete

    def receita_de_revenda(self, preco_de_mercado: float) -> float:
        return preco_de_mercado * self.fracao_revendedor


def _mediana(valores: list[float]) -> float:
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return ordenados[meio]
    return (ordenados[meio - 1] + ordenados[meio]) / 2


def _mad(valores: list[float], mediana: float) -> float:
    """Desvio absoluto mediano. Preço de leilão tem cauda pesada — um martelo
    fora da curva desloca a média e não desloca isto."""
    return _mediana([abs(v - mediana) for v in valores]) if valores else 0.0


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn").lower()


def _distancia(a: str, b: str, limite: int) -> int:
    """Distância de edição (Levenshtein), com saída antecipada.

    Para de contar assim que a linha inteira passa do limite: a comparação roda
    contra todo o vocabulário corrente do acervo, e sem o corte a varredura de
    um catálogo grande fica quadrática à toa.
    """
    if abs(len(a) - len(b)) > limite:
        return limite + 1
    anterior = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        atual = [i]
        for j, cb in enumerate(b, start=1):
            atual.append(min(anterior[j] + 1, atual[j - 1] + 1,
                             anterior[j - 1] + (ca != cb)))
        if min(atual) > limite:
            return limite + 1
        anterior = atual
    return anterior[-1]


class Acervo:
    def __init__(self, caminho: str | Path | None = None,
                 custos: Custos | None = None) -> None:
        self.caminho = Path(caminho or os.environ.get("LEILOES_DB") or CAMINHO_PADRAO)
        if not self.caminho.exists():
            raise FileNotFoundError(f"acervo de leilões não encontrado: {self.caminho}")
        self.con = sqlite3.connect(f"file:{self.caminho}?mode=ro", uri=True,
                                   check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.custos = custos or Custos()
        self._frequentes: list[str] | None = None

        # O catálogo é OPCIONAL e mora em banco próprio, que não se publica —
        # é obra protegida, e a cópia é de uso pessoal de quem a tem. Sem ele o
        # acervo funciona igual; com ele ganha duas coisas que o martelo não dá:
        # raridade declarada e tiragem.
        catalogo = Path(os.environ.get("CATALOGO_DB")
                        or self.caminho.parent / "catalogo.db")
        self.catalogo: sqlite3.Connection | None = None
        if catalogo.exists():
            self.catalogo = sqlite3.connect(f"file:{catalogo}?mode=ro", uri=True,
                                            check_same_thread=False)
            self.catalogo.row_factory = sqlite3.Row

    def _linhas(self, sql: str, *params) -> list[dict[str, Any]]:
        return [dict(r) for r in self.con.execute(sql, params).fetchall()]

    # ------------------------------------------------------------------ alcance

    def cobertura(self) -> dict[str, Any]:
        con = self.con
        leiloes = con.execute(
            """SELECT count(*) n, min(data_pregao) de, max(data_pregao) ate,
                      max(coletado_em) coletado_em FROM leilao""").fetchone()
        lotes = con.execute("SELECT count(*) FROM lote").fetchone()[0]
        por_situacao = self._linhas(
            "SELECT situacao, count(*) n FROM lote GROUP BY situacao ORDER BY 2 DESC")
        por_confianca = self._linhas(
            "SELECT confianca, count(*) n FROM identificacao GROUP BY confianca")
        indefinidos = con.execute(
            "SELECT count(*) FROM identificacao_indefinida").fetchone()[0]
        casas = self._linhas(
            """SELECT c.nome, c.uf, count(DISTINCT l.id) leiloes,
                      count(t.id) lotes, max(l.data_pregao) ultimo_pregao
               FROM casa c JOIN leilao l ON l.casa_id = c.id
               LEFT JOIN lote t ON t.leilao_id = l.id
               GROUP BY c.id ORDER BY 4 DESC""")
        chaves = con.execute(
            """SELECT count(DISTINCT i.chave) FROM identificacao i JOIN lote l
               ON l.id = i.lote_id WHERE l.preco_martelo IS NOT NULL""").fetchone()[0]
        densas = con.execute(
            """SELECT count(*) FROM (SELECT i.chave FROM identificacao i
               JOIN lote l ON l.id = i.lote_id WHERE l.preco_martelo IS NOT NULL
               GROUP BY i.chave HAVING count(*) >= 5)""").fetchone()[0]

        return {
            "portal": "LeilõesBR (leiloesbr.com.br) e as casas que anunciam nele",
            "leiloes": {"quantidade": leiloes["n"],
                        "pregoes_de": leiloes["de"], "ate": leiloes["ate"],
                        "coletado_em": leiloes["coletado_em"]},
            "lotes": {"total": lotes, "por_situacao": por_situacao},
            "identificacao": {"por_confianca": por_confianca,
                              "indefinidos": indefinidos},
            "casas": casas,
            "base_de_comparacao": {
                "chaves_com_martelo": chaves,
                "chaves_com_5_ou_mais": densas,
                "aviso": (
                    f"Só as {densas} chaves com cinco martelos ou mais recebem "
                    f"nota de assimetria. As outras {chaves - densas} aparecem "
                    f"nas consultas, mas sem margem calculada — duas ou três "
                    f"vendas não formam distribuição, e uma mediana feita delas "
                    f"tem a mesma aparência de uma feita de sessenta."),
            },
            "o_que_NAO_esta_aqui": [
                "Autenticidade. O acervo lê a descrição do vendedor e não vê a peça.",
                "Preço de catálogo. Nenhum catálogo foi ingerido: a referência "
                "deste acervo é martelo observado neste portal, e só.",
                "Leilões de outras plataformas (iArremate, Superbid, Bidfy) e as "
                "vendas de balcão das próprias casas.",
                "O que foi vendido antes da primeira coleta desta máquina.",
            ],
        }

    def pontos_cegos(self) -> dict[str, Any]:
        con = self.con
        total = con.execute("SELECT count(*) FROM lote").fetchone()[0] or 1
        indefinidos = con.execute(
            "SELECT count(*) FROM identificacao_indefinida").fetchone()[0]
        motivos = self._linhas(
            """SELECT motivo, count(*) n FROM identificacao_indefinida
               GROUP BY motivo ORDER BY 2 DESC LIMIT 12""")
        sem_martelo = con.execute(
            """SELECT count(*) FROM lote WHERE situacao='arrematado'
               AND preco_martelo IS NULL""").fetchone()[0]
        return {
            "lotes_nao_identificados": {
                "quantidade": indefinidos,
                "do_total": f"{100 * indefinidos / total:.0f}%",
                "motivos": motivos,
                "explicacao": (
                    "Estes lotes NÃO foram descartados: eles estão no acervo e "
                    "aparecem na busca. O que não têm é chave de comparação, "
                    "porque a descrição não determina qual peça é. São a fila "
                    "de leitura humana — e, por serem invisíveis a quem filtra "
                    "por catálogo, é entre eles que costuma estar o lote "
                    "esquecido. Use `lotes_para_ler`."),
            },
            "arrematados_sem_preco": {
                "quantidade": sem_martelo,
                "explicacao": ("Lotes marcados como arrematados cujo martelo o "
                               "portal não publicou, ou que a coleta pegou antes "
                               "da publicação. Não entram em comparável nenhum."),
            },
            "vies_de_sobrevivencia": (
                "O acervo só conhece o que passou por leilão neste portal. Peça "
                "que o mercado negocia fora dele — entre colecionadores, em loja, "
                "em feira — não está aqui, e para essas a mediana daqui pode "
                "estar sistematicamente baixa."),
            "janela_curta": (
                "Comparável de leilão envelhece. Metal precioso acompanha a "
                "cotação do metal, e uma mediana montada com martelos de dois "
                "anos atrás não descreve o pregão de hoje. Toda consulta devolve "
                "`periodo_dos_comparaveis` — leia antes de usar a mediana."),
        }

    # ------------------------------------------------------------ obscuridade

    def _tokens_frequentes(self) -> list[str]:
        if self._frequentes is None:
            self._frequentes = [r["token"] for r in self._linhas(
                "SELECT token FROM vocabulario WHERE ocorrencias >= 20")]
        return self._frequentes

    def _grafia_divergente(self, titulo: str) -> list[dict[str, str]]:
        """Termos do título que quase casam com um termo corrente do catálogo.

        É a assimetria mais barata que existe num leilão e não tem nada de
        sofisticado: o lote escrito "bronse" ou "Cruzeriro" não aparece na busca
        de ninguém. Quem filtra por texto passa direto, o lote chega ao pregão
        com meia dúzia de olhos em cima, e o lance fica onde começou.

        A régua é distância de edição, e não semelhança de sequência. A primeira
        versão usava `difflib` com corte em 0,86 e não disparava nunca: a troca
        de UMA letra em palavra de seis — "bronse" por "bronze" — dá 0,833 de
        semelhança e ficava abaixo do corte. Ou seja, o filtro rejeitava
        exatamente a classe de erro que ele existe para achar, e em silêncio.
        Baixar o corte resolveria pelo lado errado, deixando entrar par
        distante; a distância de edição diz o que se quer dizer de verdade —
        "isto é o mesmo termo com um erro de digitação".
        """
        frequentes = self._tokens_frequentes()
        if not frequentes:
            return []
        raros = {r["token"] for r in self._linhas(
            "SELECT token FROM vocabulario WHERE ocorrencias <= 2")}

        achados = []
        for bruto in set(_sem_acento(titulo).replace("-", " ").split()):
            token = "".join(c for c in bruto if c.isalnum())
            if len(token) < 5 or token not in raros:
                continue
            # Palavra longa tolera dois erros; curta, só um. Dois erros em seis
            # letras já não é typo — é outra palavra.
            limite = 2 if len(token) >= 8 else 1
            melhor = min(
                (t for t in frequentes if abs(len(t) - len(token)) <= limite),
                key=lambda t: _distancia(token, t, limite), default=None)
            if melhor and melhor != token \
                    and _distancia(token, melhor, limite) <= limite:
                achados.append({"escrito": token, "corrente_no_catalogo": melhor})
        return achados

    def _sinais(self, lote: dict[str, Any], tem_codigo: bool,
                total_lotes: int | None) -> list[str]:
        """Por que ESTE lote pode ter ficado esquecido.

        Não vira nota, e não entra na conta da margem. É o outro lado da
        pergunta: a margem diz quanto se ganha se der certo, isto diz por que
        a oportunidade estaria de pé às vésperas do pregão em vez de já ter
        sido tomada. Misturar os dois num número só daria a um palpite sobre
        visibilidade a mesma aparência que um martelo observado tem.
        """
        sinais = []
        if lote.get("situacao") == "pos_pregao":
            sinais.append("não arrematou no pregão e está em venda pós-pregão — "
                          "o vendedor já viu o mercado recusar o preço dele uma "
                          "vez, e o lote não disputa com ninguém agora")
        if len(lote.get("descricao") or "") < 80:
            sinais.append("descrição curta — o lote diz pouco sobre a própria peça")
        if not tem_codigo:
            sinais.append("sem código de catálogo no texto — não aparece para quem "
                          "busca por Bentes/KM/RHM")
        if not lote.get("foto_url"):
            sinais.append("sem foto")
        if total_lotes and lote.get("numero") and lote["numero"] > 0.75 * total_lotes:
            sinais.append(f"lote {lote['numero']} de {total_lotes} — último quarto do "
                          f"pregão, onde a disputa costuma afrouxar")
        for erro in self._grafia_divergente(lote.get("titulo") or ""):
            sinais.append(f"grafia divergente: escreveram {erro['escrito']!r} onde o "
                          f"catálogo usa {erro['corrente_no_catalogo']!r} — a busca "
                          f"por texto não alcança este lote")
        return sinais

    # ----------------------------------------------------------------- catálogo

    def catalogo_da_peca(self, ano: int | None, metal: str | None,
                         denominacao: str | None) -> dict[str, Any] | None:
        """O que o catálogo diz desta peça — se houver catálogo ingerido.

        Devolve TODOS os verbetes que casam, e não o primeiro: a mesma
        denominação no mesmo ano existe em casas da moeda diferentes, com
        preços diferentes. Escolher um calado seria inventar a casa.

        O preço daqui é **de catálogo**, e não entra na conta da margem. São
        três preços diferentes na vida real — catálogo, varejo e liquidação
        rápida —, e eles divergem muito em peça rara. O que o catálogo dá e o
        martelo não dá é raridade declarada e tiragem.
        """
        if not (self.catalogo and ano and metal and denominacao):
            return None

        verbetes = [dict(r) for r in self.catalogo.execute(
            """SELECT id, numero, denominacao, metal, peso_g, diametro_mm,
                      casa_da_moeda, letra, tiragem, periodo, observacoes
               FROM moeda
               WHERE ano = ? AND lower(metal) = lower(?)
                 AND denominacao_norm = lower(?)
               ORDER BY numero""", (ano, metal, denominacao))]
        if not verbetes:
            return None

        for v in verbetes:
            v["precos"] = [dict(r) for r in self.catalogo.execute(
                "SELECT grau, valor, raridade FROM preco WHERE moeda_id = ?",
                (v.pop("id"),))]

        raridades = {p["raridade"] for v in verbetes for p in v["precos"]
                     if p["raridade"]}
        tiragens = [v["tiragem"] for v in verbetes if v["tiragem"]]
        return {
            "catalogo": "AGA — Catálogo de Moedas Brasileiras (jan/2020)",
            "verbetes": verbetes,
            "raridade_declarada": sorted(raridades) or None,
            "menor_tiragem": min(tiragens) if tiragens else None,
            "ambiguo": len(verbetes) > 1,
            "como_ler": (
                "Preço DE CATÁLOGO, e **da edição de janeiro de 2020** — leia a "
                "idade antes do número. São mais de seis anos de inflação em "
                "reais, e nas peças de ouro e prata há ainda a variação da "
                "cotação do metal, que move o piso da moeda independentemente "
                "do mercado numismático. Não é preço de varejo nem de "
                "liquidação rápida, e não entra na margem calculada por este "
                "acervo, que usa martelo observado — o martelo, esse, é "
                "recente. Do catálogo valem sobretudo as duas coisas que NÃO "
                "envelhecem: raridade declarada e tiragem. "
                + ("Há mais de um verbete para esta combinação (casas da moeda "
                   "ou variantes distintas) — o acervo não escolhe entre eles."
                   if len(verbetes) > 1 else "")),
        }

    # -------------------------------------------------------------- comparáveis

    def comparaveis(self, chave: str) -> dict[str, Any]:
        """O que peças desta MESMA chave fizeram de martelo neste portal."""
        vendidos = self._linhas(
            """SELECT l.preco_martelo preco, l.data_resultado data, l.titulo,
                      l.url, c.nome casa, l.coletado_em
               FROM identificacao i JOIN lote l ON l.id = i.lote_id
               JOIN leilao a ON a.id = l.leilao_id JOIN casa c ON c.id = a.casa_id
               WHERE i.chave = ? AND l.situacao='arrematado'
                 AND l.preco_martelo IS NOT NULL
               ORDER BY l.data_resultado DESC""", chave)
        nao_vendidos = self._linhas(
            """SELECT l.lance_inicial pedido, l.data_resultado data, l.url
               FROM identificacao i JOIN lote l ON l.id = i.lote_id
               WHERE i.chave = ? AND l.situacao='nao_arrematado'
               ORDER BY l.data_resultado DESC LIMIT 20""", chave)

        precos = [v["preco"] for v in vendidos]
        if not precos:
            return {"chave": chave, "n": 0, "vendidos": [],
                    "nao_arrematados": nao_vendidos,
                    "aviso": "nenhum martelo para esta chave no acervo"}

        mediana = _mediana(precos)
        mad = _mad(precos, mediana)
        datas = [v["data"] for v in vendidos if v["data"]]
        return {
            "chave": chave,
            "n": len(precos),
            "mediana": mediana,
            "desvio_absoluto_mediano": mad,
            "dispersao_relativa": round(mad / mediana, 3) if mediana else None,
            "minimo": min(precos), "maximo": max(precos),
            "periodo_dos_comparaveis": {"de": min(datas) if datas else None,
                                        "ate": max(datas) if datas else None},
            "vendidos": vendidos[:20],
            "nao_arrematados": nao_vendidos,
            "como_ler": (
                "A mediana resiste ao martelo fora da curva; a média não. "
                "`dispersao_relativa` acima de 0,35 quer dizer que os martelos "
                "desta chave estão espalhados demais para servirem de "
                "referência — provavelmente há dentro dela mais de uma peça, ou "
                "estados que a descrição não separou. Os `nao_arrematados` NÃO "
                "entram na mediana, e são teto observado: alguém pediu aquilo e "
                "o mercado não pagou."),
        }

    # -------------------------------------------------------- valor do metal

    def _teores(self) -> dict[str, dict[str, dict[str, Any]]]:
        """Teor por metal e denominação, de duas origens que se somam.

        A primeira é o catálogo ingerido, que traz os apêndices "Pesos das
        moedas" — 77 linhas na edição AGA de 2020. A segunda é `teores.json`,
        para o que o catálogo não cobrir e vier de outra fonte sua.

        `teores.json` prevalece quando as duas trazem a mesma chave: quem
        preencheu à mão o fez sabendo o que o catálogo diz, e teve motivo.
        """
        tabelas: dict[str, dict[str, dict[str, Any]]] = {}

        if self.catalogo is not None:
            tem = self.catalogo.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' "
                "AND name='teor'").fetchone()
            if tem:
                for r in self.catalogo.execute(
                        "SELECT metal, denominacao_norm, ano_de, ano_ate, teor, "
                        "fonte FROM teor"):
                    chave = (f"{r['denominacao_norm']}|{r['ano_de']}-{r['ano_ate']}"
                             if r["ano_de"] else r["denominacao_norm"])
                    tabelas.setdefault(r["metal"].lower(), {})[chave] = {
                        "teor": r["teor"], "fonte": r["fonte"]}

        caminho = Path(os.environ.get("TEORES_JSON")
                       or Path(__file__).resolve().parent / "teores.json")
        if caminho.exists():
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            for metal, tabela in dados.items():
                if metal.startswith("_"):
                    continue
                # Entrada sem fonte declarada NÃO conta. É o que impede um
                # número posto "só para testar" de virar decisão de compra.
                tabelas.setdefault(metal, {}).update(
                    {chave: v for chave, v in tabela.items()
                     if not chave.startswith("_") and v.get("fonte")
                     and v.get("teor")})
        return tabelas

    def _teor_de(self, tabela: dict[str, dict[str, Any]], denominacao: str,
                 ano: int | None) -> dict[str, Any] | None:
        """Casa 'denominação|ano_inicial-ano_final' e, na falta, 'denominação'."""
        for chave, valor in tabela.items():
            if "|" not in chave:
                continue
            nome, faixa = chave.split("|", 1)
            if nome.strip().lower() != denominacao.lower():
                continue
            try:
                de, ate = (int(x) for x in faixa.split("-"))
            except ValueError:
                continue
            if ano and de <= ano <= ate:
                return valor
        return tabela.get(denominacao.lower()) or tabela.get(denominacao)

    def abaixo_do_metal(self, spot_por_grama: dict[str, float],
                        metal: str = "prata", periodo: str | None = None,
                        sem_lance: bool = True, limite: int = 30) -> dict[str, Any]:
        """Lotes cujo custo de arremate fica ABAIXO do metal que a peça contém.

        É a peneira mais dura que este acervo tem, e a única cujo piso não
        depende do gosto de ninguém: abaixo do valor do metal, a peça vale mais
        derretida do que como moeda, e o mercado numismático inteiro pode estar
        errado sem que isso mude a conta.

        Três coisas de que ela depende, e nenhuma o acervo inventa:

        `spot_por_grama`  o preço do metal, EM REAIS POR GRAMA, passado por
                          quem chama. O acervo não cota metal e não vai buscar
                          cotação: ela muda todo dia e um número velho aqui
                          produziria lista errada com cara de atual.
        peso              vem do catálogo ingerido. Sem catálogo, não há conta.
        teor              vem de `teores.json`, e o catálogo AGA **não o
                          declara**. Peça sem teor declarado NÃO entra na lista:
                          sai contada em `sem_teor_declarado`, para você
                          preencher. Peso bruto não é prata fina, e a diferença
                          de liga é maior que a margem que esta peneira procura.
        """
        if metal not in spot_por_grama or spot_por_grama[metal] <= 0:
            return {"erro": f"informe o preço do {metal} em reais por grama, "
                            f"em `spot_por_grama`",
                    "exemplo": {"prata": 6.20, "ouro": 480.00}}
        if self.catalogo is None:
            return {"erro": "esta peneira precisa do peso da peça, que vem do "
                            "catálogo — e nenhum catálogo foi ingerido nesta "
                            "máquina. Veja `ingerir_catalogo_aga.py`."}

        faixas = {"colonia": (1500, 1807), "reino unido": (1808, 1821),
                  "imperio": (1822, 1889), "republica": (1890, 2030)}
        faixa = faixas.get((periodo or "").strip().lower().replace("é", "e")
                           .replace("ô", "o")) if periodo else None
        if periodo and not faixa:
            return {"erro": f"período {periodo!r} desconhecido",
                    "periodos": list(faixas)}

        tabela = self._teores().get(metal, {})
        candidatos = self._linhas(
            f"""SELECT l.id, l.numero, l.titulo, l.url, l.lance_inicial,
                       l.situacao, l.lances, l.coletado_em, a.data_pregao,
                       c.nome casa, c.uf, i.ano, i.denominacao, i.estado, i.chave
                FROM lote l
                JOIN identificacao i ON i.lote_id = l.id
                JOIN leilao a ON a.id = l.leilao_id
                JOIN casa c ON c.id = a.casa_id
                WHERE l.situacao IN ('aberto','pos_pregao')
                  AND l.lance_inicial IS NOT NULL
                  AND lower(i.metal) = lower(?)
                  AND i.denominacao IS NOT NULL AND i.ano IS NOT NULL
                  {'AND i.ano BETWEEN ? AND ?' if faixa else ''}
                  {'AND l.lances = 0' if sem_lance else ''}""",
            *([metal] + (list(faixa) if faixa else [])))

        achados, sem_teor, sem_peso = [], {}, 0
        for lote in candidatos:
            referencia = self.catalogo_da_peca(lote["ano"], metal,
                                               lote["denominacao"])
            pesos = [v["peso_g"] for v in (referencia or {}).get("verbetes", [])
                     if v.get("peso_g")]
            if not pesos:
                sem_peso += 1
                continue
            # O MENOR peso entre os verbetes que casam. Conservador de
            # propósito: menos metal é menos valor intrínseco, e portanto menos
            # peça entrando na lista por engano. Nesta peneira, o erro de deixar
            # passar custa uma oportunidade; o de incluir custa dinheiro.
            peso = min(pesos)

            teor = self._teor_de(tabela, lote["denominacao"], lote["ano"])
            if not teor:
                chave = f"{lote['denominacao']} ({lote['ano']})"
                sem_teor[chave] = sem_teor.get(chave, 0) + 1
                continue

            valor_metal = peso * teor["teor"] * spot_por_grama[metal]
            custo = self.custos.custo_de_arremate(lote["lance_inicial"])
            if custo >= valor_metal:
                continue

            achados.append({
                "lote": {"titulo": lote["titulo"], "url": lote["url"],
                         "situacao": lote["situacao"], "lances": lote["lances"]},
                "leilao": {"casa": lote["casa"], "uf": lote["uf"],
                           "data_pregao": lote["data_pregao"]},
                "peca": {"ano": lote["ano"], "denominacao": lote["denominacao"],
                         "estado": lote["estado"], "peso_g": peso,
                         "teor": teor["teor"], "fonte_do_teor": teor["fonte"]},
                "dinheiro": {
                    "lance_pedido": lote["lance_inicial"],
                    "custo_total_de_arremate": round(custo, 2),
                    "metal_fino_g": round(peso * teor["teor"], 3),
                    "valor_do_metal": round(valor_metal, 2),
                    "desconto_sobre_o_metal": round(1 - custo / valor_metal, 3),
                },
                "coletado_em": lote["coletado_em"],
            })

        achados.sort(key=lambda a: a["dinheiro"]["desconto_sobre_o_metal"],
                     reverse=True)
        return {
            "parametros": {"metal": metal, "periodo": periodo,
                           "spot_por_grama": spot_por_grama[metal],
                           "so_sem_lance": sem_lance,
                           "custos": asdict(self.custos)},
            "achados": achados[:limite],
            "candidatos_examinados": len(candidatos),
            "sem_peso_no_catalogo": sem_peso,
            "sem_teor_declarado": sem_teor,
            "como_ler": (
                "O valor do metal é piso, não preço: peça numismática quase "
                "sempre vale mais que a prata dela, e quando não vale, o achado "
                "costuma ser que a peça está mal descrita, danificada ou não é "
                "o que diz ser. Confirme antes de dar lance. "
                + (f"{len(sem_teor)} combinações de denominação e ano ficaram "
                   f"FORA da conta por não haver teor declarado em "
                   f"`teores.json` — estão listadas em `sem_teor_declarado`, e "
                   f"enquanto não forem preenchidas esta lista está incompleta "
                   f"na exata medida delas. " if sem_teor else "")
                + ("A peneira usou só lotes com contagem de lances igual a "
                   "zero; lote cuja contagem o portal não publicou ficou de "
                   "fora, porque desconhecido não é zero." if sem_lance else "")),
        }

    # ------------------------------------------------------------ oportunidades

    def oportunidades(self, margem_minima: float = 0.25, n_minimo: int = 5,
                      especie: str | None = None, uf: str | None = None,
                      valor_maximo: float | None = None,
                      limite: int = 25) -> dict[str, Any]:
        """Lotes ABERTOS cujo lance pedido está abaixo do que a peça faz.

        Ordena por margem esperada. Não pontua lote sem identificação nem chave
        com menos de `n_minimo` martelos — esses saem à parte, contados, para
        que a lista curta não passe por mercado sem oportunidade.
        """
        # `pos_pregao` entra junto com `aberto`, e não é detalhe: são os lotes
        # que não arremataram e ficaram à venda depois. Deixá-los de fora
        # excluiria da busca por peça esquecida justamente as peças que o
        # mercado já esqueceu uma vez.
        abertos = self._linhas(
            f"""SELECT l.id, l.numero, l.titulo, l.descricao, l.url, l.foto_url,
                       l.lance_inicial, l.coletado_em, l.situacao, a.total_lotes,
                       a.data_pregao, a.titulo leilao, c.nome casa, c.uf,
                       i.chave, i.confianca, i.especie, i.catalogo, i.codigo,
                       i.estado, i.ressalva, i.ano, i.metal, i.denominacao
                FROM lote l
                JOIN identificacao i ON i.lote_id = l.id
                JOIN leilao a ON a.id = l.leilao_id
                JOIN casa c ON c.id = a.casa_id
                WHERE l.situacao IN ('aberto','pos_pregao')
                  AND l.lance_inicial IS NOT NULL
                  {'AND i.especie = ?' if especie else ''}
                  {'AND c.uf = ?' if uf else ''}
                  {'AND l.lance_inicial <= ?' if valor_maximo is not None else ''}
            """, *[p for p in (especie, uf, valor_maximo) if p is not None])

        achados: list[dict[str, Any]] = []
        sem_base = 0
        cache: dict[str, dict[str, Any]] = {}

        for lote in abertos:
            base = cache.get(lote["chave"]) or self.comparaveis(lote["chave"])
            cache[lote["chave"]] = base
            if base["n"] < n_minimo:
                sem_base += 1
                continue

            custo = self.custos.custo_de_arremate(lote["lance_inicial"])
            receita = self.custos.receita_de_revenda(base["mediana"])
            margem = receita - custo
            if custo <= 0 or margem / custo < margem_minima:
                continue

            achados.append({
                "lote": {"titulo": lote["titulo"], "numero": lote["numero"],
                         "url": lote["url"], "tem_foto": bool(lote["foto_url"]),
                         "situacao": lote["situacao"]},
                "leilao": {"casa": lote["casa"], "uf": lote["uf"],
                           "titulo": lote["leilao"], "data_pregao": lote["data_pregao"]},
                "peca": {"chave": lote["chave"], "confianca": lote["confianca"],
                         "especie": lote["especie"], "estado": lote["estado"],
                         "catalogo": lote["catalogo"], "codigo": lote["codigo"],
                         "ressalva": lote["ressalva"]},
                "dinheiro": {
                    "lance_pedido": lote["lance_inicial"],
                    "custo_total_de_arremate": round(custo, 2),
                    "mediana_dos_martelos": base["mediana"],
                    "receita_estimada_do_revendedor": round(receita, 2),
                    "margem": round(margem, 2),
                    "margem_sobre_o_custo": round(margem / custo, 3),
                },
                "base_da_conta": {
                    "n": base["n"],
                    "dispersao_relativa": base["dispersao_relativa"],
                    "faixa": [base["minimo"], base["maximo"]],
                    "periodo": base["periodo_dos_comparaveis"],
                    "nao_arrematados": len(base["nao_arrematados"]),
                },
                "por_que_pode_estar_esquecido": self._sinais(
                    lote, bool(lote["catalogo"]), lote["total_lotes"]),
                # Ao lado da conta, nunca dentro dela: preço de catálogo não é
                # preço de mercado, e a margem continua saindo do martelo.
                "referencia_de_catalogo": self.catalogo_da_peca(
                    lote["ano"], lote["metal"], lote["denominacao"]),
                "coletado_em": lote["coletado_em"],
            })

        achados.sort(key=lambda a: a["dinheiro"]["margem"], reverse=True)
        indefinidos_abertos = self.con.execute(
            """SELECT count(*) FROM lote l JOIN identificacao_indefinida x
               ON x.lote_id = l.id
               WHERE l.situacao IN ('aberto','pos_pregao')""").fetchone()[0]

        return {
            "parametros": {"margem_minima": margem_minima, "n_minimo": n_minimo,
                           "custos": asdict(self.custos)},
            "achados": achados[:limite],
            "lotes_abertos_examinados": len(abertos),
            "descartados_por_falta_de_comparavel": sem_base,
            "lotes_abertos_sem_identificacao": indefinidos_abertos,
            "como_ler": (
                "A margem é ESTIMADA e depende inteiramente de "
                "`fracao_revendedor`, que é o que o seu comprador paga e que "
                "ninguém publica — meça a sua nos negócios que você fizer e "
                "passe o valor real, senão a lista inteira desliza junto. "
                "`por_que_pode_estar_esquecido` não entra na conta: é o motivo "
                "pelo qual a oportunidade ainda estaria de pé, e vale como "
                "evidência, não como número. Nada aqui atesta autenticidade — "
                f"e note que {indefinidos_abertos} lotes abertos ficaram fora "
                "desta lista por não terem identificação, que é justamente onde "
                "o lote esquecido costuma estar: veja `lotes_para_ler`."),
        }

    # -------------------------------------------------------------------- busca

    def pesquisar(self, consulta: str, situacao: str | None = None,
                  limite: int = 30) -> dict[str, Any]:
        sql = ["""SELECT l.id, l.titulo, l.descricao, l.url, l.numero,
                         l.lance_inicial, l.preco_martelo, l.situacao,
                         l.data_resultado, l.coletado_em,
                         a.data_pregao, c.nome casa, c.uf,
                         i.chave, i.confianca, i.estado, i.catalogo, i.codigo,
                         x.motivo motivo_indefinicao
                  FROM lote_fts f JOIN lote l ON l.id = f.rowid
                  JOIN leilao a ON a.id = l.leilao_id JOIN casa c ON c.id = a.casa_id
                  LEFT JOIN identificacao i ON i.lote_id = l.id
                  LEFT JOIN identificacao_indefinida x ON x.lote_id = l.id
                  WHERE lote_fts MATCH ?"""]
        p: list[Any] = [consulta]
        if situacao:
            sql.append("AND l.situacao = ?"); p.append(situacao)
        sql.append("ORDER BY rank LIMIT ?"); p.append(limite)
        achados = self._linhas(" ".join(sql), *p)
        return {
            "consulta": consulta,
            "achados": achados,
            "como_ler": (
                "Onde `chave` vem nula, o lote está no acervo mas NÃO foi "
                "identificado — `motivo_indefinicao` diz o que faltou. Esses "
                "lotes não têm comparável e não recebem margem, o que não quer "
                "dizer que não valham: quer dizer que exigem seu olho."),
        }

    def lotes_para_ler(self, limite: int = 40,
                       so_abertos: bool = True) -> dict[str, Any]:
        """A fila de leitura humana: lotes abertos que o acervo não identificou.

        É a consulta mais útil deste servidor para quem caça peça esquecida, e
        por um motivo simples: o lote que a máquina não consegue classificar é o
        mesmo que não aparece em filtro nenhum do portal.
        """
        achados = self._linhas(
            f"""SELECT l.titulo, l.descricao, l.url, l.numero, l.lance_inicial,
                       l.situacao, a.data_pregao, a.total_lotes, c.nome casa, c.uf,
                       x.motivo, x.desarma_com, l.foto_url, l.coletado_em
                FROM identificacao_indefinida x JOIN lote l ON l.id = x.lote_id
                JOIN leilao a ON a.id = l.leilao_id JOIN casa c ON c.id = a.casa_id
                {"WHERE l.situacao IN ('aberto','pos_pregao')" if so_abertos else ""}
                ORDER BY a.data_pregao, l.lance_inicial LIMIT ?""", limite)
        for a in achados:
            a["desarma_com"] = json.loads(a.pop("desarma_com") or "[]")
            a["por_que_pode_estar_esquecido"] = self._sinais(
                a, tem_codigo=False, total_lotes=a.pop("total_lotes", None))
            a.pop("foto_url", None)
        return {
            "achados": achados,
            "como_ler": (
                "`motivo` diz o que faltou na descrição; `desarma_com` traz os "
                "termos que resolveriam a dúvida — se a foto do lote mostrar "
                "qualquer um deles, a peça passa a ter comparável. Nenhum destes "
                "lotes tem margem calculada, de propósito."),
        }

    def historico(self, termo: str, limite: int = 15) -> dict[str, Any]:
        """Todas as chaves que casam com um termo, e o martelo de cada uma."""
        chaves = self._linhas(
            """SELECT i.chave, count(*) n FROM identificacao i
               JOIN lote l ON l.id = i.lote_id
               WHERE l.preco_martelo IS NOT NULL AND (i.chave LIKE ?
                     OR i.denominacao LIKE ? OR i.codigo LIKE ?)
               GROUP BY i.chave ORDER BY 2 DESC LIMIT ?""",
            f"%{termo}%", f"%{termo}%", f"%{termo}%", limite)
        return {
            "termo": termo,
            "pecas": [self.comparaveis(c["chave"]) for c in chaves],
            "como_ler": ("Cada entrada é uma peça NUM ESTADO. A mesma moeda em "
                         "MBC e em FC aparece como duas, porque são duas "
                         "mercadorias — e é por isso que não há um preço só."),
        }
