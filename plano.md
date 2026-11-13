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
- **Pronto quando:** 3 links diferentes geram cortes que começam e terminam em frases completas, com legenda sincronizada.
- **Modelo:** **Fable 5.2** para desenhar o prompt do cérebro e a arquitetura do pipeline; **Opus 5.5** para o ffmpeg; Sonnet 5.5 no restante.

### Fase 2 — Narração
- O roteiro segue o modo escolhido pelo cérebro: no modo `original`, só um gancho curto na abertura; no modo `narrado`, narração do começo ao fim.
- ElevenLabs gera a voz em português; o áudio original abaixa automaticamente enquanto a narração fala.
- A narração só é gerada sozinha para cortes com nota igual ou acima do mínimo (padrão 70). Os demais ficam sem narração até alguém pedir.
- **Pronto quando:** um corte de cada modo sai com a narração sincronizada e o áudio original no volume certo.
- **Modelo:** Fable 5.2 para o prompt do roteiro; Sonnet 5.5 para a integração.

### Fase 3 — Painel
- Página local para colar link, ver a fila de processamento, assistir aos cortes e aprovar ou descartar.
- **Layout:** seguir `referencia-design.md` e as capturas em `referencia/` (barra lateral, busca no topo, cartões, grade de 6 colunas). A organização das telas vem da ViceScale; nome, logotipo e cores são próprios.
- Nesta fase entram o esqueleto do painel e a tela **Cortes**. As demais telas do menu aparecem conforme as fases seguintes.
- Telas por fase: **Cortes** (Fase 3); **Templates**, **Perfis** e **Editor** (Fase 4); **Contas** e **Agenda** (Fase 5); **Hoje** (Fase 6). **Configurações** nasce na Fase 3 e cresce a cada fase.
- Na tela Cortes, cada corte mostra a fonte e tem o botão para narrar os que ficaram abaixo da nota mínima.
- **Pronto quando:** dá para fazer o fluxo inteiro sem abrir o terminal.
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

### Fase 5 — Postagem e agendamento
- Ordem: YouTube Shorts primeiro (API mais simples), depois Instagram Reels, Facebook e TikTok.
- Agendador espaça os posts no ritmo configurado por conta.
- Modo padrão: **só posta o que foi aprovado no painel**. Há uma chave para ligar o modo 100% automático.
- **Pronto quando:** um corte aprovado é publicado nas contas conectadas no horário marcado.
- **Modelo:** Opus 5.5 (autenticação e APIs são a parte mais chata).
- A descrição de cada post credita a fonte do vídeo original.
- O agendador aplica a regra contra repetição da Fase 4 e mostra na tela **Agenda** o que vai para cada conta.
- **Atenção:** cada plataforma exige cadastro de aplicativo de desenvolvedor e aprovação. Isso leva dias — começar os cadastros já na Fase 1.
- **Travas a confirmar na documentação oficial antes de construir:**
  - YouTube: vídeos enviados por um app ainda não auditado ficam privados. Pedir a auditoria assim que houver algo funcionando para mostrar.
  - YouTube: a cota diária gratuita pode não cobrir 10 a 20 envios por dia mais as buscas da Fase 6. Medir e, se preciso, pedir aumento de cota.
  - YouTube: com o app em "modo teste", o acesso à conta expira a cada 7 dias. Publicar o app para o acesso não cair (necessário para a Fase 7 rodar 7 dias sozinha).
  - TikTok: sem auditoria do app, os posts saem só como privados, e a aprovação pode demorar ou ser negada. Se não sair, o TikTok fica com postagem manual a partir dos cortes baixados.

### Fase 6 — Busca diária
- Todo dia às 6h (horário de São Paulo): buscar vídeos de GTA 6 em alta no Brasil e nos EUA pela YouTube Data API, mais os novos vídeos dos canais e perfis da lista monitorada.
- **Critério de escolha: muitas visualizações em pouco tempo.** Só entram vídeos postados recentemente (padrão: últimas 48 horas, configurável). Para cada um, calcular a **velocidade**: visualizações divididas pelas horas desde a postagem. Um vídeo com 200 mil views em 6 horas vale mais que um com 1 milhão em 30 dias.
- A rotina guarda as visualizações de cada vídeo a cada execução, para também detectar os que estão **acelerando** de um dia para o outro.
- Ordenar pela velocidade, descartar repetidos (o banco guarda o que já foi processado) e mandar os primeiros da lista para o pipeline, até a meta diária de cortes.
- O painel mostra o ranking do dia com visualizações, horas desde a postagem e velocidade, para o dono entender por que cada vídeo foi escolhido.
- **Limpeza do disco:** a rotina diária apaga os vídeos brutos com mais de 7 dias (configurável). Os cortes prontos e o registro no banco ficam.
- **Pronto quando:** a rotina roda sozinha 3 dias seguidos no computador e os cortes aparecem na fila.
- **Modelo:** Sonnet 5.5

### Fase 7 — VPS
- Subir tudo numa VPS Linux, configurar o cron das 6h, logs e aviso quando algo falhar.
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
9. **Onde roda o download:** depende do teste de VPS da Fase 1 (na própria VPS ou no computador de casa).

## 9. Fora do escopo

- Qualquer recurso feito para enganar a detecção de direitos autorais das plataformas (espelhar, alterar velocidade ou tom, ruído, bordas ou filtros aplicados só para o vídeo não ser reconhecido). Edição aqui é editorial: corte, enquadramento, legenda, narração, headline e template.
- Compra ou automação de contas em massa, visualizações ou engajamento falsos.

## 10. Como começar no Claude Code

1. Abrir esta pasta na aba Code do app do Claude.
2. Selecionar o modelo **Fable 5.2**.
3. Primeira mensagem: *"Leia o plano.md e o CLAUDE.md e me explique a Fase 0 antes de começar."*
4. Ao terminar cada fase, pedir: *"Confira o critério de pronto da fase e me mostre o resultado."*
