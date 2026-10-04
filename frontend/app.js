"use strict";

/* Vanilla JS client for the Expense Insights API.
 * All user-supplied text is rendered with textContent (never innerHTML) to prevent XSS. */

const PAGE_SIZE = 20;
const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR" });
const $ = (selector) => document.querySelector(selector);

const state = { page: 1, totalPages: 1, editingId: null };

class ApiError extends Error {
  constructor(message, details = {}, status = 0) {
    super(message);
    this.details = details;
    this.status = status;
  }
}

async function api(path, options = {}) {
  const init = { method: options.method || "GET", headers: {} };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }
  let response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError("Cannot reach the server. Check that the backend is running.");
  }
  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const error = data && data.error ? data.error : {};
    throw new ApiError(error.message || `Request failed (${response.status}).`, error.details || {}, response.status);
  }
  return data;
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  Object.assign(node, props);
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function todayISO() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function formatDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/* ---------- Reference data ---------- */

async function loadMeta() {
  const meta = await api("/api/meta");
  const fill = (select, values, keepFirst) => {
    if (!keepFirst) select.replaceChildren();
    for (const value of values) select.append(el("option", { value, textContent: value }));
  };
  fill($("#expense-form [name=category]"), meta.categories, false);
  fill($("#expense-form [name=payment_method]"), meta.payment_methods, false);
  fill($("#filters [name=category]"), meta.categories, true);
  fill($("#filters [name=payment_method]"), meta.payment_methods, true);
}

/* ---------- Dashboard ---------- */

async function loadStats() {
  const stats = await api("/api/expenses/stats");
  $("#stat-total").textContent = inr.format(stats.total_amount);
  $("#stat-count").textContent = stats.expense_count.toLocaleString("en-IN");

  const [year, month] = stats.current_month.month.split("-").map(Number);
  $("#stat-month-label").textContent =
    new Date(year, month - 1, 1).toLocaleDateString("en-IN", { month: "long", year: "numeric" });
  $("#stat-month").textContent = inr.format(stats.current_month.total_amount);

  const topCategory = stats.highest_category;
  $("#stat-top-category").replaceChildren(
    topCategory
      ? el("span", {}, topCategory.category, el("small", { textContent: `${inr.format(topCategory.total_amount)} · ${topCategory.percentage}%` }))
      : "–"
  );
  const topExpense = stats.highest_expense;
  $("#stat-top-expense").replaceChildren(
    topExpense
      ? el("span", {}, inr.format(topExpense.amount), el("small", { textContent: topExpense.description }))
      : "–"
  );

  const chart = $("#category-chart");
  const max = Math.max(0, ...stats.by_category.map((c) => c.total_amount));
  chart.replaceChildren(
    ...stats.by_category.map((c) => {
      const fill = el("div", { className: "bar-fill" });
      fill.style.width = `${max ? (c.total_amount / max) * 100 : 0}%`;
      const track = el("div", { className: "bar-track" }, fill);
      track.setAttribute("role", "img");
      track.setAttribute("aria-label", `${c.category}: ${inr.format(c.total_amount)}, ${c.percentage}% of total`);
      return el("li", {},
        el("span", { textContent: c.category }),
        track,
        el("span", { className: "bar-value" }, inr.format(c.total_amount), el("span", { textContent: `${c.percentage}%` }))
      );
    })
  );
  $("#chart-empty").hidden = stats.by_category.length > 0;
}

/* ---------- Expense list ---------- */

function currentFilters() {
  const form = new FormData($("#filters"));
  const params = new URLSearchParams();
  for (const key of ["q", "category", "payment_method", "start_date", "end_date"]) {
    const value = (form.get(key) || "").trim();
    if (value) params.set(key, value);
  }
  const [sort, order] = (form.get("sort") || "date:desc").split(":");
  params.set("sort", sort);
  params.set("order", order);
  params.set("page", String(state.page));
  params.set("page_size", String(PAGE_SIZE));
  return params;
}

async function loadExpenses() {
  const banner = $("#list-error");
  try {
    const data = await api(`/api/expenses?${currentFilters()}`);
    banner.hidden = true;
    state.totalPages = data.pagination.total_pages;
    if (state.page > state.totalPages) {
      state.page = state.totalPages;
      return loadExpenses();
    }
    renderRows(data.items);
    const total = data.pagination.total_items;
    $("#list-summary").textContent =
      `${total.toLocaleString("en-IN")} ${total === 1 ? "expense" : "expenses"} · ${inr.format(data.summary.total_amount)}`;
    $("#page-info").textContent = `Page ${data.pagination.page} of ${data.pagination.total_pages}`;
    $("#prev-page").disabled = state.page <= 1;
    $("#next-page").disabled = state.page >= state.totalPages;
    $("#list-empty").hidden = data.items.length > 0;
  } catch (error) {
    const fields = Object.entries(error.details || {}).map(([k, v]) => `${k} ${v}`).join("; ");
    banner.textContent = fields ? `${error.message} ${fields}` : error.message;
    banner.hidden = false;
  }
}

function renderRows(items) {
  $("#expense-rows").replaceChildren(
    ...items.map((expense) => {
      const edit = el("button", { type: "button", className: "link", textContent: "Edit" });
      edit.setAttribute("aria-label", `Edit ${expense.description}`);
      edit.addEventListener("click", () => startEdit(expense));
      const remove = el("button", { type: "button", className: "link danger", textContent: "Delete" });
      remove.setAttribute("aria-label", `Delete ${expense.description}`);
      remove.addEventListener("click", () => deleteExpense(expense));
      const row = el("tr", {},
        el("td", { textContent: formatDate(expense.date) }),
        el("td", { textContent: expense.description }),
        el("td", { textContent: expense.category }),
        el("td", { textContent: expense.payment_method }),
        el("td", { className: "num", textContent: inr.format(expense.amount) }),
        el("td", { className: "row-actions" }, edit, remove)
      );
      if (expense.id === state.editingId) row.classList.add("editing");
      return row;
    })
  );
}

/* ---------- Add / edit / delete ---------- */

function clearFieldErrors() {
  for (const node of document.querySelectorAll("#expense-form .field-error")) node.textContent = "";
  for (const node of document.querySelectorAll("#expense-form [aria-invalid]")) node.removeAttribute("aria-invalid");
}

function showFieldErrors(details) {
  let first = null;
  for (const [field, message] of Object.entries(details)) {
    const slot = document.querySelector(`#expense-form [data-error-for="${field}"]`);
    const input = document.querySelector(`#expense-form [name="${field}"]`);
    if (slot) slot.textContent = `${field.replace("_", " ")} ${message}`.replace(/^./, (c) => c.toUpperCase());
    if (input) {
      input.setAttribute("aria-invalid", "true");
      first = first || input;
    }
  }
  if (first) first.focus();
}

function resetForm() {
  const form = $("#expense-form");
  form.reset();
  form.elements.date.value = todayISO();
  state.editingId = null;
  $("#form-heading").textContent = "Add an expense";
  $("#submit-button").textContent = "Add expense";
  $("#cancel-edit").hidden = true;
  clearFieldErrors();
}

function startEdit(expense) {
  const form = $("#expense-form");
  state.editingId = expense.id;
  for (const field of ["date", "category", "description", "amount", "payment_method"]) {
    form.elements[field].value = expense[field];
  }
  $("#form-heading").textContent = `Edit expense #${expense.id}`;
  $("#submit-button").textContent = "Save changes";
  $("#cancel-edit").hidden = false;
  $("#form-status").textContent = "";
  clearFieldErrors();
  form.scrollIntoView({ behavior: "smooth", block: "start" });
  form.elements.description.focus({ preventScroll: true });
  loadExpenses();
}

async function submitExpense(event) {
  event.preventDefault();
  clearFieldErrors();
  const form = event.currentTarget;
  const body = Object.fromEntries(new FormData(form).entries());
  const status = $("#form-status");
  const button = $("#submit-button");
  const editing = state.editingId !== null;
  button.disabled = true;
  try {
    if (editing) {
      await api(`/api/expenses/${state.editingId}`, { method: "PUT", body });
      status.textContent = "Changes saved.";
    } else {
      await api("/api/expenses", { method: "POST", body });
      status.textContent = "Expense added.";
    }
    resetForm();
    await refresh();
  } catch (error) {
    if (error.status === 404 && editing) {
      status.textContent = "This expense no longer exists. It may have been deleted.";
      resetForm();
      await refresh();
    } else {
      status.textContent = error.message;
      showFieldErrors(error.details);
    }
  } finally {
    button.disabled = false;
  }
}

async function deleteExpense(expense) {
  const ok = window.confirm(`Delete "${expense.description}" (${inr.format(expense.amount)})? This cannot be undone.`);
  if (!ok) return;
  try {
    await api(`/api/expenses/${expense.id}`, { method: "DELETE" });
    if (state.editingId === expense.id) resetForm();
    $("#form-status").textContent = "Expense deleted.";
  } catch (error) {
    $("#form-status").textContent = error.status === 404 ? "That expense was already deleted." : error.message;
  }
  await refresh();
}

async function refresh() {
  await Promise.all([loadStats().catch(showGlobalError), loadExpenses()]);
}

function showGlobalError(error) {
  const banner = $("#list-error");
  banner.textContent = error.message;
  banner.hidden = false;
}

/* ---------- Assistant ---------- */

function addMessage(kind, text, extra) {
  const log = $("#chat-log");
  const message = el("div", { className: `message ${kind}`, textContent: text });
  if (extra) message.append(extra);
  log.append(message);
  log.scrollTop = log.scrollHeight;
  return message;
}

function describeToolCalls(result) {
  const details = el("details");
  const via = result.provider === "anthropic" ? `Claude (${result.model})` : "built-in rules";
  details.append(el("summary", { textContent: `How this was answered: ${via}` }));
  if (result.fallback_reason) {
    details.append(el("p", { textContent: `The AI model was unavailable (${result.fallback_reason}), so built-in rules answered.` }));
  }
  if (result.tool_calls.length === 0) {
    details.append(el("p", { textContent: "No expense data was needed." }));
  }
  for (const call of result.tool_calls) {
    details.append(el("p", {}, el("code", { textContent: `${call.tool}(${JSON.stringify(call.input)})${call.ok ? "" : " – failed"}` })));
  }
  return details;
}

async function ask(question) {
  question = question.trim();
  if (!question) return;
  const input = $("#question");
  const button = $("#assistant-form button");
  addMessage("user", question);
  input.value = "";
  button.disabled = true;
  const pending = addMessage("bot", "Looking at your expenses…");
  try {
    const result = await api("/api/assistant/query", { method: "POST", body: { question } });
    pending.textContent = result.answer;
    pending.append(describeToolCalls(result));
  } catch (error) {
    pending.textContent = error.message;
    pending.classList.add("error");
  } finally {
    button.disabled = false;
    input.focus();
  }
}

/* ---------- Wiring ---------- */

function debounce(fn, wait) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function init() {
  $("#expense-form").addEventListener("submit", submitExpense);
  $("#cancel-edit").addEventListener("click", () => {
    resetForm();
    $("#form-status").textContent = "";
    loadExpenses();
  });

  const filters = $("#filters");
  const reload = () => { state.page = 1; loadExpenses(); };
  filters.addEventListener("change", reload);
  filters.addEventListener("input", debounce((event) => { if (event.target.name === "q") reload(); }, 300));
  filters.addEventListener("submit", (event) => { event.preventDefault(); reload(); });
  filters.addEventListener("reset", () => setTimeout(reload, 0));

  $("#prev-page").addEventListener("click", () => { state.page = Math.max(1, state.page - 1); loadExpenses(); });
  $("#next-page").addEventListener("click", () => { state.page = Math.min(state.totalPages, state.page + 1); loadExpenses(); });

  $("#assistant-form").addEventListener("submit", (event) => {
    event.preventDefault();
    ask($("#question").value);
  });
  for (const chip of document.querySelectorAll("#suggestions button")) {
    chip.addEventListener("click", () => ask(chip.textContent));
  }
  $("#assistant-mode").textContent = "Answers are calculated from your recorded expenses.";

  resetForm();
  loadMeta()
    .then(refresh)
    .catch(showGlobalError);
}

document.addEventListener("DOMContentLoaded", init);
