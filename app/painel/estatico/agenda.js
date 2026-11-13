/* Tela Agenda: publicações por dia, com editar, publicar agora, cancelar e tentar de novo. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  const NOMES_REDE = { youtube: "YouTube", instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok" };
  const ESTADO = {
    agendada: ['<span class="selo acento">Agendada</span>'], publicando: ['<span class="selo aviso">Publicando…</span>'],
    publicada: ['<span class="selo ok">Publicada</span>'], falhou: ['<span class="selo erro">Falhou</span>'],
    cancelada: ['<span class="selo">Cancelada</span>'],
  };
  let dados = null, filtroEstado = "proximas", filtroConta = "", busca = "", relogio = null, editando = null;

  const dia = (iso) => iso.slice(0, 10);
  function nomeDoDia(chave) {
    const hoje = new Date(); const d = new Date(chave + "T12:00:00");
    const diff = Math.round((d - new Date(hoje.toDateString() + " 12:00")) / 864e5);
    const texto = d.toLocaleDateString("pt-BR", { weekday: "long", day: "2-digit", month: "long" });
    const comMaiuscula = texto.charAt(0).toUpperCase() + texto.slice(1);
    return diff === 0 ? `Hoje · ${texto}` : diff === 1 ? `Amanhã · ${texto}` : diff === -1 ? `Ontem · ${texto}` : comMaiuscula;
  }

  function filtradas() {
    return dados.publicacoes.filter((p) => {
      if (filtroConta && String(p.conta_id) !== filtroConta) return false;
      if (busca && !(p.titulo + " " + p.conta).toLowerCase().includes(busca)) return false;
      if (filtroEstado === "proximas") return ["agendada", "publicando"].includes(p.estado);
      if (filtroEstado === "problema") return p.estado === "falhou" || (p.estado === "agendada" && p.erro);
      if (filtroEstado === "publicada") return p.estado === "publicada";
      return true;
    });
  }

  function cartao(p) {
    const hora = p.quando.slice(11, 16);
    const aviso = p.erro ? `<small style="color:${p.estado === "publicada" ? "var(--suave)" : "var(--erro)"}">${esc(p.erro)}${p.proxima_tentativa ? ` · nova tentativa às ${p.proxima_tentativa.slice(11, 16)}` : ""}</small>` : "";
    const acoes = ["agendada", "falhou"].includes(p.estado) ? `
      <button class="botao pequeno" data-acao="agora" title="Publicar agora">${icone("play")}${p.estado === "falhou" ? "Tentar de novo" : "Agora"}</button>
      <button class="botao pequeno fantasma" data-acao="editar">${icone("lapis")}Editar</button>
      <button class="mini no" data-acao="cancelar" title="Cancelar" aria-label="Cancelar">${icone("x")}</button>`
      : p.url ? `<a class="botao pequeno" href="${esc(p.url)}" target="_blank" rel="noopener">${icone("ext")}Ver post</a>` : "";
    return `<div class="post" data-id="${p.id}">
      <div class="post-hora">${hora}</div>
      <img class="post-mini" src="${p.miniatura}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
      <div class="post-info"><div><span class="rede ${p.rede}">${NOMES_REDE[p.rede]}</span> <b>${esc(p.conta)}</b> ${ESTADO[p.estado][0]}</div>
        <div class="post-titulo" title="${esc(p.titulo)}">${esc(p.titulo)}</div>${aviso}</div>
      <div class="post-acoes">${acoes}</div></div>`;
  }

  function desenhar() {
    const agendadas = dados.publicacoes.filter((p) => p.estado === "agendada").length;
    $("#n-agendadas").textContent = agendadas;
    $("#n-publicadas").textContent = dados.publicacoes.filter((p) => p.estado === "publicada").length;
    $("#n-falhas").textContent = dados.publicacoes.filter((p) => p.estado === "falhou" || (p.estado === "agendada" && p.erro)).length;

    const contas = new Map(dados.publicacoes.map((p) => [String(p.conta_id), p.conta]));
    const select = $("#filtro-conta");
    if (select.options.length - 1 !== contas.size) {
      select.innerHTML = '<option value="">Todas as contas</option>' + [...contas].map(([id, nome]) => `<option value="${id}">${esc(nome)}</option>`).join("");
      select.value = filtroConta;
    }

    const lista = filtradas();
    if (!lista.length) {
      $("#dias").innerHTML = `<div class="cartao vazio"><h2>${dados.tem_contas ? "Nada por aqui" : "Conecte uma conta para começar"}</h2>
        <p>${dados.tem_contas ? "Aprove cortes na tela Cortes e clique em Agendar, ou agende os vídeos gerados nos Templates." : "As publicações aparecem aqui depois que você conectar uma rede social."}</p>
        ${dados.tem_contas ? '<a class="botao primario" href="/cortes">Ir para Cortes</a>' : '<a class="botao primario" href="/contas">Conectar contas</a>'}</div>`;
      return;
    }
    const grupos = new Map();
    for (const p of filtroEstado === "publicada" ? lista.slice().reverse() : lista) {
      if (!grupos.has(dia(p.quando))) grupos.set(dia(p.quando), []);
      grupos.get(dia(p.quando)).push(p);
    }
    $("#dias").innerHTML = [...grupos].map(([chave, itens]) => `<section class="cartao dia-agenda">
      <h3>${nomeDoDia(chave)} <span class="dica" style="font-weight:500">· ${itens.length} post${itens.length > 1 ? "s" : ""}</span></h3>
      ${itens.map(cartao).join("")}</section>`).join("");
  }

  async function carregar() {
    clearTimeout(relogio);
    try { dados = await api("/api/agenda?dias=21&passados=3"); desenhar(); }
    catch (erro) { $("#dias").innerHTML = `<div class="cartao vazio"><h2>Não consegui carregar</h2><p>${esc(erro.message)}</p></div>`; }
    relogio = setTimeout(carregar, dados && dados.publicacoes.some((p) => p.estado === "publicando") ? 5000 : 20000);
  }

  $("#filtro-estado").addEventListener("click", (e) => {
    const b = e.target.closest(".aba"); if (!b) return;
    filtroEstado = b.dataset.estado;
    document.querySelectorAll("#filtro-estado .aba").forEach((x) => x.classList.toggle("ativa", x === b));
    desenhar();
  });
  $("#filtro-conta").onchange = (e) => { filtroConta = e.target.value; desenhar(); };
  document.addEventListener("busca", (e) => { busca = e.detail; if (dados) desenhar(); });
  document.addEventListener("agenda:mudou", carregar);

  $("#dias").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-acao]"); if (!b) return;
    const id = Number(b.closest("[data-id]").dataset.id);
    const p = dados.publicacoes.find((x) => x.id === id);
    try {
      if (b.dataset.acao === "agora") { await api(`/api/publicacoes/${id}/agora`, { metodo: "POST" }); aviso("Vai sair em até meio minuto."); }
      if (b.dataset.acao === "cancelar") {
        if (!confirm(`Cancelar a publicação em ${p.conta}?`)) return;
        await api(`/api/publicacoes/${id}/cancelar`, { metodo: "POST" }); aviso("Publicação cancelada.");
      }
      if (b.dataset.acao === "editar") { abrirEdicao(p); return; }
      carregar();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  });

  // ---------- edição ----------
  const modal = $("#modal-editar");
  function abrirEdicao(p) {
    editando = p;
    $("#ed-titulo").value = p.titulo; $("#ed-legenda").value = p.legenda; $("#ed-horario").value = p.quando;
    $("#ed-erro").textContent = "";
    modal.classList.add("aberto");
  }
  const fecharEdicao = () => modal.classList.remove("aberto");
  $("#ed-cancelar").onclick = fecharEdicao;
  modal.addEventListener("mousedown", (e) => { if (e.target === modal) fecharEdicao(); });
  $("#form-editar").onsubmit = async (e) => {
    e.preventDefault();
    const corpo = { titulo: $("#ed-titulo").value, legenda: $("#ed-legenda").value };
    if ($("#ed-horario").value !== editando.quando) corpo.horario = $("#ed-horario").value;
    try { await api(`/api/publicacoes/${editando.id}`, { metodo: "PUT", corpo }); fecharEdicao(); aviso("Publicação atualizada."); carregar(); }
    catch (erro) { $("#ed-erro").textContent = erro.message; }
  };

  carregar();
})();
