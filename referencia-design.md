# Referência de design do painel

Estrutura de telas observada na ViceScale (vídeo "Como funciona a ViceScale", capturas na pasta `referencia/`). Serve de **referência de organização e fluxo** para o nosso painel.

**Regra:** copiar a lógica das telas, não a marca. Nome, logotipo, cores e textos do nosso painel são próprios. Isso importa ainda mais porque a ferramenta será vendida depois.

## 1. Esqueleto geral (todas as telas)

- **Barra lateral fixa à esquerda**, estreita, com logotipo no topo e os itens de menu em lista, cada um com ícone e nome. O item ativo fica com fundo destacado.
- **Rodapé da barra lateral:** um cartão de destaque e o item Configurações.
- **Barra superior:** campo de busca ("Buscar projetos, clipes, templates…") à esquerda e ícones de conta à direita.
- **Área de conteúdo:** fundo cinza bem claro, com cartões brancos de cantos arredondados.
- **Cabeçalho de cada tela:** um cartão com ícone, título, uma linha de descrição e, à direita, o botão principal da tela.
- **Estilo:** tema claro, uma única cor de destaque usada em botões principais, etapa ativa e controles; bastante espaço em branco.

## 2. Menu

| ViceScale | Nosso painel | Função |
|---|---|---|
| — | **Hoje** | Ranking do dia da busca das 6h (views, horas desde a postagem, velocidade) |
| — | **Cortes** | Colar link, fila de processamento e revisão dos cortes da IA |
| Templates | **Templates** | Projetos de vídeo em massa (assistente de 7 passos) |
| ViceScrap | **Perfis** | Analisar um perfil ou canal e baixar os posts mais vistos |
| Editor | **Editor** | Ajuste rápido de um vídeo para o formato vertical |
| — | **Agenda** | Calendário do que está agendado em cada conta |
| Integrações | **Contas** | Conectar Instagram, TikTok, YouTube e Facebook |
| Configurações | **Configurações** | Voz, ritmo de postagem, chaves, modo automático |

Ficam de fora: Pack Viral, Comunidade e cupons (são itens de produto vendido, entram só quando houver venda).

## 3. Tela Templates (lista) — `01-templates-lista.png`

- Grade de 6 colunas com cartões verticais (proporção 9:16), cada um com a miniatura do vídeo.
- Selo de estado no canto do cartão: **Rascunho**, **Pronto** ou **Falhou**.
- Embaixo de cada cartão: nome do projeto, data e um botão de ação.
- Botão principal no cabeçalho: **Novo template**.

## 4. Tela Perfis (analisador) — `02-analisador-de-perfil.png`

- Campo para colar o @ ou o link do perfil + botão **Buscar perfil**.
- Filtros em forma de botões: mais curtidos, mais comentados, mais visualizações, mais recentes.
- Grade de 6 colunas com os posts: miniatura, visualizações sobre a imagem, curtidas e comentários embaixo, link "Ver post".
- Caixa de seleção em cada post; contador de selecionados, **Limpar** e **Baixar selecionados** no topo.
- No nosso painel, acrescentar o filtro **velocidade** (views por hora) e um botão **Enviar para Cortes**.

## 5. Escolha do modelo — `03-escolha-do-template.png`

Janela sobreposta com três modelos lado a lado, cada um com prévia e botão "Usar este template":

1. **Estilo post de rede social:** foto e nome da página no topo, frase, vídeo embaixo.
2. **Estilo meme/notícia:** frase no topo, vídeo no meio, foto e nome da página no rodapé.
3. **Vídeo viral (tela dividida):** vídeo em cima, frase no meio, imagem embaixo (ou o inverso).

## 6. Assistente de 7 passos

Barra de etapas no topo (a etapa ativa fica destacada), formulário à esquerda, **prévia ao vivo em formato de celular à direita**, botão **Continuar** no canto superior direito.

| Passo | O que tem | Captura |
|---|---|---|
| 1. Perfil | Foto, nome e @ da página; alinhamento do texto; tema claro ou escuro; posição do perfil; "perfil salvo" para reutilizar; controles deslizantes de tamanho de avatar, fontes, tamanho da frase e espaçamentos | `04-passo-perfil.png` |
| 2. Zonas | Divisão do quadro e predefinições, entre elas o fundo desfocado | — |
| 3. Frases | Frase base + quantidade de sugestões + **Gerar** (IA); cada sugestão tem botão "Usar" e há "Adicionar todas"; campo para escrever frase à mão; painel "Frases do projeto" | `05-passo-frases.png` |
| 4. Mídia | Enviar vários vídeos; lista dos vídeos; para o selecionado, controles de zoom, posição horizontal e vertical | `06-passo-midia.png` |
| 5. Estilo | Estilo e cor do texto, tamanho da frase, espaçamento lateral e altura da faixa | — |
| 6. Variações | Miniaturas dos vídeos com caixa de seleção; frases com caixa de seleção; contador "N variações serão geradas" (vídeos × frases) | `07-passo-variacoes.png` |
| 7. Gerar | Barra de progresso "Renderizando… 22/50"; grade de 6 colunas com player de cada vídeo e botão **Baixar**; no topo, **Publicar tudo** e **Baixar tudo** | `08-resultado-renderizando.png` |

O passo 1 da ViceScale tem um interruptor de selo "verificado". **Não incluir**: é exibir uma verificação que a página não tem.

## 7. Publicar e agendar — `09-publicar-agendar.png`

Janela pequena sobreposta: título com a rede, campo de legenda com botão **Gerar com IA**, interruptor **Agendar publicação**, campo de data e hora, botões **Cancelar** e **Agendar**.

No "Publicar tudo", acrescentar: quantos posts por dia e em quais contas.

## 8. O que o nosso painel tem a mais

- Tela **Hoje** com o ranking por velocidade.
- Tela **Cortes**: para cada corte da IA, player, nota, motivo da escolha, modo (`original` ou `narrado`), e botões aprovar, descartar e refazer narração.
- Um corte aprovado pode ser enviado direto para o passo 4 (Mídia) de um template.
