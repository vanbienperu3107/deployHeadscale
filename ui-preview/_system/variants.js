/*
 * P3 — Nhieu phuong an tren 1 trang.
 * Danh dau moi phuong an: <section data-variant="a" data-variant-label="Bottom sheet">...</section>
 * Script tao thanh chon phuong an (tab A/B/C) + che do "Xem song song".
 * Trang thai nam trong hash: #variant=b  |  #view=compare  -> link gui cho nguoi duyet tro dung phuong an.
 * ?pv-capture=1: khong ve thanh cong cu (dung khi chup baseline P5).
 * API: window.pvVariants.current() -> "a" | "compare"; su kien "pv:variantchange" tren document.
 */
(function () {
  "use strict";
  var sections = Array.prototype.slice.call(document.querySelectorAll("[data-variant]"));
  if (!sections.length) return;
  var capture = new URLSearchParams(location.search).has("pv-capture");
  var ids = sections.map(function (s) { return s.getAttribute("data-variant"); });
  var host = sections[0].parentElement;
  var state = { view: "single", variant: ids[0] };

  function readHash() {
    var h = new URLSearchParams(location.hash.slice(1));
    var v = h.get("variant");
    state.view = h.get("view") === "compare" && !capture ? "compare" : "single";
    state.variant = ids.indexOf(v) >= 0 ? v : ids[0];
  }

  function writeHash() {
    var h = state.view === "compare" ? "view=compare" : "variant=" + state.variant;
    if (location.hash.slice(1) !== h) history.replaceState(null, "", "#" + h);
  }

  var bar, tabs = [], compareBtn;
  function buildBar() {
    bar = document.createElement("nav");
    bar.className = "pv-variants-bar";
    bar.setAttribute("aria-label", "Phương án thiết kế");
    bar.setAttribute("data-pv-chrome", "");
    var list = document.createElement("div");
    list.setAttribute("role", "tablist");
    list.setAttribute("aria-label", "Chọn phương án");
    sections.forEach(function (s, i) {
      var id = ids[i];
      var label = s.getAttribute("data-variant-label") || "";
      if (!s.id) s.id = "pv-variant-" + id;
      s.setAttribute("role", "tabpanel");
      var t = document.createElement("button");
      t.type = "button";
      t.setAttribute("role", "tab");
      t.id = "pv-tab-" + id;
      t.setAttribute("aria-controls", s.id);
      t.dataset.variantTab = id;
      var key = document.createElement("strong");
      key.textContent = id.toUpperCase();
      t.appendChild(key);
      if (label) t.appendChild(document.createTextNode(" " + label));
      t.addEventListener("click", function () { state.view = "single"; state.variant = id; render(true); });
      t.addEventListener("keydown", onKey);
      s.setAttribute("aria-labelledby", t.id);
      tabs.push(t);
      list.appendChild(t);
    });
    compareBtn = document.createElement("button");
    compareBtn.type = "button";
    compareBtn.className = "pv-variants-compare";
    compareBtn.textContent = "Xem song song";
    compareBtn.addEventListener("click", function () {
      state.view = state.view === "compare" ? "single" : "compare";
      render(true);
    });
    bar.appendChild(list);
    bar.appendChild(compareBtn);
    host.parentElement.insertBefore(bar, host);
  }

  function onKey(e) {
    var i = tabs.indexOf(e.currentTarget), n = tabs.length, j = null;
    if (e.key === "ArrowRight") j = (i + 1) % n;
    else if (e.key === "ArrowLeft") j = (i - 1 + n) % n;
    else if (e.key === "Home") j = 0;
    else if (e.key === "End") j = n - 1;
    if (j === null) return;
    e.preventDefault();
    state.view = "single";
    state.variant = ids[j];
    render(true);
    tabs[j].focus();
  }

  function render(push) {
    var compare = state.view === "compare";
    host.classList.toggle("pv-variants-compare-grid", compare);
    sections.forEach(function (s, i) {
      s.hidden = !compare && ids[i] !== state.variant;
    });
    tabs.forEach(function (t, i) {
      var on = !compare && ids[i] === state.variant;
      t.setAttribute("aria-selected", String(on));
      t.tabIndex = on || (compare && i === 0) ? 0 : -1;
    });
    if (compareBtn) {
      compareBtn.setAttribute("aria-pressed", String(compare));
      compareBtn.textContent = compare ? "Xem từng phương án" : "Xem song song";
    }
    if (push) writeHash();
    document.documentElement.setAttribute("data-pv-view", compare ? "compare" : state.variant);
    document.dispatchEvent(new CustomEvent("pv:variantchange", { detail: { view: state.view, variant: state.variant } }));
  }

  var style = document.createElement("style");
  style.textContent = [
    ".pv-variants-bar{position:sticky;top:0;z-index:50;display:flex;gap:8px;align-items:center;justify-content:center;padding:8px 12px;background:var(--md-sys-color-surface-container);border-bottom:1px solid var(--md-sys-color-outline-variant)}",
    ".pv-variants-bar [role=tablist]{display:flex;gap:4px;min-width:0;overflow-x:auto;scrollbar-width:none}",
    "@media (max-width:899px){.pv-variants-bar{justify-content:flex-start}.pv-variants-compare{display:none}}",
    ".pv-variants-bar button{flex:0 0 auto;white-space:nowrap;min-height:36px;padding:0 14px;border-radius:var(--md-sys-shape-corner-full);border:1px solid var(--md-sys-color-outline-variant);background:var(--md-sys-color-surface);color:var(--md-sys-color-on-surface);font:var(--md-sys-typescale-label-large)}",
    ".pv-variants-bar [aria-selected=true],.pv-variants-bar [aria-pressed=true]{background:var(--md-sys-color-secondary-container);color:var(--md-sys-color-on-secondary-container);border-color:transparent}",
    ".pv-variants-compare-grid{display:grid!important;grid-template-columns:repeat(auto-fit,minmax(min(100%,var(--pv-device-width)),1fr));gap:24px;align-items:start}",
    ".pv-variants-compare-grid>[data-variant]::before{content:attr(data-variant-caption);display:block;margin:0 0 8px;text-align:center;font:var(--md-sys-typescale-title-small);color:var(--md-sys-color-on-surface-variant)}"
  ].join("");
  document.head.appendChild(style);

  sections.forEach(function (s) {
    var id = s.getAttribute("data-variant");
    var label = s.getAttribute("data-variant-label");
    s.setAttribute("data-variant-caption", "Phương án " + id.toUpperCase() + (label ? ": " + label : ""));
  });

  if (!capture) buildBar();
  readHash();
  render(false);
  window.addEventListener("hashchange", function () { readHash(); render(false); });

  window.pvVariants = {
    ids: ids.slice(),
    current: function () { return state.view === "compare" ? "compare" : state.variant; },
    select: function (id) { if (ids.indexOf(id) >= 0) { state.view = "single"; state.variant = id; render(true); } }
  };
})();
