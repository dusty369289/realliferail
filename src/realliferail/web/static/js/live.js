// The train page: move the marker every second, and ask the server for fresh data when it says to.
"use strict";

(function () {
  const page = document.querySelector("[data-train]");
  if (!page) return;
  const region = page.querySelector("[data-live-region]");
  const params = new URLSearchParams({ at: page.dataset.at || "", to: page.dataset.to || "" });
  const liveUrl = `/train/${encodeURIComponent(page.dataset.uid)}/live?${params}`;
  const passes = page.querySelector("[data-toggle-passes]");
  let jumped = false, timer = null, failures = 0;

  const store = window.rlrStore || { get: (_, f) => f, set() {} };
  passes.checked = store.get("rlr.passes", true);

  function rowCentre(row, wrap) {
    if (!row) return null;
    const r = row.getBoundingClientRect(), w = wrap.getBoundingClientRect();
    return r.top - w.top + r.height / 2;
  }

  function place() {
    const live = region.querySelector(".live");
    if (!live) return;
    const wrap = live.querySelector(".route-wrap");
    const route = live.querySelector(".route");
    const marker = live.querySelector("[data-train-marker]");
    route.classList.toggle("hide-passes", !passes.checked);
    let done = wrap.querySelector(".route__done");
    if (!done) { done = document.createElement("div"); done.className = "route__done"; wrap.prepend(done); }

    const d = live.dataset;
    const rows = route.querySelectorAll(".route__pt");
    const from = d.from === "" ? null : rows[Number(d.from)];
    const to = d.to === "" ? null : rows[Number(d.to)];
    const state = d.state;
    let y = null, waiting = false;

    if (state === "running" || state === "overdue") {
      const a = rowCentre(from, wrap), b = rowCentre(to, wrap);
      let f = Number(d.fraction) || 0;
      const since = Number(d.since), expected = Number(d.expected), hold = Number(d.hold) || 0.95;
      if (since && expected && expected > since) f = Math.min(Math.max((Date.now() - since) / (expected - since), 0), hold);
      if (state === "overdue") { f = hold; waiting = true; }
      if (a !== null && b !== null) y = a + (b - a) * f;
    } else if (state === "at-station" || state === "at-origin") {
      y = rowCentre(from || to, wrap); waiting = true;
    } else if (state === "not-started") {
      y = rowCentre(to, wrap); waiting = true;
    } else if (state === "arrived") {
      y = rowCentre(from, wrap);
    }
    if (y === null) { marker.hidden = true; done.style.height = "0"; return; }
    marker.hidden = false;
    marker.style.top = `${y}px`;
    marker.classList.toggle("is-waiting", waiting);
    done.style.height = `${Math.max(y, 0)}px`;
    if (!jumped) { jumped = true; jump(false); }
  }

  function jump(smooth) {
    const marker = region.querySelector("[data-train-marker]");
    if (!marker || marker.hidden) return;
    const top = marker.getBoundingClientRect().top + window.scrollY - window.innerHeight * 0.4;
    window.scrollTo({ top: Math.max(top, 0), behavior: smooth ? "smooth" : "auto" });
  }

  function age() {
    const live = region.querySelector(".live");
    const el = region.querySelector("[data-age]");
    if (!live || !el) return;
    const s = Math.max(0, Math.round((Date.now() - Number(live.dataset.fetched)) / 1000));
    el.textContent = s < 60 ? `Updated ${s} s ago` : `Updated ${Math.floor(s / 60)} min ago`;
  }

  async function refresh() {
    if (document.visibilityState !== "visible") { schedule(15); return; }
    try {
      const r = await fetch(liveUrl, { headers: { Accept: "text/html" } });
      const html = await r.text();
      if (!r.ok) throw new Error(html);
      const tpl = document.createElement("template");
      tpl.innerHTML = html;
      const fresh = tpl.content.querySelector(".live");
      if (fresh) region.replaceChildren(fresh);
      failures = 0;
      place();
    } catch {
      failures += 1;
      const el = region.querySelector("[data-age]");
      if (el) el.textContent = "Couldn't update. Trying again soon.";
    }
    const live = region.querySelector(".live");
    const next = live ? Number(live.dataset.refresh) || 30 : 30;
    schedule(Math.min(next * (1 + failures), 300));
  }

  function schedule(secs) { clearTimeout(timer); timer = setTimeout(refresh, secs * 1000); }

  passes.addEventListener("change", () => { store.set("rlr.passes", passes.checked); place(); });
  page.querySelector("[data-jump]").addEventListener("click", () => jump(true));
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") refresh(); });
  window.addEventListener("resize", place);

  place();
  setInterval(() => { place(); age(); }, 1000);
  const first = region.querySelector(".live");
  schedule(first ? Number(first.dataset.refresh) || 30 : 30);
})();
