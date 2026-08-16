# Acervo financeiro de Mesquita/RJ

Servidor MCP sobre o financeiro do Município, montado a partir de três fontes
independentes. Segue o método de `legis-mesquita/GUIA-NOVO-ACERVO.md`.

    python coletar_siconfi.py      # série oficial do Tesouro
    python coletar_pncp.py         # o que foi divulgado no PNCP
    python coletar_portal.py       # patrimônio, obras e o mapa do portal
    python construir_acervo.py     # dados_brutos/ → dados/acervo.db
    python cruzar_dom.py           # mede a lacuna do PNCP contra o Diário
    .venv\Scripts\python -m pytest tests
    .venv\Scripts\python -m financas          # servidor MCP (stdio)
    .venv\Scripts\python empacotar_mcpb.py    # extensão do Claude Desktop

Para publicar — extensão, servidor local ou Render —, veja [HOSPEDAGEM.md](HOSPEDAGEM.md).

## O que há dentro

| Tabela | Linhas | Fonte | Alcance |
|---|---:|---|---|
| `relatorio_linha` | 2.905.100 | relatórios do portal | 30 relatórios, 2015-2026 |
| `relatorio_derivado` | 14.127.503 | derivado do conteúdo | CNPJ, data, valor, link |
| `siconfi_linha` | 126.466 | SICONFI/Tesouro | RREO, RGF e DCA, 2013-2026 |
| `patrimonio_bem` | 69.792 | API do portal | fotografia única |
| `portal_tela` | 1.375 | API do portal | mapa de 883 telas |
| `pncp_documento` | 71 | PNCP | 50 editais, 20 contratos, 1 ata |
| `obra` | 46 | API do portal | 2021-2025 |

Os relatórios são a exportação **"Dados Abertos"** que o próprio portal oferece
em cada tela, acionada pela regra que ele usa no botão "Relatório":

    POST /webrun/executeRule.do?action=executeRule&pType=2
         &ruleName=<regra>&sys=LAI&formID=464569294&P_<n>=7
      → caminho de WFRReports\Generated\<GUID>.CSV
      → servido em /ver20240713/WFRReports/Generated/<GUID>.CSV

São 37 regras, mapeadas por `descobrir_relatorios.py` a partir do próprio pacote
de regras do portal; 30 devolveram dados. Entre elas a **despesa nota a nota**
com favorecido e CNPJ, receita, contratos, avisos e editais, dispensas, diárias,
cargos e folha.

## O risco desta base

Nos outros acervos o risco é a proveniência (jurisprudência), a vigência
(legislação) ou a republicação (diário oficial). Aqui é a **divergência entre
fontes sobre o mesmo fato**: o mesmo contrato pode ser extrato no Diário,
registro no PNCP, empenho na tela de despesas e bem no patrimônio, com valores
e datas que não batem. Nenhuma fonte é "a verdade"; cada uma é uma declaração
datada. Por isso toda linha carrega `coletado_em`, e `conciliar_fornecedor`
põe as versões lado a lado sem escolher entre elas.

## Quatro armadilhas medidas

**1. A hierarquia do SICONFI só existe na ordem das linhas.** No RREO-Anexo 02,
"Administração Geral" aparece sete vezes no mesmo anexo e coluna, sob funções
diferentes, de R$ 30 mil a R$ 59,9 milhões. Nada no registro diz de quem é
filha. Daí o campo `ordem`, e daí `despesa_por_funcao` só agregar onde a soma
das subfunções fecha com a função — 3.587 linhas ficam declaradamente sem
vínculo em vez de ganharem um pai inventado.

**2. Comparar colunas diferentes produz resultado impecável e errado.** A
primeira versão de `despesa_por_funcao` filtrava a coluna com `LIKE`, o que
casava "No Bimestre" e "Até o Bimestre" ao mesmo tempo: a função Legislativa de
2025 fechava em R$ 10,97 mi contra subfunções somando R$ 1,82 mi. Hoje a coluna
é comparada por igualdade exata, e coluna inexistente devolve a lista do que há
em vez de vazio silencioso.

**3. O parâmetro `ano` do portal é ignorado em silêncio.** Pedir `patrimonio` de
2021 a 2026 devolveu seis arquivos **byte a byte idênticos** — mesmo sha256.
Não há série patrimonial; quem montasse uma concluiria que o patrimônio não
mudou em cinco anos, achado inteiramente fabricado pela coleta.

**4. O somatório do patrimônio é R$ 32,7 bilhões** — 48× a receita anual. **68
bens (0,1%) respondem por 60% disso**, imóveis e obras avaliados na casa das
centenas de milhões, contra mediana de R$ 7.239. Pode ser critério contábil,
pode ser erro de cadastro. O acervo não escolhe: devolve o total sempre
acompanhado da concentração.

## Os relatórios não têm nome de coluna

Medido nos 115 arquivos coletados: **nenhum traz cabeçalho**, a primeira linha é
dado, e a largura varia dentro do mesmo relatório — a despesa tem 34 colunas em
30.685 linhas e 17 em dez.

Sem cabeçalho, nomear coluna por posição é chute, e chute aqui não produz
lacuna: produz **erro de atribuição**. Uma coluna rotulada "valor" que é outra
coisa sai bem formatada e passa em qualquer conferência de contagem. Por isso a
linha é guardada posicional e sem nome, e o servidor diz isso a quem pergunta.

O que se afirma é o que o formato do conteúdo prova — CNPJ, data, valor, link —
e cada derivado guarda **a posição de onde saiu**, para conferência na linha
crua. Um teste garante que o valor derivado esteja mesmo naquela posição.

Uma armadilha medida: o portal escreve documento dos dois jeitos, `33683111000107`
em contratos e `26.651.036/0001-29` na despesa. Exigir dígitos puros derivava
13.994 documentos em 2,9 milhões de linhas — cego justamente na despesa, que é
onde está o pagamento. Aceitando as duas formas e guardando só os dígitos, são
43.293.

## O que NÃO está aqui

Sete das 37 regras de relatório não respondem sem parâmetro específico e não
foram coletadas. O Diário Oficial é acervo à parte, com servidor próprio
(`diarios-mesquita`).

**O captcha não fecha o financeiro** — ele está na *entrada* do formulário de
Despesas, e a exportação sai por outra rota. Este README afirmou o contrário
até 05/08/2026.

## A lacuna do PNCP, medida contra o Diário

`cruzar_dom.py` confronta o que o Município publicou no seu próprio Diário
Oficial com o que divulgou no PNCP. Dos **42 contratos que declaram a Lei
14.133** entre 2024 e 2026, **15 estão no PNCP e 27 não estão** — lacuna mínima
de 8 (2024), 12 (2025) e 7 (2026).

O bruto (216 contratos e atas no Diário contra 20 no PNCP) **não se sustenta**:
mistura a transição de regime com o dever de divulgar. Em 2024 o Município
assinou 100 contratos sob a Lei 8.666 contra 8 sob a 14.133, e contrato da 8.666
não ia ao PNCP. O regime sai do "FUNDAMENTO LEGAL" do próprio extrato.

Três coisas que o extrator aprendeu apanhando, e que valem para qualquer
cruzamento assim:

- **A conferência de sentido inverso é que acha o erro.** Perguntar "o que está
  no PNCP aparece no Diário?" revelou 7 de 18 faltando — e a causa era o regex
  do número, que não admitia `Nº. 034/2025`. Corrigido, ficou 18 de 18.
- **Abater por subtração de totais desloca a conta.** Dos 20 registros de
  contrato no PNCP, 2 são notas de empenho (art. 95 da 14.133 dispensa o termo)
  e 3 correspondem a contratos que no Diário declaram 8.666 ou nada.
- **O vocabulário do extrato tem 172 formas.** "extrato de contrato" acha 162
  páginas; a dominante é "EXTRATO DE TERMO DE CONTRATO", com 650. E "EXTRATO NO
  DIÁRIO OFICIAL…" é cláusula de dentro do contrato — contá-la exagera a lacuna,
  erro que favorece a conclusão desejada.

## Sobre o PNCP

O Município está cadastrado e validado desde 28/07/2021 e publicou 41 editais e
20 contratos ao todo — a Câmara, 9 editais e 1 ata. É pouco perto do volume do
portal e do Diário no mesmo período, e a divulgação é exigida pela Lei
14.133/2021. **É achado de conformidade, não falha de coleta**, e a ausência de
um contrato lá não prova que ele não exista.

Duas armadilhas de acesso: a API documentada `/api/consulta/v1/` responde 504 de
forma crônica, e a que funciona (`/api/search/`) **ignora o filtro por CNPJ** e
devolve 200 com o Brasil inteiro. O coletor aborta se aparecer órgão de fora.

---

# Acervo de leilões de numismática e filatelia

Segundo acervo deste repositório, independente do financeiro: rastreia o portal
**LeilõesBR** (`leiloesbr.com.br`) e as casas que anunciam nele, identifica a
peça de cada lote e mede a distância entre o lance pedido num lote aberto e o
que peças iguais arremataram no mesmo portal.

    python descobrir_leiloesbr.py                 # mede a estrutura real do portal
    python coletar_leiloesbr.py --abertos         # tudo que está em pregão agora
    python coletar_leiloesbr.py --historico       # os martelos, base de comparação
    python construir_leiloes.py                   # dados_brutos/ → dados/leiloes.db
    python -m pytest tests/test_leiloes.py tests/test_coletor_leiloes.py
    python -m leiloes                             # servidor MCP (stdio)

## O que ele mede, e o que não mede

Mede uma coisa só: **mercado observado**. A referência de preço é o martelo
deste portal — nenhum catálogo foi ingerido, e nenhum preço vem de outra fonte.

Não mede autenticidade, e é bom que fique dito antes de qualquer número: o
acervo lê a descrição que o vendedor escreveu. Peça descrita como genuína e que
não é produz a **melhor** oportunidade da lista, porque o lance está baixo
justamente por isso.

## O risco desta base

No acervo financeiro o risco é a divergência entre fontes. Aqui é a
**identificação**. O lote é descrito em texto livre por quem quer vendê-lo, e
"1000 Réis 1913, prata, Soberba" parece identificação completa e não é: em 1913
foram cunhadas duas séries distintas, com faixas de preço próprias.

Por isso vale aqui a mesma regra do `nivel='indefinido'` do SICONFI: **onde a
descrição não determina a peça, o vínculo não é presumido**. O lote sai em
`identificacao_indefinida`, com o motivo e com os termos que resolveriam a
dúvida, e o motor se recusa a pontuá-lo. Um lote sem nota é recuperável; um lote
com nota errada é o que faz alguém dar lance.

## Quatro armadilhas medidas

**1. O martelo não é o custo.** Quem arremata paga comissão do leiloeiro (5%,
art. 24 do Decreto 21.981/1932, para bens móveis), a taxa administrativa da
casa, frete e seguro. A conta soma tudo em `custo_total_de_arremate` — comparar
lance contra martelo alheio sem isso infla toda margem em dois dígitos.

**2. Estado é produto, não adjetivo.** A mesma moeda em MBC e em FC são
mercadorias distintas. A chave do comparável inclui o estado, e **não há
conversão entre graus** neste acervo: o multiplicador de MBC para FC não é
constante entre peças, e um multiplicador médio faria a nota parecer precisa
exatamente onde seria chute. Selo não usa a escala da moeda — usa o estado da
goma, e medir selo com FC/S/MBC é aplicar a régua de outro mercado.

**3. O lote não vendido é informação, não ausência.** Peça que não arrematou por
R$ 800 diz que o mercado não pagou 800 naquele dia. Sai em `nao_arrematados`,
como teto observado, sem entrar na mediana.

**4. Poucos comparáveis não são comparáveis.** Abaixo de `n_minimo` (5) o acervo
recusa a nota e diz por quê, em vez de devolver mediana de dois martelos com
cara de estatística. A mediana resiste ao martelo fora da curva; a média não.

## Onde mora a assimetria

A margem diz quanto se ganha; `por_que_pode_estar_esquecido` diz por que a
oportunidade ainda estaria de pé às vésperas do pregão — descrição curta, sem
código de catálogo, sem foto, último quarto do pregão, e **grafia divergente**:
o lote escrito "Reís" ou "Cruzeriro" não aparece na busca de ninguém e chega ao
martelo com meia dúzia de olhos em cima. Os dois saem separados de propósito:
misturá-los num número só daria a um palpite sobre visibilidade a mesma
aparência que um martelo observado tem.

A consulta mais útil para caçar peça esquecida é `lotes_para_ler` — os lotes que
a máquina **não** conseguiu classificar são os mesmos que não aparecem em filtro
nenhum do portal.

## A variável que você tem de medir

`fracao_revendedor` é o que o seu comprador paga sobre o preço de mercado. O
padrão de 0,50 é chute conservador, ninguém publica esse número, e ele move a
lista inteira: passar de 0,50 para 0,30 costuma zerá-la. Meça a sua contra os
negócios que você de fato fizer.

## Três rotas, três perguntas

O portal tem busca própria sobre os leilões em andamento, e é por ela que se
entra — não leilão por leilão.

| rota | endpoint | responde |
|---|---|---|
| `--abertos` | `busca_andamento.asp` | o que se pode comprar **agora** |
| `--pos` | `buscapos.asp` | o que **não arrematou** e ficou à venda depois |
| `--historico` | `catalogo.asp` → `leilao.asp` | os **martelos**, base da comparação |

Confundi-las é confundir o que se pode comprar com o que já foi vendido: só a
terceira alimenta a mediana, e as duas primeiras alimentam a lista de
oportunidades. O pós-pregão entra na lista junto com os abertos e sai
sinalizado — é peça que o mercado já recusou uma vez, e o vendedor sabe disso.

**A categoria é o nome em hexadecimal cp1252.** Medido nos endereços públicos
do portal: `tp=|43696E656D61|` é "Cinema", e o `ê` de "Memorabilia & Efêmera"
aparece como `EA` — um byte, não os dois do UTF-8. Errar a codificação não dá
erro: devolve busca vazia, que passa por "não há peça nesta categoria".

E o nome tem de ser exato. **"Numismática" sozinha NÃO é categoria do portal**
— ele só usa a forma `Numismática - <subcategoria>`, e são oito delas. Os nomes
foram colhidos de endereços públicos indexados do próprio site e conferidos
byte a byte contra o hexadecimal que o portal publica; `descobrir_leiloesbr.py`
relê a lista da página de hoje, que é quem manda.

    python coletar_leiloesbr.py --abertos --segmento numismatica   # as 8 de uma vez
    python coletar_leiloesbr.py --pos --segmento filatelia
    python coletar_leiloesbr.py --abertos --categoria "Numismática - Cédulas Brasileiras"
    python coletar_leiloesbr.py --abertos --segmento numismatica --uf RJ

O volume não é pequeno: um endereço indexado mostrava **4.529 peças** só em
"Numismática - Moedas do Brasil". Por isso a varredura tem teto de páginas — e
por isso ela **avisa em voz alta** quando para no teto sem esgotar o resultado.
Recorte truncado tem a mesma aparência de varredura completa, e é assim que se
conclui coisa errada sobre o mercado.

## Coleta

Lenta de propósito: 2,5 s entre requisições (`LEILOES_ESPERA`), User-Agent
identificável com contato (`LEILOES_CONTATO`) e `robots.txt` conferido antes de
varrer. Não é escrúpulo — é a diferença entre ter e não ter o acervo no mês que
vem.

A paginação tem duas paradas, e a segunda é a que importa: ASP costuma
**grampear** o número de página ao máximo existente em vez de devolver vazio.
Sem a guarda que detecta página repetida, a varredura bate na última página até
o teto parecendo que está coletando.

A extração é por **rótulo visível** ("Lance inicial:", "Arrematado por:"), não
por seletor de HTML: site ASP dessa geração reescreve a marcação sem aviso, e
seletor posicional quebra calado. E `coletar_leiloesbr.py` aborta quando mais de
60% dos lotes saem sem preço — isso não é catálogo pobre, é padrão que não casa,
e coleta que grava lixo é pior que coleta que falha.

> **Estado dos padrões de extração.** Foram escritos **sem acesso ao portal** —
> o ambiente onde nasceram tem a saída de rede bloqueada para `leiloesbr.com.br`.
> São hipótese sobre a marcação, não medição dela. Rode
> `descobrir_leiloesbr.py` numa máquina que alcance o portal **antes** da
> primeira varredura: ele diz, padrão por padrão, qual casou e qual não.
