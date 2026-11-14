# Plano — Canal Dark GTA 6 (ferramenta de cortes automáticos)

> Documento de planejamento. O Claude Code deve ler este arquivo e o `CLAUDE.md` antes de escrever qualquer código, e construir **uma fase por vez**.

## 1. O que é

Uma ferramenta própria que recebe o link de um vídeo (YouTube, Instagram, TikTok ou live já encerrada), encontra os melhores momentos com IA, gera cortes verticais com legenda e narração, cria variações e publica sozinha nas redes. No final, roda todo dia às 6h numa VPS sem intervenção.

Referências de mercado: ViceScale (multiplicador, templates, agendamento), OpusClip e Vizard (link → cortes com IA).

## 1.1 Decisões já tomadas

| Tema | Decisão | O que muda no projeto |
|---|---|---|
| Uso | Só para o dono agora, vender acesso depois | Sem login nem cobrança por enquanto, mas toda tabela do banco já nasce com a coluna `usuario_id` e as configurações (contas, voz, ritmo de postagem) ficam por usuário, não fixas no código. Assim, virar produto depois não exige reescrever. |
| Idioma | Só português | Vídeos em inglês são transcritos em inglês e o cérebro escreve legenda e narração em português do Brasil. |
| Narração | A IA decide por corte | O cérebro classifica cada corte em um de dois modos: `original` (momento engraçado ou de reação: mantém o áudio original, com no máximo um gancho narrado na abertura) ou `narrado` (notícia, detalhe, explicação: narração completa e áudio original baixo ou mudo). |
| Volume | 10 a 20 cortes por dia | Uma ou duas contas por rede. O agendador distribui os posts ao longo do dia. A fila processa um vídeo por vez para caber numa VPS média. |

## 1.2 Riscos conhecidos (revisão do plano em 11/11/2026)

| Risco | Como o projeto lida |
|---|---|
| **Direitos autorais.** Repostar trechos de outros criadores pode gerar reivindicação, strike ou canal sem monetização por "conteúdo reutilizado", mesmo sem burlar nada. | Todo corte guarda a fonte (link, canal e título do vídeo original). A descrição do post credita a fonte. O cérebro favorece o modo `narrado`, que agrega comentário próprio. Continua proibido qualquer truque para escapar da detecção (seção 9). |
| **YouTube bloqueia download vindo de servidor.** O yt-dlp pode funcionar no computador de casa e falhar na VPS. | Testar o download numa VPS barata já na Fase 1. Se falhar, decidir cedo entre manter o download no computador de casa ou outra saída. |
| **Auditoria das plataformas.** YouTube e TikTok limitam apps novos (posts ficam privados, cota baixa) até aprovarem o app. | Cadastros na Fase 1, pedido de auditoria o mais cedo possível. Detalhes na Fase 5. |
| **Variações parecerem spam.** Várias versões do mesmo corte na mesma conta derrubam o alcance. | Regra do agendador: o mesmo corte nunca vai duas vezes para a mesma conta (Fase 4 e Fase 5). |

## 2. Fluxo completo

```
[Busca diária 6h]  ou  [Link colado no painel]
          │
          ▼
   1. Download do vídeo
          ▼
   2. Transcrição (áudio → texto com tempos)
          ▼
   3. Cérebro: IA escolhe os melhores momentos e dá nota a cada um
          ▼
   4. Corte vertical 9:16 + legenda animada
          ▼
   5. Roteiro + narração (ElevenLabs) mixada no corte  ← só cortes com nota acima do mínimo
          ▼
   6. Multiplicador: variações de headline e template
          ▼
   7. Fila de revisão (aprovar / descartar)  ← pode ser desligada depois
          ▼
   8. Agendamento e postagem: Shorts, Reels, TikTok, Facebook
```

**Narração sem desperdício:** a ElevenLabs cobra por caractere, então a narração só é gerada automaticamente para cortes com nota igual ou acima do mínimo (padrão 70, configurável por usuário). Cortes abaixo disso aparecem na revisão sem narração e podem ser narrados com um clique.

## 3. Módulos

| Módulo | O que faz | Ferramenta principal |
|---|---|---|
| `busca` | Acha vídeos de GTA 6 em alta no Brasil e fora; lê lista de canais/perfis monitorados | YouTube Data API |
| `download` | Baixa o vídeo a partir de um link | yt-dlp |
| `transcricao` | Gera o texto com marcação de tempo palavra a palavra | faster-whisper (local) |
| `cerebro` | Lê a transcrição, escolhe os trechos, dá nota e justificativa, sugere título | API da Anthropic |
| `edicao` | Corta, converte para 9:16, queima legenda, aplica template | ffmpeg |
| `narracao` | Escreve o roteiro e gera a voz; baixa o áudio original durante a fala | API da Anthropic + ElevenLabs |
| `multiplicador` | Gera N versões do mesmo corte com headlines e templates diferentes | ffmpeg + API da Anthropic |
| `postagem` | Publica e agenda nas redes, espaçando os posts | APIs oficiais das plataformas |
| `painel` | Site local: colar link, acompanhar a fila, revisar e aprovar cortes | FastAPI + HTML simples |
| `agendador` | Dispara a rotina diária | APScheduler (local) / cron (VPS) |

## 4. Stack

- **Linguagem:** Python 3.12
- **Vídeo:** ffmpeg + yt-dlp
- **Banco de dados:** SQLite (um arquivo só, sem servidor)
- **Painel:** FastAPI servindo páginas HTML simples
- **IA:** API da Anthropic — `claude-sonnet-5-5` no cérebro e no roteiro, `claude-haiku-5-5` em títulos, legendas e hashtags
- **Voz:** ElevenLabs
- **Ambiente:** Windows agora (desenvolvimento), Linux depois (VPS). Todo caminho de arquivo usa `pathlib`, nada fixo no código.

## 5. Estrutura de pastas

```
CANAL DARK GTA 6 - OFICIAL/
├── CLAUDE.md
├── plano.md
├── referencia-design.md ← como as telas do painel devem ser organizadas
├── referencia/          ← capturas de tela usadas como referência
├── .env                 ← chaves secretas (nunca vai para o git)
├── .env.example
├── .gitignore           ← mantém .env, .venv/ e dados/ fora do git
├── .venv/               ← ambiente isolado do Python (não vai para o git)
├── requirements.txt
├── app/
│   ├── busca/
│   ├── download/
│   ├── transcricao/
│   ├── cerebro/
│   ├── edicao/
│   ├── narracao/
│   ├── multiplicador/
│   ├── postagem/
│   ├── painel/
│   └── pipeline.py      ← liga todos os módulos em sequência
├── prompts/             ← textos dos prompts do cérebro e do roteiro
├── templates/           ← layouts de vídeo
├── dados/
│   ├── brutos/          ← vídeos baixados
│   ├── cortes/          ← cortes prontos
│   └── canal.db         ← banco SQLite
└── testes/
```

## 6. Fases de construção

Cada fase só começa quando a anterior passa no critério de "pronto".

### Modelo e esforço por etapa

O esforço é quanto o modelo "pensa" antes de agir. Mais esforço = mais cuidadoso, porém mais lento e mais caro. Troque em `/model` (setas para os lados) ou com `/effort <nivel>`.

| Etapa | Modelo | Esforço |
|---|---|---|
| Primeira conversa: revisar o plano | Fable 5.2 | high |
| Fase 0 — Preparação | Sonnet 5.5 | low |
| Fase 1 — arquitetura do pipeline e prompt do cérebro | Fable 5.2 | high |
| Fase 1 — corte e enquadramento com ffmpeg | Opus 5.5 | high |
| Fase 1 — download, transcrição e o restante | Sonnet 5.5 | medium |
| Fase 2 — prompt do roteiro da narração | Fable 5.2 | high |
| Fase 2 — integração com a ElevenLabs e mixagem | Sonnet 5.5 | medium |
| Fase 3 — Painel | Sonnet 5.5 | medium |
| Fase 4 — Templates, multiplicador e Perfis | Sonnet 5.5 | medium |
| Fase 4 — se a renderização no ffmpeg travar | Opus 5.5 | high |
| Fase 5 — Postagem e agendamento | Opus 5.5 | high |
| Fase 6 — Busca diária | Sonnet 5.5 | medium |
| Fase 7 — Deploy na VPS | Opus 5.5 | high |
| Fase 7 — Revisão final de segurança e do código | Fable 5.2 | xhigh |
| Qualquer fase — bug que não saiu em duas tentativas | Opus 5.5 | xhigh |
| Qualquer fase — ajuste pequeno (texto, cor, nome) | Sonnet 5.5 | low |

Evitar `max`: custa muito e costuma pensar demais.

### Fase 0 — Preparação
- Instalar Python, ffmpeg e dependências; criar a estrutura de pastas, `.env.example` e `requirements.txt`.
- Situação do computador em 11/11/2026: ffmpeg e Git já instalados; Python instalado é o 3.14; yt-dlp falta.
- Instalar o **Python 3.12 ao lado do 3.14** (os dois convivem) e criar o ambiente isolado `.venv` com o 3.12. Motivo: a biblioteca de transcrição pode não funcionar no 3.14, e a VPS usará o 3.12.
- Conferir na instalação se o yt-dlp pede algum programa auxiliar para o YouTube e instalar junto, se for o caso.
- Iniciar o git na pasta, com `.gitignore` protegendo `.env`, `.venv/` e `dados/`.
- **Pronto quando:** um comando de verificação confirma que Python 3.12, ffmpeg e yt-dlp respondem.
- **Modelo no Claude Code:** Sonnet 5.5

### Fase 1 — Link → cortes (o núcleo)
- Colar um link do YouTube no terminal e receber de 3 a 5 cortes `.mp4` verticais com legenda.
- Inclui: download, transcrição, cérebro e edição básica.
- O prompt do cérebro fica em `prompts/cerebro.md` e devolve JSON: início, fim, nota de 0 a 100, motivo, título sugerido e modo de narração (`original` ou `narrado`).
- Vídeo em inglês: legenda traduzida para português do Brasil. Como a tradução não tem o tempo de cada palavra, a legenda traduzida é sincronizada **por frase** (o tempo da frase original é repartido entre as palavras em português). Vídeo já em português usa o tempo palavra a palavra.
- Todo corte guarda no banco a **fonte**: link, canal e título do vídeo original.
- Enquadramento vertical inicial: vídeo centralizado com fundo desfocado. Detecção de câmera do streamer fica para depois.
- **Teste antecipado de VPS:** assim que o download funcionar no computador, repetir o mesmo download numa VPS barata para saber se o YouTube bloqueia. O resultado define como será a Fase 7.
  - **Resultado (13/11/2026, Oracle Cloud São Paulo):** sem login, o YouTube bloqueia ("confirme que não é robô"). Com o `cookies.txt` da conta secundária, baixou normalmente, inclusive vídeo com restrição de idade (11 min em 8 s; 56 min em 50 s). Precisa do Deno e do `yt-dlp-ejs` instalados. Os cookies vencem se o perfil do navegador continuar em uso: exportar de um perfil separado do Chrome e fechar a janela logo depois.
- **Pronto quando:** 3 links diferentes geram cortes que começam e terminam em frases completas, com legenda sincronizada.
- **Modelo:** **Fable 5.2** para desenhar o prompt do cérebro e a arquitetura do pipeline; **Opus 5.5** para o ffmpeg; Sonnet 5.5 no restante.

### Fase 2 — Narração
- O roteiro segue o modo escolhido pelo cérebro: no modo `original`, só um gancho curto na abertura; no modo `narrado`, narração do começo ao fim.
- ElevenLabs gera a voz em português; o áudio original abaixa automaticamente enquanto a narração fala.
- A narração só é gerada sozinha para cortes com nota igual ou acima do mínimo (padrão 70). Os demais ficam sem narração até alguém pedir.
- **Como o roteiro funciona (decidido em 13/11/2026):**
  - O roteiro é uma lista de **blocos**. Cada bloco é ancorado em uma frase do corte: a voz começa quando aquela frase começa no vídeo. Isso mantém a narração junto com a imagem. O validador confere se o texto de cada bloco cabe no tempo até o bloco seguinte (ritmo em `app/config.py`, a calibrar com a voz real).
  - Modo `narrado`: o áudio original fica baixo o corte inteiro (não sobe entre um bloco e outro) e a legenda mostra o **texto da narração**, sincronizada pelos tempos que a ElevenLabs devolve. Por isso o corte narrado é renderizado depois que a voz fica pronta.
  - Modo `original`: o gancho toca nos segundos **imediatamente antes** do corte. O vídeo começa um pouco antes (o tempo do gancho), com o áudio original baixo, e sobe quando a pessoa começa a falar. Se o corte começa no início do vídeo, segura o primeiro quadro. A IA pode devolver "sem gancho" quando a primeira fala já prende sozinha.
  - Se a voz de um bloco passar da janela, o bloco seguinte começa logo depois (nunca um por cima do outro).
  - O roteiro fica na tabela `narracoes` (estado `roteirizado` → `narrado`). Ponto de entrada: `app/narracao/roteiro.py`, função `roteirizar_corte`.
  - **Voz (13/11/2026):** ElevenLabs, modelo `eleven_multilingual_v2`. Voz provisória: **George** (pronta, em inglês, fala português com leve sotaque), escolhida pelo dono entre as amostras do plano grátis. As vozes em português da conta (Mário, Bianca, Carla) são da biblioteca e **exigem plano pago**; o plano grátis também não permite uso comercial. Trocar a voz é só mudar `ELEVENLABS_VOICE_ID` no `.env`.
  - **Calibragem real:** a voz fala ~13,8 caracteres por segundo, bem perto dos 14 usados no cálculo do roteiro. Custo estimado da voz: ~US$ 0,10 por corte narrado de 570 caracteres (preço do plano Starter, a confirmar).
  - **Pipeline:** `roteiro → voz → edição`. Roteiro e voz que falham não derrubam o vídeo: o corte sai sem narração. `pipeline.renderizar_corte(id)` refaz o mp4 de um corte depois que a narração fica pronta (usado pelo botão "narrar" do painel).
- **Pronto quando:** um corte de cada modo sai com a narração sincronizada e o áudio original no volume certo. *(Testado em 13/11/2026 com os cortes 1 e 3; falta o dono ouvir e aprovar o volume.)*
- **Modelo:** Fable 5.2 para o prompt do roteiro; Sonnet 5.5 para a integração.

### Fase 3 — Painel
- Página local para colar link, ver a fila de processamento, assistir aos cortes e aprovar ou descartar.
- **Layout:** seguir `referencia-design.md` e as capturas em `referencia/` (barra lateral, busca no topo, cartões, grade de 6 colunas). A organização das telas vem da ViceScale; nome, logotipo e cores são próprios.
- Nesta fase entram o esqueleto do painel e a tela **Cortes**. As demais telas do menu aparecem conforme as fases seguintes.
- Telas por fase: **Cortes** (Fase 3); **Templates**, **Perfis** e **Editor** (Fase 4); **Contas** e **Agenda** (Fase 5); **Hoje** (Fase 6). **Configurações** nasce na Fase 3 e cresce a cada fase.
- Na tela Cortes, cada corte mostra a fonte e tem o botão para narrar os que ficaram abaixo da nota mínima.
- **Como ficou (13/11/2026):** painel em FastAPI + HTML/CSS/JS puros (sem bibliotecas externas, funciona offline). Liga com `iniciar_painel.bat` (ou `python -m app.painel`) em http://127.0.0.1:8000. Marca própria "Canal Dark", tema claro e escuro automático.
  - **Além da referência:** números do dia (para revisar, aprovados, criados hoje, custo por corte) e gasto com IA na barra lateral; revisão por teclado (`A` aprova, `D` descarta, setas navegam, `/` busca, `N` novo corte, `F` fila); desfazer após aprovar/descartar; seleção em massa; prévia em movimento ao passar o mouse; fila ao vivo numa gaveta lateral com andamento e aviso ao terminar; filtros por modo e ordenação; botão de copiar o crédito da fonte; estado do sistema (chaves, ffmpeg, Deno, cookies) nas Configurações; funciona também em tela estreita.
  - **Fila de trabalho:** tabela `fila` no banco; um item por vez (link ou narração). Se o painel for desligado no meio, o item volta para a fila e continua de onde parou.
  - **Antes da VPS (Fase 7):** o painel não tem login e escuta só neste computador. Na VPS precisa de proteção de acesso (senha ou acesso só pela rede privada) antes de ficar acessível pela internet.
- **Pronto quando:** dá para fazer o fluxo inteiro sem abrir o terminal. *(Falta o dono colar um link novo no painel e acompanhar até os cortes aparecerem.)*
- **Modelo:** Sonnet 5.5

### Fase 4 — Multiplicador e templates
- Tela **Templates** com o assistente de 7 passos descrito em `referencia-design.md`: perfil da página, zonas, frases, mídia, estilo, variações e geração.
- Três modelos de layout: estilo post de rede social, estilo meme/notícia e tela dividida. Fundo desfocado como predefinição.
- Perfil da página (foto, nome, @) configurado uma vez e salvo para reutilizar. Sem selo de verificado.
- Frases: o dono escreve uma frase base e a IA gera N variações.
- **Cruzamento vídeos × frases:** 10 vídeos e 5 frases geram 50 vídeos, com contador antes de gerar e barra de progresso durante.
- Os vídeos podem vir de cortes aprovados, de upload ou da tela Perfis.
- **Regra contra repetição:** as variações de um mesmo corte são distribuídas entre contas e redes diferentes. O mesmo corte nunca é publicado duas vezes na mesma conta, mesmo com frase ou layout diferente.
- Tela **Editor:** ajuste rápido de um vídeo para o formato vertical (zoom e posição), reaproveitando os controles do passo 4 (Mídia).
- Tela **Perfis** (analisador): colar @ ou link, listar os posts com filtros (mais vistos, mais curtidos, mais comentados, mais recentes, velocidade), selecionar e baixar em lote. YouTube pela API oficial. Instagram e TikTok dependem de coleta não oficial, que é instável: implementar por último, isolada num módulo que pode ser trocado.
- **Pronto quando:** 3 vídeos e 3 frases geram 9 vídeos corretos, com a prévia ao vivo batendo com o resultado.
- **Modelo:** Sonnet 5.5; Opus 5.5 se o ffmpeg complicar.
- **Andamento (13/11/2026) — parte A, Templates: construída.**
  - Pronto: tela Templates (lista com capa, estado e contadores) e o assistente de 7 passos com **prévia ao vivo desenhada pelo servidor** (mesmo código do vídeo final, então "o que você vê é o que sai"). Layouts post, meme e viral; perfil com foto, tema, alinhamento e tamanhos; perfis salvos; frases escritas ou geradas pela IA (Haiku, `prompts/frases_variacoes.md`); vídeos vindos de cortes (trecho do original, sem legenda) ou enviados do computador, com zoom e posição; estilo do texto; seleção de variações com contador; geração em lote pela fila (um vídeo por vez, progresso `N/M`) e download individual ou de todos.
  - Código: `app/multiplicador/` (`modelos`, `cartao` com Pillow, `renderizar` com ffmpeg, `frases`, `lote`, `repositorio`) e `app/painel/api_templates.py`. Tabelas novas: `templates`, `template_midias`, `template_frases`, `template_saidas`, `perfis_pagina`; a fila ganhou o tipo `lote`.
  - Medido: 1 vídeo de 32 s no layout post leva cerca de 12 s para renderizar neste computador (50 variações de vídeos curtos: uns 10 a 15 minutos).
- **Andamento (13/11/2026) — parte B: construída.**
  - **Perfis:** colar @ ou link de canal do YouTube; abas Vídeos e Shorts; ordenar por mais vistos, mais recentes ou **velocidade** (visualizações por hora); selecionar vários e **Enviar para Cortes** (fila de processamento) ou **Baixar vídeos** (vão para a biblioteca, usada em Templates e no Editor). Sem chave de API: lista com yt-dlp (`app/busca/perfil.py`) e lê a data na página dos 15 vídeos mais recentes (o feed público do YouTube deu 404, então não é usado). Curtidas e comentários não aparecem (a listagem rápida não traz). Instagram e TikTok: não implementados (coleta não oficial, instável); entram como módulos ao lado deste.
  - **Editor:** ajuste rápido para tela cheia 9:16 (zoom, posição, "caber inteiro" com fundo desfocado ou preto), com prévia ao vivo e download. Usa o mesmo motor dos Templates (layout oculto `cheio`; os ajustes ficam separados da lista de Templates).
  - **Baixar tudo (.zip)** nos Templates; **biblioteca** de vídeos baixados (`dados/biblioteca/`, tabela `biblioteca`).
  - Banco: `fila` e `templates` perderam a trava de tipos/layouts fixos (migração automática e testada, sem perder dados). Fila ganhou o tipo `baixar`.
  - **Regra contra repetição:** continua para a Fase 5, junto com o agendador (é ele que distribui os vídeos entre contas).
  - **Fase 4 fechada**, faltando só o dono montar e gerar um template de verdade (3 vídeos × 3 frases = 9) para o critério de "pronto".

### Fase 5 — Postagem e agendamento
- Ordem: YouTube Shorts primeiro (API mais simples), depois Instagram Reels, Facebook e TikTok.
- Agendador espaça os posts no ritmo configurado por conta.
- Modo padrão: **só posta o que foi aprovado no painel**. Há uma chave para ligar o modo 100% automático.
- **Pronto quando:** um corte aprovado é publicado nas contas conectadas no horário marcado.
- **Modelo:** Opus 5.5 (autenticação e APIs são a parte mais chata).
- A descrição de cada post credita a fonte do vídeo original.
- O agendador aplica a regra contra repetição da Fase 4 e mostra na tela **Agenda** o que vai para cada conta.
- **Atenção:** cada plataforma exige cadastro de aplicativo de desenvolvedor e aprovação. Isso leva dias — começar os cadastros já na Fase 1.
- **Travas conferidas na documentação oficial (13/11/2026):**
  - YouTube: ~~vídeos de app não auditado ficam privados~~ **não ficam mais** (mudança oficial de 02/11/2026). Envio custa 1 unidade da cota "Video Uploads", limite de **100 envios por dia**: cobre o volume. Com o app do Google em "modo de teste", o acesso expira em 7 dias: **publicar o app** no Google Cloud antes da Fase 7.
  - Instagram e Facebook: um login da Meta (Facebook Login para Empresas) conecta a Página e o Instagram profissional ligado a ela; token de Página não expira. Instagram: até 100 posts/24 h (a conta informa o limite real), Reels de 3 s a 15 min, até 300 MB. Facebook Reels: **3 a 90 s**, até 30 posts/24 h.
  - TikTok: sem auditoria, só posta como "Somente eu" e com a conta **privada**; no máximo 5 usuários por dia. As regras exigem que o dono escolha a privacidade (sem padrão), ligue ou não comentários/dueto/costura e confirme cada post, e proíbem marca d'água ou logo no vídeo (atenção aos templates com perfil). Por isso o TikTok **nunca entra no modo automático**. Se a auditoria for negada, fica a postagem manual a partir dos cortes baixados.
- **Andamento (13/11/2026): construída e testada com as redes simuladas.**
  - Telas **Contas** (conectar pelo login oficial de cada rede, ritmo por conta, pausar, desconectar) e **Agenda** (por dia, com editar, publicar agora, cancelar, tentar de novo). Botão **Agendar** nos cortes aprovados, nos vídeos dos Templates (espalhando as variações entre as contas) e no Editor.
  - **Regra contra repetição:** o mesmo conteúdo (`chave_video`, ex.: `corte:12`) nunca vai duas vezes para a mesma conta, com trava no banco; variações de um corte são espalhadas, uma por conta.
  - Legenda escrita pela IA (Haiku, `prompts/legenda_post.md`) com hashtags e **crédito da fonte** acrescentado pelo sistema. Horários em Brasília, espaçados pelo ritmo de cada conta dentro da janela (Configurações). Falhas temporárias tentam de novo (5 min, 20 min, 1 h); acesso vencido marca a conta para reconectar.
  - **Ritmo padrão (13/11/2026):** contas novas entram com 4 posts/dia no YouTube e 3 no Instagram, Facebook e TikTok (~13/dia no total, dentro da meta de 10 a 20); janela das 11h às 23h; **intervalo mínimo de 120 min** entre posts da mesma conta (o que não cabe vai para o dia seguinte). Tudo ajustável em Configurações. Recomendação para canal novo: 1 a 2 por dia nas 2 primeiras semanas (ajustar na tela Contas).
  - Acessos das contas guardados **criptografados** (chave `CANAL_CHAVE_SECRETA` criada sozinha no `.env`; levar para a VPS junto).
  - Código: `app/postagem/` (`youtube`, `meta`, `tiktok`, `agendador`, `contas`, `cofre`, `legenda`, `redes`) e `app/painel/api_postagem.py`.
  - **Meta conectada (14/11/2026):** Página do Facebook "Arquivos de Vice City GTA 6" e Instagram @arquivos.vicecity. Duas armadilhas resolvidas no caminho, que valem para qualquer app novo da Meta:
    1. **Login unificado:** apps criados a partir de 2026 não aceitam mais a lista de permissões no endereço de login. As permissões ficam numa *configuração* criada no painel da Meta (Login do Facebook para Empresas → Configurações), e o endereço leva o número dela (`META_CONFIG_ID`, novo campo em Configurações → Chaves). Token **do usuário**, nunca o de sistema (esse exige ser Provedor de Tecnologia). As permissões de Página só aparecem na lista depois de adicionar o caso de uso "Gerenciar tudo na sua Página" e marcá-las ali.
    2. **Página de portfólio empresarial:** `/me/accounts` só lista Páginas administradas no perfil pessoal. A Página do canal pertence ao portfólio, então é procurada em `/me/businesses` → `owned_pages` e `client_pages` (exige `business_management`), e o token de publicação dela é buscado à parte. Cada passo vai para o log.
  - **App do TikTok (14/11/2026):** criado como `GTA6 Dark Publicador Web` (App ID `7708071772859467783`), na organização "Arquivos de Vice City". **O tipo tem de ser "Outro"** — a janela de criação vem marcada em "Minijogo" e o tipo não pode ser trocado depois. Categoria Entertainment, plataforma Web.
    - **Páginas públicas no GitHub Pages:** o TikTok exige provar que as páginas de termos, privacidade e site são suas, baixando um arquivo de assinatura e colocando no endereço. No endereço do Tailscale Funnel ele **não acha** o arquivo, porque não busca em endereço com porta (`:8443`). Solução (14/11/2026): as três páginas também ficam no repositório **`studiosocialresult-boop/canal-dark-site`**, publicadas em `https://studiosocialresult-boop.github.io/canal-dark-site/` (porta normal). Com esse prefixo a verificação passou. O original continua em `deploy/paginas_publicas/`; ao mexer nas páginas, atualizar os dois lugares. O endereço de retorno do login (`/contas/retorno/tiktok`) **não** precisa de verificação, então continua apontando para o painel na VPS.
    - Ícone do app: `deploy/marca/icone_app.png` (1024x1024), também publicado no GitHub Pages.
    - **Falta o vídeo de demonstração.** O portal novo do TikTok **não deixa nem salvar** o cadastro sem um vídeo curto (mp4 ou mov) mostrando o fluxo completo: conectar a conta do TikTok no painel e publicar um corte. Tudo o mais já está preenchido (ícone, categoria, descrição, as três URLs, plataforma Web, Login Kit com o endereço de retorno, Content Posting API com **Direct Post** ligado). Como o app ainda não foi aprovado, o TikTok manda gravar esse vídeo usando o **Sandbox** do portal. Próximo passo: criar o Sandbox, ligar o painel nele, gravar o vídeo, subir, salvar e pedir a auditoria.
  - **Falta para o "pronto":** terminar o cadastro do app do TikTok e ver um corte aprovado sair no horário marcado no Instagram e no Facebook (no YouTube já saiu). Endereços de retorno para cadastrar: na VPS, `https://canal-dark.tail8d61c4.ts.net/contas/retorno/youtube`, `/meta` e `/tiktok`.

### Fase 6 — Busca diária
- Todo dia às 6h (horário de São Paulo): buscar vídeos de GTA 6 em alta no Brasil e nos EUA pela YouTube Data API, mais os novos vídeos dos canais e perfis da lista monitorada.
- **Critério de escolha: muitas visualizações em pouco tempo.** Só entram vídeos postados recentemente (padrão: últimas 48 horas, configurável). Para cada um, calcular a **velocidade**: visualizações divididas pelas horas desde a postagem. Um vídeo com 200 mil views em 6 horas vale mais que um com 1 milhão em 30 dias.
- A rotina guarda as visualizações de cada vídeo a cada execução, para também detectar os que estão **acelerando** de um dia para o outro.
- Ordenar pela velocidade, descartar repetidos (o banco guarda o que já foi processado) e mandar os primeiros da lista para o pipeline, até a meta diária de cortes.
- O painel mostra o ranking do dia com visualizações, horas desde a postagem e velocidade, para o dono entender por que cada vídeo foi escolhido.
- **Limpeza do disco:** a rotina diária apaga os vídeos brutos com mais de 7 dias (configurável). Os cortes prontos e o registro no banco ficam.
- **Como ficou (13/11/2026):** a busca usa o próprio yt-dlp (pesquisas do YouTube ordenadas por visualizações, "esta semana" e "hoje"), **sem chave de API do Google** — só entram títulos com "GTA 6" ou "GTA VI" (não o GTA V). Também lê os canais acompanhados. Vídeos acima de 45 min ou abaixo de 40 s são ignorados. Tela **Hoje** mostra o ranking (views, horas, velocidade, "Acelerando"), os canais acompanhados e o histórico; botões **Buscar agora** e **Só atualizar** (sem mandar nada para a fila). Cada vídeo fora da meta tem **Gerar cortes**.
  - **Meta:** `meta_cortes_dia` (15) ÷ média de cortes por vídeo = quantos vídeos vão para a fila; buscas repetidas no mesmo dia não passam da meta.
  - **Automática desligada por padrão** (`busca_ativa`), porque cada vídeo na fila gasta créditos de IA. Ligue em Configurações; roda na hora escolhida (padrão 6h de Brasília), tenta de novo em 30 min se falhar (até 3 vezes) e roda no mesmo dia se o painel só abrir depois da hora.
  - **Limpeza:** apaga os vídeos brutos com mais de 7 dias; se um corte precisar do original depois (ex.: narrar), ele é baixado de novo.
  - **Instagram/TikTok:** continuam fora da busca (sem API oficial de "em alta").
- **Pronto quando:** a rotina roda sozinha 3 dias seguidos no computador e os cortes aparecem na fila. *(Falta o dono ligar a busca automática e deixar o painel aberto por 3 dias.)*
- **Modelo:** Sonnet 5.5

### Fase 7 — VPS
- Subir tudo numa VPS Linux, configurar o cron das 6h, logs e aviso quando algo falhar.
- **Como ficou (13/11/2026):**
  - **Servidor:** Oracle São Paulo (VM.Standard.E5.Flex, 2 vCPU, 11 GB, Ubuntu 24.04). O painel roda como serviço `canal-dark` (systemd): liga com a VPS e reinicia sozinho se cair. A "rotina das 6h" é a própria busca diária dentro do painel (não precisa de cron).
  - **Acesso:** só pela rede privada do **Tailscale**, em `https://canal-dark.tail8d61c4.ts.net` (precisa do app Tailscale ligado e logado na mesma conta). O painel escuta só dentro da VPS (127.0.0.1); a porta não abre para a internet. Endereço gravado em `~/canal-dark-vps.env` na VPS (`CANAL_URL_PAINEL`): é ele que vai nos cadastros das redes (`…/contas/retorno/youtube`, `/meta`, `/tiktok`).
  - **Publicar atualizações:** `publicar_na_vps.bat` (leva o código salvo no git, o `.env` e o `cookies.txt`). `trocar_cookies_vps.bat` quando o YouTube pedir login. `ver_logs_vps.bat` mostra o log. Os dados foram levados uma vez (`--levar-dados`); o painel do computador virou **painel de testes** (`CANAL_PAINEL_DE_TESTE=1`: não publica nem busca sozinho).
  - **Páginas públicas** (exigidas pelo Google para o app sair do modo de teste): início, privacidade e termos em `https://canal-dark.tail8d61c4.ts.net:8443/` (Tailscale Funnel, só a pasta `deploy/paginas_publicas`; o painel na porta 443 continua só na rede privada). Chaves agora podem ser colocadas pela tela Configurações → Chaves e integrações; o `publicar_na_vps.bat` não apaga as chaves da VPS.
  - **Primeiro post real (13/11/2026, 21:34):** corte aprovado → Agendar → publicado como Short público em https://www.youtube.com/shorts/SHUNONc7wLI. **"Pronto" da Fase 5 cumprido para o YouTube**; Instagram, Facebook e TikTok dependem dos cadastros da Meta e do TikTok.
  - **YouTube conectado** (13/11/2026): canal Arquivos de Vice City | GTA 6. App do Google era Interno (projeto dentro da organização gta6dark-canal-org) → mudado para Externo.
  - **Avisos:** Telegram (`app/avisos.py`), ligados só na VPS: falha na fila, na busca, post que não saiu, conta para reconectar, painel religado e resumo da busca do dia. Falta o dono criar o robô.
  - **Log:** `dados/logs/canal.log`, até 5 arquivos de 5 MB.
  - **Teste real na VPS:** busca com 26 vídeos; vídeo de 8 min virou 2 cortes narrados em 6 min. Na VPS a data dos vídeos só aparece com o login (cookies), já ajustado.
  - **Custo:** a E5.Flex usa os créditos do teste grátis da Oracle (acabam por volta de 13/12/2026). Antes disso: pagar (~US$ 40/mês, conferir), conseguir a A1 gratuita ou trocar de provedor (o `publicar_na_vps.bat` reinstala em qualquer VPS).
- **Pronto quando:** roda 7 dias sem intervenção.
- **Modelo:** Opus 5.5 para o deploy; **Fable 5.2** para a revisão final de segurança e do código inteiro.

## 7. Contas e chaves necessárias

| Para quê | O que criar | Quando |
|---|---|---|
| Cérebro e roteiro | Conta no Console da Anthropic + chave de API | Fase 1 |
| Narração | Chave de API da ElevenLabs | Fase 2 |
| Busca e postagem no YouTube | Projeto no Google Cloud com YouTube Data API | Fase 1 (cadastro), Fases 5 e 6 (uso) |
| Postagem no Instagram e Facebook | App no Meta for Developers + conta Instagram profissional | Fase 1 (cadastro), Fase 5 (uso) |
| Postagem no TikTok | App no TikTok for Developers | Fase 1 (cadastro), Fase 5 (uso) |
| Teste de download em servidor | VPS Linux barata, por poucos dias | Fase 1 |
| Rodar 24h | VPS Linux | Fase 7 |

A assinatura do Claude (usada no Claude Code) e a API da Anthropic (usada pelo app rodando) são cobranças separadas.

## 8. Decisões em aberto

1. **Transcrição:** começar com faster-whisper local, que é gratuito. Se ficar lento na VPS sem placa de vídeo, trocar por um serviço de transcrição pago.
2. **Lives:** a Fase 1 trata lives já encerradas (o vídeo gravado). Cortar live em tempo real fica para depois da Fase 7.
3. **Instagram e TikTok na busca diária:** não há API oficial de "vídeos em alta". A Fase 6 usa a lista de perfis monitorados para essas redes.
4. **Custo por corte:** medir na Fase 1 (tokens da API + caracteres da ElevenLabs) antes de definir o volume diário.
5. **Voz:** qual voz da ElevenLabs usar (uma voz fixa do canal ou vozes diferentes por conta).
6. **Duração dos cortes:** faixa padrão em segundos para cada rede.
7. **Identidade do canal:** nome, cores e fonte para os templates.
8. **Nota mínima para narrar:** começa em 70; ajustar depois de ver os primeiros cortes e o custo real da Fase 2.
9. **Onde roda o download:** ~~depende do teste de VPS da Fase 1~~ **Decidido: na própria VPS, com os cookies da conta secundária** (teste de 13/11/2026). O painel deve avisar quando os cookies vencerem.

## 9. Fora do escopo

- Qualquer recurso feito para enganar a detecção de direitos autorais das plataformas (espelhar, alterar velocidade ou tom, ruído, bordas ou filtros aplicados só para o vídeo não ser reconhecido). Edição aqui é editorial: corte, enquadramento, legenda, narração, headline e template.
- Compra ou automação de contas em massa, visualizações ou engajamento falsos.

## 10. Como começar no Claude Code

1. Abrir esta pasta na aba Code do app do Claude.
2. Selecionar o modelo **Fable 5.2**.
3. Primeira mensagem: *"Leia o plano.md e o CLAUDE.md e me explique a Fase 0 antes de começar."*
4. Ao terminar cada fase, pedir: *"Confira o critério de pronto da fase e me mostre o resultado."*
