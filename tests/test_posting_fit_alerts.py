import json
import unittest
from unittest import mock

from helpers import master
import fit_score
import import_alerts
import posting_check as pc


class WorkAuth(unittest.TestCase):
    def test_no_sponsorship_blocks_only_if_needed(self):
        jd = "Great role. We are unable to sponsor visas for this position. Apply now."
        self.assertEqual(pc.work_auth(jd)["verdict"], "no-sponsorship")
        self.assertFalse(pc.work_auth(jd)["blocker"])
        self.assertTrue(pc.work_auth(jd, {"work_authorization": {"needs_sponsorship": True}})["blocker"])

    def test_sponsors_and_citizenship(self):
        self.assertEqual(pc.work_auth("Visa sponsorship is available for this role.")["verdict"], "sponsors")
        r = pc.work_auth("Must be a U.S. citizen. Active secret clearance.",
                         {"work_authorization": {"meets_citizenship_or_clearance": False}})
        self.assertEqual((r["verdict"], r["blocker"]), ("citizenship-or-clearance", True))

    def test_not_stated(self):
        self.assertEqual(pc.work_auth("We build tools for teams.")["verdict"], "not stated")



class PageSafety(unittest.TestCase):
    def test_refuses_aggregators_http_and_private_hosts(self):
        for url, why in (("https://www.linkedin.com/jobs/view/123", "aggregator"),
                         ("http://example.com/job", "https"),
                         ("https://127.0.0.1/job", "IP"),
                         ("https://localhost/job", "public")):
            self.assertIn(why, pc.page_url_problem(url), url)
            self.assertEqual(pc.from_page(url)["status"], "uncertain")

    def test_eu_greenhouse_uses_eu_api(self):
        with mock.patch.object(pc, "_get", return_value=(None, 404)) as get:
            pc.from_api("https://job-boards.eu.greenhouse.io/acme/jobs/123")
        self.assertIn("boards-api.eu.greenhouse.io", get.call_args[0][0])

class Posting(unittest.TestCase):
    def test_years(self):
        ys = pc.years_required("You have 8+ years of product management experience. Founded 12 years ago.")
        self.assertEqual([y["years"] for y in ys], [8])

    def test_closed_wording(self):
        self.assertTrue(pc.closed_wording("Sorry. This job is no longer available."))
        self.assertFalse(pc.closed_wording("Applications closed? Not yet, apply today."))

    def test_greenhouse_404_is_closed(self):
        with mock.patch.object(pc, "_get", return_value=(None, 404)):
            r = pc.from_api("https://job-boards.greenhouse.io/acme/jobs/123")
        self.assertEqual(r["status"], "closed")

    def test_ashby_missing_from_board_is_closed(self):
        with mock.patch.object(pc, "_get", return_value=({"jobs": [{"id": "other"}]}, None)):
            r = pc.from_api("https://jobs.ashbyhq.com/acme/0e3f0c4e-0000-0000-0000-000000000000")
        self.assertEqual(r["status"], "closed")

    def test_unsafe_or_unknown_urls(self):
        self.assertIsNone(pc.from_api("https://jobs.lever.co/..%2f/abc"))
        self.assertIsNone(pc.from_api("https://example.com/careers/1"))

    def test_jobposting_json_ld(self):
        ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Product Manager, AI",
              "description": "Build AI products.", "datePosted": "2026-10-28T18:07:42-07:00",
              "responsibilities": "Own the roadmap&nbsp;Lead GTM",
              "qualifications": "8+ years of Product Management experience&nbsp;Shipped AI",
              "hiringOrganization": {"@type": "Organization", "name": "Acme"},
              "jobLocation": [{"@type": "Place", "name": "Bangalore, India"}]}
        page = f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body></body></html>'
        r = pc.job_posting_ld(page)
        self.assertEqual((r["title"], r["company"], r["location"], r["posted"]),
                         ("Product Manager, AI", "Acme", "Bangalore, India", "2026-10-28"))
        self.assertIn("- Own the roadmap\n- Lead GTM", r["text"])
        self.assertEqual([y["years"] for y in pc.years_required(r["text"])], [8])
        self.assertIsNone(pc.job_posting_ld("<html><script type='application/ld+json'>{bad json</script></html>"))


class Fit(unittest.TestCase):
    def fit(self, **kw):
        f = {"role": {"company": "X", "title": "GPM"}, "role_fit": 4, "preferences_fit": 4,
             "requirements": [{"req": "AI products", "weight": "must", "basis": "stated", "match": "proven", "evidence": ["ex_eval"]},
                              {"req": "A/B tests", "weight": "core", "basis": "stated", "match": "proven", "evidence": ["ab_tests"]}]}
        f.update(kw)
        return f

    def test_strong_fit_applies(self):
        r, errs, _ = fit_score.score_fit(self.fit(), master())
        self.assertEqual(errs, [])
        self.assertEqual((r["score"], r["decision"]), (4.6, "Apply"))

    def test_missing_must_and_bands(self):
        f = self.fit(requirements=[{"req": "Payments", "weight": "must", "basis": "stated", "match": "missing"},
                                   {"req": "AI", "weight": "core", "basis": "stated", "match": "partly", "evidence": ["ex_eval"]}])
        r, _, _ = fit_score.score_fit(f, master())
        self.assertEqual(r["decision"], "Skip")
        self.assertEqual(r["missing_must"], ["Payments"])
        self.assertEqual(fit_score.band(4.0), "Apply")
        self.assertEqual(fit_score.band(3.0), "Consider")

    def test_validation(self):
        f = self.fit(requirements=[{"req": "PM mgmt", "weight": "must", "basis": "inferred", "match": "missing"},
                                   {"req": "AI", "weight": "core", "basis": "stated", "match": "proven", "evidence": ["nope"]}])
        _, errs, _ = fit_score.score_fit(f, master())
        self.assertTrue(any("inferred" in e for e in errs))
        self.assertTrue(any("nope" in e for e in errs))

    def test_blocker_and_override(self):
        posting = {"status": "active", "work_authorization": {"blocker": True, "note": "no sponsorship", "evidence": ["x"]}}
        r, _, _ = fit_score.score_fit(self.fit(), master(), {}, posting)
        self.assertEqual(r["decision"], "Skip")
        r, _, _ = fit_score.score_fit(self.fit(override={"decision": "apply", "reason": "referral"}), master(), {}, posting)
        self.assertEqual((r["decision"], r["recommendation"], r["overridden"]), ("Apply", "Skip", True))

    def test_unconfirmed_addition_is_not_evidence(self):
        m = master()
        m["confirmed_additions"][0]["status"] = "proposed"
        _, errs, _ = fit_score.score_fit(self.fit(), m)
        self.assertTrue(any("ab_tests" in e for e in errs))

    def test_years_in_function(self):
        self.assertAlmostEqual(fit_score.years_in_function(master(), ["product manager"]),
                               fit_score.years_in_function(master(), ["product manager", "pm"]), places=1)
        self.assertIsNone(fit_score.years_in_function(master(), []))


class Alerts(unittest.TestCase):
    def test_plain_text_alert(self):
        text = ("Your job alert for group product manager\n"
                "Group Product Manager, AI\nAcme · Austin, TX (Hybrid)\n"
                "View job: https://www.linkedin.com/comm/jobs/view/4012345678/?trackingId=abc\n\n"
                "Principal PM\nBeta Inc · Remote\nhttps://job-boards.greenhouse.io/beta/jobs/7012345\n")
        rows = import_alerts.parse(import_alerts.email_text(text))
        self.assertEqual([(r["title"], r["company"], r["location"], r["via"]) for r in rows],
                         [("Group Product Manager, AI", "Acme", "Austin, TX (Hybrid)", "linkedin"),
                          ("Principal PM", "Beta Inc", "Remote", "company board")])
        self.assertEqual(rows[0]["url"], "https://www.linkedin.com/jobs/view/4012345678")

    def test_html_eml(self):
        html = ('<table><tr><td><a href="https://www.linkedin.com/comm/jobs/view/4011111111/?x=1">Staff PM, Agents</a>'
                '<p>Gamma · United States (Remote)</p></td></tr>'
                '<tr><td><a href="https://www.linkedin.com/comm/jobs/view/4022222222/">Director of Product</a>'
                '<p>Delta · Austin, TX</p></td></tr></table>')
        eml = ("From: jobs-noreply@linkedin.com\nSubject: 2 new jobs\nMIME-Version: 1.0\n"
               "Content-Type: text/html; charset=utf-8\n\n" + html)
        rows = import_alerts.parse(import_alerts.email_text(eml))
        self.assertEqual([(r["title"], r["company"]) for r in rows],
                         [("Staff PM, Agents", "Gamma"), ("Director of Product", "Delta")])

    def test_ignores_non_job_links(self):
        self.assertEqual(import_alerts.parse("Unsubscribe https://www.linkedin.com/comm/psettings/x"), [])


if __name__ == "__main__":
    unittest.main()
