#!/usr/bin/env python3
"""Pull job links out of job-alert emails you saved (LinkedIn, Indeed, Wellfound, or any board's alerts).

Usage:
    python import_alerts.py alert1.eml [alert2.txt ...] --out DATA/scout/alerts-<date>.csv [--seen DATA/applications.csv]

Save an alert from your mail app (File > Save As .eml, or copy the text into a .txt file) and run this.
It reads the file only: it never logs in to, searches or opens LinkedIn or any other site.
Each row gets the title and company the email shows. Company-board links (Greenhouse, Lever, Ashby,
Workable, SmartRecruiters, Recruitee) are kept as they are. For aggregator links (LinkedIn, Indeed...) the
Scout finds the same role on the company's own board and applies there; it never opens the aggregator link.
Idea credit: LinkedIn job-alert import in career-ops (MIT).
"""
import argparse
import csv
import email
import os
import re
import sys
from email import policy
from html.parser import HTMLParser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scout import csv_safe  # noqa: E402

URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
BOARD_RE = re.compile(r"https://(?:job-boards|boards)\.greenhouse\.io/[\w.-]+/jobs/\d+|https://jobs\.lever\.co/[\w.-]+/[0-9a-f-]{36}"
                      r"|https://jobs\.ashbyhq\.com/[\w.-]+/[0-9a-f-]{36}|https://apply\.workable\.com/(?:[\w.-]+/)?j/[0-9A-F]+"
                      r"|https://jobs\.smartrecruiters\.com/[\w.-]+/\d+[\w-]*|https://[\w-]+\.recruitee\.com/o/[\w-]+", re.I)
AGGREGATORS = [
    ("linkedin", re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(?:[\w-]*?-)?(\d{6,})", re.I), "https://www.linkedin.com/jobs/view/{}"),
    ("indeed", re.compile(r"indeed\.com/(?:rc/clk|viewjob|pagead/clk)\S*?[?&](?:jk|vjk)=([0-9a-f]{16})", re.I), "https://www.indeed.com/viewjob?jk={}"),
    ("wellfound", re.compile(r"wellfound\.com/jobs/(\d+)", re.I), "https://wellfound.com/jobs/{}"),
]
SKIP_LINE = re.compile(r"^(view job|apply|see all|unsubscribe|easy apply|promoted|actively recruiting|\d+ (?:applicants|connections?)|"
                       r"be an early applicant|new|top applicant|your job alert|manage alerts?|job alert)\b", re.I)


class _Links(HTMLParser):
    """HTML -> text, writing each link as 'anchor text\\nURL' so titles sit on the line above their link."""

    def __init__(self):
        super().__init__()
        self.out, self.href, self.anchor, self.skip = [], None, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self.skip += 1
        elif tag == "a":
            self.href, self.anchor = dict(attrs).get("href"), []
        elif tag in ("br", "p", "div", "tr", "li", "td", "table", "h1", "h2", "h3"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("style", "script") and self.skip:
            self.skip -= 1
        elif tag == "a" and self.href:
            self.out.append("\n" + " ".join("".join(self.anchor).split()) + "\n" + self.href + "\n")
            self.href = None

    def handle_data(self, d):
        if self.skip:
            return
        (self.anchor if self.href else self.out).append(d)


def email_text(raw):
    """Plain text of an .eml (prefers the HTML part, which carries the links) or of a pasted .txt. Takes bytes or str."""
    data = raw if isinstance(raw, bytes) else raw.encode("utf-8")
    text = data.decode("utf-8", errors="replace")
    if re.search(r"^(?:From|Subject|Content-Type|MIME-Version):", text[:4000], re.M):
        msg = email.message_from_bytes(data, policy=policy.default)  # bytes keep 8-bit bodies intact
        parts = {p.get_content_type(): p for p in msg.walk() if not p.is_multipart()}
        part = parts.get("text/html") or parts.get("text/plain")
        if part is not None:
            body = part.get_content()
            return html_text(body) if part.get_content_type() == "text/html" else body
    return html_text(text) if re.search(r"<a\s[^>]*href=", text, re.I) else text


def html_text(s):
    p = _Links()
    p.feed(s)
    return "".join(p.out)


def canonical(url):
    m = BOARD_RE.search(url)
    if m:
        return "company board", m.group(0)
    for name, rx, fmt in AGGREGATORS:
        m = rx.search(url)
        if m:
            return name, fmt.format(m.group(1))
    return None, None


def parse(text):
    """Return [{title, company, location, url, via}] in email order, de-duplicated."""
    lines = [" ".join(x.split()) for x in text.splitlines()]
    sep = re.compile(r"\s[·•|–-]\s")
    by_url = {}
    for i, line in enumerate(lines):
        for u in URL_RE.findall(line):
            via, url = canonical(u)
            if not url:
                continue
            # Meaningful lines around the link, stopping at neighbouring links. Plain-text alerts show
            # "Title", "Company · Location", then the link; HTML alerts put the title on the link itself.
            same = URL_RE.sub("", line).strip(" :-")
            start = max([0, i - 4] + [k + 1 for k in range(max(0, i - 4), i) if URL_RE.search(lines[k])])
            ok = lambda p: p and not URL_RE.search(p) and not SKIP_LINE.match(p)  # noqa: E731
            above = [p for p in lines[start:i] + [same] if ok(p)]
            below = []
            for p in lines[i + 1:i + 4]:
                if URL_RE.search(p):
                    break
                if ok(p):
                    below.append(p)
            title, company, location = "", "", ""
            if above and sep.search(above[-1]):  # text layout: Title / Company · Location / link
                company, location = (sep.split(above[-1], maxsplit=1) + [""])[:2]
                title = above[-2] if len(above) > 1 else ""
            else:  # HTML layout: the title is the link text; Company · Location follows
                title = above[-1] if above else ""
                co = next((p for p in below if sep.search(p)), "")
                if co:
                    company, location = (sep.split(co, maxsplit=1) + [""])[:2]
            row = by_url.setdefault(url, dict(title="", company="", location="", url=url, via=via))
            for k, v in (("title", title), ("company", company), ("location", location)):
                if v and not row[k]:  # the same job is often linked twice (logo, then title)
                    row[k] = v.strip()[:150]
    rows = list(by_url.values())
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--seen", help="tracker CSV; links already tracked are skipped")
    a = ap.parse_args()
    seen = set()
    if a.seen and os.path.isfile(a.seen):
        with open(a.seen, newline="", encoding="utf-8") as f:
            seen = {r.get("url", "") for r in csv.DictReader(f)}
    rows, urls = [], set()
    for path in a.files:
        with open(path, "rb") as f:
            for r in parse(email_text(f.read())):
                if r["url"] not in seen and r["url"] not in urls:
                    urls.add(r["url"])
                    rows.append(r)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["company", "title", "location", "via", "url"])
        w.writeheader()
        w.writerows({k: csv_safe(v) for k, v in r.items()} for r in rows)
    print(f"{len(rows)} jobs from {len(a.files)} file(s) -> {a.out}")


if __name__ == "__main__":
    main()
