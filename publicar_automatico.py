"""Atualiza o acervo financeiro e publica, sem ninguém olhando.

Disparado pelo Agendador de Tarefas do Windows. A coleta precisa rodar aqui,
na máquina do usuário: o proxy de egresso da nuvem responde 403 ao portal de
Mesquita — medido no acervo do Diário, e vale igual aqui.

A sequência é: coletar → comparar → só se mudou, reconstruir e publicar.

**Comparar antes de publicar não é economia, é correção.** Publicar sempre faria
o Render rebaixar 53 MB por semana sem nada ter mudado, e encheria a lista de
releases de versões idênticas — o que apaga o sinal de quando o Município de
fato mexeu em alguma coisa. A comparação é pelo conteúdo dos arquivos crus, não
pelo banco: o SQLite não é reprodutível byte a byte, e o CSV gerado pelo portal
muda de nome (GUID) a cada chamada mesmo com conteúdo idêntico.

Uso:  python publicar_automatico.py [--ensaio]
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent
BRUTOS = RAIZ / "dados_brutos"
NUCLEO = RAIZ / "dados" / "nucleo.db"
IMPRESSAO = RAIZ / "dados" / "impressao_digital.json"
REGISTRO = RAIZ / "publicacao.log"
REPOSITORIO = "fm85gn2y4q-maker/financas-mesquita"
PYTHON = str(RAIZ / ".venv" / "Scripts" / "python.exe")

# O sinal de vida vai para uma branch só dele, NÃO para o main. O Render
# observa o main e reconstrói a cada push: mandar o sinal para lá faria o
# serviço rebaixar o acervo toda semana, sem nada ter mudado.
RAMO_SINAL = "sinal-de-vida"
ARQUIVO_SINAL = "sinal_de_vida.json"

PASSOS_COLETA = [
    ("SICONFI", [PYTHON, "coletar_siconfi.py"]),
    ("PNCP", [PYTHON, "coletar_pncp.py"]),
    ("portal (API)", [PYTHON, "coletar_portal.py"]),
    # Os relatórios são a parte longa. `--sem-folha-nominal` fica DE FORA: a
    # folha entra por decisão expressa do Procurador (05/08/2026).
    ("portal (relatórios)", [PYTHON, "coletar_relatorios.py", "--desde", "2015"]),
]


def anotar(mensagem: str) -> None:
    linha = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {mensagem}"
    print(linha, flush=True)
    with REGISTRO.open("a", encoding="utf-8") as fh:
        fh.write(linha + "\n")


def rodar(comando: list[str], cwd: Path = RAIZ,
          extra: dict[str, str] | None = None) -> tuple[int, str]:
    ambiente = {**os.environ, **extra} if extra else None
    r = subprocess.run(comando, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=ambiente)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def impressao_digital() -> str:
    """Resumo do CONTEÚDO de tudo que foi coletado.

    Não serve o nome do arquivo nem a data: o portal gera cada relatório com um
    GUID novo, e o mesmo conteúdo sairia como novidade toda semana. Também não
    serve o sha256 do banco: SQLite não é reprodutível byte a byte.
    """
    resumos = []
    for arq in sorted(BRUTOS.rglob("*.json")):
        if arq.name == "manifesto.jsonl":
            continue
        d = hashlib.sha256()
        with arq.open("rb") as fh:
            for bloco in iter(lambda: fh.read(4 * 1024 * 1024), b""):
                d.update(bloco)
        resumos.append(f"{arq.relative_to(BRUTOS).as_posix()}:{d.hexdigest()}")
    return hashlib.sha256("\n".join(resumos).encode()).hexdigest()


def gravar_sinal(resultado: str, detalhe: str = "", numeros: dict | None = None,
                 ensaio: bool = False) -> None:
    """Deixa no GitHub a prova de que a tarefa rodou — e como terminou.

    Tarefa agendada que falha em silêncio é pior que tarefa nenhuma: passa a
    impressão de acervo em dia. Escreve pela API, não por push, para não tocar
    na árvore de trabalho enquanto o mesmo script mexe no Dockerfile do main.
    """
    if ensaio:
        anotar(f"ensaio: sinal NÃO gravado (seria '{resultado}')")
        return
    conteudo = {
        "quando": datetime.now().astimezone().isoformat(timespec="seconds"),
        "resultado": resultado,
        "detalhe": detalhe,
        **(numeros or {}),
    }
    carga = base64.b64encode(
        json.dumps(conteudo, ensure_ascii=False, indent=1).encode()).decode()

    # O `ref` vai na QUERY, não como `-f`. Com `-f` o gh o manda no corpo, que
    # o GitHub ignora num GET: ele procura o arquivo no ramo padrão, não acha,
    # devolve 404, e o script segue sem o sha. A primeira gravação funciona
    # (arquivo novo não precisa de sha) e todas as seguintes falham com
    # 422 "sha wasn't supplied" — ou seja, o sinal congela na primeira execução
    # e o monitor passa a acusar tarefa morta enquanto ela roda todo domingo.
    codigo, saida = rodar(["gh", "api",
                           f"repos/{REPOSITORIO}/contents/{ARQUIVO_SINAL}"
                           f"?ref={RAMO_SINAL}"])
    sha = ""
    if codigo == 0:
        try:
            sha = json.loads(saida)["sha"]
        except Exception:                                   # noqa: BLE001
            sha = ""
    if not sha:
        anotar("aviso: não li o sha do sinal anterior; a gravação pode falhar "
               "se o arquivo já existir.")

    comando = ["gh", "api", "-X", "PUT",
               f"repos/{REPOSITORIO}/contents/{ARQUIVO_SINAL}",
               "-f", f"message=sinal de vida: {resultado}",
               "-f", f"content={carga}",
               "-f", f"branch={RAMO_SINAL}"]
    if sha:
        comando += ["-f", f"sha={sha}"]
    codigo, saida = rodar(comando)
    if codigo != 0:
        anotar(f"aviso: não consegui gravar o sinal de vida ({codigo})")
        anotar("  " + " / ".join(saida.strip().splitlines()[-2:]))
    else:
        anotar(f"sinal de vida gravado: {resultado}")


def numeros_do_nucleo() -> dict:
    import sqlite3
    con = sqlite3.connect(f"file:{NUCLEO}?mode=ro", uri=True)
    try:
        rel, regras = con.execute(
            "SELECT count(*), count(DISTINCT regra) FROM relatorio_linha").fetchone()
        siconfi = con.execute("SELECT count(*) FROM siconfi_linha").fetchone()[0]
    finally:
        con.close()
    return {"relatorio_linha": rel, "relatorios": regras, "siconfi_linha": siconfi}


def main(argv: list[str] | None = None) -> int:
    ensaio = "--ensaio" in (argv or sys.argv[1:])
    anotar("=" * 60)
    anotar(f"atualização semanal{' (ENSAIO)' if ensaio else ''}")

    for nome, comando in PASSOS_COLETA:
        anotar(f"coletando: {nome}…")
        codigo, saida = rodar(comando)
        if codigo != 0:
            cauda = " / ".join(saida.strip().splitlines()[-3:])
            anotar(f"FALHOU em {nome} ({codigo}): {cauda}")
            gravar_sinal("falha", f"{nome}: {cauda}"[:400], ensaio=ensaio)
            return 2
        anotar(f"  {nome}: ok")

    nova = impressao_digital()
    antiga = ""
    if IMPRESSAO.exists():
        antiga = json.loads(IMPRESSAO.read_text(encoding="utf-8")).get("sha256", "")

    if nova == antiga:
        anotar("nada mudou no portal desde a última coleta; não republico.")
        gravar_sinal("sem novidade", numeros=numeros_do_nucleo() if NUCLEO.exists() else None,
                     ensaio=ensaio)
        return 0

    anotar("houve mudança; reconstruindo o acervo…")
    # `carregar_colunas` entra DUAS vezes, e as duas são necessárias:
    # `preparar_nucleo` monta o núcleo copiando do acervo completo, e a tabela
    # de rótulos não sobrevive à cópia. Sem a segunda chamada, o acervo que vai
    # para a release sai sem nome de coluna nenhum — e ninguém notaria, porque
    # a ferramenta simplesmente devolve `coluna: null` em tudo.
    no_nucleo = {"ACERVO_DB": str(NUCLEO)}
    for nome, comando, ambiente in [
            ("acervo", [PYTHON, "construir_acervo.py"], None),
            ("relatórios", [PYTHON, "ingerir_relatorios.py"], None),
            ("rótulos", [PYTHON, "carregar_colunas.py"], None),
            ("núcleo", [PYTHON, "preparar_nucleo.py"], None),
            ("rótulos no núcleo", [PYTHON, "carregar_colunas.py"], no_nucleo)]:
        codigo, saida = rodar(comando, extra=ambiente)
        if codigo != 0:
            cauda = " / ".join(saida.strip().splitlines()[-3:])
            anotar(f"FALHOU ao montar {nome} ({codigo}): {cauda}")
            gravar_sinal("falha", f"montagem/{nome}: {cauda}"[:400], ensaio=ensaio)
            return 3
        anotar(f"  {nome}: ok")

    codigo, saida = rodar([PYTHON, "-m", "pytest", "tests", "-q"])
    if codigo != 0:
        anotar("FALHOU nos testes; NÃO publico acervo que não passa.")
        gravar_sinal("falha", "testes: " + " / ".join(saida.strip().splitlines()[-3:]),
                     ensaio=ensaio)
        return 4
    anotar("  testes: ok")

    versao = f"{date.today():%Y.%m.%d}"
    if ensaio:
        anotar(f"ensaio: pararia aqui; publicaria a v{versao}")
        return 0

    codigo, saida = rodar([PYTHON, "preparar_release.py", versao])
    if codigo != 0:
        gravar_sinal("falha", "empacotamento")
        return 5
    linhas = saida.splitlines()
    url = next((l.split("ARG ACERVO=")[1].strip() for l in linhas if "ARG ACERVO=" in l), "")
    digest = next((l.split("ARG ACERVO_SHA256=")[1].strip() for l in linhas
                   if "ARG ACERVO_SHA256=" in l), "")
    pacote = RAIZ / "dist" / f"financas-mesquita-v{versao}.db.gz"
    if not (url and digest and pacote.exists()):
        anotar("não consegui ler a URL ou o hash da saída do empacotamento.")
        gravar_sinal("falha", "empacotamento sem URL/hash")
        return 5

    codigo, saida = rodar(["gh", "release", "create", f"v{versao}", str(pacote),
                           "--title", f"Acervo v{versao}",
                           "--notes", f"Atualização automática de {date.today():%d/%m/%Y}. "
                                      f"{numeros_do_nucleo()}"])
    if codigo != 0:
        anotar("FALHOU ao publicar a release: " +
               " / ".join(saida.strip().splitlines()[-2:]))
        gravar_sinal("falha", "release")
        return 6
    anotar(f"  release v{versao} publicada")

    dockerfile = RAIZ / "Dockerfile"
    texto = dockerfile.read_text(encoding="utf-8")
    texto = "\n".join(
        (f"ARG ACERVO={url}" if l.startswith("ARG ACERVO=") else
         f"ARG ACERVO_SHA256={digest}" if l.startswith("ARG ACERVO_SHA256=") else l)
        for l in texto.splitlines()) + "\n"
    dockerfile.write_text(texto, encoding="utf-8")

    IMPRESSAO.write_text(json.dumps({"sha256": nova, "versao": versao,
                                     "quando": datetime.now().astimezone().isoformat()},
                                    indent=1), encoding="utf-8")

    for comando in (["git", "add", "Dockerfile"],
                    ["git", "commit", "-m", f"Acervo v{versao} (atualizacao automatica)"],
                    ["git", "push", "origin", "main"]):
        codigo, saida = rodar(comando)
        if codigo != 0:
            anotar(f"FALHOU no git ({' '.join(comando[:2])}): " +
                   " / ".join(saida.strip().splitlines()[-2:]))
            gravar_sinal("falha", "git")
            return 7

    anotar(f"publicado: v{versao}. O Render reconstrói sozinho.")
    gravar_sinal("publicado", f"v{versao}", numeros=numeros_do_nucleo())
    return 1        # 1 = houve novidade, para quem chama pelo .cmd


if __name__ == "__main__":
    raise SystemExit(main())
