/* Assistente de Templates: 7 passos com prévia ao vivo (a prévia é desenhada pelo servidor,
   com o mesmo código que gera o vídeo final: o que você vê é o que sai). */
"use strict";

(() => {
  const { $, esc, icone, api, aviso } = Painel;
  const ID = window.TEMPLATE_ID;
  const NOMES = ["Perfil", "Zonas", "Frases", "Mídia", "Estilo", "Variações", "Gerar"];

  let T = null;                  // dados do template (veio do servidor)
  let passo = 1;
  let previaFrase = 0, previaMidia = 0, midiaEmEdicao = null, textoDigitado = "";
  let cortesDoCanal = null, bibliotecaVideos = null, sugestoes = [], saidas = null, relogioSaidas = null;
  let pendente = {}, relogioSalvar = null, relogioPrevia = null;
  const temporizadores = {};

  const painel = $("#passo");
  const cfg = (secao, chave) => T.config[secao][chave];
  const midiasZona = (z) => T.midias.filter((m) => m.zona === z);
  const frasesEscolhidas = () => T.frases.filter((f) => f.selecionada);

  // ---------- salvar e prévia ----------

  /** Guarda uma mudança de configuração e redesenha a prévia (com pequena espera, para sliders). */
  function mudar(secao, chave, valor) {
    T.config[secao][chave] = valor;
    (pendente[secao] ||= {})[chave] = valor;
    clearTimeout(relogioSalvar);
    relogioSalvar = setTimeout(guardar, 320);
  }

  async function guardar() {
    if (!Object.keys(pendente).length) return atualizarPrevia();
    const config = pendente; pendente = {};
    try {
      await api(`/api/templates/${ID}`, { metodo: "PUT", corpo: { config } });
      atualizarPrevia();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }

  function atualizarPrevia() {
    clearTimeout(relogioPrevia);
    relogioPrevia = setTimeout(() => {
      const escolhidas = frasesEscolhidas();
      const midias = midiasZona(1).filter((m) => m.selecionada);
      if (previaFrase >= escolhidas.length) previaFrase = 0;
      if (previaMidia >= midias.length) previaMidia = 0;
      const midia = midiaEmEdicao && T.midias.find((m) => m.id === midiaEmEdicao && m.zona === 1) || midias[previaMidia];
      const texto = textoDigitado || (escolhidas[previaFrase] ? escolhidas[previaFrase].texto : "");
      const url = `/api/templates/${ID}/previa.jpg?frase=${encodeURIComponent(texto)}` +
        `${midia ? "&midia=" + midia.id : ""}&v=${Date.now()}`;
      const celular = $("#celular"), imagem = $("#previa");
      celular.classList.add("carregando");
      const nova = new Image();
      nova.onload = () => { imagem.src = nova.src; celular.classList.remove("carregando"); };
      nova.onerror = () => { celular.classList.remove("carregando"); };
      nova.src = url;
      $("#frase-pos").textContent = escolhidas.length ? `Frase ${previaFrase + 1} de ${escolhidas.length}` : "Frase de exemplo";
      $("#midia-pos").textContent = midias.length ? `Vídeo ${previaMidia + 1} de ${midias.length}` : "Sem vídeo ainda";
      $("#frase-ant").disabled = $("#frase-prox").disabled = escolhidas.length < 2;
      $("#midia-ant").disabled = $("#midia-prox").disabled = midias.length < 2;
    }, 140);
  }

  const passear = (que, delta) => {
    if (que === "frase") previaFrase = (previaFrase + delta + frasesEscolhidas().length) % Math.max(frasesEscolhidas().length, 1);
    else { midiaEmEdicao = null; previaMidia = (previaMidia + delta + midiasZona(1).filter((m) => m.selecionada).length) % Math.max(midiasZona(1).filter((m) => m.selecionada).length, 1); }
    textoDigitado = "";
    atualizarPrevia();
  };
  $("#frase-ant").onclick = () => passear("frase", -1);
  $("#frase-prox").onclick = () => passear("frase", 1);
  $("#midia-ant").onclick = () => passear("midia", -1);
  $("#midia-prox").onclick = () => passear("midia", 1);

  async function recarregar() {
    T = await api(`/api/templates/${ID}`);
    if (!$("#nome").matches(":focus")) $("#nome").value = T.nome;
  }

  // ---------- peças de formulário ----------

  const controle = (secao, chave, rotulo, min, max, unidade = "", passoValor = 1) => `
    <div class="controle"><div class="controle-topo"><span>${rotulo}</span><output>${cfg(secao, chave)}${unidade}</output></div>
      <input type="range" data-cfg="${secao}.${chave}" data-unidade="${unidade}" min="${min}" max="${max}" step="${passoValor}" value="${cfg(secao, chave)}"></div>`;

  const segmentado = (secao, chave, opcoes, atual) => `<div class="segmentado" data-seg="${secao}.${chave}">
    ${opcoes.map(([valor, nome]) => `<button type="button" data-valor="${valor ?? ""}" class="${(atual ?? "") === (valor ?? "") ? "ativo" : ""}">${nome}</button>`).join("")}</div>`;

  // Um só ouvinte para todos os controles do painel.
  painel.addEventListener("input", (e) => {
    const alvo = e.target;
    if (alvo.dataset.cfg) {
      const [secao, chave] = alvo.dataset.cfg.split(".");
      if (alvo.type === "range") {
        mudar(secao, chave, Number(alvo.value));
        alvo.closest(".controle").querySelector("output").textContent = alvo.value + (alvo.dataset.unidade || "");
      } else if (alvo.type === "text" || alvo.type === "color") {
        mudar(secao, chave, alvo.value);
      }
    } else if (alvo.dataset.midiaCampo) {
      const m = T.midias.find((x) => x.id === midiaEmEdicao);
      if (!m) return;
      m[alvo.dataset.midiaCampo] = Number(alvo.value);
      alvo.closest(".controle").querySelector("output").textContent = alvo.dataset.midiaCampo === "zoom" ? Number(alvo.value).toFixed(2) + "×" : alvo.value + "%";
      clearTimeout(temporizadores.midia);
      temporizadores.midia = setTimeout(async () => {
        try { await api(`/api/templates/${ID}/midias/${m.id}`, { metodo: "PUT", corpo: { [alvo.dataset.midiaCampo]: m[alvo.dataset.midiaCampo] } }); atualizarPrevia(); }
        catch (erro) { aviso(erro.message, { tipo: "erro" }); }
      }, 300);
    } else if (alvo.id === "nova-frase") {
      textoDigitado = alvo.value.trim();
      atualizarPrevia();
    }
  });

  painel.addEventListener("change", async (e) => {
    const alvo = e.target;
    if (alvo.dataset.cfg && alvo.type === "checkbox") {
      const [secao, chave] = alvo.dataset.cfg.split(".");
      mudar(secao, chave, alvo.checked ? true : null);
    } else if (alvo.dataset.fraseTexto) {
      await acao(() => api(`/api/templates/${ID}/frases/${alvo.dataset.fraseTexto}`, { metodo: "PUT", corpo: { texto: alvo.value } }));
    } else if (alvo.id === "arquivo-foto" && alvo.files[0]) {
      await enviarFoto(alvo.files[0]);
    } else if (alvo.id === "arquivo-videos" && alvo.files.length) {
      await enviarVideos([...alvo.files], Number(alvo.dataset.zona || 1));
      alvo.value = "";
    }
  });

  painel.addEventListener("click", async (e) => {
    const seg = e.target.closest("[data-seg] button");
    if (seg) {
      const [secao, chave] = seg.parentElement.dataset.seg.split(".");
      const valor = seg.dataset.valor === "" ? null : seg.dataset.valor;
      mudar(secao, chave, valor);
      seg.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("ativo", b === seg));
      return;
    }
    const a = e.target.closest("[data-acao]");
    if (!a) return;
    const dado = a.dataset;
    switch (dado.acao) {
      case "trocar-layout":
        await acao(() => api(`/api/templates/${ID}`, { metodo: "PUT", corpo: { layout: dado.layout } }), true); break;
      case "tirar-foto":
        await acao(() => api(`/api/templates/${ID}/avatar`, { metodo: "DELETE" }), true); break;
      case "salvar-perfil": {
        const rotulo = prompt("Nome para este perfil (ex.: Minha página de GTA):", cfg("perfil", "nome"));
        if (rotulo !== null) await acao(() => api(`/api/templates/${ID}/perfil-salvo`, { metodo: "POST", corpo: { rotulo } }), true, "Perfil salvo para reutilizar.");
        break;
      }
      case "usar-perfil":
        await acao(() => api(`/api/templates/${ID}/perfil-salvo/${dado.id}`, { metodo: "POST" }), true, "Perfil aplicado."); break;
      case "apagar-perfil":
        e.stopPropagation();
        await acao(() => api(`/api/perfis-pagina/${dado.id}`, { metodo: "DELETE" }), true); break;
      case "gerar-frases": await gerarFrases(); break;
      case "usar-sugestao": await usarSugestoes([sugestoes[Number(dado.i)]], Number(dado.i)); break;
      case "usar-todas": await usarSugestoes(sugestoes.slice(), null); break;
      case "add-frase": await adicionarFrase(); break;
      case "tirar-frase": await acao(() => api(`/api/templates/${ID}/frases/${dado.id}`, { metodo: "DELETE" }), true); break;
      case "add-corte": await alternarCorte(Number(dado.id), Number(dado.zona)); break;
      case "add-biblioteca": await alternarBiblioteca(Number(dado.id)); break;
      case "editar-midia": midiaEmEdicao = midiaEmEdicao === Number(dado.id) ? null : Number(dado.id); desenharPasso(); atualizarPrevia(); break;
      case "tirar-midia": if (midiaEmEdicao === Number(dado.id)) midiaEmEdicao = null; e.stopPropagation();
        await acao(() => api(`/api/templates/${ID}/midias/${dado.id}`, { metodo: "DELETE" }), true); break;
      case "ajuste": await mudarAjuste(dado.valor); break;
      case "marcar-midia": await acao(() => api(`/api/templates/${ID}/midias/${dado.id}`, { metodo: "PUT", corpo: { selecionada: !T.midias.find((m) => m.id === Number(dado.id)).selecionada } }), true); break;
      case "marcar-frase": await acao(() => api(`/api/templates/${ID}/frases/${dado.id}`, { metodo: "PUT", corpo: { selecionada: !T.frases.find((f) => f.id === Number(dado.id)).selecionada } }), true); break;
      case "todas-midias": await acao(() => api(`/api/templates/${ID}/midias`, { metodo: "PUT", corpo: { selecionada: dado.valor === "1" } }), true); break;
      case "todas-frases": await acao(() => api(`/api/templates/${ID}/frases`, { metodo: "PUT", corpo: { selecionada: dado.valor === "1" } }), true); break;
      case "gerar-lote": await gerarLote(); break;
      case "baixar-todos": baixarTodos(); break;
      case "agendar-saidas": Agendar.abrir({ saidas: saidas.saidas.filter((s) => s.url).map((s) => s.id), distribuir: true }); break;
    }
  });

  /** Executa uma chamada, recarrega os dados e redesenha. */
  async function acao(chamada, redesenhar = false, mensagem = null) {
    try {
      await chamada();
      await recarregar();
      if (mensagem) aviso(mensagem);
      if (redesenhar) desenharPasso();
      atualizarPrevia();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }

  // ---------- passo 1: perfil ----------

  function passoPerfil() {
    const inicial = (cfg("perfil", "nome") || "?").trim()[0] || "?";
    const mostrar = cfg("perfil", "mostrar") ?? T.padroes_do_layout.mostrar;
    return `<h2>Perfil e texto</h2>
      <p class="dica">Foto, nome e @ aparecem no vídeo como se a página estivesse postando. Preencha uma vez e salve para reutilizar.</p>
      <div class="secao"><h3>Perfis salvos</h3><div class="perfis-salvos" id="perfis-salvos"><span class="dica">Carregando…</span></div></div>
      <div class="secao"><h3>Quem posta</h3>
        <label class="interruptor"><input type="checkbox" data-cfg="perfil.mostrar" ${mostrar ? "checked" : ""}>Mostrar o perfil no vídeo</label>
        <div class="foto-perfil"><div class="bolinha">${T.avatar_url ? `<img src="${T.avatar_url}" alt="">` : esc(inicial.toUpperCase())}</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <label class="botao pequeno" style="cursor:pointer">${icone("baixar", "transform:rotate(180deg)")}Enviar foto<input type="file" id="arquivo-foto" accept="image/png,image/jpeg,image/webp" hidden></label>
            ${T.avatar_url ? `<button class="botao pequeno fantasma" data-acao="tirar-foto">Tirar foto</button>` : ""}</div></div>
        <div class="linha-campos">
          <label class="rotulo-campo">Nome<input class="campo" type="text" maxlength="60" data-cfg="perfil.nome" value="${esc(cfg("perfil", "nome"))}"></label>
          <label class="rotulo-campo">@usuário<input class="campo" type="text" maxlength="60" data-cfg="perfil.handle" value="${esc(cfg("perfil", "handle"))}"></label></div></div>
      <div class="secao"><h3>Aparência</h3>
        <div class="linha-campos">
          <div class="rotulo-campo">Tema ${segmentado("perfil", "tema", [["escuro", "Escuro"], ["claro", "Claro"]], cfg("perfil", "tema"))}</div>
          <div class="rotulo-campo">Alinhamento ${segmentado("perfil", "alinhamento", [[null, "Automático"], ["esquerda", "Esquerda"], ["centro", "Centro"], ["direita", "Direita"]], cfg("perfil", "alinhamento"))}</div>
          <div class="rotulo-campo">Posição do perfil ${segmentado("perfil", "posicao", [[null, "Automática"], ["topo", "Topo"], ["base", "Rodapé"]], cfg("perfil", "posicao"))}</div></div>
        <div class="linha-campos">${controle("perfil", "tam_avatar", "Tamanho da foto", 40, 260, "px")}${controle("perfil", "fonte_nome", "Fonte do nome", 20, 80, "px")}${controle("perfil", "fonte_handle", "Fonte do @", 16, 70, "px")}</div></div>
      <button class="botao" data-acao="salvar-perfil" style="justify-self:start">${icone("check")}Salvar este perfil para reutilizar</button>`;
  }

  async function carregarPerfis() {
    try {
      const { perfis } = await api("/api/perfis-pagina");
      const caixa = $("#perfis-salvos");
      if (!caixa) return;
      caixa.innerHTML = perfis.length ? perfis.map((p) => `<span class="chip-perfil" data-acao="usar-perfil" data-id="${p.id}" title="Aplicar este perfil">${esc(p.rotulo)}
        <button data-acao="apagar-perfil" data-id="${p.id}" aria-label="Apagar perfil">${icone("x", "width:12px;height:12px")}</button></span>`).join("")
        : '<span class="dica">Nenhum perfil salvo ainda. Preencha abaixo e clique em "Salvar".</span>';
    } catch (e) { /* os perfis são um conforto: o resto segue funcionando */ }
  }

  async function enviarFoto(arquivo) {
    try {
      const r = await fetch(`/api/templates/${ID}/avatar?nome=${encodeURIComponent(arquivo.name)}`, { method: "POST", body: arquivo });
      if (!r.ok) throw new Error((await r.json()).erro || "Não consegui enviar a foto.");
      await recarregar(); desenharPasso(); atualizarPrevia();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }

  // ---------- passo 2: zonas ----------

  function passoZonas() {
    return `<h2>Zonas e modelo</h2><p class="dica">Escolha como o vídeo, a frase e o perfil se distribuem na tela.</p>
      <div class="cartoes-layout">${Object.entries(T.layouts).map(([id, nome]) => `
        <button class="opcao-layout ${T.layout === id ? "ativo" : ""}" data-acao="trocar-layout" data-layout="${id}">${Painel.esquemaDeLayout(id)}<b>${esc(nome)}</b></button>`).join("")}</div>
      <div class="secao"><h3>Fundo atrás do vídeo</h3>
        <p class="dica" style="margin:0">Só aparece quando o vídeo é ajustado para "caber" inteiro na zona (passo Mídia).</p>
        ${segmentado("video", "fundo", [["desfocado", "Desfocado (o próprio vídeo)"], ["solido", "Preto liso"]], cfg("video", "fundo"))}</div>
      ${T.zonas_de_video === 2 ? `<div class="aviso-caixa">${icone("alerta")}<span>Neste modelo há duas zonas de vídeo. No passo Mídia você escolhe o vídeo da zona de baixo; sem escolha, ela mostra o mesmo vídeo desfocado.</span></div>` : ""}`;
  }

  // ---------- passo 3: frases ----------

  function passoFrases() {
    const lista = T.frases.length ? T.frases.map((f) => `<div class="frase-item">
        <input type="text" data-frase-texto="${f.id}" value="${esc(f.texto)}" maxlength="240" aria-label="Frase">
        <button class="mini no" data-acao="tirar-frase" data-id="${f.id}" aria-label="Apagar frase">${icone("x")}</button></div>`).join("")
      : '<div class="vazio-pequeno">Ainda sem frases. Gere com a IA ou escreva a sua.</div>';
    const itens = sugestoes.map((s, i) => `<div class="sugestao"><span>${esc(s)}</span>
        <button class="botao pequeno" data-acao="usar-sugestao" data-i="${i}">Usar</button></div>`).join("");
    return `<h2>Frases</h2><p class="dica">Cada frase vira um vídeo diferente. Escreva a ideia e a IA cria variações, ou escreva você mesmo.</p>
      <div class="duas-colunas">
        <div style="display:grid;gap:14px;align-content:start">
          <div class="secao"><h3>Gerar com IA</h3>
            <textarea class="campo" id="ideia-base" maxlength="300" placeholder="Descreva a ideia do vídeo. Ex.: A página perfeita para quem quer saber tudo sobre o GTA 6">${esc(window.__ideia || "")}</textarea>
            <div style="display:flex;gap:8px;align-items:center">
              <select class="campo-select" id="qtd-frases" style="flex:none">${[3, 5, 8, 10, 15].map((n) => `<option value="${n}" ${n === (window.__qtd || 5) ? "selected" : ""}>${n} sugestões</option>`).join("")}</select>
              <button class="botao primario" id="botao-gerar" data-acao="gerar-frases" style="flex:1">Gerar sugestões</button></div>
            <span class="dica">Custa uma fração de centavo.</span>
            <div class="lista" id="sugestoes">${itens}</div>
            ${sugestoes.length ? `<button class="botao" data-acao="usar-todas">${icone("mais")}Adicionar todas</button>` : ""}</div>
          <div class="secao"><h3>Escrever frase</h3>
            <div style="display:flex;gap:8px"><input class="campo" id="nova-frase" maxlength="240" placeholder="Digite e aperte Enter">
              <button class="botao primario" data-acao="add-frase" aria-label="Adicionar frase">${icone("mais")}</button></div></div>
        </div>
        <div class="secao" style="border-top:0;padding-top:0;align-content:start"><h3>Frases do projeto (${T.frases.length})</h3><div class="lista">${lista}</div></div>
      </div>`;
  }

  async function gerarFrases() {
    const base = $("#ideia-base").value.trim(), qtd = Number($("#qtd-frases").value);
    window.__ideia = base; window.__qtd = qtd;
    const botao = $("#botao-gerar");
    botao.disabled = true; botao.textContent = "Gerando…";
    try {
      const r = await api(`/api/templates/${ID}/frases/gerar`, { metodo: "POST", corpo: { base, quantidade: qtd } });
      sugestoes = r.sugestoes;
      Painel.atualizarGasto();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
    desenharPasso();
  }

  async function usarSugestoes(textos, indice) {
    try {
      await api(`/api/templates/${ID}/frases`, { metodo: "POST", corpo: { textos, origem: "ia" } });
      sugestoes = indice === null ? [] : sugestoes.filter((_, i) => i !== indice);
      await recarregar(); desenharPasso(); atualizarPrevia();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }

  async function adicionarFrase() {
    const campo = $("#nova-frase"), texto = campo.value.trim();
    if (!texto) return;
    textoDigitado = "";
    await acao(() => api(`/api/templates/${ID}/frases`, { metodo: "POST", corpo: { textos: [texto] } }), true);
    const novo = $("#nova-frase"); if (novo) novo.focus();
  }
  painel.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.id === "nova-frase") { e.preventDefault(); adicionarFrase(); }
    else if (e.key === "Enter" && e.target.dataset.fraseTexto) e.target.blur();
  });

  // ---------- passo 4: mídia ----------

  const noTemplate = (corteId, zona) => T.midias.find((m) => m.corte_id === corteId && m.zona === zona);
  const miniMidia = (m) => `/api/templates/${ID}/midias/${m.id}/miniatura.jpg`;

  function passoMidia() {
    const zona1 = midiasZona(1);
    const editando = T.midias.find((m) => m.id === midiaEmEdicao);
    const cortes = cortesDoCanal === null ? '<span class="dica">Carregando seus cortes…</span>'
      : cortesDoCanal.length ? `<div class="miniaturas">${cortesDoCanal.map((c) => miniaturaCorte(c, 1)).join("")}</div>`
      : '<div class="vazio-pequeno">Você ainda não tem cortes. Crie na tela Cortes ou envie vídeos.</div>';
    const meus = zona1.length ? `<div class="miniaturas">${zona1.map((m) => miniaturaMidia(m)).join("")}</div>`
      : '<div class="vazio-pequeno">Nenhum vídeo ainda. Escolha cortes ou envie arquivos.</div>';
    const ajuste = editando ? `<div class="secao"><h3>Ajustar: ${esc(editando.rotulo)}</h3>
        <div class="segmentado"><button type="button" data-acao="ajuste" data-valor="preencher" class="${editando.ajuste === "preencher" ? "ativo" : ""}">Preencher a zona</button>
          <button type="button" data-acao="ajuste" data-valor="caber" class="${editando.ajuste === "caber" ? "ativo" : ""}">Caber inteiro</button></div>
        ${editando.ajuste === "preencher" ? `<div class="linha-campos">
          <div class="controle"><div class="controle-topo"><span>Zoom</span><output>${Number(editando.zoom).toFixed(2)}×</output></div><input type="range" data-midia-campo="zoom" min="1" max="3" step="0.05" value="${editando.zoom}"></div>
          <div class="controle"><div class="controle-topo"><span>Posição horizontal</span><output>${Math.round(editando.pos_x)}%</output></div><input type="range" data-midia-campo="pos_x" min="0" max="100" value="${editando.pos_x}"></div>
          <div class="controle"><div class="controle-topo"><span>Posição vertical</span><output>${Math.round(editando.pos_y)}%</output></div><input type="range" data-midia-campo="pos_y" min="0" max="100" value="${editando.pos_y}"></div></div>`
          : '<p class="dica" style="margin:0">O vídeo aparece inteiro, com o fundo escolhido no passo Zonas.</p>'}</div>`
      : (zona1.length ? '<p class="dica" style="margin:0">Clique em um vídeo acima para ajustar zoom e enquadramento. A prévia mostra o resultado.</p>' : "");
    const segunda = T.zonas_de_video === 2 ? `<div class="secao"><h3>Vídeo da zona de baixo (opcional)</h3>
        <p class="dica" style="margin:0">Sem escolha, a zona de baixo mostra o mesmo vídeo desfocado. Escolha um para usar em todos os vídeos gerados.</p>
        ${midiasZona(2).length ? `<div class="miniaturas">${midiasZona(2).map((m) => miniaturaMidia(m, false)).join("")}</div>` : ""}
        ${cortesDoCanal && cortesDoCanal.length ? `<div class="miniaturas">${cortesDoCanal.slice(0, 12).map((c) => miniaturaCorte(c, 2)).join("")}</div>` : ""}
        <label class="botao pequeno" style="cursor:pointer;justify-self:start">${icone("baixar", "transform:rotate(180deg)")}Enviar um vídeo<input type="file" id="arquivo-videos" data-zona="2" accept="video/*" hidden></label></div>` : "";
    return `<h2>Vídeos</h2><p class="dica">Escolha de onde vêm os vídeos. Cada vídeo será combinado com cada frase.</p>
      <div class="secao"><h3>Cortes do seu canal</h3>${cortes}</div>
      <div class="secao"><h3>Biblioteca (baixados na tela Perfis)</h3>${bibliotecaHtml()}</div>
      <div class="secao"><h3>Enviar do computador</h3>
        <label class="envio" id="area-envio"><span>${icone("baixar", "transform:rotate(180deg);width:26px;height:26px")}</span><b>Clique ou arraste vídeos aqui</b><small>MP4, MOV, WEBM ou MKV, até 2 GB cada</small>
          <input type="file" id="arquivo-videos" data-zona="1" accept="video/*" multiple hidden></label><div id="progresso-envio"></div></div>
      <div class="secao"><h3>Vídeos deste template (${zona1.length})</h3>${meus}${ajuste}</div>${segunda}`;
  }

  const naTemplatePorArquivo = (arquivo, zona = 1) => T.midias.find((m) => m.arquivo === arquivo && m.zona === zona);

  function bibliotecaHtml() {
    if (bibliotecaVideos === null) return '<span class="dica">Carregando…</span>';
    if (!bibliotecaVideos.length) return '<div class="vazio-pequeno">Vazia. Na tela Perfis, escolha vídeos e clique em "Baixar vídeos".</div>';
    return `<div class="miniaturas">${bibliotecaVideos.map((b) => `<button class="miniatura ${naTemplatePorArquivo(b.arquivo) ? "escolhida" : ""}" data-acao="add-biblioteca" data-id="${b.id}" title="${esc(b.titulo || "")}">
      <img src="${b.miniatura}" alt="" loading="lazy" onerror="this.style.display='none'"><span class="marca">${icone("check")}</span><span class="legenda">${esc(b.titulo || b.id_externo)}</span></button>`).join("")}</div>`;
  }

  async function carregarBiblioteca() {
    try { bibliotecaVideos = (await api("/api/biblioteca")).itens; } catch (e) { bibliotecaVideos = []; }
    if (passo === 4) desenharPasso();
  }

  async function alternarBiblioteca(itemId) {
    const item = bibliotecaVideos.find((b) => b.id === itemId);
    const existente = naTemplatePorArquivo(item.arquivo);
    if (existente) await acao(() => api(`/api/templates/${ID}/midias/${existente.id}`, { metodo: "DELETE" }), true);
    else await acao(() => api(`/api/templates/${ID}/midias`, { metodo: "POST", corpo: { biblioteca: [itemId] } }), true);
  }

  function miniaturaCorte(c, zona) {
    const ja = noTemplate(c.id, zona);
    return `<button class="miniatura ${ja ? "escolhida" : ""}" data-acao="add-corte" data-id="${c.id}" data-zona="${zona}" title="${esc(c.titulo)}">
      ${c.miniatura ? `<img src="${c.miniatura}" alt="" loading="lazy">` : ""}<span class="marca">${icone("check")}</span><span class="legenda">${esc(c.titulo)}</span></button>`;
  }

  function miniaturaMidia(m, editavel = true) {
    return `<div class="miniatura ${m.id === midiaEmEdicao ? "em-edicao" : ""}" ${editavel ? `data-acao="editar-midia" data-id="${m.id}"` : ""} role="button" tabindex="0" title="${esc(m.rotulo)}">
      <img src="${miniMidia(m)}" alt="" loading="lazy" onerror="this.style.display='none'"><span class="legenda">${esc(m.rotulo)}</span>
      <button class="tira" data-acao="tirar-midia" data-id="${m.id}" aria-label="Tirar vídeo" style="border:0">${icone("x", "width:13px;height:13px")}</button></div>`;
  }

  async function alternarCorte(corteId, zona) {
    const existente = noTemplate(corteId, zona);
    if (existente) { await acao(() => api(`/api/templates/${ID}/midias/${existente.id}`, { metodo: "DELETE" }), true); return; }
    if (zona === 2) for (const m of midiasZona(2)) await api(`/api/templates/${ID}/midias/${m.id}`, { metodo: "DELETE" });   // só um na zona de baixo
    await acao(() => api(`/api/templates/${ID}/midias`, { metodo: "POST", corpo: { cortes: [corteId], zona } }), true);
  }

  async function mudarAjuste(valor) {
    await acao(() => api(`/api/templates/${ID}/midias/${midiaEmEdicao}`, { metodo: "PUT", corpo: { ajuste: valor } }), true);
  }

  function enviarUm(arquivo, zona, aoProgredir) {
    return new Promise((resolver, rejeitar) => {
      const pedido = new XMLHttpRequest();
      pedido.open("POST", `/api/templates/${ID}/upload?nome=${encodeURIComponent(arquivo.name)}&zona=${zona}`);
      pedido.upload.onprogress = (e) => e.lengthComputable && aoProgredir(e.loaded / e.total);
      pedido.onload = () => pedido.status < 300 ? resolver() : rejeitar(new Error((JSON.parse(pedido.responseText || "{}").erro) || "Falha no envio."));
      pedido.onerror = () => rejeitar(new Error("A conexão caiu durante o envio."));
      pedido.send(arquivo);
    });
  }

  async function enviarVideos(arquivos, zona) {
    const caixa = $("#progresso-envio");
    for (let i = 0; i < arquivos.length; i++) {
      const trilho = (p) => caixa && (caixa.innerHTML = `<div class="dica" style="margin:8px 0 4px">Enviando ${i + 1} de ${arquivos.length}: ${esc(arquivos[i].name)}</div>
        <div class="trilho-progresso"><i style="width:${Math.round(p * 100)}%"></i></div>`);
      trilho(0);
      try {
        if (zona === 2) for (const m of midiasZona(2)) await api(`/api/templates/${ID}/midias/${m.id}`, { metodo: "DELETE" });
        await enviarUm(arquivos[i], zona, trilho);
      } catch (erro) { aviso(`${arquivos[i].name}: ${erro.message}`, { tipo: "erro" }); }
    }
    await recarregar(); desenharPasso(); atualizarPrevia();
  }

  // ---------- passo 5: estilo ----------

  function passoEstilo() {
    const cor = cfg("texto", "cor");
    return `<h2>Estilo do texto</h2><p class="dica">Ajuste como a frase aparece. Se não couber, o tamanho diminui sozinho.</p>
      <div class="linha-campos">${controle("texto", "tamanho", "Tamanho máximo da frase", 28, 120, "px")}${controle("texto", "espaco_lateral", "Margem lateral", 16, 200, "px")}${controle("texto", "faixa_minima", "Altura mínima da faixa (0 = automática)", 0, 700, "px", 10)}</div>
      <div class="secao"><h3>Cor do texto</h3>
        <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap">
          ${segmentado("texto", "cor", [[null, "Automática (pelo tema)"], ["#ffd23f", "Amarelo"], ["#ff4f8b", "Rosa"], ["#3ccf7a", "Verde"]], cor)}
          <label class="rotulo-campo" style="display:flex;align-items:center;gap:8px">Outra cor <input type="color" data-cfg="texto.cor" value="${cor || "#ffffff"}" style="width:42px;height:32px;border:0;background:none"></label></div></div>`;
  }

  // ---------- passo 6: variações ----------

  function passoVariacoes() {
    const r = T.resumo, zona1 = midiasZona(1);
    const midias = zona1.length ? `<div class="miniaturas">${zona1.map((m) => `
        <button class="miniatura ${m.selecionada ? "escolhida" : ""}" data-acao="marcar-midia" data-id="${m.id}" title="${esc(m.rotulo)}">
          <img src="${miniMidia(m)}" alt="" onerror="this.style.display='none'"><span class="marca">${icone("check")}</span><span class="legenda">${esc(m.rotulo)}</span></button>`).join("")}</div>`
      : '<div class="vazio-pequeno">Sem vídeos. Volte ao passo Mídia.</div>';
    const frases = T.frases.length ? `<div class="lista">${T.frases.map((f) => `
        <label class="frase-item" style="cursor:pointer"><input type="checkbox" ${f.selecionada ? "checked" : ""} data-acao="marcar-frase" data-id="${f.id}" style="accent-color:var(--acento);width:18px;height:18px"><span>${esc(f.texto)}</span></label>`).join("")}</div>`
      : '<div class="vazio-pequeno">Sem frases. Volte ao passo Frases.</div>';
    return `<h2>Variações</h2><p class="dica">Marque o que entra. Cada vídeo marcado é combinado com cada frase marcada.</p>
      <div class="contador-grande"><strong>${r.total}</strong> variações serão geradas<span style="font-weight:500;margin-left:auto;font-size:13px">${r.midias} vídeo${r.midias === 1 ? "" : "s"} × ${r.frases} frase${r.frases === 1 ? "" : "s"}${r.ja_existem ? ` · ${r.ja_existem} já geradas` : ""}</span></div>
      ${r.total > 60 ? `<div class="aviso-caixa">${icone("alerta")}<span>São muitos vídeos. Cada um leva de 10 a 40 segundos para ficar pronto no seu computador; o trabalho segue na fila e você pode fechar o painel.</span></div>` : ""}
      <div class="secao"><h3>Vídeos <span style="text-transform:none;letter-spacing:0;font-weight:500">· <a href="#" data-acao="todas-midias" data-valor="1">todos</a> · <a href="#" data-acao="todas-midias" data-valor="0">nenhum</a></span></h3>${midias}</div>
      <div class="secao"><h3>Frases <span style="text-transform:none;letter-spacing:0;font-weight:500">· <a href="#" data-acao="todas-frases" data-valor="1">todas</a> · <a href="#" data-acao="todas-frases" data-valor="0">nenhuma</a></span></h3>${frases}</div>`;
  }

  // ---------- passo 7: gerar ----------

  function passoGerar() {
    return `<h2>Gerar</h2><div id="area-gerar"><div class="esqueleto" style="aspect-ratio:auto;height:120px"></div></div>`;
  }

  async function atualizarSaidas() {
    clearTimeout(relogioSaidas);
    if (passo !== 7) return;
    try { saidas = await api(`/api/templates/${ID}/saidas`); } catch (e) { relogioSaidas = setTimeout(atualizarSaidas, 4000); return; }
    desenharGerar();
    const c = saidas.contagem;
    if (c.aguardando + c.renderizando > 0) relogioSaidas = setTimeout(atualizarSaidas, 2500);
    else recarregar().then(atualizarPrevia);
  }

  function desenharGerar() {
    const caixa = $("#area-gerar");
    if (!caixa || !saidas) return;
    const c = saidas.contagem, r = T.resumo;
    const feitos = c.pronto + c.falhou, trabalhando = c.aguardando + c.renderizando > 0;
    const pct = c.total ? Math.round((feitos / c.total) * 100) : 0;
    const botao = !trabalhando && r.novas > 0
      ? `<button class="botao primario" data-acao="gerar-lote">${icone("play")}Gerar ${r.novas} vídeo${r.novas === 1 ? "" : "s"}</button>`
      : (c.falhou && !trabalhando ? `<button class="botao" data-acao="gerar-lote">${icone("refazer")}Tentar de novo os que falharam</button>` : "");
    const topo = c.total ? `<div class="secao" style="border-top:0;padding-top:0"><div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;flex-wrap:wrap">
        <b>${trabalhando ? `Renderizando… ${feitos}/${c.total}` : `${c.pronto} de ${c.total} vídeos prontos`}</b>
        <span class="dica">${c.falhou ? `${c.falhou} com falha` : ""}</span></div>
        <div class="trilho-progresso"><i style="width:${pct}%"></i></div></div>`
      : `<div class="contador-grande"><strong>${r.total}</strong> vídeos serão gerados (${r.midias} × ${r.frases})</div>`;
    const grade = saidas.saidas.length ? `<div class="grade-saidas">${saidas.saidas.map((s) => `
        <div class="saida"><div class="tela">${s.url ? `<video src="${s.url}" controls preload="metadata" playsinline></video>`
          : s.estado === "falhou" ? `<span style="padding:12px;text-align:center;font-size:12px;color:var(--erro)">${esc(s.erro || "Falhou")}</span>`
          : '<div class="giro"></div>'}</div>
          <div class="pe"><small title="${esc(s.frase)}">${esc(s.frase)}</small>
            ${s.url ? `<a class="botao pequeno primario" href="${s.url}?baixar=1" download>${icone("baixar")}Baixar</a>` : `<span class="selo ${s.estado === "falhou" ? "erro" : ""}">${s.estado === "renderizando" ? "Montando…" : s.estado === "falhou" ? "Falhou" : "Na fila"}</span>`}</div></div>`).join("")}</div>` : "";
    caixa.innerHTML = `<div style="display:grid;gap:18px">${topo}
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">${botao}
        ${c.pronto ? `<a class="botao" href="/api/templates/${ID}/saidas.zip" download>${icone("baixar")}Baixar tudo (.zip · ${c.pronto})</a>
          <button class="botao primario" data-acao="agendar-saidas">${icone("calendario")}Agendar ${c.pronto} vídeo${c.pronto > 1 ? "s" : ""}</button>` : ""}
        ${!c.total && r.total === 0 ? '<span class="dica">Escolha vídeos e frases nos passos anteriores.</span>' : ""}</div>${grade}</div>`;
  }

  async function gerarLote() {
    try {
      const r = await api(`/api/templates/${ID}/gerar`, { metodo: "POST" });
      aviso(`${r.novas} vídeo${r.novas === 1 ? "" : "s"} na fila.`);
      atualizarSaidas();
    } catch (erro) { aviso(erro.message, { tipo: "erro" }); }
  }

  function baixarTodos() {
    const prontos = saidas.saidas.filter((s) => s.url);
    aviso(`Baixando ${prontos.length} vídeos… o navegador pode pedir para permitir vários downloads.`);
    prontos.forEach((s, i) => setTimeout(() => {
      const a = document.createElement("a"); a.href = s.url + "?baixar=1"; a.download = ""; document.body.appendChild(a); a.click(); a.remove();
    }, i * 600));
  }

  // ---------- navegação entre passos ----------

  const PASSOS_HTML = [passoPerfil, passoZonas, passoFrases, passoMidia, passoEstilo, passoVariacoes, passoGerar];

  function desenharPassos() {
    $("#passos").innerHTML = NOMES.map((nome, i) => `<button class="passo ${i + 1 === passo ? "ativo" : ""} ${i + 1 < passo ? "feito" : ""}" data-passo="${i + 1}"><i>${i + 1 < passo ? "✓" : i + 1}</i>${nome}</button>`).join("");
    const ultimo = passo === NOMES.length;
    $("#continuar").innerHTML = ultimo ? "Concluir" : `Continuar${icone("dir")}`;
  }

  function desenharPasso() {
    const rolagem = window.scrollY;
    painel.innerHTML = PASSOS_HTML[passo - 1]();
    desenharPassos();
    if (passo === 1) carregarPerfis();
    if (passo === 4 && cortesDoCanal === null) carregarCortes();
    if (passo === 4 && bibliotecaVideos === null) carregarBiblioteca();
    if (passo === 7) { atualizarSaidas(); }
    const envio = $("#area-envio");
    if (envio) {
      envio.addEventListener("dragover", (e) => { e.preventDefault(); envio.classList.add("sobre"); });
      envio.addEventListener("dragleave", () => envio.classList.remove("sobre"));
      envio.addEventListener("drop", (e) => { e.preventDefault(); envio.classList.remove("sobre");
        const videos = [...e.dataTransfer.files].filter((f) => f.type.startsWith("video/") || /\.(mp4|mov|webm|mkv|m4v)$/i.test(f.name));
        if (videos.length) enviarVideos(videos, 1); });
    }
    window.scrollTo(0, rolagem);
  }

  async function carregarCortes() {
    try {
      const dados = await api("/api/cortes");
      cortesDoCanal = dados.cortes.filter((c) => c.estado !== "descartado" && c.estado !== "falhou" && c.miniatura);
    } catch (e) { cortesDoCanal = []; }
    if (passo === 4) desenharPasso();
  }

  async function irPara(novo) {
    passo = Math.max(1, Math.min(novo, NOMES.length));
    clearTimeout(relogioSaidas);
    if (pendente && Object.keys(pendente).length) await guardar();
    api(`/api/templates/${ID}`, { metodo: "PUT", corpo: { passo } }).catch(() => {});
    if (passo >= 6) await recarregar();
    desenharPasso();
    atualizarPrevia();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  $("#passos").addEventListener("click", (e) => { const b = e.target.closest("[data-passo]"); if (b) irPara(Number(b.dataset.passo)); });
  $("#continuar").onclick = () => passo === NOMES.length ? (location.href = "/templates") : irPara(passo + 1);
  document.addEventListener("fila:terminou", () => { if (passo === 7) atualizarSaidas(); });

  let relogioNome = null;
  $("#nome").addEventListener("input", (e) => {
    clearTimeout(relogioNome);
    relogioNome = setTimeout(() => api(`/api/templates/${ID}`, { metodo: "PUT", corpo: { nome: e.target.value } }).catch((x) => aviso(x.message, { tipo: "erro" })), 500);
  });

  // ---------- início ----------

  (async () => {
    try {
      await recarregar();
      passo = Math.min(Math.max(T.passo || 1, 1), NOMES.length);
      if (passo === 7 && !T.contagem.total) passo = 6;
      desenharPasso();
      atualizarPrevia();
    } catch (erro) {
      painel.innerHTML = `<div class="vazio"><h2>Não consegui abrir este template</h2><p>${esc(erro.message)}</p><a class="botao" href="/templates">Voltar</a></div>`;
    }
  })();
})();
