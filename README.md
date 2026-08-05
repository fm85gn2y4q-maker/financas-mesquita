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
| `siconfi_linha` | 126.466 | SICONFI/Tesouro | RREO, RGF e DCA, 2013-2026 |
| `patrimonio_bem` | 69.792 | API do portal | fotografia única |
| `portal_tela` | 1.375 | API do portal | mapa de 883 telas |
| `pncp_documento` | 71 | PNCP | 50 editais, 20 contratos, 1 ata |
| `obra` | 46 | API do portal | 2021-2025 |

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

**4. O somatório do patrimônio é R$ 32,7 bilhões** — 48× a receita anual. 1.041
bens (1,5%) carregam 96% disso, imóveis e obras avaliados em centenas de
milhões, contra mediana de R$ 7.239. Pode ser critério contábil, pode ser erro
de cadastro. O acervo não escolhe: devolve o total sempre acompanhado da
concentração.

## O que NÃO está aqui

Despesa nota a nota, receita detalhada, folha nominal e contratos com fiscais
**não foram coletados**. Estão no Portal da Transparência, em telas Softwell
Maker com CAPTCHA na entrada — que não se contorna. As duas vias legítimas:

1. A própria tela oferece exportação "Dados Abertos" em CSV, XLS e ODS.
2. A regra do captcha desvia quando o parâmetro `API` não é nulo: existe modo
   API para essas telas, e a chave se pede à Subsecretaria de Tecnologia da
   Informação, ou pelo e-SIC.

O Diário Oficial é acervo à parte, com servidor próprio (`diarios-mesquita`).

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
