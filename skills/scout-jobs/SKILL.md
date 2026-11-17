---
name: scout-jobs
description: Find open roles that match the candidate's job_preferences.yaml on company job boards (Greenhouse, Lever, Ashby, Rippling) and careers sites, verify they are live, and score fit against master_resume.yaml. Use when asked to find, scout or shortlist jobs.
---

# Scout jobs

`DATA` = `job-agent-data/` in the working folder. Scripts live in `${CLAUDE_PLUGIN_ROOT}`.

## 1. Collect

```
python "${CLAUDE_PLUGIN_ROOT}/skills/scout-jobs/scripts/scout.py" --prefs DATA/job_preferences.yaml \
  --out DATA/scout/<yyyy-mm-dd>.csv --seen DATA/applications.csv
```

It uses only public JSON board APIs, matches titles and locations as whole words, filters by `departments` (where the board reports one), flags postings older than `posting.max_age_days`, and skips roles already in the tracker. Boards that fail are listed at the end; the rest of the scan still completes.

Then check each URL in `sources.careers_sites` (companies without a public board) with the browser. Many careers sites load results from a JSON search API you can call from their own pages (for example Microsoft's `/api/pcsx/search`); check the page's network requests to find it.

Optionally search the web for high-growth companies matching `company_stage` and `domain` that aren't in `sources`, and propose their board ids to the user.

**Never** scrape or automate LinkedIn.

## 2. Verify each candidate

- Open the posting on the company's own board; confirm it is live. Record the first-published date (Greenhouse: `GET /v1/boards/<board>/jobs/<id>` returns `first_published`).
- Check company stage against `company_stage`. If you can't confirm it, write "unconfirmed".
- Apply `target_levels.vp_only_if_stage`.

## 3. Score fit (1–10)

List the JD's requirements in its own order. Mark each Proven / Partly / Missing against `master_resume.yaml`. Adjust for:

- **Hard gaps a screener computes**, especially minimum years in `function`: count only roles whose titles belong to that function.
- `domain.preferred` (bonus, not a requirement unless `ai_required: true`).

## 4. Output

Write `DATA/scout/<date>-shortlist.md`: a ranked table (role with link, company, location, posted/age, fit score, one-line why, main gap), at most `volume.shortlist_size` rows. Return it to the orchestrator for Checkpoint 1.
