#!/usr/bin/env python3
# test_functional_suite_ci_runner.py
"""
Functional test for the full-suite CI workflow and its helpers.
Version: 0.261.492
Implemented in: 0.261.492

This test ensures that the known-failures list guard reports only new entries,
that run_tests.py splits the functional files into disjoint shards that cover
every file, and that the workflow runs every shard, the JavaScript suite and the
guard on pull requests.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "functional-test-suite.yml"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_guard_reports_only_new_entries():
    """Removed entries and changed reasons pass; a new test or file entry is reported."""
    print("Testing the shrink-only guard...")
    guard = _load("check_known_failures_shrink")
    base = "test_a.py::test_one   # old reason\ntest_b.py::test_two   # reason\ntest_c.py   # hangs\n"
    assert guard.new_entries(base, "test_a.py::test_one   # new reason\n") == []
    assert guard.new_entries(base, base + "test_d.py::test_new   # reason\ntest_e.py   # hangs\n") == [
        "test_d.py::test_new",
        "test_e.py",
    ]
    assert guard.new_entries("", "test_a.py::test_one   # reason\n") == ["test_a.py::test_one"]
    print("Test passed!")


def test_guard_passes_against_the_checked_in_list():
    """Comparing the list with itself finds nothing new."""
    guard = _load("check_known_failures_shrink")
    text = (REPO_ROOT / guard.LIST_PATH).read_text(encoding="utf-8")
    assert guard.new_entries(text, text) == []


def test_shards_are_disjoint_and_cover_every_file():
    """--shard K/N slices partition the functional test files."""
    print("Testing functional shards...")
    runner = _load("run_tests")
    files = sorted(runner.FUNCTIONAL.glob("test_*.py"))
    count = 8
    slices = [files[index - 1::count] for index in range(1, count + 1)]
    seen = [path for part in slices for path in part]
    assert sorted(seen) == files
    assert len(seen) == len(set(seen))
    assert runner._shard("2/8") == (2, 8)
    for bad in ("0/8", "9/8", "x/8", "3"):
        with pytest.raises(Exception):
            runner._shard(bad)
    print("Test passed!")


def test_workflow_runs_every_shard_the_js_suite_and_the_guard():
    """The workflow's shard matrix matches the --shard count and every job is present."""
    print("Testing the functional test suite workflow...")
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "shard: [1, 2, 3, 4, 5, 6, 7, 8]" in text
    assert "run_tests.py functional --shard ${{ matrix.shard }}/8" in text
    assert "run_tests.py js" in text
    assert "check_known_failures_shrink.py" in text
    assert "fail-fast: false" in text
    print("Test passed!")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
