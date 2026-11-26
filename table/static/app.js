/* DM Copilot — Table mode front-end (vanilla JS, no build step).
   Every number comes from the Python pipeline through /api/* : retrieval, tools, agent, meter. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const uid = () => Math.random().toString(36).slice(2, 9);
const fmtCR = (cr) => (cr === 0.125 ? "1/8" : cr === 0.25 ? "1/4" : cr === 0.5 ? "1/2" : cr ?? "?");
const debounce = (fn, ms) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

const TYPE_ICON = { creature: "🐉", spell: "✨", magic_item: "💎", rule: "📜", condition: "🌀", class: "⚔️", species: "🧝", feat: "🏅", background: "🎭", equipment: "🛡️" };
const TOOL = {
  search_library: ["🔍", "Searches the library"], get_entry: ["📖", "Opens a tome"], roll_dice: ["🎲", "Rolls the dice"],
  dice_stats: ["📊", "Computes the odds"], encounter_difficulty: ["⚔️", "Weighs the encounter"], final_answer: ["🪶", "Writes the answer"],
};

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { /* not json */ }
    throw new Error(msg);
  }
  return r.json();
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });

/* ------------------------------------------------------------------ state (per-device, localStorage) */
const DEFAULT = { heroes: [], combat: { round: 0, turn: -1, list: [] }, forge: { monsters: [], size: 4, level: 3 }, rolls: [], sound: true, tray: true };
let S = loadState();
function loadState() {
  try { return { ...structuredClone(DEFAULT), ...JSON.parse(localStorage.getItem("dmc-table") || "{}") }; }
  catch (e) { return structuredClone(DEFAULT); }
}
function save() { try { localStorage.setItem("dmc-table", JSON.stringify(S)); } catch (e) { /* private mode */ } }

/* ------------------------------------------------------------------ toasts, tabs, modal */
function toast(msg, bad = false) {
  const t = document.createElement("div");
  t.className = "toast" + (bad ? " bad" : "");
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), 3200);
}

function showTab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((s) => s.classList.toggle("active", s.id === "tab-" + name));
  if (name === "chronicles") loadChronicles();
  if (name === "forge") renderForge();
  if (name === "library" && !$("#lib-results").children.length) runSearch();
}
$$(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));

function openModal(html) { $("#modal-body").innerHTML = html; $("#modal").classList.remove("hidden"); enhanceDice($("#modal-body")); }
function closeModal() { $("#modal").classList.add("hidden"); }
$("#modal-close").onclick = closeModal;
$("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

function statblockHTML(e) {
  return `<div class="statblock" data-label="${esc(e.name)}">
    <span class="badge ${e.tier}">${e.tier === "official" ? "Official SRD" : "Open extension"}</span>
    <span class="badge type">${TYPE_ICON[e.type] || "📜"} ${esc(e.type.replace("_", " "))}</span>
    ${e.html}
    <div class="lic">${esc(e.source)}${e.license ? " · " + esc(e.license) : ""} · <code>${esc(e.doc_id)}</code></div></div>`;
}

const ENTRY_CACHE = {};
async function getEntry(docId) {
  if (!ENTRY_CACHE[docId]) ENTRY_CACHE[docId] = await api("/api/entry/" + encodeURIComponent(docId));
  return ENTRY_CACHE[docId];
}

async function openEntry(docId) {
  try {
    const e = await getEntry(docId);
    let actions = "";
    if (e.combat) {
      actions = `<div class="modal-actions">
        <button class="btn primary" data-summon="${esc(e.doc_id)}">⚔️ Add to combat</button>
        <button class="btn" data-forge-add="${esc(e.doc_id)}">🏰 Add to the forge</button></div>`;
    }
    openModal(statblockHTML(e) + actions);
  } catch (err) { toast(err.message, true); }
}

document.addEventListener("click", async (ev) => {
  const s = ev.target.closest("[data-summon]");
  if (s) { const e = await getEntry(s.dataset.summon); await summon(e, 1, false); closeModal(); showTab("combat"); }
  const f = ev.target.closest("[data-forge-add]");
  if (f) { const e = await getEntry(f.dataset.forgeAdd); forgeAdd(e); closeModal(); showTab("forge"); }
  const d = ev.target.closest(".dice-link");
  if (d) { const sb = d.closest("[data-label]"); rollDice(d.dataset.expr, (sb ? sb.dataset.label + " · " : "") + d.dataset.what); }
  const c = ev.target.closest("[data-open]");
  if (c) openEntry(c.dataset.open);
});

/* ------------------------------------------------------------------ clickable dice inside stat blocks */
const DICE_IN_TEXT = /(Attack Roll:\s*|Attack:\s*)([+-]\d+)|([+-]\d+)( to hit)|(\d+d\d+(?:\s*[+\-−]\s*\d+)?)/g;
function enhanceDice(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (!n.parentElement.closest(".dice-link") && DICE_IN_TEXT.test(n.nodeValue)) nodes.push(n);
    DICE_IN_TEXT.lastIndex = 0;
  }
  for (const n of nodes) {
    const html = esc(n.nodeValue).replace(DICE_IN_TEXT, (m, pre, bonus, bonus2, toHit, dice) => {
      if (bonus) return `${pre}<span class="dice-link" data-expr="1d20${bonus}" data-what="attack">${bonus}</span>`;
      if (bonus2) return `<span class="dice-link" data-expr="1d20${bonus2}" data-what="attack">${bonus2}</span>${toHit}`;
      const expr = dice.replace(/\s+/g, "").replace("−", "-");
      return `<span class="dice-link" data-expr="${expr}" data-what="damage">${dice}</span>`;
    });
    const span = document.createElement("span");
    span.innerHTML = html;
    n.replaceWith(span);
  }
}

/* ------------------------------------------------------------------ status pills */
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const k = $("#pill-key");
    k.textContent = s.api_key ? `🟢 Oracle awake · ${s.documents.toLocaleString()} entries` : "🔴 No API key (Oracle asleep)";
    k.className = "pill " + (s.api_key ? "ok" : "bad");
    $("#pill-cost").textContent = `💰 $${s.meter.usd.toFixed(4)}`;
    $("#oracle-meter").innerHTML = kpi(s.meter.calls, "API calls") + kpi("$" + s.meter.usd.toFixed(4), "spent") +
      kpi((s.meter.chat_in / 1000).toFixed(1) + "k", "tokens in") + kpi((s.meter.chat_out / 1000).toFixed(1) + "k", "tokens out");
    $("#lib-mode").textContent = `search: ${s.api_key && s.dense ? s.search_mode : "bm25"} · chunking ${s.strategy} · ${s.books} books`;
  } catch (e) { $("#pill-key").textContent = "⚠️ server unreachable"; }
}
const kpi = (v, l) => `<div class="kpi"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`;

/* ------------------------------------------------------------------ dice tray */
let audioCtx;
function rattle() {
  if (!S.sound) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    for (let i = 0; i < 5; i++) {
      const t = audioCtx.currentTime + i * 0.07 + Math.random() * 0.03;
      const len = 0.035, buf = audioCtx.createBuffer(1, audioCtx.sampleRate * len, audioCtx.sampleRate);
      const data = buf.getChannelData(0);
      for (let j = 0; j < data.length; j++) data[j] = (Math.random() * 2 - 1) * Math.pow(1 - j / data.length, 3);
      const src = audioCtx.createBufferSource(), gain = audioCtx.createGain(), f = audioCtx.createBiquadFilter();
      f.type = "bandpass"; f.frequency.value = 1800 + Math.random() * 1500;
      gain.gain.value = 0.5 - i * 0.07;
      src.buffer = buf; src.connect(f).connect(gain).connect(audioCtx.destination); src.start(t);
    }
  } catch (e) { /* audio not available */ }
}

function naturalD20(expr, rolls) {
  if (!/(^|[^\d])(1?d20|2d20k[hl]1)/i.test(expr)) return null;
  const keep = rolls.match(/keep \[(\d+)\]/);
  if (keep) return +keep[1];
  const m = rolls.match(/d20\[(\d+)\]/);
  return m ? +m[1] : null;
}

async function rollDice(expr, label = "") {
  if (!expr) return;
  const box = $("#dice-result"), face = $("#die-face");
  box.classList.remove("crit", "fumble");
  face.classList.remove("rolling"); void face.offsetWidth; face.classList.add("rolling");
  face.textContent = (expr.match(/d(\d+)/) || ["", "?"])[0] || "d?";
  rattle();
  const spin = setInterval(() => ($("#dice-total").textContent = Math.floor(Math.random() * 20) + 1), 60);
  try {
    const r = await post("/api/roll", { expression: expr });
    await new Promise((res) => setTimeout(res, 450));
    clearInterval(spin);
    $("#dice-total").textContent = r.total;
    $("#dice-detail").textContent = `${label ? label + " — " : ""}${expr}: ${r.rolls}  (avg ${r.stats.average})`;
    const nat = naturalD20(expr, r.rolls);
    if (nat === 20) box.classList.add("crit");
    if (nat === 1) box.classList.add("fumble");
    S.rolls.unshift({ label, expr, total: r.total, nat, at: new Date().toLocaleTimeString().slice(0, 5) });
    S.rolls = S.rolls.slice(0, 25);
    save(); renderRollLog();
    return r;
  } catch (e) { clearInterval(spin); $("#dice-total").textContent = "✖"; $("#dice-detail").textContent = e.message; }
}

function renderRollLog() {
  $("#dice-log").innerHTML = S.rolls.map((r) => `<li><span>${r.at} ${esc(r.label || "")} <small>${esc(r.expr)}</small>${r.nat === 20 ? " ⭐" : r.nat === 1 ? " 💀" : ""}</span><b>${r.total}</b></li>`).join("")
    || `<li class="muted">No rolls yet.</li>`;
}

function setupDiceTray() {
  $("#dice-buttons").innerHTML = [4, 6, 8, 10, 12, 20, 100].map((d) => `<button data-die="${d}">d${d}</button>`).join("");
  $("#dice-buttons").onclick = (e) => {
    const b = e.target.closest("[data-die]");
    if (!b) return;
    const d = +b.dataset.die, mod = +$("#dice-mod").value || 0;
    const adv = $("input[name=adv]:checked").value;
    let expr = d === 20 && adv ? `2d20${adv === "adv" ? "kh1" : "kl1"}` : `1d${d}`;
    if (mod) expr += (mod > 0 ? "+" : "") + mod;
    rollDice(expr, d === 20 && adv ? (adv === "adv" ? "Advantage" : "Disadvantage") : "");
  };
  $("#dice-form").onsubmit = (e) => { e.preventDefault(); rollDice($("#dice-expr").value.trim(), "Custom"); };
  $("#log-btn").onclick = () => $("#dice-log").classList.toggle("open");
  $("#sound-btn").onclick = () => { S.sound = !S.sound; $("#sound-btn").textContent = S.sound ? "🔊" : "🔇"; save(); };
  $("#sound-btn").textContent = S.sound ? "🔊" : "🔇";
  renderRollLog();
}

/* ------------------------------------------------------------------ autocomplete (monsters) */
function setupAutocomplete(input, list, onPick, officialBox) {
  let items = [], sel = -1;
  const draw = () => {
    list.innerHTML = items.map((c, i) => `<div class="ac-item ${i === sel ? "sel" : ""}" data-i="${i}">
      <span>${TYPE_ICON.creature} ${esc(c.name)}</span>
      <span class="meta">CR ${fmtCR(c.combat.cr)} · ${c.combat.hp} HP · AC ${c.combat.ac}${c.tier === "official" ? "" : " · " + esc(c.source)}</span></div>`).join("");
    list.classList.toggle("open", items.length > 0);
  };
  const fetchItems = debounce(async () => {
    const q = input.value.trim();
    if (!q) { items = []; draw(); return; }
    const official = officialBox ? officialBox.checked : true;
    items = await api(`/api/creatures?q=${encodeURIComponent(q)}&official=${official}`);
    sel = items.length ? 0 : -1; draw();
  }, 180);
  input.addEventListener("input", fetchItems);
  if (officialBox) officialBox.addEventListener("change", fetchItems);
  input.addEventListener("keydown", (e) => {
    if (!items.length) return;
    if (e.key === "ArrowDown") { sel = (sel + 1) % items.length; draw(); e.preventDefault(); }
    if (e.key === "ArrowUp") { sel = (sel - 1 + items.length) % items.length; draw(); e.preventDefault(); }
    if (e.key === "Enter") { e.preventDefault(); pick(sel); }
    if (e.key === "Escape") { items = []; draw(); }
  });
  list.addEventListener("mousedown", (e) => { const it = e.target.closest(".ac-item"); if (it) { e.preventDefault(); pick(+it.dataset.i); } });
  input.addEventListener("blur", () => setTimeout(() => { list.classList.remove("open"); }, 150));
  function pick(i) { if (i < 0) return; const c = items[i]; items = []; draw(); input.value = ""; onPick(c); }
}

/* ------------------------------------------------------------------ combat tracker */
let CONDITIONS = [];

function activeId() { const c = S.combat; return c.turn >= 0 && c.list[c.turn] ? c.list[c.turn].id : null; }

function sortCombat() {
  const keep = activeId();
  S.combat.list.sort((a, b) => (b.init ?? -99) - (a.init ?? -99) || (b.initBonus || 0) - (a.initBonus || 0) || a.name.localeCompare(b.name));
  if (keep) S.combat.turn = S.combat.list.findIndex((c) => c.id === keep);
}

function nextName(base) {
  const same = S.combat.list.filter((c) => c.base === base).length;
  return same ? `${base} ${same + 1}` : base;
}

async function summon(card, count = 1, rollHp = false) {
  for (let i = 0; i < count; i++) {
    let hp = card.combat.hp || 1;
    if (rollHp && card.combat.hit_dice) {
      try { hp = (await post("/api/roll", { expression: card.combat.hit_dice })).total; } catch (e) { /* keep average */ }
    }
    const init = (await post("/api/roll", { expression: `1d20${card.combat.init >= 0 ? "+" : ""}${card.combat.init}` })).total;
    S.combat.list.push({
      id: uid(), kind: "monster", base: card.name, name: nextName(card.name), doc_id: card.doc_id,
      init, initBonus: card.combat.init, hp, max: hp, ac: card.combat.ac, conds: [],
      sub: `CR ${fmtCR(card.combat.cr)} · ${card.subtitle || ""}`,
    });
  }
  sortCombat(); save(); renderCombat();
  toast(`🐉 ${count > 1 ? count + "× " : ""}${card.name} enter${count > 1 ? "" : "s"} the battle!`);
}

function addHeroesToCombat() {
  if (!S.heroes.length) { toast("Add heroes to the party first", true); return; }
  let added = 0;
  for (const h of S.heroes) {
    if (S.combat.list.some((c) => c.heroId === h.id)) continue;
    S.combat.list.push({ id: uid(), heroId: h.id, kind: "hero", base: h.name, name: h.name, init: null, initBonus: h.init,
      hp: h.hp, max: h.hp, ac: h.ac, conds: [], sub: `Level ${h.level} hero · init ${h.init >= 0 ? "+" : ""}${h.init}` });
    added++;
  }
  sortCombat(); save(); renderCombat();
  toast(added ? "🛡️ The party is ready — type each hero's initiative roll" : "The party is already on the battlefield");
}

function renderCombat() {
  const c = S.combat, ol = $("#combatants");
  $("#round").textContent = c.round || "—";
  $("#combat-empty").style.display = c.list.length ? "none" : "block";
  const act = c.list[c.turn];
  $("#turn-banner").textContent = act ? `${act.kind === "hero" ? "🛡️" : "🐉"} ${act.name}'s turn` : (c.list.length ? "Roll initiative, then ▶ Next turn" : "Prepare for battle…");
  ol.innerHTML = c.list.map((x, i) => {
    const pct = Math.max(0, Math.min(100, (x.hp / x.max) * 100));
    const cls = pct <= 25 ? "low" : pct <= 55 ? "mid" : "";
    const opts = CONDITIONS.filter((k) => !x.conds.includes(k.name)).map((k) => `<option>${esc(k.name)}</option>`).join("");
    return `<li class="combatant ${x.kind} ${i === c.turn ? "active" : ""} ${x.hp <= 0 ? "down" : ""}" data-id="${x.id}">
      <div class="init"><input type="number" value="${x.init ?? ""}" placeholder="?" data-act="init" title="Initiative"></div>
      <div class="who"><span class="icon">${x.hp <= 0 ? "💀" : x.kind === "hero" ? "🛡️" : "🐉"}</span>
        <div style="min-width:0"><div class="name">${esc(x.name)}</div><div class="sub">${esc(x.sub)}</div></div></div>
      <div class="ac"><span class="shield" title="Armor Class">${x.ac ?? "?"}</span></div>
      <div class="hp"><div class="hpbar ${cls}"><div style="width:${pct}%"></div></div><div class="hp-text">${x.hp} / ${x.max} HP</div></div>
      <div class="hp-ctrl"><input type="number" min="0" placeholder="±" data-act="amount">
        <button class="dmg" data-act="dmg" title="Damage">🗡️</button><button class="heal" data-act="heal" title="Heal">✚</button></div>
      <div class="conds">${x.conds.map((k) => `<span class="cond" data-cond="${esc(k)}" title="Click to read the rule">${esc(k)} <i data-uncond="${esc(k)}" title="Remove">✕</i></span>`).join("")}
        <select data-act="cond"><option value="">+ condition</option>${opts}</select></div>
      <div class="row-actions">${x.doc_id ? `<button data-act="stat" title="Stat block">📜</button>` : ""}<button data-act="remove" title="Remove">✖</button></div>
    </li>`;
  }).join("");
}

$("#combatants").addEventListener("change", (e) => {
  const li = e.target.closest(".combatant"); if (!li) return;
  const x = S.combat.list.find((c) => c.id === li.dataset.id);
  if (e.target.dataset.act === "init") { x.init = e.target.value === "" ? null : +e.target.value; sortCombat(); }
  if (e.target.dataset.act === "cond" && e.target.value) { x.conds.push(e.target.value); toast(`🌀 ${x.name} is ${e.target.value}`); }
  save(); renderCombat();
});

$("#combatants").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.dataset.act === "amount") { e.preventDefault(); applyHp(e.target.closest(".combatant"), e.shiftKey ? "heal" : "dmg"); }
});

$("#combatants").addEventListener("click", async (e) => {
  const li = e.target.closest(".combatant"); if (!li) return;
  const x = S.combat.list.find((c) => c.id === li.dataset.id);
  const act = e.target.closest("[data-act]")?.dataset.act;
  const un = e.target.closest("[data-uncond]");
  if (un) { x.conds = x.conds.filter((k) => k !== un.dataset.uncond); save(); renderCombat(); return; }
  const cond = e.target.closest("[data-cond]");
  if (cond) {
    const k = CONDITIONS.find((c) => c.name === cond.dataset.cond);
    if (k) openModal(`<div class="statblock" data-label="${esc(k.name)}">${k.html}</div>`);
    return;
  }
  if (act === "dmg" || act === "heal") applyHp(li, act);
  if (act === "remove") { S.combat.list = S.combat.list.filter((c) => c.id !== x.id); if (S.combat.turn >= S.combat.list.length) S.combat.turn = S.combat.list.length ? 0 : -1; save(); renderCombat(); }
  if (act === "stat") {
    const en = await getEntry(x.doc_id);
    $("#side-statblock").innerHTML = statblockHTML({ ...en, name: x.name });
    enhanceDice($("#side-statblock"));
    $("#side-statblock").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
});
function applyHp(li, kind) {
  const x = S.combat.list.find((c) => c.id === li.dataset.id);
  const n = +$("[data-act=amount]", li).value || 0;
  if (!n) return;
  const wasUp = x.hp > 0;
  x.hp = kind === "dmg" ? Math.max(0, x.hp - n) : Math.min(x.max, x.hp + n);
  save(); renderCombat();
  const row = $(`.combatant[data-id="${x.id}"]`);
  row.classList.add(kind === "dmg" ? "flash-dmg" : "flash-heal");
  if (wasUp && x.hp === 0) toast(x.kind === "monster" ? `💀 ${x.name} falls!` : `⚠️ ${x.name} drops to 0 HP — death saves!`, x.kind === "hero");
}

$("#btn-roll-init").onclick = async () => {
  const mons = S.combat.list.filter((c) => c.kind === "monster");
  if (!mons.length) { toast("No monster to roll for", true); return; }
  for (const m of mons) m.init = (await post("/api/roll", { expression: `1d20${m.initBonus >= 0 ? "+" : ""}${m.initBonus || 0}` })).total;
  rattle(); sortCombat(); save(); renderCombat(); toast("🎲 Initiative rolled for every monster");
};
$("#btn-next").onclick = () => {
  const c = S.combat;
  if (!c.list.length) { toast("The battlefield is empty", true); return; }
  if (c.list.some((x) => x.init === null || x.init === undefined)) { toast("Some combatants have no initiative yet", true); return; }
  if (c.round === 0) { c.round = 1; c.turn = 0; }
  else {
    let guard = 0;
    do {
      c.turn++;
      if (c.turn >= c.list.length) { c.turn = 0; c.round++; toast(`🔔 Round ${c.round}`); }
    } while (c.list[c.turn].kind === "monster" && c.list[c.turn].hp <= 0 && ++guard < c.list.length);
  }
  save(); renderCombat();
};
$("#btn-clear").onclick = () => {
  if (!S.combat.list.length || confirm("End the combat and clear the battlefield?")) {
    S.combat = { round: 0, turn: -1, list: [] }; save(); renderCombat();
  }
};

/* party roster */
$("#hero-form").onsubmit = (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  S.heroes.push({ id: uid(), name: f.get("name").trim(), level: +f.get("level"), init: +f.get("init"), hp: +f.get("hp"), ac: +f.get("ac") });
  e.target.reset(); save(); renderRoster(); renderForge();
};
function renderRoster() {
  $("#roster").innerHTML = S.heroes.map((h) => `<li data-id="${h.id}"><span>🛡️</span><span class="n">${esc(h.name)}</span>
    <span class="s">Lv ${h.level} · ${h.hp} HP · AC ${h.ac} · init ${h.init >= 0 ? "+" : ""}${h.init}</span><button data-del="${h.id}" title="Remove">✖</button></li>`).join("")
    || `<li class="muted">No heroes yet — add your players' characters above.</li>`;
}
$("#roster").onclick = (e) => { const d = e.target.closest("[data-del]"); if (d) { S.heroes = S.heroes.filter((h) => h.id !== d.dataset.del); save(); renderRoster(); renderForge(); } };
$("#btn-party-in").onclick = addHeroesToCombat;

setupAutocomplete($("#monster-q"), $("#monster-ac"),
  (c) => summon(c, Math.max(1, Math.min(20, +$("#monster-count").value || 1)), $("#monster-rollhp").checked), $("#monster-official"));

/* ------------------------------------------------------------------ forge */
function partyLevels() {
  if (S.heroes.length) return S.heroes.map((h) => h.level);
  return Array(S.forge.size).fill(S.forge.level);
}
function forgeAdd(card) {
  const m = S.forge.monsters.find((x) => x.doc_id === card.doc_id);
  if (m) m.count++; else S.forge.monsters.push({ doc_id: card.doc_id, name: card.name, count: 1, cr: card.combat.cr, xp: card.combat.xp });
  save(); renderForge();
}
setupAutocomplete($("#forge-q"), $("#forge-ac"), forgeAdd, null);

const evalForge = debounce(async () => {
  const lv = partyLevels();
  if (!S.forge.monsters.length) {
    $("#forge-verdict").textContent = "—"; $("#forge-budget").textContent = "Add some foes to weigh the encounter."; $("#forge-table").innerHTML = "";
    $("#forge-gauge").style.background = "#ccc"; $("#forge-needle").style.left = "0%";
    return;
  }
  try {
    const r = await post("/api/encounter", { party_levels: lv, monsters: S.forge.monsters.map((m) => ({ name: m.doc_id, count: m.count })) });
    const b = r.budget, scale = b.high * 1.5;
    const g = (b.low / scale) * 100, y = (b.moderate / scale) * 100, h = (b.high / scale) * 100;
    $("#forge-gauge").style.background = `linear-gradient(90deg, var(--green) 0 ${g}%, var(--amber) ${g}% ${y}%, var(--red) ${y}% ${h}%, var(--dark-red) ${h}% 100%)`;
    $("#forge-needle").style.left = `calc(${Math.min(100, (r.total_xp / scale) * 100)}% - 3px)`;
    const color = { LOW: "var(--green)", MODERATE: "var(--amber)", HIGH: "var(--red)" }[r.difficulty] || "var(--dark-red)";
    $("#forge-verdict").innerHTML = `<span style="color:${color}">${esc(r.difficulty)}</span>`;
    $("#forge-budget").innerHTML = `Total <b>${r.total_xp.toLocaleString()} XP</b> for ${lv.length} hero${lv.length > 1 ? "es" : ""} (levels ${[...new Set(lv)].join(", ")})<br>Low ≤ ${b.low.toLocaleString()} · Moderate ≤ ${b.moderate.toLocaleString()} · High ≤ ${b.high.toLocaleString()}`;
    $("#forge-table").innerHTML = `<table class="grid"><tr><th>Foe</th><th>CR</th><th>XP each</th><th>×</th><th>XP</th></tr>${r.monsters.map((m) =>
      `<tr><td><a href="#" data-open="${esc(m.doc_id)}">${esc(m.name)}</a></td><td>${fmtCR(m.cr)}</td><td>${m.xp_each.toLocaleString()}</td><td>${m.count}</td><td>${m.xp_total.toLocaleString()}</td></tr>`).join("")}</table>`;
  } catch (e) { toast(e.message, true); }
}, 150);

function renderForge() {
  $("#forge-party").innerHTML = S.heroes.length
    ? `<p>Using your party: ${S.heroes.map((h) => `<b>${esc(h.name)}</b> (Lv ${h.level})`).join(", ")}</p>`
    : `<div class="forge-party-quick"><label>Heroes <input type="number" id="forge-size" min="1" max="10" value="${S.forge.size}"></label>
       <label>Level <input type="number" id="forge-level" min="1" max="20" value="${S.forge.level}"></label>
       <span class="muted tiny">or add your real party in the Combat tab</span></div>`;
  if (!S.heroes.length) {
    $("#forge-size").oninput = (e) => { S.forge.size = Math.max(1, Math.min(10, +e.target.value || 1)); save(); evalForge(); };
    $("#forge-level").oninput = (e) => { S.forge.level = Math.max(1, Math.min(20, +e.target.value || 1)); save(); evalForge(); };
  }
  $("#forge-list").innerHTML = S.forge.monsters.map((m, i) => `<li><span>🐉</span><span class="n"><a href="#" data-open="${esc(m.doc_id)}">${esc(m.name)}</a></span>
    <span class="x">CR ${fmtCR(m.cr)} · ${(m.xp || 0).toLocaleString()} XP</span>
    <button data-fm="${i}" data-d="-1">−</button><b>${m.count}</b><button data-fm="${i}" data-d="1">＋</button></li>`).join("")
    || `<li class="muted">No foes yet.</li>`;
  evalForge();
}
$("#forge-list").onclick = (e) => {
  const b = e.target.closest("[data-fm]"); if (!b) return;
  const m = S.forge.monsters[+b.dataset.fm];
  m.count += +b.dataset.d;
  if (m.count <= 0) S.forge.monsters.splice(+b.dataset.fm, 1);
  save(); renderForge();
};
document.addEventListener("click", (e) => { if (e.target.closest("a[data-open]")) e.preventDefault(); }, true);
$("#forge-send").onclick = async () => {
  if (!S.forge.monsters.length) { toast("Forge an encounter first", true); return; }
  for (const m of S.forge.monsters) await summon(await getEntry(m.doc_id), m.count, false);
  showTab("combat");
};

/* ------------------------------------------------------------------ library */
const LIB_TYPES = [["", "All"], ["creature", "🐉 Creatures"], ["spell", "✨ Spells"], ["magic_item", "💎 Magic items"], ["rule", "📜 Rules"],
  ["condition", "🌀 Conditions"], ["class", "⚔️ Classes"], ["species", "🧝 Species"], ["feat", "🏅 Feats"], ["background", "🎭 Backgrounds"], ["equipment", "🛡️ Equipment"]];
let libType = "";
$("#lib-types").innerHTML = LIB_TYPES.map(([k, l]) => `<button class="chip ${k === "" ? "active" : ""}" data-t="${k}">${l}</button>`).join("");
$("#lib-types").onclick = (e) => { const b = e.target.closest("[data-t]"); if (!b) return; libType = b.dataset.t; $$("#lib-types .chip").forEach((c) => c.classList.toggle("active", c === b)); runSearch(); };
$("#lib-official").onchange = () => runSearch();
$("#lib-q").addEventListener("input", debounce(() => runSearch(), 400));

async function runSearch() {
  const q = $("#lib-q").value.trim() || "dragon";
  $("#lib-results").innerHTML = `<p class="thinking">The librarian searches the stacks</p>`;
  try {
    const r = await api(`/api/search?q=${encodeURIComponent(q)}&type=${libType}&official=${$("#lib-official").checked}&k=16`);
    $("#lib-results").innerHTML = r.results.map((c) => `<div class="card" data-open="${esc(c.doc_id)}">
        <div class="t">${TYPE_ICON[c.type] || "📜"} ${esc(c.name)}</div>
        <div class="s">${esc(c.subtitle)}</div>
        ${c.combat ? `<div class="stats">CR ${fmtCR(c.combat.cr)} · ❤️ ${c.combat.hp} · 🛡 ${c.combat.ac}</div>` : ""}
        <div class="src"><span class="badge ${c.tier}">${c.tier === "official" ? "SRD" : "Ext."}</span>${esc(c.source)}</div></div>`).join("")
      || `<p class="muted">Nothing found in the library.</p>`;
  } catch (e) { $("#lib-results").innerHTML = `<p class="red">${esc(e.message)}</p>`; }
}

/* ------------------------------------------------------------------ the Oracle (agent, streamed) */
const QUICK = [
  "How difficult is an encounter with 2 Trolls for four level 5 characters? What should my players exploit?",
  "What is the average damage of a Fireball cast with a 5th-level slot, and can it kill a Troll in one hit?",
  "Combien de points de vie a un Troll selon les règles 2024, et comment l'empêcher de se régénérer ?",
  "What does the Grappled condition do, and how does a creature escape?",
  "Compare the Adult Red Dragon and the Adult Blue Dragon: CR, hit points and breath weapon.",
  "What are the stats of a Beholder?",
];
$("#quick").innerHTML = QUICK.map((q, i) => `<button data-q="${i}">${esc(q)}</button>`).join("");
$("#quick").onclick = (e) => { const b = e.target.closest("[data-q]"); if (b) { $("#ask-q").value = QUICK[+b.dataset.q]; ask(); } };
$("#ask-form").onsubmit = (e) => { e.preventDefault(); ask(); };
$("#ask-q").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } });

function md(text) {
  const lines = esc(text || "").split("\n"), out = [];
  let list = null, table = [];
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*(?!\s)(.+?)\*(?!\*)/g, "$1<i>$2</i>").replace(/`(.+?)`/g, "<code>$1</code>");
  const flushList = () => { if (list) { out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.tag}>`); list = null; } };
  const flushTable = () => {
    if (!table.length) return;
    const rows = table.filter((r) => !/^\|?\s*:?-{2,}/.test(r)).map((r) => r.trim().replace(/^\||\|$/g, "").split("|").map((c) => inline(c.trim())));
    out.push(`<table><tr>${rows[0].map((c) => `<th>${c}</th>`).join("")}</tr>${rows.slice(1).map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</table>`);
    table = [];
  };
  for (const raw of lines) {
    const l = raw.trimEnd();
    if (l.trim().startsWith("|")) { flushList(); table.push(l); continue; }
    flushTable();
    let m;
    if ((m = l.match(/^\s*[-*•]\s+(.*)/))) { if (!list || list.tag !== "ul") { flushList(); list = { tag: "ul", items: [] }; } list.items.push(m[1]); continue; }
    if ((m = l.match(/^\s*\d+[.)]\s+(.*)/))) { if (!list || list.tag !== "ol") { flushList(); list = { tag: "ol", items: [] }; } list.items.push(m[1]); continue; }
    flushList();
    if ((m = l.match(/^#{1,4}\s+(.*)/))) out.push(`<p><b>${inline(m[1])}</b></p>`);
    else if (l.trim()) out.push(`<p>${inline(l)}</p>`);
  }
  flushList(); flushTable();
  return out.join("");
}

function addMsg(who, html) {
  const d = document.createElement("div");
  d.className = "msg " + who;
  d.innerHTML = `<div class="avatar">${who === "user" ? "🎲" : "🧙"}</div><div class="bubble">${html}</div>`;
  $("#chat").appendChild(d);
  $("#chat").scrollTop = $("#chat").scrollHeight;
  return $(".bubble", d);
}

let asking = false;
async function ask() {
  const q = $("#ask-q").value.trim();
  if (!q || asking) return;
  asking = true; $("#ask-btn").disabled = true; $("#ask-q").value = "";
  const poison = $("#poison").checked;
  addMsg("user", esc(q) + (poison ? `<br><small>🧪 poisoned library</small>` : ""));
  const b = addMsg("oracle", `<div class="steps"></div><p class="thinking">The Oracle consults the archives</p>`);
  const steps = $(".steps", b);
  try {
    const resp = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, poison }) });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const ev = (chunk.match(/^event: (.*)$/m) || [])[1], data = JSON.parse((chunk.match(/^data: (.*)$/m) || [, "{}"])[1]);
        if (ev === "step") {
          const [ic, label] = TOOL[data.tool] || ["❓", data.tool];
          const s = document.createElement("div");
          s.className = "step" + (data.ok ? "" : " err");
          s.innerHTML = `${ic} <b>${esc(label)}</b> <code>${esc(data.arguments.slice(0, 140))}</code> <span class="muted">${(data.model_latency_s + data.tool_latency_s).toFixed(1)}s</span>`;
          steps.appendChild(s);
          if (data.tool === "roll_dice" && data.ok) { try { const r = JSON.parse(data.observation); $("#dice-total").textContent = r.total; $("#dice-detail").textContent = "Oracle — " + r.expression + ": " + r.rolls; rattle(); } catch (e) { /* ignore */ } }
          $("#chat").scrollTop = $("#chat").scrollHeight;
        } else if (ev === "final") {
          $(".thinking", b)?.remove();
          const ans = data.answer || `(no final answer — stopped by ${data.terminated_by})`;
          b.insertAdjacentHTML("beforeend", `<div class="answer">${md(ans)}</div>
            ${data.cards?.length ? `<div class="cites">${data.cards.map((c) => `<span class="cite" data-open="${esc(c.doc_id)}">${TYPE_ICON[c.type] || "📜"} ${esc(c.name)} · <i>${esc(c.source)}</i></span>`).join("")}</div>` : ""}
            <div class="run-meta"><span>🔁 ${data.iterations} it.</span><span>🛠 ${data.tool_calls} tools</span><span>⚠️ ${data.hallucinated_calls} bad calls</span>
            <span>📥 ${data.tokens_in.toLocaleString()} tok</span><span>📤 ${data.tokens_out.toLocaleString()} tok</span><span>💰 $${data.cost_usd.toFixed(4)}</span><span>⏱ ${data.latency_s.toFixed(1)}s</span>
            ${data.terminated_by !== "final_answer" ? `<span class="red">stopped by ${esc(data.terminated_by)}</span>` : ""}</div>`);
        } else if (ev === "error") {
          $(".thinking", b)?.remove();
          b.insertAdjacentHTML("beforeend", `<p class="red">The Oracle stumbled: ${esc(data.message)}</p>`);
        }
      }
    }
  } catch (e) {
    $(".thinking", b)?.remove();
    b.insertAdjacentHTML("beforeend", `<p class="red">${esc(e.message)}</p>`);
  } finally {
    asking = false; $("#ask-btn").disabled = false; $("#chat").scrollTop = $("#chat").scrollHeight; refreshStatus();
  }
}

/* ------------------------------------------------------------------ chronicles (evaluation + instrumentation) */
async function loadChronicles() {
  try {
    const c = await api("/api/chronicles");
    const a = c.agent_v2;
    $("#chr-kpis").innerHTML = a ? [
      [Math.round(a.success_rate * 100) + "%", "agent success (test)"], [Math.round((a.trap_refusal_rate || 0) * 100) + "%", "trap refusals"],
      [a.faithfulness_mean.toFixed(2), "faithfulness"], [(a.hallucinated_tool_call_rate * 100).toFixed(1) + "%", "bad tool calls"],
      [a.mean_iterations, "mean iterations"], ["$" + a.cost_per_question_usd.toFixed(4), "cost / question"],
      [a.latency_p50_s + "s", "latency p50"], [a.latency_p95_s + "s", "latency p95"],
    ].map(([v, l]) => kpi(v, l)).join("") : `<p class="muted">Run <code>python -m src.evaluate</code> to fill the chronicles.</p>`;
    const rows = c.retrieval_test || [];
    const best = rows.reduce((m, r) => (!m || r.MRR > m.MRR ? r : m), null);
    $("#chr-retrieval").innerHTML = rows.length ? `<table class="grid"><tr><th>Chunking</th><th>Retriever</th><th>P@5</th><th>R@5</th><th>MRR</th><th>nDCG@5</th></tr>
      ${rows.map((r) => `<tr class="${r === best ? "best" : ""}"><td>${r.strategy}</td><td>${esc(r.mode)}</td><td>${r["P@5"].toFixed(3)}</td><td>${r["R@5"].toFixed(3)}</td><td>${r.MRR.toFixed(3)}</td><td>${r["nDCG@5"].toFixed(3)}</td></tr>`).join("")}</table>
      <p class="muted tiny">A fixed 200/50 · B structure-aware · C structure + contextual header. The Oracle uses C + dense (best on the dev split).</p>` : "";
    const keys = [["success_rate", "Success", (v) => Math.round(v * 100) + "%"], ["trap_refusal_rate", "Trap refusals", (v) => Math.round((v || 0) * 100) + "%"],
      ["faithfulness_mean", "Faithfulness", (v) => v.toFixed(2)], ["mean_iterations", "Iterations", (v) => v], ["cost_per_question_usd", "$ / question", (v) => "$" + v.toFixed(4)],
      ["latency_p50_s", "Latency p50", (v) => v + "s"]];
    const cols = [["v1 (test)", c.agent_v1], ["v2 1st run (test)", c.agent_v2_first], ["v2.1 shipped (test)", c.agent_v2], ["v2.1 (dev)", c.agent_dev]].filter(([, v]) => v);
    $("#chr-versions").innerHTML = cols.length ? `<table class="grid"><tr><th></th>${cols.map(([n]) => `<th>${n}</th>`).join("")}</tr>
      ${keys.map(([k, l, f]) => `<tr><td>${l}</td>${cols.map(([, v]) => `<td>${v[k] == null ? "—" : f(v[k])}</td>`).join("")}</tr>`).join("")}</table>
      <p class="muted tiny">v1 looped on monsters absent from the library and wrote "hard" instead of the tool's "HIGH". v2: stop after 3 failed searches, forced final answer at the bound, labels verbatim. v2.1: dice_stats reads a Multiattack, e.g. 3*(2d6+4).</p>` : "";
    $("#chr-live").innerHTML = c.live_runs.length ? `<table class="grid"><tr><th>When</th><th>Question</th><th>Tools</th><th>It.</th><th>Tokens in/out</th><th>Cost</th><th>Latency</th></tr>
      ${c.live_runs.map((r) => `<tr><td>${esc((r.ts || "").slice(11, 16))}</td><td>${esc(r.question.slice(0, 70))}</td><td>${r.tools.map((t) => (TOOL[t] || ["❓"])[0]).join(" ")}</td>
        <td>${r.iterations}</td><td>${r.tokens_in.toLocaleString()} / ${r.tokens_out}</td><td>$${r.cost_usd.toFixed(4)}</td><td>${r.latency_s.toFixed(1)}s</td></tr>`).join("")}</table>`
      : `<p class="muted">Ask the Oracle something: every run appears here with its tokens, cost, latency and tool calls.</p>`;
  } catch (e) { toast(e.message, true); }
}

/* ------------------------------------------------------------------ boot */
(async function init() {
  setupDiceTray();
  renderRoster();
  try { CONDITIONS = await api("/api/conditions"); } catch (e) { CONDITIONS = []; }
  renderCombat();
  refreshStatus();
  setInterval(refreshStatus, 15000);
})();
