#!/usr/bin/env python3
"""Scan company job boards (Greenhouse, Lever, Ashby, Rippling) for roles that match job_preferences.yaml.

Usage:
    python scout.py --prefs job-agent-data/job_preferences.yaml --out job-agent-data/scout/latest.csv [--seen job-agent-data/applications.csv]

Uses only the boards' public, documented JSON endpoints (no scraping, no login, no LinkedIn).
Output: CSV of candidate roles with posting dates, for the Scout agent to verify, score and shortlist.
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
from datetime import datetime, timezone

import yaml

SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")  # board ids are inserted into URLs: allowlist them
UA = "job-agent-scout/1.0 (+personal job search; respects public board APIs)"
TIMEOUT = 20
MAX_BYTES = 15 * 1024 * 1024  # refuse absurdly large payloads

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "rippling": "https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs",
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


def normalise(source, slug, data):
    """Map each ATS's payload to {company, title, location, workplace, url, posted, source}."""
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


def age_days(posted):
    try:
        d = datetime.fromisoformat(posted).date()
    except ValueError:
        return None
    return (datetime.now(timezone.utc).date() - d).days


def scan(prefs):
    tasks = []
    for source, slugs in (prefs.get("sources") or {}).items():
        if source not in ENDPOINTS:
            continue
        for slug in slugs or []:
            if not SLUG_RE.match(str(slug)):
                print(f"skip invalid board id {slug!r}", file=sys.stderr)
                continue
            tasks.append((source, slug))

    def run(task):
        source, slug = task
        try:
            return normalise(source, slug, fetch_json(ENDPOINTS[source].format(slug=slug))), None
        except Exception as e:  # one bad board must never abort the whole scan
            return [], f"{source}/{slug}: {type(e).__name__}"

    jobs, failures = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for found, err in ex.map(run, tasks):
            jobs += found
            if err:
                failures.append(err)

    max_age = (prefs.get("posting") or {}).get("max_age_days", 45)
    keep = []
    for j in jobs:
        depts = prefs.get("departments") or []
        # whole-word match, so "product" keeps "Product & Design" and "Product Management"
        if j.get("department") and depts and not any(has_phrase(j["department"], d) for d in depts):
            continue
        if not (title_ok(j["title"], prefs) and location_ok(j, prefs)):
            continue
        if j["source"] == "rippling" and not j["posted"]:
            j["posted"] = rippling_created(j["company"], j["url"])  # list API has no date; detail API does
        a = age_days(j["posted"]) if j["posted"] else None
        j["age_days"] = "" if a is None else a
        j["flag"] = "stale?" if (a is not None and a > max_age) else ""
        keep.append(j)
    keep.sort(key=lambda j: (j["flag"] != "", j["age_days"] if j["age_days"] != "" else 9999))
    return keep, failures


def csv_safe(v):
    """Neutralise spreadsheet formulas in third-party text (CSV injection)."""
    v = "" if v is None else str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@", "\t", "\r") else v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seen", help="tracker CSV; roles whose url is already tracked are skipped")
    a = ap.parse_args()
    with open(a.prefs, encoding="utf-8") as f:
        prefs = yaml.safe_load(f)
    jobs, failures = scan(prefs)
    seen = set()
    if a.seen:
        try:
            with open(a.seen, newline="", encoding="utf-8") as f:
                seen = {r.get("url", "") for r in csv.DictReader(f)}
        except FileNotFoundError:
            pass
    jobs = [j for j in jobs if j["url"] not in seen]
    cols = ["company", "title", "location", "workplace", "posted", "age_days", "flag", "source", "url"]
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows({k: csv_safe(v) for k, v in j.items()} for j in jobs)
    print(f"{len(jobs)} matching roles -> {a.out}")
    for e in failures:
        print("board unavailable:", e, file=sys.stderr)


if __name__ == "__main__":
    main()
