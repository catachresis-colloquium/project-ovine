# SPDX-License-Identifier: MPL-2.0
"""Offline workflow pin checks. With PyYAML installed, run from the repo root:

    python3 -m unittest discover -s tests/workflows -p test_workflow_pins.py
"""

from pathlib import Path
import re
import unittest

import yaml


WORKFLOWS = Path(__file__).resolve().parents[2] / ".github/workflows"
ACTION_WORKFLOWS = (
    "boj-build", "codeql", "container-build", "dependabot-automerge",
    "dogfood-gate", "e2e", "estate-rules", "guix-policy", "openssf-compliance",
    "pages", "quality", "release", "rhodibot", "runtime-policy",
    "security-policy", "sonarqube", "static-analysis-gate",
    "wellknown-enforcement", "workflow-linter",
)
REUSABLE_JOBS = {
    "governance": "governance",
    "hypatia-scan": "scan",
    "mirror": "mirror",
    "rust-ci": "rust-ci",
    "scorecard": "scorecard",
}
SHA = re.compile(r"[0-9a-f]{40}")


def load_yaml(path):
    with path.open(encoding="utf-8") as stream:
        return yaml.safe_load(stream)


class WorkflowPinsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lock = load_yaml(WORKFLOWS / "actions.lock")
        cls.workflow_locks = lock["workflows"]
        cls.dependencies = lock["dependencies"]

    def test_workflows_lock_exactly_their_remote_step_actions(self):
        for workflow in (*ACTION_WORKFLOWS, *REUSABLE_JOBS):
            filename = f"{workflow}.yml"
            with self.subTest(workflow=filename):
                jobs = load_yaml(WORKFLOWS / filename)["jobs"]
                actions = set()
                for job in jobs.values():
                    for step in job.get("steps", []):
                        use = step.get("uses")
                        if use is None or use.startswith(("./", "docker://")):
                            continue
                        path, ref = use.rsplit("@", 1)
                        # The lock is keyed by repository, even for actions in
                        # subdirectories (e.g. CodeQL init and analyze).
                        repository = "/".join(path.lower().split("/")[:2])
                        actions.add(f"{repository}@{ref}")

                self.assertCountEqual(
                    self.workflow_locks[f".github/workflows/{filename}"],
                    sorted(actions),
                )

    def test_action_dependency_graph_resolves_to_commits(self):
        pending = [
            action
            for workflow_actions in self.workflow_locks.values()
            for action in workflow_actions
        ]
        seen = set()
        while pending:
            action = pending.pop()
            if action in seen:
                continue
            seen.add(action)
            with self.subTest(action=action):
                self.assertIn(action, self.dependencies)
                dependency = self.dependencies[action]
                commit = dependency["commit"]
                self.assertRegex(commit, r"\Asha1-[0-9a-f]{40}\Z")
                ref = action.rsplit("@", 1)[1]
                if SHA.fullmatch(ref):
                    self.assertEqual(commit, f"sha1-{ref}")
                else:
                    self.assertEqual(dependency["ref"], ref)
                pending.extend(dependency.get("uses", []))
        self.assertEqual(set(self.dependencies) - seen, set(), "Unused lock entries")

    def test_standards_reusable_jobs_share_an_immutable_pin(self):
        pins = set()
        for workflow, job in REUSABLE_JOBS.items():
            with self.subTest(workflow=workflow, job=job):
                jobs = load_yaml(WORKFLOWS / f"{workflow}.yml")["jobs"]
                path, pin = jobs[job]["uses"].rsplit("@", 1)
                self.assertEqual(
                    path,
                    f"hyperpolymath/standards/.github/workflows/{workflow}-reusable.yml",
                )
                self.assertIsNotNone(SHA.fullmatch(pin), f"Expected full SHA, got {pin!r}")
                pins.add(pin)
        self.assertEqual(len(pins), 1, f"Standards workflow pins differ: {sorted(pins)}")
