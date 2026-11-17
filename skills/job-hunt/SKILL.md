---
name: job-hunt
description: Run the end-to-end job search pipeline (scout roles, tailor resume, independent review, fill application, submit with approval, track). Use when the user wants to find jobs, apply to a role, tailor a resume for a posting, or check on their applications.
---

# Job hunt (orchestrator)

You coordinate four agents and keep the user in control at three checkpoints. You talk to the user; the agents don't. You never tailor, review or submit yourself.

## Paths

- `PLUGIN = ${CLAUDE_PLUGIN_ROOT}` – this plugin (scripts, examples). Never write user data here.
- `DATA` = `job-agent-data/` in the user's working folder. It holds everything personal and must never be committed to a public repo:
  - `master_resume.yaml` – source of truth for every claim (incl. `confirmed_additions`)
  - `job_preferences.yaml` – what to look for
  - `writing_style.md` – the candidate's rules for all written material
  - `applications.csv` – the tracker
  - `scout/` – scan results and shortlists
  - `applications/<yyyy-mm>-<company>-<role>/` – `jd.md`, `gap_report.md`, `tailoring.yaml`, the PDF, `review_<n>.md`, `form_snapshot.txt`

If `DATA` doesn't exist, run the **setup-profile** skill first.

## Pipeline

1. **Scout** (agent `scout`) → shortlist in `DATA/scout/`.
   **Checkpoint 1:** the user picks roles (respect `volume.max_tailored_per_week`).
2. **Writer, pass 1** (agent `writer`) → `jd.md`, requirement map, reframed `tailoring.yaml`, PDF, and `gap_report.md` with questions.
3. **You ask the user the gap questions.** Record every confirmed answer in `DATA/master_resume.yaml` → `confirmed_additions` (`id`, `fact`, `confirmed` (date), `question`). Unconfirmed answers are not recorded. If the user approves a new Core Strengths phrase, add it to `strengths_library` yourself; the Writer can't.
4. **Writer, pass 2** → uses the new confirmed additions (`additions:` in `tailoring.yaml`) and rebuilds.
5. **Tod** (agent `reviewer-tod`) → save his report as `review_<n>.md`. Loop Writer ↔ Tod until READY.
   **Checkpoint 2:** show the user the PDF, the change list and Tod's verdict; apply only the edits they ask for, only to that resume.
6. **Applier** (agent `applier`) → fills the form, asks the user to attach the PDF, stops before Submit, writes `form_snapshot.txt`.
7. **Tod** reviews the form snapshot against the master file and the attached resume. Save his report as `form_review_<n>.md`.
   **Checkpoint 3:** the user says yes in chat → the Applier submits, confirms the confirmation page, updates `applications.csv`.
8. For strong-fit roles, suggest a referral or direct outreach to the hiring team.

## Rules

- Never submit, send a message or create an account without the user's explicit yes in chat.
- Never automate LinkedIn.
- Change only the application the user names.
- Keep updates short; the user can open the files.
