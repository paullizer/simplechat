# Functional Test Suite in CI

Implemented in version: **0.261.494**

## Overview and Purpose

Before this change, pull requests ran only about 155 of the roughly 2,000
Python functional test files: the ones named in a workflow or picked by the
Cosmos DB contract check. The rest were never run, so they fell behind the
application without anyone noticing. Version 0.261.491 made every test runnable
offline and recorded the out-of-date ones in `functional_tests/known_failures.txt`.

This change runs every functional test, Python and JavaScript, on every pull
request, and keeps the known-failures list from growing. A pull request that
breaks a test now has to fix it, and one that fixes a listed test has to take it
off the list.

Dependencies: the pinned application and development requirements, Node 24 with
`npm ci` in `application/v2_ui`. No new packages.

## Technical Specifications

### Architecture

| Piece | File | What it does |
|---|---|---|
| Workflow | `.github/workflows/functional-test-suite.yml` | On pull requests to Development and main: eight Python shards, the JavaScript suite, and the shrink-only guard. |
| Runner | `scripts/run_tests.py` | `functional` runs each test file in its own pytest process, several at once, with `--shard K/N`, `--jobs N` and `--file-timeout SECONDS`. |
| Guard | `scripts/check_known_failures_shrink.py` | Compares the list with the pull request's base branch and fails on any new entry. Removing entries and changing reasons is allowed. |

### Runner behavior

- `run_tests.py functional` no longer needs pytest-xdist. Each file runs in its
  own process, so it starts with clean modules, and a file that hangs is stopped
  after `--file-timeout` seconds (default 900) and reported as `TIMEOUT`.
- `--shard K/N` takes every Nth file of the sorted file list, starting with the
  Kth. The eight CI shards together run every file exactly once.
- Files listed whole in the known-failures list are skipped and reported, since
  naming a file on the pytest command line would collect it anyway.
- pytest exit code 5 (nothing collected) counts as a pass, for files whose tests
  all skip.
- The JavaScript suite (`run_tests.py js`) is unchanged.

### Running on Linux and macOS

The known-failures list was first built on Windows. Running the suite on a fresh
Linux runner showed tests that only worked on a developer's Windows machine:

- **Tokenizer downloads.** The application counts tokens with tiktoken, which
  downloads each encoding on first use. Many tests block the network, so they
  failed on a machine with an empty tiktoken cache. `run_tests.py functional`
  downloads all encodings once before the tests start.
- **Session folder.** `app.py` keeps Flask sessions in `/app/flask_session`
  unless `SESSION_FILE_DIR` is set. `functional_tests/conftest.py` sets it to a
  temporary folder, since `/app` cannot be created outside the container.
- **esbuild.** `node_modules/esbuild/bin/esbuild` is a JavaScript launcher on
  Windows and the native executable elsewhere.
  `test_support/node_tools.esbuild_command()` starts it either way.
- **Paths and encodings.** Test file paths use forward slashes, and Node output
  is decoded as UTF-8 rather than with the Windows console code page.
- **A built V2 bundle.** The V1 chat bootstrap test no longer depends on whether
  the V2 SPA has been built on the machine running it.

Fixing these, and the test stubs that had fallen behind the application
(`group_identity_harness.py`, `shared_secret_responses.py`), brought 178 listed
tests back to passing, and they were removed from the list.

### File structure

- `.github/workflows/functional-test-suite.yml` (new)
- `scripts/check_known_failures_shrink.py` (new)
- `functional_tests/test_support/node_tools.py` (new: starts esbuild on every platform)
- `functional_tests/test_support/known_failures_list.py` (new: the list parser, without pytest, for the guard and the JavaScript job)
- `scripts/run_tests.py` (per-file runner, sharding)
- `functional_tests/test_functional_suite_ci_runner.py` (new)
- `docs/contributing/testing.md` (runner options, Continuous integration section)

## Usage Instructions

Run one CI shard locally:

```powershell
python scripts/run_tests.py functional --shard 3/8
```

Check the list against the branch you will merge into:

```powershell
python scripts/check_known_failures_shrink.py --base origin/Development
```

A fork gets the same checks by enabling GitHub Actions on the fork.

## Testing and Validation

- `functional_tests/test_functional_suite_ci_runner.py` checks that the guard
  reports only new entries, that the shards partition the test files, and that
  the workflow runs all eight shards, the JavaScript suite and the guard.
- The workflow ran on the pull request that added it; see the PR's checks.

### Known limitations

- The UI suite is not part of this workflow. The offline UI tests need Chromium
  and the built v2 SPA, and the live UI tests need a deployment.
- Shards are split by file name, not by run time, so one shard can take longer
  than the others.
