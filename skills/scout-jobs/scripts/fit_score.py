#!/usr/bin/env python3
"""Turn a requirement-by-requirement fit assessment into a 1-5 score and an apply / consider / skip call.

Usage:
    python fit_score.py --master DATA/master_resume.yaml [--prefs DATA/job_preferences.yaml] FIT.yaml [FIT.yaml ...] \
        [--table DATA/scout/<date>-shortlist-scores.md]

Each FIT.yaml is written by the Scout (and refined by the Writer); see example-data/applications/example-gpm-ai/fit.yaml.
For each file the script writes <name>.json next to it and prints a short report; --table writes a ranked table.

The score is computed, not guessed, so it is the same every run and Tod can audit it:
  coverage   = sum(weight x credit) / sum(weight)      weight must 3, core 2, nice 1; credit proven 1, partly 0.5, missing 0
  global     = 0.6 x (1 + 4 x coverage) + 0.25 x role_fit + 0.15 x preferences_fit
  penalties  = 0.5 per missing must-have (max 1.5); 0.5 when the candidate is 2+ years short of a stated minimum
Bands: 4.0+ Apply, 3.0-3.9 Consider (only with a reason the candidate names), below 3.0 Skip.
A blocker (closed posting, sponsorship or citizenship conflict, or one the Scout lists) forces Skip.
The candidate always has the last word: `override: {decision: apply, reason: ...}`.
Rules borrowed from career-ops (MIT): a requirement weighted from market knowledge rather than the JD's own words
(`basis: inferred`) can never be a must-have, and the apply line is 4.0.
Requires: pyyaml
"""
import argparse
import json
import os
import re
import sys
from datetime import date

import yaml

WEIGHT = {"must": 3, "core": 2, "nice": 1}
CREDIT = {"proven": 1.0, "partly": 0.5, "missing": 0.0}
BASIS = {"stated", "structural", "inferred"}


def evidence_ids(master):
    ids = {b["id"] for co in master.get("experience") or [] for r in co.get("roles") or []
           for s in r.get("sections") or [] for b in s.get("bullets") or [] if b.get("id")}
    ids |= {r["id"] for co in master.get("experience") or [] for r in co.get("roles") or [] if r.get("id")}
    ids |= {a["id"] for a in master.get("confirmed_additions") or []
            if a.get("id") and a.get("status", "confirmed") in ("confirmed", "candidate-confirmed")}
    return ids


def _month(v):
    if v is None or str(v).lower() == "present":
        t = date.today()
        return t.year * 12 + t.month - 1
    y, m = str(v).split("-")[:2]
    return int(y) * 12 + int(m) - 1


def years_in_function(master, title_words):
    """Years in roles whose title contains one of title_words (overlaps counted once)."""
    if not title_words:
        return None
    spans = []
    for co in master.get("experience") or []:
        for r in co.get("roles") or []:
            if any(re.search(r"(?<![a-z])" + re.escape(w.lower()) + r"(?![a-z])", str(r.get("title", "")).lower())
                   for w in title_words):
                spans.append((_month(r["start"]), _month(r["end"]) + 1))
    total, end = 0, None
    for s, e in sorted(spans):
        if end is None or s >= end:
            total += e - s
            end = e
        elif e > end:
            total += e - end
            end = e
    return round(total / 12, 1)


def band(score):
    if score >= 4.0:
        return "Apply"
    if score >= 3.0:
        return "Consider"
    return "Skip"


def score_fit(fit, master, prefs=None, posting=None):
    errs, warns = [], []
    ids = evidence_ids(master)
    reqs = fit.get("requirements") or []
    if not reqs:
        errs.append("requirements: list the JD's requirements in its own order of emphasis")
    num = den = 0.0
    missing_must, gaps = [], []
    for i, r in enumerate(reqs):
        where = f"requirements[{i}] ({str(r.get('req', '?'))[:40]})"
        w, m, b = r.get("weight"), r.get("match"), r.get("basis", "stated")
        if w not in WEIGHT:
            errs.append(f"{where}: weight must be must, core or nice"); continue
        if m not in CREDIT:
            errs.append(f"{where}: match must be proven, partly or missing"); continue
        if b not in BASIS:
            errs.append(f"{where}: basis must be stated, structural or inferred")
        if b == "inferred" and w == "must":
            errs.append(f"{where}: an inferred requirement can't be a must-have; only the JD's own words make one")
        ev = r.get("evidence") or []
        unknown = [e for e in ev if e not in ids]
        if unknown:
            errs.append(f"{where}: evidence ids not in the master file: {unknown}")
        if m in ("proven", "partly") and not ev:
            errs.append(f"{where}: '{m}' needs evidence (bullet, role or confirmed_additions ids)")
        num += WEIGHT[w] * CREDIT[m]
        den += WEIGHT[w]
        if m == "missing" and w == "must":
            missing_must.append(r.get("req", ""))
        if m != "proven" and w in ("must", "core"):
            gaps.append({"req": r.get("req", ""), "weight": w, "match": m, "evidence": ev, "note": r.get("note", "")})
    for k in ("role_fit", "preferences_fit"):
        v = fit.get(k)
        if not isinstance(v, (int, float)) or not 1 <= v <= 5:
            errs.append(f"{k}: give a number from 1 to 5")
    if errs:
        return None, errs, warns

    coverage = num / den if den else 0.0
    raw = 0.6 * (1 + 4 * coverage) + 0.25 * fit["role_fit"] + 0.15 * fit["preferences_fit"]
    penalties = []
    if missing_must:
        penalties.append(("missing must-haves", min(1.5, 0.5 * len(missing_must))))
    risks = []
    title_words = (prefs or {}).get("function_titles")
    have = years_in_function(master, title_words)
    need = fit.get("min_years")
    if need is None and posting and posting.get("years_required"):
        need = max(y["years"] for y in posting["years_required"])
    if have is not None and need:
        short = float(need) - have
        if short > 0:
            risks.append(f"{have} years in {', '.join(title_words)}-titled roles vs {need} asked; screeners compute this")
        if short >= 2:
            penalties.append(("years short of the stated minimum", 0.5))
    score = round(max(1.0, min(5.0, raw - sum(p for _, p in penalties))), 1)

    blockers = list(fit.get("blockers") or [])
    if posting:
        if posting.get("status") == "closed":
            blockers.append(f"posting closed ({posting.get('reason', '')})")
        wa = posting.get("work_authorization") or {}
        if wa.get("blocker"):
            blockers.append(f"{wa.get('note')}: \"{(wa.get('evidence') or [''])[0][:140]}\"")
        elif wa.get("note"):
            risks.append(wa["note"])
    recommendation = "Skip" if blockers else band(score)
    decision, overridden = recommendation, False
    ov = fit.get("override") or {}
    if ov.get("decision"):
        if str(ov["decision"]).lower() not in ("apply", "skip"):
            errs.append("override.decision must be apply or skip")
            return None, errs, warns
        if not ov.get("reason"):
            warns.append("override: record the candidate's reason")
        decision, overridden = str(ov["decision"]).capitalize(), True
    role = fit.get("role") or {}
    return {
        "company": role.get("company", ""), "title": role.get("title", ""), "url": role.get("url", ""),
        "score": score, "coverage": round(coverage, 2), "recommendation": recommendation, "decision": decision,
        "overridden": overridden, "override_reason": ov.get("reason", ""), "blockers": blockers,
        "screener_risks": risks + list(fit.get("screener_risks") or []), "penalties": penalties,
        "missing_must": missing_must, "gaps": gaps, "years_in_function": have, "scored": date.today().isoformat(),
    }, errs, warns


def report(r):
    lines = [f"## {r['company']} - {r['title']}", "",
             f"**Fit {r['score']} / 5 -> {r['decision']}**" + (f" (candidate override; computed: {r['recommendation']}."
                                                                 f" Reason: {r['override_reason']})" if r["overridden"] else ""),
             f"Requirement coverage {int(r['coverage'] * 100)}%."]
    for k, title in (("blockers", "Blockers"), ("screener_risks", "Screener risks")):
        if r[k]:
            lines += ["", f"{title}:"] + [f"- {x}" for x in r[k]]
    if r["gaps"]:
        lines += ["", "Gaps for the Writer (map by intent first; propose bullets only for what stays uncovered):"]
        lines += [f"- [{g['weight']}/{g['match']}] {g['req']}" + (f" (closest: {', '.join(g['evidence'])})" if g["evidence"] else "")
                  for g in r["gaps"]]
    return "\n".join(lines)


def table(results):
    rows = sorted(results, key=lambda r: (r["decision"] != "Apply", r["decision"] == "Skip", -r["score"]))
    out = ["| Fit | Call | Role | Company | Main gap | Blocker / risk |", "|---|---|---|---|---|---|"]
    for r in rows:
        gap = r["missing_must"][0] if r["missing_must"] else (r["gaps"][0]["req"] if r["gaps"] else "")
        risk = (r["blockers"] or r["screener_risks"] or [""])[0]
        cell = lambda s: str(s).replace("|", "/").replace("\n", " ")[:90]  # noqa: E731
        role = f"[{cell(r['title'])}]({r['url']})" if r["url"].startswith("http") else cell(r["title"])
        out.append(f"| {r['score']} | {r['decision']}{'*' if r['overridden'] else ''} | {role} | {cell(r['company'])} | "
                   f"{cell(gap)} | {cell(risk)} |")
    return "\n".join(out) + "\n\nApply = 4.0+; Consider = 3.0-3.9, only with a reason you name; Skip = below 3.0 or a blocker. * = your override.\n"


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fits", nargs="+")
    ap.add_argument("--master", required=True)
    ap.add_argument("--prefs")
    ap.add_argument("--table", help="write a ranked markdown table here")
    a = ap.parse_args()
    master, prefs = load(a.master), load(a.prefs) if a.prefs else {}
    results, failed = [], False
    for path in a.fits:
        fit = load(path)
        posting = None
        # posting_check.py output, relative to the fit file (default: posting_check.json beside it)
        pc = os.path.join(os.path.dirname(os.path.abspath(path)), fit.get("posting_check") or "posting_check.json")
        if os.path.isfile(pc):
            with open(pc, encoding="utf-8") as f:
                posting = json.load(f)
        r, errs, warns = score_fit(fit, master, prefs, posting)
        for w in warns:
            print(f"WARNING {path}: {w}", file=sys.stderr)
        if errs:
            failed = True
            for e in errs:
                print(f"ERROR {path}: {e}", file=sys.stderr)
            continue
        with open(os.path.splitext(path)[0] + ".json", "w", encoding="utf-8") as f:
            json.dump(r, f, indent=2)
        results.append(r)
        print(report(r) + "\n")
    if a.table and results:
        os.makedirs(os.path.dirname(os.path.abspath(a.table)), exist_ok=True)
        with open(a.table, "w", encoding="utf-8") as f:
            f.write(table(results))
        print("table ->", a.table)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
