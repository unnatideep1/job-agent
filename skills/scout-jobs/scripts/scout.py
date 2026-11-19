#!/usr/bin/env python3
"""Scan company job boards for roles that match job_preferences.yaml.

Usage:
    python scout.py --prefs job-agent-data/job_preferences.yaml --out job-agent-data/scout/latest.csv \
        [--seen job-agent-data/applications.csv] [--history job-agent-data/scout/history.csv] [--catalog portals.yaml]

Boards: Greenhouse, Lever, Ashby, Rippling, Workable, SmartRecruiters and Recruitee, via their public,
documented JSON endpoints only (no scraping, no login, no LinkedIn). Boards come from `sources:` in the
preferences file plus any companies picked from the bundled catalog (`catalog: {tags: [...]}`).

Output: CSV of matching roles with posting dates and flags, for the Scout agent to verify, score and shortlist.
Flags: stale? (older than posting.max_age_days), repost? (same company and title seen before under another
URL), new (first seen in this scan; needs --history).
Requires: pyyaml
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone

import yaml

SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")  # board ids are inserted into URLs: allowlist them
SUBDOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")      # Recruitee ids become a host name
UA = "job-agent-scout/1.0 (+personal job search; respects public board APIs)"
TIMEOUT = 20
MAX_BYTES = 15 * 1024 * 1024  # refuse absurdly large payloads
SMARTRECRUITERS_PAGES = 10    # 100 postings per page
REPOST_WINDOW_DAYS = 90
HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CATALOG = os.path.join(HERE, "..", "portals.yaml")

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "rippling": "https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
}


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # HTTPS with default cert verification
        if r.status != 200:
            raise urllib.error.HTTPError(url, r.status, "bad status", r.headers, None)
        body = r.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("response too large")
        return json.loads(body.decode("utf-8"))


def iso_date(v):
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):  # Lever: epoch ms
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc).date().isoformat()
    return str(v)[:10]


def valid_id(source, slug):
    return bool((SUBDOMAIN_RE if source == "recruitee" else SLUG_RE).match(str(slug)))


def board_url(source, slug):
    if source == "smartrecruiters":
        return ENDPOINTS[source].format(slug=slug, offset=0)
    return ENDPOINTS[source].format(slug=slug)


def fetch_board(source, slug):
    if source != "smartrecruiters":
        return fetch_json(board_url(source, slug))
    content = []
    for page in range(SMARTRECRUITERS_PAGES):
        d = fetch_json(ENDPOINTS[source].format(slug=slug, offset=page * 100))
        content += d.get("content") or []
        if len(content) >= int(d.get("totalFound") or 0) or not d.get("content"):
            break
    return {"content": content}


def normalise(source, slug, data):
    """Map each ATS's payload to {title, location, workplace, url, posted, department}."""
    out = []
    if source == "greenhouse":
        for j in data.get("jobs", []):
            out.append(dict(title=j.get("title", ""), location=(j.get("location") or {}).get("name", ""),
                            workplace="", url=j.get("absolute_url", ""),
                            posted=iso_date(j.get("first_published") or j.get("updated_at"))))
    elif source == "lever":
        for j in data if isinstance(data, list) else []:
            c = j.get("categories") or {}
            loc = " / ".join(filter(None, [c.get("location")] + list(c.get("allLocations") or [])))
            out.append(dict(title=j.get("text", ""), location=loc, workplace=j.get("workplaceType", ""),
                            url=j.get("hostedUrl", ""), posted=iso_date(j.get("createdAt")),
                            department=c.get("department") or c.get("team") or ""))
    elif source == "ashby":
        for j in data.get("jobs", []):
            locs = [j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations") or []]
            out.append(dict(title=j.get("title", ""), location=" / ".join(filter(None, locs)),
                            workplace=j.get("workplaceType", "") or ("Remote" if j.get("isRemote") else ""),
                            url=j.get("jobUrl", ""), posted=iso_date(j.get("publishedAt")),
                            department=j.get("department") or j.get("team") or ""))
    elif source == "rippling":
        for j in data if isinstance(data, list) else []:
            out.append(dict(title=(j.get("name") or "").strip(), location=(j.get("workLocation") or {}).get("label", ""),
                            workplace="", url=j.get("url", ""), posted="",
                            department=(j.get("department") or {}).get("label", "")))
    elif source == "workable":
        for j in data.get("jobs", []):
            locs = [", ".join(filter(None, [x.get("city"), x.get("region"), x.get("country")]))
                    for x in j.get("locations") or [] if not x.get("hidden")]
            if not locs:
                locs = [", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))]
            out.append(dict(title=j.get("title", ""), location=" / ".join(filter(None, locs)),
                            workplace="Remote" if j.get("telecommuting") else "", url=j.get("url", ""),
                            posted=iso_date(j.get("published_on") or j.get("created_at")),
                            department=j.get("department") or ""))
    elif source == "smartrecruiters":
        for j in data.get("content", []):
            loc = j.get("location") or {}
            work = "Remote" if loc.get("remote") else ("Hybrid" if loc.get("hybrid") else "")
            out.append(dict(title=j.get("name", ""), location=loc.get("fullLocation") or loc.get("city") or "",
                            workplace=work, url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id', '')}",
                            posted=iso_date(j.get("releasedDate")),
                            department=(j.get("department") or {}).get("label", "")))
    elif source == "recruitee":
        for j in data.get("offers", []):
            work = "Remote" if j.get("remote") else ("Hybrid" if j.get("hybrid") else "")
            out.append(dict(title=j.get("title", ""), location=j.get("location") or "", workplace=work,
                            url=j.get("careers_url", ""), posted=iso_date(j.get("published_at") or j.get("created_at")),
                            department=j.get("department") or ""))
    for o in out:
        o.update(company=slug, source=source)
    return out


def rippling_created(slug, url):
    """Rippling's list endpoint has no posting date; fetch it for matched roles only."""
    uuid = url.rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", uuid):
        return ""
    try:
        return iso_date(fetch_json(ENDPOINTS["rippling"].format(slug=slug) + "/" + uuid).get("createdOn"))
    except Exception:
        return ""


def has_phrase(text, phrase):
    """Whole-word phrase match ('us' must not match 'Belarus'; 'engineer' must not match 'Engineering')."""
    return re.search(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])", text.lower()) is not None


def title_ok(title, prefs):
    lv = prefs.get("target_levels") or {}
    if any(has_phrase(title, x) for x in lv.get("exclude_titles", [])):
        return False
    return any(has_phrase(title, x) for x in lv.get("include_titles", []))


def location_ok(job, prefs):
    loc = f"{job['location']} {job.get('workplace', '')}"
    L = prefs.get("locations") or {}
    if any(has_phrase(loc, x) for x in L.get("onsite_or_hybrid", [])):
        return True
    return has_phrase(loc, "remote") and any(has_phrase(loc, x) for x in L.get("remote_from", []))


def age_days(posted, today=None):
    try:
        d = datetime.fromisoformat(posted).date()
    except ValueError:
        return None
    return ((today or datetime.now(timezone.utc).date()) - d).days


def title_key(title):
    """Same set of title words = same role (tolerates word order and punctuation; not city or level changes)."""
    return " ".join(sorted(set(re.findall(r"[a-z0-9]+", title.lower()))))


# ------------------------------------------------------------------ boards to scan
def load_catalog(path):
    try:
        with open(path, encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("companies") or []
    except FileNotFoundError:
        return []


def board_list(prefs, catalog):
    """(source, id, display name, tags) from prefs.sources plus catalog companies picked by tag or name."""
    names = {(c["source"], str(c["id"]).lower()): c for c in catalog}
    boards, seen = [], set()

    def add(source, slug, name, tags):
        key = (source, str(slug).lower())
        if source in ENDPOINTS and key not in seen:
            seen.add(key)
            boards.append((source, slug, name, tags))

    for source, slugs in (prefs.get("sources") or {}).items():
        if source not in ENDPOINTS:  # e.g. careers_sites: checked by the Scout in the browser
            continue
        for slug in slugs or []:
            c = names.get((source, str(slug).lower())) or {}
            add(source, slug, c.get("name", slug), c.get("tags", []))
    cat = prefs.get("catalog") or {}
    want = {t.lower() for t in cat.get("tags") or []}
    extra = {n.lower() for n in cat.get("companies") or []}
    skip = {n.lower() for n in cat.get("exclude") or []}
    for c in catalog:
        if str(c.get("name", "")).lower() in skip:
            continue
        if cat.get("all") or want & {t.lower() for t in c.get("tags") or []} or str(c.get("name", "")).lower() in extra:
            add(c["source"], c["id"], c.get("name", c["id"]), c.get("tags") or [])
    return boards


# ------------------------------------------------------------------ scan
def scan(prefs, catalog=None, fetch=fetch_board):
    tasks = []
    for source, slug, name, tags in board_list(prefs, catalog or []):
        if not valid_id(source, slug):
            print(f"skip invalid board id {slug!r}", file=sys.stderr)
            continue
        tasks.append((source, slug, name, tags))

    def run(task):
        source, slug, name, tags = task
        try:
            found = normalise(source, slug, fetch(source, slug))
            for j in found:
                j.update(company=name, board=slug, tags=" ".join(tags))
            return found, None
        except Exception as e:  # one bad board must never abort the whole scan
            return [], f"{source}/{slug}: {type(e).__name__}"

    jobs, failures = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for found, err in ex.map(run, tasks):
            jobs += found
            if err:
                failures.append(err)

    max_age = (prefs.get("posting") or {}).get("max_age_days", 45)
    depts = prefs.get("departments") or []
    keep, dedup = [], set()
    for j in jobs:
        # whole-word match, so "product" keeps "Product & Design" and "Product Management"
        if j.get("department") and depts and not any(has_phrase(j["department"], d) for d in depts):
            continue
        if not (title_ok(j["title"], prefs) and location_ok(j, prefs)):
            continue
        key = (j["company"].lower(), title_key(j["title"]), j["location"].lower())
        if key in dedup:  # the same opening listed on two boards
            continue
        dedup.add(key)
        if j["source"] == "rippling" and not j["posted"]:
            j["posted"] = rippling_created(j["board"], j["url"])  # list API has no date; detail API does
        a = age_days(j["posted"]) if j["posted"] else None
        j["age_days"] = "" if a is None else a
        j["flag"] = "stale?" if (a is not None and a > max_age) else ""
        keep.append(j)
    keep.sort(key=lambda j: (j["flag"] != "", j["age_days"] if j["age_days"] != "" else 9999))
    return keep, failures


# ------------------------------------------------------------------ history: reposts and new roles
HISTORY_COLS = ["url", "company", "title", "title_key", "first_seen", "last_seen", "posted"]


def read_history(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def apply_history(jobs, history, today=None):
    """Flag reposts and new roles, and return the updated history rows.

    A repost is the same company + title words under a different URL that we first saw on an earlier date
    within REPOST_WINDOW_DAYS. Postings first seen in the same scan are parallel openings, not reposts.
    """
    today = today or date.today()
    by_url = {h["url"]: h for h in history}
    for j in jobs:
        tk = title_key(j["title"])
        prior = [h for h in history if h["url"] != j["url"] and h["company"].lower() == j["company"].lower()
                 and h["title_key"] == tk and h["first_seen"] < today.isoformat()
                 and (age_days(h["first_seen"], today) or 0) <= REPOST_WINDOW_DAYS]
        flags = [f for f in j.get("flag", "").split() if f]
        if prior:
            flags.append("repost?")
        h = by_url.get(j["url"])
        if h is None:
            if history:  # on the very first scan everything is new; don't flag it
                flags.append("new")
            h = dict(url=j["url"], company=j["company"], title=j["title"], title_key=tk,
                     first_seen=today.isoformat(), posted=j.get("posted", ""))
            by_url[j["url"]] = h
        h["last_seen"] = today.isoformat()
        j["first_seen"] = h["first_seen"]
        j["flag"] = " ".join(flags)
    return list(by_url.values())


def csv_safe(v):
    """Neutralise spreadsheet formulas in third-party text (CSV injection)."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def write_csv(path, cols, rows):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows({k: csv_safe(v) for k, v in r.items()} for r in rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seen", help="tracker CSV; roles whose url is already tracked are skipped")
    ap.add_argument("--history", help="scan history CSV (created if missing); enables repost? and new flags")
    ap.add_argument("--catalog", default=DEFAULT_CATALOG, help="company catalog (default: bundled portals.yaml)")
    a = ap.parse_args()
    with open(a.prefs, encoding="utf-8") as f:
        prefs = yaml.safe_load(f) or {}
    catalog = load_catalog(a.catalog)
    print(f"scanning {len(board_list(prefs, catalog))} boards", file=sys.stderr)
    jobs, failures = scan(prefs, catalog)
    seen = set()
    if a.seen:
        try:
            with open(a.seen, newline="", encoding="utf-8") as f:
                seen = {r.get("url", "") for r in csv.DictReader(f)}
        except FileNotFoundError:
            pass
    jobs = [j for j in jobs if j["url"] not in seen]
    if a.history:
        write_csv(a.history, HISTORY_COLS, apply_history(jobs, read_history(a.history)))
    cols = ["company", "title", "location", "workplace", "posted", "age_days", "flag", "source", "tags",
            "first_seen", "url"]
    write_csv(a.out, cols, jobs)
    print(f"{len(jobs)} matching roles -> {a.out}")
    for e in failures:
        print("board unavailable:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
