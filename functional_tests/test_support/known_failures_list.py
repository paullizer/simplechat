# known_failures_list.py
"""Parse ``functional_tests/known_failures.txt``.

Version: 0.261.494
Implemented in: 0.261.494

Kept apart from the pytest plugin in ``known_failures.py`` so that scripts which
only read the list (``scripts/run_tests.py js``,
``scripts/check_known_failures_shrink.py``) work without pytest installed. See
``known_failures.py`` for the list's format and rules.
"""


LIST_FILE_NAME = "known_failures.txt"
IGNORE_ENV = "SIMPLECHAT_IGNORE_KNOWN_FAILURES"


def parse_known_failures(text):
    """Return ``({test_id: reason}, {file_name: reason})`` from the list's text."""
    tests, files = {}, {}
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entry, _, reason = line.partition("#")
        entry, reason = entry.strip(), reason.strip()
        if not reason:
            raise ValueError(f"{LIST_FILE_NAME} line {number}: '{entry}' needs a '# reason'.")
        target = tests if "::" in entry else files
        if entry in target:
            raise ValueError(f"{LIST_FILE_NAME} line {number}: '{entry}' is listed twice.")
        target[entry] = reason
    return tests, files
