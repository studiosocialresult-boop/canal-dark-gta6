# Canal Dark GTA 6 — instruções do projeto

Ferramenta que transforma links de vídeos em cortes verticais com legenda e narração, cria variações e publica nas redes. O plano completo está em `plano.md` — leia antes de qualquer tarefa.

## Como trabalhar com o dono do projeto

- Ele é **leigo em programação**. Responda sempre em **português do Brasil**, em linguagem simples, sem jargão. Quando um termo técnico for inevitável, explique em uma frase.
- Construa **uma fase por vez**, na ordem do `plano.md`. Não adiante fases.
- Antes de começar uma fase, explique em poucas linhas o que vai fazer. Ao terminar, mostre como ele testa o resultado sozinho, com o comando exato para copiar e colar.
- Peça confirmação antes de instalar programas, criar contas ou gastar créditos de API.
- Quando ele precisar fazer algo fora do código (criar chave de API, cadastrar app numa plataforma), dê o passo a passo numerado, clique a clique.
- Se algo der errado, diga o que aconteceu e o que você vai tentar, sem despejar o erro bruto.

## Stack

- Python 3.12, ffmpeg, yt-dlp, faster-whisper
- SQLite em `dados/canal.db`
- FastAPI + HTML simples no painel
- API da Anthropic: `claude-sonnet-5-5` (cérebro, roteiro), `claude-haiku-5-5` (títulos, legendas, hashtags)
- ElevenLabs para narração

## Regras de código

- Desenvolvimento em **Windows**, produção em **VPS Linux**. Use `pathlib` para todo caminho; nada de `D:\` ou barras fixas no código. A pasta do projeto tem espaços no nome — sempre trate caminhos com isso em mente, inclusive nas chamadas ao ffmpeg.
- Chame ffmpeg e yt-dlp com lista de argumentos (`subprocess.run([...])`), nunca montando texto de comando.
- Segredos ficam só no `.env`. Nunca escreva chaves no código, em logs ou em commits. Mantenha `.env.example` atualizado sem valores reais.
- Cada módulo em `app/` tem uma função principal clara e pode ser rodado sozinho para teste.
- Prompts de IA ficam em arquivos em `prompts/`, não embutidos no código.
- O cérebro sempre devolve JSON validado; resposta inválida gera nova tentativa, não quebra o pipeline.
- Todo vídeo processado é registrado no banco, para nunca reprocessar ou repostar o mesmo.
- Etapas demoradas (download, transcrição, render) registram progresso em log legível.
- Nomes de arquivos, funções e comentários em português, sem acentos nos nomes de arquivo.
- Vídeos e o banco (`dados/`) ficam fora do git.

## Comportamento do produto

- Hoje é de uso pessoal, mas será vendido depois: toda tabela tem `usuario_id` e as configurações são por usuário. Não construir login nem cobrança agora.
- Saída sempre em **português do Brasil** (legenda e narração), mesmo quando o vídeo de origem é em inglês.
- O cérebro define o modo de cada corte: `original` (áudio original, no máximo um gancho narrado) ou `narrado` (narração completa).
- Meta de volume: 10 a 20 cortes por dia, processando um vídeo por vez.

- Painel: a organização das telas segue `referencia-design.md` e as imagens em `referencia/`. Olhe as imagens antes de construir qualquer tela. Copie a lógica e o fluxo, nunca a marca: nome, logotipo, cores e textos são próprios. Não incluir selo de "verificado".
- Postagem: por padrão, só publica cortes **aprovados no painel**. O modo totalmente automático é uma configuração explícita, desligada por padrão.
- Edição é editorial: corte, enquadramento 9:16, legenda, narração, headline e template.
- **Não implementar** recursos cujo objetivo seja burlar a detecção de direitos autorais das plataformas (espelhamento, alteração de velocidade ou tom, ruído, bordas ou filtros aplicados só para o vídeo não ser reconhecido). Se isso for pedido, recuse essa parte e siga com o restante.

## Testes

- Cada fase tem um critério de "pronto" no `plano.md`. A fase só fecha quando ele passa de verdade, rodando o fluxo real.
- Guarde em `testes/` um vídeo curto de exemplo para testar sem baixar nada.

## Modelo e esforço recomendados

| Tarefa | Modelo | Esforço |
|---|---|---|
| Arquitetura, prompts do cérebro e do roteiro | Fable 5.2 | high |
| Revisão final do projeto | Fable 5.2 | xhigh |
| ffmpeg, autenticação e APIs de postagem, deploy | Opus 5.5 | high |
| Bug que não saiu em duas tentativas | Opus 5.5 | xhigh |
| Telas, banco de dados, integrações, tarefas do dia a dia | Sonnet 5.5 | medium |
| Instalação, ajustes pequenos, renomear, mudar texto | Sonnet 5.5 | low |

Não usar `max`: custa muito e tende a pensar demais.

**Sempre avisar:** no começo de cada fase, e sempre que a próxima tarefa pedir um modelo ou esforço diferente do atual, comece a resposta com uma linha assim, antes de qualquer outra coisa:

> 🔧 Para esta etapa: **Modelo X**, esforço **Y**. Troque em `/model` (setas para os lados ajustam o esforço) ou com `/effort Y`.

A tabela por fase está no `plano.md`, seção 6.
