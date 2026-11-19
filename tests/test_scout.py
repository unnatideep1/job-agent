import unittest
from datetime import date

from helpers import example  # noqa: F401  (sets sys.path)
import scout


PREFS = {
    "target_levels": {"include_titles": ["group product manager", "principal product manager"], "exclude_titles": ["associate"]},
    "locations": {"onsite_or_hybrid": ["austin"], "remote_from": ["united states", "us"]},
    "posting": {"max_age_days": 45},
}


class Normalise(unittest.TestCase):
    def test_smartrecruiters(self):
        data = {"content": [{"id": "744000012345", "name": "Group Product Manager", "releasedDate": "2026-11-01T10:00:00Z",
                             "location": {"fullLocation": "Austin, TX, United States", "remote": False, "hybrid": True},
                             "department": {"label": "Product"}}]}
        j = scout.normalise("smartrecruiters", "acme", data)[0]
        self.assertEqual(j["url"], "https://jobs.smartrecruiters.com/acme/744000012345")
        self.assertEqual((j["workplace"], j["posted"], j["department"]), ("Hybrid", "2026-11-01", "Product"))

    def test_workable_and_recruitee(self):
        w = scout.normalise("workable", "acme", {"jobs": [{"title": "Principal Product Manager", "telecommuting": True,
                                                          "url": "https://apply.workable.com/acme/j/ABC123/",
                                                          "locations": [{"city": "Austin", "country": "United States"}],
                                                          "published_on": "2026-11-02"}]})[0]
        self.assertEqual((w["workplace"], w["location"]), ("Remote", "Austin, United States"))
        r = scout.normalise("recruitee", "acme", {"offers": [{"title": "PM", "remote": False, "hybrid": True,
                                                              "careers_url": "https://acme.recruitee.com/o/pm",
                                                              "published_at": "2026-11-03 09:00:00 UTC"}]})[0]
        self.assertEqual((r["workplace"], r["url"]), ("Hybrid", "https://acme.recruitee.com/o/pm"))

    def test_ids_are_allowlisted(self):
        self.assertFalse(scout.valid_id("greenhouse", "../etc"))
        self.assertFalse(scout.valid_id("recruitee", "Bad_Host"))
        self.assertTrue(scout.valid_id("recruitee", "acme-co"))


class Catalog(unittest.TestCase):
    CAT = [{"name": "Alpha AI", "source": "ashby", "id": "alpha", "tags": ["ai"]},
           {"name": "Beta Pay", "source": "greenhouse", "id": "beta", "tags": ["fintech"]},
           {"name": "Gamma", "source": "lever", "id": "gamma", "tags": ["ai"]}]

    def test_pick_by_tag_name_and_exclude(self):
        prefs = {"sources": {"greenhouse": ["beta"], "careers_sites": ["https://x"]},
                 "catalog": {"tags": ["ai"], "companies": ["Beta Pay"], "exclude": ["Gamma"]}}
        got = [(s, i, n) for s, i, n, _ in scout.board_list(prefs, self.CAT)]
        self.assertEqual(got, [("greenhouse", "beta", "Beta Pay"), ("ashby", "alpha", "Alpha AI")])

    def test_shipped_catalog_is_valid(self):
        cat = scout.load_catalog(scout.DEFAULT_CATALOG)
        self.assertGreater(len(cat), 200)
        keys = [(c["source"], str(c["id"]).lower()) for c in cat]
        self.assertEqual(len(keys), len(set(keys)), "duplicate boards in portals.yaml")
        for c in cat:
            self.assertIn(c["source"], scout.ENDPOINTS, c)
            self.assertTrue(scout.valid_id(c["source"], str(c["id"])), c)


class Scan(unittest.TestCase):
    def test_filters_and_dedups_across_boards(self):
        today = date.today().isoformat()
        boards = {
            ("greenhouse", "alpha"): {"jobs": [
                {"title": "Group Product Manager, AI", "location": {"name": "Austin, TX"},
                 "absolute_url": "https://job-boards.greenhouse.io/alpha/jobs/1", "first_published": today},
                {"title": "Associate Product Manager", "location": {"name": "Austin"},
                 "absolute_url": "https://job-boards.greenhouse.io/alpha/jobs/2", "first_published": today}]},
            ("ashby", "alpha2"): {"jobs": [
                {"title": "Group Product Manager, AI", "location": "Austin, TX",
                 "jobUrl": "https://jobs.ashbyhq.com/alpha2/x", "publishedAt": today},
                {"title": "Principal Product Manager", "location": "Belarus", "isRemote": True,
                 "jobUrl": "https://jobs.ashbyhq.com/alpha2/y", "publishedAt": today}]},
        }
        cat = [{"name": "Alpha", "source": "greenhouse", "id": "alpha", "tags": ["ai"]},
               {"name": "Alpha", "source": "ashby", "id": "alpha2", "tags": ["ai"]}]
        prefs = dict(PREFS, catalog={"tags": ["ai"]})
        jobs, fails = scout.scan(prefs, cat, fetch=lambda s, i: boards[(s, i)])
        self.assertEqual(fails, [])
        self.assertEqual([j["url"] for j in jobs], ["https://job-boards.greenhouse.io/alpha/jobs/1"])

    def test_failed_board_does_not_abort(self):
        def boom(s, i):
            raise TimeoutError()
        jobs, fails = scout.scan(dict(PREFS, sources={"lever": ["x"]}), [], fetch=boom)
        self.assertEqual((jobs, fails), ([], ["lever/x: TimeoutError"]))


class History(unittest.TestCase):
    def test_repost_and_new(self):
        hist = [dict(url="https://a/old", company="Alpha", title="Group Product Manager, AI",
                     title_key=scout.title_key("Group Product Manager, AI"), first_seen="2026-10-01",
                     last_seen="2026-10-20", posted="")]
        jobs = [dict(url="https://a/new", company="Alpha", title="AI Group Product Manager", flag=""),
                dict(url="https://b/1", company="Beta", title="Principal Product Manager", flag="")]
        rows = scout.apply_history(jobs, hist, today=date(2026, 11, 1))
        self.assertEqual(jobs[0]["flag"], "repost? new")
        self.assertEqual(jobs[1]["flag"], "new")
        self.assertEqual(len(rows), 3)

    def test_first_scan_flags_nothing(self):
        jobs = [dict(url="https://a/1", company="A", title="PM", flag="")]
        scout.apply_history(jobs, [], today=date(2026, 11, 1))
        self.assertEqual(jobs[0]["flag"], "")


if __name__ == "__main__":
    unittest.main()
