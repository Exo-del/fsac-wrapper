/* FSAC Portail local — frontend logic (vanilla JS, hash router) */
"use strict";

const API = {
  feed: (force) => `/api/feed?force=${force ? "true" : "false"}`,
  article: (kind, id, force) =>
    `/api/article/${encodeURIComponent(kind)}/${encodeURIComponent(id)}?force=${force ? "true" : "false"}`,
  stats: (force) => `/api/stats?force=${force ? "true" : "false"}`,
  pages: () => `/api/pages`,
  page: (slug) => `/api/pages/${encodeURIComponent(slug)}`,
  health: () => `/api/health`,
};

const KIND_LABEL = {
  annonce: "Annonce",
  event: "Événement",
  actu: "Actualité",
  recrut: "Recrutement",
};

const PAGE_TITLES = {
  presentation: "Présentation",
  departements: "Départements",
  formations: "Formations",
  recherche: "Recherche",
  espace_etu: "Espace étudiant",
};

const HOME_FEED_COUNT = 9;
const LIVE_INTERVAL_MS = 60_000;

const state = {
  route: "home", // home | news | page
  pageSlug: null,
  items: [],
  kind: "all",
  query: "",
  live: false,
  liveTimer: null,
  loaded: false,
  current: null, // open drawer article {kind, id}
  routeBeforeArticle: "",
  lastVisit: Number(localStorage.getItem("fsac_last_visit") || 0),
  newIds: new Set(),
  pages: null, // slug -> page data cache
  pageLoaded: false,
};

const $ = (sel) => document.querySelector(sel);
const els = {
  views: {
    home: $("#view-home"),
    news: $("#view-news"),
    page: $("#view-page"),
  },
  nav: $("#mainNav"),
  feed: $("#feed"),
  homeFeed: $("#homeFeed"),
  tabs: $("#tabs"),
  search: $("#search"),
  searchForm: $("#searchForm"),
  btnLive: $("#btnLive"),
  btnRefresh: $("#btnRefresh"),
  feedStatus: $("#feedStatus"),
  empty: $("#emptyState"),
  error: $("#errorState"),
  errorMsg: $("#errorMessage"),
  btnRetry: $("#btnRetry"),
  btnReset: $("#btnResetFilters"),
  statsRow: $("#statsRow"),
  pageCrumb: $("#pageCrumb"),
  pageTitle: $("#pageTitle"),
  pageNav: $("#pageNav"),
  pageContent: $("#pageContent"),
  drawer: $("#drawer"),
  backdrop: $("#drawerBackdrop"),
  drawerBody: $("#drawerBody"),
  drawerBadge: $("#drawerBadge"),
  drawerDate: $("#drawerDate"),
  btnClose: $("#btnCloseDrawer"),
  btnPrev: $("#btnPrev"),
  btnNext: $("#btnNext"),
  btnOriginal: $("#btnOriginal"),
  toasts: $("#toasts"),
  footerYear: $("#footerYear"),
};

/* ------------------------------ helpers ------------------------------ */

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

function setStatus(text) {
  if (els.feedStatus) els.feedStatus.textContent = text;
}

function toast(msg, kind = "info", ttl = 4000) {
  const el = document.createElement("div");
  el.className = "toast";
  el.dataset.kind = kind;
  const icon = kind === "ok" ? "✓" : kind === "err" ? "⚠" : "ℹ";
  el.innerHTML = `<strong>${icon}</strong><span>${escapeHtml(msg)}</span>`;
  els.toasts.appendChild(el);
  setTimeout(() => {
    el.classList.add("is-leaving");
    setTimeout(() => el.remove(), 260);
  }, ttl);
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  const body = await r.json().catch(() => null);
  if (!r.ok) {
    const detail = body && body.detail ? body.detail : `HTTP ${r.status}`;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return body;
}

function computeNewIds(items) {
  const cutoff = state.lastVisit > 0 ? state.lastVisit : Date.now() - 24 * 3600 * 1000;
  const set = new Set();
  for (const it of items) {
    if (!it.date) continue;
    const t = Date.parse(it.date);
    if (!isNaN(t) && t > cutoff) set.add(`${it.kind}:${it.id}`);
  }
  return set;
}

/* ------------------------------ router ------------------------------ */

function parseRoute() {
  const hash = location.hash.replace(/^#/, "");
  if (!hash || hash === "/") return { route: "home" };
  if (hash === "actualites" || hash === "/actualites") return { route: "news" };
  const m = hash.match(/^\/?page\/([a-z_]+)$/);
  if (m && PAGE_TITLES[m[1]]) return { route: "page", slug: m[1] };
  const legacy = hash.match(/^(annonce|event|actu|recrut)\/([\w-]+)$/);
  if (legacy) return { route: "article", kind: legacy[1], id: legacy[2] };
  return { route: "home" };
}

function setNavActive(key) {
  els.nav.querySelectorAll("a").forEach((a) => {
    a.classList.toggle("is-active", a.dataset.nav === key);
  });
}

async function navigate() {
  const r = parseRoute();

  if (r.route === "article") {
    // deep link to an article: show news view underneath, then open drawer
    showView("news");
    setNavActive("news");
    openArticle(r.kind, r.id, { fromRoute: false });
    return;
  }

  if (state.current) closeDrawer(true);

  if (r.route === "home") {
    showView("home");
    setNavActive("home");
    document.title = "FSAC — Portail local (preuve de concept)";
    if (!state.loaded) loadFeed();
    else renderHomeFeed();
    if (!els.statsRow.querySelector(".num")) loadStats();
    return;
  }

  if (r.route === "news") {
    showView("news");
    setNavActive("news");
    document.title = "Actualités — FSAC (clone)";
    if (!state.loaded) loadFeed();
    else renderFeed();
    return;
  }

  // page view
  showView("page");
  setNavActive(`page:${r.slug}`);
  document.title = `${PAGE_TITLES[r.slug]} — FSAC (clone)`;
  await loadContentPage(r.slug);
}

function showView(name) {
  state.route = name === "page" ? "page" : name;
  for (const [k, el] of Object.entries(els.views)) {
    if (el) el.classList.toggle("hidden", k !== name);
  }
  if (name !== "news") {
    // keep news state, just hide it
  }
}

/* ------------------------------ feed ------------------------------ */

function filtered() {
  const tokens = state.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  return state.items.filter((it) => {
    if (state.kind !== "all" && it.kind !== state.kind) return false;
    if (!tokens.length) return true;
    const hay = `${it.title} ${it.subtitle || ""} ${it.excerpt || ""}`.toLowerCase();
    return tokens.every((t) => hay.includes(t));
  });
}

function cardTemplate(item) {
  const label = KIND_LABEL[item.kind] || item.kind;
  const media = item.image
    ? `<div class="card-media"><img loading="lazy" referrerpolicy="no-referrer"
         src="${escapeHtml(item.image)}" alt=""
         onerror="this.closest('.card-media').innerHTML='&lt;span class=&quot;media-glyph&quot;&gt;${escapeHtml(
           label.toUpperCase().slice(0, 3)
         )}&lt;/span&gt;'"></div>`
    : `<div class="card-media"><span class="media-glyph">${escapeHtml(label.toUpperCase().slice(0, 3))}</span></div>`;

  const badgeNew = state.newIds.has(`${item.kind}:${item.id}`)
    ? `<span class="badge badge-new">Nouveau</span>`
    : "";
  const atts = item.attachment_count
    ? `<span class="att-count">📎 ${item.attachment_count}</span>`
    : "";
  const sub = item.subtitle
    ? `<p class="card-excerpt">${escapeHtml(item.subtitle)}</p>`
    : item.excerpt
      ? `<p class="card-excerpt">${escapeHtml(item.excerpt)}</p>`
      : "";

  return `
    <article class="card" role="button" tabindex="0"
      data-kind="${escapeHtml(item.kind)}" data-id="${escapeHtml(item.id)}">
      ${media}
      <div class="card-body">
        <div class="card-meta">
          <span class="badge" data-kind="${escapeHtml(item.kind)}">${escapeHtml(label)}</span>
          ${badgeNew || (item.date_display ? `<time class="card-date">${escapeHtml(item.date_display)}</time>` : "")}
        </div>
        <h3 class="card-title">${escapeHtml(item.title)}</h3>
        ${sub}
        <div class="card-foot">
          <span class="read">Lire →</span>
          ${atts}
        </div>
      </div>
    </article>`;
}

function renderFeed() {
  if (state.route !== "news") return;
  const list = filtered();
  els.feed.setAttribute("aria-busy", "false");

  if (!list.length) {
    els.feed.innerHTML = "";
    els.empty.classList.remove("hidden");
    els.error.classList.add("hidden");
    return;
  }
  els.empty.classList.add("hidden");
  els.error.classList.add("hidden");
  els.feed.innerHTML = list.map(cardTemplate).join("");
}

function renderHomeFeed() {
  els.homeFeed.setAttribute("aria-busy", "false");
  const list = state.items.slice(0, HOME_FEED_COUNT);
  els.homeFeed.innerHTML = list.length
    ? list.map(cardTemplate).join("")
    : `<p class="muted">Aucune actualité disponible pour le moment.</p>`;
}

function renderCounts(counts) {
  const map = {
    all: counts.total ?? "·",
    annonce: counts.annonce ?? 0,
    event: counts.event ?? 0,
    actu: counts.actu ?? 0,
    recrut: counts.recrut ?? 0,
  };
  for (const [k, v] of Object.entries(map)) {
    const el = document.getElementById(`count-${k}`);
    if (el) el.textContent = v;
  }
}

async function loadFeed({ force = false, silent = false } = {}) {
  if (!silent) {
    setStatus("Chargement du flux…");
    els.btnRefresh && els.btnRefresh.classList.add("is-spinning");
  }
  try {
    const data = await getJSON(API.feed(force));
    const beforeIds = new Set(state.items.map((i) => `${i.kind}:${i.id}`));
    state.items = data.items;
    state.newIds = computeNewIds(data.items);
    state.loaded = true;
    renderCounts(data.counts || {});
    renderFeed();
    renderHomeFeed();

    const fresh = data.items.filter((i) => !beforeIds.has(`${i.kind}:${i.id}`));
    const time = new Date().toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setStatus(`${data.items.length} éléments · ${time}`);
    if (force && beforeIds.size && fresh.length) {
      toast(`${fresh.length} nouvel(aux) élément(s) détecté(s)`, "ok");
    }
    state.lastVisit = Date.now();
    localStorage.setItem("fsac_last_visit", String(state.lastVisit));
  } catch (err) {
    console.error(err);
    if (!state.loaded && state.route === "news") {
      els.feed.innerHTML = "";
      els.error.classList.remove("hidden");
      els.empty.classList.add("hidden");
      els.errorMsg.textContent = err.message;
    }
    setStatus(`Erreur · ${err.message}`);
    if (state.loaded) toast(err.message, "err");
  } finally {
    els.btnRefresh && els.btnRefresh.classList.remove("is-spinning");
  }
}

/* ------------------------------ stats (home) ------------------------------ */

async function loadStats() {
  try {
    const data = await getJSON(API.stats(false));
    els.statsRow.innerHTML = data.stats
      .map(
        (s) => `<div class="stat-chip"><span class="num" data-target="${s.value}">0</span>
                <span class="lbl">${escapeHtml(s.label)}</span></div>`
      )
      .join("");
    animateCounters();
  } catch (err) {
    els.statsRow.innerHTML = `<div class="stat-chip" style="grid-column:1/-1">
      <span class="lbl">Chiffres indisponibles (${escapeHtml(err.message)})</span></div>`;
  }
}

function animateCounters() {
  const nums = els.statsRow.querySelectorAll(".num[data-target]");
  nums.forEach((el) => {
    const target = Number(el.dataset.target) || 0;
    const dur = 900;
    const t0 = performance.now();
    const step = (t) => {
      const p = Math.min((t - t0) / dur, 1);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = Math.round(target * eased).toLocaleString("fr-FR");
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/* ------------------------------ content pages ------------------------------ */

function partId(key) {
  return (
    "p-" +
    String(key)
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
  );
}

async function loadContentPage(slug) {
  els.pageCrumb.textContent = PAGE_TITLES[slug] || slug;
  els.pageTitle.textContent = "…";

  if (state.pages && state.pages[slug]) {
    renderContentPage(slug, state.pages[slug]);
    return;
  }

  els.pageNav.innerHTML = "";
  els.pageContent.setAttribute("aria-busy", "true");
  els.pageContent.innerHTML = `<div class="sk-block" style="height:220px;border-radius:4px"></div>`;

  try {
    const data = await getJSON(API.page(slug));
    if (!state.pages) state.pages = {};
    state.pages[slug] = data;
    if (state.route === "page" && parseRoute().slug === slug) {
      renderContentPage(slug, data);
    }
  } catch (err) {
    els.pageContent.innerHTML = `<div class="state state-error" style="margin-top:0">
      <p class="state-title">Impossible de charger cette page</p>
      <p class="muted">${escapeHtml(err.message)}</p></div>`;
    toast(err.message, "err");
  }
}

function renderContentPage(slug, data) {
  els.pageCrumb.textContent = data.title || PAGE_TITLES[slug];
  els.pageTitle.textContent = data.title || PAGE_TITLES[slug];
  els.pageContent.setAttribute("aria-busy", "false");

  const parts = data.parts || [];
  els.pageNav.innerHTML = parts
    .map(
      (p, i) =>
        `<button type="button" data-part="${escapeHtml(partId(p.key))}" class="${i === 0 ? "is-active" : ""}">${escapeHtml(p.title || p.key)}</button>`
    )
    .join("");

  els.pageContent.innerHTML = parts
    .map((p, i) => {
      const title = p.title || p.key;
      const show = i === 0;
      return `<section class="page-part" id="${escapeHtml(partId(p.key))}" ${show ? "" : 'hidden'}>
        <h2>${escapeHtml(title)}</h2>
        <div class="part-html">${p.html || ""}</div>
      </section>`;
    })
    .join("");

  window.scrollTo(0, 0);
}

/* section switcher (page sub-nav) */
function bindPageNav() {
  els.pageNav.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-part]");
    if (!btn) return;
    els.pageNav.querySelectorAll("button").forEach((b) => b.classList.remove("is-active"));
    btn.classList.add("is-active");
    els.pageContent.querySelectorAll(".page-part").forEach((sec) => {
      sec.hidden = sec.id !== btn.dataset.part;
    });
    window.scrollTo({ top: els.pageContent.offsetTop - 70, behavior: "smooth" });
  });
}

/* ------------------------------ drawer ------------------------------ */

function attachmentRow(att) {
  const ext = (att.ext || "").toLowerCase();
  const icon = ext ? ext.slice(0, 4) : "file";
  return `<li><a href="${escapeHtml(att.url)}" target="_blank" rel="noopener noreferrer">
      <span class="att-icon" data-ext="${escapeHtml(ext)}">${escapeHtml(icon)}</span>
      <span class="att-name">${escapeHtml(att.title)}</span>
      <span class="att-dl">télécharger ↓</span>
    </a></li>`;
}

function renderArticle(data) {
  const label = KIND_LABEL[data.kind] || data.kind;
  els.drawerBadge.textContent = label;
  els.drawerBadge.dataset.kind = data.kind;
  els.drawerDate.textContent = data.date_display || "";
  els.btnOriginal.href = data.original_url;

  const html = data.html && data.html.trim()
    ? data.html
    : `<p class="muted">Pas de contenu textuel pour cet élément.</p>`;

  const atts = data.attachments && data.attachments.length
    ? `<div class="drawer-attach"><h3>Pièces jointes · ${data.attachments.length}</h3>
       <ul class="att-list">${data.attachments.map(attachmentRow).join("")}</ul></div>`
    : "";

  els.drawerBody.innerHTML = `
    <span class="badge" data-kind="${escapeHtml(data.kind)}">${escapeHtml(label)}</span>
    ${data.date_display ? `<time class="muted" style="margin-left:.6rem;font-size:.85rem">${escapeHtml(data.date_display)}</time>` : ""}
    <h1 class="drawer-title">${escapeHtml(data.title)}</h1>
    <div class="article-html">${html}</div>
    ${atts}
  `;
  els.drawerBody.scrollTop = 0;

  // prev_id points to the OLDER item (next in feed order), next_id to the NEWER one
  els.btnPrev.disabled = !data.next_id;
  els.btnNext.disabled = !data.prev_id;
  els.btnPrev.onclick = () => data.next_id && openArticle(data.kind, data.next_id);
  els.btnNext.onclick = () => data.prev_id && openArticle(data.kind, data.prev_id);
}

async function openArticle(kind, id, { fromRoute = true } = {}) {
  if (fromRoute && !state.current) {
    state.routeBeforeArticle = location.hash;
    history.replaceState(null, "", `#${kind}/${id}`);
  }

  els.drawer.classList.add("is-open");
  els.backdrop.classList.remove("hidden");
  requestAnimationFrame(() => els.backdrop.classList.add("is-open"));
  els.drawer.setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";

  els.drawerBody.innerHTML = `
    <div class="sk-block" style="height:22px;width:55%;margin:.5rem 0"></div>
    <div class="sk-block" style="height:16px;width:88%;margin:.5rem 0"></div>
    <div class="sk-block" style="height:180px;margin:1rem 0"></div>
    <div class="sk-block" style="height:16px;width:70%;margin:.5rem 0"></div>`;
  els.btnPrev.disabled = true;
  els.btnNext.disabled = true;

  try {
    const data = await getJSON(API.article(kind, id, false));
    state.current = { kind: data.kind, id: data.id };
    renderArticle(data);
  } catch (err) {
    els.drawerBody.innerHTML = `<div class="state state-error" style="margin-top:0">
      <p class="state-title">Impossible de charger cet élément</p>
      <p class="muted">${escapeHtml(err.message)}</p></div>`;
    toast(err.message, "err");
  }
}

function closeDrawer(silent = false) {
  els.drawer.classList.remove("is-open");
  els.backdrop.classList.remove("is-open");
  els.drawer.setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  setTimeout(() => els.backdrop.classList.add("hidden"), 250);
  state.current = null;
  if (!silent) {
    const back = state.routeBeforeArticle;
    state.routeBeforeArticle = "";
    if (back) {
      history.replaceState(null, "", location.pathname + back);
      navigate();
    } else {
      history.replaceState(null, "", location.pathname);
    }
  }
}

/* ------------------------------ live mode ------------------------------ */

function setLive(on) {
  state.live = on;
  els.btnLive.classList.toggle("is-on", on);
  els.btnLive.setAttribute("aria-pressed", String(on));
  els.btnLive.innerHTML = on
    ? `<span class="live-dot" aria-hidden="true"></span> Live • 60s`
    : `<span class="live-dot" aria-hidden="true"></span> Live`;

  if (state.liveTimer) {
    clearInterval(state.liveTimer);
    state.liveTimer = null;
  }
  if (on) {
    state.liveTimer = setInterval(() => loadFeed({ force: true, silent: true }), LIVE_INTERVAL_MS);
    toast("Mode live activé (60 s)", "ok");
  } else {
    toast("Mode live désactivé");
  }
}

/* ------------------------------ tabs & search ------------------------------ */

function bindTabs() {
  els.tabs.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab");
    if (!btn) return;
    els.tabs.querySelectorAll(".tab").forEach((t) => t.classList.remove("is-active"));
    btn.classList.add("is-active");
    state.kind = btn.dataset.kind;
    renderFeed();
  });
}

const onSearch = debounce(() => {
  state.query = els.search.value;
  if (state.route !== "news") {
    location.hash = "#/actualites";
    setTimeout(renderFeed, 50);
  } else {
    renderFeed();
  }
}, 140);

/* ------------------------------ events ------------------------------ */

function bindCardOpeners(container) {
  container.addEventListener("click", (e) => {
    const card = e.target.closest(".card[data-id]");
    if (card) openArticle(card.dataset.kind, card.dataset.id);
  });
  container.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const card = e.target.closest(".card[data-id]");
    if (card) {
      e.preventDefault();
      openArticle(card.dataset.kind, card.dataset.id);
    }
  });
}

function bindEvents() {
  bindTabs();
  bindPageNav();

  window.addEventListener("hashchange", navigate);

  els.btnRefresh.addEventListener("click", () => loadFeed({ force: true }));
  els.btnLive.addEventListener("click", () => setLive(!state.live));
  els.btnRetry.addEventListener("click", () => loadFeed({ force: true }));
  els.btnReset.addEventListener("click", () => {
    state.query = "";
    els.search.value = "";
    state.kind = "all";
    els.tabs.querySelectorAll(".tab").forEach((t) =>
      t.classList.toggle("is-active", t.dataset.kind === "all")
    );
    renderFeed();
  });

  els.search.addEventListener("input", onSearch);
  els.searchForm.addEventListener("submit", (e) => {
    e.preventDefault();
    state.query = els.search.value;
    if (state.route !== "news") location.hash = "#/actualites";
    else renderFeed();
  });

  bindCardOpeners(els.feed);
  bindCardOpeners(els.homeFeed);

  els.btnClose.addEventListener("click", () => closeDrawer());
  els.backdrop.addEventListener("click", () => closeDrawer());

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.current) closeDrawer();
    if (e.key === "/" && document.activeElement !== els.search) {
      e.preventDefault();
      els.search.focus();
    }
  });
}

/* ------------------------------ boot ------------------------------ */

async function boot() {
  els.footerYear.textContent = new Date().getFullYear();
  bindEvents();
  await navigate();
  if (!state.loaded) loadFeed();
  loadStats();
}

boot();
