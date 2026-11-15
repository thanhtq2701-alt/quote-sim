"use strict";

// The browser keeps only the list of steps. Every click sends the whole list to the server,
// which replays it on a fresh, empty desk and returns quotes plus the audit log. No business
// rule lives here: this file only builds steps and draws what the server returns.

const ACTION_BUTTONS = [
  { action: "submit", label: "Submit", permission: "submit_quote" },
  { action: "approve", label: "Approve", permission: "approve_quote" },
  { action: "reject", label: "Reject", permission: "reject_quote" },
  { action: "revise", label: "Revise", permission: "revise_quote" },
  { action: "send", label: "Send", permission: "send_quote" },
];

const STATE_LABELS = {
  draft: "Draft",
  pending_approval: "Pending approval",
  approved: "Approved",
  rejected: "Rejected",
  sent: "Sent",
};
const PROGRESS = ["draft", "pending_approval", "approved", "sent"];

const SCENARIOS = [
  {
    title: "Small order, auto-approved",
    text: "No discount, so the policy approves on submit — no manager needed.",
    actor: "sales-01",
    steps: (agent) => [
      { action: "agent_draft", actor: agent, request: "3 x sample-widget, 4 x sample-cable" },
      { action: "submit", actor: "sales-01", quote_id: "Q-0001" },
      { action: "send", actor: "sales-01", quote_id: "Q-0001" },
    ],
  },
  {
    title: "Volume deal needs a manager",
    text: "A 15% volume discount is above the threshold, so a manager must approve.",
    actor: "manager-01",
    steps: (agent) => [
      { action: "agent_draft", actor: agent, request: "60 x sample-widget, 1 x sample-support-plan" },
      { action: "submit", actor: "sales-01", quote_id: "Q-0001" },
      { action: "approve", actor: "manager-01", quote_id: "Q-0001" },
      { action: "send", actor: "sales-01", quote_id: "Q-0001" },
    ],
  },
  {
    title: "Blocked shortcuts",
    text: "Sales tries to approve its own deal, the agent tries to send — both denied and logged.",
    actor: "sales-01",
    steps: (agent) => [
      { action: "agent_draft", actor: agent, request: "55 x sample-gadget" },
      { action: "send", actor: agent, quote_id: "Q-0001" },
      { action: "submit", actor: "sales-01", quote_id: "Q-0001" },
      { action: "approve", actor: "sales-01", quote_id: "Q-0001" },
      { action: "reject", actor: "manager-02", quote_id: "Q-0001" },
    ],
  },
];

const state = {
  catalog: null,
  steps: [],
  actor: "sales-01",
  result: null,
  banner: null,
  showReads: false,
  busy: false,
};

// ----- tiny DOM helper -----------------------------------------------------------------------

/** Build an element. Children that are strings become text nodes, so data is never parsed as HTML. */
function h(tag, props = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") element.className = value;
    else if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else if (key in element && typeof value !== "string") element[key] = value;
    else element.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

const $ = (id) => document.getElementById(id);

// ----- server calls ----------------------------------------------------------------------------

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || `HTTP ${response.status}`);
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}

/** Replay `steps`; only keep them if the server accepted the request as well-formed. */
async function replaySteps(steps, { announceLast = true } = {}) {
  state.busy = true;
  renderBusy();
  try {
    const result = await api("/api/replay", { viewer: state.actor, steps });
    state.steps = steps;
    state.result = result;
    if (announceLast && result.steps.length > 0) {
      const last = result.steps[result.steps.length - 1];
      state.banner = last.ok
        ? { kind: "ok", title: last.message, notes: last.notes }
        : { kind: "refused", title: `Refused: ${last.message}`, notes: ["The attempt was recorded in the audit log."] };
    }
  } catch (error) {
    state.banner = error.status === 422
      ? questionBanner(error, steps)
      : { kind: "refused", title: `Request rejected: ${error.message}`, notes: [] };
  } finally {
    state.busy = false;
    render();
  }
}

/**
 * HTTP 422 means "a person must answer first". Nothing was kept or audited. For an ambiguous
 * discount the server offers both readings; picking one re-sends the step with that unit.
 */
function questionBanner(error, steps) {
  const clarify = (error.data && error.data.clarify) || {};
  const index = clarify.step ?? steps.length - 1;
  const asked = steps[index];
  const options = (clarify.options || []).map((option) => ({
    label: option.label,
    steps: [...steps.slice(0, index), { ...asked, discount_unit: option.discount_unit }],
  }));
  return {
    kind: "question",
    title: `Question: ${error.message}`,
    notes: options.length ? [] : ["Nothing was created. Rephrase and try again."],
    options,
  };
}

function perform(step) {
  return replaySteps([...state.steps, step]);
}

// ----- rendering -------------------------------------------------------------------------------

function render() {
  renderActor();
  renderBanner();
  renderQuotes();
  renderAudit();
  renderBusy();
}

function renderBusy() {
  for (const button of document.querySelectorAll("button")) button.disabled = state.busy;
}

function userById(userId) {
  return state.catalog.users.find((user) => user.user_id === userId);
}

function roleOf(userId) {
  return userById(userId)?.role;
}

function allowed(permission) {
  const role = roleOf(state.actor);
  return (state.catalog.permissions[role] || []).includes(permission);
}

function renderActor() {
  const permissions = state.catalog.permissions[roleOf(state.actor)] || [];
  $("actor-permissions").replaceChildren(
    ...permissions.map((permission) => h("span", { class: "chip" }, permission.replaceAll("_", " "))),
  );
}

function renderBanner() {
  const banner = $("banner");
  if (!state.banner) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  banner.className = `banner ${state.banner.kind}`;
  const options = state.banner.options || [];
  banner.replaceChildren(
    h("strong", {}, state.banner.title),
    state.banner.notes.length ? h("ul", {}, state.banner.notes.map((note) => h("li", {}, note))) : null,
    options.length
      ? h("div", { class: "actions answer" }, options.map((option) =>
        h("button", { class: "button", type: "button", onclick: () => replaySteps(option.steps) }, option.label),
      ))
      : null,
  );
}

function renderQuotes() {
  const quotes = state.result ? [...state.result.quotes].reverse() : [];
  $("quote-count").textContent = quotes.length ? `${quotes.length} quote(s), newest first` : "";
  if (!quotes.length) {
    $("quotes").replaceChildren(
      h("div", { class: "empty" }, "No quotes yet. Ask the agent to draft one, or try a scenario."),
    );
    return;
  }
  $("quotes").replaceChildren(...quotes.map(renderQuote));
}

function renderQuote(quote) {
  const people = [
    `created by ${quote.creator_id}`,
    quote.submitted_by && `submitted by ${quote.submitted_by}`,
    quote.approved_by && `approved by ${quote.approved_by}`,
  ].filter(Boolean);

  return h(
    "article",
    { class: "card" },
    h(
      "div",
      { class: "quote-head" },
      h("h3", { class: "mono" }, quote.quote_id),
      h("span", { class: `state ${quote.state}` }, STATE_LABELS[quote.state] || quote.state),
    ),
    h("p", { class: "quote-meta" }, people.join(" · ")),
    renderStepper(quote.state),
    h("div", { class: "table-wrap" }, renderLines(quote)),
    h(
      "div",
      { class: "quote-foot" },
      h(
        "div",
        { class: "actions" },
        ACTION_BUTTONS.map(({ action, label, permission }) => {
          const permitted = allowed(permission);
          return h(
            "button",
            {
              class: `button${permitted ? "" : " not-permitted"}`,
              type: "button",
              title: permitted
                ? `${label} as ${state.actor}`
                : `${roleOf(state.actor)} is not permitted — try it to see the denial being audited`,
              onclick: () => perform({ action, actor: state.actor, quote_id: quote.quote_id }),
            },
            label,
          );
        }),
      ),
      renderTotals(quote),
    ),
    quote.cost_visible
      ? null
      : h("p", { class: "locked" }, `Cost and margin are hidden for the ${roleOf(state.actor)} role.`),
    renderAddLine(quote),
  );
}

function renderStepper(current) {
  const currentIndex = current === "rejected" ? 1 : PROGRESS.indexOf(current);
  return h(
    "div",
    { class: "stepper", "aria-label": "Workflow progress" },
    PROGRESS.map((name, index) => {
      if (current === "rejected" && index === 1) return h("span", { class: "rejected" }, "Rejected");
      const status = index < currentIndex ? "done" : index === currentIndex ? "current" : "";
      return h("span", { class: status }, STATE_LABELS[name]);
    }),
  );
}

function renderLines(quote) {
  const showCost = quote.cost_visible;
  const head = h(
    "tr",
    {},
    h("th", {}, "Product"),
    h("th", { class: "num" }, "Qty"),
    h("th", { class: "num" }, "Unit price"),
    h("th", { class: "num" }, "Discount"),
    h("th", { class: "num" }, "Line total"),
    h("th", {}, "Evidence"),
    showCost ? h("th", { class: "num" }, "Unit cost") : null,
    showCost ? h("th", { class: "num" }, "Margin") : null,
    h("th", {}, ""),
  );
  const rows = quote.lines.map((line, index) =>
    h(
      "tr",
      {},
      h("td", { class: "mono" }, line.product_id),
      h("td", { class: "num" }, line.quantity),
      h("td", { class: "num" }, line.unit_price),
      h("td", { class: "num" }, `${line.discount_percent}%`),
      h("td", { class: "num" }, line.line_total),
      h("td", { class: "evidence" }, `${line.price_list_version} · ${line.discount_rule_id}`),
      showCost ? h("td", { class: "num cost" }, line.unit_cost ?? "unknown") : null,
      showCost ? h("td", { class: "num cost" }, line.margin ?? "unknown") : null,
      h(
        "td",
        {},
        h(
          "button",
          {
            class: "button icon",
            type: "button",
            title: `Remove this line as ${state.actor}`,
            "aria-label": `Remove ${line.product_id}`,
            onclick: () => perform({ action: "remove_line", actor: state.actor, quote_id: quote.quote_id, line_index: index }),
          },
          "×",
        ),
      ),
    ),
  );
  if (!rows.length) {
    rows.push(h("tr", {}, h("td", { colspan: showCost ? 9 : 7, class: "muted" }, "No lines.")));
  }
  return h("table", { class: "lines" }, h("thead", {}, head), h("tbody", {}, rows));
}

function renderTotals(quote) {
  return h(
    "dl",
    { class: "totals" },
    h("dt", {}, "Subtotal"), h("dd", {}, `${quote.subtotal} USD`),
    h("dt", {}, `VAT (${state.catalog.policy.vat_percent}%)`), h("dd", {}, `${quote.vat} USD`),
    h("dt", { class: "grand" }, "Total"), h("dd", { class: "grand" }, `${quote.total} USD`),
    quote.cost_visible ? h("dt", { class: "cost" }, "Margin") : null,
    quote.cost_visible ? h("dd", { class: "cost" }, quote.total_margin ? `${quote.total_margin} USD` : "unknown") : null,
  );
}

function renderAddLine(quote) {
  const versionSelect = h("select", { "aria-label": "Price list" }, versionOptions(false));
  const productSelect = h("select", { "aria-label": "Product" });
  const fillProducts = () => {
    const list = state.catalog.price_lists.find((item) => item.version === versionSelect.value);
    productSelect.replaceChildren(
      ...list.products.map((product) =>
        h("option", { value: product.product_id }, `${product.product_id} — ${product.unit_price}`),
      ),
    );
  };
  versionSelect.addEventListener("change", fillProducts);
  fillProducts();

  const quantity = h("input", { type: "number", min: "1", step: "1", value: "1", "aria-label": "Quantity" });
  // Free text on purpose: "10%", "10" and "0.1" are all accepted; the server asks if unclear.
  const discount = h("input", {
    type: "text", value: "0", placeholder: "10% or 0.1", inputmode: "decimal", "aria-label": "Discount",
  });

  const form = h(
    "form",
    {
      class: "add-line",
      onsubmit: (event) => {
        event.preventDefault();
        const qty = Number(quantity.value);
        if (!Number.isInteger(qty)) {
          state.banner = { kind: "refused", title: "Quantity must be a whole number.", notes: [] };
          renderBanner();
          return;
        }
        perform({
          action: "add_line",
          actor: state.actor,
          quote_id: quote.quote_id,
          product_id: productSelect.value,
          quantity: qty,
          // Sent exactly as typed so the server parses an exact Decimal and resolves the unit.
          discount: discount.value.trim() || "0",
          price_list_version: versionSelect.value,
        });
      },
    },
    h("label", {}, "Price list", versionSelect),
    h("label", {}, "Product", productSelect),
    h("label", {}, "Qty", quantity),
    h("label", {}, "Discount", discount),
    h("button", { class: "button", type: "submit" }, "Add line"),
  );
  return h("details", {}, h("summary", {}, `Add a line manually (as ${state.actor})`), form);
}

function versionOptions(includeFromRequest) {
  const options = [...state.catalog.price_lists].reverse().map((list) =>
    h("option", { value: list.version }, list.version === state.catalog.latest_price_list ? `${list.version} (latest)` : list.version),
  );
  if (includeFromRequest) {
    options.unshift(h("option", { value: "" }, "As the request says, else latest"));
  }
  return options;
}

function renderAudit() {
  const entries = state.result ? state.result.audit : [];
  const visible = entries.filter((entry) => state.showReads || entry.action !== "view_quote");
  const hidden = entries.length - visible.length;
  $("hidden-reads").textContent = hidden ? `${hidden} read entr${hidden === 1 ? "y" : "ies"} hidden.` : "";

  const head = h(
    "tr",
    {},
    ["#", "Time", "Actor", "Action", "Quote", "Transition", "Details"].map((title) => h("th", {}, title)),
  );
  const rows = visible.map((entry) => {
    const result = entry.details.result;
    const rowClass = result === "denied" ? "denied" : result === "failed" ? "failed"
      : entry.role === "policy" ? "policy" : entry.action === "view_quote" ? "read" : "";
    const details = Object.entries(entry.details).map(([key, value]) => `${key}=${value}`).join(", ");
    return h(
      "tr",
      { class: rowClass },
      h("td", { class: "muted" }, entries.indexOf(entry) + 1),
      h("td", { class: "mono" }, entry.timestamp.slice(11, 16)),
      h("td", {}, h("span", { class: "mono" }, entry.actor_id), " ", h("span", { class: `role ${entry.role}` }, entry.role)),
      h("td", { class: "mono" }, entry.action),
      h("td", { class: "mono" }, entry.quote_id),
      h("td", {}, `${entry.from_state ?? "—"} → ${entry.to_state ?? "✕"}`),
      h("td", { class: "details" }, details),
    );
  });
  if (!rows.length) {
    rows.push(h("tr", {}, h("td", { colspan: 7, class: "muted" }, "Nothing has happened yet.")));
  }
  $("audit").replaceChildren(h("thead", {}, head), h("tbody", {}, rows));
}

// ----- static sidebar content --------------------------------------------------------------------

function renderSidebar() {
  const catalog = state.catalog;

  $("actor-select").replaceChildren(
    ...catalog.users.map((user) =>
      h("option", { value: user.user_id, selected: user.user_id === state.actor }, `${user.display_name} — ${user.role}`),
    ),
  );
  $("agent-version").replaceChildren(...versionOptions(true));

  $("agent-rules").replaceChildren(
    h("thead", {}, h("tr", {}, h("th", {}, "Rule"), h("th", {}, "Min qty"), h("th", {}, "Discount"))),
    h("tbody", {}, catalog.agent_rules.map((rule) =>
      h("tr", {}, h("td", { class: "mono" }, rule.rule_id), h("td", {}, rule.min_quantity), h("td", {}, /^[0-9.]+$/.test(rule.discount_percent) ? `${rule.discount_percent}%` : rule.discount_percent)),
    )),
  );

  const policy = catalog.policy;
  $("policy").replaceChildren(
    h("dt", {}, "Max discount per line"), h("dd", {}, `${policy.max_discount_percent}%`),
    h("dt", {}, "Auto-approve if every line ≤"), h("dd", {}, `${policy.auto_approve_percent}%`),
    h("dt", {}, "VAT"), h("dd", {}, `${policy.vat_percent}%`),
    h("dt", {}, "Currency"), h("dd", {}, "USD, 2 decimals"),
  );

  $("price-lists").replaceChildren(
    ...catalog.price_lists.map((list) =>
      h("div", { class: "price-list" },
        h("h3", {}, list.version === catalog.latest_price_list ? `${list.version} (latest)` : list.version),
        h("table", { class: "mini" }, h("tbody", {}, list.products.map((product) =>
          h("tr", {}, h("td", { class: "mono" }, product.product_id), h("td", { class: "num" }, product.unit_price)),
        ))),
      ),
    ),
  );

  $("scenarios").replaceChildren(
    ...SCENARIOS.map((scenario) =>
      h("button", {
        class: "scenario",
        type: "button",
        onclick: () => {
          state.actor = scenario.actor;
          $("actor-select").value = scenario.actor;
          state.banner = { kind: "", title: `Scenario: ${scenario.title}`, notes: [scenario.text] };
          replaySteps(scenario.steps(catalog.agent_user_id), { announceLast: false });
        },
      }, h("strong", {}, scenario.title), h("span", {}, scenario.text)),
    ),
  );
}

// ----- start-up ------------------------------------------------------------------------------------

async function start() {
  try {
    state.catalog = await api("/api/catalog");
  } catch (error) {
    $("quotes").replaceChildren(h("div", { class: "empty" }, `Could not load the catalog: ${error.message}`));
    return;
  }
  renderSidebar();

  $("actor-select").addEventListener("change", (event) => {
    state.actor = event.target.value;
    // Same steps, different reader: replaying shows the quotes from the new user's point of view.
    replaySteps(state.steps, { announceLast: false });
  });
  $("agent-form").addEventListener("submit", (event) => {
    event.preventDefault();
    perform({
      action: "agent_draft",
      actor: state.catalog.agent_user_id,
      request: $("agent-request").value,
      price_list_version: $("agent-version").value,
    });
  });
  $("show-reads").addEventListener("change", (event) => {
    state.showReads = event.target.checked;
    renderAudit();
  });
  $("reset").addEventListener("click", () => {
    state.banner = { kind: "", title: "Simulation reset.", notes: [] };
    replaySteps([], { announceLast: false });
  });

  replaySteps([], { announceLast: false });
}

start();
