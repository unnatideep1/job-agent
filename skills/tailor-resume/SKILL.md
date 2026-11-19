---
name: tailor-resume
description: Tailor the candidate's resume to one job posting. Map every JD requirement and keyword to her real experience by intent, reframe it in the JD's language, draft bullet proposals for what is still uncovered (the candidate approves or rejects them; approved ones are saved to the master file for reuse), then build a screening-friendly PDF and run the keyword and parse checks. Use when a role has been picked and needs a tailored resume.
---

# Tailor resume

`DATA` = `job-agent-data/` in the working folder; `APP` = `DATA/applications/<yyyy-mm>-<company>-<role>/`.
`SCRIPTS` = `${CLAUDE_PLUGIN_ROOT}/skills/tailor-resume/scripts`.

Read first: `DATA/writing_style.md` (the candidate's rules; they override this skill), all of `DATA/master_resume.yaml`
(including `confirmed_additions` from earlier applications, which you can reuse, and `rejected_proposals`), the full JD,
and `APP/fit.yaml` if the Scout wrote one. Format references in `${CLAUDE_PLUGIN_ROOT}/example-data/applications/example-gpm-ai/`:
`tailoring.yaml`, `proposals.yaml`, `fit.yaml`.

The master file is the only source of truth and is small enough to read whole every time. Nothing reaches the PDF
unless it is in the master file: bullets, or `confirmed_additions` the candidate approved.

## Pass 1

**1. Save the JD** to `APP/jd.md`, including "what we need", "mandatory qualifications", the URL and the first-published
date (`posting_check.py --jd-out` may already have saved the text).

**2. Requirement and keyword list.** List the JD's requirements in its own order of emphasis (start from `fit.yaml` if it
exists). Pull out the terms a screening tool will search for: skills, domains, tools the JD names, the title's key words.
Give each a priority: `must` (stated as required), `core` (central to the role), `nice` (preferred / bonus).

**3. Map by intent before anything else.** Don't stop at exact word matches. For each requirement and keyword, look for
the fact that answers it, in this order:
- **Direct:** a bullet already says it. Surface it on page 1 in the JD's words.
- **Synonym:** the same thing under another name ("experimentation" ↔ "A/B tests", "enterprise" ↔ "large business
  customers"). Add the other names as `aliases`.
- **Parallel experience:** a fact that proves the same capability in a neighbouring setting ("evaluation suite for the AI
  assistant" answers "AI quality"; "launched usage-based billing" answers "pricing"). A minor, truthful stretch or reword
  is fine. Record the bullet ids in `evidence` and one line in `stretch` saying why it's a fair reading. Tod checks
  every stretch, so it must hold up if a recruiter asks about it.
- **Earlier approvals:** `confirmed_additions` the candidate approved for other applications. Reuse them as additions.

A stretch can change wording, emphasis and framing. It can never add a fact, a tool, a scope, a team size or a number
the source doesn't have. Only requirements still uncovered after all of this go to step 5. Most JDs need few or none.

**4. Reframe.** Write `APP/tailoring.yaml`:
- `summary`: one coherent argument for this job (who → proof → why it matters here), in the voice `writing_style.md`
  asks for, leading with what the JD ranks first. If it names a count, it names every item. If the candidate supplied a
  summary, use theirs.
- `strengths`: chosen and ordered from `strengths_library`. To suggest a new phrase, list it in your report; only the
  candidate can approve it.
- `order`: bullet order per role and section, by JD priority. The builder keeps each scope bullet first.
- `rewrites`: this is where the tailoring happens. Rewrite every page-1 bullet (and relevant page-2 bullets) so it opens
  with what it proves for this JD, in the JD's vocabulary. Keep the facts and every number. Give each a `why`. Reordering
  alone is not tailoring. Never retitle roles.
- `keywords`: every term from step 2 with `priority`, `aliases`, and for intent-mapped terms `evidence` + `stretch`.
  The builder refuses a keyword in a rewrite, addition or summary that its source doesn't back.
- `omit`: only if needed to fit the page limit; older roles first, never a scope bullet.

**5. Propose bullets for what's still uncovered** (must and core only; let nice-to-haves go). Don't write open questions.
Write `APP/proposals.yaml` with one or two drafts per uncovered requirement, at most about five in total:
- `kind: grounded` when the draft extends something in the master file. List those ids in `inspired_by`.
- `kind: new-claim` when nothing in the master file supports it. Draft something that plausibly fits her actual roles,
  companies, products and seniority, modelled on the style of her bullets (`inspired_by` the bullets you modelled it on).
  It is **UNVERIFIED**: only she knows whether it happened.
- No new metrics. Use only numbers that appear in the `inspired_by` facts. New-claim drafts carry no numbers at all;
  leave a blank such as `[X%]` if a metric would help, for her to fill in or drop.
- Never re-propose an idea in `rejected_proposals` for the same requirement.
- Run `python "SCRIPTS/proposals.py" check --master DATA/master_resume.yaml --proposals APP/proposals.yaml` and fix
  every ERROR.

Proposals never go into `tailoring.yaml`. The builder only accepts `additions` that cite an approved `confirmed_additions` id.

**6. Build and run the screening pass** (see below). Act on the report: reword bullets for `surface` terms; any
`unsupported` term is an error to remove.

**7. Gap report.** Write `APP/gap_report.md`: what you mapped by intent (term → evidence → stretch), the proposals
(grounded vs UNVERIFIED new claim), keyword coverage and parse score from the screening report, and **screener risks**
(years in `function` vs the minimum, title mismatch, gaps, location) with how to handle each.

Return the PDF path, the change list, the proposals and the screening summary. **Stop.** You cannot talk to the
candidate; the orchestrator shows her the proposals (`proposals.py prompt`) and records her answers.

## Pass 2 (after the orchestrator records her decisions)

The orchestrator runs `proposals.py apply`, which saves approved and edited proposals to `confirmed_additions`
(`status: candidate-confirmed`, with the date, source application and the requirement covered) and rejected ones to
`rejected_proposals`. For each newly approved id, add it under `additions:` (`from: <id>`, `section`, `after: <bullet id>`,
`text`) next to the bullet it relates to, and add the term to `keywords` with that id as evidence. Rewrites can't carry
new facts or numbers, so new facts always go in as additions. If an addition makes an existing bullet redundant, ask the
orchestrator before omitting that bullet. Rebuild and re-run the screening pass.

## Build and screening pass

```
python "SCRIPTS/build_resume.py" --master DATA/master_resume.yaml --tailoring APP/tailoring.yaml --out APP/
python "SCRIPTS/ats_check.py" --master DATA/master_resume.yaml --tailoring APP/tailoring.yaml \
  --pdf APP/<output_name>.pdf --jd APP/jd.md
```

The builder refuses:
- unknown bullet or role ids, and duplicate ids in `order`
- rewrites that drop or add numbers (digits inside words such as B2B don't count as numbers)
- additions that don't cite a candidate-approved `confirmed_additions` id, or use numbers not in that fact
- a JD keyword in a rewrite, addition or summary that its source doesn't back (directly, by alias, or by `evidence` + `stretch`)
- omitting a scope bullet, and strengths outside the library

It checks the reading order and page count and switches to inline dates if a parser would misread the layout.

`ats_check.py` reads the PDF's text layer the way an applicant tracking system does and writes `APP/ats_report.md` and
`.json`:
- **Parse score (0–100):** readable text, email and phone, name at the top, standard headings, embedded fonts, reading
  order, no broken glyphs, page limit. Below 70 is an error. Lints flag characters some parsers drop (e.g. `→`).
- **Keyword coverage:** each keyword is `covered`, `mapped` (via your stretch), `surface` (backed but not on the
  resume yet: reword the listed bullet), `propose` (must/core with no backing: step 5), `missing-ok` (nice-to-have with no
  backing) or `unsupported` (on the resume with no backing: error).
- **Advisory:** JD terms (acronyms, common skills) not in your keyword list. Consider each; add only what's true.

Fix every ERROR. Report every WARNING and the screening summary to Tod.

## Change list

Report exactly what differs from the master resume: the summary, the strengths, bullets moved, each rewrite
(before → after, with any stretch), each addition and each omission. When the candidate asks for an edit, change only
that resume and only what they asked.
