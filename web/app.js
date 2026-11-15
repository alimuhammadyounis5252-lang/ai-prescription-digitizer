"use strict";
const $ = id => document.getElementById(id);
const FORMS = ["", "Tablet", "Capsule", "Syrup", "Suspension", "Injection", "Drops", "Cream", "Ointment", "Lotion", "Gel", "Sachet", "Inhaler", "Spray"];
const FOODS = [["", "not written"], ["after meal", "after meal"], ["before meal", "before meal"], ["empty stomach", "empty stomach"]];
const FOOD_TEXT = {after_meal: "after meal", before_meal: "before meal", empty_stomach: "empty stomach"};
const UNCLEAR_UR = "ہدایت واضح نہیں، فارماسسٹ سے تصدیق کریں۔";
let uploadSeq = 0;         // guards against a slow old upload overwriting a new one
let current = null;        // last result from the server
let locked = null;         // approved record
let urduTimer = null;

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v; else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v); else node.setAttribute(k, v);
  }
  for (const kid of kids) if (kid != null) node.append(kid);
  return node;
}
function msg(target, kind, text, list) {
  const box = el("div", {class: "msg " + kind, text});
  if (list && list.length) { const ul = el("ul"); list.forEach(t => ul.append(el("li", {text: t}))); box.append(ul); }
  target.replaceChildren(box);
}

// fetch wrapper: asks for the access code once when the server requires it
async function api(url, options) {
  let res = await fetch(url, options);
  if (res.status === 401) {
    const code = window.prompt("Access code:");
    if (code === null) return res;
    const login = await fetch("/api/login", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code})});
    if (!login.ok) { window.alert("Wrong access code."); return res; }
    res = await fetch(url, options);
  }
  return res;
}

async function checkHealth() {
  const pill = $("modelPill");
  try {
    const h = await (await fetch("/api/health")).json();
    if (h.model_configured) {
      pill.textContent = "Model: " + h.model.model + (h.second_reader ? "  +  cross-check: " + h.second_reader : "");
      pill.className = "pill";
    } else {
      pill.textContent = "No model connected"; pill.className = "pill bad";
      msg($("status"), "warn", "No recognition model is connected yet, so nothing can be read. Set VLM_BASE_URL, VLM_MODEL and VLM_API_KEY in the .env file and restart (README, section \"Connect a model\").");
    }
  } catch (e) { pill.textContent = "Server not reachable"; pill.className = "pill bad"; }
}

function resetView() {
  current = null; locked = null;
  ["meds", "otherBox", "qualityBox", "approveMsg", "secondBox"].forEach(id => $(id).replaceChildren());
  $("actions").classList.add("hidden");
  ["exportBtn", "fhirBtn", "shareBtn", "printBtn"].forEach(id => $(id).disabled = true);
  ["approveBtn", "addBtn", "pharmacist"].forEach(id => $(id).disabled = false);
}

async function handleFile(file) {
  if (!file) return;
  const seq = ++uploadSeq;
  resetView();
  const url = URL.createObjectURL(file);
  const img = $("preview");
  img.onload = () => URL.revokeObjectURL(url);
  img.src = url; img.style.display = "block"; img.classList.remove("zoom");
  $("previewHint").textContent = "Click the photo to zoom.";
  $("status").replaceChildren(el("div", {class: "msg info"}, el("span", {class: "spinner"}), "Reading the prescription with the model. This can take up to a minute..."));
  const form = new FormData(); form.append("file", file);
  let res, body;
  try { res = await api("/api/recognize", {method: "POST", body: form}); body = await res.json().catch(() => ({})); }
  catch (e) { if (seq === uploadSeq) msg($("status"), "crit", "Could not reach the server. Is app.py running?"); return; }
  if (seq !== uploadSeq) return;                       // a newer upload replaced this one
  if (!res.ok) { msg($("status"), "crit", body.error || "Upload failed (server error " + res.status + "). See the terminal window for details."); return; }
  current = body;
  render(body);
}

function render(r) {
  const q = r.image_quality;
  if (q.warnings.length) msg($("qualityBox"), "warn", "Photo quality: " + q.warnings.join(" ") + " Results may be less reliable.");
  if (r.status !== "ok") {
    msg($("status"), r.status === "no_medicines" ? "warn" : "crit", r.message + (r.status === "rejected_quality" ? "" : " You can still type the medicines by hand below."));
    if (r.status === "rejected_quality") return;
  } else {
    const n = r.medicines.length, attn = r.medicines.filter(m => m.needs_attention).length;
    msg($("status"), attn ? "warn" : "info",
        n + " medicine line" + (n === 1 ? "" : "s") + " read by " + r.model.model + "." +
        (attn ? " " + attn + " need careful checking (red border)." : "") + " " + r.confidence_note);
  }
  renderSecond(r.second_reader);
  if (r.other_lines.length) {
    const ul = el("ul", {class: "other", style: "list-style:none;padding:0;display:flex;flex-direction:column;gap:4px;"});
    r.other_lines.forEach(l => {
      const isLab = l.kind === "lab";
      const li = el("li", {style: "display:flex;align-items:center;gap:8px;font-size:13px;"});
      const badge = el("span", {
        style: isLab 
          ? "background:#ede9fe;color:#6b21a8;padding:2px 8px;border-radius:12px;font-weight:700;font-size:11px;border:1px solid #c4b5fd;"
          : "background:#f1f5f9;color:#475569;padding:2px 6px;border-radius:4px;font-weight:600;font-size:11px;",
        text: isLab ? "🔬 LAB TEST" : "[" + l.kind + "]"
      });
      li.append(badge, el("span", {style: isLab ? "color:#1e1b4b;font-weight:600;" : "color:inherit;", text: l.text + (l.unclear ? " (unclear)" : "")}));
      ul.append(li);
    });
    $("otherBox").replaceChildren(el("div", {class: "lbl", style: "font-weight:600;margin-bottom:6px;", text: "Other text on the page (Labs, Doctor, Diagnosis):"}), ul);
  }
  r.medicines.forEach(m => $("meds").append(medCard(m)));
  $("actions").classList.remove("hidden");
}

function renderSecond(s) {
  if (!s) return;
  if (s.error) { msg($("secondBox"), "warn", "The cross-check model did not answer (" + s.error + "). Only one reading is shown."); return; }
  if (!s.enabled) return;
  const extra = s.only_second_rows || [];
  const box = el("div", {class: "msg " + (s.disagreed || extra.length ? "warn" : "ok"),
    text: "Cross-check with " + s.model + ": " + s.agreed + " line(s) agree, " + s.disagreed + " differ, " + s.only_first + " seen only by the first model."});
  if (extra.length) {
    box.append(el("div", {text: "Lines seen ONLY by the second model. Check the original; a medicine may have been missed:"}));
    const ul = el("ul");
    extra.forEach(row => ul.append(el("li", {}, el("span", {text: row.raw_text + "  "}),
      el("button", {class: "btn ghost small", type: "button", text: "Add as row",
        onclick: e => { const card = medCard(Object.assign({}, row, {second_reading: row.raw_text, raw_text: ""})); $("meds").append(card); e.target.disabled = true; }}))));
    box.append(ul);
  }
  $("secondBox").replaceChildren(box);
}

function field(label, node) { return el("div", {}, el("div", {class: "lbl", text: label}), node); }
function input(cls, value, placeholder) {
  return el("input", {type: "text", class: cls, value: value || "", placeholder: placeholder || "", oninput: scheduleUrdu});
}
function select(cls, options, value) {
  const s = el("select", {class: cls, onchange: scheduleUrdu});
  options.forEach(o => { const [v, t] = Array.isArray(o) ? o : [o, o || "not written"]; const op = el("option", {value: v, text: t}); if (v === value) op.selected = true; s.append(op); });
  return s;
}

function medCard(m) {
  const card = el("div", {class: "med" + (m.needs_attention ? " attn" : "")});
  card.dataset.lineNo = m.line_no == null ? "" : m.line_no;
  card.dataset.raw = m.raw_text || "";
  card.append(el("div", {class: "lbl", text: m.raw_text ? "As read from the image (line " + m.line_no + ")" : "Added by pharmacist"}));
  if (m.raw_text) card.append(el("div", {class: "raw", text: m.raw_text}));
  if (m.second_reading) card.append(el("div", {class: "second"}, "Second model read: ", el("b", {text: m.second_reading})));
  const nameInput = input("f-name", m.name, "Medicine name");
  card.append(el("div", {class: "fields"},
    field("Form", select("f-form", FORMS, m.form || "")),
    field("Name", nameInput),
    field("Strength", input("f-strength", m.strength ? m.strength.raw : "", "e.g. 500mg")),
    field("Frequency", input("f-frequency", m.frequency ? m.frequency.raw : "", "e.g. 1+0+1")),
    field("Duration", input("f-duration", m.duration ? m.duration.raw : "", "e.g. 5 days")),
    field("Food", select("f-food", FOODS, m.food ? FOOD_TEXT[m.food.code] : ""))));
  if (m.flags && m.flags.length) {
    const chips = el("div", {class: "chips"});
    m.flags.forEach(f => chips.append(el("span", {class: "chip " + f.severity, text: f.message})));
    card.append(chips);
  }
  const ref = m.reference || {};
  if (ref.match_type === "exact" && ref.entry) {
    card.append(el("div", {class: "sugg", text: "Reference list: " + ref.entry.brand + " = " + ref.entry.generic + (ref.entry.verified ? "" : "  (list entry not yet verified against DRAP)")}));
  } else if (ref.suggestions && ref.suggestions.length) {
    const box = el("div", {class: "sugg", text: "Similar names in the reference list (check the original before using): "});
    ref.suggestions.forEach(s => box.append(el("button", {class: "btn ghost small", type: "button", text: s.brand + " (" + s.generic + ")",
      onclick: () => { nameInput.value = s.brand; scheduleUrdu(); }}), " "));
    card.append(box);
  }
  const urdu = el("div", {class: "urdu" + (m.urdu && m.urdu.complete ? "" : " unclear"), lang: "ur", text: m.urdu ? m.urdu.text : ""});
  card.append(el("div", {class: "lbl", text: "Urdu instruction for the patient"}), urdu);
  const chk = el("input", {type: "checkbox", class: "f-checked"});
  card.append(el("div", {class: "medfoot"},
    el("label", {}, chk, " I checked this row against the original"),
    el("button", {class: "btn ghost small", type: "button", text: "🔊 اردو سنیں", onclick: (e) => speak(urdu.textContent, e.currentTarget)}),
    el("button", {class: "btn ghost small sp del", type: "button", text: "Remove row", onclick: () => { card.remove(); }})));
  return card;
}

function collect() {
  return [...document.querySelectorAll("#meds .med")].map(c => ({
    line_no: c.dataset.lineNo === "" ? null : Number(c.dataset.lineNo),
    raw_text: c.dataset.raw,
    form: c.querySelector(".f-form").value, name: c.querySelector(".f-name").value,
    strength: c.querySelector(".f-strength").value, frequency: c.querySelector(".f-frequency").value,
    duration: c.querySelector(".f-duration").value, food: c.querySelector(".f-food").value,
    checked: c.querySelector(".f-checked").checked}));
}

function scheduleUrdu() { clearTimeout(urduTimer); urduTimer = setTimeout(refreshUrdu, 350); }
async function refreshUrdu() {
  const cards = [...document.querySelectorAll("#meds .med")];
  try {
    const res = await api("/api/urdu", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({medicines: collect()})});
    const out = (await res.json()).medicines || [];
    cards.forEach((c, i) => { if (!out[i]) return; const u = c.querySelector(".urdu"); u.textContent = out[i].text; u.classList.toggle("unclear", !out[i].complete); });
  } catch (e) { /* keep the previous text */ }
}

let currentAudio = null;
function speak(text, btn) {
  if (!text) return;
  if (currentAudio) {
    try { currentAudio.pause(); } catch(e) {}
    currentAudio = null;
  }
  const origText = btn ? btn.textContent : "";
  if (btn) {
    btn.textContent = "🔊 بول رہا ہے...";
    btn.disabled = true;
  }
  const resetBtn = () => {
    if (btn) {
      btn.textContent = origText;
      btn.disabled = false;
    }
  };

  const audio = new Audio("/api/tts?text=" + encodeURIComponent(text));
  currentAudio = audio;
  audio.onended = resetBtn;
  audio.onerror = () => {
    resetBtn();
    if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(text);
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    }
  };
  audio.play().catch(() => {
    resetBtn();
    if ("speechSynthesis" in window) {
      const u = new SpeechSynthesisUtterance(text);
      speechSynthesis.cancel();
      speechSynthesis.speak(u);
    }
  });
}

let approving = false;
async function approve() {
  if (!current || approving) return;                   // ignores a second click while the first is running
  approving = true; $("approveBtn").disabled = true;
  let res, body;
  try {
    res = await api("/api/records", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({request_id: current.request_id, pharmacist: $("pharmacist").value, medicines: collect()})});
    body = await res.json().catch(() => ({}));
  } catch (e) {
    msg($("approveMsg"), "crit", "Could not reach the server. Nothing was approved.");
    approving = false; $("approveBtn").disabled = false; return;
  }
  approving = false;
  if (!res.ok) { $("approveBtn").disabled = false; msg($("approveMsg"), "crit", body.error || "Not approved (server error " + res.status + ").", body.details); return; }
  locked = body;
  document.querySelectorAll("#meds input, #meds select, #meds .del, #secondBox button").forEach(n => n.disabled = true);
  ["approveBtn", "addBtn", "pharmacist"].forEach(id => $(id).disabled = true);
  ["exportBtn", "fhirBtn", "shareBtn", "printBtn"].forEach(id => $(id).disabled = false);
  msg($("approveMsg"), "ok", "Approved and locked as " + body.record_id + " by " + body.approved_by + ". " + body.audit.changes_by_pharmacist.length + " correction(s) recorded in the audit trail.");
}

function download(name, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
  const a = el("a", {href: URL.createObjectURL(blob), download: name});
  document.body.append(a); a.click(); a.remove();
}
async function downloadFhir(id) {
  const res = await api("/api/records/" + id + "/fhir");
  if (res.ok) download(id + ".fhir.json", await res.json());
}
function medLabel(m) { return [m.form, m.name, m.strength].filter(Boolean).join(" "); }
async function share(record) {
  const text = record.medicines.map((m, i) => (i + 1) + ". " + medLabel(m) + "\n" + m.urdu.text).join("\n\n");
  if (!window.confirm("Share these medicine instructions? Only share with the patient or their caregiver, with their permission.")) return;
  if (navigator.share) { try { await navigator.share({title: "Medicine instructions", text}); } catch (e) { /* cancelled */ } }
  else { await navigator.clipboard.writeText(text); window.alert("Instructions copied. Paste them into the message you want to send."); }
}

// ---------------------------------------------------------------- records tab
function showTab(name) {
  $("viewNew").classList.toggle("hidden", name !== "new");
  $("viewRecords").classList.toggle("hidden", name !== "records");
  $("tabNew").classList.toggle("on", name === "new");
  $("tabRecords").classList.toggle("on", name === "records");
  if (name === "records") loadRecords();
}
function stat(value, label) { return el("div", {class: "stat"}, el("b", {text: String(value)}), el("span", {text: label})); }

async function loadRecords() {
  $("recordDetail").classList.add("hidden");
  const [listRes, statsRes] = await Promise.all([api("/api/records"), api("/api/stats")]);
  if (!listRes.ok || !statsRes.ok) { msg($("recordsTable"), "crit", "Could not load records."); return; }
  const records = (await listRes.json()).records, s = await statsRes.json();
  const keptShare = s.model_rows ? Math.round(100 * s.rows_kept_unchanged / s.model_rows) + "%" : "n/a";
  $("statsBox").replaceChildren(stat(s.records, "approved records"), stat(s.model_rows, "rows read by the model"),
    stat(keptShare, "rows approved without edits"), stat(s.rows_edited, "rows edited"), stat(s.rows_removed, "rows removed"), stat(s.rows_added, "rows added by hand"));
  if (!records.length) { msg($("recordsTable"), "info", "No approved records yet."); return; }
  const table = el("table", {class: "list"}, el("tr", {}, ...["Record", "Approved at", "Pharmacist", "Model", "Medicines", "Corrections"].map(t => el("th", {text: t}))));
  records.forEach(r => table.append(el("tr", {class: "rowlink", onclick: () => openRecord(r.record_id)},
    ...[r.record_id, r.approved_at.replace("T", " ").slice(0, 16), r.approved_by, r.model, r.medicines, r.corrections].map(t => el("td", {text: String(t)})))));
  $("recordsTable").replaceChildren(table,
    el("p", {class: "kv", text: "\"Rows approved without edits\" describes how the tool was used. It is not an accuracy figure; accuracy comes from evaluate.py."}));
}

async function openRecord(id) {
  const res = await api("/api/records/" + id);
  if (!res.ok) return;
  const r = await res.json(), box = $("recordDetail");
  const meds = el("table", {class: "list"}, el("tr", {}, ...["#", "Medicine", "Dose as written", "Urdu instruction"].map(t => el("th", {text: t}))));
  r.medicines.forEach((m, i) => meds.append(el("tr", {},
    el("td", {text: String(i + 1)}), el("td", {text: medLabel(m)}),
    el("td", {text: [m.frequency, m.duration, m.food].filter(Boolean).join(", ")}),
    el("td", {class: "urdu", lang: "ur", text: m.urdu.text}))));
  const changes = r.audit.changes_by_pharmacist;
  const audit = el("ul", {class: "other"});
  changes.forEach(c => audit.append(el("li", {text: (c.line_no ? "Line " + c.line_no + ", " : "") + c.field + ": model \"" + c.model + "\" -> pharmacist \"" + c.pharmacist + "\""})));
  box.replaceChildren(
    el("h2", {text: "Record " + r.record_id}),
    el("p", {class: "kv", text: "Approved by " + r.approved_by + " on " + r.approved_at.replace("T", " ").slice(0, 16) + ". Read by " + r.model.model + ". Status: " + r.status + "."}),
    meds,
    el("div", {class: "lbl", text: "Audit trail: " + changes.length + " correction(s) by the pharmacist"}), changes.length ? audit : null,
    el("div", {class: "row left"},
      el("button", {class: "btn ghost small", type: "button", text: "Export JSON", onclick: () => download(r.record_id + ".json", r)}),
      el("button", {class: "btn ghost small", type: "button", text: "Export FHIR", onclick: () => downloadFhir(r.record_id)}),
      el("button", {class: "btn ghost small", type: "button", text: "Share Urdu instructions", onclick: () => share(r)}),
      el("button", {class: "btn ghost small", type: "button", text: "Print", onclick: () => window.print()})));
  box.classList.remove("hidden");
  box.scrollIntoView({behavior: "smooth"});
}

// ---------------------------------------------------------------- wiring
$("pickBtn").onclick = () => $("fileInput").click();
$("camBtn").onclick = () => $("camInput").click();
["fileInput", "camInput"].forEach(id => $(id).addEventListener("change", e => { const f = e.target.files[0]; e.target.value = ""; handleFile(f); }));
const drop = $("drop");
["dragover", "dragenter"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", e => handleFile(e.dataTransfer.files[0]));
$("preview").onclick = () => $("preview").classList.toggle("zoom");
$("addBtn").onclick = () => $("meds").append(medCard({line_no: null, raw_text: "", flags: [], reference: {}, urdu: {text: UNCLEAR_UR, complete: false}}));
$("approveBtn").onclick = approve;
$("exportBtn").onclick = () => download(locked.record_id + ".json", locked);
$("fhirBtn").onclick = () => downloadFhir(locked.record_id);
$("shareBtn").onclick = () => share(locked);
$("printBtn").onclick = () => window.print();
$("tabNew").onclick = () => showTab("new");
$("tabRecords").onclick = () => showTab("records");
if ("speechSynthesis" in window) speechSynthesis.getVoices();
checkHealth();
