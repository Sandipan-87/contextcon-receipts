const $ = (s, el = document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const api = async (path, body) => {
  const r = await fetch(path, body ? {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)} : {});
  if (!r.ok) { const e = await r.json().catch(() => ({})); throw new Error(e.detail || r.statusText); }
  return r.json();
};
const chip = (t, cls) => `<span class="chip ${esc(cls || t)}">${esc(t)}</span>`;
const pct = p => p == null ? "–" : `${Math.round(p * 100)}%`;
const fmtUsd = v => v == null ? "n/a" : v >= 1e9 ? `$${(v / 1e9).toFixed(2)}B` : v >= 1e6 ? `$${(v / 1e6).toFixed(0)}M` : `$${Math.round(v).toLocaleString()}`;
let currentRun = null;

// ------------------------------------------------------------ navigation
document.querySelectorAll("#nav a").forEach(a => a.onclick = () => show(a.dataset.page));
function show(page) {
  document.querySelectorAll("#nav a").forEach(a => a.classList.toggle("active", a.dataset.page === page));
  document.querySelectorAll(".page").forEach(p => p.classList.toggle("active", p.id === `page-${page}`));
  ({board: loadBoard, rounds: loadRounds, pitch: loadExamples, learned: loadLearned, outbox: loadOutbox, audit: loadAudit, rules: loadRules})[page]?.();
}

// ------------------------------------------------------------ jobs (live agent console)
async function runJob(title, endpoint, body) {
  const {job} = await api(endpoint, body);
  const box = $("#console"), log = $("#console-log"), st = $("#console-status");
  box.classList.remove("hidden"); $("#console-title").textContent = title; log.textContent = ""; st.textContent = "running"; st.className = "pill";
  document.querySelectorAll("button.primary").forEach(b => b.disabled = true);
  let since = 0;
  try {
    for (;;) {
      const j = await api(`/api/jobs/${job}?since=${since}`);
      if (j.log.length) { log.textContent += j.log.join("\n") + "\n"; log.scrollTop = log.scrollHeight; }
      since = j.next;
      if (j.status !== "running") {
        st.textContent = j.status === "done" ? "done" : "error"; st.className = `pill ${j.status === "done" ? "done" : "error"}`;
        if (j.status === "error") throw new Error(j.error);
        return j.result;
      }
      await new Promise(r => setTimeout(r, 600));
    }
  } finally { document.querySelectorAll("button.primary").forEach(b => b.disabled = false); }
}
$("#console-close").onclick = () => $("#console").classList.add("hidden");

// ------------------------------------------------------------ receipts modal
async function openFact(runId, fid) {
  const d = await api(`/api/fact/${runId}/${fid}`);
  const v = JSON.stringify(d.fact.value, null, 1);
  $("#modal-body").innerHTML = `<h3>${esc(fid)} · ${esc(d.fact.label)}</h3>
    <pre class="json">${esc(v.length > 5000 ? v.slice(0, 5000) + "\n…" : v)}</pre>
    <div class="kv">
      <div>Raw bytes check</div><div>${d.matches_raw ? '<b style="color:var(--green)">✔ this value re-resolves from the stored API response</b>' : '<b style="color:var(--red)">✘ mismatch</b>'}</div>
      <div>JSON pointer</div><div class="mono">${esc(d.fact.pointer)}</div>
      <div>Receipt</div><div>#${d.entry.seq} · <span class="mono">POST ${esc(d.entry.endpoint)}</span> · ${esc(d.entry.source)} · credits ${esc(d.entry.credits_used ?? "?")}</div>
      <div>Crustdata request ID</div><div class="mono">${esc(d.entry.upstream_request_id)}</div>
      <div>Retrieved</div><div>${esc(d.entry.ts)}</div>
      <div>Response hash</div><div class="mono">${esc(d.entry.response_hash)}</div>
      <div>Ledger entry hash</div><div class="mono">${esc(d.entry.entry_hash)}</div>
      <div>Previous entry</div><div class="mono">${esc(d.entry.prev_hash)}</div>
    </div><b>Request sent to Crustdata</b><pre class="json">${esc(JSON.stringify(d.entry.request, null, 1))}</pre>`;
  $("#modal").classList.remove("hidden");
}
$("#modal-close").onclick = () => $("#modal").classList.add("hidden");
$("#modal").onclick = e => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); };
const factify = (text, runId) => esc(text).replace(/\[(F\d+)\]/g, (_, f) => `<button class="fact" onclick="openFact('${runId}','${f}')">${f}</button>`);

// ------------------------------------------------------------ board
const STAGES = ["Needs analyst", "Partner meeting", "Awaiting founder info", "Passed"];
async function loadBoard() {
  const deals = await api("/api/board");
  if (!deals.length) { $("#board").innerHTML = `<div class="empty card">No deals yet. Scout a round or check a pitch.</div>`; return; }
  $("#board").innerHTML = STAGES.map(stage => {
    const ds = deals.filter(d => (d.stage || "Needs analyst") === stage);
    return `<div class="col"><h4>${stage}<span class="muted">${ds.length}</span></h4>${ds.map(d => `
      <div class="deal"><b>${esc(d.name)}</b><span class="muted small">${esc(d.domain || "")}</span>
        <div class="meta">${chip(d.source === "pitch" ? "inbound pitch" : `round ${d.round_no}`, "UNVERIFIABLE")}
          ${d.agent_recommendation ? chip("agent: " + d.agent_recommendation, d.agent_recommendation) : ""}
          ${d.agent_probability != null ? `<span class="small muted">p(pick) ${pct(d.agent_probability)}</span>` : ""}
          ${d.human_decision ? chip("you: " + d.human_decision, d.human_decision) : ""}</div></div>`).join("")}</div>`;
  }).join("");
}

// ------------------------------------------------------------ scout & decide
let rounds = [], activeRound = null;
async function loadRounds(selectRunId) {
  rounds = await api("/api/rounds");
  if (!rounds.length) { $("#round-tabs").innerHTML = ""; $("#round-view").innerHTML = `<div class="empty card">No rounds yet. Click “Scout a new round”.</div>`; return; }
  activeRound = rounds.find(r => r.run_id === selectRunId) || rounds.find(r => r.run_id === activeRound?.run_id) || rounds[0];
  $("#round-tabs").innerHTML = rounds.map(r => `<button class="${r.run_id === activeRound.run_id ? "on" : ""}" data-run="${r.run_id}">Round ${r.round_no} ${r.decided_by ? "✓" : "· awaiting you"}</button>`).join("");
  document.querySelectorAll("#round-tabs button").forEach(b => b.onclick = () => { activeRound = rounds.find(r => r.run_id === b.dataset.run); loadRounds(activeRound.run_id); });
  activeRound.decided_by ? renderDecided(activeRound) : renderRound(activeRound);
}

async function renderRound(r) {
  const run = await api(`/api/run/${r.run_id}`);
  const m = run.meta.model;
  $("#round-view").innerHTML = `
    <div class="banner info"><div class="big">${run.candidates.length}</div><div><b>Round ${r.round_no}: companies matching your thesis, newest fundraises first.</b><br>
      <span class="small">The agent has learned from <b>${m.n_decisions}</b> of your decisions. Its predictions were sealed in the signed ledger before you see this page.
      <label style="margin-left:10px"><input type="checkbox" id="reveal"> reveal the agent's sealed prediction (pick blind for a fair score)</label></span></div></div>
    ${thesisBox(run.meta)}
    <div class="card" style="padding:0"><table><thead><tr><th>Pick</th><th>Company</th><th>Team</th><th>Growth YoY</th><th>Last round</th><th>Open roles (eng)</th>${run.candidates.some(c => "founders" in c.raw) ? "<th>Founders (people graph)</th>" : ""}<th class="agentcol">Agent prediction</th><th class="agentcol">Why</th></tr></thead><tbody>
    ${run.candidates.map(c => {
      const x = c.raw, refs = c.refs, F = k => refs[k] ? ` <button class="fact" onclick="openFact('${r.run_id}','${refs[k]}')">${refs[k]}</button>` : "";
      return `<tr><td><input type="checkbox" class="pick" value="${c.n}"></td>
        <td><b>${c.n}. ${esc(c.name)}</b><br><span class="small muted">${esc(c.domain || "")}</span></td>
        <td>${x.headcount != null ? x.headcount.toLocaleString() : "n/a"}${F("headcount_total")}</td>
        <td>${x.growth_excluded ? `<span class="small muted">excluded: unstable data</span>` : x.growth_yoy != null ? `${x.growth_yoy > 0 ? "+" : ""}${Math.round(x.growth_yoy)}%` : "n/a"}${x.growth_excluded ? "" : F("growth_yoy")}</td>
        <td>${esc((x.last_round_type || "n/a").replace("_", " "))}<br><span class="small muted">${esc(x.last_fundraise_date || "")}</span>${F("last_round_type")}</td>
        <td>${x.open_roles ?? 0} (${x.eng_roles ?? 0})${F("job_buckets")}${x.identity_collision ? `<br>${chip("⚠ possible merged record", "CONTRADICTED")}` : ""}</td>
        ${"founders" in x ? `<td class="small">${founderCell(x.founders)}${F("founders")}</td>` : ""}
        <td class="agentcol hiddencol">${chip(c.predicted_pick ? "predicts pick" : "predicts reject", c.predicted_pick ? "pick" : "reject")}<br>
          <span class="small">p ${pct(c.probability)} · ${chip(c.recommendation)}</span><br><span class="small muted">${c.auto_act ? "acted alone" : "queued for you"}</span></td>
        <td class="agentcol hiddencol small">${esc((c.why || []).join(", "))}<br><span class="muted">${esc(c.rule)}</span></td></tr>`;
    }).join("")}</tbody></table></div>
    <div class="row"><span class="muted small">Everything you don't pick is recorded as a reject. The agent then executes your decisions: board moves and drafted intro emails.</span>
      <button class="primary" id="btn-decide">Submit my picks</button></div>`;
  $("#reveal").onchange = e => document.querySelectorAll(".agentcol").forEach(td => td.classList.toggle("hiddencol", !e.target.checked));
  $("#btn-decide").onclick = async () => {
    const picks = [...document.querySelectorAll(".pick:checked")].map(i => +i.value);
    if (!picks.length) return alert("Pick at least one company you would take forward.");
    try { await runJob(`Recording your picks for round ${r.round_no}`, "/api/decide", {round_no: r.round_no, picks}); await loadRounds(r.run_id); }
    catch (e) { alert(e.message); }
  };
}

function founderCell(f) {
  if (!f) return "<span class='muted'>none listed</span>";
  if (!f.verified.length) return `<span class="muted">${f.listed} listed, none verified here</span>`;
  const tags = [];
  if (f.technical) tags.push(chip("technical", "VERIFIED"));
  if (f.repeat_founder) tags.push(chip("repeat founder", "VERIFIED"));
  if (f.big_tech.length) tags.push(chip("ex-" + f.big_tech.slice(0, 2).join("/"), "VERIFIED"));
  return `${f.verified.slice(0, 3).map(v => `<b>${esc(v.name)}</b>`).join(", ")}<br><span class="muted">${f.verified.length} of ${f.listed} listed verified</span><br>${tags.join(" ")}`;
}

function thesisBox(meta) {
  const t = meta.thesis, tr = meta.thesis_request;
  if (!t && !tr) return "";
  const f = [];
  if (t) {
    f.push(...(t.sectors || []).map(x => `industry: ${x}`), ...(t.hq_countries || []).map(x => `HQ: ${x}`),
      `team ${t.headcount[0]}–${t.headcount[1]}`, ...(t.last_round || []).map(x => `round: ${x.replace("_", " ")}`));
    if (t.raised_since) f.push(`raised since ${t.raised_since}`);
    (t.description_keywords || []).forEach(k => f.push(`mentions “${k}”`));
  }
  return `<div class="card"><b>${tr ? `Your thesis: “${esc(tr.text)}”` : "Rulebook thesis"}</b>
    ${tr ? `<span class="small muted"> · interpreted by ${esc(tr.model)}</span>` : ""}
    <div class="filters">${f.map(x => chip(x, "VERIFIED")).join("")}</div>
    ${(meta.relaxed || []).length ? `<div class="filters">${meta.relaxed.map(x => chip("relaxed: " + x, "PARTIAL")).join("")}</div>` : ""}
    ${tr && tr.unmapped.length ? `<div class="filters">${tr.unmapped.map(x => chip("not a filter: " + x, "UNVERIFIABLE")).join("")}</div>` : ""}</div>`;
}

async function renderDecided(r) {
  const run = await api(`/api/run/${r.decided_by}`);
  const m = run.meta, a = m.agreement;
  const emails = run.actions.filter(x => x.action === "draft_email_to_outbox");
  const moves = run.actions.filter(x => x.action === "update_deal_board");
  $("#round-view").innerHTML = `
    <div class="grid2">
      <div class="banner ${a.accuracy >= 0.7 ? "ok" : "warn"}"><div class="big">${a.decisions_matched}/${a.total}</div>
        <div><b>The agent's sealed predictions matched your decisions.</b><br><span class="small">You picked ${a.top_k_overlap} of its top ${a.top_k}.
          ${a.brier != null ? `Calibration (Brier) <b>${a.brier.toFixed(3)}</b>, lower is better; 0.25 = coin flip. ` : ""}Scored against predictions sealed in <span class="mono">${esc(m.scout_run_id)}</span> before you decided.</span></div></div>
      <div class="banner info"><div class="big">${moves.length + emails.length}</div><div><b>Actions executed</b><br><span class="small">${moves.length} deal-board moves · ${emails.length} intro emails drafted to the outbox (not sent)</span></div></div>
    </div>
    <div class="card" style="padding:0"><table><thead><tr><th>#</th><th>Company</th><th>Agent predicted</th><th>You decided</th><th>Agent p(pick)</th><th>Final action</th></tr></thead><tbody>
      ${m.decisions.map(d => `<tr><td>${d.n}</td><td><b>${esc(d.name)}</b></td>
        <td>${chip(d.predicted_pick ? "pick" : "reject")}</td><td>${chip(d.picked ? "pick" : "reject")} ${d.predicted_pick === d.picked ? "✅" : "✗"}</td>
        <td>${pct(d.probability)}</td><td class="small">${d.picked ? "→ Partner meeting · intro email drafted" : "→ Passed"}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="card"><h3>What it learned from this round</h3><ul>${m.learned.map(l => `<li>${esc(l)}</li>`).join("")}</ul>
      <div class="row gap"><button class="primary" onclick="document.getElementById('btn-scout').click()">Scout the next round with what it learned</button>
      <button onclick="show('outbox')">See drafted emails</button><button onclick="show('board')">See deal board</button></div></div>`;
}

$("#btn-scout").onclick = async () => {
  const thesis = $("#thesis-text").value.trim();
  try { const runId = await runJob(thesis ? "Interpreting your thesis and scouting" : "Scouting a new round", "/api/scout", {n: +$("#scout-n").value || 10, thesis: thesis || null}); await loadRounds(runId); }
  catch (e) { alert(e.message); }
};

// ------------------------------------------------------------ pitch
async function loadExamples() {
  if ($("#examples").dataset.loaded) return;
  const ex = await api("/api/fixtures");
  $("#examples").innerHTML = `<span class="small muted">Examples (team-written test pitches; some contain planted false claims):</span>` +
    ex.map((e, i) => `<button data-i="${i}">${esc(e.name)}</button>`).join("");
  document.querySelectorAll("#examples button").forEach(b => b.onclick = () => { $("#pitch-text").value = ex[+b.dataset.i].text; });
  $("#examples").dataset.loaded = 1;
}
$("#btn-pitch").onclick = async () => {
  try {
    const runId = await runJob("Running diligence on the pitch", "/api/pitch", {text: $("#pitch-text").value, domain: $("#pitch-domain").value});
    renderPitch(runId);
  } catch (e) { alert(e.message); }
};
async function renderPitch(runId) {
  const run = await api(`/api/run/${runId}`);
  const m = run.meta, res = m.resolution, d = m.decision || {};
  const counts = {}; run.claims.forEach(c => counts[c.status] = (counts[c.status] || 0) + 1);
  const outbox = await api("/api/outbox");
  const email = outbox.find(o => o.run === runId);
  const bannerCls = {ADVANCE: "ok", REQUEST_INFO: "warn", PASS: "bad", NEEDS_HUMAN: "warn"}[d.decision] || "info";
  $("#pitch-result").innerHTML = `
    <div class="banner ${bannerCls}"><div class="big">${esc(d.decision || "")}</div><div>
      <b>${res.status === "RESOLVED" ? `${esc(res.name)} (${esc(res.domain)}) · Crustdata ID ${res.company_id}` : `Company ${esc(res.status)}: the agent will not guess`}</b><br>
      <span class="small">${esc(d.rule || "")}</span></div></div>
    <div class="card"><h3>How the company was identified</h3><div class="small">${esc(res.rationale)}</div>
      ${res.candidates?.length ? `<div class="steps">${res.candidates.slice(0, 5).map(c => `<span>${esc(c.name)} · ${esc(c.domain || "no domain")} · score ${c.score}</span>`).join("")}</div>` : ""}
      ${run.decisions.filter(x => /person/.test(x.question)).map(x => `<div class="small" style="margin-top:6px">👤 ${esc(x.question)} → <b>${esc(x.status)}</b>: ${esc(x.rationale)}</div>`).join("")}</div>
    <div class="card" style="padding:0"><table><thead><tr><th>#</th><th>Claim in the pitch</th><th>Verdict</th><th>Evidence (click a fact for its receipt)</th></tr></thead><tbody>
      ${run.claims.map(c => `<tr><td>${c.claim_id}</td><td>${esc(c.text)}</td><td>${chip(c.status)}</td><td>${factify(c.explanation, runId)}</td></tr>`).join("")}
    </tbody></table></div>
    <div class="grid2">
      <div class="card"><h3>Final actions taken</h3>${run.actions.map(x => `<div class="small">✔ <b>${esc(x.action)}</b>${x.fields?.stage ? ` → ${esc(x.fields.stage)}` : ""}${x.path ? ` → ${esc(x.path)}` : ""}<br><span class="muted">allowed by: ${esc(x.allowed_by || x.reason)}</span></div>`).join("<br>") || "<span class='muted'>none</span>"}</div>
      <div class="card"><h3>Drafted email (not sent)</h3>${email ? `<div class="small"><b>${esc(email.subject)}</b></div><div class="email">${esc(email.body)}</div>` : "<span class='muted'>No email for this decision.</span>"}</div>
    </div>
    <div class="row gap"><button onclick="verifyRun('${runId}', true)">Verify this run (with Crustdata witness)</button><span class="small muted">${run.calls.length} Crustdata calls · ${run.entry_count} signed ledger entries · head ${esc(run.head_hash.slice(0, 22))}…</span></div>`;
}

// ------------------------------------------------------------ learned
async function loadLearned() {
  const L = await api("/api/learned");
  const feats = Object.keys(L.prior);
  const lim = 3, pos = v => 50 + Math.max(-lim, Math.min(lim, v)) / lim * 50;
  const seg = (v, cls) => { const a = pos(0), b = pos(v); return `<i class="${cls}" style="left:${Math.min(a, b)}%;width:${Math.abs(b - a)}%"></i>`; };
  const remaining = Math.max(0, L.autonomy.min_decisions_before_auto_act - L.model.n_decisions);
  $("#learned").innerHTML = `
    <div class="grid2">
      <div class="banner ${remaining ? "warn" : "ok"}"><div class="big">${L.model.n_decisions}</div><div><b>decisions learned from</b> (${L.model.n_picks} picks)<br>
        <span class="small">${remaining ? `The agent defers to you until it has ${L.autonomy.min_decisions_before_auto_act} decisions (${remaining} to go), and always below ${pct(L.autonomy.auto_act_if_confidence)} confidence.` : `Autonomy unlocked: it acts alone when ≥ ${pct(L.autonomy.auto_act_if_confidence)} confident, and queues everything else for you.`}</span></div></div>
      <div class="card"><h3>Agreement with you, round by round</h3>${L.history.length ? L.history.map(h => `
        <div class="small">Round ${h.round_no}: <b>${h.decisions_matched}/${h.total}</b> decisions matched · you picked ${h.top_k_overlap} of its top ${h.top_k}${h.brier != null ? ` · calibration ${h.brier.toFixed(3)}` : ""}</div>
        <div class="bar" style="margin:4px 0 10px"><i style="width:${100 * h.decisions_matched / h.total}%"></i></div>`).join("") : "<span class='muted'>No decided rounds yet.</span>"}</div>
    </div>
    <div class="card"><h3>In plain words</h3>${L.summary.length ? `<ul>${L.summary.map(s => `<li>${esc(s)}</li>`).join("")}</ul>` : "<span class='muted'>Ranking purely by the stated thesis until you decide a round.</span>"}</div>
    <div class="card"><h3>Preference weights: stated thesis (grey) vs learned now (blue)</h3><table><tbody>
      ${feats.map(f => `<tr><td style="width:240px">${esc(f.replace(/_/g, " "))}</td><td style="width:90px" class="small">${(+L.prior[f]).toFixed(2)} → <b>${(+L.model.weights[f]).toFixed(2)}</b></td>
        <td><div class="wbar"><span class="mid"></span>${seg(+L.prior[f], "prior")}${seg(+L.model.weights[f], "now")}</div></td></tr>`).join("")}
    </tbody></table><div class="small muted">Left of centre: you prefer less of it. Right: more. Bounded by the rulebook's weight limits.</div></div>`;
}

// ------------------------------------------------------------ outbox
async function loadOutbox() {
  const mails = await api("/api/outbox");
  $("#outbox").innerHTML = mails.length ? mails.map(m => `<div class="card"><div class="row"><b>${esc(m.subject)}</b>${chip("DRAFT · not sent", "UNVERIFIABLE")}</div>
    <div class="small muted">${esc(m.to)} · from run <span class="mono">${esc(m.run)}</span></div><div class="email" style="margin-top:8px">${esc(m.body)}</div></div>`).join("")
    : `<div class="empty card">No drafted emails yet.</div>`;
}

// ------------------------------------------------------------ audit
async function loadAudit() {
  const runs = await api("/api/runs");
  $("#audit").innerHTML = `<div class="card" style="padding:0"><table><thead><tr><th>Run</th><th>What</th><th>When</th><th></th></tr></thead><tbody>
    ${runs.map(r => `<tr><td class="mono">${esc(r.run_id)}</td><td>${esc(r.title)} ${r.decision ? chip(r.decision) : ""}</td>
      <td class="small">${new Date(r.mtime * 1000).toLocaleTimeString()}</td>
      <td style="white-space:nowrap"><button onclick="verifyRun('${r.run_id}', false)">Verify</button>
        <button onclick="verifyRun('${r.run_id}', true)">+ witness</button>
        <button class="danger" onclick="tamperDemo('${r.run_id}')">Tamper test</button></td></tr>`).join("")}
  </tbody></table></div>`;
}
async function verifyRun(runId, witness) {
  try { await runJob(`Verifying ${runId}${witness ? " (with Crustdata usage-log witness)" : ""}`, "/api/verify", {run_id: runId, witness}); }
  catch (e) { alert(e.message); }
}
async function tamperDemo(runId) {
  try { await runJob(`Tamper test on a copy of ${runId}`, "/api/tamper-demo", {run_id: runId}); }
  catch (e) { alert(e.message); }
}

// ------------------------------------------------------------ rules
async function loadRules() {
  const {rules: R, text} = await api("/api/strategy");
  const list = xs => (xs || []).map(x => `<span class="chip UNVERIFIABLE">${esc(x)}</span>`).join(" ");
  $("#rules").innerHTML = `
    <div class="grid2">
      <div class="card"><h3>Thesis (hard filters)</h3><div class="kv">
        <div>Sectors</div><div>${list(R.thesis.sectors)}</div><div>HQ countries</div><div>${list(R.thesis.hq_countries)}</div>
        <div>Headcount</div><div>${R.thesis.headcount.join(" – ")}</div><div>Last round</div><div>${list(R.thesis.last_round)}</div>
        <div>Raised since</div><div>${esc(R.thesis.raised_since || "any")}</div></div></div>
      <div class="card"><h3>Claim tolerances (± margins)</h3><div class="kv">
        <div>Headcount</div><div>±${R.tolerances.headcount.verified}% verified · ±${R.tolerances.headcount.partial}% partial</div>
        <div>Total funding</div><div>±${R.tolerances.total_funding.verified}% · ±${R.tolerances.total_funding.partial}%</div>
        <div>Round amount</div><div>±${R.tolerances.round_amount}%</div>
        <div>Unstable data</div><div>week-on-week swing &gt; ${R.tolerances.unstable_series_swing}% → never held against the company</div></div></div>
      <div class="card"><h3>Guardrails (learning cannot override)</h3><div class="kv">
        <div>Pass if</div><div>≥ ${R.guardrails.pass_if_contradictions} contradicted claims</div>
        <div>Block ADVANCE if</div><div>${list(R.guardrails.block_advance_if_contradicted)} contradicted</div>
        <div>Ambiguous entity</div><div>${esc(R.guardrails.ambiguous_entity)}</div>
        <div>Decision thresholds</div><div>ADVANCE ≥ ${pct(R.decision_thresholds.advance_at_or_above)} · PASS ≤ ${pct(R.decision_thresholds.pass_at_or_below)}</div></div></div>
      <div class="card"><h3>Autonomy &amp; actions</h3><div class="kv">
        <div>Acts alone when</div><div>confidence ≥ ${pct(R.autonomy.auto_act_if_confidence)} and ≥ ${R.autonomy.min_decisions_before_auto_act} of your decisions learned</div>
        <div>Allowed</div><div>${R.actions.allowed.map(a => chip(a, "VERIFIED")).join(" ")}</div>
        <div>Forbidden</div><div>${R.actions.forbidden.map(a => chip(a, "CONTRADICTED")).join(" ")}</div></div></div>
    </div>
    <details class="card"><summary>Full STRATEGY.md (sealed into every run)</summary><pre class="json">${esc(text)}</pre></details>`;
}

show("board");
