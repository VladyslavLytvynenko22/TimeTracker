(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
  const KIND_LABEL = { work: "Work", nonwork: "Not work", afk: "Away" };
  const KIND_COLOR = { work: "var(--work)", nonwork: "var(--nonwork)", afk: "var(--afk)" };
  const CAT_PALETTE = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
  const OTHER_COLOR = "#6b6b72";
  let chartMode = "kind";
  try { chartMode = localStorage.getItem("tt.chartMode") || "kind"; } catch (e) { chartMode = "kind"; }
  const DAY = 86400;

  const state = {
    view: "overview", range: "day", date: null, summary: null, status: null,
    categories: [], rules: [], overrides: [], settings: null,
    rv: { q: "", kind: "", group: "title", min: 0 },
  };

  async function api(path, method = "GET", body) {
    const opts = { method, headers: {} };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) throw new Error((data && data.error) || ("Request failed: " + r.status));
    return data;
  }

  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const escRe = s => String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const pad2 = n => String(n).padStart(2, "0");

  function fmt(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    if (h) return h + "h " + pad2(m) + "m";
    if (m) return m + "m";
    return sec + "s";
  }
  const fmtH = sec => { const h = sec / 3600; return (Math.round(h * 10) / 10) + "h"; };
  const clock = ts => { const d = new Date(ts * 1000); return pad2(d.getHours()) + ":" + pad2(d.getMinutes()); };
  const iso = d => d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  const fromIso = s => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
  const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const DAYS_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const wd = d => (d.getDay() + 6) % 7;
  function weekNo(d) {
    const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
    const day = x.getUTCDay() || 7;
    x.setUTCDate(x.getUTCDate() + 4 - day);
    const y0 = new Date(Date.UTC(x.getUTCFullYear(), 0, 1));
    return Math.ceil(((x - y0) / 86400000 + 1) / 7);
  }

  let toastTimer = null;
  function toast(msg, isErr) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast" + (isErr ? " err" : "");
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, isErr ? 5000 : 2200);
  }
  const fail = e => toast(e.message || String(e), true);

  const tip = $("#tooltip");
  function showTip(html, ev) {
    tip.innerHTML = html;
    tip.hidden = false;
    moveTip(ev);
  }
  function moveTip(ev) {
    const pad = 14, w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + w > window.innerWidth - 8) x = ev.clientX - w - pad;
    if (y + h > window.innerHeight - 8) y = ev.clientY - h - pad;
    tip.style.left = x + "px";
    tip.style.top = y + "px";
  }
  const hideTip = () => { tip.hidden = true; };

  function catById(id) { return state.categories.find(c => c.id === id); }
  function catColor(id, kind) { const c = catById(id); return (c && c.color) || KIND_COLOR[kind] || KIND_COLOR.work; }
  function isGroup(c) {
    return state.categories.some(o => o.path.startsWith(c.path + " > ")) && !(state.rules || []).some(r => r.category_id === c.id);
  }
  function pickableCats(keepId) { return state.categories.filter(c => c.id === keepId || !isGroup(c)); }
  function catOptions(selected, extra) {
    const groups = { work: [], nonwork: [], afk: [] };
    pickableCats(selected).forEach(c => groups[c.kind].push(c));
    let html = extra || "";
    for (const k of ["work", "nonwork", "afk"]) {
      if (!groups[k].length) continue;
      html += `<optgroup label="${KIND_LABEL[k]}">` + groups[k].map(c =>
        `<option value="${c.id}" ${c.id === selected ? "selected" : ""}>${esc(c.path)}</option>`).join("") + "</optgroup>";
    }
    return html;
  }

  async function loadMeta() {
    const [cats, rules, overrides] = await Promise.all([api("/api/categories"), api("/api/rules"), api("/api/overrides")]);
    state.categories = cats;
    state.rules = rules.rules;
    state.brokenRules = rules.broken;
    state.overrides = overrides;
  }

  async function loadSummary() {
    const s = await api(`/api/summary?range=${state.range}&date=${iso(state.date)}`);
    state.summary = s;
    renderDateLabel();
    if (state.view === "overview") renderOverview();
    if (state.view === "review") renderReview();
  }

  async function refreshStatus() {
    try {
      const st = await api("/api/status");
      state.status = st;
      const live = $("#live");
      live.className = "live " + (st.paused ? "paused" : st.kind);
      let txt;
      if (st.paused) txt = "Tracking paused";
      else if (st.skipped) txt = "Private window · not recorded";
      else if (st.call) txt = `On a call (${(st.call_apps || []).join(", ")}) · ${st.category.split(" > ").pop()} · ${st.app}${st.title ? " · " + st.title : ""}`;
      else if (st.afk) txt = "Away · " + st.title;
      else txt = `${KIND_LABEL[st.kind]} · ${st.category.split(" > ").pop()}${st.media ? " · playing" : ""} · ${st.app}${st.title ? " · " + st.title : ""}`;
      $("#live .live-text").textContent = txt;
      live.title = txt + (st.since ? `\nsince ${clock(st.since)}` : "");
      const pb = $("#pause-btn");
      if (pb) pb.textContent = st.paused ? "Resume tracking" : "Pause tracking";
      if (!state.date) { state.date = fromIso(st.today); }
      document.title = st.paused ? "TimeTracker (paused)" : "TimeTracker";
    } catch (e) {
      $("#live").className = "live";
      $("#live .live-text").textContent = "tracker not reachable";
    }
  }

  function isToday() { return state.status && iso(state.date) === state.status.today; }

  function renderDateLabel() {
    const d = state.date, s = state.summary;
    let label;
    if (state.range === "day") {
      const t = state.status ? fromIso(state.status.today) : new Date();
      const diff = Math.round((d - t) / 86400000);
      const rel = diff === 0 ? "Today, " : diff === -1 ? "Yesterday, " : diff === 1 ? "Tomorrow, " : "";
      label = `${rel}${DAYS_LONG[wd(d)]} ${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)}${d.getFullYear() !== t.getFullYear() ? " " + d.getFullYear() : ""}`;
    } else if (state.range === "week") {
      const a = s ? fromIso(s.range.first) : addDays(d, -wd(d)), b = addDays(a, 6);
      const sameMonth = a.getMonth() === b.getMonth();
      label = `${a.getDate()}${sameMonth ? "" : " " + MONTHS[a.getMonth()].slice(0, 3)} – ${b.getDate()} ${MONTHS[b.getMonth()].slice(0, 3)} ${b.getFullYear()} · Week ${weekNo(a)}`;
    } else {
      label = `${MONTHS[d.getMonth()]} ${d.getFullYear()}`;
    }
    $("#datelabel").textContent = label;
    $$("#rangeseg button").forEach(b => b.classList.toggle("on", b.dataset.range === state.range));
  }

  function renderOverview() {
    const s = state.summary;
    if (!s) return;
    const t = s.totals, target = s.target_minutes * 60;
    const activeDays = s.days.filter(x => x.work + x.nonwork > 0).length;
    const isDay = state.range === "day";
    $("#hero-label").textContent = isDay ? (isToday() ? "Worked today" : "Worked that day") : (state.range === "week" ? "Worked this week" : "Worked this month");
    $("#hero-value").textContent = fmt(t.work);
    const goal = s.targets ? s.targets.range : target;
    const vsTarget = (work, tg) => work >= tg ? `${fmt(work - tg)} over the ${fmtH(tg)} target` : `${fmt(tg - work)} left to the ${fmtH(tg)} target`;
    let sub = goal ? vsTarget(t.work, goal) : "no target";
    if (!isDay) {
      const wdCount = s.workdays ? s.days.filter(x => s.workdays.includes(wd(fromIso(x.date)))).length : 0;
      sub += ` · ${wdCount} work day${wdCount === 1 ? "" : "s"} × ${fmtH(target)}`;
      if (activeDays) sub += ` · average ${fmt(t.work / activeDays)} per active day`;
    }
    $("#hero-sub").textContent = sub;
    const fillMeter = (fillEl, overEl, work, tg) => {
      $(fillEl).style.width = Math.min(100, tg ? work / tg * 100 : 0) + "%";
      $(overEl).style.width = (tg && work > tg ? Math.min(100, (work - tg) / tg * 100) : 0) + "%";
    };
    fillMeter("#meter-fill", "#meter-over", t.work, goal);
    const wk = $("#hero-week");
    if (isDay && s.week && s.week.work != null && s.targets.week) {
      wk.hidden = false;
      const a = fromIso(s.week.first), b = fromIso(s.week.last);
      $("#hero-week-text").textContent = `This week ${fmt(s.week.work)} · ${vsTarget(s.week.work, s.targets.week)}`;
      $("#hero-week-range").textContent = `${a.getDate()} ${MONTHS[a.getMonth()].slice(0, 3)} – ${b.getDate()} ${MONTHS[b.getMonth()].slice(0, 3)}`;
      fillMeter("#meter-week-fill", "#meter-week-over", s.week.work, s.targets.week);
    } else wk.hidden = true;
    $("#t-nonwork").textContent = fmt(t.nonwork);
    $("#t-nonwork-sub").textContent = t.active ? Math.round(t.nonwork / t.active * 100) + "% of time at the computer" : "";
    $("#t-afk").textContent = fmt(t.afk);
    $("#t-active").textContent = fmt(t.active);
    $("#t-active-sub").textContent = t.active ? `work ${Math.round(t.work / t.active * 100)}% · not work ${Math.round(t.nonwork / t.active * 100)}%` : "";
    $("#t-untracked").textContent = fmt(t.untracked);

    $("#tape-wrap").hidden = !isDay;
    $("#columns-wrap").hidden = isDay;
    $("#chart-title").textContent = isDay ? "The day" : "Hours per day";
    $("#chart-hint").textContent = isDay ? "Hover a block for details, click to change its category" : "Hover a day for its top categories, click to open it";
    $("#chart-mode").hidden = isDay;
    $$("#chart-mode button").forEach(b => b.classList.toggle("on", b.dataset.mode === chartMode));
    const exp = `range=${state.range}&date=${iso(state.date)}`;
    $("#exp-windows").href = `/api/export.csv?${exp}&mode=windows`;
    $("#exp-days").href = `/api/export.csv?${exp}&mode=days`;
    $("#exp-segments").href = `/api/export.csv?${exp}&mode=segments`;
    if (isDay) renderTape(); else renderColumns();
    renderCategories();
    renderTopItems();
    renderFilterBar();
  }

  const catFilter = new Set();
  const catMatch = path => catFilter.size === 0 || [...catFilter].some(sel => path === sel || path.startsWith(sel + " > "));
  function renderFilterBar() {
    const bar = $("#filter-bar");
    if (!catFilter.size) { bar.hidden = true; return; }
    const s = state.summary;
    const total = s ? s.categories.filter(c => catMatch(c.path)).reduce((a, c) => a + c.seconds, 0) : 0;
    bar.hidden = false;
    bar.innerHTML = `<span>Showing only</span>` + [...catFilter].map(p => `<button class="chip" data-path="${esc(p)}" title="Remove">${esc(p)} ×</button>`).join("") +
      `<span class="hint">${fmt(total)} in this range</span><button class="tiny" id="filter-clear">Clear</button>`;
  }
  function toggleCat(path) {
    if (catFilter.has(path)) catFilter.delete(path);
    else {
      for (const p of [...catFilter]) { if (p.startsWith(path + " > ") || path.startsWith(p + " > ")) catFilter.delete(p); }
      catFilter.add(path);
    }
    if (state.summary) { if (state.view === "overview") renderOverview(); else renderReview(); }
    renderFilterBar();
  }

  const zoom = { v0: 0, v1: 1 };
  const resetZoom = () => { zoom.v0 = 0; zoom.v1 = 1; };

  function renderTape() {
    const s = state.summary, start = s.range.start, span = s.range.end - start;
    const tape = $("#tape");
    tape.innerHTML = "";
    const track = document.createElement("div");
    track.className = "track";
    s.timeline.forEach((b, i) => {
      const el = document.createElement("div");
      el.className = "blk " + b.kind + (catMatch(b.category) ? "" : " dim");
      el.style.left = ((b.start - start) / span * 100) + "%";
      el.style.width = Math.max(0.02, (b.end - b.start) / span * 100) + "%";
      el.style.background = b.color;
      el.dataset.i = i;
      track.appendChild(el);
    });
    if (isToday()) {
      const now = document.createElement("div");
      now.className = "now";
      now.style.left = ((s.now - start) / span * 100) + "%";
      track.appendChild(now);
    }
    tape.appendChild(track);
    applyZoom();
  }

  function applyZoom() {
    const s = state.summary;
    if (!s || state.range !== "day") return;
    const track = $("#tape .track");
    if (!track) return;
    const vs = zoom.v1 - zoom.v0;
    track.style.width = (100 / vs) + "%";
    track.style.left = (-zoom.v0 / vs * 100) + "%";
    const axis = $("#tape-axis");
    axis.innerHTML = "";
    const [h0, m0] = s.range.day_start.split(":").map(Number);
    const hours = vs * 24;
    const stepMin = hours > 12 ? 120 : hours > 6 ? 60 : hours > 3 ? 30 : hours > 1.2 ? 15 : hours > 0.4 ? 5 : 1;
    const startMin = Math.ceil(zoom.v0 * 1440 / stepMin) * stepMin;
    for (let m = startMin; m <= zoom.v1 * 1440 + 0.001; m += stepMin) {
      const f = (m / 1440 - zoom.v0) / vs;
      if (f < -0.001 || f > 1.001) continue;
      const sp = document.createElement("span");
      sp.style.left = (f * 100) + "%";
      const tot = h0 * 60 + m0 + m;
      const hh = Math.floor(tot / 60) % 24, mm = tot % 60;
      sp.textContent = stepMin >= 60 ? pad2(hh) : pad2(hh) + ":" + pad2(mm);
      if (f > 0.97) sp.style.transform = "translateX(-100%)";
      if (f < 0.03) sp.style.transform = "none";
      axis.appendChild(sp);
    }
    const zoomed = vs < 0.999;
    $("#zoom-reset").hidden = !zoomed;
    $("#chart-hint").textContent = zoomed ? "Scroll to zoom, drag to pan, double-click to reset" : "Hover a block for details, click to change it, scroll to zoom";
  }

  function zoomAt(fraction, factor) {
    const vs = zoom.v1 - zoom.v0;
    const t = zoom.v0 + fraction * vs;
    const ns = Math.min(1, Math.max(10 / 1440, vs * factor));
    let v0 = t - fraction * ns;
    v0 = Math.max(0, Math.min(1 - ns, v0));
    zoom.v0 = v0;
    zoom.v1 = v0 + ns;
    applyZoom();
  }

  function blockTip(b) {
    let html = `<b>${esc(b.category)}</b><div class="r"><span>${esc(b.app)}</span><span>${fmt(b.seconds)}</span></div>
      <div class="r"><span>${clock(b.start)} – ${clock(b.end)}</span><span>${KIND_LABEL[b.kind]}</span></div>`;
    if (b.titles.length) html += "<hr>" + b.titles.map(t => `<div class="r"><span>${esc(t.title || "(no title)")}</span><span>${fmt(t.seconds)}</span></div>`).join("");
    return html;
  }

  function renderColumns() {
    const s = state.summary, svg = $("#columns");
    const W = svg.clientWidth || 900, H = 260, padL = 40, padR = 12, padT = 18, padB = 26;
    const days = s.days, n = days.length;
    const target = s.target_minutes * 60;
    let maxV = Math.max(target, ...days.map(d => d.work + d.nonwork)) * 1.08;
    const stepH = maxV > 12 * 3600 ? 4 : maxV > 6 * 3600 ? 2 : 1;
    maxV = Math.ceil(maxV / (stepH * 3600)) * stepH * 3600;
    const plotW = W - padL - padR, plotH = H - padT - padB;
    const slot = plotW / n, bw = Math.min(24, slot * 0.62);
    const y = v => padT + plotH - v / maxV * plotH;
    const todayIso = state.status ? state.status.today : "";
    let out = "";
    for (let v = 0; v <= maxV; v += stepH * 3600) {
      out += `<line class="grid" x1="${padL}" x2="${W - padR}" y1="${y(v)}" y2="${y(v)}"/><text x="${padL - 8}" y="${y(v) + 4}" text-anchor="end">${v / 3600}h</text>`;
    }
    if (target <= maxV) {
      out += `<line class="target" x1="${padL}" x2="${W - padR}" y1="${y(target)}" y2="${y(target)}"/><text class="target-label" x="${W - padR}" y="${y(target) - 5}" text-anchor="end">target ${fmtH(target)}</text>`;
    }
    const gap = 2, r = 4;
    const series = chartSeries(s);
    days.forEach((d, i) => {
      const cx = padL + slot * i + slot / 2, x = cx - bw / 2;
      const segs = series.map(sr => [sr.color, sr.value(d)]).filter(sg => sg[1] > 0);
      let base = 0;
      segs.forEach((sg, j) => {
        const top = j === segs.length - 1;
        let y1 = y(base + sg[1]), y0 = y(base);
        if (j > 0) y0 -= gap;
        if (y0 - y1 < 1) y1 = y0 - 1;
        if (top && y0 - y1 >= r) {
          out += `<path fill="${sg[0]}" d="M${x},${y0} V${y1 + r} a${r},${r} 0 0 1 ${r},-${r} h${bw - 2 * r} a${r},${r} 0 0 1 ${r},${r} V${y0} Z"/>`;
        } else {
          out += `<rect fill="${sg[0]}" x="${x}" y="${y1}" width="${bw}" height="${Math.max(1, y0 - y1)}"/>`;
        }
        base += sg[1];
      });
      const dd = fromIso(d.date);
      const label = state.range === "week" ? `${DAYS[wd(dd)]} ${dd.getDate()}` : (n > 20 && dd.getDate() % 2 === 0 ? "" : String(dd.getDate()));
      out += `<text x="${cx}" y="${H - 8}" text-anchor="middle" class="${d.date === todayIso ? "today-label" : ""}">${label}</text>`;
      out += `<rect class="hit" data-i="${i}" x="${padL + slot * i}" y="${padT}" width="${slot}" height="${plotH}"/>`;
    });
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.innerHTML = out;
    const legend = $("#chart-legend");
    if (chartMode === "cat") {
      legend.hidden = false;
      legend.innerHTML = series.map(sr => `<span><i style="background:${sr.color}"></i>${esc(sr.label)}</span>`).join("");
    } else legend.hidden = true;
  }

  function chartSeries(s) {
    const dayCats = d => (d.categories || []).filter(x => catMatch(x.path));
    if (chartMode !== "cat") {
      if (!catFilter.size) return [{ label: "Work", color: KIND_COLOR.work, value: d => d.work }, { label: "Not work", color: KIND_COLOR.nonwork, value: d => d.nonwork }];
      return [{ label: "Work", color: KIND_COLOR.work, value: d => dayCats(d).filter(x => x.kind === "work").reduce((a, x) => a + x.seconds, 0) },
              { label: "Not work", color: KIND_COLOR.nonwork, value: d => dayCats(d).filter(x => x.kind === "nonwork").reduce((a, x) => a + x.seconds, 0) }];
    }
    const top = s.categories.filter(c => c.kind !== "afk" && catMatch(c.path)).slice(0, 7);
    const ids = new Set(top.map(c => c.id));
    const series = top.map((c, i) => ({ label: c.path, color: CAT_PALETTE[i], value: d => (d.categories || []).filter(x => x.id === c.id).reduce((a, x) => a + x.seconds, 0) }));
    series.push({ label: "Other", color: OTHER_COLOR, value: d => dayCats(d).filter(x => x.kind !== "afk" && !ids.has(x.id)).reduce((a, x) => a + x.seconds, 0) });
    return series;
  }

  function buildCatTree() {
    const s = state.summary, nodes = new Map();
    s.categories.forEach(c => {
      const parts = c.path.split(" > ");
      for (let i = 1; i <= parts.length; i++) {
        const p = parts.slice(0, i).join(" > ");
        let n = nodes.get(p);
        if (!n) { n = { path: p, name: parts[i - 1], depth: i - 1, total: 0, own: 0, kind: c.kind, color: c.color, children: [] }; nodes.set(p, n); }
        n.total += c.seconds;
        if (i === parts.length) { n.own += c.seconds; n.kind = c.kind; n.color = c.color; }
      }
    });
    const roots = [];
    nodes.forEach(n => {
      if (n.depth === 0) roots.push(n);
      else nodes.get(n.path.split(" > ").slice(0, -1).join(" > ")).children.push(n);
    });
    const sortRec = a => { a.sort((x, y) => y.total - x.total); a.forEach(n => sortRec(n.children)); };
    sortRec(roots);
    const flat = [];
    const walk = n => { flat.push(n); n.children.forEach(walk); };
    roots.forEach(walk);
    return flat;
  }

  function targetFactor() {
    const s = state.summary;
    if (!s || state.range === "day" || !s.targets || !s.targets.day) return 1;
    return s.targets.range / s.targets.day;
  }
  function renderCategories() {
    const list = $("#cat-list"), s = state.summary;
    const flat = buildCatTree();
    const max = Math.max(1, ...flat.filter(n => n.depth === 0).map(n => n.total));
    if (!flat.length) { list.innerHTML = `<p class="empty">Nothing tracked yet.</p>`; return; }
    const factor = targetFactor();
    list.innerHTML = flat.map(n => {
      const c = state.categories.find(x => x.path === n.path);
      const goal = c && c.target_min ? c.target_min * 60 * factor : 0;
      let val = fmt(n.total), bar;
      if (goal) {
        const pct = Math.min(100, n.total / goal * 100);
        const over = n.total > goal;
        val = `<span class="${over ? "hit" : ""}">${fmt(n.total)}</span> <span class="goal">/ ${fmt(goal)}</span>`;
        bar = `<div class="bar goal" title="${over ? fmt(n.total - goal) + " over the target" : fmt(goal - n.total) + " left to the target"}"><i style="width:${pct}%;background:${over ? "var(--hit)" : n.color}"></i></div>`;
      } else {
        bar = `<div class="bar"><i style="width:${n.total / max * 100}%;background:${n.color};opacity:${n.depth ? 0.55 : 1}"></i></div>`;
      }
      return `
      <div class="cat-row ${catFilter.has(n.path) ? "sel" : ""} ${catFilter.size && !catMatch(n.path) && ![...catFilter].some(p => p.startsWith(n.path + " > ")) ? "off" : ""}" data-path="${esc(n.path)}" title="Click to show only ${esc(n.path)}">
        <div class="name depth-${Math.min(3, n.depth)}"><i style="background:${n.color}"></i>${esc(n.name)}</div>
        <div class="val">${val}</div>
        ${bar}
      </div>`;
    }).join("");
  }

  function renderTopItems() {
    const items = state.summary.items.filter(it => catMatch(it.category)).slice(0, 12);
    const el = $("#top-items");
    if (!items.length) { el.innerHTML = `<p class="empty">Nothing tracked yet.</p>`; return; }
    el.innerHTML = items.map(it => `
      <div class="item-row">
        <i style="background:${catColor(it.category_id, it.kind)}" title="${esc(it.category)}"></i>
        <div class="t" title="${esc(it.title)}">${esc(it.title || "(no title)")} <span class="a">${esc(it.app)}</span></div>
        <div class="v">${fmt(it.seconds)}</div>
      </div>`).join("");
  }

  function reviewRows() {
    const s = state.summary;
    if (!s) return [];
    let items = s.items.filter(it => catMatch(it.category));
    const q = state.rv.q.trim().toLowerCase();
    if (q) items = items.filter(it => it.title.toLowerCase().includes(q) || it.app.toLowerCase().includes(q));
    if (state.rv.kind === "default") items = items.filter(it => it.source === "default");
    else if (state.rv.kind === "needs") items = items.filter(it => it.source === "default");
    else if (state.rv.kind) items = items.filter(it => it.kind === state.rv.kind);
    const minSec = (Number(state.rv.min) || 0) * 60;
    if (minSec > 0) items = items.filter(it => it.seconds >= minSec);
    if (state.rv.group === "app") {
      const m = new Map();
      items.forEach(it => {
        let g = m.get(it.app);
        if (!g) { g = { app: it.app, title: "", seconds: 0, count: 0, cats: new Map(), windows: 0 }; m.set(it.app, g); }
        g.seconds += it.seconds; g.count += it.count; g.windows++;
        g.cats.set(it.category_id, (g.cats.get(it.category_id) || 0) + it.seconds);
      });
      items = Array.from(m.values()).map(g => {
        const top = Array.from(g.cats.entries()).sort((a, b) => b[1] - a[1])[0];
        const c = catById(top[0]);
        return { ...g, category_id: top[0], category: c ? c.path : "?", kind: c ? c.kind : "work", source: g.cats.size > 1 ? "mixed" : "app", title: `${g.windows} window title${g.windows === 1 ? "" : "s"}` };
      }).sort((a, b) => b.seconds - a.seconds);
    }
    return items;
  }

  function sourceTag(src) {
    if (src === "manual") return `<span class="tag manual">manual</span>`;
    if (src === "call") return `<span class="tag">on a call</span>`;
    if (src === "block") return `<span class="tag block">block</span>`;
    if (src === "mixed") return `<span class="tag">mixed</span>`;
    if (src === "afk") return `<span class="tag">away</span>`;
    if (src === "default") return `<span class="tag">no rule</span>`;
    if (src === "app") return `<span class="tag">rules</span>`;
    if (src && src.startsWith("rule:")) {
      const r = state.rules.find(x => x.id === Number(src.slice(5)));
      return `<span class="tag" title="${esc(r ? r.pattern : "")}">rule</span>`;
    }
    return `<span class="tag">${esc(src)}</span>`;
  }

  function renderReview() {
    const rows = reviewRows(), body = $("#rv-body");
    $("#rv-empty").hidden = rows.length > 0;
    $("#rv-count").textContent = state.summary ? `${rows.length} of ${state.summary.item_count} windows` : "";
    const max = Math.max(1, ...rows.map(r => r.seconds));
    const byApp = state.rv.group === "app";
    body.innerHTML = rows.map((it, i) => `
      <tr data-i="${i}">
        <td class="app" title="${esc(it.app)}">${esc(it.app)}</td>
        <td class="title ${byApp ? "" : "clickable"}" title="${esc(it.title)}">${esc(it.title || "(no title)")}</td>
        <td><div class="catcell"><span class="kind-dot" style="background:${catColor(it.category_id, it.kind)}"></span><select class="cat-sel" ${it.source === "afk" ? "disabled" : ""}>${catOptions(it.category_id)}</select></div></td>
        <td class="num">${fmt(it.seconds)}</td>
        <td class="share"><i style="width:${it.seconds / max * 100}%;background:${catColor(it.category_id, it.kind)}"></i></td>
        <td class="src">${sourceTag(it.source)}</td>
        <td class="act"><button class="tiny mk-rule" title="Create a rule from this">Rule</button> ${it.source === "manual" ? `<button class="tiny clr" title="Remove the manual choice">×</button>` : ""}</td>
      </tr>`).join("");
    body._rows = rows;
    renderFilterBar();
  }

  async function setItemCategory(it, cid) {
    if (state.rv.group === "app") {
      const pattern = "^" + escRe(it.app) + "$";
      const existing = state.rules.find(r => r.pattern === pattern);
      if (existing) await api("/api/rules", "POST", { id: existing.id, pattern, category_id: cid, ignore_case: true, enabled: true });
      else await api("/api/rules", "POST", { pattern, category_id: cid, ignore_case: true, enabled: true, position: "top" });
      toast("Rule saved for " + it.app);
    } else {
      await api("/api/overrides", "POST", { app: it.app, title: it.title, category_id: cid });
      toast("Category changed");
    }
    await loadMeta();
    await loadSummary();
  }

  const modal = $("#modal"), modalBody = $("#modal-body");
  function openModal(html) { modalBody.innerHTML = html; if (!modal.open) modal.showModal(); }
  function closeModal() { if (modal.open) modal.close(); }
  modal.addEventListener("click", e => { if (e.target === modal) closeModal(); });

  function ruleModal(pre) {
    pre = pre || {};
    const isEdit = !!pre.id;
    openModal(`
      <h2>${isEdit ? "Edit rule" : "New rule"}</h2>
      <div class="field"><label for="m-pattern">Pattern</label><input id="m-pattern" type="text" value="${esc(pre.pattern || "")}" spellcheck="false"><span class="hint">Regular expression, checked against the window title and the app name. Example: anime|серіал|netflix</span></div>
      <div class="field check"><label><input id="m-ic" type="checkbox" ${pre.ignore_case === false ? "" : "checked"}> Ignore case</label></div>
      <div class="field"><label for="m-cat">Category</label><select id="m-cat">${catOptions(pre.category_id, `<option value="new">+ New category…</option>`)}</select></div>
      <div id="m-newcat" hidden>
        <div class="field"><label for="m-newname">Name</label><input id="m-newname" type="text" placeholder="e.g. Entertainment > Anime"></div>
        <div class="field"><label for="m-newkind">Counts as</label><select id="m-newkind"><option value="work">Work</option><option value="nonwork">Not work</option><option value="afk">Away</option></select></div>
      </div>
      <div class="field"><label>Would match</label><div><div class="preview" id="m-preview"><div>Type a pattern to preview.</div></div></div></div>
      <div class="actions"><span class="err" id="m-err"></span>${isEdit ? `<button type="button" class="danger" id="m-delete">Delete</button>` : ""}<button type="button" class="ghost" id="m-cancel">Cancel</button><button type="button" class="primary" id="m-save">${isEdit ? "Save rule" : "Add rule on top"}</button></div>`);
    const catSel = $("#m-cat"), newBox = $("#m-newcat");
    if (!pre.category_id && !isEdit) catSel.value = "new";
    newBox.hidden = catSel.value !== "new";
    catSel.onchange = () => { newBox.hidden = catSel.value !== "new"; };
    let timer = null;
    const preview = async () => {
      const pattern = $("#m-pattern").value;
      const box = $("#m-preview");
      if (!pattern.trim()) { box.innerHTML = "<div>Type a pattern to preview.</div>"; return; }
      const items = (state.summary ? state.summary.items : []).slice(0, 400);
      try {
        const r = await api("/api/rules/test", "POST", { pattern, ignore_case: $("#m-ic").checked, texts: items.map(it => ({ app: it.app, title: it.title })) });
        if (!r.ok) { box.innerHTML = `<div style="color:var(--over)">${esc(r.error)}</div>`; return; }
        const hits = items.filter((it, i) => r.matches[i]);
        box.innerHTML = (hits.length ? `<div class="m" style="color:var(--muted)">${hits.length} of ${items.length} windows in this range</div>` : `<div>No window in this range matches.</div>`) +
          hits.slice(0, 60).map(it => `<div class="m" title="${esc(it.title)}">${esc(it.title || "(no title)")} <span style="color:var(--muted)">${esc(it.app)} · ${fmt(it.seconds)}</span></div>`).join("");
      } catch (e) { box.innerHTML = `<div style="color:var(--over)">${esc(e.message)}</div>`; }
    };
    $("#m-pattern").oninput = () => { clearTimeout(timer); timer = setTimeout(preview, 250); };
    $("#m-ic").onchange = preview;
    preview();
    $("#m-cancel").onclick = closeModal;
    if (isEdit) $("#m-delete").onclick = async () => {
      try { await api("/api/rules/" + pre.id, "DELETE"); closeModal(); toast("Rule deleted"); await afterRuleChange(); } catch (e) { fail(e); }
    };
    $("#m-save").onclick = async () => {
      const err = $("#m-err");
      err.textContent = "";
      try {
        let cid = catSel.value;
        if (cid === "new") {
          const name = $("#m-newname").value.trim();
          if (!name) throw new Error("Give the new category a name.");
          const r = await api("/api/categories", "POST", { path: name, kind: $("#m-newkind").value });
          cid = r.id;
        }
        const body = { pattern: $("#m-pattern").value, ignore_case: $("#m-ic").checked, category_id: Number(cid), enabled: isEdit ? pre.enabled !== 0 : true };
        if (isEdit) body.id = pre.id; else body.position = "top";
        await api("/api/rules", "POST", body);
        closeModal();
        toast(isEdit ? "Rule saved" : "Rule added");
        await afterRuleChange();
      } catch (e) { err.textContent = e.message; }
    };
    setTimeout(() => $("#m-pattern").focus(), 50);
  }

  async function afterRuleChange() {
    await loadMeta();
    if (state.view === "rules") renderRules();
    await loadSummary();
  }

  function categoryModal(pre) {
    pre = pre || {};
    const isEdit = !!pre.id;
    openModal(`
      <h2>${isEdit ? "Edit category" : "New category"}</h2>
      <div class="field"><label for="c-name">Name</label><input id="c-name" type="text" value="${esc(pre.path || "")}" ${pre.protected ? "readonly" : ""} placeholder="Work > Development > SQL"><span class="hint">Use " > " to nest under a parent.</span></div>
      <div class="field"><label for="c-kind">Counts as</label><select id="c-kind"><option value="work">Work</option><option value="nonwork">Not work</option><option value="afk">Away</option></select></div>
      <div class="field"><label for="c-color">Color</label><div class="unit"><input id="c-color" type="color" value="${esc(pre.color || "#3987e5")}"><button type="button" class="tiny" id="c-color-reset">Use the kind's color</button></div></div>
      <div class="field"><label for="c-target-h">Daily target</label><div class="unit"><input id="c-target-h" type="number" min="0" max="24" class="short" value="${Math.floor((pre.target_min || 0) / 60)}"><span>h</span><input id="c-target-m" type="number" min="0" max="59" class="short" value="${(pre.target_min || 0) % 60}"><span>min</span></div><span class="hint">Optional. Shown as progress in the category list; week and month multiply it by work days.</span></div>
      <div class="actions"><span class="err" id="c-err"></span>${isEdit && !pre.protected ? `<button type="button" class="danger" id="c-delete">Delete</button>` : ""}<button type="button" class="ghost" id="c-cancel">Cancel</button><button type="button" class="primary" id="c-save">Save</button></div>`);
    $("#c-kind").value = pre.kind || "work";
    let color = pre.color_raw || null;
    $("#c-color").oninput = e => { color = e.target.value; };
    $("#c-color-reset").onclick = () => { color = null; $("#c-color").value = { work: "#3987e5", nonwork: "#d95926", afk: "#6b6b72" }[$("#c-kind").value]; };
    $("#c-cancel").onclick = closeModal;
    if (isEdit && !pre.protected) $("#c-delete").onclick = async () => {
      if (!confirm(`Delete "${pre.path}"? Its rules and manual choices are removed too; the time moves to Uncategorized.`)) return;
      try { await api("/api/categories/" + pre.id, "DELETE"); closeModal(); toast("Category deleted"); await afterRuleChange(); } catch (e) { fail(e); }
    };
    $("#c-save").onclick = async () => {
      try {
        const body = { path: $("#c-name").value, kind: $("#c-kind").value, color,
          target_min: Number($("#c-target-h").value || 0) * 60 + Number($("#c-target-m").value || 0) };
        if (isEdit) body.id = pre.id;
        await api("/api/categories", "POST", body);
        closeModal();
        toast("Category saved");
        await afterRuleChange();
      } catch (e) { $("#c-err").textContent = e.message; }
    };
  }

  function blockModal(b) {
    openModal(`
      <h2>${esc(b.app)}</h2>
      <div class="meta"><div>${clock(b.start)} – ${clock(b.end)} · ${fmt(b.seconds)}</div><div>Now counted as <b>${esc(b.category)}</b> (${KIND_LABEL[b.kind]})</div></div>
      <div class="titles">${b.titles.map(t => `<div title="${esc(t.title)}">${esc(t.title || "(no title)")} · ${fmt(t.seconds)}</div>`).join("")}</div>
      <div class="field"><label for="b-cat">This block only</label><select id="b-cat">${catOptions(b.category_id)}</select><span class="hint">Changes just these ${b.ids.length} tracked segment${b.ids.length === 1 ? "" : "s"}; rules stay as they are.</span></div>
      <div class="actions"><button type="button" class="ghost" id="b-rule">Rule for this app…</button><button type="button" class="ghost" id="b-reset">Back to rules</button><button type="button" class="ghost" id="b-cancel">Close</button><button type="button" class="primary" id="b-save">Apply to block</button></div>`);
    $("#b-cancel").onclick = closeModal;
    $("#b-rule").onclick = () => ruleModal({ pattern: "^" + escRe(b.app) + "$", category_id: b.category_id });
    $("#b-reset").onclick = async () => { try { await api("/api/event-override", "POST", { ids: b.ids, category_id: null }); closeModal(); toast("Block follows the rules again"); await loadSummary(); } catch (e) { fail(e); } };
    $("#b-save").onclick = async () => { try { await api("/api/event-override", "POST", { ids: b.ids, category_id: Number($("#b-cat").value) }); closeModal(); toast("Block changed"); await loadSummary(); } catch (e) { fail(e); } };
  }

  async function itemEventsModal(it) {
    const s = state.summary;
    const evs = await api(`/api/events?from=${s.range.start}&to=${s.range.end}&app=${encodeURIComponent(it.app)}&title=${encodeURIComponent(it.title)}`);
    openModal(`
      <h2>${esc(it.title || "(no title)")}</h2>
      <div class="meta"><div>${esc(it.app)} · ${fmt(it.seconds)} in ${evs.length} segment${evs.length === 1 ? "" : "s"}</div></div>
      <div class="preview" style="max-height:320px">${evs.map(e => `<div class="m" style="display:flex;gap:12px;align-items:center">
        <span style="flex:none;font-variant-numeric:tabular-nums">${fromIso(iso(new Date(e.start * 1000))).getDate() !== state.date.getDate() && state.range !== "day" ? iso(new Date(e.start * 1000)).slice(5) + " " : ""}${clock(e.start)} – ${clock(e.end)}</span>
        <span style="flex:none;color:var(--muted);font-variant-numeric:tabular-nums">${fmt(e.end - e.start)}</span>
        <select class="ev-cat" data-id="${e.id}" style="flex:1;min-width:0;padding:2px 6px;font-size:12px">${catOptions(e.category_id)}</select>
        ${e.source === "block" ? `<button class="tiny ev-reset" data-id="${e.id}" title="Back to rules">↺</button>` : ""}</div>`).join("")}</div>
      <div class="actions"><button type="button" class="ghost" id="e-close">Close</button></div>`);
    $("#e-close").onclick = () => { closeModal(); loadSummary(); };
    $$(".ev-cat", modalBody).forEach(sel => sel.onchange = async () => {
      try { await api("/api/event-override", "POST", { ids: [Number(sel.dataset.id)], category_id: Number(sel.value) }); toast("Segment changed"); } catch (e) { fail(e); }
    });
    $$(".ev-reset", modalBody).forEach(btn => btn.onclick = async () => {
      try { await api("/api/event-override", "POST", { ids: [Number(btn.dataset.id)], category_id: null }); toast("Segment follows the rules again"); itemEventsModal(it); } catch (e) { fail(e); }
    });
  }

  function renderRules() {
    const body = $("#rules-body");
    const rules = state.rules;
    body.innerHTML = rules.map((r, i) => `
      <tr class="${r.enabled ? "" : "off"}" data-id="${r.id}">
        <td class="ord">${i + 1} <button class="up" title="Move up" ${i === 0 ? "disabled" : ""}>▲</button><button class="down" title="Move down" ${i === rules.length - 1 ? "disabled" : ""}>▼</button></td>
        <td class="pat"><code>${esc(r.pattern)}</code>${r.ignore_case ? "" : ` <span class="tag" title="Case sensitive">Aa</span>`}</td>
        <td class="cat"><span class="kind-dot" style="background:${KIND_COLOR[r.kind]}"></span>${esc(r.path)}</td>
        <td><input type="checkbox" class="en" ${r.enabled ? "checked" : ""} title="Enabled"></td>
        <td class="act"><button class="tiny edit">Edit</button></td>
      </tr>`).join("");
    const broken = $("#broken-rules");
    if (state.brokenRules && state.brokenRules.length) {
      broken.hidden = false;
      broken.innerHTML = "Some patterns are not valid and are skipped: " + state.brokenRules.map(b => `<code>${esc(b.pattern)}</code> (${esc(b.error)})`).join(", ");
    } else broken.hidden = true;

    $("#cat-admin").innerHTML = pickableCats().map(c => `
      <div class="row" data-id="${c.id}">
        <div class="n" title="${esc(c.path)}"><i style="background:${c.color}"></i>${esc(c.path)}${c.target_min ? ` <small class="k">target ${fmt(c.target_min * 60)}/day</small>` : ""}</div>
        <select class="k-sel" title="Counts as"><option value="work" ${c.kind === "work" ? "selected" : ""}>Work</option><option value="nonwork" ${c.kind === "nonwork" ? "selected" : ""}>Not work</option><option value="afk" ${c.kind === "afk" ? "selected" : ""}>Away</option></select>
        <button class="tiny edit">Edit</button>
      </div>`).join("");

    const ov = $("#override-list");
    ov.innerHTML = state.overrides.length ? state.overrides.map(o => `
      <div class="row" data-id="${o.id}">
        <div class="t" title="${esc(o.title)}">${esc(o.title || "(no title)")} <small>${esc(o.app)}</small></div>
        <div><span class="kind-dot" style="background:${KIND_COLOR[o.kind]}"></span>${esc(o.path)}</div>
        <button class="tiny del" title="Remove">×</button>
      </div>`).join("") : `<p class="hint">None yet. Change a category in Review to add one.</p>`;
  }

  let tryTimer = null;
  async function tryTitle() {
    const app = $("#try-app").value, title = $("#try-title").value;
    const box = $("#try-result");
    if (!app && !title) { box.textContent = "Type something above."; return; }
    try {
      const r = await api(`/api/categorize?app=${encodeURIComponent(app)}&title=${encodeURIComponent(title)}`);
      let how;
      if (r.source === "manual") how = "a manual choice from Review";
      else if (r.source === "default") how = "no rule matches, so it falls to the default";
      else if (r.source.startsWith("rule:")) { const rule = state.rules.find(x => x.id === Number(r.source.slice(5))); how = `rule ${state.rules.indexOf(rule) + 1}: <code>${esc(rule ? rule.pattern : "")}</code>`; }
      else how = r.source;
      box.innerHTML = `<span class="kind-dot" style="background:${KIND_COLOR[r.kind]}"></span><b>${esc(r.category)}</b> · ${KIND_LABEL[r.kind]} · ${how}`;
    } catch (e) { box.textContent = e.message; }
  }

  async function renderSettings() {
    const s = state.settings = await api("/api/settings");
    $("#s-day-start").value = s.day_start;
    $("#s-afk").value = s.afk_timeout_min;
    $("#s-target-h").value = Math.floor(s.work_target_min / 60);
    $("#s-target-m").value = s.work_target_min % 60;
    const wdays = s.workdays || [0, 1, 2, 3, 4];
    $$("#s-workdays input").forEach(cb => { cb.checked = wdays.includes(Number(cb.value)); });
    const updWdHint = () => {
      const n = $$("#s-workdays input:checked").length;
      const tg = Number($("#s-target-h").value) * 3600 + Number($("#s-target-m").value) * 60;
      $("#s-workdays-hint").textContent = `Week target: ${n} × ${fmtH(tg)} = ${fmtH(tg * n)}. The month target counts its work days the same way.`;
    };
    $$("#s-workdays input").forEach(cb => cb.onchange = updWdHint);
    $("#s-target-h").oninput = $("#s-target-m").oninput = updWdHint;
    updWdHint();
    $("#s-n-enabled").checked = !!s.notifications.enabled;
    $("#s-n-before").value = (s.notifications.before_end_min || []).join(", ");
    $("#s-n-end").checked = !!s.notifications.at_end;
    $("#s-n-over").checked = !!s.notifications.overtime;
    $("#s-n-over-every").value = s.notifications.overtime_every_min;
    $("#s-port").value = s.port;
    $("#s-private").value = s.private_windows || "hide";
    $("#s-media").checked = s.media_keeps_active !== false;
    const callSel = $("#s-calls-cat");
    callSel.innerHTML = pickableCats().filter(c => c.kind !== "afk").map(c => `<option value="${esc(c.path)}">${esc(c.path)}</option>`).join("");
    $("#s-calls").checked = !!s.calls_category;
    if (s.calls_category) callSel.value = s.calls_category;
    else if ([...callSel.options].some(o => o.value === "Work > Chat & Calls")) callSel.value = "Work > Chat & Calls";
    callSel.disabled = !$("#s-calls").checked;
    $("#s-calls").onchange = () => { callSel.disabled = !$("#s-calls").checked; };
    const ws = s.weekly_summary || {};
    $("#s-w-enabled").checked = ws.enabled !== false;
    $("#s-w-day").value = String(ws.weekday ?? 4);
    $("#s-w-time").value = ws.time || "18:00";
    $("#s-data-dir").textContent = s.data_dir;
    if (state.status) $("#pause-btn").textContent = state.status.paused ? "Resume tracking" : "Pause tracking";
  }

  async function saveSettings(e) {
    e.preventDefault();
    const msg = $("#settings-msg");
    try {
      const body = {
        day_start: $("#s-day-start").value,
        afk_timeout_min: Number($("#s-afk").value),
        work_target_min: Number($("#s-target-h").value) * 60 + Number($("#s-target-m").value),
        workdays: $$("#s-workdays input:checked").map(cb => Number(cb.value)),
        port: Number($("#s-port").value),
        private_windows: $("#s-private").value,
        media_keeps_active: $("#s-media").checked,
        calls_category: $("#s-calls").checked ? $("#s-calls-cat").value : "",
        weekly_summary: { enabled: $("#s-w-enabled").checked, weekday: Number($("#s-w-day").value), time: $("#s-w-time").value || "18:00" },
        notifications: {
          enabled: $("#s-n-enabled").checked, before_end_min: $("#s-n-before").value, at_end: $("#s-n-end").checked,
          overtime: $("#s-n-over").checked, overtime_every_min: Number($("#s-n-over-every").value),
        },
      };
      const s = await api("/api/settings", "POST", body);
      state.settings = s;
      msg.textContent = "Saved" + (s.port !== Number(location.port || 80) ? ". The new port applies after a restart." : ".");
      toast("Settings saved");
      state.summary = null;
      loadSummary();
    } catch (err) { msg.textContent = err.message; toast(err.message, true); }
  }

  function setView(v) {
    state.view = ["overview", "review", "rules", "settings"].includes(v) ? v : "overview";
    $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.view === state.view));
    $$(".view").forEach(m => { m.hidden = m.id !== "view-" + state.view; });
    $("#rangebar").hidden = !(state.view === "overview" || state.view === "review");
    if (state.view === "overview") { if (state.summary) renderOverview(); else loadSummary().catch(fail); }
    if (state.view === "review") { if (state.summary) renderReview(); else loadSummary().catch(fail); }
    if (state.view === "rules") renderRules();
    if (state.view === "settings") renderSettings().catch(fail);
  }

  function navigate(dir) {
    resetZoom();
    const d = state.date;
    if (state.range === "day") state.date = addDays(d, dir);
    else if (state.range === "week") state.date = addDays(d, 7 * dir);
    else { const x = new Date(d.getFullYear(), d.getMonth() + dir, 1); state.date = x; }
    loadSummary().catch(fail);
  }

  function bind() {
    window.addEventListener("hashchange", () => setView(location.hash.slice(1)));
    $$("#rangeseg button").forEach(b => b.onclick = () => { resetZoom(); state.range = b.dataset.range; loadSummary().catch(fail); });
    $("#prev").onclick = () => navigate(-1);
    $("#next").onclick = () => navigate(1);
    $("#today").onclick = () => { resetZoom(); state.date = fromIso(state.status.today); loadSummary().catch(fail); };
    const manualRefresh = async () => {
      const btn = $("#refresh");
      btn.disabled = true;
      try { await Promise.all([refreshStatus(), loadMeta()]); await loadSummary(); toast("Refreshed"); }
      catch (e) { fail(e); }
      finally { btn.disabled = false; }
    };
    $("#refresh").onclick = manualRefresh;
    document.addEventListener("keydown", e => {
      if (modal.open || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName) || $("#rangebar").hidden) return;
      if (e.key === "ArrowLeft") navigate(-1);
      if (e.key === "ArrowRight") navigate(1);
      if (e.key === "r" || e.key === "R") manualRefresh();
    });

    const tape = $("#tape");
    tape.addEventListener("mousemove", e => {
      const el = e.target.closest(".blk");
      if (!el) { hideTip(); return; }
      showTip(blockTip(state.summary.timeline[el.dataset.i]), e);
    });
    tape.addEventListener("mouseleave", hideTip);
    let drag = null;
    tape.addEventListener("click", e => {
      if (drag && drag.moved) { drag = null; return; }
      drag = null;
      const el = e.target.closest(".blk");
      if (el) { hideTip(); blockModal(state.summary.timeline[el.dataset.i]); }
    });
    tape.addEventListener("wheel", e => {
      if (state.range !== "day" || !state.summary) return;
      e.preventDefault();
      const r = tape.getBoundingClientRect();
      zoomAt((e.clientX - r.left) / r.width, e.deltaY < 0 ? 0.7 : 1 / 0.7);
      hideTip();
    }, { passive: false });
    tape.addEventListener("mousedown", e => {
      if (e.button !== 0) return;
      drag = { x: e.clientX, v0: zoom.v0, moved: false };
    });
    window.addEventListener("mousemove", e => {
      if (!drag) return;
      const r = tape.getBoundingClientRect();
      const dx = (e.clientX - drag.x) / r.width;
      if (Math.abs(e.clientX - drag.x) > 3) drag.moved = true;
      if (!drag.moved) return;
      const vs = zoom.v1 - zoom.v0;
      let v0 = Math.max(0, Math.min(1 - vs, drag.v0 - dx * vs));
      zoom.v0 = v0; zoom.v1 = v0 + vs;
      applyZoom();
      hideTip();
    });
    window.addEventListener("mouseup", () => { if (drag && !drag.moved) drag = null; });
    tape.addEventListener("dblclick", () => { resetZoom(); applyZoom(); });
    $("#zoom-reset").onclick = () => { resetZoom(); applyZoom(); };
    $("#cat-list").addEventListener("click", e => {
      const row = e.target.closest(".cat-row");
      if (row) toggleCat(row.dataset.path);
    });
    $("#filter-bar").addEventListener("click", e => {
      if (e.target.closest("#filter-clear")) { catFilter.clear(); if (state.summary) { if (state.view === "overview") renderOverview(); else renderReview(); } renderFilterBar(); return; }
      const chip = e.target.closest(".chip");
      if (chip) toggleCat(chip.dataset.path);
    });
    const cols = $("#columns");
    cols.addEventListener("mousemove", e => {
      const el = e.target.closest(".hit");
      if (!el) { hideTip(); return; }
      const d = state.summary.days[el.dataset.i], dd = fromIso(d.date);
      const top = (d.categories || []).filter(c => c.kind !== "afk").slice(0, 5);
      showTip(`<b>${DAYS_LONG[wd(dd)]} ${dd.getDate()} ${MONTHS[dd.getMonth()].slice(0, 3)}</b>
        <div class="r"><span>Work</span><span>${fmt(d.work)}</span></div><div class="r"><span>Not work</span><span>${fmt(d.nonwork)}</span></div><div class="r"><span>Away</span><span>${fmt(d.afk)}</span></div>` +
        (top.length ? "<hr>" + top.map(c => `<div class="r"><span><i class="kind-dot" style="background:${catColor(c.id, c.kind)}"></i>${esc(c.path)}</span><span>${fmt(c.seconds)}</span></div>`).join("") : ""), e);
    });
    cols.addEventListener("mouseleave", hideTip);
    cols.addEventListener("click", e => {
      const el = e.target.closest(".hit");
      if (!el) return;
      hideTip();
      state.date = fromIso(state.summary.days[el.dataset.i].date);
      state.range = "day";
      loadSummary().catch(fail);
    });
    window.addEventListener("resize", () => { if (state.view === "overview" && state.range !== "day" && state.summary) renderColumns(); });

    $("#rv-search").oninput = e => { state.rv.q = e.target.value; renderReview(); };
    $$("#rv-kind button").forEach(b => b.onclick = () => {
      $$("#rv-kind button").forEach(x => x.classList.remove("on")); b.classList.add("on"); state.rv.kind = b.dataset.kind;
      if (b.dataset.kind === "needs" && !(Number($("#rv-min").value) > 0)) { $("#rv-min").value = 10; state.rv.min = 10; }
      renderReview();
    });
    $("#rv-min").oninput = e => { state.rv.min = Number(e.target.value); renderReview(); };
    $$("#chart-mode button").forEach(b => b.onclick = () => {
      chartMode = b.dataset.mode;
      try { localStorage.setItem("tt.chartMode", chartMode); } catch (e) { }
      $$("#chart-mode button").forEach(x => x.classList.toggle("on", x === b));
      renderColumns();
    });
    document.addEventListener("click", e => { const m = $("#export-menu"); if (m.open && !m.contains(e.target)) m.open = false; });
    $$("#rv-group button").forEach(b => b.onclick = () => { $$("#rv-group button").forEach(x => x.classList.remove("on")); b.classList.add("on"); state.rv.group = b.dataset.group; renderReview(); });
    const rvBody = $("#rv-body");
    rvBody.addEventListener("change", e => {
      const sel = e.target.closest(".cat-sel");
      if (!sel) return;
      const it = rvBody._rows[e.target.closest("tr").dataset.i];
      setItemCategory(it, Number(sel.value)).catch(fail);
    });
    rvBody.addEventListener("click", e => {
      const tr = e.target.closest("tr");
      if (!tr) return;
      const it = rvBody._rows[tr.dataset.i];
      if (e.target.closest(".mk-rule")) {
        const pattern = state.rv.group === "app" ? "^" + escRe(it.app) + "$" : escRe(it.title);
        ruleModal({ pattern, category_id: it.category_id });
      } else if (e.target.closest(".clr")) {
        api("/api/overrides", "POST", { app: it.app, title: it.title, category_id: null }).then(() => { toast("Manual choice removed"); return afterRuleChange(); }).catch(fail);
      } else if (e.target.closest("td.title.clickable")) {
        itemEventsModal(it).catch(fail);
      }
    });

    $("#add-rule").onclick = () => ruleModal();
    $("#add-cat").onclick = () => categoryModal();
    $("#try-app").oninput = $("#try-title").oninput = () => { clearTimeout(tryTimer); tryTimer = setTimeout(tryTitle, 200); };
    const rulesBody = $("#rules-body");
    rulesBody.addEventListener("click", async e => {
      const tr = e.target.closest("tr");
      if (!tr) return;
      const id = Number(tr.dataset.id), idx = state.rules.findIndex(r => r.id === id);
      try {
        if (e.target.closest(".edit")) { ruleModal(state.rules[idx]); return; }
        if (e.target.closest(".up") || e.target.closest(".down")) {
          const ids = state.rules.map(r => r.id), j = e.target.closest(".up") ? idx - 1 : idx + 1;
          if (j < 0 || j >= ids.length) return;
          [ids[idx], ids[j]] = [ids[j], ids[idx]];
          await api("/api/rules/reorder", "POST", { ids });
          await afterRuleChange();
        }
      } catch (err) { fail(err); }
    });
    rulesBody.addEventListener("change", async e => {
      const en = e.target.closest(".en");
      if (!en) return;
      const r = state.rules.find(x => x.id === Number(e.target.closest("tr").dataset.id));
      try { await api("/api/rules", "POST", { id: r.id, pattern: r.pattern, category_id: r.category_id, ignore_case: !!r.ignore_case, enabled: en.checked }); await afterRuleChange(); } catch (err) { fail(err); }
    });
    const catAdmin = $("#cat-admin");
    catAdmin.addEventListener("click", e => {
      const row = e.target.closest(".row");
      if (!row || !e.target.closest(".edit")) return;
      const c = catById(Number(row.dataset.id));
      const raw = state.categories.find(x => x.id === c.id);
      categoryModal({ ...c, color_raw: raw.color });
    });
    catAdmin.addEventListener("change", async e => {
      const sel = e.target.closest(".k-sel");
      if (!sel) return;
      const c = catById(Number(e.target.closest(".row").dataset.id));
      try { await api("/api/categories", "POST", { id: c.id, path: c.path, kind: sel.value, color: null }); toast("Category updated"); await afterRuleChange(); } catch (err) { fail(err); }
    });
    $("#override-list").addEventListener("click", async e => {
      const row = e.target.closest(".row");
      if (!row || !e.target.closest(".del")) return;
      try { await api("/api/overrides/" + row.dataset.id, "DELETE"); toast("Manual choice removed"); await afterRuleChange(); } catch (err) { fail(err); }
    });
    $("#import-aw").onclick = () => $("#aw-file").click();
    $("#aw-file").onchange = async e => {
      const f = e.target.files[0];
      if (!f) return;
      try {
        const json = JSON.parse(await f.text());
        const r = await api("/api/import-aw", "POST", json);
        toast(`Imported ${r.rules_added} rule${r.rules_added === 1 ? "" : "s"}`);
        await afterRuleChange();
      } catch (err) { fail(err); }
      e.target.value = "";
    };

    $("#settings-form").onsubmit = saveSettings;
    $("#test-notify").onclick = async () => { try { const r = await api("/api/notify/test", "POST", {}); toast(r.ok ? "Notification sent" : "Notification could not be shown", !r.ok); } catch (e) { fail(e); } };
    $("#pause-btn").onclick = async () => { try { const r = await api("/api/pause", "POST", {}); toast(r.paused ? "Tracking paused" : "Tracking resumed"); refreshStatus(); } catch (e) { fail(e); } };
    $("#quit-btn").onclick = async () => {
      if (!confirm("Quit TimeTracker? Tracking stops until you start it again (or until the next Windows login).")) return;
      try { await api("/api/quit", "POST", {}); toast("TimeTracker is shutting down"); } catch (e) { fail(e); }
    };
  }

  async function init() {
    bind();
    await refreshStatus();
    if (!state.date) state.date = new Date();
    const qs = new URLSearchParams(location.search);
    if (["day", "week", "month"].includes(qs.get("range"))) state.range = qs.get("range");
    if (/^\d{4}-\d{2}-\d{2}$/.test(qs.get("date") || "")) state.date = fromIso(qs.get("date"));
    if (["kind", "cat"].includes(qs.get("chart"))) chartMode = qs.get("chart");
    try { await loadMeta(); } catch (e) { fail(e); }
    setView(location.hash.slice(1));
    const refreshCurrent = () => {
      if ((state.view === "overview" || state.view === "review") && state.summary && (state.range !== "day" || isToday())) loadSummary().catch(() => {});
    };
    setInterval(refreshStatus, 5000);
    setInterval(refreshCurrent, 30000);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") { refreshStatus(); refreshCurrent(); }
    });
    window.addEventListener("focus", () => { refreshStatus(); refreshCurrent(); });
  }
  init();
})();
