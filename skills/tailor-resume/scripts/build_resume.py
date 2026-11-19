#!/usr/bin/env python3
"""Render a tailored resume PDF from master_resume.yaml + one application's tailoring.yaml.

Usage:
    python build_resume.py --master <data>/master_resume.yaml \
        --tailoring <data>/applications/<app>/tailoring.yaml --out <data>/applications/<app>/

What this script enforces (so tailoring cannot break the candidate's rules by accident):
  * Bullets come from the master file. A rewrite must reference an existing bullet and keep every
    number from the source bullet. A new bullet must cite a confirmed addition (by id) and may only use
    numbers that appear in that confirmed fact.
  * Each section's first (scope) bullet is always rendered first and can never be omitted or replaced
    by an addition.
  * Every role and sub-product section in the master file is rendered, separately.
  * Core Strengths must come from strengths_library (only the candidate adds to it).
  * Only <b>, <i>, <u> markup is allowed in text; anything else is escaped.
  * After building, the text layer is checked for reading order (company, title, dates, bullets) and
    page count. Dates are inline by default; date_style: right is used only if it reads in order.
Exit code 1 on any validation error. Requires: reportlab, pyyaml. Optional: poppler (pdftotext, pdfinfo).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import date

import yaml  # safe_load only
from reportlab.lib import colors
from reportlab.lib.fonts import addMapping
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer
from reportlab.platypus.flowables import HRFlowable

# ------------------------------------------------------------------ fonts
FONT_FAMILIES = [  # (regular, bold, italic, bold-italic); first complete family found wins
    ("/usr/share/fonts/truetype/crosextra/Carlito-Regular.ttf", "/usr/share/fonts/truetype/crosextra/Carlito-Bold.ttf",
     "/usr/share/fonts/truetype/crosextra/Carlito-Italic.ttf", "/usr/share/fonts/truetype/crosextra/Carlito-BoldItalic.ttf"),
    ("/Applications/Microsoft Word.app/Contents/Resources/DFonts/calibri.ttf",
     "/Applications/Microsoft Word.app/Contents/Resources/DFonts/calibrib.ttf",
     "/Applications/Microsoft Word.app/Contents/Resources/DFonts/calibrii.ttf",
     "/Applications/Microsoft Word.app/Contents/Resources/DFonts/calibriz.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-BoldOblique.ttf"),
    ("/Library/Fonts/Arial Unicode.ttf",) * 4,
]


def register_fonts(font_dir=None):
    fams = list(FONT_FAMILIES)
    if font_dir:
        fams.insert(0, tuple(os.path.join(font_dir, f) for f in
                             ("Carlito-Regular.ttf", "Carlito-Bold.ttf", "Carlito-Italic.ttf", "Carlito-BoldItalic.ttf")))
    for files in fams:
        if all(os.path.isfile(f) for f in files):
            for name, f in zip(("RF", "RF-Bold", "RF-Italic", "RF-BoldItalic"), files):
                pdfmetrics.registerFont(TTFont(name, f))
            addMapping("RF", 0, 0, "RF"); addMapping("RF", 1, 0, "RF-Bold")
            addMapping("RF", 0, 1, "RF-Italic"); addMapping("RF", 1, 1, "RF-BoldItalic")
            return True
    print("WARNING: no TrueType font found; using Helvetica (non-Latin characters and arrows will not render). "
          "Pass --font-dir with Carlito-*.ttf.", file=sys.stderr)
    return False


NAVY = colors.HexColor("#1F3864"); BLUE = colors.HexColor("#4A90D9"); GREY = colors.HexColor("#666666")


def make_styles(ttf):
    R, B, I, BI = ("RF", "RF-Bold", "RF-Italic", "RF-BoldItalic") if ttf else \
        ("Helvetica", "Helvetica-Bold", "Helvetica-Oblique", "Helvetica-BoldOblique")
    base = 10.2
    return {
        "name": ParagraphStyle("name", fontName=B, fontSize=22, leading=26, alignment=1, textColor=NAVY),
        "contact": ParagraphStyle("contact", fontName=R, fontSize=base, leading=13, alignment=1),
        "h": ParagraphStyle("h", fontName=B, fontSize=11, leading=13, textColor=NAVY),
        "body": ParagraphStyle("body", fontName=R, fontSize=base, leading=12.6),
        "bullet": ParagraphStyle("bullet", fontName=R, fontSize=base, leading=12.4, leftIndent=11, bulletIndent=2),
        "co": ParagraphStyle("co", fontName=B, fontSize=11.5, leading=14, textColor=BLUE),
        "role": ParagraphStyle("role", fontName=B, fontSize=base, leading=12.6),
        "right": ParagraphStyle("right", fontName=R, fontSize=base, leading=12.6, textColor=colors.black),
        "righti": ParagraphStyle("righti", fontName=I, fontSize=9.4, leading=12.6, textColor=GREY),
        "desc": ParagraphStyle("desc", fontName=I, fontSize=9.6, leading=11.8, textColor=GREY),
        "sub": ParagraphStyle("sub", fontName=BI, fontSize=base, leading=12.6, textColor=NAVY),
    }


class Row(Flowable):
    """Left paragraph + right-aligned text on one line, drawn in reading order."""

    def __init__(self, left, right, ls, rs):
        super().__init__()
        self.lp, self.right, self.rs = Paragraph(left, ls), right, rs

    def wrap(self, aw, ah):
        rw = pdfmetrics.stringWidth(self.right, self.rs.fontName, self.rs.fontSize) + 6
        self.aw = aw
        _, self.h = self.lp.wrap(aw - rw, ah)
        return aw, self.h

    def draw(self):
        self.lp.drawOn(self.canv, 0, 0)
        c = self.canv
        c.saveState(); c.setFont(self.rs.fontName, self.rs.fontSize); c.setFillColor(self.rs.textColor)
        c.drawRightString(self.aw, self.h - self.lp.style.leading + 2.6, " " + self.right)
        c.restoreState()


class Spaced(Flowable):
    """One line of letter-spaced text using real character spacing, so text extraction yields whole words."""

    def __init__(self, text, style, spacing, align="left"):
        super().__init__()
        self.text, self.st, self.sp, self.align = text, style, spacing, align

    def wrap(self, aw, ah):
        self.aw = aw
        return aw, self.st.leading

    def draw(self):
        c = self.canv
        w = pdfmetrics.stringWidth(self.text, self.st.fontName, self.st.fontSize) + self.sp * (len(self.text) - 1)
        x = (self.aw - w) / 2 if self.align == "center" else 0
        t = c.beginText(x, self.st.leading - self.st.fontSize)
        t.setFont(self.st.fontName, self.st.fontSize)
        t.setCharSpace(self.sp)
        t.setFillColor(self.st.textColor)
        t.textOut(self.text)
        c.drawText(t)


# ------------------------------------------------------------------ text helpers
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def fmt_date(v):
    if v is None or str(v).lower() == "present":
        return "Present"
    m = re.fullmatch(r"(\d{4})-(\d{2})", str(v))
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError(f"bad date {v!r}: use YYYY-MM (month 01-12) or 'present'")
    return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}"


def span(a, b):
    return f"{fmt_date(a)} – {fmt_date(b)}"


def esc(t):
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_ALLOWED_TAG = re.compile(r"</?(b|i|u)>", re.I)
_ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);")


def safe_markup(t):
    """Keep <b>/<i>/<u> and valid entities; escape every other markup character."""
    out, pos = [], 0
    t = str(t)
    for m in _ALLOWED_TAG.finditer(t):
        out.append(_escape_plain(t[pos:m.start()])); out.append(m.group(0).lower()); pos = m.end()
    out.append(_escape_plain(t[pos:]))
    return "".join(out)


def _escape_plain(s):
    parts, pos = [], 0
    for m in _ENTITY.finditer(s):
        parts.append(s[pos:m.start()].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        parts.append(m.group(0)); pos = m.end()
    parts.append(s[pos:].replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return "".join(parts)


def plain(t):
    return " ".join(re.sub(r"<[^>]+>", "", str(t)).split())


NUM_RE = re.compile(r"(?<![A-Za-z])\d[\d,.]*\s*%?|\+\d+%?")  # digits inside words (B2B, S3) aren't metrics


def numbers(t):
    return sorted(n.replace(" ", "").rstrip(".,") for n in NUM_RE.findall(plain(t)))


# ------------------------------------------------------------------ keywords
def norm(t):
    """Lower-case words with punctuation as spaces, padded, so phrases match on word boundaries."""
    return " " + " ".join(re.sub(r"[^a-z0-9+#/&]+", " ", plain(t).lower().replace("→", " to ")).split()) + " "


def _variants(phrase):
    p = norm(phrase).strip()
    if not p:
        return []
    out = {p, p + "s", p + "es"}
    if p.endswith("s"):
        out.add(p[:-1])
    if p.endswith("es"):
        out.add(p[:-2])
    return [f" {v} " for v in out]


def mentions(text, kw):
    """True if text uses the keyword's term or one of its aliases (whole words, singular or plural)."""
    t = norm(text)
    return any(v in t for ph in [kw.get("term", "")] + list(kw.get("aliases") or []) for v in _variants(str(ph)))


def master_texts(master):
    """id -> text for every bullet and confirmed addition, plus role titles and the default summary."""
    out = {}
    for co in master.get("experience") or []:
        for r in co.get("roles") or []:
            out[r["id"]] = f"{r.get('title', '')}. {r.get('description', '')}"
            for s in r.get("sections") or []:
                for b in s.get("bullets") or []:
                    out[b["id"]] = f"{s.get('heading', '')} {b['text']}"
    for a in master.get("confirmed_additions") or []:
        if a.get("id") and a.get("status", "confirmed") in CONFIRMED:
            out[a["id"]] = str(a.get("fact", ""))
    out["_summary_default"] = str(master.get("summary_default", ""))
    out["_strengths_library"] = " · ".join(master.get("strengths_library") or [])
    return out


def supports(kw, text, ids):
    """A placement is backed if its source says it (term or alias) or the Writer mapped this source to it by intent."""
    return mentions(text, kw) or bool(set(kw.get("evidence") or []) & set(ids) and kw.get("stretch"))


def validate_keywords(master, t):
    """Every JD keyword the resume uses must be backed by the source it sits in (decision: no unsupported keywords)."""
    errs, warns = [], []
    kws = t.get("keywords") or []
    if not isinstance(kws, list):
        return ["keywords: expected a list of {term, priority, aliases, evidence, stretch}"], warns
    texts = master_texts(master)
    bullets = {b["id"]: b["text"] for co in master.get("experience") or [] for r in co.get("roles") or []
               for s in r.get("sections") or [] for b in s.get("bullets") or []}
    adds = {a["id"]: a for a in master.get("confirmed_additions") or [] if a.get("id")}
    for kw in kws:
        if not isinstance(kw, dict) or not kw.get("term"):
            errs.append("keywords: every item needs a 'term'"); continue
        name = kw["term"]
        if kw.get("priority", "core") not in ("must", "core", "nice"):
            errs.append(f"keywords.{name}: priority must be must, core or nice")
        ev = kw.get("evidence") or []
        bad = [e for e in ev if e not in texts]
        if bad:
            errs.append(f"keywords.{name}: evidence ids not in the master file: {bad}")
        if ev and not kw.get("stretch") and not all(mentions(texts.get(e, ""), kw) for e in ev if e in texts):
            errs.append(f"keywords.{name}: evidence doesn't use the term; add 'stretch' saying why it's a fair reading")
        for bid, rw in (t.get("rewrites") or {}).items():
            if isinstance(rw, dict) and bid in bullets and mentions(rw.get("text", ""), kw) \
                    and not supports(kw, bullets[bid], [bid]):
                errs.append(f"rewrites.{bid}: uses '{name}', which bullet {bid} doesn't back. Map it by intent "
                            f"(keywords.{name}.evidence + stretch), place it where it's true, or propose a bullet for approval")
        for rid, items in (t.get("additions") or {}).items():
            for it in items or []:
                src = adds.get((it or {}).get("from")) if isinstance(it, dict) else None
                if src and mentions(it.get("text", ""), kw) and not supports(kw, src.get("fact", ""), [src["id"]]):
                    errs.append(f"additions.{rid}: uses '{name}', which confirmed fact '{src['id']}' doesn't back")
        summary = t.get("summary")
        if summary and mentions(summary, kw) and not supports(kw, " ".join(texts.values()), list(texts)):
            errs.append(f"summary: uses '{name}', which nothing in the master file backs")
    return errs, warns


# ------------------------------------------------------------------ validation
def sections_of(role):
    return [s for s in (role.get("sections") or []) if s.get("bullets")]


def validate_master(master):
    errs = []
    if not isinstance(master, dict):
        return ["master file is empty or not a mapping"]
    p = master.get("person") or {}
    if not p.get("name"):
        errs.append("person.name is required")
    seen = set()
    for ci, co in enumerate(master.get("experience") or []):
        where = f"experience[{ci}] ({co.get('company', '?')})"
        for k in ("company", "start", "end", "roles"):
            if not co.get(k):
                errs.append(f"{where}: '{k}' is required")
        for role in co.get("roles") or []:
            for k in ("id", "title", "start", "end"):
                if not role.get(k):
                    errs.append(f"{where}: every role needs '{k}'")
            for k in ("start", "end"):
                try:
                    fmt_date(role.get(k))
                except ValueError as e:
                    errs.append(f"{where} / {role.get('id')}: {e}")
            for sec in role.get("sections") or []:
                for b in sec.get("bullets") or []:
                    if not b.get("id") or not b.get("text"):
                        errs.append(f"{where} / {role.get('id')}: every bullet needs 'id' and 'text'")
                    elif b["id"] in seen:
                        errs.append(f"duplicate bullet id {b['id']}")
                    seen.add(b.get("id"))
        for k in ("start", "end"):
            try:
                fmt_date(co.get(k))
            except ValueError as e:
                errs.append(f"{where}: {e}")
    for a in master.get("confirmed_additions") or []:
        if not a.get("id") or not a.get("fact"):
            errs.append("every confirmed_additions entry needs 'id' and 'fact'")
    return errs


CONFIRMED = ("confirmed", "candidate-confirmed")


def validate_tailoring(master, t):
    errs, warns = [], []
    roles = {r["id"]: r for co in master.get("experience", []) for r in co.get("roles", [])}
    bullets = {b["id"]: b["text"] for r in roles.values() for s in sections_of(r) for b in s["bullets"]}
    scope_ids = {s["bullets"][0]["id"] for r in roles.values() for s in sections_of(r)}
    adds = {a["id"]: a for a in master.get("confirmed_additions") or [] if a.get("id")}

    for rid, secs in (t.get("order") or {}).items():
        if rid not in roles:
            errs.append(f"order: unknown role id {rid}"); continue
        if not isinstance(secs, list) or not all(isinstance(x, list) for x in secs):
            errs.append(f"order.{rid}: expected a list of lists, one per section, e.g. [[id1, id2]]"); continue
        for si, lst in enumerate(secs):
            rsecs = sections_of(roles[rid])
            if si >= len(rsecs):
                errs.append(f"order.{rid}: no section #{si}"); continue
            valid = {b["id"] for b in rsecs[si]["bullets"]}
            errs += [f"order.{rid}: {b} is not in section #{si}" for b in lst if b not in valid]
            dup = sorted({b for b in lst if lst.count(b) > 1})
            if dup:
                errs.append(f"order.{rid}: duplicate ids {dup}")

    for bid, rw in (t.get("rewrites") or {}).items():
        if bid not in bullets:
            errs.append(f"rewrites: {bid} does not exist in the master file"); continue
        if not isinstance(rw, dict):
            errs.append(f"rewrites.{bid}: expected {{text: ..., why: ...}}"); continue
        text = rw.get("text", "")
        if not text:
            errs.append(f"rewrites.{bid}: missing text"); continue
        missing = [n for n in numbers(bullets[bid]) if n not in numbers(text)]
        if missing:
            errs.append(f"rewrites.{bid}: drops or changes numbers from the source bullet: {missing}")
        extra = [n for n in numbers(text) if n not in numbers(bullets[bid])]
        if extra:
            errs.append(f"rewrites.{bid}: introduces numbers not in the source bullet: {extra}")
        if not (rw or {}).get("why"):
            warns.append(f"rewrites.{bid}: add 'why' (the JD term it maps to) for Tod")

    for rid, items in (t.get("additions") or {}).items():
        if rid not in roles:
            errs.append(f"additions: unknown role id {rid}"); continue
        for it in items or []:
            if not isinstance(it, dict):
                errs.append(f"additions.{rid}: each item must be {{from, text, section, after}}"); continue
            src = adds.get(it.get("from"))
            if not src:
                errs.append(f"additions.{rid}: 'from: {it.get('from')}' is not a confirmed_additions id "
                            "(drafts in proposals.yaml can't be used until the candidate approves them)")
            elif src.get("status", "confirmed") not in CONFIRMED:
                errs.append(f"additions.{rid}: confirmed_additions '{src['id']}' has status "
                            f"'{src.get('status')}'; only candidate-approved facts can go on a resume")
            if not it.get("text"):
                errs.append(f"additions.{rid}: missing text")
            elif src:
                extra = [n for n in numbers(it["text"]) if n not in numbers(src["fact"])]
                if extra:
                    errs.append(f"additions.{rid}: numbers not in the confirmed fact '{src['id']}': {extra}")
            sec = it.get("section", 0)
            rsecs = sections_of(roles[rid])
            if not isinstance(sec, int) or not 0 <= sec < len(rsecs):
                errs.append(f"additions.{rid}: no section #{sec}")
            elif it.get("after") and it["after"] not in {b["id"] for b in rsecs[sec]["bullets"]}:
                errs.append(f"additions.{rid}: after: {it['after']} is not a bullet in section #{sec}")

    for bid in t.get("omit") or []:
        if bid not in bullets:
            errs.append(f"omit: {bid} does not exist")
        elif bid in scope_ids:
            errs.append(f"omit: {bid} is a scope bullet and cannot be omitted")

    lib = set(master.get("strengths_library") or [])
    for s in t.get("strengths") or []:
        if s not in lib:
            errs.append(f"strengths: '{s}' is not in strengths_library. Only the candidate can approve a new phrase; "
                        "the orchestrator adds it to the master file after they say yes.")
    if t.get("date_style") not in (None, "right", "inline"):
        errs.append("date_style must be 'right' or 'inline'")
    e2, w2 = validate_keywords(master, t)
    return errs + e2, warns + w2


def ordered(section, wanted, omit, extra):
    bl = section["bullets"]
    by_id = {b["id"]: b for b in bl}
    scope = bl[0]["id"]
    seq = [scope]
    for b in wanted or []:
        if b in by_id and b not in seq:
            seq.append(b)
    seq += [b["id"] for b in bl if b["id"] not in seq]  # never drop silently
    seq = [b for b in seq if b == scope or b not in omit]
    out = [by_id[b]["text"] for b in seq]
    for it in extra:  # additions: after a given bullet, else at the end; never before the scope bullet
        after = it.get("after")
        idx = seq.index(after) + 1 if after in seq else len(seq)
        idx = max(idx, 1)
        seq.insert(idx, f"+{it['from']}"); out.insert(idx, it["text"])
    return seq, out


# ------------------------------------------------------------------ render
def build(master, t, out_pdf, S, ttf, inline_dates):
    page = letter if str(master.get("page_size", "A4")).lower() == "letter" else A4
    W = page[0] - 32 * mm
    rewrites = t.get("rewrites") or {}
    order = t.get("order") or {}
    omit = set(t.get("omit") or [])
    additions = t.get("additions") or {}
    p = master["person"]
    rendered_first = {}

    def txt(s):
        s = safe_markup(" ".join(str(s).split()))
        return s if ttf else s.replace("→", "-&gt;")

    def row(left, right, ls, rs):
        if inline_dates:
            return Paragraph(f'{left} <font name="{rs.fontName}" size="{rs.fontSize}" color="#666666">| {esc(right)}</font>', ls)
        return Row(left, right, ls, rs)

    def header(title):
        return [Spacer(1, 7), Spaced(title.upper(), S["h"], 1.0),
                HRFlowable(width="100%", thickness=1.1, color=NAVY, spaceBefore=1, spaceAfter=4)]

    doc = SimpleDocTemplate(out_pdf, pagesize=page, leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=12 * mm, bottomMargin=11 * mm, title=f"{p['name']} – Resume", author=p["name"])
    st = [Spaced(str(p["name"]).upper(), S["name"], 2.0, align="center")]
    contact = [esc(p[k]) for k in ("email", "phone") if p.get(k)]
    if p.get("linkedin"):
        contact.append(f'<link href="{esc(p["linkedin"])}"><u><font color="#1F3864">'
                       f'{esc(str(p["linkedin"]).split("//")[-1])}</font></u></link>')
    if p.get("location"):
        contact.append(esc(p["location"]))
    st.append(Paragraph(" &nbsp;&nbsp;|&nbsp;&nbsp; ".join(contact), S["contact"]))

    summary = t.get("summary") or master.get("summary_default")
    if summary:
        st += header("Summary"); st.append(Paragraph(txt(summary), S["body"]))
    if t.get("strengths"):
        st += header(str(t.get("strengths_title", "Core Strengths")))
        st.append(Paragraph(txt(" · ".join(t["strengths"])), S["body"]))

    st += header("Experience")
    for ci, co in enumerate(master.get("experience") or []):
        name = esc(co["company"])
        if co.get("acquired_by"):
            name += f' <font color="#3A8D5C" size="9.5">(Acquired by {esc(co["acquired_by"])})</font>'
        if ci:
            st.append(Spacer(1, 6))
        block_start = len(st)  # company header .. first bullet are kept on one page
        st.append(row(name, span(co["start"], co["end"]), S["co"], S["right"]))
        if co.get("description"):
            st.append(Paragraph(txt(co["description"]), S["desc"]))
        multi = len(co["roles"]) > 1
        for ri, role in enumerate(co["roles"]):
            if multi:
                if ri:
                    st.append(Spacer(1, 4))
                st.append(row(esc(role["title"]), span(role["start"], role["end"]), S["role"], S["righti"]))
            else:
                st.append(Paragraph(esc(role["title"]), S["role"]))
            if role.get("description"):
                st.append(Paragraph(txt(role["description"]), S["desc"]))
            wanted_secs = order.get(role["id"], [])
            role_adds = additions.get(role["id"]) or []
            for si, sec in enumerate(sections_of(role)):
                if sec.get("heading"):
                    st.append(Paragraph(txt(sec["heading"]), S["sub"]))
                wanted = wanted_secs[si] if si < len(wanted_secs) else None
                extra = [a for a in role_adds if a.get("section", 0) == si]
                ids, texts = ordered(sec, wanted, omit, extra)
                texts = [(rewrites.get(i) or {}).get("text", tx) if not i.startswith("+") else tx
                         for i, tx in zip(ids, texts)]
                if si == 0:
                    rendered_first[role["id"]] = plain(texts[0])
                paras = [Paragraph(txt(b), S["bullet"], bulletText="•") for b in texts]
                if block_start is not None:
                    st[block_start:] = [KeepTogether(st[block_start:] + paras[:1])]
                    paras = paras[1:]
                    block_start = None
                st += paras

    edu = header("Education") if master.get("education") else []
    for e in master.get("education") or []:
        edu.append(row(f"<b>{esc(e.get('school', ''))}</b> - <i>{esc(e.get('degree', ''))}</i>",
                       str(e.get("years", "")), S["body"], S["righti"]))
    if edu:
        st.append(KeepTogether(edu))
    doc.build(st)
    return rendered_first


# ------------------------------------------------------------------ post-build checks
def _run(tool, *args):
    exe = shutil.which(tool)
    if not exe:
        return None
    return subprocess.run([exe, *args], capture_output=True, text=True, check=False).stdout  # no shell


def page_count(pdf):
    out = _run("pdfinfo", pdf)
    m = re.search(r"^Pages:\s+(\d+)", out or "", re.M)
    return int(m.group(1)) if m else None


def reading_order_problems(pdf, master, rendered_first):
    """For every role: company < title < first bullet, and its dates appear before the first bullet."""
    text = _run("pdftotext", pdf, "-")
    if text is None:
        return None  # poppler not installed
    flat = " ".join(text.split())
    problems, cursor = [], 0
    for co in master.get("experience") or []:
        ci = flat.find(co["company"], cursor)
        if ci < 0:
            problems.append(f"{co['company']}: company name not found in text layer"); continue
        cursor = ci
        multi = len(co["roles"]) > 1
        for role in co["roles"]:
            if role["id"] not in rendered_first:
                continue  # role has no bullets: nothing to order
            ti = flat.find(role["title"], cursor)
            first = rendered_first.get(role["id"], "")[:40]
            bi = flat.find(first, max(ti, cursor)) if first else -1
            dates = span(role["start"], role["end"]) if multi else span(co["start"], co["end"])
            di = flat.find(dates, cursor)
            if min(ti, bi) < 0:
                problems.append(f"{role['title']}: title or first bullet not found"); continue
            if not (di >= 0 and di < bi):
                problems.append(f"{role['title']}: dates read after its first bullet")
            cursor = bi
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--master", required=True)
    ap.add_argument("--tailoring", required=True)
    ap.add_argument("--out", required=True, help="output directory")
    ap.add_argument("--font-dir", help="folder with Carlito-Regular/Bold/Italic/BoldItalic.ttf (optional)")
    a = ap.parse_args()

    with open(a.master, encoding="utf-8") as f:
        master = yaml.safe_load(f)
    with open(a.tailoring, encoding="utf-8") as f:
        t = yaml.safe_load(f) or {}

    errors = validate_master(master)
    warns = []
    if not errors:
        e2, warns = validate_tailoring(master, t)
        errors += e2
    for w in warns:
        print("WARNING:", w, file=sys.stderr)
    if errors:
        for e in errors:
            print("ERROR:", e, file=sys.stderr)
        sys.exit(1)

    name = re.sub(r"[^A-Za-z0-9_.-]", "_", t.get("output_name") or f"Resume_{date.today():%Y%m%d}")
    os.makedirs(a.out, exist_ok=True)
    out_pdf = os.path.join(a.out, name + ".pdf")
    ttf = register_fonts(a.font_dir)
    S = make_styles(ttf)
    inline = t.get("date_style", "inline") == "inline"  # inline is the safe default
    first = build(master, t, out_pdf, S, ttf, inline)
    problems = reading_order_problems(out_pdf, master, first)
    if problems is None:
        print("NOTE: pdftotext not found; reading-order check skipped (install poppler).", file=sys.stderr)
    elif problems and not inline:
        print("WARNING: right-aligned dates read out of order; rebuilt with inline dates:", file=sys.stderr)
        for p in problems[:5]:
            print("  -", p, file=sys.stderr)
        first = build(master, t, out_pdf, S, ttf, True)
        problems = reading_order_problems(out_pdf, master, first)
    if problems:
        print("WARNING: reading-order problems remain:", problems, file=sys.stderr)
    pages = page_count(out_pdf)
    if pages and pages > int(master.get("max_pages", 2)):
        print(f"WARNING: {pages} pages; limit is {master.get('max_pages', 2)}. Use 'omit' on older roles.", file=sys.stderr)
    print(out_pdf)


if __name__ == "__main__":
    main()
