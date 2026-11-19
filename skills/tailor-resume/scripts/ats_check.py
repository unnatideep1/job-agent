#!/usr/bin/env python3
"""Screening pass on a built resume PDF: does it parse cleanly, and does it cover the JD's keywords truthfully?

Usage:
    python ats_check.py --master DATA/master_resume.yaml --tailoring APP/tailoring.yaml \
        --pdf APP/<name>.pdf [--jd APP/jd.txt] [--out APP/]

Reads the PDF's text layer the way an applicant tracking system does (pdftotext, else pypdf) and writes
ats_report.md + ats_report.json next to the tailoring file (or in --out).

1. Parse score (0-100): enough text, email + phone, name at the top, standard headings, embedded fonts,
   reading order (company > title > dates > bullets), no broken glyphs, page limit. Plus lints.
2. Keyword coverage, for each item in tailoring.yaml `keywords:` (the JD's must/core/nice terms):
     covered      in the PDF and backed by the master file in its own words
     mapped       in the PDF via the Writer's intent mapping (evidence + stretch); Tod checks the stretch
     surface      not in the PDF, but a master fact backs it: reword that bullet (ids listed)
     propose      not in the PDF and nothing backs it, must/core: the Writer drafts a bullet for the
                  candidate to approve (proposals.yaml), never inserts it directly
     missing-ok   not in the PDF, nothing backs it, nice-to-have: leave it out
     unsupported  in the PDF but nothing backs it: ERROR (exit 1)
   Coverage % is weighted must=3, core=2, nice=1 over covered + mapped.
3. Advisory: JD terms (acronyms, common tools/skills) the keyword list doesn't mention yet.
Exit code 1 on unsupported keywords or a parse score below 70.
Idea adapted from career-ops (MIT, github.com/career-ops-hq/career-ops) modes/ats.md and keyword coverage.
"""
import argparse
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_resume as br  # noqa: E402

WEIGHT = {"must": 3, "core": 2, "nice": 1}
SKILLS = [  # common JD terms; extend freely. Matched whole-word, case-insensitive.
    "a/b testing", "experimentation", "sql", "python", "analytics", "roadmap", "okrs", "stakeholder management",
    "go-to-market", "pricing", "monetization", "b2b", "b2c", "saas", "platform", "api", "apis", "machine learning",
    "generative ai", "llm", "llms", "agents", "rag", "evaluation", "evals", "fine-tuning", "prompt engineering",
    "responsible ai", "data science", "user research", "discovery", "product strategy", "product vision",
    "cross-functional", "enterprise", "developer tools", "growth", "retention", "activation", "onboarding",
    "payments", "billing", "marketplace", "mobile", "ios", "android", "security", "compliance", "privacy",
    "infrastructure", "cloud", "aws", "gcp", "azure", "kubernetes", "figma", "jira", "amplitude", "mixpanel",
    "tableau", "looker", "people management", "hiring", "mentoring", "p&l", "0 to 1", "zero to one", "scale",
]
ACRONYM = re.compile(r"\b[A-Z][A-Z0-9&/+]{1,6}s?\b")
ACRONYM_STOP = {"US", "USA", "EEO", "EOE", "PTO", "AND", "OR", "THE", "WE", "OUR", "YOU", "II", "III", "IV",
                "HQ", "CA", "NY", "TX", "WA", "UK", "EU", "LGBTQ", "ADA", "OK", "FAQ", "CEO", "CTO", "CPO", "VP"}
GLYPHS = {"\ufffd": "replacement character", "\ufb01": "fi ligature", "\ufb02": "fl ligature",
          "\ufb00": "ff ligature", "\ufb03": "ffi ligature", "\u25a1": "empty box"}


def pdf_text(pdf):
    out = br._run("pdftotext", "-layout", pdf, "-")
    if out is not None:
        return out, "pdftotext"
    try:
        from pypdf import PdfReader
        return "\n".join(p.extract_text() or "" for p in PdfReader(pdf).pages), "pypdf"
    except Exception:  # pypdf missing or unreadable PDF
        return None, None


def fonts_embedded(pdf):
    out = br._run("pdffonts", pdf)
    if out is None:
        return None
    rows = [ln.split() for ln in out.splitlines()[2:] if ln.strip()]
    # columns end with: emb sub uni object-id(2 fields); 'emb' is the 5th from the end.
    # The 14 standard PDF fonts (Helvetica, Times, Courier, ...) are built into every reader, so they're fine.
    std = re.compile(r"^(Helvetica|Times|Courier|Symbol|ZapfDingbats)", re.I)
    return all(len(r) >= 5 and (r[-5] == "yes" or std.match(r[0])) for r in rows) if rows else None


def parse_checks(text, master, t, pdf, rendered_first=None):
    """Return (score, checks, lints). Each check: {name, points, max, detail}."""
    flat = " ".join(text.split())
    low = flat.lower()
    p = master.get("person") or {}
    checks = []

    def add(name, ok, pts, detail=""):
        checks.append(dict(name=name, points=pts if ok else 0, max=pts, ok=bool(ok), detail=detail))

    add("Text layer readable (300+ characters)", len(flat) >= 300, 15, f"{len(flat)} characters")
    em, ph = str(p.get("email", "")), re.sub(r"\D", "", str(p.get("phone", "")))
    add("Email and phone readable", em.lower() in low and (not ph or ph in re.sub(r"\D", "", flat)), 15)
    name = str(p.get("name", "")).lower()
    add("Name at the top", name and name in low[:200], 5)
    heads = ["experience", "education", (t.get("strengths_title") or "skills").lower()]
    if not master.get("education"):
        heads.remove("education")
    found = [h for h in heads if re.search(rf"(^|\n)\s*{re.escape(h)}\s*(\n|$)", text.lower())]
    add("Standard section headings", len(found) == len(heads), 20, f"found {found} of {heads}")
    emb = fonts_embedded(pdf)
    add("Fonts embedded", emb is not False, 10, "pdffonts not installed; not checked" if emb is None else "")
    probs = br.reading_order_problems(pdf, master, rendered_first) if rendered_first is not None else None
    add("Reading order: company > title > dates > bullets", not probs, 20,
        "; ".join(probs[:3]) if probs else ("not checked" if probs is None else ""))
    bad = sorted({v for k, v in GLYPHS.items() if k in text})
    add("No broken glyphs or ligatures", not bad, 10, ", ".join(bad))
    pages = br.page_count(pdf)
    limit = int(master.get("max_pages", 2))
    add(f"Within {limit} pages", not pages or pages <= limit, 5, f"{pages} pages" if pages else "pdfinfo not installed")

    lints = []
    if "→" in text:
        lints.append("'→' in the text: some parsers drop it. Prefer 'to' (e.g. '0 to 1') in the summary and strengths.")
    if re.search(r"\(Acquired by [^)]+\)", flat):
        lints.append("'(Acquired by X)' sits next to a company name; a few parsers read it as part of the employer.")
    if re.search(r"[\u2022\u25cf]\s*$", text, re.M):
        lints.append("A bullet character sits alone on a line; check that bullets read with their text.")
    return sum(c["points"] for c in checks), checks, lints


def rendered_first_bullets(master, t):
    """Role id -> text of the first rendered bullet (scope bullet, rewritten if a rewrite exists)."""
    rw = t.get("rewrites") or {}
    out = {}
    for co in master.get("experience") or []:
        for r in co.get("roles") or []:
            secs = br.sections_of(r)
            if secs and secs[0]["bullets"]:
                b = secs[0]["bullets"][0]
                out[r["id"]] = br.plain((rw.get(b["id"]) or {}).get("text") or b["text"])
    return out


def keyword_report(master, t, text):
    texts = br.master_texts(master)
    texts["_education"] = " ".join(f"{e.get('school', '')} {e.get('degree', '')}" for e in master.get("education") or [])
    rows = []
    for kw in t.get("keywords") or []:
        if not isinstance(kw, dict) or not kw.get("term"):
            continue
        pri = kw.get("priority", "core")
        in_pdf = br.mentions(text, kw)
        direct = [i for i, x in texts.items() if br.mentions(x, kw)]
        mapped = [e for e in kw.get("evidence") or [] if e in texts] if kw.get("stretch") else []
        if in_pdf:
            status = "covered" if direct else ("mapped" if mapped else "unsupported")
        elif direct or mapped:
            status = "surface"
        else:
            status = "propose" if pri in ("must", "core") else "missing-ok"
        rows.append(dict(term=kw["term"], priority=pri, status=status, in_pdf=in_pdf,
                         backed_by=[i.strip("_").replace("_", " ") if i.startswith("_") else i
                                    for i in (direct or mapped)][:6],
                         stretch=kw.get("stretch", "")))
    tot = sum(WEIGHT.get(r["priority"], 2) for r in rows)
    got = sum(WEIGHT.get(r["priority"], 2) for r in rows if r["status"] in ("covered", "mapped"))
    return rows, round(100 * got / tot) if tot else None


def jd_terms(jd, t, text):
    """JD terms not in the keyword list and not in the PDF: candidates for the Writer to consider."""
    if not jd:
        return []
    listed = t.get("keywords") or []
    covered = lambda term: br.mentions(text, {"term": term}) or any(  # noqa: E731
        br.mentions(term, k) or br.mentions(k.get("term", ""), {"term": term}) for k in listed if isinstance(k, dict))
    found = {}
    for m in ACRONYM.findall(jd):
        if m.rstrip("s") not in ACRONYM_STOP and len(m.rstrip("s")) >= 2:
            found[m] = found.get(m, 0) + 1
    seen = {k.lower() for k in found}
    for s in SKILLS:
        n = br.norm(jd).count(br.norm(s))
        if n and s.lower() not in seen:
            found[s] = found.get(s, 0) + n
    return sorted(((k, n) for k, n in found.items() if not covered(k)), key=lambda x: -x[1])[:20]


def render_md(rep):
    L = [f"# Screening report: {rep['target']}", "",
         f"**Parse score {rep['parse_score']}/100** (text read with {rep['extractor']})  ",
         f"**Keyword coverage {rep['coverage'] if rep['coverage'] is not None else 'n/a'}%** (must=3, core=2, nice=1)", ""]
    L += ["## Parse checks", "", "| Check | Points | Detail |", "|---|---|---|"]
    L += [f"| {'✅' if c['ok'] else '❌'} {c['name']} | {c['points']}/{c['max']} | {c['detail']} |" for c in rep["checks"]]
    if rep["lints"]:
        L += ["", "**Lints**", ""] + [f"- {x}" for x in rep["lints"]]
    L += ["", "## Keywords", "", "| Term | Priority | Status | Backed by | Stretch |", "|---|---|---|---|---|"]
    L += [f"| {r['term']} | {r['priority']} | {r['status']} | {', '.join(r['backed_by'])} | {r['stretch']} |"
          for r in rep["keywords"]]
    todo = {s: [r["term"] for r in rep["keywords"] if r["status"] == s] for s in ("unsupported", "surface", "propose")}
    L += ["", "## Next steps", ""]
    if todo["unsupported"]:
        L.append(f"- ❌ Remove or back these (no master fact supports them): {', '.join(todo['unsupported'])}")
    if todo["surface"]:
        L.append(f"- Reword the listed bullets so these appear: {', '.join(todo['surface'])}")
    if todo["propose"]:
        L.append(f"- Writer drafts proposals for the candidate to approve: {', '.join(todo['propose'])}")
    if not any(todo.values()):
        L.append("- Nothing to do: every listed keyword is covered or deliberately left out.")
    if rep["jd_terms"]:
        L += ["", "## JD terms not in the keyword list (advisory)", "",
              ", ".join(f"{k} ({n})" for k, n in rep["jd_terms"])]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", required=True)
    ap.add_argument("--tailoring", required=True)
    ap.add_argument("--pdf", required=True)
    ap.add_argument("--jd", help="job description text file (optional; enables the advisory term list)")
    ap.add_argument("--out", help="folder for ats_report.md/.json (default: the tailoring file's folder)")
    a = ap.parse_args()
    with open(a.master, encoding="utf-8") as f:
        master = yaml.safe_load(f)
    with open(a.tailoring, encoding="utf-8") as f:
        t = yaml.safe_load(f) or {}
    jd = open(a.jd, encoding="utf-8", errors="replace").read() if a.jd and os.path.isfile(a.jd) else ""

    text, how = pdf_text(a.pdf)
    if text is None:
        print("NOTE: neither pdftotext (poppler) nor pypdf is available; screening pass skipped.", file=sys.stderr)
        sys.exit(0)
    score, checks, lints = parse_checks(text, master, t, a.pdf, rendered_first_bullets(master, t))
    kws, cov = keyword_report(master, t, text)
    tgt = t.get("target") or {}
    rep = dict(target=f"{tgt.get('company', '')} · {tgt.get('role', '')}".strip(" ·"), extractor=how,
               parse_score=score, checks=checks, lints=lints, coverage=cov, keywords=kws,
               jd_terms=jd_terms(jd, t, text))
    out = a.out or os.path.dirname(os.path.abspath(a.tailoring))
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "ats_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, indent=2, ensure_ascii=False)
    with open(os.path.join(out, "ats_report.md"), "w", encoding="utf-8") as f:
        f.write(render_md(rep))
    bad = [r["term"] for r in kws if r["status"] == "unsupported"]
    print(f"parse {score}/100 · coverage {cov if cov is not None else 'n/a'}% · "
          + ", ".join(f"{s} {sum(r['status'] == s for r in kws)}"
                      for s in ("covered", "mapped", "surface", "propose", "missing-ok", "unsupported")))
    print(os.path.join(out, "ats_report.md"))
    if bad:
        print(f"ERROR: keywords in the PDF that nothing in the master file backs: {bad}", file=sys.stderr)
    if score < 70:
        print("ERROR: parse score below 70; fix the failed checks before sending.", file=sys.stderr)
    sys.exit(1 if bad or score < 70 else 0)


if __name__ == "__main__":
    main()
