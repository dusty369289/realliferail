// Every page: service worker, station suggestions, recent stations, self-refreshing "now" boards.
"use strict";

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode */ } },
};
window.rlrStore = store;

if ("serviceWorker" in navigator && window.isSecureContext) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

function suggest(box) {
  const input = box.querySelector("input");
  const list = box.querySelector(".suggest__list");
  let items = [], active = -1, timer = null, seq = 0;

  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
  const choose = (s) => { input.value = `${s.name} (${s.crs})`; close(); };
  const render = () => {
    list.replaceChildren(...items.map((s, i) => {
      const li = document.createElement("li");
      li.id = `${list.id}-${i}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === active));
      const name = document.createElement("span"); name.textContent = s.name;
      const crs = document.createElement("span"); crs.className = "suggest__crs"; crs.textContent = s.crs;
      li.append(name, crs);
      li.addEventListener("mousedown", (e) => { e.preventDefault(); choose(s); });
      return li;
    }));
    list.hidden = items.length === 0;
    input.setAttribute("aria-expanded", String(items.length > 0));
    if (active >= 0) input.setAttribute("aria-activedescendant", `${list.id}-${active}`);
    else input.removeAttribute("aria-activedescendant");
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    if (q.length < 2) { items = []; render(); return; }
    timer = setTimeout(async () => {
      const mine = ++seq;
      try {
        const r = await fetch(`/api/stations?q=${encodeURIComponent(q)}`);
        if (mine !== seq) return;  // a newer keystroke won
        items = r.ok ? await r.json() : [];
      } catch { items = []; }
      active = -1; render();
    }, 120);
  });
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { active = Math.min(active + 1, items.length - 1); render(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
    else if (e.key === "Enter" && active >= 0) { choose(items[active]); e.preventDefault(); }
    else if (e.key === "Escape") { close(); }
  });
  input.addEventListener("blur", () => setTimeout(close, 100));
}

function recent() {
  const box = document.querySelector("[data-recent]");
  const board = document.querySelector("[data-board]");
  let list = store.get("rlr.recent", []);
  if (board && board.dataset.crs) {
    const entry = { name: board.dataset.station, crs: board.dataset.crs };
    list = [entry, ...list.filter((s) => s.crs !== entry.crs)].slice(0, 6);
    store.set("rlr.recent", list);
  }
  if (!box || list.length === 0) return;
  const ul = box.querySelector("ul");
  ul.replaceChildren(...list.map((s) => {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = `/board?station=${encodeURIComponent(s.crs)}`;
    a.textContent = s.name;
    li.append(a);
    return li;
  }));
  box.hidden = false;
}

function liveBoard() {
  const board = document.querySelector("[data-live-board]");
  if (!board) return;
  const secs = Number(board.dataset.liveBoard) || 60;
  setInterval(() => { if (document.visibilityState === "visible") location.reload(); }, secs * 1000);
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-suggest]").forEach(suggest);
  recent();
  liveBoard();
});
