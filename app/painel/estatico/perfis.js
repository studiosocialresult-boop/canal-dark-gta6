/* Tela Perfis: busca um canal do YouTube, ordena os vídeos e manda os escolhidos para Cortes ou para a biblioteca. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  const estado = { dados: null, aba: "videos", ordem: "views", selecionados: new Set(), busca: "" };
  const grade = $("#posts");

  const compacto = (n) => n == null ? "—" : n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(".", ",") + " mi"
    : n >= 1e3 ? Math.round(n / 1e3) + " mil" : String(n);
  const duracao = (s) => { if (!s) return ""; const m = Math.floor(s / 60), r = Math.round(s % 60); return `${m}:${String(r).padStart(2, "0")}`; };
  const quando = (iso) => {
    if (!iso) return "";
    const h = (Date.now() - new Date(iso)) / 36e5;
    if (h < 1) return "agora há pouco";
    if (h < 24) return `há ${Math.floor(h)} h`;
    if (h < 24 * 30) return `há ${Math.floor(h / 24)} dias`;
    const meses = Math.floor(h / 24 / 30);
    return meses < 12 ? `há ${meses} ${meses > 1 ? "meses" : "mês"}` : `há ${Math.floor(meses / 12)} ano${meses >= 24 ? "s" : ""}`;
  };

  function ordenados() {
    let lista = estado.dados.posts.slice();
    if (estado.busca) lista = lista.filter((p) => p.titulo.toLowerCase().includes(estado.busca));
    const por = {
      views: (a, b) => (b.views ?? -1) - (a.views ?? -1),
      recentes: (a, b) => a.ordem - b.ordem,
      velocidade: (a, b) => (b.velocidade ?? -1) - (a.velocidade ?? -1) || a.ordem - b.ordem,
    }[estado.ordem];
    return lista.sort(por);
  }

  function cartao(p) {
    const marcado = estado.selecionados.has(p.id);
    return `<article class="corte ${marcado ? "selecionado" : ""}" data-id="${p.id}">
      <div class="corte-imagem"><img src="${p.miniatura}" alt="" loading="lazy">
        <div class="corte-topo"><span class="tag">${icone("play", "width:11px;height:11px;vertical-align:-1px")} ${compacto(p.views)}</span>
          <div class="espaco caixa-selecao" data-selecionar>${icone("check")}</div></div>
        ${p.duracao_s ? `<span class="tag" style="position:absolute;right:8px;bottom:62px;z-index:2">${duracao(p.duracao_s)}</span>` : ""}
        <div class="corte-titulo">${esc(p.titulo)}</div></div>
      <div class="corte-pe"><div class="corte-fonte">${p.velocidade != null ? `<b>${compacto(Math.round(p.velocidade))}/h</b> · ` : ""}${esc(quando(p.publicado)) || "&nbsp;"}</div>
        <a class="mini" href="${p.url}" target="_blank" rel="noopener" title="Ver no YouTube" onclick="event.stopPropagation()">${icone("ext")}</a></div></article>`;
  }

  function desenhar() {
    if (!estado.dados) return;
    const lista = ordenados();
    grade.innerHTML = lista.length ? lista.map(cartao).join("") : '<div class="cartao vazio" style="grid-column:1/-1"><h2>Nada encontrado</h2></div>';
    const n = estado.selecionados.size;
    $("#contagem-selecao").textContent = n ? `${n} selecionado${n > 1 ? "s" : ""}` : "Nenhum selecionado";
    $("#baixar-sel").disabled = $("#enviar-cortes").disabled = n === 0;
    const c = estado.dados.canal;
    $("#canal-info").innerHTML = `<b>${esc(c.nome)}</b> <span class="dica">${esc(c.arroba || "")} · ${estado.dados.posts.length} vídeos</span>`;
  }

  async function buscar(e) {
    e.preventDefault();
    const botao = $("#buscar-perfil"), erro = $("#erro-perfil");
    erro.textContent = ""; botao.disabled = true; botao.lastChild.textContent = "Buscando…";
    grade.innerHTML = Array.from({ length: 6 }, () => '<div class="esqueleto"></div>').join("");
    $("#resultado").hidden = false; $("#vazio-perfil").hidden = true;
    try {
      estado.dados = await api("/api/perfis/buscar", { metodo: "POST", corpo: { alvo: $("#alvo").value, aba: estado.aba } });
      estado.selecionados.clear();
      desenhar();
    } catch (falha) {
      erro.textContent = falha.message;
      $("#resultado").hidden = !estado.dados; $("#vazio-perfil").hidden = !!estado.dados;
      if (estado.dados) desenhar();
    } finally { botao.disabled = false; botao.lastChild.textContent = "Buscar perfil"; }
  }
  $("#form-perfil").addEventListener("submit", buscar);

  $("#aba-perfil").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    estado.aba = b.dataset.aba;
    document.querySelectorAll("#aba-perfil button").forEach((x) => x.classList.toggle("ativo", x === b));
    if ($("#alvo").value.trim()) $("#form-perfil").requestSubmit();
  });
  $("#ordem-perfil").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    estado.ordem = b.dataset.ordem;
    document.querySelectorAll("#ordem-perfil button").forEach((x) => x.classList.toggle("ativo", x === b));
    desenhar();
  });
  grade.addEventListener("click", (e) => {
    const c = e.target.closest(".corte"); if (!c) return;
    const id = c.dataset.id;
    if (estado.selecionados.has(id)) estado.selecionados.delete(id); else estado.selecionados.add(id);
    desenhar();
  });
  $("#todos").onclick = () => { ordenados().forEach((p) => estado.selecionados.add(p.id)); desenhar(); };
  $("#limpar").onclick = () => { estado.selecionados.clear(); desenhar(); };
  document.addEventListener("busca", (e) => { estado.busca = e.detail; desenhar(); });

  async function enviar(caminho, corpoExtra, texto) {
    const escolhidos = estado.dados.posts.filter((p) => estado.selecionados.has(p.id));
    try {
      const r = await api(caminho, { metodo: "POST", corpo: { urls: escolhidos.map((p) => p.url), titulos: Object.fromEntries(escolhidos.map((p) => [p.url, p.titulo])), ...corpoExtra } });
      const novos = r.na_fila, repetidos = r.ja_processados ?? r.ja_tem ?? 0;
      aviso(`${novos} ${texto}${repetidos ? ` (${repetidos} já estavam)` : ""}.`);
      estado.selecionados.clear(); desenhar();
      if (novos) Painel.abrirGaveta();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }
  $("#enviar-cortes").onclick = () => enviar("/api/perfis/enviar-cortes", {}, "vídeo(s) na fila para virar cortes");
  $("#baixar-sel").onclick = () => enviar("/api/perfis/baixar", {}, "vídeo(s) na fila para baixar");
})();
