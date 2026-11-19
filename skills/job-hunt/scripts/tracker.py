#!/usr/bin/env python3
"""The application tracker: one CSV row per posting, plus a local HTML dashboard built from it.

Usage:
    python tracker.py upsert --data DATA --url URL [--set status=applied --set date_applied=2026-11-20 ...]
    python tracker.py dashboard --data DATA [--out DATA/dashboard.html] [--open]

upsert     Finds the row for URL (or adds one) and sets the given columns. Old CSVs gain any new columns.
           A copy of the previous file is kept as applications.csv.bak.
dashboard  Writes one self-contained HTML file (no server, no network): pipeline cards, a funnel, applications
           per week, follow-ups that are due, and a sortable, filterable table. Rows with an app_folder pick up
           fit (fit.json) and screening results (ats_report.json) from DATA/applications/<app_folder>/.
Status values: shortlisted, tailoring, ready, applied, screening, interview, rejected, closed, skipped, withdrawn.
Tracker layout inspired by career-ops (MIT, github.com/career-ops-hq/career-ops).
"""
import argparse
import csv
import json
import os
import shutil
import sys
import webbrowser
from datetime import date, timedelta

COLUMNS = ["date_applied", "company", "role", "location", "url", "first_published", "fit_score", "resume_file",
           "status", "referral_or_outreach", "next_step", "next_step_date", "notes", "date_added", "app_folder"]
STATUSES = ["shortlisted", "tailoring", "ready", "applied", "screening", "interview",
            "rejected", "closed", "skipped", "withdrawn"]
ACTIVE = {"shortlisted", "tailoring", "ready", "applied", "screening", "interview"}
SENT = {"applied", "screening", "interview", "rejected"}  # reached the employer
CALLED = {"screening", "interview"}                       # recruiter screen or interview = an interview call


def read_rows(path):
    if not os.path.isfile(path):
        return [], list(COLUMNS)
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        rows = [dict(x) for x in r]
        cols = list(r.fieldnames or [])
    return rows, cols + [c for c in COLUMNS if c not in cols]


def upsert(path, url, values, today=None):
    bad = [k for k in values if k not in COLUMNS]
    if bad:
        raise ValueError(f"unknown columns: {bad}")
    if values.get("status") and values["status"] not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    rows, cols = read_rows(path)
    row = next((r for r in rows if r.get("url") == url), None)
    if row is None:
        row = {c: "" for c in cols}
        row.update(url=url, date_added=str(today or date.today()))
        rows.append(row)
    row.update({k: str(v) for k, v in values.items()})
    if os.path.isfile(path):
        shutil.copyfile(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows({c: r.get(c, "") or "" for c in cols} for r in rows)
    os.replace(tmp, path)
    return row


def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def collect(data, today=None):
    """Tracker rows (last row per url wins) enriched from each application folder."""
    today = today or date.today()
    rows, _ = read_rows(os.path.join(data, "applications.csv"))
    by = {}
    for r in rows:
        by[r.get("url") or f"_row{len(by)}"] = r
    out = []
    for r in by.values():
        r = {k: (v or "").strip() for k, v in r.items() if k}
        r["status"] = (r.get("status") or "shortlisted").lower()
        folder = os.path.basename(r.get("app_folder", ""))  # a folder name, never a path
        if folder:
            app = os.path.join(data, "applications", folder)
            fit, ats = _json(os.path.join(app, "fit.json")), _json(os.path.join(app, "ats_report.json"))
            if fit.get("score") is not None and not r.get("fit_score"):
                r["fit_score"] = str(fit["score"])
            r["fit_call"] = fit.get("decision", "")
            r["ats_coverage"] = "" if ats.get("coverage") is None else str(ats["coverage"])
            r["parse_score"] = "" if ats.get("parse_score") is None else str(ats["parse_score"])
        due = r.get("next_step_date", "")
        r["followup"] = ""
        if due and r["status"] in ACTIVE:
            try:
                d = date.fromisoformat(due)
                r["followup"] = "overdue" if d < today else ("due" if d <= today + timedelta(days=2) else "")
            except ValueError:
                pass
        r["url"] = r.get("url", "") if r.get("url", "").startswith(("http://", "https://")) else ""
        out.append(r)
    return out


def stats(rows, today=None):
    today = today or date.today()
    num = lambda k: [float(r[k]) for r in rows if _isnum(r.get(k))]  # noqa: E731
    sent = [r for r in rows if r["status"] in SENT]
    called = [r for r in rows if r["status"] in CALLED]
    fits, cov = num("fit_score"), num("ats_coverage")
    weeks = {(today - timedelta(days=today.weekday() + 7 * i)).isoformat(): 0 for i in range(7, -1, -1)}
    for r in sent:
        try:
            d = date.fromisoformat(r.get("date_applied", ""))
        except ValueError:
            continue
        wk = (d - timedelta(days=d.weekday())).isoformat()
        if wk in weeks:
            weeks[wk] += 1
    return {
        "in_pipeline": sum(r["status"] in ACTIVE - SENT for r in rows),
        "applied": len(sent),
        "calls": len(called),
        "call_rate": round(100 * len(called) / len(sent)) if sent else None,
        "avg_fit": round(sum(fits) / len(fits), 1) if fits else None,
        "avg_coverage": round(sum(cov) / len(cov)) if cov else None,
        "followups": sum(bool(r["followup"]) for r in rows),
        "funnel": {s: sum(r["status"] == s for r in rows) for s in STATUSES},
        "weeks": weeks,
    }


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>Job search tracker</title>
<style>
:root{--bg:#f6f7fb;--card:#fff;--ink:#1d2433;--mute:#6b7385;--line:#e5e8f0;--navy:#1f3864;--blue:#4a90d9}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--ink)}
header{padding:24px 32px 8px}h1{margin:0;font-size:22px;color:var(--navy)}header p{margin:4px 0 0;color:var(--mute)}
main{padding:8px 32px 40px;max-width:1400px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:12px 0 20px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.card b{display:block;font-size:26px;color:var(--navy)}.card span{color:var(--mute);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.row{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}@media(max-width:900px){.row{grid-template-columns:1fr}}
.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}.panel h2{margin:0 0 10px;font-size:14px;color:var(--navy)}
.bar{display:flex;align-items:center;gap:8px;margin:5px 0}.bar label{width:96px;color:var(--mute);font-size:12px}
.bar div{height:16px;border-radius:4px;background:var(--blue);min-width:2px}.bar em{font-style:normal;font-size:12px;color:var(--mute)}
.tools{display:flex;gap:8px;margin:0 0 10px;flex-wrap:wrap;align-items:center}
.tools input,.tools select{padding:7px 10px;border:1px solid var(--line);border-radius:8px;font:inherit}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line)}
th,td{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:#eef1f8;font-size:12px;color:var(--mute);cursor:pointer;user-select:none;white-space:nowrap}
td.num{text-align:right;font-variant-numeric:tabular-nums}a{color:var(--blue);text-decoration:none}a:hover{text-decoration:underline}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:600;background:#eef1f8;color:var(--navy)}
.s-applied{background:#e3efff;color:#1d5fb8}.s-screening,.s-interview{background:#dff5e6;color:#1d7a43}
.s-rejected,.s-closed,.s-withdrawn{background:#f6e3e3;color:#a33}.s-skipped{background:#eee;color:#777}
.s-ready{background:#fff3d6;color:#8a6100}.s-tailoring,.s-shortlisted{background:#efe8ff;color:#5b3fb5}
.nw{white-space:nowrap}.due{color:#8a6100;font-weight:600}.overdue{color:#a33;font-weight:600}.mute{color:var(--mute)}
</style></head><body>
<header><h1>Job search tracker</h1><p id="sub"></p></header>
<main>
<section class="cards" id="cards"></section>
<section class="row"><div class="panel"><h2>Funnel</h2><div id="funnel"></div></div>
<div class="panel"><h2>Applications per week</h2><div id="weeks"></div></div></section>
<div class="tools"><input id="q" placeholder="Filter company, role, notes" size="32">
<select id="st"><option value="">All statuses</option></select>
<label class="mute"><input type="checkbox" id="due"> follow-ups only</label></div>
<table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent),S=D.stats,$=id=>document.getElementById(id);
const el=(t,a={},...k)=>{const e=document.createElement(t);for(const[x,v]of Object.entries(a))x==='text'?e.textContent=v:e.setAttribute(x,v);k.forEach(c=>e.append(c));return e};
$('sub').textContent='Generated '+D.generated+' from applications.csv · '+D.rows.length+' postings';
const dash=(v,s='')=>v==null?'–':v+s;
[['In pipeline',S.in_pipeline],['Applied',S.applied],['Interview calls',S.calls],['Call rate',dash(S.call_rate,'%')],
 ['Avg fit',dash(S.avg_fit,' / 5')],['Avg keyword coverage',dash(S.avg_coverage,'%')],['Follow-ups due',S.followups]]
 .forEach(([l,v])=>$('cards').append(el('div',{class:'card'},el('b',{text:String(v)}),el('span',{text:l}))));
const bars=(id,obj)=>{const m=Math.max(1,...Object.values(obj));for(const[k,v]of Object.entries(obj)){const d=el('div');d.style.width=(v/m*70)+'%';
 $(id).append(el('div',{class:'bar'},el('label',{text:k}),d,el('em',{text:String(v)})))}};
bars('funnel',S.funnel);bars('weeks',Object.fromEntries(Object.entries(S.weeks).map(([k,v])=>['wk of '+k.slice(5),v])));
const cols=[['company','Company'],['role','Role'],['status','Status'],['fit_score','Fit'],['fit_call','Call'],['ats_coverage','Keywords %'],
 ['parse_score','Parse'],['date_applied','Applied'],['location','Location'],['next_step','Next step'],['next_step_date','When'],['notes','Notes']];
const num=new Set(['fit_score','ats_coverage','parse_score']);let sk='date_applied',dir=-1;
cols.forEach(([k,l])=>{const th=el('th',{text:l});th.onclick=()=>{dir=sk===k?-dir:1;sk=k;draw()};$('head').append(th)});
D.statuses.forEach(s=>$('st').append(el('option',{value:s,text:s})));
['q','st','due'].forEach(i=>$(i).oninput=draw);
function draw(){const q=$('q').value.toLowerCase(),st=$('st').value,du=$('due').checked;$('body').replaceChildren();
 D.rows.filter(r=>(!st||r.status===st)&&(!du||r.followup)&&(!q||[r.company,r.role,r.notes,r.location].join(' ').toLowerCase().includes(q)))
 .sort((a,c)=>{let x=a[sk]||'',y=c[sk]||'';if(num.has(sk)){x=parseFloat(x)||-1;y=parseFloat(y)||-1}return(x>y?1:x<y?-1:0)*dir})
 .forEach(r=>{const tr=el('tr');cols.forEach(([k])=>{const td=el('td'),v=r[k]||'';
  if(k==='role'&&r.url)td.append(el('a',{href:r.url,target:'_blank',rel:'noopener noreferrer',text:v||'posting'}));
  else if(k==='status')td.append(el('span',{class:'pill s-'+v.replace(/[^a-z]/g,''),text:v}));
  else{td.textContent=v;if(num.has(k))td.className='num';if(/date/.test(k))td.className='nw '+(k==='next_step_date'&&r.followup||'')}
  tr.append(td)});$('body').append(tr)})}
draw();
</script></body></html>
"""


def render(rows, today=None):
    today = today or date.today()
    payload = {"generated": today.isoformat(), "statuses": STATUSES, "stats": stats(rows, today), "rows": rows}
    # Escape <, > and & so nothing in the data can close the <script> block; JSON.parse restores them.
    blob = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return PAGE.replace("__DATA__", blob)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("upsert")
    u.add_argument("--data", required=True)
    u.add_argument("--url", required=True)
    u.add_argument("--set", action="append", default=[], metavar="COLUMN=VALUE")
    d = sub.add_parser("dashboard")
    d.add_argument("--data", required=True)
    d.add_argument("--out")
    d.add_argument("--open", action="store_true")
    a = ap.parse_args()
    if a.cmd == "upsert":
        vals = {}
        for kv in a.set:
            if "=" not in kv:
                sys.exit(f"--set expects COLUMN=VALUE, got {kv!r}")
            k, v = kv.split("=", 1)
            vals[k.strip()] = v.strip()
        try:
            row = upsert(os.path.join(a.data, "applications.csv"), a.url, vals)
        except ValueError as e:
            sys.exit(f"ERROR: {e}")
        print(f"{row.get('company') or a.url}: {row.get('status') or '(no status)'}")
        return
    out = a.out or os.path.join(a.data, "dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(render(collect(a.data)))
    print(out)
    if a.open:
        webbrowser.open("file://" + os.path.abspath(out))


if __name__ == "__main__":
    main()
