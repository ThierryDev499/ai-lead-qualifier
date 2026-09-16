const $ = (s) => document.querySelector(s);
const el = (tag, text, cls = "") => {
  const n = document.createElement(tag);
  n.textContent = text;
  n.className = cls;
  return n;
};
let current = null,
  busy = false;
const classes = {
  quente: "Hot / quente",
  morno: "Warm / morno",
  frio: "Cold / frio",
  pending: "Pending",
};
async function api(path, method = "GET", body) {
  const r = await fetch("/api" + path, {
    method,
    headers: { "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await r.json();
  if (!r.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : "Invalid request. Check the fields.",
    );
  return data;
}
async function action(text, fn) {
  if (busy) return;
  busy = true;
  $("#notice").textContent = text;
  document.querySelectorAll("button").forEach((b) => (b.disabled = true));
  try {
    await fn();
    $("#notice").textContent = "";
  } catch (e) {
    $("#notice").textContent = e.message;
  } finally {
    busy = false;
    document.querySelectorAll("button").forEach((b) => (b.disabled = false));
  }
}
async function refresh() {
  const all = await api("/leads");
  const previous = $("#source").value;
  const option = el("option", "All sources");
  option.value = "";
  $("#source").replaceChildren(
    option,
    ...[...new Set(all.map((l) => l.data.source))].sort().map((s) => {
      const o = el("option", s);
      o.value = s;
      return o;
    }),
  );
  $("#source").value = previous;
  const rows = all.filter(
    (l) =>
      (!$("#classification").value ||
        (l.classification || "pending") === $("#classification").value) &&
      (!previous || l.data.source === previous),
  );
  $("#leads").replaceChildren(
    ...rows.map((l) => {
      const row = el("tr");
      const first = el("td");
      const b = el("button", l.data.name);
      b.onclick = () => action("Opening lead...", () => open(l.id));
      first.append(b, el("small", l.data.company));
      const status = el("td");
      status.append(
        el(
          "span",
          classes[l.classification || "pending"],
          "status " + (l.classification || ""),
        ),
      );
      row.append(
        first,
        el("td", l.score === null ? "-" : String(l.score)),
        status,
        el("td", l.data.source),
      );
      return row;
    }),
  );
  if (!rows.length) {
    const row = el("tr");
    const cell = el("td", "No leads in this view.");
    cell.colSpan = 4;
    row.append(cell);
    $("#leads").append(row);
  }
  const stats = await api("/dashboard");
  $("#metrics").replaceChildren(
    ...["quente", "morno", "frio", "pending"].map((c) => {
      const m = el("div", "", "metric");
      m.append(
        el("span", classes[c]),
        el(
          "strong",
          stats.counts.find((r) => r.classification === c)?.count ?? 0,
        ),
      );
      return m;
    }),
  );
}
async function open(id) {
  current = await api("/leads/" + id);
  render();
  await refresh();
}
function render() {
  const l = current;
  const d = l.data;
  const target = $("#detail");
  const top = el("div", "", "heading");
  top.append(
    el("h2", d.name),
    el(
      "span",
      classes[l.classification || "pending"],
      "status " + (l.classification || ""),
    ),
  );
  target.replaceChildren(
    top,
    el("p", d.company + " / " + d.role, "muted"),
    el("p", d.message, "prose"),
  );
  const contact = el("details");
  contact.append(el("summary", "Contact and company details"));
  const fields = el("dl");
  for (const [k, v] of Object.entries(d))
    fields.append(el("dt", k.replaceAll("_", " ")), el("dd", String(v)));
  contact.append(fields);
  target.append(contact);
  const qualify = el(
    "button",
    l.analysis ? "Qualify again" : "Qualify with local AI",
    "primary",
  );
  qualify.onclick = () =>
    action("Analyzing commercial criteria with local AI...", async () => {
      current = await api(`/leads/${l.id}/qualify`, "POST");
      render();
      await refresh();
    });
  target.append(qualify);
  if (l.analysis) {
    const a = l.analysis;
    const score = el("div", "", "scoreline");
    const meter = el("meter");
    meter.min = 0;
    meter.max = 100;
    meter.value = l.score;
    meter.setAttribute("aria-label", "Commercial fit score");
    score.append(el("strong", String(l.score)), el("small", "/ 100"), meter);
    target.append(score);
    const criteria = el("div", "", "criteria");
    for (const [key, max] of [
      ["fit", 30],
      ["urgency", 25],
      ["budget", 25],
      ["authority", 20],
    ]) {
      const c = el("div", key);
      c.append(el("strong", `${a[key]} / ${max}`));
      criteria.append(c);
    }
    target.append(criteria, el("h3", "Score rationale"));
    const reasons = el("ul");
    a.reasons.forEach((r) => reasons.append(el("li", r)));
    target.append(
      reasons,
      el("h3", "Intent"),
      el("p", a.intent, "prose"),
      el("h3", "Next action"),
      el("p", a.next_action, "prose"),
      el("h3", "Suggested outreach"),
      el("p", a.outreach, "prose"),
    );
    const sync = el("button", "Sync to demo CRM");
    sync.onclick = () =>
      action("Saving to local CRM simulator...", async () => {
        await api(`/leads/${l.id}/crm-sync`, "POST");
        await open(l.id);
      });
    target.append(
      sync,
      el(
        "p",
        l.crm
          ? `Simulated CRM record: ${l.crm.external_id}`
          : "CRM simulation: local only. No external delivery.",
        "crm-note",
      ),
    );
  }
  const history = el("details");
  history.append(el("summary", "Lead history"));
  l.history.forEach((e) => {
    const row = el("div", "", "event");
    row.append(
      el("time", new Date(e.created_at).toLocaleString()),
      el("strong", e.kind),
    );
    if (e.kind !== "qualified") row.append(el("p", e.detail));
    history.append(row);
  });
  target.append(history);
}
$("#new").onclick = () => {
  $("#createForm").reset();
  $("#create .form-error").textContent = "";
  $("#create").showModal();
};
$("#close").onclick = () => $("#create").close();
$("#createForm").onsubmit = async (event) => {
  event.preventDefault();
  if (busy) return;
  const form = event.target;
  const submit = form.querySelector(".primary");
  submit.disabled = true;
  try {
    const data = Object.fromEntries(new FormData(form));
    data.budget = Number(data.budget);
    data.company_size = Number(data.company_size);
    const lead = await api("/leads", "POST", data);
    $("#create").close();
    await action("Opening lead...", () => open(lead.id));
  } catch (e) {
    $("#create .form-error").textContent = e.message;
  } finally {
    submit.disabled = false;
  }
};
$("#samples").onclick = () =>
  action("Loading fictional leads...", async () => {
    const rows = await api("/samples", "POST");
    await open(rows[0].id);
  });
for (const id of ["#classification", "#source"])
  $(id).onchange = () => action("Filtering leads...", refresh);
action("Loading pipeline...", refresh);
