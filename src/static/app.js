"use strict";
// Бүх өгөгдлийг textContent-оор харуулна (XSS-ээс хамгаална), innerHTML ашиглахгүй.
let csrf = null;
let role = null;
const $ = (id) => document.getElementById(id);

function show(msg) { $("message").textContent = msg || ""; }

function el(tag, text, cls) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (cls) node.className = cls;
  return node;
}

function date(value) {
  if (!value) return "Хугацаа баталгаажаагүй";
  return new Date(value).toLocaleString("mn-MN", { timeZone: "Asia/Ulaanbaatar" });
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json" };
  if (csrf) headers["X-CSRF-Token"] = csrf;
  const res = await fetch(path, { credentials: "same-origin", ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Алдаа гарлаа.");
  return data;
}

async function refresh() {
  show("");
  const data = await api("/api/orders");
  $("list-title").textContent = data.role === "cleaner" ? "Ажлын жагсаалт" : "Миний захиалгууд";
  const list = $("orders");
  list.replaceChildren();
  if (!data.orders.length) list.append(el("li", "Захиалга байхгүй байна."));
  for (const order of data.orders) {
    const li = el("li");
    li.append(el("strong", order.number), el("div", order.status_label), el("small", "Шинэчилсэн: " + date(order.updated_at)));
    li.addEventListener("click", () => detail(order.id).catch((e) => show(e.message)));
    list.append(li);
  }
}

async function detail(id) {
  const order = await api("/api/orders/" + id);
  const box = $("detail");
  box.replaceChildren();
  box.append(el("h3", order.number), el("p", "Төлөв: " + order.status_label));
  const bar = el("div", undefined, "progress");
  const fill = el("span");
  fill.style.width = order.progress + "%";
  bar.append(fill);
  box.append(bar, el("p", "Бэлэн болох хугацаа: " + date(order.ready_at)),
    el("p", "Сүүлд шинэчилсэн: " + date(order.updated_at)), el("h4", "Хувцас"));
  const items = el("ul");
  for (const item of order.items) items.append(el("li", item.garment + " × " + item.quantity));
  box.append(items, el("h4", "Түүх"));
  const hist = el("ol");
  for (const h of order.history) hist.append(el("li", date(h.changed_at) + " — " + h.status + (h.reason ? " (" + h.reason + ")" : "")));
  box.append(hist);
  if (role === "cleaner") box.append(statusForm(order));
  box.hidden = false;
}

function statusForm(order) {
  const form = el("form");
  const select = el("select");
  for (const s of ["cleaning", "quality_check", "ready"]) select.append(new Option(s, s));
  const reason = el("textarea");
  reason.placeholder = "Шалтгаан (чанараас буцаахад заавал)";
  reason.maxLength = 500;
  form.append(select, reason, el("button", "Төлөв хадгалах"));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/orders/" + order.id + "/status", { method: "POST", body: JSON.stringify({ status: select.value, reason: reason.value }) });
      await refresh();
      await detail(order.id);
    } catch (err) { show(err.message); }
  });
  return form;
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const data = await api("/api/login", { method: "POST", body: JSON.stringify({ username: $("username").value.trim(), password: $("password").value }) });
    csrf = data.csrf; role = data.role;
    $("login-view").hidden = true; $("app-view").hidden = false; $("logout").hidden = false;
    await refresh();
  } catch (err) { show(err.message); }
});

$("refresh").addEventListener("click", () => refresh().catch((e) => show(e.message)));
$("logout").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST", body: "{}" }); } catch (_) { /* session аль хэдийн дууссан */ }
  location.reload();
});
