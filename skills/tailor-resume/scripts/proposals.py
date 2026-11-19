#!/usr/bin/env python3
"""Gap-filling proposals: check the Writer's drafts, show them to the candidate, record her decisions.

When a must/core JD requirement is still uncovered after intent mapping, the Writer doesn't ask an open
question. It drafts a bullet and the candidate approves, edits or rejects it. Two kinds:
  grounded    extends or rewords something already in the master file (inspired_by lists those bullet ids)
  new-claim   UNVERIFIED: nothing in the master file supports it. Drafted to fit her roles, companies and
              seniority, but only she knows whether it happened. Never used until she approves it.
Approved (or edited) proposals are appended to master_resume.yaml `confirmed_additions` with
status: candidate-confirmed, so every later application can reuse them. Rejected ones go to
`rejected_proposals` so the same idea isn't proposed again for the same requirement.

Usage:
    python proposals.py check  --master DATA/master_resume.yaml --proposals APP/proposals.yaml
    python proposals.py prompt --master DATA/master_resume.yaml --proposals APP/proposals.yaml
    python proposals.py apply  --master DATA/master_resume.yaml --proposals APP/proposals.yaml [--app NAME]

proposals.yaml:
    proposals:
      - id: agent_platform_pilot          # becomes the confirmed_additions id; unique, snake_case
        requirement: agent platforms      # the JD requirement it covers
        kind: new-claim                   # grounded | new-claim
        role: ex_senior                   # role it belongs under
        inspired_by: [ex_scope, ex_eval]  # master ids it's modelled on (required for grounded)
        text: "Scoped tool-calling for the AI assistant with engineering and support teams."
        decision: pending                 # pending | approved | edited | rejected  (set from her answer)
        edited_text: ""                   # her wording, when decision: edited (numbers she adds are hers)

Rules (check exits 1 on any): ids unique and not already in the master file; role and inspired_by ids exist;
grounded proposals cite inspired_by; numbers in a draft must appear in its inspired_by facts (new-claim drafts
may contain no numbers at all) unless the candidate wrote them in edited_text; no draft repeats one she
rejected for the same requirement. `apply` only records proposals she decided; pending ones stay pending.
The master file keeps its comments: entries are inserted as text, then the file is re-parsed to verify.
"""
import argparse
import os
import re
import shutil
import sys
from datetime import date

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_resume as br  # noqa: E402

KINDS = ("grounded", "new-claim")
DECISIONS = ("pending", "approved", "edited", "rejected")


def load(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def words(t):
    return set(br.norm(t).split())


def similar(a, b):
    """Same idea: normalised text equal, or 80% word overlap."""
    wa, wb = words(a), words(b)
    return bool(wa and wb) and (wa == wb or len(wa & wb) / max(len(wa | wb), 1) >= 0.8)


def check(master, props):
    errs = []
    texts = br.master_texts(master)
    roles = {r["id"] for co in master.get("experience") or [] for r in co.get("roles") or []}
    taken = set(texts) | {a.get("id") for a in master.get("confirmed_additions") or []}
    rejected = master.get("rejected_proposals") or []
    seen = set()
    for p in props:
        pid = p.get("id")
        where = f"proposal {pid or '?'}"
        if not pid or not re.fullmatch(r"[a-z0-9_]+", str(pid)):
            errs.append(f"{where}: needs an id in snake_case"); continue
        if pid in seen:
            errs.append(f"{where}: duplicate id")
        seen.add(pid)
        if pid in taken and not p.get("recorded"):
            errs.append(f"{where}: id already used in the master file")
        for k in ("requirement", "text"):
            if not p.get(k):
                errs.append(f"{where}: missing {k}")
        kind = p.get("kind", "grounded")
        if kind not in KINDS:
            errs.append(f"{where}: kind must be grounded or new-claim")
        if p.get("decision", "pending") not in DECISIONS:
            errs.append(f"{where}: decision must be one of {DECISIONS}")
        if p.get("role") not in roles:
            errs.append(f"{where}: role {p.get('role')!r} is not a role id in the master file")
        insp = p.get("inspired_by") or []
        bad = [i for i in insp if i not in texts]
        if bad:
            errs.append(f"{where}: inspired_by ids not in the master file: {bad}")
        if kind == "grounded" and not insp:
            errs.append(f"{where}: a grounded proposal must list the master bullets it extends (inspired_by)")
        allowed = set() if kind == "new-claim" else {n for i in insp for n in br.numbers(texts.get(i, ""))}
        extra = [n for n in br.numbers(p.get("text", "")) if n not in allowed]
        if extra:
            errs.append(f"{where}: numbers the candidate hasn't given: {extra}. Drafts use no new metrics; "
                        "leave a blank for her to fill, e.g. 'cut handling time by [X%]'")
        if p.get("decision") == "edited" and not p.get("edited_text"):
            errs.append(f"{where}: decision is edited but edited_text is empty")
        final = p.get("edited_text") if p.get("decision") == "edited" else p.get("text", "")
        if p.get("decision") in ("approved", "edited") and re.search(r"\[[^\]]*\]", str(final or "")):
            errs.append(f"{where}: still has a blank like [X%]; the candidate must fill it in (edit) before it's saved")
        for r in rejected:
            if str(r.get("requirement", "")).lower() == str(p.get("requirement", "")).lower() \
                    and similar(r.get("text", ""), p.get("text", "")) and p.get("decision") != "rejected":
                errs.append(f"{where}: the candidate already rejected this idea for '{r.get('requirement')}' "
                            f"on {r.get('date')}; don't propose it again")
    return errs


def prompt(props):
    """The approval list shown to the candidate (pending proposals only)."""
    L = []
    pend = [p for p in props if p.get("decision", "pending") == "pending"]
    for n, p in enumerate(pend, 1):
        tag = "UNVERIFIED new claim, nothing in your master file says this" if p.get("kind") == "new-claim" \
            else f"extends {', '.join(p.get('inspired_by') or [])}"
        L += [f"{n}. [{tag}] covers \"{p.get('requirement')}\" (under {p.get('role')})",
              f"   \"{br.plain(p.get('text', ''))}\""]
    if L:
        L = ["Proposed bullets for requirements your resume doesn't cover yet.",
             "Approve only what is true and you could talk through in an interview.",
             "Reply per item: approve / edit: <your wording> / reject.", ""] + L
    return "\n".join(L)


def _item_yaml(item, indent):
    body = yaml.safe_dump([item], sort_keys=False, allow_unicode=True, width=1000)
    return "".join(" " * indent + ln + "\n" for ln in body.splitlines())


def insert_list_items(src, key, items):
    """Append items to the top-level list `key:` as text, so comments elsewhere survive."""
    if not items:
        return src
    lines = src.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{key}:\s*(\[\s*\])?\s*(#.*)?$", ln)), None)
    if start is None:
        sep = "" if src.endswith("\n") or not src else "\n"
        return src + sep + f"\n{key}:\n" + "".join(_item_yaml(it, 2) for it in items)
    if re.match(rf"^{key}:\s*\[\s*\]", lines[start]):
        lines[start] = f"{key}:\n"
    end, indent = start + 1, None
    for i in range(start + 1, len(lines)):
        ln = lines[i]
        if re.match(r"^[A-Za-z_]", ln):
            break
        if ln.strip() and not ln.lstrip().startswith("#"):
            end = i + 1
            m = re.match(r"^(\s*)- ", ln)
            if m and indent is None:
                indent = len(m.group(1))
    if lines[end - 1:end] and not lines[end - 1].endswith("\n"):
        lines[end - 1] += "\n"
    block = "".join(_item_yaml(it, 2 if indent is None else indent) for it in items)
    return "".join(lines[:end]) + block + "".join(lines[end:])


def apply(master_path, props_path, app, today=None):
    master, doc = load(master_path), load(props_path)
    props = doc.get("proposals") or []
    errs = check(master, props)
    if errs:
        return errs, [], []
    today = date.fromisoformat(str(today)) if today else date.today()
    adds, rejs = [], []
    for p in props:
        d = p.get("decision", "pending")
        if p.get("recorded") or d == "pending":
            continue
        if d in ("approved", "edited"):
            adds.append(dict(id=p["id"], fact=br.plain(p["edited_text"] if d == "edited" else p["text"]),
                             status="candidate-confirmed", confirmed=today, source_app=app,
                             covers=p["requirement"], role=p["role"], origin=p.get("kind", "grounded"),
                             inspired_by=list(p.get("inspired_by") or [])))
        else:
            rejs.append(dict(requirement=p["requirement"], text=br.plain(p["text"]), date=today, app=app))
        p["recorded"] = today
    if not adds and not rejs:
        return [], adds, rejs
    with open(master_path, encoding="utf-8") as f:
        src = f.read()
    before = yaml.safe_load(src) or {}
    for key in ("confirmed_additions", "rejected_proposals"):
        if not isinstance(before.get(key) or [], list):
            return [f"{key} in the master file is not a list; fix it by hand first. Nothing was written"], [], []
    new = insert_list_items(insert_list_items(src, "confirmed_additions", adds), "rejected_proposals", rejs)
    # The edited file must parse to exactly the old content plus the new items, so nothing is lost or duplicated.
    expected = dict(before)
    expected["confirmed_additions"] = list(before.get("confirmed_additions") or []) + adds
    if rejs or "rejected_proposals" in before:
        expected["rejected_proposals"] = list(before.get("rejected_proposals") or []) + rejs
    try:
        ok = yaml.safe_load(new) == expected
    except yaml.YAMLError:
        ok = False
    if not ok:
        return ["could not insert into the master file cleanly (is a list written inline?); nothing was written"], [], []
    shutil.copyfile(master_path, master_path + ".bak")
    with open(master_path, "w", encoding="utf-8") as f:
        f.write(new)
    with open(props_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(doc, f, sort_keys=False, allow_unicode=True, width=1000)
    return [], adds, rejs


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["check", "prompt", "apply"])
    ap.add_argument("--master", required=True)
    ap.add_argument("--proposals", required=True)
    ap.add_argument("--app", help="application folder name (default: the proposals file's folder)")
    a = ap.parse_args()
    app = a.app or os.path.basename(os.path.dirname(os.path.abspath(a.proposals)))
    if a.cmd == "apply":
        errs, adds, rejs = apply(a.master, a.proposals, app)
        for e in errs:
            print("ERROR:", e, file=sys.stderr)
        if not errs:
            print(f"recorded {len(adds)} approved into confirmed_additions, {len(rejs)} into rejected_proposals")
        sys.exit(1 if errs else 0)
    master, props = load(a.master), load(a.proposals).get("proposals") or []
    errs = check(master, props)
    for e in errs:
        print("ERROR:", e, file=sys.stderr)
    if a.cmd == "prompt" and not errs:
        print(prompt(props) or "No pending proposals.")
    elif not errs:
        print(f"{len(props)} proposals OK")
    sys.exit(1 if errs else 0)


if __name__ == "__main__":
    main()
