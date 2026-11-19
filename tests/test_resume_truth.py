import os
import shutil
import tempfile
import unittest

import yaml

from helpers import EXAMPLE, master, tailoring
import build_resume as br
import proposals as pr


class KeywordTruth(unittest.TestCase):
    def errs(self, m, t):
        return br.validate_tailoring(m, t)[0]

    def test_example_is_clean(self):
        self.assertEqual(self.errs(master(), tailoring()), [])

    def test_unsupported_keyword_in_rewrite(self):
        t = tailoring()
        t["keywords"].append({"term": "Kubernetes", "priority": "core"})
        t["rewrites"]["ex_eval"]["text"] = "Built a Kubernetes evaluation suite that cut bad answers by <b>40%</b>."
        self.assertTrue(any("Kubernetes" in e and "ex_eval" in e for e in self.errs(master(), t)))

    def test_intent_mapping_needs_a_stretch(self):
        t = tailoring()
        kw = next(k for k in t["keywords"] if k["term"] == "enterprise customers")
        kw.pop("stretch")
        errs = self.errs(master(), t)
        self.assertTrue(any("stretch" in e for e in errs))
        self.assertTrue(any("rewrites.ex_scope" in e for e in errs))

    def test_evidence_must_exist_and_summary_must_be_backed(self):
        t = tailoring()
        t["keywords"].append({"term": "fintech", "priority": "nice", "evidence": ["ghost"], "stretch": "x"})
        t["summary"] = "Fintech product manager with 8 years in B2B SaaS."
        errs = self.errs(master(), t)
        self.assertTrue(any("ghost" in e for e in errs))
        self.assertTrue(any(e.startswith("summary") and "fintech" in e for e in errs))

    def test_matching_is_word_based(self):
        self.assertTrue(br.mentions("Ran A/B tests weekly", {"term": "A/B test"}))
        self.assertTrue(br.mentions("Led evals for LLMs", {"term": "LLM"}))
        self.assertFalse(br.mentions("Scaled the platform", {"term": "AI"}))
        self.assertTrue(br.mentions("go to market plan", {"term": "go-to-market"}))

    def test_b2b_is_not_a_number(self):
        self.assertEqual(br.numbers("B2B SaaS for 2,000 customers"), ["2,000"])


class UnapprovedNeverRenders(unittest.TestCase):
    def test_addition_must_be_candidate_confirmed(self):
        m = master()
        m["confirmed_additions"][0]["status"] = "proposed"
        errs = br.validate_tailoring(m, tailoring())[0]
        self.assertTrue(any("only candidate-approved" in e for e in errs))

    def test_proposal_id_is_not_an_addition(self):
        t = tailoring()
        t["additions"]["ex_senior"].append({"from": "assistant_tool_calling", "section": 0, "text": "Defined tool calling."})
        self.assertTrue(any("proposals.yaml" in e for e in br.validate_tailoring(master(), t)[0]))


class Proposals(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.master = os.path.join(self.dir, "master_resume.yaml")
        self.props = os.path.join(self.dir, "app1", "proposals.yaml")
        os.makedirs(os.path.dirname(self.props))
        shutil.copy(os.path.join(EXAMPLE, "master_resume.yaml"), self.master)
        shutil.copy(os.path.join(EXAMPLE, "applications/example-gpm-ai/proposals.yaml"), self.props)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def doc(self):
        with open(self.props) as f:
            return yaml.safe_load(f)

    def save(self, d):
        with open(self.props, "w") as f:
            yaml.safe_dump(d, f, sort_keys=False)

    def test_example_checks_and_prompt_flags_unverified(self):
        props = self.doc()["proposals"]
        self.assertEqual(pr.check(master(), props), [])
        text = pr.prompt(props)
        self.assertIn("UNVERIFIED new claim", text)
        self.assertIn("talk through in an interview", text)

    def test_no_new_numbers(self):
        props = self.doc()["proposals"]
        props[1]["text"] = "Piloted agent workflows with 12 design partners."
        props[0]["text"] = "Gated tools behind the suite, cutting bad answers by 40%."  # 40% is in ex_eval
        errs = pr.check(master(), props)
        self.assertEqual(len(errs), 1)
        self.assertIn("12", errs[0])

    def test_blank_must_be_filled_before_approval(self):
        props = self.doc()["proposals"]
        props[1].update(text="Cut handling time by [X%] with agents.", decision="approved")
        self.assertTrue(any("blank" in e for e in pr.check(master(), props)))
        props[1].update(decision="edited", edited_text="Cut handling time by 15% with agents.")
        self.assertEqual(pr.check(master(), props), [])

    def test_apply_records_and_keeps_comments(self):
        d = self.doc()
        d["proposals"][0]["decision"] = "approved"
        d["proposals"][1].update(decision="rejected")
        self.save(d)
        errs, adds, rejs = pr.apply(self.master, self.props, "app1", today="2026-11-20")
        self.assertEqual(errs, [])
        self.assertEqual((len(adds), len(rejs)), (1, 1))
        with open(self.master) as f:
            src = f.read()
        self.assertIn("# Proposals the candidate turned down.", src)  # comments survive
        m = yaml.safe_load(src)
        add = next(a for a in m["confirmed_additions"] if a["id"] == "assistant_tool_calling")
        self.assertEqual((add["status"], add["source_app"], add["covers"], add["origin"]),
                         ("candidate-confirmed", "app1", "agent platforms", "grounded"))
        self.assertEqual(m["rejected_proposals"][-1]["requirement"], "agent platforms")
        # the approved fact is now usable as an addition; re-running apply records nothing twice
        t = tailoring()
        t["additions"]["ex_senior"].append({"from": "assistant_tool_calling", "section": 0,
                                            "text": "Defined how the AI assistant calls customer tools and APIs."})
        self.assertEqual(br.validate_tailoring(m, t)[0], [])
        self.assertEqual(pr.apply(self.master, self.props, "app1")[1:], ([], []))

    def test_rejected_idea_is_not_proposed_again(self):
        m = master()
        m["rejected_proposals"].append({"requirement": "agent platforms", "date": "2026-11-01", "app": "x",
                                        "text": "Piloted multi-step agent workflows with design-partner customers and "
                                                "turned the findings into the assistant roadmap."})
        errs = pr.check(m, self.doc()["proposals"])
        self.assertTrue(any("already rejected" in e for e in errs))

    def test_insert_into_missing_or_empty_list(self):
        src = "person:\n  name: A\nconfirmed_additions: []\n# tail comment\nmax_pages: 2\n"
        out = pr.insert_list_items(src, "confirmed_additions", [{"id": "x", "fact": "y"}])
        self.assertEqual(yaml.safe_load(out)["confirmed_additions"], [{"id": "x", "fact": "y"}])
        self.assertIn("# tail comment", out)
        out = pr.insert_list_items(src, "rejected_proposals", [{"requirement": "r", "text": "t"}])
        self.assertEqual(yaml.safe_load(out)["rejected_proposals"][0]["text"], "t")


if __name__ == "__main__":
    unittest.main()
