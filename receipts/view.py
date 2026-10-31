"""Static HTML viewer for a run: the report on the left; click any fact to see its receipt
(ledger entry, request, X-Request-ID, hashes) and the raw API JSON at the cited pointer."""

import html
import json
from pathlib import Path

import markdown

from .facts import load_facts
from .ledger import read_blob, read_ledger, verify_signature

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Receipts · {run_id}</title>
<style>
body{{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:#1d2433;display:flex;height:100vh}}
#report{{flex:1.25;overflow:auto;padding:24px 32px;border-right:1px solid #e3e6ec}}
#receipt{{flex:1;overflow:auto;padding:24px;background:#f7f8fa}}
table{{border-collapse:collapse;margin:8px 0;font-size:13px}} td,th{{border:1px solid #e3e6ec;padding:4px 8px;vertical-align:top}}
th{{background:#f1f3f6}} a[href^="#f"]{{background:#e8f0fe;color:#1a56db;padding:0 4px;border-radius:4px;text-decoration:none;font-weight:600}}
pre{{background:#fff;border:1px solid #e3e6ec;padding:10px;border-radius:6px;overflow:auto;font-size:12px;max-height:55vh}}
.hl{{background:#fff3c4}} .ok{{color:#0a7d33;font-weight:600}} .bad{{color:#b42318;font-weight:600}} code{{font-size:12px}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;background:#eef1f5;margin-right:6px;font-size:12px}}
</style></head><body>
<div id="report"><div class="badge">run {run_id}</div><div class="badge {sig_class}">{sig_text}</div>{report}</div>
<div id="receipt"><h3>Receipt</h3><p>Click any highlighted fact (F1, F2, …) in the report to see where it came from.</p></div>
<script>
const FACTS = {facts};
const ENTRIES = {entries};
const BLOBS = {blobs};
function show(fid) {{
  const f = FACTS[fid]; if (!f) return;
  const e = ENTRIES[f.receipt_seq] || {{}};
  const blob = BLOBS[f.receipt_seq];
  const esc = s => String(s).replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));
  let at = blob; for (const part of f.pointer.split('/').slice(1)) {{ if (at == null) break; at = at[part.replace(/~1/g,'/').replace(/~0/g,'~')]; }}
  const value = JSON.stringify(f.value, null, 1);
  const shown = value.length > 4000 ? value.slice(0, 4000) + '\\n…' : value;
  document.getElementById('receipt').innerHTML = `
    <h3>${{fid}} · ${{esc(f.label)}}</h3>
    <p><b>Value</b></p><pre class="hl">${{esc(shown)}}</pre>
    <p><b>JSON pointer</b> <code>${{esc(f.pointer)}}</code>, resolved inside the raw response of
       <b>receipt #${{f.receipt_seq}}</b>. ${{JSON.stringify(at) === JSON.stringify(f.value) ? '<span class="ok">✔ matches the raw bytes</span>' : '<span class="bad">✘ does not match</span>'}}</p>
    <p><b>Call</b> <code>POST ${{esc(e.endpoint || '')}}</code> · source ${{esc(e.source || '')}} · credits ${{esc(e.credits_used ?? '?')}}</p>
    <p><b>Crustdata X-Request-ID</b> <code>${{esc(e.upstream_request_id || '')}}</code> (checkable in Crustdata's usage log)</p>
    <p><b>Response hash</b> <code>${{esc(e.response_hash || '')}}</code><br><b>Ledger entry hash</b> <code>${{esc(e.entry_hash || '')}}</code><br>
       <b>Previous entry</b> <code>${{esc(e.prev_hash || '')}}</code></p>
    <p><b>Request body</b></p><pre>${{esc(JSON.stringify(e.request, null, 1))}}</pre>`;
}}
document.querySelectorAll('a[href^="#f"]').forEach(a => a.addEventListener('click', ev => {{
  ev.preventDefault(); show(a.getAttribute('href').slice(1).toUpperCase()); }}));
</script></body></html>"""


def build(run_dir: Path) -> Path:
    entries = read_ledger(run_dir)
    facts = load_facts(run_dir / "facts.json") if (run_dir / "facts.json").exists() else {}
    seqs = {f["receipt_seq"] for f in facts.values()}
    blobs = {}
    for e in entries:
        if e["seq"] in seqs and e.get("response_hash"):
            blobs[e["seq"]] = json.loads(read_blob(run_dir, e["response_hash"]))
    sealed = json.loads((run_dir / "head.sig").read_text(encoding="utf-8"))
    signed = verify_signature(sealed) and sealed["head_hash"] == entries[-1]["entry_hash"]
    report_html = markdown.markdown((run_dir / "report.md").read_text(encoding="utf-8"), extensions=["tables"])
    page = PAGE.format(
        run_id=html.escape(run_dir.name), report=report_html,
        sig_class="ok" if signed else "bad", sig_text="✔ signature valid" if signed else "✘ signature invalid",
        facts=_js(facts), entries=_js({e["seq"]: e for e in entries if e.get("type") == "tool_call"}), blobs=_js(blobs))
    out = run_dir / "view.html"
    out.write_text(page, encoding="utf-8")
    return out


def _js(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")
