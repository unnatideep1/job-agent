---
name: apply-greenhouse
description: Fill a Greenhouse job application form in the browser from master_resume.yaml, stop before Submit, and capture a form snapshot for review. Use when the candidate has approved a tailored resume for a Greenhouse-hosted role (job-boards.greenhouse.io or a company page embedding Greenhouse).
---

# Apply on Greenhouse

`DATA` = `job-agent-data/`; `APP` = the application folder.

## Before you start

- Make sure the candidate approved the tailored resume (Checkpoint 2).
- Open the posting URL and click **Apply**.
- List every form field (label and whether it's required) before filling anything, so nothing is missed.

## Fill

- **Contact:** name, email, phone and location, from `person` in the master file. For the phone, pick the country code in the dropdown, then type the local number.
- **Resume/CV:** you can't attach local files. Ask the candidate to click **Attach** and choose the exact PDF filename. If the resume changes, ask them to remove the old file and attach it again.
- **Employment:** enter **every role** from the master file, most recent first, with the current role flagged. Click "Add another" for each one.
  - Use titles exactly as held, and months and years exactly as in the master file.
  - Month fields are dropdowns: click the field, type the month name, press Enter. Setting the value with JavaScript doesn't register on these. Company, title and year are plain text fields.
  - After filling, read back every entry and compare it with the master file.
- **Custom questions:**
  - Answer only from the master file or the candidate. Ask the candidate for anything personal or unknown, such as gender, demographics, website, notice period, salary or visa. Never guess.
  - If a dropdown has no option that fits, pick the closest honest one and tell the candidate.
- **Years of experience:** total span minus gaps, from the master dates. Show the maths in the snapshot.

## Stop before Submit

Write `APP/form_snapshot.txt` with every field, its value and the attached filename. Hand it to Tod, then show the candidate the filled values and Tod's verdict.

## Submit (Checkpoint 3)

Only after the candidate says yes in chat:

1. Check that the latest PDF is attached.
2. Click **Submit application**.
3. Confirm the confirmation page has loaded.
4. Update the tracker (it keys on the posting URL, so this updates the row the orchestrator created):
   ```
   python "${CLAUDE_PLUGIN_ROOT}/skills/job-hunt/scripts/tracker.py" upsert --data DATA --url <posting url> \
     --set status=applied --set date_applied=<yyyy-mm-dd> --set resume_file=<pdf filename> \
     --set next_step="Follow up if no reply" --set next_step_date=<date + 7 days>
   ```

If the candidate wants to pause before submitting, don't submit. Keep `APP/form_snapshot.txt` current and set:
```
python "${CLAUDE_PLUGIN_ROOT}/skills/job-hunt/scripts/tracker.py" upsert --data DATA --url <posting url> \
  --set status=paused --set next_step="Finish and submit" --set next_step_date=<yyyy-mm-dd>
```

Other ATSs (Lever, Ashby, Workday) need their own skill. Follow the same structure.
