"""Descobre o nome de cada coluna dos relatórios — e só o que se prova.

O CSV do portal não tem cabeçalho. Mas o MESMO relatório sai em PDF, e o PDF
traz os rótulos: uns como cabeçalho de coluna, numa faixa de x, e outros
embutidos no corpo como "Rótulo: valor". Este script gera o PDF, lê os rótulos
e os casa com as posições do CSV **pelo valor**, registro a registro.

A REGRA: um rótulo só é atribuído a uma posição se a correspondência se repetir
em vários registros e nenhum outro rótulo disputar aquela posição. Data repete
muito num contrato — assinatura, início, vencimento, publicação —, e casar pelo
primeiro que bate produziria rótulo errado com aparência perfeita. Onde não se
prova, a coluna continua sem nome, que é a informação honesta.

Grava a tabela `relatorio_coluna` no acervo.

Uso:  python nomear_colunas.py [--regra TRECHO] [--registros 40]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sqlite3
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

import fitz

from coletar_relatorios import BASE, PUBLICO, abrir_sessao

RAIZ = Path(__file__).resolve().parent
BANCO = RAIZ / "dados" / "acervo.db"
ASSINATURAS = RAIZ / "dados" / "relatorios.json"
BRUTOS = RAIZ / "dados_brutos" / "portal_relatorios"
FORM = "464569294"

ESQUEMA = """
CREATE TABLE IF NOT EXISTS relatorio_coluna (
    regra      TEXT NOT NULL,
    posicao    INTEGER NOT NULL,
    rotulo     TEXT NOT NULL,
    -- Em quantos registros a correspondência se confirmou, de quantos testados.
    acertos    INTEGER NOT NULL,
    testados   INTEGER NOT NULL,
    origem     TEXT NOT NULL,   -- 'cabecalho' | 'embutido'
    PRIMARY KEY (regra, posicao)
);
"""

# "Rótulo: valor" dentro do corpo do relatório.
EMBUTIDO = re.compile(r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s./º°]{2,28}?):\s*(.+)")


def gerar_pdf(op, regra: str, params: list[str]) -> str | None:
    q = {"action": "executeRule", "pType": "2", "ruleName": regra, "sys": "LAI",
         "formID": FORM, "parentRID": "", "decodedParams": "true"}
    for i, p in enumerate(params):
        q[f"P_{i}"] = "2" if re.fullmatch(r"Relatorio|RELATORIO|TIPO_RELATORIO", p) else ""
    resp = op.open(BASE + "executeRule.do?" + urllib.parse.urlencode(q),
                   data=b"", timeout=900).read().decode("latin-1", "replace")
    if "WFRReports" not in resp:
        return None
    arq = resp.split("WFRReports")[1].split("'")[0].replace("\\\\", "\\").split("\\")[-1]
    return PUBLICO + arq


def registros_do_pdf(caminho: Path, paginas: int = 6) -> list[list[tuple[str, str]]]:
    """Extrai os pares (rótulo, valor) AGRUPADOS POR REGISTRO.

    Agrupar importa mais do que parece. A primeira versão montava um índice
    global valor→rótulo com todos os registros juntos, e aí a data de
    vencimento de um contrato casava com a coluna de início de outro: num
    contrato há quatro datas parecidas — assinatura, início, vencimento e
    publicação —, e o mesmo rótulo acabou ganhando quatro posições diferentes.
    Rótulo errado com aparência de certo é o erro que este acervo existe para
    evitar, e aqui ele apareceu na própria ferramenta de nomear.

    Um registro começa na linha de valores logo abaixo da faixa de cabeçalho e
    vai até a próxima faixa de cabeçalho.
    """
    doc = fitz.open(caminho)
    registros: list[list[tuple[str, str]]] = []
    atual: list[tuple[str, str]] | None = None

    for n in range(min(paginas, doc.page_count)):
        palavras = doc[n].get_text("words")
        if not palavras:
            continue
        linhas: dict[int, list] = defaultdict(list)
        for w in palavras:
            linhas[round(w[1] / 3)].append(w)
        ordenadas = [sorted(v, key=lambda w: w[0]) for _, v in sorted(linhas.items())]

        i = 0
        while i < len(ordenadas):
            linha = ordenadas[i]
            texto = " ".join(w[4] for w in linha)
            if re.search(r"N[ºo°]\s*(Compra|Processo|Contrato)|CPF\s*/\s*CNPJ", texto) \
                    and i + 1 < len(ordenadas):
                if atual:
                    registros.append(atual)
                atual = []
                faixas = _agrupar_por_coluna(linha)
                valores = _agrupar_por_coluna(ordenadas[i + 1])
                for x, rotulo in faixas:
                    valor = next((v for xv, v in valores if abs(xv - x) < 12), None)
                    if valor:
                        atual.append((rotulo, valor))
                i += 2
                continue
            if atual is not None:
                for m in EMBUTIDO.finditer(texto):
                    rotulo, valor = m.group(1).strip(), m.group(2).strip()
                    corte = re.search(
                        r"\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s./º°]{2,28}?:", valor)
                    if corte:
                        valor = valor[:corte.start()].strip()
                    if valor:
                        atual.append((rotulo, valor))
            i += 1

    if atual:
        registros.append(atual)
    doc.close()
    return registros


def _pares_planos(caminho: Path, paginas: int = 6) -> list[tuple[str, str]]:
    """Versão antiga, mantida só para contagem no relato."""
    doc = fitz.open(caminho)
    pares: list[tuple[str, str]] = []

    for n in range(min(paginas, doc.page_count)):
        palavras = doc[n].get_text("words")
        if not palavras:
            continue
        # Agrupa em linhas por y.
        linhas: dict[int, list] = defaultdict(list)
        for w in palavras:
            linhas[round(w[1] / 3)].append(w)

        ordenadas = [sorted(v, key=lambda w: w[0]) for _, v in sorted(linhas.items())]

        # 1) Faixas de x do cabeçalho: a linha que contém vários rótulos
        #    conhecidos e é seguida por uma linha de valores alinhados.
        for i, linha in enumerate(ordenadas[:-1]):
            texto = " ".join(w[4] for w in linha)
            if not re.search(r"N[ºo°]\s*(Compra|Processo)|CPF\s*/\s*CNPJ", texto):
                continue
            faixas = _agrupar_por_coluna(linha)
            seguinte = _agrupar_por_coluna(ordenadas[i + 1])
            for x, rotulo in faixas:
                valor = next((v for xv, v in seguinte if abs(xv - x) < 12), None)
                if valor:
                    pares.append((rotulo, valor))

        # 2) "Rótulo: valor" no corpo.
        for linha in ordenadas:
            texto = " ".join(w[4] for w in linha)
            for m in EMBUTIDO.finditer(texto):
                rotulo = m.group(1).strip()
                valor = m.group(2).strip()
                # corta no próximo "Rótulo:" da mesma linha
                corte = re.search(r"\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s./º°]{2,28}?:", valor)
                if corte:
                    valor = valor[:corte.start()].strip()
                if valor:
                    pares.append((rotulo, valor))
    doc.close()
    return pares


def _agrupar_por_coluna(linha: list) -> list[tuple[float, str]]:
    """Junta palavras vizinhas numa mesma célula, pelo espaçamento."""
    grupos: list[tuple[float, list[str]]] = []
    for w in linha:
        if grupos and w[0] - _fim(grupos[-1]) < 8:
            grupos[-1][1].append(w[4])
            grupos[-1] = (grupos[-1][0], grupos[-1][1])
            _FIM[id(grupos[-1][1])] = w[2]
        else:
            grupos.append((w[0], [w[4]]))
            _FIM[id(grupos[-1][1])] = w[2]
    return [(x, " ".join(p)) for x, p in grupos]


_FIM: dict[int, float] = {}


def _fim(grupo: tuple[float, list[str]]) -> float:
    return _FIM.get(id(grupo[1]), grupo[0])


def normalizar(v: str) -> str:
    return re.sub(r"\s+", " ", (v or "")).strip().lower()


def mapear(regra_arquivo: str, registros_pdf: list[list[tuple[str, str]]],
           limite: int) -> dict[int, tuple[str, int, int, str]]:
    """Casa rótulo→posição registro a registro, e só aceita o que se repete.

    Cada registro do PDF é primeiro pareado com a SUA linha no CSV — a que
    contém o maior número dos valores daquele registro. Sem esse pareamento, o
    voto atravessa registros e o rótulo migra de coluna.
    """
    arq = BRUTOS / f"{regra_arquivo}.json"
    if not arq.exists():
        return {}
    linhas = list(csv.reader(io.StringIO(arq.read_bytes().decode("latin-1"))))
    linhas = [l for l in linhas if any((c or "").strip() for c in l)]
    if not linhas:
        return {}

    # Índice de valor → linhas que o contêm, para achar a linha de cada registro.
    onde: dict[str, set[int]] = defaultdict(set)
    for i, linha in enumerate(linhas):
        for c in linha:
            v = normalizar(c)
            if len(v) >= 4:
                onde[v].add(i)

    votos: dict[int, Counter] = defaultdict(Counter)
    pareados = 0

    for pares in registros_pdf[:limite]:
        contagem: Counter = Counter()
        for _, valor in pares:
            v = normalizar(valor)
            if len(v) >= 4:
                for i in onde.get(v, ()):
                    contagem[i] += 1
        if not contagem:
            continue
        (melhor, forca), *resto = contagem.most_common()
        # Exige folga: sem ela, um registro casaria com a linha errada e todo o
        # voto seguinte sairia deslocado.
        if forca < 3 or (resto and forca < resto[0][1] + 2):
            continue
        pareados += 1
        linha = linhas[melhor]

        # Só vota quando o valor é ÚNICO na linha e o rótulo é único no
        # registro. Num contrato, vencimento e fim costumam ser a mesma data, e
        # o mesmo valor em duas posições não decide nada: contá-lo dá voto a
        # uma posição por acaso, e foi o que produziu "Fim" em quatro colunas
        # diferentes. Registros em que as datas divergem resolvem sozinhos.
        ocorrencias = Counter(normalizar(c) for c in linha)
        rotulos_do_registro = Counter(r for r, _ in pares)

        for rotulo, valor in pares:
            v = normalizar(valor)
            if len(v) < 3 or ocorrencias[v] != 1 or rotulos_do_registro[rotulo] != 1:
                continue
            for pos, bruto in enumerate(linha):
                if normalizar(bruto) == v:
                    votos[pos][rotulo] += 1
                    break

    # Primeiro, o vencedor de cada posição, com folga.
    candidatos: dict[int, tuple[str, int]] = {}
    for pos, contagem in votos.items():
        (rotulo, n), *resto = contagem.most_common()
        if n >= 3 and (not resto or n >= 2 * resto[0][1]):
            candidatos[pos] = (rotulo, n)

    # Depois, o inverso: um rótulo não pode nomear duas posições. Quando
    # disputa, fica com a que tiver mais votos e a outra perde o nome — porque
    # não se sabe qual das duas datas é a de vencimento e qual é a de fim.
    melhor_por_rotulo: dict[str, int] = {}
    for pos, (rotulo, n) in candidatos.items():
        atual = melhor_por_rotulo.get(rotulo)
        if atual is None or n > candidatos[atual][1]:
            melhor_por_rotulo[rotulo] = pos

    mapa: dict[int, tuple[str, int, int, str]] = {}
    for pos, (rotulo, n) in candidatos.items():
        if melhor_por_rotulo[rotulo] != pos:
            continue
        mapa[pos] = (rotulo, n, pareados, "pdf")
    return mapa


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--regra", help="só as regras cujo nome contenha este trecho")
    p.add_argument("--registros", type=int, default=40)
    args = p.parse_args()

    assinaturas = json.loads(ASSINATURAS.read_text(encoding="utf-8"))
    con = sqlite3.connect(BANCO)
    con.executescript(ESQUEMA)

    op = abrir_sessao()
    temp = RAIZ / "dados" / "_relatorio.pdf"

    for regra in sorted(assinaturas):
        if args.regra and args.regra.lower() not in regra.lower():
            continue
        arquivo = re.sub(r"[^A-Za-z0-9]+", "_", regra).strip("_").lower()
        if not (BRUTOS / f"{arquivo}.json").exists():
            continue

        url = gerar_pdf(op, regra, assinaturas[regra])
        if not url:
            print(f"{regra[:50]:<52} sem PDF")
            continue
        temp.write_bytes(op.open(url, timeout=900).read())
        regs = registros_do_pdf(temp)
        mapa = mapear(arquivo, regs, args.registros)

        con.execute("DELETE FROM relatorio_coluna WHERE regra = ?", (arquivo,))
        con.executemany(
            "INSERT INTO relatorio_coluna VALUES (?,?,?,?,?,?)",
            [(arquivo, pos, r, n, t, o) for pos, (r, n, t, o) in mapa.items()])
        con.commit()
        print(f"{regra[:50]:<52} {len(mapa):>3} colunas nomeadas "
              f"(de {len(regs)} registros no PDF)")
        for pos in sorted(mapa):
            r, n, t, _ = mapa[pos]
            print(f"     [{pos:>2}] {r:<28} {n}/{t}")

    temp.unlink(missing_ok=True)
    con.close()


if __name__ == "__main__":
    main()
