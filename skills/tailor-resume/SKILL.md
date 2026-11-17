---
name: tailor-resume
description: Tailor the candidate's resume to one job posting. First reframe existing facts in the JD's language, then run a job-seeker gap analysis that produces specific questions for the candidate, then rebuild with any facts they confirm. Use when a role has been picked and needs a tailored resume.
---

# Tailor resume

`DATA` = `job-agent-data/` in the working folder; `APP` = `DATA/applications/<yyyy-mm>-<company>-<role>/`.

Read first: `DATA/writing_style.md` (the candidate's rules; they override this skill), `DATA/master_resume.yaml`, and the full JD. Format reference: `${CLAUDE_PLUGIN_ROOT}/example-data/applications/example-gpm-ai/tailoring.yaml`.

## Pass 1

**1. Save the JD** to `APP/jd.md`, including "what we need", "mandatory qualifications", the URL and the first-published date.

**2. Requirement map.** List the JD's requirements in the JD's own order of emphasis. For each, mark Proven / Partly / Missing and cite the bullet ids that prove it.

**3. Reframe existing material.** Write `APP/tailoring.yaml`:
- `summary`: to the point, in the voice `writing_style.md` asks for, leading with what the JD ranks first. If the candidate supplied a summary, use theirs.
- `strengths`: chosen and ordered from `strengths_library`. To suggest a new phrase, list it in your report; only the candidate can approve it.
- `order`: bullet order per role and section, by JD priority. The builder keeps each scope bullet first.
- `rewrites`: rewording of existing bullets into the JD's language. Keep the meaning and every number, and give each a `why` (the JD term it maps to). Never retitle roles.
- `omit`: only if needed to fit the page limit; older roles first, never a scope bullet.

**4. Gap analysis (think like a job seeker).** Write `APP/gap_report.md`:
- **Questions for the candidate:** one specific question per Partly/Missing item, for example "This JD asks for SQL and dashboards. Have you written SQL or built dashboards? Where, and for what?" Also probe things people leave off resumes: experiments and A/B tests, tools, team size managed, revenue/P&L/pricing ownership, customer counts, scale.
- **Screener risks:** what an ATS or screening agent will compute (years in `function` vs the minimum, title mismatch, gaps) and how to handle each (referral, outreach note, interview answer).

**5. Build** (see below) and return the PDF path, the change list and the questions. **Stop.** You cannot talk to the candidate; the orchestrator asks the questions and records confirmed answers in `confirmed_additions`.

## Pass 2 (after the orchestrator records answers)

For each new `confirmed_additions` id, add it under `additions:` (`from: <id>`, `section`, `after: <bullet id>`, `text`) next to the bullet it relates to. Rewrites can't carry new facts or numbers (the builder rejects them), so new facts always go in as additions. If an addition makes an existing bullet redundant, ask the orchestrator before omitting that bullet. Rebuild.

## Build

```
python "${CLAUDE_PLUGIN_ROOT}/skills/tailor-resume/scripts/build_resume.py" \
  --master DATA/master_resume.yaml --tailoring APP/tailoring.yaml --out APP/
```

The builder refuses:
- unknown bullet or role ids
- rewrites that drop or add numbers, and duplicate ids in `order`
- additions that don't come from a confirmed addition, or that use numbers not in that confirmed fact
- omitting a scope bullet
- strengths outside the library

It checks the reading order and the page count, and switches to inline dates if a parser would misread the layout. Fix every ERROR. Report every WARNING to Tod.

## Change list

Report exactly what differs from the master resume: the summary, the strengths, bullets moved, each rewrite (before → after), each addition and each omission. When the candidate asks for an edit, change only that resume and only what they asked.
