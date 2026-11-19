import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date

from helpers import EXAMPLE, ROOT, master, tailoring
import ats_check
import tracker

PY = sys.executable
BUILD = os.path.join(ROOT, "skills/tailor-resume/scripts/build_resume.py")


class Screening(unittest.TestCase):
    """End to end: build the example PDF and run the screening pass on it (needs reportlab)."""

    @classmethod
    def setUpClass(cls):
        try:
            import reportlab  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("reportlab not installed")
        cls.out = tempfile.mkdtemp()
        app = os.path.join(EXAMPLE, "applications/example-gpm-ai")
        r = subprocess.run([PY, BUILD, "--master", os.path.join(EXAMPLE, "master_resume.yaml"),
                            "--tailoring", os.path.join(app, "tailoring.yaml"), "--out", cls.out],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        cls.pdf = r.stdout.strip().splitlines()[-1]
        cls.text, cls.how = ats_check.pdf_text(cls.pdf)
        if cls.text is None:
            raise unittest.SkipTest("no PDF text extractor (poppler or pypdf)")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def test_parse_score(self):
        score, checks, _ = ats_check.parse_checks(self.text, master(), tailoring(), self.pdf,
                                                  ats_check.rendered_first_bullets(master(), tailoring()))
        failed = [c["name"] for c in checks if not c["ok"]]
        self.assertGreaterEqual(score, 90, failed)

    def test_keyword_statuses(self):
        rows, cov = ats_check.keyword_report(master(), tailoring(), self.text)
        st = {r["term"]: r["status"] for r in rows}
        self.assertEqual(st["experimentation"], "covered")
        self.assertEqual(st["enterprise customers"], "mapped")
        self.assertEqual(st["agent platforms"], "propose")
        self.assertEqual(cov, 80)

    def test_surface_missing_ok_and_unsupported(self):
        t = tailoring()
        t["keywords"] += [{"term": "usage-based billing", "priority": "core"},
                          {"term": "Kubernetes", "priority": "nice"},
                          {"term": "Example Corp", "priority": "nice"}]
        m = master()
        m["strengths_library"] = [s for s in m["strengths_library"] if s != "Usage-based pricing"]
        rows, _ = ats_check.keyword_report(m, t, self.text + " Kubernetes")
        st = {r["term"]: r["status"] for r in rows}
        self.assertEqual(st["Kubernetes"], "unsupported")
        self.assertEqual(st["Example Corp"], "covered")
        rows, _ = ats_check.keyword_report(m, t, self.text.replace("billing", ""))
        self.assertEqual({r["term"]: r["status"] for r in rows}["usage-based billing"], "surface")
        t["keywords"] = [{"term": "Kubernetes", "priority": "nice"}]
        self.assertEqual(ats_check.keyword_report(m, t, self.text)[0][0]["status"], "missing-ok")

    def test_cli_writes_reports(self):
        app = os.path.join(EXAMPLE, "applications/example-gpm-ai")
        r = subprocess.run([PY, os.path.join(ROOT, "skills/tailor-resume/scripts/ats_check.py"),
                            "--master", os.path.join(EXAMPLE, "master_resume.yaml"),
                            "--tailoring", os.path.join(app, "tailoring.yaml"), "--pdf", self.pdf, "--out", self.out],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.out, "ats_report.json")) as f:
            rep = json.load(f)
        self.assertEqual(rep["coverage"], 80)
        with open(os.path.join(self.out, "ats_report.md")) as f:
            self.assertIn("Writer drafts proposals", f.read())


class Tracker(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        shutil.copy(os.path.join(EXAMPLE, "applications.csv"), self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_upsert_updates_in_place_and_migrates_columns(self):
        path = os.path.join(self.dir, "applications.csv")
        with open(path, "w", newline="") as f:  # an old tracker without the new columns
            f.write("date_applied,company,role,url,status\n,Acme,PM,https://a/1,ready\n")
        tracker.upsert(path, "https://a/1", {"status": "applied", "date_applied": "2026-11-20"})
        tracker.upsert(path, "https://b/2", {"company": "Beta", "status": "shortlisted"}, today=date(2026, 11, 21))
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([(r["url"], r["status"]) for r in rows], [("https://a/1", "applied"), ("https://b/2", "shortlisted")])
        self.assertEqual(rows[1]["date_added"], "2026-11-21")
        self.assertIn("app_folder", rows[0])
        with self.assertRaises(ValueError):
            tracker.upsert(path, "https://a/1", {"status": "offer"})

    def test_dashboard_escapes_and_enriches(self):
        app = os.path.join(self.dir, "applications", "example-gpm-ai")
        os.makedirs(app)
        for name, obj in (("fit.json", {"score": 4.2, "decision": "Apply"}), ("ats_report.json", {"coverage": 80, "parse_score": 100})):
            with open(os.path.join(app, name), "w") as f:
                json.dump(obj, f)
        tracker.upsert(os.path.join(self.dir, "applications.csv"), "javascript:alert(1)",
                       {"company": "</script><img src=x onerror=alert(1)>", "status": "applied"})
        rows = tracker.collect(self.dir, today=date(2026, 11, 22))
        ex = next(r for r in rows if r.get("app_folder") == "example-gpm-ai")
        self.assertEqual((ex["fit_score"], ex["fit_call"], ex["ats_coverage"]), ("4.2", "Apply", "80"))
        self.assertEqual(next(r for r in rows if r["company"].startswith("</script"))["url"], "")
        html = tracker.render(rows, today=date(2026, 11, 22))
        self.assertNotIn("</script><img", html)
        self.assertEqual(html.count("</script>"), 2)

    def test_stats(self):
        s = tracker.stats(tracker.collect(self.dir, today=date(2026, 11, 22)), today=date(2026, 11, 22))
        self.assertEqual((s["applied"], s["calls"], s["call_rate"]), (2, 1, 50))
        self.assertEqual(s["followups"], 3)  # Demo Corp overdue; Example Target and Sample Labs due within 2 days

    def test_paused_draft_is_in_pipeline_not_applied(self):
        path = os.path.join(self.dir, "applications.csv")
        before = tracker.stats(tracker.collect(self.dir, today=date(2026, 11, 22)), today=date(2026, 11, 22))
        tracker.upsert(path, "https://example.com/jobs/123", {"status": "paused", "next_step": "Finish and submit",
                                                               "next_step_date": "2026-11-21"})
        rows = tracker.collect(self.dir, today=date(2026, 11, 22))
        s = tracker.stats(rows, today=date(2026, 11, 22))
        self.assertEqual((s["paused"], s["applied"], s["in_pipeline"]), (1, before["applied"], before["in_pipeline"]))
        self.assertEqual(next(r for r in rows if r["status"] == "paused")["followup"], "overdue")
        self.assertIn("Paused drafts", tracker.render(rows, today=date(2026, 11, 22)))


if __name__ == "__main__":
    unittest.main()
