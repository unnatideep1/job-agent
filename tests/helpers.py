"""Shared helpers for the offline test suite. Run: python -m unittest discover tests"""
import copy
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(ROOT, "example-data")
for sub in ("skills/scout-jobs/scripts", "skills/tailor-resume/scripts", "skills/job-hunt/scripts"):
    sys.path.insert(0, os.path.join(ROOT, sub))


def example(name):
    with open(os.path.join(EXAMPLE, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


def master():
    return copy.deepcopy(example("master_resume.yaml"))


def tailoring():
    return copy.deepcopy(example("applications/example-gpm-ai/tailoring.yaml"))
