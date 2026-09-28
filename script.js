// ==========================================================
// 敵情報検索
// data/enemies.json（scripts/build_data.py で生成）を読み込み、ブラウザ内だけで絞り込む。
// 同じグループ内の選択は OR、グループ同士は AND。
// ==========================================================

const PAGE_SIZE = 60;

// 絞り込みグループの定義。values(enemy) がその敵の持つ値の配列を返す。
const GROUPS = [
  { key: "region",  title: "勢力 / 地域", values: e => e.regions },
  { key: "content", title: "初登場コンテンツ", values: e => e.debut != null ? [e.debut] : [] },
  { key: "race",    title: "種族", values: e => e.races.length ? e.races : ["種族なし"] },
  { key: "rank",    title: "ランク", parent: "属性", values: e => [e.rank] },
  { key: "motion",  title: "移動", parent: "属性", values: e => [e.motion] },
  { key: "range",   title: "攻撃範囲", parent: "属性", values: e => e.attackRange ? [e.attackRange] : [] },
  { key: "damage",  title: "攻撃属性", parent: "属性", values: e => e.damage },
];

const state = {
  data: null,
  query: "",
  sort: "new",
  browseAll: false,             // 条件なしで一覧を見るとき true（false なら地域のタイルを出す）
  selected: Object.fromEntries(GROUPS.map(g => [g.key, new Set()])),
  collapsed: new Set(),         // 閉じているグループ / カテゴリ
  contentQuery: "",
  shown: PAGE_SIZE,
  results: [],
};

const $ = id => document.getElementById(id);
const els = {
  search: $("searchInput"), count: $("resultCount"), groups: $("filterGroups"),
  grid: $("resultsGrid"), empty: $("emptyState"), chips: $("activeChips"),
  sort: $("sortSelect"), more: $("moreBtn"), reset: $("resetBtn"), source: $("dataSource"),
  landing: $("landing"), landingGrid: $("landingGrid"), browseAll: $("browseAllBtn"), toolbar: $("resultsToolbar"),
  suggest: $("suggest"),
  detail: $("detailPanel"), detailCard: $("detailCard"), scrim: $("detailScrim"),
  filters: $("filters"), mobileToggle: $("mobileToggle"),
};

init();

async function init() {
  const build = await loadBuildInfo();
  try {
    const res = await fetch(`data/enemies.json${build ? `?v=${build.commit}` : ""}`);
    if (!res.ok) throw new Error(res.status);
    state.data = await res.json();
  } catch (err) {
    els.grid.innerHTML = `<p class="results__error">敵データを読み込めませんでした（data/enemies.json）。ページを再読み込みしてください。</p>`;
    console.error(err);
    return;
  }
  // 各敵の値を先に計算しておく
  for (const e of state.data.enemies) {
    e._values = Object.fromEntries(GROUPS.map(g => [g.key, g.values(e)]));
    e._search = [e.name, e.index, ...e.abilities].join(" ").toLowerCase();
    e._base = e.stats[0] || {};
  }
  const m = state.data.meta;
  els.source.textContent = `データ: ${m.source} / Ver.${m.dataVersion}`;
  // 最初は「初登場コンテンツ」以外の絞り込みを閉じておく。初登場コンテンツの中の各カテゴリも閉じる
  for (const g of GROUPS) if (g.key !== "content") state.collapsed.add(g.parent ? "parent:" + g.parent : "group:" + g.key);
  for (const c of m.categories) state.collapsed.add("cat:" + c);

  bindEvents();
  update();
}

// ---------- 公開バージョン ----------

// タイトルの下に更新日時とコミット番号を出す。
// 1. GitHub Actions で公開したときに作られる build-info.json を読む
// 2. 無ければ（ブランチから公開している場合など）GitHub API で main の最新コミットを調べる
// 表示中のページより新しい版が公開されていたら、再読み込みを促す。
async function loadBuildInfo() {
  const info = await fetchBuildInfo() || await fetchLatestCommit();
  if (!info) return null; // ローカル確認時など
  const el = $("buildInfo");
  el.textContent = `更新 ${info.committedAt}（${info.commit}）`;
  if (info.deployedAt) el.title = `公開: ${info.deployedAt}`;
  el.hidden = false;

  const loaded = document.querySelector('meta[name="build"]')?.content;
  if (loaded && loaded !== "dev" && loaded !== info.commit) {
    $("updateNotice").hidden = false;
    // index.html 自体もキャッシュされるので、URLを変えて最新版を取りにいく
    $("reloadBtn").addEventListener("click", () => location.replace(`${location.pathname}?v=${info.commit}`));
  }
  return info;
}

async function fetchBuildInfo() {
  try {
    const res = await fetch("build-info.json", { cache: "no-store" });
    return res.ok ? await res.json() : null;
  } catch {
    return null;
  }
}

async function fetchLatestCommit() {
  // https://<owner>.github.io/<repo>/ のときだけ
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const repo = location.pathname.split("/").filter(Boolean)[0];
  if (!m || !repo) return null;
  try {
    const res = await fetch(`https://api.github.com/repos/${m[1]}/${repo}/commits/main`, { cache: "no-store" });
    if (!res.ok) return null;
    const c = await res.json();
    return { commit: c.sha.slice(0, 7), committedAt: formatJst(c.commit.committer.date) };
  } catch {
    return null;
  }
}

function formatJst(iso) {
  const d = new Date(new Date(iso).getTime() + 9 * 3600 * 1000);
  const p = n => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

// ---------- 絞り込み ----------

function matchesQuery(e) {
  if (!state.query) return true;
  return state.query.split(/\s+/).every(q => e._search.includes(q));
}

function matchesGroup(e, key) {
  const sel = state.selected[key];
  if (!sel.size) return true;
  return e._values[key].some(v => sel.has(v));
}

function matches(e, exceptKey) {
  if (!matchesQuery(e)) return false;
  return GROUPS.every(g => g.key === exceptKey || matchesGroup(e, g.key));
}

// 各選択肢の件数（そのグループ以外の条件をかけた状態で数える）
function facetCounts(key) {
  const counts = new Map();
  for (const e of state.data.enemies) {
    if (!matches(e, key)) continue;
    for (const v of new Set(e._values[key])) counts.set(v, (counts.get(v) || 0) + 1);
  }
  return counts;
}

// 全体での出現値（並び順は件数の多い順。ランク等は固定順）
const FIXED_ORDER = {
  rank: ["通常", "エリート", "ボス"],
  motion: ["地上", "空中"],
  range: ["近距離", "遠距離", "近/遠", "攻撃しない"],
  damage: ["物理", "術", "回復", "攻撃しない"],
};

function allValues(key) {
  const counts = new Map();
  for (const e of state.data.enemies) for (const v of new Set(e._values[key])) counts.set(v, (counts.get(v) || 0) + 1);
  let vals = [...counts.keys()];
  if (FIXED_ORDER[key]) {
    const order = FIXED_ORDER[key];
    vals.sort((a, b) => (order.indexOf(a) + 99 * (order.indexOf(a) < 0)) - (order.indexOf(b) + 99 * (order.indexOf(b) < 0)));
  } else if (key === "content") {
    vals.sort((a, b) => a - b); // 生成時にカテゴリ順・開催順に並べてある
  } else {
    vals.sort((a, b) => (a === "種族なし") - (b === "種族なし") || counts.get(b) - counts.get(a));
  }
  return vals;
}

// ---------- 描画 ----------

function update(resetPaging = true) {
  if (resetPaging) state.shown = PAGE_SIZE;
  state.results = state.data.enemies.filter(e => matches(e));
  sortResults();
  renderFilters();
  renderChips();
  const landing = isLanding();
  els.landing.hidden = !landing;
  els.toolbar.hidden = landing;
  if (landing) els.suggest.hidden = true;
  els.grid.hidden = landing;
  if (landing) renderLanding();
  else renderResults();
}

// 検索語も絞り込み条件も無く、一覧表示を選んでいないとき
function isLanding() {
  return !state.browseAll && !state.query && GROUPS.every(g => !state.selected[g.key].size);
}

// ---------- 最初の画面（地域のタイル） ----------

// タイル用の短い表示名。メインテーマは「第九章」のように章番号だけにする
function tileLabel(i) {
  const c = state.data.contents[i];
  return c.category === "メインテーマ" ? c.name.split(" ")[0] : contentLabel(i);
}

// コンテンツの表示名（生息演算などはカテゴリ名を付ける）
function contentLabel(i) {
  const c = state.data.contents[i];
  return c.label ? `${c.category}：${c.label}` : c.name;
}

function renderLanding() {
  const pool = state.data.enemies;
  els.count.textContent = pool.length;
  els.empty.hidden = true;
  els.more.hidden = true;

  const byRegion = new Map();
  for (const e of pool) {
    for (const r of e.regions) {
      if (!byRegion.has(r)) byRegion.set(r, []);
      byRegion.get(r).push(e);
    }
  }
  const frag = document.createDocumentFragment();
  for (const [region, list] of [...byRegion].sort((a, b) => b[1].length - a[1].length)) {
    // この地域の元になった章・イベントをすべて、メインテーマ → イベント → … の順（各カテゴリ内は開催順）で
    const sources = [...new Set(list.map(e => e.regionFrom).filter(i => i != null))].sort((a, b) => a - b);
    const names = sources.map(tileLabel);
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "tile";
    tile.innerHTML = `
      <span class="tile__head"><span class="tile__name">${esc(region)}</span><span class="tile__count">${list.length}体</span></span>
      <span class="tile__picks">${names.map(esc).join("、")}</span>`;
    tile.addEventListener("click", () => {
      state.selected.region.add(region);
      state.collapsed.delete("group:region");
      update();
      window.scrollTo({ top: 0 });
    });
    frag.appendChild(tile);
  }
  els.landingGrid.replaceChildren(frag);
}

function sortResults() {
  const key = state.sort;
  if (key === "index") return; // 生成時点で図鑑順
  // 初登場日が同じもの同士は図鑑順のまま（sort は安定）。日付不明は最後
  if (key === "new") return state.results.sort((a, b) => (b.debutAt ?? -1) - (a.debutAt ?? -1));
  if (key === "appear") state.results.sort((a, b) => b.appear.length - a.appear.length);
  else state.results.sort((a, b) => (b._base[key] ?? 0) - (a._base[key] ?? 0));
}

function renderFilters() {
  const frag = document.createDocumentFragment();
  let lastParent = null;
  let parentBody = null;

  for (const g of GROUPS) {
    const values = allValues(g.key);
    if (!values.length) continue; // 地域データが空なら出さない
    const counts = facetCounts(g.key);

    let body;
    if (g.parent) {
      // 「属性」の中に小見出しでまとめる
      if (lastParent !== g.parent) {
        parentBody = makeGroupShell(frag, g.parent, "parent:" + g.parent);
        lastParent = g.parent;
      }
      const sub = document.createElement("div");
      sub.className = "filters__subhead";
      sub.textContent = g.title;
      parentBody.appendChild(sub);
      body = parentBody;
    } else {
      lastParent = null;
      body = makeGroupShell(frag, g.title, "group:" + g.key, state.selected[g.key].size);
    }

    if (g.key === "content") renderContentOptions(body, values, counts);
    else for (const v of values) body.appendChild(optionRow(g.key, v, v, counts.get(v) || 0));
  }

  els.groups.replaceChildren(frag);
}

function makeGroupShell(parent, title, id, selectedCount = 0) {
  const group = document.createElement("section");
  group.className = "filters__group";
  const collapsed = state.collapsed.has(id);
  group.dataset.collapsed = collapsed;
  const head = document.createElement("button");
  head.className = "filters__group-head";
  head.setAttribute("aria-expanded", !collapsed);
  head.innerHTML = `<span>${esc(title)}${selectedCount ? `<span class="filters__badge">${selectedCount}</span>` : ""}</span><span class="filters__chevron" aria-hidden="true">▾</span>`;
  head.addEventListener("click", () => { toggleSet(state.collapsed, id); renderFilters(); });
  const body = document.createElement("div");
  body.className = "filters__group-body";
  group.append(head, body);
  parent.appendChild(group);
  return body;
}

function optionRow(key, value, label, count) {
  const row = document.createElement("label");
  const checked = state.selected[key].has(value);
  row.className = "filter-option" + (checked ? " filter-option--checked" : "") + (!count && !checked ? " filter-option--empty" : "");
  row.innerHTML = `<input type="checkbox" ${checked ? "checked" : ""}><span class="filter-option__label">${esc(label)}</span><span class="filter-option__count">${count}</span>`;
  row.querySelector("input").addEventListener("change", () => { toggleSet(state.selected[key], value); update(); });
  return row;
}

function renderContentOptions(body, values, counts) {
  const contents = state.data.contents;

  // コンテンツ名の絞り込み欄
  const finder = document.createElement("input");
  finder.type = "search";
  finder.className = "filters__finder";
  finder.placeholder = "イベント名などで探す";
  finder.value = state.contentQuery;
  finder.addEventListener("input", () => {
    state.contentQuery = finder.value.trim();
    renderFilters();
    const again = els.groups.querySelector(".filters__finder");
    again.focus();
    again.setSelectionRange(again.value.length, again.value.length);
  });
  body.appendChild(finder);

  const q = state.contentQuery.toLowerCase();
  const sel = state.selected.content;

  for (const cat of state.data.meta.categories) {
    const idxs = values.filter(i => contents[i].category === cat);
    const visible = q ? idxs.filter(i => (cat + contents[i].name).toLowerCase().includes(q)) : idxs;
    if (!visible.length) continue;

    const catId = "cat:" + cat;
    const open = q || !state.collapsed.has(catId);
    const nSel = idxs.filter(i => sel.has(i)).length;

    const head = document.createElement("div");
    head.className = "filters__cat";
    head.innerHTML = `
      <input type="checkbox" aria-label="${esc(cat)}をすべて選択">
      <button class="filters__cat-name" aria-expanded="${!!open}">
        <span>${esc(cat)}</span>
        <span class="filters__cat-meta">${nSel ? `${nSel}/` : ""}${idxs.length}</span>
        <span class="filters__chevron" aria-hidden="true">${open ? "▾" : "▸"}</span>
      </button>`;
    const box = head.querySelector("input");
    box.checked = nSel === idxs.length;
    box.indeterminate = nSel > 0 && nSel < idxs.length;
    box.addEventListener("change", () => {
      if (box.checked) idxs.forEach(i => sel.add(i));
      else idxs.forEach(i => sel.delete(i));
      update();
    });
    head.querySelector("button").addEventListener("click", () => { toggleSet(state.collapsed, catId); renderFilters(); });
    body.appendChild(head);

    if (!open) continue;
    const list = document.createElement("div");
    list.className = "filters__cat-list";
    for (const i of visible) list.appendChild(optionRow("content", i, contents[i].label || contents[i].name, counts.get(i) || 0));
    body.appendChild(list);
  }
}

function renderChips() {
  const frag = document.createDocumentFragment();
  const contents = state.data.contents;
  for (const g of GROUPS) {
    for (const v of state.selected[g.key]) {
      const chip = document.createElement("span");
      chip.className = "chip";
      const label = g.key === "content" ? contentLabel(v) : v;
      chip.innerHTML = `<span>${esc(label)}</span><button aria-label="${esc(label)}の条件を外す">×</button>`;
      chip.querySelector("button").addEventListener("click", () => { state.selected[g.key].delete(v); update(); });
      frag.appendChild(chip);
    }
  }
  els.chips.replaceChildren(frag);
}

// ---------- 次の絞り込みの候補 ----------

// 結果が多いときに一覧の上へ出す。まだ条件を選んでいないグループから、
// 結果を分けられる値（全件に当てはまらない値）を件数の多い順に並べる。
const SUGGEST_MIN_RESULTS = 24;
const SUGGEST_GROUPS = [
  { key: "content", title: "初登場", limit: 6 },
  { key: "rank",    title: "ランク", limit: 3 },
  { key: "race",    title: "種族",   limit: 4 },
  { key: "motion",  title: "移動",   limit: 2 },
  { key: "damage",  title: "攻撃",   limit: 3 },
];

function renderSuggestions() {
  const list = state.results;
  const rows = [];
  if (list.length >= SUGGEST_MIN_RESULTS) {
    for (const g of SUGGEST_GROUPS) {
      if (state.selected[g.key].size) continue;
      const counts = new Map();
      for (const e of list) for (const v of new Set(e._values[g.key])) counts.set(v, (counts.get(v) || 0) + 1);
      const order = FIXED_ORDER[g.key];
      const values = [...counts]
        .filter(([v, n]) => n < list.length && v !== "種族なし")
        .sort((a, b) => order ? order.indexOf(a[0]) - order.indexOf(b[0]) : b[1] - a[1])
        .slice(0, g.limit);
      if (values.length) rows.push({ g, values });
    }
  }
  els.suggest.hidden = !rows.length;
  if (!rows.length) return;

  const frag = document.createDocumentFragment();
  const head = document.createElement("div");
  head.className = "suggest__title";
  head.textContent = "さらに絞り込む";
  frag.appendChild(head);
  for (const { g, values } of rows) {
    const row = document.createElement("div");
    row.className = "suggest__row";
    row.innerHTML = `<span class="suggest__label">${esc(g.title)}</span>`;
    for (const [v, n] of values) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "suggest__chip";
      const label = g.key === "content" ? contentLabel(v) : v;
      b.innerHTML = `<span>${esc(label)}</span><span class="suggest__count">${n}</span>`;
      b.addEventListener("click", () => {
        state.selected[g.key].add(v);
        update();
        window.scrollTo({ top: 0 });
      });
      row.appendChild(b);
    }
    frag.appendChild(row);
  }
  els.suggest.replaceChildren(frag);
}

function renderResults() {
  const list = state.results;
  els.count.textContent = list.length;
  els.empty.hidden = list.length > 0;
  renderSuggestions();
  const frag = document.createDocumentFragment();
  for (const e of list.slice(0, state.shown)) frag.appendChild(card(e));
  els.grid.replaceChildren(frag);
  const rest = list.length - state.shown;
  els.more.hidden = rest <= 0;
  els.more.textContent = `さらに表示（残り ${rest} 体）`;
}

function card(e) {
  const el = document.createElement("button");
  el.className = "card";
  const s = e._base;
  el.innerHTML = `
    <div class="card__top">
      ${iconHtml(e, "card__icon")}
      <div class="card__titles">
        <div class="card__index">${esc(e.index || "")}</div>
        <div class="card__name">${esc(e.name)}</div>
      </div>
      <span class="rank-badge rank-badge--${rankClass(e.rank)}">${esc(e.rank)}</span>
    </div>
    <div class="card__meta">${esc([...new Set([e.races.join("・"), e.motion, e.attackRange, e.damage.join("・")].filter(Boolean))].join(" / "))}</div>
    <dl class="card__stats">
      <div><dt>HP</dt><dd>${num(s.hp, true)}</dd></div>
      <div><dt>攻撃</dt><dd>${num(s.atk)}</dd></div>
      <div><dt>防御</dt><dd>${num(s.def)}</dd></div>
      <div><dt>術耐性</dt><dd>${num(s.res)}</dd></div>
    </dl>`;
  el.addEventListener("click", () => openDetail(e));
  return el;
}

// ---------- 詳細パネル ----------

function openDetail(e) {
  const contents = state.data.contents;
  const statRows = [
    ["HP", "hp"], ["攻撃力", "atk"], ["防御力", "def"], ["術耐性", "res"],
    ["攻撃間隔", "interval"], ["移動速度", "speed"], ["重量", "weight"], ["射程", "range"], ["耐久値減少", "lifeReduce"],
  ];
  const lvHead = e.stats.map((_, i) => `<th>Lv${i}</th>`).join("");
  const lvBody = statRows.map(([label, k]) =>
    `<tr><th>${label}</th>${e.stats.map(s => `<td>${k === "range" ? rangeText(s[k]) : num(s[k], k === "hp")}</td>`).join("")}</tr>`).join("");

  const byCat = {};
  for (const [idx, codes] of e.appear) (byCat[contents[idx].category] ??= []).push([contents[idx].label || contents[idx].name, codes, idx]);
  const appearHtml = state.data.meta.categories.filter(c => byCat[c]).map(c => `
    <div class="detail__appear-cat">${esc(c)}</div>
    <ul class="detail__appear">
      ${byCat[c].map(([name, codes, idx]) => `<li><span>${esc(name)}${idx === e.debut ? `<span class="detail__debut">初登場</span>` : ""}</span>${codes.length ? `<span class="detail__codes">${esc(shortCodes(codes))}</span>` : ""}</li>`).join("")}
    </ul>`).join("") || `<p class="detail__none">登場ステージのデータが見つかりませんでした。</p>`;

  els.detailCard.innerHTML = `
    <button class="detail__close" id="detailClose" aria-label="閉じる">×</button>
    <div class="detail__head">
      ${iconHtml(e, "detail__icon")}
      <div>
        <div class="detail__index">${esc(e.index || "")}</div>
        <h2 class="detail__name">${esc(e.name)}</h2>
      </div>
    </div>
    <div class="detail__tags">
      <span class="rank-badge rank-badge--${rankClass(e.rank)}">${esc(e.rank)}</span>
      ${[...new Set([...e.races, e.motion, e.attackRange, ...e.damage].filter(Boolean))].map(t => `<span class="tag">${esc(t)}</span>`).join("")}
    </div>
    ${e.debut != null ? `<p class="detail__region">初登場: <span>${esc(contents[e.debut].name)}</span></p>` : ""}
    ${e.regions.length ? `<p class="detail__region">勢力 / 地域: ${e.regions.map(r => `<span class="tag tag--region">${esc(r)}</span>`).join(" ")}${e.regionFrom != null && e.regionFrom !== e.debut ? `<span class="detail__region-from">（${esc(contents[e.regionFrom].name)} の地域）</span>` : ""}</p>` : ""}

    ${e.abilities.length ? `<h3 class="detail__h">能力</h3><ul class="detail__abilities">${e.abilities.map(a => `<li>${esc(a)}</li>`).join("")}</ul>` : ""}

    <h3 class="detail__h">ステータス</h3>
    <div class="detail__table-wrap">
      <table class="detail__table"><thead><tr><th></th>${lvHead}</tr></thead><tbody>${lvBody}</tbody></table>
    </div>

    <h3 class="detail__h">登場コンテンツ（${e.appear.length}）</h3>
    ${appearHtml}

    <h3 class="detail__h">説明</h3>
    <p class="detail__desc">${esc(e.description)}</p>
    <p class="detail__id">${esc(e.id)}</p>`;
  $("detailClose").addEventListener("click", closeDetail);
  els.detail.hidden = false;
  document.body.style.overflow = "hidden";
  $("detailClose").focus();
}

function closeDetail() {
  els.detail.hidden = true;
  document.body.style.overflow = "";
}

function shortCodes(codes) {
  const MAX = 10;
  return codes.length > MAX ? codes.slice(0, MAX).join(", ") + ` ほか${codes.length - MAX}件` : codes.join(", ");
}

// ---------- イベント ----------

function bindEvents() {
  let timer;
  els.search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { state.query = els.search.value.trim().toLowerCase(); update(); }, 120);
  });
  els.sort.addEventListener("change", () => { state.sort = els.sort.value; update(); });
  els.browseAll.addEventListener("click", () => { state.browseAll = true; update(); window.scrollTo({ top: 0 }); });
  els.more.addEventListener("click", () => { state.shown += PAGE_SIZE * 2; renderResults(); });
  els.reset.addEventListener("click", goHome);
  // タイトルを押すと最初の画面（地域のタイル）に戻る
  $("homeLink").addEventListener("click", ev => {
    ev.preventDefault();
    closeDetail();
    goHome();
    window.scrollTo({ top: 0 });
  });
  els.scrim.addEventListener("click", closeDetail);
  document.addEventListener("keydown", ev => { if (ev.key === "Escape" && !els.detail.hidden) closeDetail(); });
  els.mobileToggle.addEventListener("click", () => {
    const open = els.filters.classList.toggle("filters--open");
    els.mobileToggle.setAttribute("aria-expanded", open);
    els.mobileToggle.textContent = open ? "絞り込み条件を閉じる" : "絞り込み条件を開く";
  });
}

// すべての条件を外して最初の画面に戻す
function goHome() {
  state.query = ""; els.search.value = "";
  state.contentQuery = "";
  GROUPS.forEach(g => state.selected[g.key].clear());
  state.browseAll = false;
  update();
}

// ---------- 敵の画像 ----------

// 画像はこのリポジトリには置かず、yuanyan3060/ArknightsGameResource（ゲームの素材を自動更新で
// 公開しているリポジトリ）を jsDelivr 経由で読み込む。ファイル名は敵IDそのまま。
const ICON_BASE = "https://cdn.jsdelivr.net/gh/yuanyan3060/ArknightsGameResource@main/enemy/";

// 読み込めなかったときは枠に「画像なし」と出す（代わりの画像は使わず、異変に気づけるようにする）
function iconHtml(e, cls) {
  return `<span class="icon ${cls}"><img src="${ICON_BASE}${encodeURIComponent(e.id)}.png" alt="" loading="lazy" decoding="async" onerror="this.parentNode.classList.add('icon--missing');this.remove()"></span>`;
}

// ---------- ユーティリティ ----------

function toggleSet(set, v) { set.has(v) ? set.delete(v) : set.add(v); }
function rankClass(rank) { return { "通常": "normal", "エリート": "elite", "ボス": "boss" }[rank] || "normal"; }
// 射程。-1 などの負の値は範囲の設定が無いので「-」
function rangeText(r) { return typeof r === "number" && r < 0 ? "-" : num(r); }

// 数値の表示。カンマ区切りはHPだけ
function num(n, comma = false) {
  if (n === undefined || n === null) return "-";
  return comma ? Number(n).toLocaleString() : String(n);
}
function esc(str) {
  return String(str ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
