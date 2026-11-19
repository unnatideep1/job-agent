# job-agent

A Claude plugin for a careful, human-approved job search:

- **Scout:** finds high-fit roles.
- **Writer:** tailors your resume truthfully to each posting.
- **Tod:** a second agent that reviews everything independently.
- **Applier:** fills in the application for you to approve.

Nothing is submitted without your yes.

It's built for quality over volume: a few strong, well-targeted applications a week, each one checked twice. The goal
is interview calls, so it covers everything up to submitting and tracking (no interview prep, negotiation or cover letters).

What it adds to a plain resume tailor:
- **More places to look:** 7 job-board APIs, a catalog of 260+ companies you pick by tag, and imports of saved LinkedIn / Indeed job-alert emails.
- **Fit scoring:** a 1–5 score with Apply / Consider / Skip, based on the posting's must-haves. Closed postings, reposts and sponsorship or citizenship requirements are flagged before you spend time on a role.
- **Gaps filled with your experience:** requirements are first matched by intent to what you've done. For what's still missing, the Writer drafts bullets and you approve, edit or reject them. Approvals are saved to your master file and reused for every later application.
- **A screening pass:** the PDF's text layer is checked the way an applicant tracking system reads it, with a keyword-coverage report for the posting. Keywords are only added where your experience backs them.
- **A tracker dashboard:** one local HTML file showing your pipeline, paused drafts vs applied, interview-call rate and follow-ups due.

## How it works

```
Scout (scan, check live/repost/sponsorship, fit 1–5) ──▶ [you pick roles]
  ──▶ Writer (map by intent, reframe, build PDF, screening pass, draft proposals for real gaps)
  ──▶ [you approve / edit / reject proposals] ──▶ approved → master file ──▶ Writer rebuilds
  ──▶ Tod reviews ──▶ [you approve resume] ──▶ Applier fills form ──▶ Tod checks form
  ──▶ [you approve submit] ──▶ tracker + dashboard
```

| Agent | What it does | What it can't do |
|---|---|---|
| **Scout** | Scans company job boards (Greenhouse, Lever, Ashby, Rippling, Workable, SmartRecruiters, Recruitee), a 260+ company catalog, careers sites and saved alert emails; checks each role is live, not a repost and open to your work authorization; scores fit 1–5 | Tailor, apply, touch LinkedIn |
| **Writer** | Maps each requirement to your experience by intent, rewords it in the posting's language, builds the PDF, runs the screening pass, and drafts bullet proposals for real gaps | Browse, talk to you directly, put anything on a resume you haven't approved |
| **Tod** (reviewer) | Checks every claim and every stretch against your master resume, your writing rules, the posting, and the screening report | Edit anything |
| **Applier** | Fills the form from your master resume and stops before Submit | Submit without your yes, enter passwords, automate LinkedIn |

## Your data (private)

Everything personal lives in a **`job-agent-data/`** folder in your working folder, not in this repo:

```
job-agent-data/
├── master_resume.yaml     # every fact you can claim, confirmed_additions (grows as you approve proposals),
│                          # rejected_proposals; the only source of truth, read whole for every application
├── job_preferences.yaml   # function, levels, stages, locations, work authorization, catalog tags, boards
├── writing_style.md       # your rules for how material is written
├── applications.csv       # tracker
├── dashboard.html         # generated from the tracker
├── scout/                 # scans, scan history, alert imports, per-role checks and shortlists
└── applications/<yyyy-mm>-<company>-<role>/
    ├── jd.md  fit.yaml  posting_check.json  tailoring.yaml  proposals.yaml  gap_report.md
    ├── <resume>.pdf  ats_report.md  review_<n>.md  form_snapshot.txt
```

**Never push `job-agent-data/` to a public repo.** `example-data/` shows every file's format with a fictional person.

## Install

**Requirements:**
- Python 3.9+
- `pip install -r requirements.txt` (reportlab, pyyaml, pypdf)
- Recommended: poppler (`brew install poppler` / `apt install poppler-utils`), used for the reading-order, page-count, font and screening checks (pypdf is the fallback)
- For the Scout's careers-site checks and for applying: Claude's built-in browser. If your browser tools have different names, update the `tools:` lines in `agents/scout.md` and `agents/applier.md`.

**Claude Code:**
```
/plugin marketplace add unnatideep1/job-agent
/plugin install job-agent@job-agent
```

**Cowork:** add `unnatideep1/job-agent` as a plugin source from the plugins settings, then install **job-agent**.

## Use

1. "Set up my job-agent profile." Share your resume. Claude builds `job-agent-data/` with you and asks what your resume leaves out.
2. "Run the job hunt." You approve the shortlist, any gap proposals, each resume, and each submission.
3. "Show my job tracker." Opens the dashboard.

From a clone of this repo you can also run the scripts directly:

```
python skills/tailor-resume/scripts/build_resume.py --master job-agent-data/master_resume.yaml \
  --tailoring job-agent-data/applications/<app>/tailoring.yaml --out job-agent-data/applications/<app>/

python skills/tailor-resume/scripts/ats_check.py --master job-agent-data/master_resume.yaml \
  --tailoring <app>/tailoring.yaml --pdf <app>/<resume>.pdf --jd <app>/jd.md

python skills/tailor-resume/scripts/proposals.py prompt|apply --master job-agent-data/master_resume.yaml \
  --proposals <app>/proposals.yaml

python skills/scout-jobs/scripts/scout.py --prefs job-agent-data/job_preferences.yaml \
  --out job-agent-data/scout/latest.csv --seen job-agent-data/applications.csv --history job-agent-data/scout/history.csv
python skills/scout-jobs/scripts/import_alerts.py saved-alert.eml --out job-agent-data/scout/alerts.csv
python skills/scout-jobs/scripts/posting_check.py <posting url> --prefs job-agent-data/job_preferences.yaml
python skills/scout-jobs/scripts/fit_score.py <role>/fit.yaml --master job-agent-data/master_resume.yaml

python skills/job-hunt/scripts/tracker.py dashboard --data job-agent-data --open
```

Run the tests with `python -m unittest discover -s tests` (no network needed).

## Fit scoring

The Scout lists the posting's requirements in `fit.yaml`, each with a weight (must 3, core 2, nice 1), a match
(proven 1, partly 0.5, missing 0) and the master-file ids that prove it. `fit_score.py` computes:

- score = 0.6 × (1 + 4 × coverage) + 0.25 × role fit + 0.15 × preferences fit, minus 0.5 per missing must-have (up to 1.5) and 0.5 if you're 2+ years short of a stated minimum
- **4.0+ Apply, 3.0–3.9 Consider, below 3.0 Skip.** A closed posting or a sponsorship / citizenship conflict forces Skip.
- Evidence ids must exist in your master file. The recommendation is advice: you can override it and the reason is recorded.

## Gaps: map first, then propose

1. **Intent mapping.** For each requirement and keyword the Writer looks for what answers it, even under another name
   ("experimentation" ↔ "A/B tests") or in a neighbouring setting (an evaluation suite answers "AI quality"). A minor,
   truthful reword is recorded as a `stretch` with its evidence, and Tod checks that each one would hold up in an interview.
2. **Proposals, not questions.** For must-have and core requirements that are still uncovered, the Writer drafts bullets for you to approve:
   - **grounded:** extends something in your master file.
   - **UNVERIFIED new claim:** nothing in your file supports it, but it's drafted to fit your roles and seniority.
   You **approve** (only if it's true and you could talk it through in an interview), **edit** or **reject**. Drafts
   never contain numbers that aren't already in your file; you supply any metric.
3. **Your master file learns.** Approved items are saved to `confirmed_additions` (marked candidate-confirmed, with
   the date, the application and the requirement it covers) and every later application can use them. Rejected ones are
   saved to `rejected_proposals` and aren't proposed again for that requirement. No vector store is needed: the file is
   small enough to read whole each time.

## Screening pass

`ats_check.py` reads the finished PDF's text layer the way an applicant tracking system does and writes `ats_report.md`:

- **Parse score (0–100):** readable text, contact details, name at the top, standard headings, embedded fonts, reading order, no broken characters, page limit.
- **Keyword coverage:** each posting keyword is covered, mapped (via a recorded stretch), *surface* (you have it but the resume doesn't say it yet), *propose* (a real gap: goes to proposals) or *unsupported*. An unsupported keyword is an error: keywords are only added where your experience backs them.
- **Advisory:** other terms in the posting (acronyms, common skills) for the Writer to consider.

## Tracker dashboard

`tracker.py upsert` updates one row per posting (keyed on the URL, with a backup). `tracker.py dashboard` writes
`dashboard.html`: one self-contained file with no server or network access. It shows pipeline cards, a funnel,
applications per week, your interview-call rate, paused drafts (applications you started but haven't submitted), follow-ups due or overdue, and a sortable, filterable table with
each role's fit score and screening results.

## What the resume builder enforces

- Every bullet comes from your master file.
- **Rewrites** must keep every number and can't add new ones.
- **New bullets** must cite a fact you approved (`confirmed_additions` with status confirmed or candidate-confirmed) and can only use numbers from it. Unapproved proposals can't be used.
- **Keywords** in rewrites, additions and the summary must be backed by their source, directly, by an alias, or by recorded evidence plus a stretch.
- **Numbers** inside words (B2B, S3) aren't treated as metrics.
- Each role's **first (scope) bullet** stays first and can't be dropped.
- **Sub-products** stay separate, and **every role** is rendered.
- **Core Strengths** come only from your approved list.
- **Markup** is limited to bold, italic and underline.
- **Layout:** the PDF is checked so screening software reads company → title → dates → bullets in order, and it switches to inline dates if not. It also warns if the page limit is exceeded.

## Principles

- **Map and reframe first, then fill gaps.** Existing facts are matched by intent and reworded in the posting's language. Only what's still missing becomes a proposal, so you aren't asked a question every time a word doesn't match.
- **No unapproved claims.** The Writer may draft a new bullet, but it stays a proposal until you say it's true. Drafts never invent numbers.
- **Independent review.** The agent that writes or fills a form never approves its own work.
- **You approve** the shortlist, the resume and every submission.
- **No LinkedIn automation.** It breaks LinkedIn's terms and risks your account. Reach out to people directly instead.

## Status

v0.2:
- **Applying:** Greenhouse forms only. Lever, Ashby and Workday skills are next.
- **Scanner:** every catalog board answered its public API when the catalog was built; boards move, so the scan lists any that fail.
- **Install:** test on a real install in Claude Code and Cowork before tagging a release, to confirm `${CLAUDE_PLUGIN_ROOT}` paths and agent skill preloading work.

## Credits

Several ideas are adapted from [career-ops](https://github.com/career-ops-hq/career-ops) (MIT), reimplemented
here in Python: the 1–5 fit score with weighted requirements and "don't apply below 4.0", posting liveness and repost
(ghost job) checks, the work-authorization blocker, the portal catalog, LinkedIn job-alert email import, ATS
parse checks, keyword coverage, and the tracker layout.

## License

MIT
