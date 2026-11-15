/* Tela Desempenho: totais, o que está funcionando e os melhores e piores posts. */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  const NOMES_REDE = { youtube: "YouTube", instagram: "Instagram Reels", facebook: "Facebook Reels", tiktok: "TikTok" };
  const NOMES_GRUPO = { modo: "Modo", nota: "Nota", rede: "Rede", fonte: "Fonte", tipo: "Tipo", hora: "Horário" };
  const MEDIDAS = [["visualizacoes", "Visualizações"], ["curtidas", "Curtidas"], ["comentarios", "Comentários"]];
  let dias = 7, medida = "visualizacoes", conta = "", contasCarregadas = false;

  const numero = (n) => (n === null || n === undefined ? "—" : n.toLocaleString("pt-BR"));

  function cartoes(t) {
    const cores = { visualizacoes: "var(--acento)", curtidas: "var(--acento-2)", comentarios: "var(--ok)" };
    const variacao = t.variacao_pct === null ? "" :
      `<em style="color:${t.variacao_pct >= 0 ? "var(--ok)" : "var(--erro)"}">${t.variacao_pct >= 0 ? "▲" : "▼"} ${numero(Math.abs(t.variacao_pct))}% sobre o período anterior</em>`;
    const horario = t.melhor_horario ? `${t.melhor_horario.inicio_h}h às ${t.melhor_horario.fim_h}h` : "poucos dados";
    const unico = (rotulo, valor, cor, extra = "") =>
      `<div class="cartao numero"><div class="brilho" style="background:${cor}"></div><small>${rotulo}</small><strong>${valor}</strong>${extra}</div>`;
    return MEDIDAS.map(([id, nome]) => unico(nome, numero(t[id]), cores[id], id === medida ? variacao : "")).join("") +
      unico("Posts", numero(t.posts), "var(--aviso)") +
      unico("Melhor horário", horario, "var(--acento)");
  }

  function linhaGrupo(nome, itens) {
    if (nome === "hora") {
      const maior = Math.max(1, ...itens.map((i) => i.media || 0));
      return `<div class="grupo-linha"><b>${NOMES_GRUPO[nome]}</b><div class="barras-hora">` + itens.map((i) =>
        `<div class="barra-hora" title="${i.rotulo}h: ${i.media === null ? "poucos dados" : numero(i.media)} (${i.posts} posts)">
          <span style="height:${i.media === null ? 0 : Math.max(4, Math.round(i.media / maior * 100))}%"></span><small>${i.rotulo}</small></div>`).join("") + "</div></div>";
    }
    const chips = itens.length ? itens.map((i) =>
      `<span class="chip-grupo"><b>${esc(i.rotulo)}</b> ${i.media === null ? "<em>poucos dados</em>" : numero(i.media)} <small>${numero(i.posts)} posts</small></span>`
    ).join("") : '<span class="dica">sem posts</span>';
    return `<div class="grupo-linha"><b>${NOMES_GRUPO[nome]}</b><div class="chips-grupo">${chips}</div></div>`;
  }

  function tabela(posts) {
    if (!posts.length) return '<div class="vazio-pequeno">Nada por aqui ainda.</div>';
    return `<div class="tabela-posts"><div class="linha-post cabeca"><span></span><span>24 h</span><span>3 dias</span><span>7 dias</span><span>Agora</span></div>` +
      posts.map((p) => `
        <div class="linha-post">
          <span class="titulo-post">
            <a href="${esc(p.url || "#")}" target="_blank" rel="noopener">${esc(p.titulo)}</a>
            <small>${esc(NOMES_REDE[p.rede] || p.rede)} · ${esc(p.conta)} ${p.removido ? '<span class="selo">removido</span>' : ""}
              ${p.corte_id ? '· <a href="/cortes">ver corte</a>' : ""}</small>
          </span>
          <span>${numero(p["24h"])}</span><span>${numero(p["3d"])}</span><span>${numero(p["7d"])}</span><span>${numero(p.atual)}</span>
        </div>`).join("") + "</div>";
  }

  function desenhar(d) {
    if (!contasCarregadas) {
      contasCarregadas = true;
      $("#filtro-conta").insertAdjacentHTML("beforeend",
        d.contas.map((c) => `<option value="${c.id}">${esc(c.nome)} (${esc(NOMES_REDE[c.rede] || c.rede)})</option>`).join(""));
    }
    $("#cartoes").innerHTML = cartoes(d.totais);
    const vazio = d.totais.posts === 0;
    $("#vazio").innerHTML = vazio ? '<div class="cartao vazio-pequeno">Ainda não há números. Os primeiros aparecem cerca de uma hora depois que um post é publicado.</div>' : "";
    for (const id of ["grupos-cartao", "melhores-cartao", "piores-cartao"]) $("#" + id).hidden = vazio;
    $("#aviso-sem-medida").innerHTML = d.sem_medida.length
      ? `<div class="aviso-caixa" style="margin-bottom:16px">${icone("alerta")}<span>${d.sem_medida.map((r) => esc(NOMES_REDE[r] || r)).join(" e ")} ainda não informam visualizações. Troque para Curtidas ou Comentários para ver essas redes.</span></div>`
      : "";
    $("#grupos").innerHTML = Object.keys(NOMES_GRUPO).map((g) => linhaGrupo(g, d.grupos[g])).join("");
    $("#melhores").innerHTML = tabela(d.melhores);
    $("#piores").innerHTML = tabela(d.piores);
  }

  async function carregar() {
    try {
      const consulta = new URLSearchParams({ dias, medida, conta_id: conta });
      desenhar(await api("/api/desempenho?" + consulta));
    } catch (e) { aviso(e.message, { tipo: "erro" }); }
  }

  function aba(seletor, atributo, aoMudar) {
    $(seletor).addEventListener("click", (e) => {
      const botao = e.target.closest(".aba"); if (!botao) return;
      $(seletor).querySelectorAll(".aba").forEach((b) => b.classList.toggle("ativa", b === botao));
      aoMudar(botao.dataset[atributo]); carregar();
    });
  }
  aba("#sel-periodo", "dias", (v) => { dias = Number(v); });
  aba("#sel-medida", "medida", (v) => { medida = v; });
  $("#filtro-conta").addEventListener("change", (e) => { conta = e.target.value; carregar(); });

  $("#atualizar").addEventListener("click", async () => {
    const botao = $("#atualizar"), texto = botao.querySelector("span");
    botao.disabled = true; texto.textContent = "Lendo os números…";
    try {
      const r = await api("/api/desempenho/atualizar", { metodo: "POST" });
      if (r.ocupado) aviso("Já existe uma leitura em andamento.");
      else aviso(`Pronto: ${r.lidas} posts lidos.${r.falhas ? ` ${r.falhas} conta(s) com problema.` : ""}`);
      await carregar();
    } catch (e) { aviso(e.message, { tipo: "erro" }); }
    botao.disabled = false; texto.textContent = "Atualizar agora";
  });

  carregar();
})();
