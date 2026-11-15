/* Tela Cortes: grade, filtros, revisão por teclado e seleção em massa. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso, dolar } = Painel;

  const estado = {
    cortes: [], numeros: null, aba: "revisar", modos: new Set(), ordem: "novos", busca: "",
    selecionados: new Set(), selecao: false, aberto: null, carregado: false,
  };

  const grade = $("#grade"), modal = $("#modal-corte"), player = $("#player");

  // ---------- dados ----------

  async function carregar() {
    try {
      const dados = await api("/api/cortes");
      estado.cortes = dados.cortes;
      estado.numeros = dados.numeros;
      estado.carregado = true;
      // Tira da seleção o que sumiu da lista.
      for (const id of [...estado.selecionados]) if (!estado.cortes.some((c) => c.id === id)) estado.selecionados.delete(id);
      desenhar();
      if (estado.aberto) preencherModal();
    } catch (erro) {
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1"><h2>Não consegui carregar os cortes</h2><p>${esc(erro.message)}</p></div>`;
    }
  }

  /** Pronto para agendar: tem o vídeo no template e ainda não foi agendado. */
  const prontoParaAgendar = (c) => !!c.pronta && !c.agendado && !["descartado", "falhou"].includes(c.estado);

  /** Já publicado em pelo menos uma rede. */
  const postado = (c) => !!c.postagem;

  const ABAS = {
    revisar: (c) => (c.estado === "renderizado" || c.estado === "proposto") && !prontoParaAgendar(c) && !postado(c),
    aprovado: (c) => c.estado === "aprovado" && !prontoParaAgendar(c) && !postado(c),
    prontos: prontoParaAgendar,
    postados: postado,
    descartado: (c) => c.estado === "descartado",
    todos: () => true,
  };

  function filtrados() {
    let lista = estado.cortes.filter(ABAS[estado.aba]);
    if (estado.modos.size) lista = lista.filter((c) => estado.modos.has(c.modo));
    if (estado.busca) {
      lista = lista.filter((c) => (c.titulo + " " + c.canal + " " + c.video_titulo + " " + c.motivo).toLowerCase().includes(estado.busca));
    }
    const ordem = {
      novos: (a, b) => b.id - a.id,
      nota: (a, b) => b.nota - a.nota || b.id - a.id,
      curtos: (a, b) => a.duracao_s - b.duracao_s,
      views: (a, b) => (b.postagem?.visualizacoes ?? -1) - (a.postagem?.visualizacoes ?? -1) || b.id - a.id,
    }[estado.ordem];
    return lista.sort(ordem);
  }

  // ---------- grade ----------

  const corDaNota = (n) => (n >= 80 ? "#3ccf7a" : n >= 65 ? "#ffb02e" : "#ff6b70");

  const NOMES_REDES = { youtube: "YouTube", instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok" };
  const numero = (n) => (n == null ? "–" : n.toLocaleString("pt-BR"));

  /** Pé do cartão na aba Postados: visualizações, curtidas e comentários somados de todas as redes. */
  function pePostado(c) {
    const p = c.postagem;
    const redes = p.redes.map((r) => NOMES_REDES[r] || r).join(", ");
    return `<div class="corte-pe corte-metricas" title="Publicado em: ${esc(redes)}. Soma de todas as redes.">
      <span title="Visualizações">👁 <b>${numero(p.visualizacoes)}</b></span>
      <span title="Curtidas">❤ <b>${numero(p.curtidas)}</b></span>
      <span title="Comentários">💬 <b>${numero(p.comentarios)}</b></span>
      <span class="corte-redes">${esc(redes)}</span></div>`;
  }

  function cartao(c, indice) {
    const selo = c.estado === "aprovado" ? '<span class="tag estado-aprovado">Aprovado</span>'
      : c.estado === "descartado" ? '<span class="tag estado-descartado">Descartado</span>'
      : c.estado === "falhou" ? '<span class="tag estado-falhou">Falhou</span>' : "";
    const voz = c.narracao === "narrado" ? '<span class="tag voz">Com voz</span>'
      : c.modo === "narrado" ? '<span class="tag">Sem voz</span>' : '<span class="tag">Original</span>';
    const situacao = c.preparando ? '<span class="tag">Preparando…</span>'
      : prontoParaAgendar(c) ? '<span class="tag estado-pronto">Pronto para agendar</span>'
      : postado(c) ? '<span class="tag estado-aprovado">Postado</span>'
      : c.agendado ? '<span class="tag">Agendado</span>' : "";
    const imagem = c.pronta ? c.pronta.miniatura : c.miniatura;
    const marcado = estado.selecionados.has(c.id);
    const acoes = c.estado === "renderizado"
      ? `<button class="mini ok" data-acao="aprovado" title="Aprovar (A)">${icone("check")}</button>
         <button class="mini no" data-acao="descartado" title="Descartar (D)">${icone("x")}</button>`
      : `<button class="mini" data-acao="renderizado" title="Voltar para revisar">${icone("refazer")}</button>`;
    return `<article class="corte ${c.estado} ${marcado ? "selecionado" : ""}" data-id="${c.id}" style="animation-delay:${Math.min(indice, 12) * 30}ms">
      <div class="corte-imagem">
        ${imagem ? `<img src="${imagem}" alt="" loading="lazy">` : ""}
        <div class="corte-topo">
          <div class="nota" style="--p:${c.nota};--cor:${corDaNota(c.nota)}" title="Nota ${c.nota}"><span>${c.nota}</span></div>
          <div style="display:flex;flex-direction:column;gap:5px;align-items:flex-start">${voz}${selo}${situacao}</div>
          <div class="espaco caixa-selecao" data-selecionar>${icone("check")}</div>
        </div>
        <div class="corte-titulo">${esc(c.titulo)}</div>
      </div>
      ${estado.aba === "postados" && postado(c) ? pePostado(c) : `<div class="corte-pe">
        <div class="corte-fonte" title="${esc(c.video_titulo)}"><b>${esc(c.canal || "—")}</b> · ${Math.round(c.duracao_s)} s${c.visualizacoes != null ? ` · <a href="/desempenho" title="Ver o desempenho">${c.visualizacoes.toLocaleString("pt-BR")} visualizações</a>` : ""}</div>
        ${acoes}
      </div>`}</article>`;
  }

  function desenhar() {
    const n = estado.numeros;
    $("#n-revisar").textContent = n.revisar;
    $("#n-aprovados").textContent = estado.cortes.filter((c) => c.estado === "aprovado" && !postado(c)).length;
    $("#n-hoje").textContent = n.cortes_hoje;
    const custos = estado.cortes.filter((c) => c.custo_usd > 0).map((c) => c.custo_usd);
    $("#n-custo").textContent = custos.length ? dolar(custos.reduce((a, b) => a + b, 0) / custos.length) : "–";
    $("#aba-revisar").textContent = n.revisar;
    $("#aba-aprovado").textContent = estado.cortes.filter(ABAS.aprovado).length;
    $("#aba-prontos").textContent = estado.cortes.filter(ABAS.prontos).length;
    $("#aba-postados").textContent = estado.cortes.filter(ABAS.postados).length;
    $("#aba-descartado").textContent = n.descartados;
    $("#aba-todos").textContent = estado.cortes.length;

    const lista = filtrados();
    if (!estado.cortes.length) {
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1">${arte()}
        <h2>Nenhum corte ainda</h2>
        <p>Cole o link de um vídeo do YouTube e a IA escolhe os melhores momentos, monta os cortes verticais e coloca legenda em português.</p>
        <button class="botao primario" onclick="Painel.abrirNovo()">${icone("mais")}Criar meu primeiro corte</button></div>`;
    } else if (!lista.length) {
      const porAba = { revisar: "Nada esperando revisão. Bom trabalho!", aprovado: "Nenhum corte aprovado esperando template.",
                       prontos: "Nenhum corte pronto para agendar. Selecione cortes e clique em “Preparar com template”.",
                       postados: "Nenhum corte foi publicado ainda. Quando um post sair, ele aparece aqui com os números.",
                       descartado: "Nenhum corte descartado.", todos: "Nenhum corte combina com os filtros." };
      grade.innerHTML = `<div class="cartao vazio" style="grid-column:1/-1"><h2>${porAba[estado.aba]}</h2>
        <p>${estado.busca || estado.modos.size ? "Tente limpar a busca ou os filtros." : "Quando novos cortes ficarem prontos, eles aparecem aqui."}</p></div>`;
    } else {
      grade.innerHTML = lista.map(cartao).join("");
    }
    document.body.classList.toggle("modo-selecao", estado.selecao);
    atualizarBarraMassa();
  }

  const arte = () => `<svg class="arte" viewBox="0 0 160 160" fill="none"><defs><linearGradient id="ga" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#6a45ff"/><stop offset="1" stop-color="#ff4f8b"/></linearGradient></defs>
    <rect x="48" y="14" width="64" height="112" rx="14" fill="url(#ga)" opacity=".16"/><rect x="48" y="14" width="64" height="112" rx="14" stroke="url(#ga)" stroke-width="3"/>
    <path d="M73 52v32l26-16z" fill="url(#ga)"/><circle cx="32" cy="118" r="9" stroke="url(#ga)" stroke-width="3"/><circle cx="32" cy="146" r="9" stroke="url(#ga)" stroke-width="3"/>
    <path d="M40 124l60 18M40 140l60-18" stroke="url(#ga)" stroke-width="3" stroke-linecap="round"/></svg>`;

  // ---------- ações ----------

  async function definirEstado(ids, novo, { silencioso = false } = {}) {
    const anteriores = ids.map((id) => ({ id, estado: estado.cortes.find((c) => c.id === id)?.estado })).filter((x) => x.estado);
    try {
      await api("/api/cortes/estado", { metodo: "POST", corpo: { ids, estado: novo } });
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); return false; }
    await carregar();
    if (!silencioso) {
      const rotulo = { aprovado: "aprovado", descartado: "descartado", renderizado: "devolvido para revisão" }[novo];
      aviso(ids.length === 1 ? `Corte ${rotulo}.` : `${ids.length} cortes ${rotulo}s.`, {
        acao: async () => {
          for (const estadoAntigo of new Set(anteriores.map((a) => a.estado))) {
            await api("/api/cortes/estado", { metodo: "POST", corpo: { ids: anteriores.filter((a) => a.estado === estadoAntigo).map((a) => a.id), estado: estadoAntigo } });
          }
          carregar();
        },
      });
    }
    return true;
  }

  // Clique nos cartões (delegação).
  grade.addEventListener("click", (e) => {
    const alvo = e.target.closest(".corte");
    if (!alvo) return;
    const id = Number(alvo.dataset.id);
    const botao = e.target.closest("[data-acao]");
    if (botao) { e.stopPropagation(); definirEstado([id], botao.dataset.acao); return; }
    if (e.target.closest("[data-selecionar]") || estado.selecao || e.shiftKey || e.ctrlKey) {
      alternarSelecao(id);
      return;
    }
    abrir(id);
  });

  function alternarSelecao(id) {
    if (estado.selecionados.has(id)) estado.selecionados.delete(id); else estado.selecionados.add(id);
    desenhar();
  }

  // Prévia em movimento ao passar o mouse.
  grade.addEventListener("mouseover", (e) => {
    const alvo = e.target.closest(".corte");
    if (!alvo || alvo.dataset.previa) return;
    const c = estado.cortes.find((x) => x.id === Number(alvo.dataset.id));
    if (!c || !c.midia) return;
    alvo.dataset.previa = "1";
    const video = document.createElement("video");
    Object.assign(video, { src: c.pronta ? c.pronta.url : c.midia, muted: true, loop: true, playsInline: true, preload: "auto" });
    video.addEventListener("loadeddata", () => video.classList.add("tocando"), { once: true });
    alvo.querySelector(".corte-imagem").insertBefore(video, alvo.querySelector(".corte-topo"));
    if (alvo.matches(":hover")) video.play().catch(() => {});
    alvo.addEventListener("mouseenter", () => video.play().catch(() => {}));
    alvo.addEventListener("mouseleave", () => { video.pause(); video.currentTime = 0; });
  });

  // ---------- seleção em massa ----------

  function atualizarBarraMassa() {
    const total = estado.selecionados.size;
    $("#barra-massa").classList.toggle("aberta", total > 0);
    $("#massa-texto").textContent = total === 1 ? "1 selecionado" : `${total} selecionados`;
  }
  $("#botao-selecionar").onclick = () => {
    estado.selecao = !estado.selecao;
    if (!estado.selecao) estado.selecionados.clear();
    $("#botao-selecionar").classList.toggle("primario", estado.selecao);
    desenhar();
  };
  $("#massa-aprovar").onclick = async () => { await definirEstado([...estado.selecionados], "aprovado"); estado.selecionados.clear(); desenhar(); };
  $("#massa-descartar").onclick = async () => { await definirEstado([...estado.selecionados], "descartado"); estado.selecionados.clear(); desenhar(); };
  $("#massa-limpar").onclick = () => { estado.selecionados.clear(); desenhar(); };

  // ---------- filtros ----------

  $("#abas").addEventListener("click", (e) => {
    const aba = e.target.closest(".aba");
    if (!aba) return;
    estado.aba = aba.dataset.aba;
    document.querySelectorAll(".aba").forEach((a) => a.classList.toggle("ativa", a === aba));
    desenhar();
  });
  document.querySelectorAll(".chip[data-modo]").forEach((chip) => chip.addEventListener("click", () => {
    const modo = chip.dataset.modo;
    if (estado.modos.has(modo)) estado.modos.delete(modo); else estado.modos.add(modo);
    chip.classList.toggle("ativo", estado.modos.has(modo));
    desenhar();
  }));
  $("#ordem").onchange = (e) => { estado.ordem = e.target.value; desenhar(); };
  document.addEventListener("busca", (e) => { estado.busca = e.detail; desenhar(); });
  document.addEventListener("fila:terminou", carregar);

  // ---------- janela de revisão ----------

  function abrir(id) {
    estado.aberto = id;
    modal.classList.add("aberto");
    preencherModal(true);
  }
  function fechar() {
    modal.classList.remove("aberto");
    player.pause(); player.removeAttribute("src"); player.load();
    player.hidden = false; previaGrande.hidden = true; previaGrande.removeAttribute("src"); delete previaGrande.dataset.src;
    estado.aberto = null;
  }

  function preencherModal(novoVideo = false) {
    const lista = filtrados();
    let indice = lista.findIndex((c) => c.id === estado.aberto);
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    if (!c) { fechar(); return; }

    if (novoVideo) { player.pause(); player.removeAttribute("src"); }
    $("#corte-posicao").textContent = indice >= 0 ? `${indice + 1} de ${lista.length}` : "";
    const estadoSelo = { renderizado: '<span class="selo acento">Para revisar</span>', aprovado: '<span class="selo ok">Aprovado</span>',
                         descartado: '<span class="selo erro">Descartado</span>', falhou: '<span class="selo erro">Falhou</span>' }[c.estado] || "";
    $("#corte-selos").innerHTML = estadoSelo +
      `<span class="selo">${c.modo === "narrado" ? "Modo narrado" : "Áudio original"}</span>` +
      `<span class="selo">${Math.round(c.duracao_s)} s</span>`;
    $("#corte-titulo").textContent = c.titulo;
    const nota = $("#corte-nota");
    nota.style.setProperty("--p", c.nota); nota.style.setProperty("--cor", corDaNota(c.nota));
    nota.firstElementChild.textContent = c.nota;
    $("#corte-nota-texto").textContent = c.nota >= 80 ? "Corte forte" : c.nota >= 65 ? "Corte bom" : "Corte mediano";
    $("#corte-motivo").textContent = c.motivo;
    $("#corte-fonte").innerHTML = `<b>${esc(c.canal || "Canal desconhecido")}</b><br><span class="dica">${esc(c.video_titulo)}</span>`;
    $("#corte-original").href = c.video_url;
    $("#corte-baixar").href = c.midia || "#";
    $("#corte-baixar").setAttribute("download", `corte_${c.id}.mp4`);
    $("#corte-aprovar").disabled = c.estado === "aprovado";
    $("#corte-aprovar").hidden = c.estado === "aprovado";
    $("#corte-agendar").hidden = c.estado !== "aprovado";
    $("#corte-descartar").disabled = c.estado === "descartado";

    const narrando = Painel.fila().some((i) => i.tipo === "narrar" && i.alvo === String(c.id) && ["aguardando", "processando"].includes(i.estado));
    const botaoVoz = $("#corte-narrar"), textoVoz = $("#corte-voz-texto");
    if (narrando) {
      textoVoz.textContent = "Na fila: a narração está sendo feita…"; botaoVoz.disabled = true;
      botaoVoz.lastElementChild.textContent = "Narrando";
    } else if (c.narracao === "narrado") {
      textoVoz.innerHTML = "Este corte já tem <b>voz</b>. Você pode refazer o roteiro e a gravação."; botaoVoz.disabled = false;
      botaoVoz.lastElementChild.textContent = "Refazer";
    } else {
      textoVoz.innerHTML = c.narracao === "falhou" ? "A última tentativa de narrar falhou. Tente de novo."
        : "Sem narração. Narrar custa cerca de <b>US$ 0,10</b> de voz mais 1 centavo de IA.";
      botaoVoz.disabled = false; botaoVoz.lastElementChild.textContent = "Narrar";
    }
    iniciarModelo(c, novoVideo);
  }

  // ---------- postar com template (frase do gancho + modelo, sem sair da janela) ----------

  const modelo = { templates: null, templateId: null, corteId: null, frase: "", gerandoFrases: false, carregandoFrase: false,
                   enviando: false, saidas: [], relogio: null, relogioPrevia: null };
  try { modelo.templateId = Number(localStorage.getItem("canal_modelo_template")) || null; } catch (e) { /* sem memória do navegador: tudo bem */ }
  const caixaModelo = $("#corte-modelo");

  async function carregarTemplatesDoModelo() {
    try {
      const { templates } = await api("/api/templates");
      modelo.templates = templates.filter((t) => t.layout !== "cheio");
    } catch (e) { modelo.templates = []; }
    if (!modelo.templates.some((t) => t.id === modelo.templateId)) modelo.templateId = modelo.templates.length ? modelo.templates[0].id : null;
    if (estado.aberto) desenharModelo();
  }

  async function carregarSaidasDoModelo() {
    const id = modelo.corteId;
    clearTimeout(modelo.relogio);
    try {
      const r = await api(`/api/cortes/${id}/modelo/saidas`);
      if (modelo.corteId !== id) return;
      modelo.saidas = r.saidas;
    } catch (e) { return; }
    desenharModelo();
    if (modelo.saidas.some((s) => ["aguardando", "renderizando"].includes(s.estado)) && estado.aberto === id) {
      modelo.relogio = setTimeout(carregarSaidasDoModelo, 3000);
    }
  }

  function urlPrevia(templateId) {
    return `/api/cortes/${modelo.corteId}/modelo/previa.jpg?template_id=${templateId}&frase=${encodeURIComponent(modelo.frase)}`;
  }

  /** Atualiza as miniaturas de todos os templates com a frase atual (espera um instante enquanto se digita). */
  function previaDoModelo(esperar = 700) {
    clearTimeout(modelo.relogioPrevia);
    modelo.relogioPrevia = setTimeout(() => {
      if (modelo.carregandoFrase) return;
      caixaModelo.querySelectorAll("[data-previa-template]").forEach((img) => {
        const nova = new Image();
        img.style.opacity = .5;
        nova.onload = () => { img.src = nova.src; img.style.opacity = 1; img.hidden = false; img.nextElementSibling.style.display = "none"; };
        nova.onerror = () => { img.style.opacity = .25; };
        nova.src = urlPrevia(img.dataset.previaTemplate);
      });
      atualizarVisualizacao();
    }, esperar);
  }

  function itemDoModelo(s) {
    const texto = `<div style="min-width:0;flex:1"><b style="display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(s.frase)}">${esc(s.frase)}</b><span class="dica">${esc(s.template)}</span>`;
    if (s.estado === "pronto") {
      return `<video src="${s.url}" muted playsinline preload="metadata" controls style="width:64px;height:114px;border-radius:8px;background:#000;flex:none"></video>
        ${texto}</div>
        <button class="botao pequeno primario" data-modelo-agendar="${s.id}">${icone("calendario")}Agendar</button>
        <a class="botao pequeno" href="${s.url}?baixar=1" download title="Baixar o vídeo">${icone("baixar")}</a>`;
    }
    if (s.estado === "falhou") {
      return `${texto}<br><span class="dica" style="color:#e5484d">${esc(s.erro || "Não deu certo.")}</span></div>
        <button class="botao pequeno" data-modelo-refazer="${s.id}">Tentar de novo</button>`;
    }
    return `${texto}<br><span class="dica">Gerando o vídeo… pode levar uns 15 segundos.</span></div>`;
  }

  function desenharModelo() {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    const bloco = $("#corte-modelo-bloco");
    const pode = c && c.midia && !["falhou", "descartado"].includes(c.estado);
    bloco.hidden = !pode;
    if (!pode) return;
    if (modelo.templates === null) { caixaModelo.innerHTML = '<span class="dica">Carregando seus templates…</span>'; return; }
    if (!modelo.templates.length) {
      caixaModelo.innerHTML = '<p class="dica">Você ainda não tem template. <a href="/templates">Crie um em Templates</a> e ele aparece aqui.</p>';
      return;
    }
    const itens = modelo.saidas.map((s) => `<div style="display:flex;gap:10px;align-items:center;padding:8px 0;border-top:1px solid var(--linha)">${itemDoModelo(s)}</div>`).join("");
    const miniaturas = modelo.templates.map((t) => {
      const escolhido = t.id === modelo.templateId;
      const pronta = !modelo.carregandoFrase;
      return `<button type="button" data-escolher-template="${t.id}" aria-pressed="${escolhido}" title="${esc(t.nome)} · ${esc(t.layout_nome)}"
          style="flex:none;width:96px;padding:4px;border-radius:12px;background:none;cursor:pointer;text-align:center;border:2px solid ${escolhido ? "var(--acento)" : "transparent"}">
        <div style="position:relative;width:88px;height:156px;border-radius:8px;background:#0002;overflow:hidden">
          <img data-previa-template="${t.id}" onload="this.nextElementSibling.style.display='none'" ${pronta ? `src="${urlPrevia(t.id)}"` : "hidden"} alt="" width="88" height="156" style="width:100%;height:100%;object-fit:cover;transition:opacity .2s">
          <span class="dica" style="position:absolute;inset:0;display:${pronta ? "none" : "flex"};align-items:center;justify-content:center;font-size:11px">carregando…</span>
        </div>
        <span class="dica" style="display:block;margin-top:4px;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.nome)}${escolhido ? " ✓" : ""}</span>
      </button>`;
    }).join("");
    caixaModelo.innerHTML = `
      <div style="display:grid;gap:10px">
        <div id="modelo-miniaturas" style="display:flex;gap:6px;overflow-x:auto;padding-bottom:4px">${miniaturas}</div>
        <textarea class="campo" id="modelo-frase" maxlength="240" rows="2" placeholder="${modelo.carregandoFrase ? "Escrevendo a frase do gancho…" : "Frase do gancho: aparece escrita no vídeo"}">${esc(modelo.frase)}</textarea>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="botao pequeno" id="modelo-sugerir" ${modelo.gerandoFrases || modelo.carregandoFrase ? "disabled" : ""}>${modelo.gerandoFrases ? "Escrevendo…" : "Outra frase"}</button>
          <button class="botao primario pequeno" id="modelo-gerar" ${modelo.enviando ? "disabled" : ""}>Gerar vídeo</button></div>
        <span class="dica">Clique no template que você gostou e gere o vídeo. A frase foi escrita pela IA (uma fração de centavo); você pode editar.</span>
      </div>
      ${itens ? `<div style="margin-top:10px">${itens}</div>` : ""}`;
    atualizarVisualizacao();
  }

  // ---------- o vídeo grande: com o template escolhido ou o original ----------

  const previaGrande = $("#player-previa"), avisoVideo = $("#player-aviso");
  const visual = { modo: "template" };
  try { if (localStorage.getItem("canal_modo_video") === "original") visual.modo = "original"; } catch (e) { /* ok */ }

  const normal = (texto) => String(texto || "").trim().split(/\s+/).join(" ");

  /** O vídeo pronto deste corte no template escolhido (de preferência com a frase atual). */
  function saidaEscolhida() {
    const prontas = modelo.saidas.filter((s) => s.estado === "pronto" && s.template_id === modelo.templateId);
    return prontas.find((s) => normal(s.frase) === normal(modelo.frase)) || prontas[0] || null;
  }

  function atualizarVisualizacao() {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    if (!c) return;
    const comTemplate = !!(c.midia && modelo.templates && modelo.templates.length && modelo.templateId
                           && !["falhou", "descartado"].includes(c.estado) && modelo.corteId === c.id);
    $("#video-modos").hidden = !comTemplate;
    document.querySelectorAll("[data-modo-video]").forEach((b) => b.classList.toggle("ativo", b.dataset.modoVideo === visual.modo));
    let fonte = c.midia || "", imagem = null;
    if (comTemplate && visual.modo === "template") {
      const s = saidaEscolhida();
      if (s) fonte = s.url;
      else if (!modelo.carregandoFrase) imagem = urlPrevia(modelo.templateId);
    }
    if (imagem) {
      player.pause(); player.hidden = true; previaGrande.hidden = false;
      if (previaGrande.dataset.src !== imagem) {
        previaGrande.dataset.src = imagem;
        previaGrande.style.opacity = .6;
        previaGrande.onload = () => { previaGrande.style.opacity = 1; };
        previaGrande.src = imagem;
      }
      const naFila = modelo.saidas.some((s) => s.template_id === modelo.templateId && ["aguardando", "renderizando"].includes(s.estado));
      avisoVideo.textContent = naFila ? "Gerando o vídeo neste template… ele aparece aqui quando ficar pronto."
        : "Prévia do template. Clique em “Gerar vídeo” para assistir com ele.";
      avisoVideo.hidden = false;
    } else {
      previaGrande.hidden = true; avisoVideo.hidden = true; player.hidden = false;
      if (fonte && !player.src.endsWith(fonte)) { player.src = fonte; player.play().catch(() => {}); }
    }
  }

  $("#video-modos").addEventListener("click", (e) => {
    const b = e.target.closest("[data-modo-video]");
    if (!b) return;
    visual.modo = b.dataset.modoVideo;
    try { localStorage.setItem("canal_modo_video", visual.modo); } catch (x) { /* ok */ }
    atualizarVisualizacao();
  });

  /** Chamada pelo preencherModal a cada corte aberto. */
  function iniciarModelo(c, novoVideo) {
    if (novoVideo || modelo.corteId !== c.id) {
      clearTimeout(modelo.relogio);
      const fraseGuardada = c.frase_gancho || (c.pronta && c.pronta.frase) || "";
      Object.assign(modelo, { corteId: c.id, frase: fraseGuardada, saidas: [], gerandoFrases: false, enviando: false,
                              carregandoFrase: !!c.midia && !fraseGuardada });
      if (c.pronta && (!modelo.templates || modelo.templates.some((t) => t.id === c.pronta.template_id))) modelo.templateId = c.pronta.template_id;
      if (c.midia) { carregarSaidasDoModelo(); if (!fraseGuardada) carregarFraseAuto(c.id); }
    }
    if (modelo.templates === null) carregarTemplatesDoModelo();
    if (!caixaModelo.querySelector("#modelo-miniaturas") || novoVideo) desenharModelo();
    else $("#corte-modelo-bloco").hidden = !(c.midia && !["falhou", "descartado"].includes(c.estado));
    atualizarVisualizacao();
  }

  /** A frase do gancho já pronta: a guardada, ou a IA escreve uma na primeira vez. */
  async function carregarFraseAuto(id) {
    try {
      const r = await api(`/api/cortes/${id}/modelo/frase-auto`, { metodo: "POST" });
      if (modelo.corteId === id) modelo.frase = r.frase;
      if (r.nova) Painel.atualizarGasto();
    } catch (erro) { /* sem frase: as prévias usam um texto de exemplo e ele escreve a sua */ }
    if (modelo.corteId !== id) return;
    modelo.carregandoFrase = false;
    desenharModelo();
  }

  async function gerarFrasesDoModelo() {
    const id = modelo.corteId;
    modelo.gerandoFrases = true; desenharModelo();
    try {
      const r = await api(`/api/cortes/${id}/modelo/frases`, { metodo: "POST", corpo: { quantidade: 1 } });
      if (modelo.corteId === id && r.frases[0]) modelo.frase = r.frases[0];
      Painel.atualizarGasto();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
    modelo.gerandoFrases = false;
    if (modelo.corteId === id) desenharModelo();
  }

  async function gerarVideoDoModelo(frase, templateId) {
    const id = modelo.corteId;
    if (!frase.trim()) { aviso("Escolha ou escreva a frase do gancho primeiro.", { tipo: "erro" }); return; }
    modelo.enviando = true; desenharModelo();
    try {
      const r = await api(`/api/cortes/${id}/modelo/gerar`, { metodo: "POST", corpo: { template_id: templateId, frase } });
      aviso(r.ja_existia ? "Esse vídeo já existe, está na lista abaixo." : "Gerando o vídeo. Ele aparece aqui embaixo.");
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
    modelo.enviando = false;
    if (modelo.corteId === id) await carregarSaidasDoModelo();
  }

  caixaModelo.addEventListener("input", (e) => {
    if (e.target.id !== "modelo-frase") return;
    modelo.frase = e.target.value;
    previaDoModelo(900);
  });
  caixaModelo.addEventListener("click", (e) => {
    const alvo = e.target.closest("button");
    if (!alvo) return;
    if (alvo.dataset.escolherTemplate) {
      modelo.templateId = Number(alvo.dataset.escolherTemplate);
      try { localStorage.setItem("canal_modelo_template", String(modelo.templateId)); } catch (x) { /* ok */ }
      caixaModelo.querySelectorAll("[data-escolher-template]").forEach((b) => {
        const ativo = Number(b.dataset.escolherTemplate) === modelo.templateId;
        b.setAttribute("aria-pressed", ativo);
        b.style.borderColor = ativo ? "var(--acento)" : "transparent";
        const nome = b.querySelector("span.dica:last-child");
        if (nome) nome.textContent = nome.textContent.replace(" ✓", "") + (ativo ? " ✓" : "");
      });
      atualizarVisualizacao();
    }
    else if (alvo.id === "modelo-sugerir") gerarFrasesDoModelo();
    else if (alvo.id === "modelo-gerar") gerarVideoDoModelo(modelo.frase, modelo.templateId);
    else if (alvo.dataset.modeloAgendar) { const sid = Number(alvo.dataset.modeloAgendar); fechar(); Agendar.abrir({ saidas: [sid] }); }
    else if (alvo.dataset.modeloRefazer) {
      const s = modelo.saidas.find((x) => x.id === Number(alvo.dataset.modeloRefazer));
      if (s) gerarVideoDoModelo(s.frase, s.template_id);
    }
  });
  document.addEventListener("fila:terminou", () => { if (estado.aberto && modelo.corteId === estado.aberto) carregarSaidasDoModelo(); });

  async function decidir(novo) {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    if (!c) return;
    const lista = filtrados();
    const indice = lista.findIndex((x) => x.id === c.id);
    const proximo = lista[indice + 1] || lista[indice - 1];
    if (await definirEstado([c.id], novo)) {
      // Fluxo de revisão: depois de decidir, já mostra o próximo da lista.
      const aindaNaLista = filtrados().some((x) => x.id === c.id);
      if (!aindaNaLista) {
        if (proximo && filtrados().some((x) => x.id === proximo.id)) { estado.aberto = proximo.id; preencherModal(true); }
        else fechar();
      }
    }
  }

  function navegar(passo) {
    const lista = filtrados();
    const indice = lista.findIndex((c) => c.id === estado.aberto);
    const alvo = lista[indice + passo];
    if (alvo) { estado.aberto = alvo.id; preencherModal(true); }
  }

  $("#corte-fechar").onclick = fechar;
  $("#corte-agendar").onclick = () => {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    const s = saidaEscolhida();
    const saidaId = s ? s.id : c && c.pronta ? c.pronta.saida_id : null;
    fechar();
    Agendar.abrir(saidaId ? { saidas: [saidaId] } : { cortes: [c.id] });
  };

  // ---------- preparar vários cortes com um template ----------

  async function abrirPreparar() {
    const escolhidos = [...estado.selecionados].map((id) => estado.cortes.find((c) => c.id === id))
      .filter((c) => c && c.midia && !["descartado", "falhou"].includes(c.estado));
    if (!escolhidos.length) { aviso("Nenhum dos cortes selecionados pode ser preparado.", { tipo: "erro" }); return; }
    if (modelo.templates === null) await carregarTemplatesDoModelo();
    if (!modelo.templates.length) { aviso("Crie um template primeiro, na tela Templates.", { tipo: "erro" }); return; }
    const exemplo = escolhidos[0];
    let escolhido = modelo.templates.some((t) => t.id === modelo.templateId) ? modelo.templateId : modelo.templates[0].id;
    const fundo = document.createElement("div");
    fundo.className = "fundo-modal aberto";
    const n = escolhidos.length;
    fundo.innerHTML = `<div class="modal estreito" style="position:relative;width:min(640px,100%)">
      <div class="modal-simples" style="padding:24px;display:grid;gap:14px">
        <h2 style="margin:0">Preparar ${n === 1 ? "1 corte" : `${n} cortes`} com template</h2>
        <p class="dica" style="margin:0">Escolha o template. Cada corte ganha a frase do gancho escrita pela IA (uma fração de centavo cada)
          e o vídeo pronto no template, que vai para <b>Prontos para agendar</b>. Leva cerca de 1 minuto por corte; pode continuar usando o painel.</p>
        <div class="grade-escolha">${modelo.templates.map((t) => `<button type="button" data-t="${t.id}" class="${t.id === escolhido ? "ativo" : ""}" title="${esc(t.nome)} · ${esc(t.layout_nome)}">
          <img loading="lazy" alt="" src="/api/cortes/${exemplo.id}/modelo/previa.jpg?template_id=${t.id}&frase=${encodeURIComponent(exemplo.frase_gancho || "")}">
          <span class="dica" style="display:block;margin-top:4px;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(t.nome)} · ${esc(t.layout_nome)}</span></button>`).join("")}</div>
        <div class="modal-acoes"><button class="botao" data-cancelar>Cancelar</button>
          <button class="botao primario" data-confirmar>${icone("check")}Preparar ${n === 1 ? "1 corte" : `${n} cortes`}</button></div>
      </div></div>`;
    document.body.appendChild(fundo);
    const fechar = () => fundo.remove();
    fundo.addEventListener("mousedown", (e) => { if (e.target === fundo) fechar(); });
    fundo.addEventListener("click", async (e) => {
      const t = e.target.closest("[data-t]");
      if (t) {
        escolhido = Number(t.dataset.t);
        fundo.querySelectorAll("[data-t]").forEach((b) => b.classList.toggle("ativo", b === t));
        return;
      }
      if (e.target.closest("[data-cancelar]")) { fechar(); return; }
      const confirmar = e.target.closest("[data-confirmar]");
      if (!confirmar) return;
      confirmar.disabled = true;
      try {
        // Preparar é decidir postar: o que ainda não estava aprovado passa a estar.
        const naoAprovados = escolhidos.filter((c) => c.estado !== "aprovado").map((c) => c.id);
        if (naoAprovados.length) await api("/api/cortes/estado", { metodo: "POST", corpo: { ids: naoAprovados, estado: "aprovado" } });
        const r = await api("/api/cortes/preparar", { metodo: "POST", corpo: { cortes: escolhidos.map((c) => c.id), template_id: escolhido } });
        modelo.templateId = escolhido;
        try { localStorage.setItem("canal_modelo_template", String(escolhido)); } catch (x) { /* ok */ }
        aviso(r.enfileirados
          ? `${r.enfileirados} corte(s) na fila para preparar.${r.pulados ? ` ${r.pulados} já estavam na fila ou não têm vídeo.` : ""} Eles vão para “Prontos para agendar”.`
          : "Esses cortes já estavam na fila.");
        fechar();
        estado.selecionados.clear();
        await carregar();
        if (r.enfileirados && Painel.abrirGaveta) Painel.abrirGaveta();
      } catch (erro) { aviso(erro.message, { tipo: "erro" }); confirmar.disabled = false; }
    });
  }
  $("#massa-preparar").onclick = abrirPreparar;
  $("#massa-agendar").onclick = () => {
    const todos = [...estado.selecionados].map((id) => estado.cortes.find((c) => c.id === id)).filter(Boolean);
    const preparando = todos.filter((c) => c.preparando && !c.pronta);
    if (preparando.length) aviso(`${preparando.length} corte(s) ainda estão sendo preparados e ficaram de fora. Agende quando aparecerem em “Prontos para agendar”.`);
    const escolhidos = todos.filter((c) => !preparando.includes(c));
    if (!escolhidos.length) return;
    const saidas = escolhidos.filter((c) => c.pronta && c.estado === "aprovado").map((c) => c.pronta.saida_id);   // já no template
    const cortes = escolhidos.filter((c) => !c.pronta && c.estado === "aprovado").map((c) => c.id);
    if (!saidas.length && !cortes.length) { aviso("Só cortes aprovados podem ser agendados. Aprove primeiro.", { tipo: "erro" }); return; }
    const fora = escolhidos.length - saidas.length - cortes.length;   // não aprovados
    if (fora) aviso(`${fora} corte(s) não aprovado(s) ficaram de fora.`);
    Agendar.abrir({ cortes, saidas });
  };
  modal.addEventListener("mousedown", (e) => { if (e.target === modal) fechar(); });
  $("#corte-aprovar").onclick = () => decidir("aprovado");
  $("#corte-descartar").onclick = () => decidir("descartado");
  $("#corte-credito").onclick = async () => {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    const texto = `Vídeo original: ${c.video_titulo} — ${c.canal} (${c.video_url})`;
    try { await navigator.clipboard.writeText(texto); aviso("Crédito copiado."); }
    catch (e) { aviso("Não consegui copiar. Selecione o texto na tela.", { tipo: "erro" }); }
  };
  $("#corte-narrar").onclick = async () => {
    const c = estado.cortes.find((x) => x.id === estado.aberto);
    $("#corte-narrar").disabled = true;
    try {
      await api(`/api/cortes/${c.id}/narrar`, { metodo: "POST" });
      aviso("Narração adicionada à fila.");
      Painel.abrirGaveta();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
    preencherModal();
  };
  document.addEventListener("fila:mudou", () => { if (estado.aberto) preencherModal(); });

  document.addEventListener("keydown", (e) => {
    if (!modal.classList.contains("aberto") || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toLowerCase();
    if (k === "a") decidir("aprovado");
    else if (k === "d") decidir("descartado");
    else if (e.key === "ArrowRight") navegar(1);
    else if (e.key === "ArrowLeft") navegar(-1);
    else if (e.key === "Escape") fechar();
  });

  // Primeira carga: mostra esqueletos enquanto espera.
  grade.innerHTML = Array.from({ length: 6 }, () => '<div class="esqueleto"></div>').join("");
  carregar();
})();
