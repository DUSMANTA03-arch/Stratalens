import { action, api } from "./api.js";
export const $ = (selector) => document.querySelector(selector);
export function el(tag, text, className) {
  const n = document.createElement(tag);
  if (text != null) n.textContent = String(text);
  if (className) n.className = className;
  return n;
}
export function button(text, fn, className = "secondary") {
  const b = el("button", text, className);
  b.type = "button";
  b.addEventListener("click", action(fn));
  return b;
}
export function field(text, node) {
  const l = el("label", text);
  if (["INPUT", "SELECT", "TEXTAREA"].includes(node.tagName))
    node.setAttribute("aria-label", text);
  l.append(node);
  return l;
}
export function input(name, placeholder = "", type = "text") {
  const i = el("input");
  i.name = name;
  i.type = type;
  i.placeholder = placeholder;
  return i;
}
export function select(name, options, value) {
  const s = el("select");
  s.name = name;
  for (const [v, t] of options) {
    const o = el("option", t);
    o.value = v;
    s.append(o);
  }
  if (value !== undefined) s.value = value;
  return s;
}
export const badge = (text) => el("span", text, `badge ${text}`);
export function heading(title, subtitle, eyebrow = "YOUR WORKSPACE") {
  const h = el("div", null, "page-heading"),
    left = el("div");
  left.append(
    el("div", eyebrow, "eyebrow"),
    el("h1", title),
    el("p", subtitle, "lede"),
  );
  h.append(left);
  return h;
}
export function empty(title, description) {
  const d = el("div", null, "empty");
  d.append(el("h3", title), el("p", description));
  return d;
}
export function table(headers, rows) {
  const wrap = el("div", null, "table-wrap"),
    t = el("table"),
    head = el("thead"),
    hr = el("tr"),
    body = el("tbody");
  headers.forEach((h) => {
    const th = el("th", h);
    th.scope = "col";
    hr.append(th);
  });
  head.append(hr);
  rows.forEach((row) => {
    const tr = el("tr");
    row.forEach((value) => {
      const td = el("td");
      td.append(value instanceof Node ? value : el("span", value ?? "—"));
      tr.append(td);
    });
    body.append(tr);
  });
  t.append(head, body);
  wrap.append(t);
  return wrap;
}
export function safeLink(url, label) {
  try {
    const u = new URL(url);
    if (!["https:", "http:"].includes(u.protocol)) return el("span", label);
    const a = el("a", label);
    a.href = u.href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  } catch {
    return el("span", label);
  }
}
export function formSubmit(form, fn) {
  form.addEventListener(
    "submit",
    action(async (e) => {
      e.preventDefault();
      const b = form.querySelector("[type=submit]");
      if (b) b.disabled = true;
      try {
        await fn(new FormData(form));
      } finally {
        if (b) b.disabled = false;
      }
    }),
  );
}
export function submit(text) {
  const b = el("button", text, "primary");
  b.type = "submit";
  return b;
}
export function checks(items, name, selected = []) {
  const root = el("div", null, "checks");
  for (const item of items) {
    const i = input(name, "", "checkbox");
    i.value = item.id;
    i.checked = selected.includes(item.id);
    const l = el("label");
    l.append(i, document.createTextNode(item.label));
    root.append(l);
  }
  if (!items.length)
    root.append(
      el(
        "p",
        "No indexed documents available. Add reports in Library.",
        "muted",
      ),
    );
  return root;
}
export async function viewDocument(id, page = 1, quote = "") {
  const r = await api(`/api/v2/documents/${id}/view?page=${page}`);
  $("#viewer-title").textContent = `${r.document.data.title} · page ${page}`;
  $("#viewer-evidence").replaceChildren(
    el("div", "SUPPORTING EVIDENCE", "eyebrow"),
    el(
      "blockquote",
      quote || "Inspect the original report and extracted text.",
    ),
    safeLink(r.url + "#page=" + page, "Open original PDF ↗"),
  );
  const d = el("details");
  d.append(
    el("summary", "Extracted page text"),
    el("div", r.page?.text || "No indexed text on this page.", "source-text"),
  );
  $("#viewer-evidence").append(d);
  $("#viewer-frame").src = r.url + "#page=" + page;
  $("#document-viewer").showModal();
}
export function download(content, name, type) {
  const blob =
    content instanceof Blob ? content : new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = el("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
export function section(title) {
  const d = el("div", null, "section-heading");
  d.append(el("h2", title));
  return d;
}
export const number = (value) =>
  value == null
    ? "—"
    : Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
