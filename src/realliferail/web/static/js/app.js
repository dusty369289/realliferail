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

// ---- journeys: saved on this phone only ----
function journeys() {
  const board = document.querySelector("[data-board]");
  const save = document.querySelector("[data-save-journey]");
  let list = store.get("rlr.journeys", []);
  if (board && save) {
    const j = { from: board.dataset.crs, fromName: board.dataset.station, to: board.dataset.toCrs, toName: board.dataset.toName };
    const note = document.querySelector("[data-save-note]");
    const has = () => list.some((x) => x.from === j.from && x.to === j.to);
    if (has()) { save.textContent = "Saved. Remove this journey"; }
    save.addEventListener("click", () => {
      if (has()) {
        list = list.filter((x) => !(x.from === j.from && x.to === j.to));
        save.textContent = "Save this journey"; note.textContent = "Removed.";
      } else {
        list = [j, ...list].slice(0, 8);
        save.textContent = "Saved. Remove this journey"; note.textContent = "It's on the home screen now.";
      }
      store.set("rlr.journeys", list);
    });
  }
  const box = document.querySelector("[data-journeys]");
  if (!box || list.length === 0) return;
  const link = (from, to, label) => {
    const a = document.createElement("a");
    a.href = `/board?station=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;
    a.textContent = label;
    return a;
  };
  box.querySelector("ul").replaceChildren(...list.map((j) => {
    const li = document.createElement("li");
    li.className = "journeys__item";
    const there = link(j.from, j.to, `${j.fromName} → ${j.toName}`);
    there.className = "journeys__go";
    const back = link(j.to, j.from, "Return");
    back.className = "journeys__back";
    back.setAttribute("aria-label", `Return: ${j.toName} to ${j.fromName}`);
    li.append(there, back);
    return li;
  }));
  box.hidden = false;
}

// ---- the train you were last following, so reopening the app takes you back to it ----
function tracking() {
  const train = document.querySelector("[data-train]");
  if (train) {
    const ends = Number(train.dataset.ends) || 0;
    store.set("rlr.tracking", {
      href: location.pathname + location.search, title: train.dataset.title, ends, seen: Date.now(),
    });
    return;
  }
  const box = document.querySelector("[data-tracking]");
  const t = store.get("rlr.tracking", null);
  if (!box || !t) return;
  // offer it until half an hour after the train is due to finish (or 3 hours after it was opened)
  const until = t.ends ? t.ends + 30 * 60e3 : t.seen + 3 * 3600e3;
  if (Date.now() > until) return;
  const a = box.querySelector("a");
  a.href = t.href;
  box.querySelector(".tracking__title").textContent = t.title;
  box.querySelector(".tracking__sub").textContent = "Tap to see where it is now";
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
  journeys();
  tracking();
  liveBoard();
});
