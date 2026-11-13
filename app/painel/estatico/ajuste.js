/* Editor: ajusta um vídeo para a tela vertical (zoom e posição) e gera o mp4. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  const ID = window.TEMPLATE_ID;
  let T = null, fonte = "cortes", cortes = null, biblioteca = null, saidas = null;
  let relogioPrevia = null, relogioMidia = null, relogioSaidas = null;

  const midia = () => T.midias.find((m) => m.zona === 1);

  async function recarregar() {
    T = await api(`/api/templates/${ID}`);
    if (!$("#nome").matches(":focus")) $("#nome").value = T.nome;
  }

  function atualizarPrevia() {
    clearTimeout(relogioPrevia);
    relogioPrevia = setTimeout(() => {
      const celular = $("#celular"), imagem = $("#previa"), m = midia();
      celular.classList.add("carregando");
      const nova = new Image();
      nova.onload = () => { imagem.src = nova.src; celular.classList.remove("carregando"); };
      nova.onerror = () => celular.classList.remove("carregando");
      nova.src = `/api/templates/${ID}/previa.jpg?${m ? "midia=" + m.id + "&" : ""}v=${Date.now()}`;
    }, 140);
  }

  // ---------- passo 1: fonte do vídeo ----------

  const miniatura = (src, titulo, acao, id) => `<button class="miniatura" data-acao="${acao}" data-id="${id}" title="${esc(titulo)}">
    ${src ? `<img src="${src}" alt="" loading="lazy" onerror="this.style.display='none'">` : ""}<span class="legenda">${esc(titulo)}</span></button>`;

  function desenharFonte() {
    const caixa = $("#painel-fonte");
    if (fonte === "cortes") {
      caixa.innerHTML = cortes === null ? '<span class="dica">Carregando…</span>' : cortes.length
        ? `<div class="miniaturas">${cortes.map((c) => miniatura(c.miniatura, c.titulo, "usar-corte", c.id)).join("")}</div>`
        : '<div class="vazio-pequeno">Nenhum corte ainda. Crie na tela Cortes ou use outra fonte.</div>';
    } else if (fonte === "biblioteca") {
      caixa.innerHTML = biblioteca === null ? '<span class="dica">Carregando…</span>' : biblioteca.length
        ? `<div class="miniaturas">${biblioteca.map((b) => miniatura(b.miniatura, b.titulo || b.id_externo, "usar-biblioteca", b.id)).join("")}</div>`
        : '<div class="vazio-pequeno">A biblioteca está vazia. Na tela Perfis, escolha vídeos e clique em "Baixar vídeos".</div>';
    } else {
      caixa.innerHTML = `<label class="envio" id="area-envio"><span>${icone("baixar", "transform:rotate(180deg);width:26px;height:26px")}</span><b>Clique ou arraste um vídeo aqui</b>
        <small>MP4, MOV, WEBM ou MKV, até 2 GB</small><input type="file" id="arquivo" accept="video/*" hidden></label><div id="progresso-envio"></div>`;
      const envio = $("#area-envio");
      envio.addEventListener("dragover", (e) => { e.preventDefault(); envio.classList.add("sobre"); });
      envio.addEventListener("dragleave", () => envio.classList.remove("sobre"));
      envio.addEventListener("drop", (e) => { e.preventDefault(); envio.classList.remove("sobre"); if (e.dataTransfer.files[0]) enviar(e.dataTransfer.files[0]); });
      $("#arquivo").onchange = (e) => e.target.files[0] && enviar(e.target.files[0]);
    }
  }

  function desenharAtual() {
    const m = midia();
    $("#video-atual").innerHTML = m ? `<div class="aviso-caixa" style="background:var(--ok-fraco);color:var(--ok)">${icone("check")}<span>Vídeo escolhido: <b>${esc(m.rotulo)}</b></span></div>` : "";
  }

  async function trocarMidia(chamada) {
    try {
      for (const m of T.midias) await api(`/api/templates/${ID}/midias/${m.id}`, { metodo: "DELETE" });   // o Editor trabalha com um vídeo só
      await chamada();
      await api(`/api/templates/${ID}/saidas`, { metodo: "DELETE" }).catch(() => {});
      await recarregar(); saidas = null;
      desenharAtual(); desenharEnquadramento(); desenharResultado(); atualizarPrevia();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }

  function enviar(arquivo) {
    const caixa = $("#progresso-envio");
    return trocarMidia(() => new Promise((resolver, rejeitar) => {
      const pedido = new XMLHttpRequest();
      pedido.open("POST", `/api/templates/${ID}/upload?nome=${encodeURIComponent(arquivo.name)}`);
      pedido.upload.onprogress = (e) => e.lengthComputable && (caixa.innerHTML = `<div class="dica" style="margin:8px 0 4px">Enviando ${esc(arquivo.name)}…</div><div class="trilho-progresso"><i style="width:${Math.round(e.loaded / e.total * 100)}%"></i></div>`);
      pedido.onload = () => pedido.status < 300 ? resolver() : rejeitar(new Error(JSON.parse(pedido.responseText || "{}").erro || "Falha no envio."));
      pedido.onerror = () => rejeitar(new Error("A conexão caiu durante o envio."));
      pedido.send(arquivo);
    }));
  }

  $("#painel-fonte").addEventListener("click", (e) => {
    const b = e.target.closest("[data-acao]"); if (!b) return;
    const id = Number(b.dataset.id);
    if (b.dataset.acao === "usar-corte") trocarMidia(() => api(`/api/templates/${ID}/midias`, { metodo: "POST", corpo: { cortes: [id] } }));
    else if (b.dataset.acao === "usar-biblioteca") trocarMidia(() => api(`/api/templates/${ID}/midias`, { metodo: "POST", corpo: { biblioteca: [id] } }));
  });

  $("#fontes").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    fonte = b.dataset.fonte;
    document.querySelectorAll("#fontes button").forEach((x) => x.classList.toggle("ativo", x === b));
    desenharFonte();
    try {
      if (fonte === "cortes" && cortes === null) { cortes = (await api("/api/cortes")).cortes.filter((c) => c.miniatura && !["descartado", "falhou"].includes(c.estado)); desenharFonte(); }
      if (fonte === "biblioteca" && biblioteca === null) { biblioteca = (await api("/api/biblioteca")).itens; desenharFonte(); }
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  // ---------- passo 2: enquadramento ----------

  function desenharEnquadramento() {
    const m = midia(), caixa = $("#enquadramento");
    if (!m) { caixa.innerHTML = '<h2>2. Enquadramento</h2><div class="vazio-pequeno">Escolha um vídeo acima para ajustar.</div>'; return; }
    const ctl = (campo, rotulo, min, max, passo, texto) => `<div class="controle"><div class="controle-topo"><span>${rotulo}</span><output>${texto}</output></div>
      <input type="range" data-campo="${campo}" min="${min}" max="${max}" step="${passo}" value="${m[campo]}"></div>`;
    caixa.innerHTML = `<h2>2. Enquadramento</h2>
      <div class="segmentado" id="seg-ajuste" style="justify-self:start"><button data-valor="preencher" class="${m.ajuste === "preencher" ? "ativo" : ""}">Preencher a tela</button>
        <button data-valor="caber" class="${m.ajuste === "caber" ? "ativo" : ""}">Caber inteiro</button></div>
      ${m.ajuste === "preencher" ? `<div class="linha-campos">${ctl("zoom", "Zoom", 1, 3, 0.05, Number(m.zoom).toFixed(2) + "×")}${ctl("pos_x", "Posição horizontal", 0, 100, 1, Math.round(m.pos_x) + "%")}${ctl("pos_y", "Posição vertical", 0, 100, 1, Math.round(m.pos_y) + "%")}</div>`
        : `<div class="rotulo-campo">Fundo atrás do vídeo<div class="segmentado" id="seg-fundo" style="justify-self:start"><button data-valor="desfocado" class="${T.config.video.fundo === "desfocado" ? "ativo" : ""}">Desfocado</button><button data-valor="solido" class="${T.config.video.fundo === "solido" ? "ativo" : ""}">Preto liso</button></div></div>`}`;
  }

  $("#enquadramento").addEventListener("input", (e) => {
    const campo = e.target.dataset.campo; if (!campo) return;
    const m = midia(); m[campo] = Number(e.target.value);
    e.target.closest(".controle").querySelector("output").textContent = campo === "zoom" ? m[campo].toFixed(2) + "×" : Math.round(m[campo]) + "%";
    clearTimeout(relogioMidia);
    relogioMidia = setTimeout(async () => {
      try { await api(`/api/templates/${ID}/midias/${m.id}`, { metodo: "PUT", corpo: { [campo]: m[campo] } }); marcarMudanca(); atualizarPrevia(); }
      catch (erro) { aviso(erro.message, { tipo: "erro" }); }
    }, 300);
  });
  $("#enquadramento").addEventListener("click", async (e) => {
    const b = e.target.closest(".segmentado button"); if (!b) return;
    try {
      if (b.parentElement.id === "seg-ajuste") await api(`/api/templates/${ID}/midias/${midia().id}`, { metodo: "PUT", corpo: { ajuste: b.dataset.valor } });
      else await api(`/api/templates/${ID}`, { metodo: "PUT", corpo: { config: { video: { fundo: b.dataset.valor } } } });
      await recarregar(); marcarMudanca(); desenharEnquadramento(); atualizarPrevia();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  /** Mexeu no enquadramento depois de gerar: o vídeo pronto ficou desatualizado. */
  function marcarMudanca() { if (saidas && saidas.contagem.pronto) { saidas.desatualizado = true; desenharResultado(); } }

  // ---------- passo 3: gerar e baixar ----------

  function desenharResultado() {
    const caixa = $("#resultado");
    caixa.hidden = !saidas || !saidas.saidas.length;
    if (caixa.hidden) return;
    const s = saidas.saidas[0], c = saidas.contagem;
    const trabalhando = c.aguardando + c.renderizando > 0;
    caixa.innerHTML = `<h2>3. Resultado</h2>
      ${trabalhando ? `<div style="display:flex;gap:12px;align-items:center"><div class="giro"></div><b>${s.estado === "renderizando" ? "Montando o vídeo…" : "Na fila…"}</b></div>`
        : s.estado === "pronto" ? `${saidas.desatualizado ? `<div class="aviso-caixa">${icone("alerta")}<span>Você mudou o enquadramento depois de gerar. Clique em "Gerar vídeo" para atualizar.</span></div>` : ""}
            <div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap"><div class="saida" style="width:200px"><div class="tela"><video src="${s.url}" controls preload="metadata" playsinline></video></div></div>
              <a class="botao primario" href="${s.url}?baixar=1" download>${icone("baixar")}Baixar vídeo</a></div>`
        : `<div class="aviso-caixa" style="background:var(--erro-fraco);color:var(--erro)">${icone("alerta")}<span>${esc(s.erro || "Falhou")}</span></div>`}`;
  }

  async function atualizarSaidas() {
    clearTimeout(relogioSaidas);
    try { saidas = await api(`/api/templates/${ID}/saidas`); } catch (e) { relogioSaidas = setTimeout(atualizarSaidas, 4000); return; }
    desenharResultado();
    if (saidas.contagem.aguardando + saidas.contagem.renderizando > 0) relogioSaidas = setTimeout(atualizarSaidas, 2000);
  }

  $("#gerar").onclick = async () => {
    if (!midia()) { aviso("Escolha um vídeo primeiro.", { tipo: "erro" }); return; }
    try {
      await api(`/api/templates/${ID}/saidas`, { metodo: "DELETE" });      // refaz do zero com o enquadramento atual
      await api(`/api/templates/${ID}/gerar`, { metodo: "POST" });
      saidas = null; atualizarSaidas();
      $("#resultado").hidden = false;
      $("#resultado").scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  };
  document.addEventListener("fila:terminou", atualizarSaidas);

  let relogioNome = null;
  $("#nome").addEventListener("input", (e) => {
    clearTimeout(relogioNome);
    relogioNome = setTimeout(() => api(`/api/templates/${ID}`, { metodo: "PUT", corpo: { nome: e.target.value } }).catch(() => {}), 500);
  });

  // ---------- início ----------

  (async () => {
    try {
      await recarregar();
      desenharFonte(); desenharAtual(); desenharEnquadramento(); atualizarPrevia();
      cortes = (await api("/api/cortes")).cortes.filter((c) => c.miniatura && !["descartado", "falhou"].includes(c.estado));
      desenharFonte();
      atualizarSaidas();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  })();
})();
