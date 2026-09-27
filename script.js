// ==========================================================
// 敵情報検索ツール
// フィルタ軸: 勢力/地域(factions), 登場コンテンツ(content: category+name),
//            種族(race), 属性(motion/atkType)
// ==========================================================

const state = {
  enemies: [],
  query: "",
  factions: new Set(),
  content: new Set(),   // "category::name" 形式で保持
  race: new Set(),
  attr: new Set(),      // motion または atkType の値
};

const els = {
  search: document.getElementById("searchInput"),
  resultCount: document.getElementById("resultCount"),
  grid: document.getElementById("resultsGrid"),
  empty: document.getElementById("emptyState"),
  chips: document.getElementById("activeChips"),
  factionOptions: document.getElementById("factionOptions"),
  contentOptions: document.getElementById("contentOptions"),
  raceOptions: document.getElementById("raceOptions"),
  attrOptions: document.getElementById("attrOptions"),
  resetBtn: document.getElementById("resetBtn"),
  detailPanel: document.getElementById("detailPanel"),
  detailCard: document.getElementById("detailCard"),
  detailScrim: document.getElementById("detailScrim"),
};

init();

async function init() {
  try {
    const res = await fetch("data/enemies.json");
    const json = await res.json();
    state.enemies = json.enemies;
  } catch (err) {
    els.grid.innerHTML = `<p style="color:var(--text-secondary)">データの読み込みに失敗しました。data/enemies.json を確認してください。</p>`;
    console.error(err);
    return;
  }

  buildFilterOptions();
  bindEvents();
  render();
}

// ---------- フィルタ選択肢の構築 ----------

function buildFilterOptions() {
  const factionCounts = countValues(state.enemies.flatMap(e => e.factions));
  renderOptionGroup(els.factionOptions, factionCounts, "factions", (val) => state.factions.has(val));

  // 登場コンテンツはカテゴリごとに小見出しを出す
  const byCategory = {};
  state.enemies.forEach(e => {
    e.content.forEach(c => {
      byCategory[c.category] ??= {};
      const key = c.category + "::" + c.name;
      byCategory[c.category][key] = (byCategory[c.category][key] || 0) + 1;
    });
  });
  els.contentOptions.innerHTML = "";
  Object.keys(byCategory).forEach(category => {
    const heading = document.createElement("div");
    heading.textContent = category;
    heading.style.cssText = "font-size:11px;color:var(--text-faint);margin:8px 0 2px;padding:0 6px;font-family:var(--font-display);letter-spacing:.04em;";
    els.contentOptions.appendChild(heading);
    Object.entries(byCategory[category]).forEach(([key, count]) => {
      const name = key.split("::")[1];
      els.contentOptions.appendChild(makeOptionRow(name, count, () => state.content.has(key), () => toggle(state.content, key)));
    });
  });

  const raceCounts = countValues(state.enemies.map(e => e.race));
  renderOptionGroup(els.raceOptions, raceCounts, "race", (val) => state.race.has(val));

  const attrValues = state.enemies.flatMap(e => [e.motion, e.atkType]);
  const attrCounts = countValues(attrValues);
  renderOptionGroup(els.attrOptions, attrCounts, "attr", (val) => state.attr.has(val));
}

function countValues(arr) {
  const counts = {};
  arr.forEach(v => { counts[v] = (counts[v] || 0) + 1; });
  return counts;
}

function renderOptionGroup(container, counts, stateKey, isChecked) {
  container.innerHTML = "";
  Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .forEach(([value, count]) => {
      container.appendChild(
        makeOptionRow(value, count, () => isChecked(value), () => toggle(state[stateKey], value))
      );
    });
}

function makeOptionRow(label, count, isChecked, onToggle) {
  const row = document.createElement("label");
  row.className = "filter-option";
  row.innerHTML = `
    <input type="checkbox" ${isChecked() ? "checked" : ""}>
    <span>${escapeHtml(label)}</span>
    <span class="filter-option__count">${count}</span>
  `;
  row.querySelector("input").addEventListener("change", () => {
    onToggle();
    row.classList.toggle("filter-option--checked");
    render();
  });
  if (isChecked()) row.classList.add("filter-option--checked");
  return row;
}

function toggle(set, value) {
  set.has(value) ? set.delete(value) : set.add(value);
}

// ---------- イベント ----------

function bindEvents() {
  els.search.addEventListener("input", (e) => {
    state.query = e.target.value.trim();
    render();
  });

  document.querySelectorAll("[data-toggle]").forEach(btn => {
    btn.addEventListener("click", () => {
      const group = btn.closest(".filters__group");
      const collapsed = group.getAttribute("data-collapsed") === "true";
      group.setAttribute("data-collapsed", collapsed ? "false" : "true");
    });
  });

  els.resetBtn.addEventListener("click", () => {
    state.query = "";
    state.factions.clear();
    state.content.clear();
    state.race.clear();
    state.attr.clear();
    els.search.value = "";
    buildFilterOptions();
    render();
  });

  els.detailScrim.addEventListener("click", closeDetail);
}

// ---------- フィルタリングと描画 ----------

function matches(enemy) {
  if (state.query) {
    const q = state.query.toLowerCase();
    const hay = (enemy.name + " " + enemy.nameEn).toLowerCase();
    if (!hay.includes(q)) return false;
  }
  if (state.factions.size && !enemy.factions.some(f => state.factions.has(f))) return false;
  if (state.content.size) {
    const keys = enemy.content.map(c => c.category + "::" + c.name);
    if (!keys.some(k => state.content.has(k))) return false;
  }
  if (state.race.size && !state.race.has(enemy.race)) return false;
  if (state.attr.size && !state.attr.has(enemy.motion) && !state.attr.has(enemy.atkType)) return false;
  return true;
}

function render() {
  const results = state.enemies.filter(matches);
  els.resultCount.textContent = results.length;
  renderChips();

  els.grid.innerHTML = "";
  els.empty.hidden = results.length > 0;

  results.forEach(enemy => els.grid.appendChild(makeCard(enemy)));
}

function renderChips() {
  els.chips.innerHTML = "";
  const addChip = (label, onRemove) => {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `<span>${escapeHtml(label)}</span>`;
    const btn = document.createElement("button");
    btn.textContent = "×";
    btn.addEventListener("click", () => { onRemove(); buildFilterOptions(); render(); });
    chip.appendChild(btn);
    els.chips.appendChild(chip);
  };

  state.factions.forEach(v => addChip(v, () => state.factions.delete(v)));
  state.content.forEach(v => addChip(v.split("::")[1], () => state.content.delete(v)));
  state.race.forEach(v => addChip(v, () => state.race.delete(v)));
  state.attr.forEach(v => addChip(v, () => state.attr.delete(v)));
}

function makeCard(enemy) {
  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <div class="card__top">
      <div>
        <div class="card__name">${escapeHtml(enemy.name)}</div>
        <div class="card__name-en">${escapeHtml(enemy.nameEn)}</div>
      </div>
      <span class="rank-badge rank-badge--${enemy.rank}">${enemy.rank}</span>
    </div>
    <div class="card__meta">${escapeHtml(enemy.race)} ・ ${enemy.motion} ・ ${enemy.atkType}</div>
    <div class="card__tags">
      ${enemy.factions.map(f => `<span class="tag tag--faction">${escapeHtml(f)}</span>`).join("")}
      ${enemy.content.map(c => `<span class="tag">${escapeHtml(c.name)}</span>`).join("")}
    </div>
  `;
  card.addEventListener("click", () => openDetail(enemy));
  return card;
}

// ---------- 詳細パネル ----------

function openDetail(enemy) {
  els.detailCard.innerHTML = `
    <button class="detail__close" id="detailCloseBtn">×</button>
    <div class="detail__name">${escapeHtml(enemy.name)}</div>
    <div class="detail__name-en">${escapeHtml(enemy.nameEn)} / ${escapeHtml(enemy.code)}</div>

    <div class="detail__row"><span>ランク</span><span>${enemy.rank}</span></div>
    <div class="detail__row"><span>種族</span><span>${escapeHtml(enemy.race)}</span></div>
    <div class="detail__row"><span>移動</span><span>${enemy.motion}</span></div>
    <div class="detail__row"><span>攻撃属性</span><span>${enemy.atkType}</span></div>
    <div class="detail__row"><span>HP</span><span>${enemy.stats.hp.toLocaleString()}</span></div>
    <div class="detail__row"><span>攻撃力</span><span>${enemy.stats.atk.toLocaleString()}</span></div>
    <div class="detail__row"><span>防御力</span><span>${enemy.stats.def.toLocaleString()}</span></div>
    <div class="detail__row"><span>法術耐性</span><span>${enemy.stats.res}</span></div>

    <div class="detail__section-title">勢力 / 地域</div>
    <div class="detail__taglist">${enemy.factions.map(f => `<span class="tag tag--faction">${escapeHtml(f)}</span>`).join("")}</div>

    <div class="detail__section-title">登場コンテンツ</div>
    <div class="detail__taglist">${enemy.content.map(c => `<span class="tag">${escapeHtml(c.category)}: ${escapeHtml(c.name)}</span>`).join("")}</div>

    <div class="detail__section-title">解説</div>
    <div class="detail__desc">${escapeHtml(enemy.description)}</div>
  `;
  document.getElementById("detailCloseBtn").addEventListener("click", closeDetail);
  els.detailPanel.hidden = false;
}

function closeDetail() {
  els.detailPanel.hidden = true;
}

function escapeHtml(str) {
  return String(str ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
