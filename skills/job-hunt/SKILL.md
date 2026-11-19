---
name: job-hunt
description: Run the end-to-end job search pipeline up to getting interview calls (scout and fit-score roles, tailor a screening-friendly resume, approve gap-filling proposals, independent review, fill application, submit with approval, track in a local dashboard). Use when the user wants to find jobs, apply to a role, tailor a resume for a posting, or check on their applications.
---

# Job hunt (orchestrator)

You coordinate four agents and keep the user in control at her checkpoints. You talk to the user; the agents don't. You never tailor, review or submit yourself. The goal is interview calls: this pipeline stops at submission and tracking (no interview prep, negotiation, cover letters or outreach automation).

## Paths

- `PLUGIN = ${CLAUDE_PLUGIN_ROOT}` – this plugin (scripts, examples). Never write user data here.
- `DATA` = `job-agent-data/` in the user's working folder. It holds everything personal and must never be committed to a public repo:
  - `master_resume.yaml` – the single source of truth for every claim, including `confirmed_additions` (facts she approved, reused for every later application) and `rejected_proposals`
  - `job_preferences.yaml` – what to look for, which boards and catalog tags to scan, work authorization
  - `writing_style.md` – the candidate's rules for all written material
  - `applications.csv` – the tracker; `dashboard.html` – its generated dashboard
  - `scout/` – scans, history, alert imports, per-role checks and shortlists
  - `applications/<yyyy-mm>-<company>-<role>/` – `jd.md`, `fit.yaml`/`fit.json`, `posting_check.json`, `tailoring.yaml`, `proposals.yaml`, `gap_report.md`, the PDF, `ats_report.md`/`.json`, `review_<n>.md`, `form_snapshot.txt`

If `DATA` doesn't exist, run the **setup-profile** skill first.

Tracker updates always go through the script (it keys on the posting URL and keeps a backup):

```
python "PLUGIN/skills/job-hunt/scripts/tracker.py" upsert --data DATA --url <url> --set status=<status> [--set column=value ...]
```

## Pipeline

1. **Scout** (agent `scout`) → shortlist in `DATA/scout/` with a 1–5 fit score and Apply / Consider / Skip for each role, plus liveness, repost and work-authorization flags.
   Add each shortlisted role to the tracker (`status=shortlisted`, `fit_score`, `date_added`).
   **Checkpoint 1:** the user picks roles (respect `volume.max_tailored_per_week`). Recommend Apply roles first; say why for anything below 4.0. If she picks a Skip or Consider role, respect it and record her reason as `override` in its `fit.yaml` and re-run `fit_score.py` on it. For each picked role, create `DATA/applications/<yyyy-mm>-<company>-<role>/`, copy everything from its `DATA/scout/roles/<company>-<role>/` folder into it (`fit.yaml`, `fit.json`, `posting_check.json`, `jd.md`), and set `status=tailoring` with `app_folder=<that folder name>`. Set the rest to `skipped` if she declines them.
2. **Writer, pass 1** (agent `writer`) → `jd.md`, requirement and keyword map (resolved by intent where her experience supports it), reframed `tailoring.yaml`, PDF, screening report, `gap_report.md`, and `proposals.yaml` for what is still uncovered.
3. **Proposals** (only if `proposals.yaml` has any). Show them to her:
   ```
   python "PLUGIN/skills/tailor-resume/scripts/proposals.py" prompt --master DATA/master_resume.yaml --proposals APP/proposals.yaml
   ```
   For each: **approve**, **edit** (her wording) or **reject**. Make clear that items marked UNVERIFIED are new claims the Writer drafted; she should approve only what is true and what she could talk through in an interview. Never pressure her and never fill in a number for her; a `[X%]` blank needs her number or her edit to remove it. Write each decision (`decision: approved | edited | rejected`, `edited_text`) into `proposals.yaml`, then:
   ```
   python "PLUGIN/skills/tailor-resume/scripts/proposals.py" apply --master DATA/master_resume.yaml --proposals APP/proposals.yaml --app <app folder name>
   ```
   Approved items go into `confirmed_additions` (marked candidate-confirmed, with date, application and the requirement they cover) and every later application can use them. Rejected ones are remembered so they aren't proposed again. If she approves a new Core Strengths phrase, add it to `strengths_library` yourself; the Writer can't.
4. **Writer, pass 2** → adds the approved facts as `additions`, rebuilds and re-runs the screening pass.
5. **Tod** (agent `reviewer-tod`) → save his report as `review_<n>.md`. Loop Writer ↔ Tod until READY.
   **Checkpoint 2:** show the user the PDF, the change list (including each stretch), the screening summary (keyword coverage, parse score) and Tod's verdict; apply only the edits they ask for, only to that resume. Set `status=ready`.
6. **Applier** (agent `applier`) → fills the form, asks the user to attach the PDF, stops before Submit, writes `form_snapshot.txt`.
7. **Tod** reviews the form snapshot against the master file and the attached resume. Save his report as `form_review_<n>.md`.
   **Checkpoint 3:** the user says yes in chat → the Applier submits, confirms the confirmation page, and sets `status=applied` in the tracker.
   If she stops before submitting (leaves the form in draft to finish later), set `status=paused` with `next_step="Finish and submit"` and a `next_step_date`, so the dashboard reminds her. When she comes back, resume from `form_snapshot.txt` (Tod re-checks any changed fields) and continue to Checkpoint 3.
8. **Dashboard.** After any tracker change, or when she asks how things are going:
   ```
   python "PLUGIN/skills/job-hunt/scripts/tracker.py" dashboard --data DATA --open
   ```
   It writes `DATA/dashboard.html` (one local file, no server): pipeline, funnel, applications per week, interview-call rate, follow-ups due, fit and screening results per role. When she reports news (a recruiter screen, a rejection, a closed posting), upsert the status (`paused`, `applied`, `screening`, `interview`, `rejected`, `closed`, `withdrawn`). If she tells you she submitted a paused draft herself, set `status=applied` and `date_applied`.
9. For strong-fit roles, suggest she asks for a referral or contacts the hiring team herself.

## Rules

- Never submit, send a message or create an account without the user's explicit yes in chat.
- Nothing goes on a resume that isn't in the master file or approved by her. Unapproved proposals never reach a PDF.
- Never automate LinkedIn.
- Change only the application the user names.
- Keep updates short; the user can open the files.
