/* Janela "Agendar publicação": usada pelas telas Cortes, Templates e Agenda.
   Agendar.abrir({ cortes: [ids], saidas: [ids], distribuir: bool }) */
"use strict";

const Agendar = (() => {
  const { esc, icone, api, aviso } = Painel;
  const NOMES_REDE = { youtube: "YouTube", instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok" };
  const PRIVACIDADE = { PUBLIC_TO_EVERYONE: "Todo mundo", MUTUAL_FOLLOW_FRIENDS: "Amigos (seguidores que você segue)",
                        FOLLOWER_OF_CREATOR: "Seguidores", SELF_ONLY: "Somente eu" };
  let pedido = null, dadosContas = null, infoTiktok = null;

  const fundo = document.createElement("div");
  fundo.className = "fundo-modal";
  fundo.id = "modal-agendar";
  fundo.innerHTML = `<div class="modal largo" style="position:relative;width:min(760px,100%)">
    <button class="botao-icone fechar" data-fechar aria-label="Fechar">${icone("x")}</button>
    <div class="modal-simples" id="agendar-corpo" style="max-height:calc(100vh - 60px);overflow-y:auto"></div></div>`;
  document.body.appendChild(fundo);
  const corpo = fundo.querySelector("#agendar-corpo");
  const fechar = () => fundo.classList.remove("aberto");
  fundo.addEventListener("mousedown", (e) => { if (e.target === fundo) fechar(); });
  fundo.addEventListener("click", (e) => { if (e.target.closest("[data-fechar]")) fechar(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && fundo.classList.contains("aberto")) fechar(); });

  const selo = (rede) => `<span class="rede ${rede}">${NOMES_REDE[rede]}</span>`;
  const total = () => (pedido.cortes || []).length + (pedido.saidas || []).length;

  async function abrir(novo) {
    pedido = { cortes: [], saidas: [], distribuir: false, ...novo };
    infoTiktok = null;
    corpo.innerHTML = '<div class="esqueleto" style="aspect-ratio:auto;height:240px"></div>';
    fundo.classList.add("aberto");
    try { dadosContas = await api("/api/contas"); } catch (erro) { corpo.innerHTML = `<p class="erro-texto">${esc(erro.message)}</p>`; return; }
    desenhar();
  }

  function desenhar() {
    const lista = dadosContas.contas;
    const n = total();
    const titulo = `<div><h2>Agendar ${n === 1 ? "publicação" : `${n} vídeos`}</h2>
      <p class="dica" style="margin:6px 0 0">O crédito do vídeo original entra sozinho na legenda. O mesmo corte nunca vai duas vezes para a mesma conta.</p></div>`;
    if (!lista.length) {
      corpo.innerHTML = titulo + `<div class="vazio-pequeno">Nenhuma conta conectada ainda. <a href="/contas">Conectar contas</a></div>`;
      return;
    }
    const contasHtml = lista.map((c) => {
      const ok = c.ativa && c.estado === "conectada";
      return `<label class="frase-item" style="cursor:${ok ? "pointer" : "not-allowed"};opacity:${ok ? 1 : .55}">
        <input type="checkbox" name="conta" value="${c.id}" data-rede="${c.rede}" ${ok ? "" : "disabled"} style="accent-color:var(--acento);width:18px;height:18px">
        ${selo(c.rede)}<span><b>${esc(c.nome)}</b> <small class="dica">${ok ? `${c.ritmo_hoje ?? c.posts_por_dia} por dia` : c.estado === "conectada" ? "pausada" : "precisa conectar de novo"}</small></span></label>`;
    }).join("");
    corpo.innerHTML = titulo + `
      <div class="secao"><h3>Contas</h3><div class="lista">${contasHtml}</div></div>
      ${n > 1 ? `<div class="secao"><h3>Para onde vai cada vídeo</h3>
        <div class="segmentado" id="ag-distribuir" style="justify-self:start">
          <button type="button" data-valor="todas" class="${pedido.distribuir ? "" : "ativo"}">Cada vídeo em todas as contas marcadas</button>
          <button type="button" data-valor="espalhar" class="${pedido.distribuir ? "ativo" : ""}">Um vídeo por conta (espalhar)</button></div>
        <p class="dica" style="margin:0">“Espalhar” serve para variações de um mesmo corte: cada vídeo vai para uma conta só.</p></div>` : ""}
      <div class="secao"><h3>Quando</h3>
        <div class="segmentado" id="ag-quando" style="justify-self:start"><button type="button" class="ativo" data-valor="ritmo">Próximo horário livre de cada conta</button><button type="button" data-valor="hora">Escolher data e hora</button></div>
        <input class="campo" type="datetime-local" id="ag-hora" hidden style="max-width:260px"></div>
      <div class="secao"><h3>Legenda</h3>${n === 1 ? `
        <p class="dica" style="margin:0">Deixe em branco para a IA escrever, ou peça uma sugestão e edite.</p>
        <button type="button" class="botao pequeno" id="ag-sugerir" style="justify-self:start">${icone("refazer")}Sugerir com IA</button>
        <label class="rotulo-campo">Título<input class="campo" id="ag-titulo" maxlength="90"></label>
        <label class="rotulo-campo">Descrição<textarea class="campo" id="ag-descricao" maxlength="600"></textarea></label>
        <label class="rotulo-campo">Hashtags (separadas por espaço, sem #)<input class="campo" id="ag-tags"></label>
        <p class="dica" id="ag-credito" style="margin:0"></p>` : `<p class="dica" style="margin:0">A IA escreve título, descrição e hashtags de cada vídeo (uma fração de centavo por vídeo). Você pode editar depois, na Agenda.</p>`}</div>
      <div class="secao" id="ag-tiktok" hidden></div>
      <p class="resumo-agendar" id="ag-resumo"></p>
      <div class="erro-texto" id="ag-erro"></div>
      <div class="modal-acoes"><button class="botao" type="button" data-fechar>Cancelar</button><button class="botao primario" type="button" id="ag-confirmar">Agendar</button></div>`;
    atualizarResumo();
  }

  const espalhar = () => !!corpo.querySelector('#ag-distribuir [data-valor="espalhar"].ativo');

  /** Diz, antes de confirmar, quantas publicações vão ser criadas. */
  function atualizarResumo() {
    const caixa = corpo.querySelector("#ag-resumo");
    if (!caixa) return;
    const n = total(), contas = corpo.querySelectorAll("input[name=conta]:checked").length;
    const v = n === 1 ? "1 vídeo" : `${n} vídeos`, c = contas === 1 ? "1 conta" : `${contas} contas`;
    if (!contas) { caixa.textContent = "Marque as contas onde quer postar."; return; }
    if (n > 1 && espalhar()) {
      caixa.innerHTML = `${v} espalhados entre ${c}: <b>cada vídeo vai para uma conta só</b>.`;
    } else {
      const pubs = n * contas;
      caixa.innerHTML = `${v} × ${c} = <b>${pubs} publicaç${pubs === 1 ? "ão" : "ões"}</b>${contas > 1 ? " (cada vídeo em todas as contas marcadas)" : ""}.`;
    }
  }

  corpo.addEventListener("click", async (e) => {
    const botaoQuando = e.target.closest("#ag-quando button");
    if (botaoQuando) {
      corpo.querySelectorAll("#ag-quando button").forEach((b) => b.classList.toggle("ativo", b === botaoQuando));
      corpo.querySelector("#ag-hora").hidden = botaoQuando.dataset.valor !== "hora";
      return;
    }
    const botaoDistribuir = e.target.closest("#ag-distribuir button");
    if (botaoDistribuir) {
      corpo.querySelectorAll("#ag-distribuir button").forEach((b) => b.classList.toggle("ativo", b === botaoDistribuir));
      atualizarResumo();
      return;
    }
    if (e.target.closest("#ag-sugerir")) return sugerir(e.target.closest("#ag-sugerir"));
    if (e.target.closest("#ag-confirmar")) return confirmar(e.target.closest("#ag-confirmar"));
  });
  corpo.addEventListener("change", (e) => {
    if (e.target.name === "conta") atualizarResumo();
    if (e.target.name === "conta" && e.target.dataset.rede === "tiktok") atualizarTiktok();
  });

  async function sugerir(botao) {
    botao.disabled = true; botao.lastChild.textContent = "Escrevendo…";
    try {
      const r = await api("/api/agendar/legenda", { metodo: "POST", corpo: pedido });
      corpo.querySelector("#ag-titulo").value = r.textos.titulo;
      corpo.querySelector("#ag-descricao").value = r.textos.descricao;
      corpo.querySelector("#ag-tags").value = r.textos.hashtags.join(" ");
      corpo.querySelector("#ag-credito").textContent = r.credito ? `Será acrescentado: ${r.credito}` : "";
      Painel.atualizarGasto();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
    botao.disabled = false; botao.lastChild.textContent = "Sugerir com IA";
  }

  async function atualizarTiktok() {
    const marcada = corpo.querySelector('input[name=conta][data-rede=tiktok]:checked');
    const caixa = corpo.querySelector("#ag-tiktok");
    if (!marcada) { caixa.hidden = true; infoTiktok = null; return; }
    caixa.hidden = false;
    caixa.innerHTML = '<h3>TikTok</h3><span class="dica">Consultando a conta…</span>';
    try { infoTiktok = await api(`/api/contas/${marcada.value}/tiktok`); }
    catch (erro) { caixa.innerHTML = `<h3>TikTok</h3><p class="erro-texto">${esc(erro.message)}</p>`; infoTiktok = null; return; }
    const op = infoTiktok.privacidades.map((p) => `<option value="${p}">${PRIVACIDADE[p] || p}</option>`).join("");
    const chave = (id, nome, desligado) => `<label class="interruptor" style="opacity:${desligado ? .5 : 1}"><input type="checkbox" id="${id}" ${desligado ? "disabled" : ""}>${nome}${desligado ? " (desativado na conta)" : ""}</label>`;
    caixa.innerHTML = `<h3>TikTok</h3>
      <p style="margin:0">Postando como <b>${esc(infoTiktok.apelido)}</b>.</p>
      <label class="rotulo-campo">Quem pode ver<select class="campo" id="tt-privacidade"><option value="" selected disabled>Escolha…</option>${op}</select></label>
      <div style="display:flex;gap:18px;flex-wrap:wrap">${chave("tt-comentarios", "Permitir comentários", infoTiktok.comentario_desligado)}
        ${chave("tt-dueto", "Permitir dueto", infoTiktok.dueto_desligado)}${chave("tt-costura", "Permitir costura", infoTiktok.costura_desligada)}</div>
      <label class="interruptor"><input type="checkbox" id="tt-consentimento">Ao postar, você concorda com a&nbsp;<a href="https://www.tiktok.com/legal/page/global/music-usage-confirmation/en" target="_blank" rel="noopener">Confirmação de Uso de Música do TikTok</a>.</label>
      <p class="dica" style="margin:0">Depois de enviado, o vídeo pode levar alguns minutos para aparecer no seu perfil. Enquanto o app não for auditado pelo TikTok, só dá para postar como "Somente eu", em conta privada.</p>`;
  }

  async function confirmar(botao) {
    const erroTexto = corpo.querySelector("#ag-erro");
    erroTexto.textContent = "";
    const contas = [...corpo.querySelectorAll("input[name=conta]:checked")].map((c) => Number(c.value));
    const corpoPedido = { cortes: pedido.cortes, saidas: pedido.saidas, contas,
                          distribuir: total() > 1 && espalhar() };
    if (!contas.length) { erroTexto.textContent = "Marque pelo menos uma conta."; return; }
    if (!corpo.querySelector("#ag-hora").hidden) {
      if (!corpo.querySelector("#ag-hora").value) { erroTexto.textContent = "Escolha a data e a hora."; return; }
      corpoPedido.horario = corpo.querySelector("#ag-hora").value;
    }
    const titulo = corpo.querySelector("#ag-titulo");
    if (titulo && (titulo.value.trim() || corpo.querySelector("#ag-descricao").value.trim())) {
      corpoPedido.textos = { titulo: titulo.value.trim(), descricao: corpo.querySelector("#ag-descricao").value.trim(),
                             hashtags: corpo.querySelector("#ag-tags").value.split(/[\s,#]+/).filter(Boolean) };
    }
    if (infoTiktok) {
      corpoPedido.tiktok = { privacidade: corpo.querySelector("#tt-privacidade").value,
                             comentarios: corpo.querySelector("#tt-comentarios").checked, dueto: corpo.querySelector("#tt-dueto").checked,
                             costura: corpo.querySelector("#tt-costura").checked, confirmado: corpo.querySelector("#tt-consentimento").checked };
      if (!corpoPedido.tiktok.privacidade) { erroTexto.textContent = "Escolha quem pode ver o post no TikTok."; return; }
      if (!corpoPedido.tiktok.confirmado) { erroTexto.textContent = "Para o TikTok, marque a confirmação de uso de música."; return; }
    }
    botao.disabled = true; botao.textContent = total() > 1 ? "Agendando (a IA escreve as legendas)…" : "Agendando…";
    try {
      const r = await api("/api/agendar", { metodo: "POST", corpo: corpoPedido });
      const puladas = r.puladas.length ? `<div class="secao"><h3>Não agendados (${r.puladas.length})</h3><div class="lista">${r.puladas.map((p) =>
        `<div class="frase-item"><span><b>${esc(p.conta)}</b> · ${esc(p.titulo)}<br><small class="dica">${esc(p.motivo)}</small></span></div>`).join("")}</div></div>` : "";
      corpo.innerHTML = `<div><h2>${r.criadas.length ? `${r.criadas.length} publicação${r.criadas.length > 1 ? "ões" : ""} agendada${r.criadas.length > 1 ? "s" : ""}` : "Nada foi agendado"}</h2></div>
        ${r.criadas.length ? `<div class="lista">${r.criadas.slice(0, 8).map((c) => `<div class="frase-item">${selo(c.rede)}<span><b>${esc(c.conta)}</b> · ${new Date(c.quando).toLocaleString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</span></div>`).join("")}</div>` : ""}
        ${puladas}<div class="modal-acoes"><button class="botao" type="button" data-fechar>Fechar</button><a class="botao primario" href="/agenda">Ver na Agenda</a></div>`;
      document.dispatchEvent(new CustomEvent("agenda:mudou"));
      Painel.atualizarGasto();
    } catch (erro) {
      erroTexto.textContent = erro.message;
      botao.disabled = false; botao.textContent = "Agendar";
    }
  }

  return { abrir };
})();
