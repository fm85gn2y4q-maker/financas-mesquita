# Imagem do servidor do acervo financeiro de Mesquita (Render, Cloud Run, Fly).
FROM python:3.12-slim

WORKDIR /app

# As dependências mudam menos que o código: instaladas antes, para aproveitar o
# cache entre construções.
COPY requirements-servidor.txt ./
RUN pip install --no-cache-dir -r requirements-servidor.txt

COPY financas/ ./financas/

# O acervo NÃO viaja no repositório: são ~100 MB, acima dos 50 MB em que o
# GitHub adverte, e cada coleta nova somaria outro tanto ao histórico, para
# sempre. Vem como asset de release, com o sha256 declarado aqui e conferido
# ANTES de descomprimir — divergindo o publicado do declarado, a construção
# falha em vez de subir um acervo diferente do que foi testado.
#
# Os três modos de falha conhecidos desta escolha, para reconhecê-los no log:
#   - repositório privado devolve 404 no download (a release precisa ser pública);
#   - asset errado anexado à tag (o hash pega, e a mensagem diz o que veio);
#   - URL divergente do nome do repositório depois de renomeá-lo.
#
# Publicar acervo novo é rodar `python preparar_release.py <versão>`, anexar o
# .gz à release e trocar estas duas linhas.
#
# PREENCHER APÓS A PRIMEIRA RELEASE. Enquanto estiverem vazias, a construção
# para no instalar_acervo.py com mensagem explícita — de propósito: imagem sem
# acervo subiria e só falharia na primeira consulta do usuário.
ARG ACERVO=
ARG ACERVO_SHA256=
COPY instalar_acervo.py ./
RUN python instalar_acervo.py "$ACERVO" dados/acervo.db "$ACERVO_SHA256"

# O serviço define a porta; 8080 é o padrão do Cloud Run quando ele não define.
ENV PORT=8080 \
    FINANCAS_HOST=0.0.0.0 \
    ACERVO_DB=/app/dados/acervo.db \
    PYTHONUTF8=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# FINANCAS_DOMINIOS é definido depois do primeiro deploy, quando o endereço
# público passa a existir. Sem ele, só requisições locais são aceitas — o que
# na prática significa que o serviço responde 421 a tudo.
CMD ["python", "-m", "financas", "--http"]
