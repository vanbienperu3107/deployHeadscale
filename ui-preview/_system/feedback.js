/*
 * P4 — Gop y truc tiep tren prototype (chi chay phia client, khong gui du lieu di dau).
 * Bat "Góp ý" -> bam vao phan tu bat ky -> nhap ghi chu -> "Sao chép Markdown" de dan vao chat voi agent.
 * Ghi chu luu localStorage theo duong dan trang, nen tai lai trang khong mat.
 * Markdown gom: prototype/phien ban (meta pv-prototype), URL, phuong an dang xem, selector CSS, text phan tu, ghi chu.
 * Phan tu co data-pv-id se duoc uu tien lam selector (on dinh hon nth-of-type) -> nen dat data-pv-id cho phan tu chinh.
 * ?pv-capture=1: tat hoan toan (dung khi chup baseline).
 */
(function () {
  "use strict";
  if (new URLSearchParams(location.search).has("pv-capture")) return;

  var meta = document.querySelector('meta[name="pv-prototype"]');
  var protoId = meta ? meta.content : location.pathname;
  var storeKey = "pv-feedback:" + location.pathname;
  var notes = load();
  var active = false, hoverEl = null;

  function load() {
    try { return JSON.parse(localStorage.getItem(storeKey) || "[]"); } catch (e) { return []; }
  }
  function save() {
    try { localStorage.setItem(storeKey, JSON.stringify(notes)); } catch (e) { /* private mode: van dung trong phien */ }
  }

  function cssEscape(s) { return window.CSS && CSS.escape ? CSS.escape(s) : s.replace(/[^\w-]/g, "\\$&"); }

  function selectorFor(el) {
    var parts = [];
    while (el && el.nodeType === 1 && el !== document.body) {
      if (el.hasAttribute("data-pv-id")) { parts.unshift('[data-pv-id="' + el.getAttribute("data-pv-id") + '"]'); break; }
      if (el.id) { parts.unshift("#" + cssEscape(el.id)); break; }
      var tag = el.tagName.toLowerCase(), sib = el, n = 1;
      while ((sib = sib.previousElementSibling)) if (sib.tagName === el.tagName) n++;
      var same = el.parentElement ? el.parentElement.querySelectorAll(":scope > " + tag).length : 1;
      parts.unshift(same > 1 ? tag + ":nth-of-type(" + n + ")" : tag);
      el = el.parentElement;
    }
    return parts.join(" > ");
  }

  function variantOf(el) {
    var v = el.closest("[data-variant]");
    return v ? v.getAttribute("data-variant").toUpperCase() : "";
  }

  function textOf(el) {
    var t = (el.getAttribute("aria-label") || el.textContent || "").replace(/\s+/g, " ").trim();
    return t.length > 60 ? t.slice(0, 57) + "..." : t;
  }

  function isChrome(el) { return !!el.closest("[data-pv-chrome]"); }

  // ---- UI ----
  var root = document.createElement("div");
  root.setAttribute("data-pv-chrome", "");
  root.className = "pv-fb";
  root.innerHTML =
    '<button type="button" class="pv-fb-toggle" aria-pressed="false">Góp ý <span class="pv-fb-count" aria-label="số ghi chú">0</span></button>' +
    '<section class="pv-fb-panel" hidden aria-label="Ghi chú góp ý">' +
    '<p class="pv-fb-hint">Bấm vào phần tử cần góp ý. Esc để tắt chế độ góp ý.</p>' +
    '<ol class="pv-fb-list"></ol>' +
    '<div class="pv-fb-actions"><button type="button" data-act="copy">Sao chép Markdown</button><button type="button" data-act="clear">Xóa hết</button></div>' +
    '<p class="pv-fb-status" role="status" aria-live="polite"></p>' +
    '<textarea class="pv-fb-out" readonly hidden aria-label="Markdown góp ý"></textarea>' +
    '</section>' +
    '<form class="pv-fb-form" hidden><label>Ghi chú cho <code class="pv-fb-target"></code><textarea name="note" rows="3" required></textarea></label>' +
    '<div class="pv-fb-actions"><button type="submit">Lưu ghi chú</button><button type="button" data-act="cancel">Hủy</button></div></form>' +
    '<div class="pv-fb-outline" hidden></div>';
  var toggle = root.querySelector(".pv-fb-toggle"),
      panel = root.querySelector(".pv-fb-panel"),
      list = root.querySelector(".pv-fb-list"),
      count = root.querySelector(".pv-fb-count"),
      status = root.querySelector(".pv-fb-status"),
      out = root.querySelector(".pv-fb-out"),
      form = root.querySelector(".pv-fb-form"),
      formTarget = root.querySelector(".pv-fb-target"),
      outline = root.querySelector(".pv-fb-outline");
  var pending = null;

  var style = document.createElement("style");
  style.textContent = [
    ".pv-fb{position:fixed;right:16px;bottom:16px;z-index:2147483000;font:var(--md-sys-typescale-body-medium,14px/20px system-ui);color:var(--md-sys-color-on-surface,#171d1a)}",
    ".pv-fb button{min-height:36px;padding:0 14px;border-radius:999px;border:1px solid var(--md-sys-color-outline,#707974);background:var(--md-sys-color-surface,#fff);cursor:pointer}",
    ".pv-fb-toggle{display:block;margin-left:auto;background:var(--md-sys-color-tertiary-container,#c2e8fd)!important;color:var(--md-sys-color-on-tertiary-container,#001f2a);border-color:transparent!important;font-weight:500}",
    ".pv-fb-toggle[aria-pressed=true]{background:var(--md-sys-color-tertiary,#3f6375)!important;color:var(--md-sys-color-on-tertiary,#fff)}",
    ".pv-fb-count{display:inline-block;min-width:20px;margin-left:4px;padding:0 6px;border-radius:999px;background:var(--md-sys-color-surface,#fff);color:var(--md-sys-color-on-surface,#000);font-size:12px}",
    ".pv-fb-panel,.pv-fb-form{width:min(340px,calc(100vw - 32px));margin-bottom:8px;padding:12px 14px;border-radius:16px;background:var(--md-sys-color-surface-container-high,#e4eae4);box-shadow:0 6px 24px color-mix(in srgb,var(--md-sys-color-shadow,#000) 22%,transparent)}",
    ".pv-fb-panel[hidden],.pv-fb-form[hidden],.pv-fb-outline[hidden],.pv-fb-out[hidden]{display:none}",
    ".pv-fb-hint{margin:0 0 8px;color:var(--md-sys-color-on-surface-variant,#404944)}",
    ".pv-fb-list{max-height:200px;overflow:auto;margin:0 0 8px;padding-left:20px}",
    ".pv-fb-list li{margin:4px 0}.pv-fb-list code,.pv-fb-form code{font-size:12px;word-break:break-all}",
    ".pv-fb-actions{display:flex;gap:6px;flex-wrap:wrap}",
    ".pv-fb-form label{display:block}.pv-fb-form textarea,.pv-fb-out{display:block;width:100%;margin:6px 0 8px;padding:8px;border-radius:8px;border:1px solid var(--md-sys-color-outline,#707974);font:inherit}",
    ".pv-fb-out{min-height:120px;font:12px/1.4 ui-monospace,monospace}",
    ".pv-fb-status{margin:6px 0 0;min-height:1em}",
    ".pv-fb-outline{position:fixed;pointer-events:none;border:2px dashed var(--md-sys-color-tertiary,#3f6375);border-radius:6px;background:color-mix(in srgb,var(--md-sys-color-tertiary,#3f6375) 10%,transparent)}",
    "html.pv-fb-on body *:not([data-pv-chrome]):not([data-pv-chrome] *){cursor:crosshair!important}"
  ].join("");
  document.head.appendChild(style);
  document.body.appendChild(root);

  function renderList() {
    count.textContent = String(notes.length);
    list.innerHTML = "";
    notes.forEach(function (n, i) {
      var li = document.createElement("li");
      var code = document.createElement("code");
      code.textContent = (n.variant ? "[" + n.variant + "] " : "") + n.selector;
      li.appendChild(code);
      li.appendChild(document.createTextNode(" — " + n.note + " "));
      var del = document.createElement("button");
      del.type = "button";
      del.textContent = "Xóa";
      del.setAttribute("aria-label", "Xóa ghi chú " + (i + 1));
      del.addEventListener("click", function () { notes.splice(i, 1); save(); renderList(); });
      li.appendChild(del);
      list.appendChild(li);
    });
  }

  function setActive(on) {
    active = on;
    toggle.setAttribute("aria-pressed", String(on));
    panel.hidden = !on;
    document.documentElement.classList.toggle("pv-fb-on", on);
    if (!on) { outline.hidden = true; form.hidden = true; pending = null; }
  }

  function markdown() {
    var v = window.pvVariants ? window.pvVariants.current() : "";
    var lines = [
      "## Góp ý prototype `" + protoId + "`",
      "- URL: " + location.href,
      v ? "- Phương án đang xem: " + v.toUpperCase() : null,
      "- Viewport: " + innerWidth + "x" + innerHeight,
      ""
    ].filter(function (x) { return x !== null; });
    notes.forEach(function (n, i) {
      lines.push((i + 1) + ". " + (n.variant ? "**[" + n.variant + "]** " : "") + "`" + n.selector + "`" + (n.text ? " (\"" + n.text + "\")" : ""));
      lines.push("   - " + n.note.replace(/\n/g, "\n     "));
    });
    return lines.join("\n");
  }

  function copy() {
    if (!notes.length) { status.textContent = "Chưa có ghi chú nào để sao chép."; return; }
    var md = markdown();
    out.value = md;
    var done = function () { status.textContent = "Đã sao chép " + notes.length + " ghi chú. Dán vào chat để gửi."; };
    var fallback = function () {
      out.hidden = false; out.focus(); out.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      status.textContent = ok ? "Đã sao chép " + notes.length + " ghi chú. Dán vào chat để gửi." : "Trình duyệt chặn clipboard: hãy chọn và sao chép nội dung bên dưới.";
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(md).then(done, fallback);
    else fallback();
  }

  toggle.addEventListener("click", function () { setActive(!active); });
  root.addEventListener("click", function (e) {
    var act = e.target.getAttribute && e.target.getAttribute("data-act");
    if (act === "copy") copy();
    if (act === "clear") { notes = []; save(); renderList(); out.hidden = true; status.textContent = "Đã xóa hết ghi chú."; }
    if (act === "cancel") { form.hidden = true; pending = null; }
  });

  document.addEventListener("mouseover", function (e) {
    if (!active || isChrome(e.target)) { outline.hidden = true; return; }
    hoverEl = e.target;
    var r = hoverEl.getBoundingClientRect();
    outline.hidden = false;
    outline.style.cssText = "left:" + r.left + "px;top:" + r.top + "px;width:" + r.width + "px;height:" + r.height + "px";
  }, true);

  document.addEventListener("click", function (e) {
    if (!active || isChrome(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    pending = { selector: selectorFor(e.target), text: textOf(e.target), variant: variantOf(e.target) };
    formTarget.textContent = (pending.variant ? "[" + pending.variant + "] " : "") + pending.selector;
    form.hidden = false;
    form.note.value = "";
    form.note.focus();
  }, true);

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    var note = form.note.value.trim();
    if (!pending || !note) return;
    pending.note = note;
    pending.at = new Date().toISOString();
    notes.push(pending);
    pending = null;
    save();
    renderList();
    form.hidden = true;
    status.textContent = "Đã lưu ghi chú " + notes.length + ".";
  });

  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && active) setActive(false); });

  renderList();
  window.pvFeedback = { markdown: markdown, notes: function () { return notes.slice(); } };
})();
