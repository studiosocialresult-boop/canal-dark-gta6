# Desempenho — desenho (Fase 8)

Aprovado pelo dono em 14/11/2026. O passo a passo da construção fica em `docs/superpowers/plans/`.

## Para que serve

O painel já acha vídeo, corta, narra e publica, mas não olha o que acontece depois do post. O dono não sabe quais cortes renderam e quais morreram, e escolhe no escuro. Esta fase faz o painel buscar os números de cada post nas redes e mostrar, em linguagem simples, o que está funcionando.

## Objetivos

- Guardar visualizações, curtidas e comentários de cada post publicado, sozinho, sem o dono fazer nada.
- Uma tela **Desempenho** que responde a três perguntas: quanto o canal rendeu no período, que tipo de post rende mais, quais posts foram os melhores e os piores.
- Na tela **Cortes**, cada corte já publicado mostra quantas visualizações teve.
- Guardar os dados de um jeito que sirva depois para a IA aprender (ideia futura).

## Fora desta fase

- A IA usar os números para dar nota aos cortes.
- O agendador escolher horário sozinho com base nos números.
- TikTok (ver "Redes").
- Retenção, tempo assistido e crescimento de seguidores.

## O que seria um fracasso, mesmo funcionando

- **Atrapalhar a postagem.** A leitura dos números roda separada do publicador. Uma falha na leitura nunca muda o estado de um post nem impede o próximo de sair.
- **Gastar créditos de IA.** Esta fase não chama IA nenhuma.
- **Mostrar conclusão sem base.** Média de um grupo com menos de 3 posts aparece como "poucos dados", não como número.
- **Pedir permissão nova sem o dono saber.** Nenhuma permissão é acrescentada ao login das redes nesta fase sem um passo a passo dado a ele.

## Caminhos considerados

1. **Em camadas, começando pelo YouTube (escolhido).** O YouTube já deixa ler tudo com a permissão atual. Instagram e Facebook entram com o que a permissão atual deixa ler; visualizações deles entram quando o dono acrescentar a permissão. TikTok fica para depois da auditoria. Vantagem: o histórico começa a ser guardado já.
2. **Esperar e fazer as quatro redes de uma vez.** Exige mexer no cadastro da Meta e do TikTok antes de mostrar qualquer coisa, e mexer no app do TikTok com a auditoria em análise pode atrasá-la. Perde semanas de histórico.
3. **O dono digitar os números à mão.** Não se sustenta com 10 a 20 posts por dia.

## Redes

| Rede | Com a permissão de hoje | Para ter o resto |
|---|---|---|
| YouTube | Visualizações, curtidas, comentários (`youtube.readonly` já é pedido no login) | Nada |
| Instagram | Curtidas e comentários (`instagram_basic`) | Visualizações: permissão de estatísticas na configuração de login da Meta; o dono reconecta a conta |
| Facebook | Curtidas e comentários (`pages_read_engagement`) | Visualizações: permissão de estatísticas da Página; mesma reconexão |
| TikTok | Nada (`user.info.basic`, `video.publish`) | Permissão de listar vídeos. Só depois da auditoria sair |

Quem construir **confere na documentação oficial**, na hora, os nomes exatos das permissões e dos campos da Meta, e anota no `plano.md` (como foi feito na Fase 5). Quando a rede não deixa ler um número, ele fica vazio (não zero), e a tela diz "esta rede ainda não informa".

## Como funciona

**Leitura.** Uma rotina dentro do painel (como o publicador e a busca diária) roda de hora em hora. Ela pega os posts publicados há menos de 7 dias (com folga) e pergunta os números às redes, em lotes (uma chamada para vários posts). Não roda no painel de testes.

**O que é guardado.** Para cada post, até quatro leituras:

- `atual`: a mais recente, regravada a cada rodada.
- `24h`, `3d`, `7d`: uma "foto" tirada na primeira rodada depois que o post completa essa idade. Não muda depois.

As fotos existem para comparar posts de idades diferentes de forma justa: um post de ontem e um do mês passado são comparados pelo que cada um tinha com 24 horas.

Depois de 7 dias o post para de ser lido. *(Decisão do Claude: mantém as chamadas às redes pequenas; se o dono quiser ver números de posts antigos crescendo, é um ajuste simples.)*

**Falhas.** Rede fora do ar: tenta na rodada seguinte. Acesso vencido: marca a conta para reconectar e avisa, do mesmo jeito que o publicador faz hoje. Post que a rede não devolve mais (apagado ou removido): marcado como "removido" e não é mais lido.

**Tela Desempenho** (menu, depois de Agenda):

```
Desempenho          [7 dias | 30 dias | 90 dias]   [Todas as contas]
                    [Visualizações | Curtidas | Comentários]

 Visualizações    Curtidas    Comentários    Posts    Melhor horário
    48.200          3.100         212          41       19h às 21h
    ▲ 32% sobre o período anterior

 O que está funcionando (média por post, com 24 h de vida)
   Modo:     narrado 6.400      original 2.100
   Nota:     80 ou mais 7.900   70 a 79 3.000   abaixo de 70 (poucos dados)
   Rede:     YouTube 5.100      Instagram —     Facebook —
   Fonte:    Canal X 9.200      Canal Y 1.800
   Tipo:     corte 4.900        template 3.300
   Horário:  barras por hora do dia

 Melhores posts                         24 h      3 dias     7 dias
   1. Mapa vazado mostra...  YouTube     12.400    18.900     21.000
 Posts que não renderam
   1. ...
```

- Os totais do topo usam a leitura `atual`. As comparações de "o que está funcionando" usam a foto de `24h`.
- O seletor Visualizações / Curtidas / Comentários troca a medida da tela inteira. Em Visualizações, as redes que ainda não informam ficam de fora, com um aviso.
- Cada post da lista abre o link dele na rede e mostra o corte de origem.
- Sem nenhum post lido ainda, a tela explica que os primeiros números aparecem cerca de uma hora depois do primeiro post.

**Tela Cortes.** O cartão de um corte publicado ganha o total de visualizações (soma das leituras `atual` de todos os posts daquele corte, inclusive os que saíram por Templates).

## Decisões do Claude (o dono não pediu; pode corrigir)

- Leitura de hora em hora, e a leitura `atual` além das três fotos, para a tela não ficar vazia nas primeiras 24 horas.
- Mínimo de 3 posts para mostrar média de um grupo.
- Seletor de medida, porque Instagram e Facebook começam sem visualizações.
- Código novo em `app/desempenho/` (`coletor.py`, `relatorio.py`), com a leitura de cada rede ao lado do conector dela em `app/postagem/` (`ler_numeros` em `youtube.py` e `meta.py`). Tela em `app/painel/api_desempenho.py`, `paginas/desempenho.html`, `estatico/desempenho.js`.
- Tabela nova `leituras` (com `usuario_id`), ligada a `publicacoes`.

## Deixado para quem construir

- Nomes exatos de campos e permissões da Meta, e o tamanho dos lotes de cada rede.
- Desenho fino da tela, seguindo o padrão visual das telas existentes e `referencia-design.md`.
- Como o gráfico de horário é desenhado (sem bibliotecas externas, como o resto do painel).

## Pronto quando

Com posts reais publicados pela VPS: os números do YouTube aparecem na tela Desempenho em até uma hora, a foto de 24 h é guardada no dia seguinte, e o total aparece no cartão do corte na tela Cortes. Uma falha simulada na leitura não altera nenhum post agendado.

## Modelo por etapa

| Etapa | Modelo | Esforço |
|---|---|---|
| Leitura dos números nas redes (YouTube, Meta) e a rotina | Opus 5.5 | high |
| Banco, relatório e tela | Sonnet 5.5 | medium |
