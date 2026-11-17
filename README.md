# job-agent

A Claude plugin for a careful, human-approved job search:

- **Scout:** finds high-fit roles.
- **Writer:** tailors your resume truthfully to each posting.
- **Tod:** a second agent that reviews everything independently.
- **Applier:** fills in the application for you to approve.

Nothing is submitted without your yes.

It's built for quality over volume: a few strong, well-targeted applications a week, each one checked twice.

## How it works

```
Scout ──▶ [you pick roles] ──▶ Writer (reframe + gap questions) ──▶ you answer ──▶ Writer rebuilds
      ──▶ Tod reviews ──▶ [you approve resume] ──▶ Applier fills form ──▶ Tod checks form
      ──▶ [you approve submit] ──▶ tracker
```

| Agent | What it does | What it can't do |
|---|---|---|
| **Scout** | Scans company job boards (Greenhouse, Lever, Ashby, Rippling) and careers sites, checks each role is live, scores fit, flags gaps | Tailor, apply, touch LinkedIn |
| **Writer** | Rewords your experience in the posting's language, finds what the posting asks for that your resume doesn't show, writes questions for you, builds the PDF | Browse, talk to you directly, use facts you haven't confirmed |
| **Tod** (reviewer) | Checks every claim against your master resume, your writing rules, the posting, and what a screening tool will compute | Edit anything |
| **Applier** | Fills the form from your master resume and stops before Submit | Submit without your yes, enter passwords, automate LinkedIn |

## Your data (private)

Everything personal lives in a **`job-agent-data/`** folder in your working folder, not in this repo:

```
job-agent-data/
├── master_resume.yaml     # every fact you can claim, plus confirmed_additions; the only source of truth
├── job_preferences.yaml   # function, levels, company stages, locations, boards to scan
├── writing_style.md       # your rules for how material is written
├── applications.csv       # tracker
├── scout/                 # scans and shortlists
└── applications/<yyyy-mm>-<company>-<role>/
    ├── jd.md  gap_report.md  tailoring.yaml  <resume>.pdf  review_<n>.md  form_snapshot.txt
```

**Never push `job-agent-data/` to a public repo.** `example-data/` shows every file's format with a fictional person.

## Install

**Requirements:**
- Python 3.9+
- `pip install -r requirements.txt` (reportlab, pyyaml)
- Recommended: poppler (`brew install poppler` / `apt install poppler-utils`), used for the automatic reading-order and page-count checks
- For the Scout's careers-site checks and for applying: Claude's built-in browser. If your browser tools have different names, update the `tools:` lines in `agents/scout.md` and `agents/applier.md`.

**Claude Code:**
```
/plugin marketplace add unnatideep1/job-agent
/plugin install job-agent@job-agent
```

**Cowork:** add `unnatideep1/job-agent` as a plugin source from the plugins settings, then install **job-agent**.

## Use

1. "Set up my job-agent profile." Share your resume. Claude builds `job-agent-data/` with you and asks what your resume leaves out.
2. "Run the job hunt." You approve the shortlist, each resume, and each submission.

From a clone of this repo you can also run the scripts directly:

```
python skills/tailor-resume/scripts/build_resume.py --master job-agent-data/master_resume.yaml \
  --tailoring job-agent-data/applications/<app>/tailoring.yaml --out job-agent-data/applications/<app>/

python skills/scout-jobs/scripts/scout.py --prefs job-agent-data/job_preferences.yaml \
  --out job-agent-data/scout/latest.csv --seen job-agent-data/applications.csv
```

## What the resume builder enforces

- Every bullet comes from your master file.
- **Rewrites** must keep every number and can't add new ones.
- **New bullets** must cite a fact you confirmed (`confirmed_additions`) and can only use numbers from it.
- Each role's **first (scope) bullet** stays first and can't be dropped.
- **Sub-products** stay separate, and **every role** is rendered.
- **Core Strengths** come only from your approved list.
- **Markup** is limited to bold, italic and underline.
- **Layout:** the PDF is checked so screening software reads company → title → dates → bullets in order, and it switches to inline dates if not. It also warns if the page limit is exceeded.

## Principles

- **Reframe first, then fill gaps.** Existing facts are reworded in the posting's language. The Writer then asks you about what the posting wants that your resume doesn't show.
- **No unconfirmed claims.** New facts are welcome once you confirm them.
- **Independent review.** The agent that writes or fills a form never approves its own work.
- **You approve** the shortlist, the resume and every submission.
- **No LinkedIn automation.** It breaks LinkedIn's terms and risks your account. Reach out to people directly instead.

## Status

v0.1:
- **Applying:** Greenhouse forms only. Lever, Ashby and Workday skills are next.
- **Scanner:** tested on sample data only. Run it once on your machine to confirm it can reach the job-board APIs.
- **Install:** test on a real install in Claude Code and Cowork before tagging a release, to confirm `${CLAUDE_PLUGIN_ROOT}` paths and agent skill preloading work.

## License

MIT
