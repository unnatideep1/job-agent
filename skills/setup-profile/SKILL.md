---
name: setup-profile
description: Create a new candidate's private data folder (master_resume.yaml, job_preferences.yaml, writing_style.md, tracker) from their resume and a short interview. Use when job-agent-data/ is missing or someone wants to start their own job search with this plugin.
---

# Set up a candidate profile

1. **Create the data folder.** Create `job-agent-data/` in the user's working folder, never inside the plugin folder. Tell the user it holds personal data and must not be pushed to a public repo. Copy these from `${CLAUDE_PLUGIN_ROOT}/example-data/`:
   - `applications.csv`: just the header row (the tracker script adds any missing columns later).
   - `writing_style.md`: the starting rules.
   - Don't copy the example's `applications/` folder.
   - Create empty `applications/` and `scout/` folders.
2. **Read the resume.** Ask for the candidate's current resume (PDF or DOCX) and read all of it.
3. **Write `master_resume.yaml`** in the same format as `${CLAUDE_PLUGIN_ROOT}/example-data/master_resume.yaml`:
   - One entry per company and one per role. Sub-products become separate `sections`, each with a `heading`.
   - The first bullet of each section is its scope bullet.
   - Copy every bullet and number word for word, and give each a stable id.
   - Ask the candidate to label each role's `product_type` (B2B, B2C or both). Never guess.
   - Set `page_size` (A4 or letter) and `max_pages`.
   - Ask which phrases belong in `strengths_library`.
4. **Ask about what's missing.** People leave a lot off their resumes, so ask about:
   - experiments run
   - tools used
   - team size managed
   - revenue, P&L or pricing ownership
   - scale numbers
   - side projects
   - awards

   Record every confirmed answer in `confirmed_additions` with `id`, `fact`, `status: confirmed`, `confirmed` (date), `question` and `role`. Later, gap proposals she approves are added here automatically (`status: candidate-confirmed`), and every application reads this list, so the file grows into her full record.
5. **Write `job_preferences.yaml`** (format: `${CLAUDE_PLUGIN_ROOT}/example-data/job_preferences.yaml`). Ask for:
   - `function`
   - target titles and levels
   - company stages
   - domains
   - locations, remote and relocation
   - deal-breakers
   - weekly volume
   - work authorization: does she need visa sponsorship now or later; can she meet citizenship or security-clearance requirements (`work_authorization`)
   - titles that count toward her years in the function (`function_titles`)

   Suggest catalog tags (`catalog: {tags: [...]}`; see `${CLAUDE_PLUGIN_ROOT}/skills/scout-jobs/portals.yaml`) and company boards to add under `sources`. If she gets LinkedIn or other job-alert emails, tell her she can save them as .eml or .txt for the Scout to import; it never logs in to LinkedIn.
6. **Edit `writing_style.md` with them.** Ask about tone, words to avoid, summary style, and whether to write in the first person.
7. **Check the result.** Create `DATA/applications/_baseline/tailoring.yaml` containing only `output_name: Baseline`, build it into that folder, and ask the candidate to confirm the PDF matches their original resume.
