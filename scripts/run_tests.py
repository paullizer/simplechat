# run_tests.py
"""Run the SimpleChat test suites with the flags each one needs.

Version: 0.261.494
Implemented in: 0.261.491

Usage (from the repository root, with the app and dev requirements installed):

    python scripts/run_tests.py functional        # offline Python functional tests
    python scripts/run_tests.py js                # Node functional tests
    python scripts/run_tests.py ui                # Playwright UI tests (needs a running app)
    python scripts/run_tests.py all               # functional + js
    python scripts/run_tests.py functional -- -k image   # extra arguments go to pytest
    python scripts/run_tests.py functional --shard 2/8   # the second of eight CI shards

Functional tests run one test file per pytest process, several files at a time
(``--jobs``, default: the number of CPUs), so each file starts with clean
modules and a file that hangs is stopped after ``--file-timeout`` seconds.
``--shard K/N`` runs every Nth file starting with the Kth, which is how CI
splits the suite across jobs. Arguments after ``--`` go to each pytest process.
A per-test timeout is applied when pytest-timeout is installed; it is optional.

The JavaScript tests use Node's built-in runner. Several load the v2 UI's
TypeScript sources, so ``npm ci`` in ``application/v2_ui`` must have been run
once; the runner reports that instead of failing each test.

See docs/contributing/testing.md for what each suite needs and how tests that
require a live deployment are skipped.
"""

import argparse
import importlib.util
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FUNCTIONAL = REPO_ROOT / "functional_tests"
UI = REPO_ROOT / "ui_tests"
V2_UI = REPO_ROOT / "application" / "v2_ui"
JS_TEST_TIMEOUT_SECONDS = 300
FILE_TIMEOUT_SECONDS = 900


def _has_plugin(module_name):
    return importlib.util.find_spec(module_name) is not None


def _warm_tokenizer_cache():
    """Download tiktoken's encodings once, before tests that block the network run.

    The application counts tokens with tiktoken, which downloads each encoding the
    first time it is used. Many tests forbid network access, so on a machine whose
    cache is empty (a fresh CI runner, a new clone) they would fail on that download.
    """
    script = "import tiktoken; [tiktoken.get_encoding(name) for name in tiktoken.list_encoding_names()]"
    try:
        result = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=300)
    except subprocess.TimeoutExpired:
        print("Could not download tiktoken encodings (timed out); tests that count tokens may fail.")
        return
    if result.returncode != 0:
        last = (result.stderr.strip().splitlines() or [""])[-1]
        print(f"Could not download tiktoken encodings ({last}); tests that count tokens may fail.")


def run_functional(extra, shard=None, jobs=None, file_timeout=FILE_TIMEOUT_SECONDS):
    files = sorted(FUNCTIONAL.glob("test_*.py"))
    if shard:
        index, count = shard
        files = files[index - 1::count]
    excluded = _known_failing_files()
    _warm_tokenizer_cache()
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rfE", "--tb=short"]
    if _has_plugin("pytest_timeout"):
        command += ["--timeout", "300"]
    command += extra
    print("+", " ".join(command), "<file>", f"({len(files)} files)", flush=True)

    def run_file(path):
        try:
            result = subprocess.run(
                [*command, str(path)], cwd=REPO_ROOT, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=file_timeout,
            )
            return path, result.returncode, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return path, "timeout", f"stopped after {file_timeout}s"

    to_run = []
    for path in files:
        if path.name in excluded:
            # A listed file is not collected (see known_failures.txt); naming it on the
            # command line would collect it anyway.
            print(f"skip   {path.relative_to(REPO_ROOT)} (known failure: {excluded[path.name]})", flush=True)
        else:
            to_run.append(path)

    failed = []
    with ThreadPoolExecutor(max_workers=jobs or os.cpu_count() or 1) as pool:
        for future in as_completed([pool.submit(run_file, path) for path in to_run]):
            path, code, output = future.result()
            lines = output.strip().splitlines()
            summary = lines[-1] if lines else ""
            # 5 means pytest collected nothing, e.g. a file whose tests all skip at import.
            if code in (0, 5):
                print(f"ok     {path.relative_to(REPO_ROOT)}  {summary}", flush=True)
                continue
            failed.append(path)
            status = "TIMEOUT" if code == "timeout" else "FAILED"
            print(f"{status:6} {path.relative_to(REPO_ROOT)}", flush=True)
            print(output[-6000:], flush=True)
    print(f"{len(to_run) - len(failed)} of {len(to_run)} Python test files passed, "
          f"{len(files) - len(to_run)} skipped as known failures, {len(failed)} failed.")
    for path in sorted(failed):
        print(f"  failed: {path.relative_to(REPO_ROOT)}")
    return 1 if failed else 0


def run_ui(extra):
    command = [sys.executable, "-m", "pytest", str(UI), "-p", "no:cacheprovider", "-q", *extra]
    print("+", " ".join(command), flush=True)
    return subprocess.call(command, cwd=REPO_ROOT)


def run_js(extra):
    if not (V2_UI / "node_modules").is_dir():
        print(
            "application/v2_ui/node_modules is missing. Run `npm ci` in application/v2_ui first; "
            "several JavaScript tests load the v2 UI's TypeScript sources.",
            file=sys.stderr,
        )
        return 2

    files = sorted([*FUNCTIONAL.glob("test_*.js"), *FUNCTIONAL.glob("test_*.mjs")])
    known = _known_failing_files()
    failed = []
    expected = []
    for path in files:
        # --experimental-vm-modules is needed by tests that evaluate ES modules through
        # node:vm (vm.SourceTextModule); it is harmless for the others.
        command = ["node", "--experimental-vm-modules", "--test", *extra, str(path)]
        try:
            result = subprocess.run(
                command, cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=JS_TEST_TIMEOUT_SECONDS,
            )
            code, output = result.returncode, result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            code, output = 1, f"timed out after {JS_TEST_TIMEOUT_SECONDS}s"
        reason = known.get(path.name)
        if reason and code != 0:
            expected.append(path)
            print(f"xfail  {path.relative_to(REPO_ROOT)} (known failure: {reason})", flush=True)
            continue
        if reason:
            failed.append(path)
            print(f"XPASS  {path.relative_to(REPO_ROOT)} now passes; remove it from "
                  f"functional_tests/known_failures.txt", flush=True)
            continue
        status = "ok" if code == 0 else "FAILED"
        print(f"{status:6} {path.relative_to(REPO_ROOT)}", flush=True)
        if code != 0:
            failed.append(path)
            print(output[-4000:])
    passed = len(files) - len(failed) - len(expected)
    print(f"{passed} of {len(files)} JavaScript test files passed, {len(expected)} known failures, "
          f"{len(failed)} failed.")
    return 1 if failed else 0


def _known_failing_files():
    """Whole-file entries of functional_tests/known_failures.txt."""
    if os.environ.get("SIMPLECHAT_IGNORE_KNOWN_FAILURES", "").strip().lower() in ("1", "true", "yes"):
        return {}
    sys.path.insert(0, str(FUNCTIONAL))
    try:
        from test_support.known_failures_list import LIST_FILE_NAME, parse_known_failures
    finally:
        sys.path.pop(0)
    list_path = FUNCTIONAL / LIST_FILE_NAME
    if not list_path.is_file():
        return {}
    return parse_known_failures(list_path.read_text(encoding="utf-8"))[1]


def _shard(value):
    index, _, count = value.partition("/")
    try:
        index, count = int(index), int(count)
    except ValueError:
        raise argparse.ArgumentTypeError("use K/N, for example 2/8")
    if not 1 <= index <= count:
        raise argparse.ArgumentTypeError("K must be between 1 and N")
    return index, count


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the SimpleChat test suites.")
    parser.add_argument("suite", choices=("functional", "js", "ui", "all"))
    parser.add_argument("--shard", type=_shard, help="K/N: run only the Kth of N slices of the functional files")
    parser.add_argument("--jobs", type=int, help="functional test files run at once (default: CPU count)")
    parser.add_argument("--file-timeout", type=int, default=FILE_TIMEOUT_SECONDS,
                        help="seconds before a functional test file is stopped")
    parser.epilog = "Arguments after -- go to pytest (or node for js)."
    argv = list(sys.argv[1:] if argv is None else argv)
    # Split at -- by hand: argparse.REMAINDER would also swallow --shard and the
    # other options when they follow the suite name.
    split = argv.index("--") if "--" in argv else len(argv)
    argv, extra = argv[:split], argv[split + 1:]
    args = parser.parse_args(argv)
    # Test output can hold characters a Windows console code page cannot print.
    sys.stdout.reconfigure(errors="replace")

    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    functional_options = {"shard": args.shard, "jobs": args.jobs, "file_timeout": args.file_timeout}
    if args.suite == "functional":
        return run_functional(extra, **functional_options)
    if args.suite == "js":
        return run_js(extra)
    if args.suite == "ui":
        return run_ui(extra)
    functional_code = run_functional(extra, **functional_options)
    js_code = run_js([])
    return functional_code or js_code


if __name__ == "__main__":
    sys.exit(main())
