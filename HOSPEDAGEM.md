# Publicar o acervo financeiro de Mesquita

Três caminhos, do mais curto ao mais trabalhoso. Não são alternativas
excludentes: o `.mcpb` serve o Claude no seu PC, o Render serve o ChatGPT e o
celular.

A divisão de trabalho é a de sempre: os artefatos estão prontos e testados;
criar conta, conceder OAuth e publicar release no GitHub é seu — vincular a sua
identidade a um terceiro não é coisa que eu faça no seu lugar.

---

## 1. Extensão do Claude Desktop (`.mcpb`) — o caminho curto

    python empacotar_mcpb.py

Gera `dist/financas-mesquita.mcpb` (~63 MB). Instale arrastando o arquivo para
**Configurações → Extensões** do Claude Desktop. Não precisa de conta, de túnel
nem de o PC estar publicando nada: o servidor roda localmente por stdio, e o
acervo viaja dentro do pacote.

Duas armadilhas conhecidas, ambas já tratadas no script:

- **O Claude Desktop não usa o Python do projeto.** Ele pega o primeiro
  `python` do PATH dele, e as dependências viajam em `server/lib/py312`,
  `py313`, `py314` — `pydantic_core` é binário compilado, e o `.pyd` de uma
  versão não carrega noutra. Se o Python que ele achar não estiver na lista,
  a extensão avisa em vez de falhar em silêncio. Para fixar um interpretador:

      python empacotar_mcpb.py --python C:\caminho\sem\espacos\python.exe

- **O pin do `mcp` é lido de `requirements-servidor.txt`**, não repetido no
  empacotador. Isso não é preciosismo: a versão anterior pedia `mcp>=1.28` sem
  teto, empacotava a **2.0.0** — em que `mcp.server.fastmcp` não existe mais —
  e o pacote zipava, instalava e só quebrava na primeira pergunta do usuário.

Para conferir antes de instalar: `pytest tests/test_mcpb.py` sobe o pacote
construído com o `python` do PATH e faz o handshake. É o teste que apanhou a
versão errada do `mcp`.

---

## 2. Servidor local por HTTP — para provar antes de hospedar

    python -m financas --http

Sobe em `http://127.0.0.1:8767/mcp`. Só aceita requisições locais: sem
`--dominio`, qualquer Host de fora leva 421, e isso é proteção contra DNS
rebinding, não defeito.

Expondo por túnel, declare o domínio, porque a comparação de Host é exata e
não há curinga:

    python -m financas --http --dominio meu-tunel.exemplo.dev

---

## 3. Render — para o ChatGPT, o celular e o PC desligado

### Antes: publicar o acervo

O banco tem ~100 MB e **não entra no Git**. Vai como asset de release:

    python construir_acervo.py        # se ainda não tiver o banco
    python preparar_release.py 1.0.0

O script imprime o comando `gh release create` pronto e as duas linhas para o
Dockerfile. Rode-o com o servidor **fechado**: um `-wal` ao lado do banco
significa escritas que não entrariam no arquivo publicado, e ele avisa.

Depois de publicar a release, preencha no `Dockerfile`:

    ARG ACERVO=https://github.com/<você>/financas-mesquita/releases/download/v1.0.0/financas-mesquita-v1.0.0.db.gz
    ARG ACERVO_SHA256=<o hash que o script imprimiu>

Enquanto essas linhas estiverem vazias a construção **para**, com a mensagem
dizendo o que falta. É de propósito: imagem sem acervo sobe normalmente e só
falha na primeira consulta.

### Depois: o deploy

Dashboard → **Blueprints → New Blueprint**, apontando para o repositório. O
`render.yaml` já declara o serviço.

Duas coisas só existem **depois** do primeiro deploy, quando o endereço público
nasce. Preencha-as nas variáveis de ambiente e refaça o deploy:

| variável | para quê |
|---|---|
| `FINANCAS_DOMINIOS` | `financas-mesquita.onrender.com` — sem isso, 421 em tudo |
| `FINANCAS_URL_PUBLICA` | `https://financas-mesquita.onrender.com` — ativa o OAuth que o ChatGPT exige |
| `FINANCAS_SEGREDO_OAUTH` | o Blueprint gera. Não deixe vazio |

O `FINANCAS_SEGREDO_OAUTH` merece um parágrafo: sem valor fixo, cada partida do
processo sorteia um segredo novo e toda autorização concedida antes deixa de
valer. No plano gratuito, que hiberna por inatividade, isso significa
reautorizar o dia inteiro.

### O que não declarar, e por quê

**`healthCheckPath` fica de fora de propósito.** O Render faz GET no caminho
declarado e só considera saudável com 2xx/3xx. O endpoint MCP responde
`406` a `GET /mcp` (exige `text/event-stream`), `404` a `GET /`, e `200` só a
`POST /mcp`. Não existe caminho que devolva 2xx a um GET — declarar qualquer um
deixaria o serviço eternamente "unhealthy" e o deploy falharia sem dizer por quê.

---

## Trocar a lista de ferramentas exige recriar o conector

Nem o Claude nem o ChatGPT releem as ferramentas de um conector já existente.
Mudando os nomes ou a assinatura das ferramentas, remova e recrie o conector.
Isso **não** vale para atualização só de dados: publicando acervo novo, o
conector segue funcionando.

---

## Atualizar o acervo

    python coletar_siconfi.py
    python coletar_pncp.py
    python coletar_portal.py
    python construir_acervo.py
    pytest tests

A coleta é incremental no que importa: reexecutar sobrescreve os arquivos crus
e acrescenta uma linha ao `manifesto.jsonl` de cada fonte, com data e sha256.
A ingestão reconstrói o banco do zero a partir do cru — pode rodar quantas
vezes quiser, e nunca vai à rede.

Depois, para republicar: `preparar_release.py <nova versão>`, anexar o `.gz`,
trocar as duas linhas do Dockerfile, commitar. O Render reconstrói e confere o
hash; divergindo, o build falha em vez de subir acervo diferente do testado.

---

# Publicar o acervo de leilões

Segundo serviço, com banco, endereço e conector próprios. O `render.yaml` já
declara os dois; o `Dockerfile.leiloes` é a imagem deste.

## A ordem importa, e ela começa fora daqui

Este acervo **não existe antes da primeira coleta**, e a coleta depende de uma
máquina que alcance o `leiloesbr.com.br`. Aplicar o Blueprint antes disso faz
este serviço falhar na construção — de propósito, com a mensagem dizendo o que
falta — enquanto o serviço financeiro sobe normalmente. É a razão de serem duas
imagens e não uma.

    python descobrir_leiloesbr.py --leilao <id>   # mede a página real
    # corrija PADROES em coletar_leiloesbr.py com o relatório na mão
    python coletar_leiloesbr.py
    python construir_leiloes.py
    python -m pytest tests/test_leiloes.py tests/test_publicacao_leiloes.py
    python preparar_release_leiloes.py 1.0.0

O script imprime o resumo do conteúdo, o `gh release create` pronto e as duas
linhas para o `Dockerfile.leiloes`. Repare no número que ele destaca: **quantos
lotes ficaram sem identificação**. É ele, e não o total de lotes, que diz se o
acervo publicado presta.

A tag leva o prefixo `leiloes-` porque as duas releases moram no mesmo
repositório — sem ele, publicar como `v1.0.0` colidiria com a tag do acervo
financeiro.

## Depois do primeiro deploy

Três variáveis, preenchidas quando o endereço público nascer:

| variável | para quê |
|---|---|
| `LEILOES_DOMINIOS` | `leiloes-numismatica.onrender.com` — sem isso, 421 em tudo |
| `LEILOES_URL_PUBLICA` | `https://leiloes-numismatica.onrender.com` — ativa o OAuth do ChatGPT |
| `LEILOES_SEGREDO_OAUTH` | o Blueprint gera. Não deixe vazio |

Conferido contra o servidor no ar: `/.well-known/oauth-authorization-server`
responde com o escopo `leiloes-numismatica`, o registro dinâmico de cliente
funciona, e `POST /mcp` sem token leva 401.

## O aviso que este acervo tem e os outros não

**A aprovação do OAuth é automática.** Quem chegar à URL completa o fluxo e
recebe um token. Isso protege contra chamada sem token, não contra quem conhece
o endereço.

Nos acervos públicos deste repositório isso era aceitável: Diário Oficial e
legislação municipal a Prefeitura já publica, e o pior que acontece é alguém
ler o que já era lido. Aqui não. Os lotes vêm de portal público, mas a **lista
de oportunidades não** — ela é a sua leitura de mercado, e quem a obtiver dá
lance contra você no mesmo pregão. Trate a URL como credencial: não a publique,
não a ponha em repositório público, e prefira mantê-la fora de índice de busca.

Querendo fechar de vez, o caminho é trocar `LEILOES_SEGREDO_OAUTH` — todas as
assinaturas antigas param de valer de uma vez.

## Escopo separado, de propósito

O escopo deste conector é `leiloes-numismatica`, e o do financeiro,
`financas-mesquita`. Dois conectores com o mesmo escopo no mesmo cliente
disputam a mesma autorização. Há teste que confere que eles não coincidem.
