# check_known_failures_shrink.py
"""Fail when functional_tests/known_failures.txt gains an entry.

Version: 0.261.492
Implemented in: 0.261.492

The known-failures list records tests that fell behind the application before the
suite was normalized. It may only shrink: a change that breaks a test must fix the
test (or the application), not list it. This compares the list on the current
checkout with the list at a base git revision and reports every entry that is new.
Changing an existing entry's reason is allowed.

Usage (from the repository root):

    python scripts/check_known_failures_shrink.py --base origin/Development
"""

import argparse
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LIST_PATH = "functional_tests/known_failures.txt"


def list_entries(text):
    """Return the set of entries (tests and files) named in the list's text."""
    sys.path.insert(0, str(REPO_ROOT / "functional_tests"))
    try:
        from test_support.known_failures import parse_known_failures
    finally:
        sys.path.pop(0)
    tests, files = parse_known_failures(text)
    return set(tests) | set(files)


def text_at(revision):
    """Return the list's text at ``revision``, or an empty string where it does not exist."""
    result = subprocess.run(
        ["git", "show", f"{revision}:{LIST_PATH}"], cwd=REPO_ROOT,
        capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode != 0:
        if "does not exist" in result.stderr or "exists on disk, but not in" in result.stderr:
            return ""
        raise SystemExit(f"git show {revision}:{LIST_PATH} failed: {result.stderr.strip()}")
    return result.stdout


def new_entries(base_text, current_text):
    """Entries in the current list that the base list does not have, sorted."""
    return sorted(list_entries(current_text) - list_entries(base_text))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="git revision to compare against")
    args = parser.parse_args(argv)

    current_path = REPO_ROOT / LIST_PATH
    current_text = current_path.read_text(encoding="utf-8") if current_path.is_file() else ""
    base_text = text_at(args.base)
    added = new_entries(base_text, current_text)
    removed = len(list_entries(base_text) - list_entries(current_text))
    if added:
        print(f"{LIST_PATH} gained {len(added)} entr{'y' if len(added) == 1 else 'ies'}. "
              "The list can only shrink: fix the test, or the application if the test "
              "found a real problem, instead of listing it.")
        for entry in added:
            print(f"  + {entry}")
        return 1
    print(f"{LIST_PATH}: no new entries ({removed} removed compared with {args.base}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
