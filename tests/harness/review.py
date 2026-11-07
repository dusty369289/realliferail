"""Keep failing output, and flag flaky tests until they're explained. Same rules as uppYT (CLAUDE.md).

- Every failure is appended to `.test-review/failures.log` with its full report.
- Each test's last outcome is stored with a fingerprint of the code (src + tests). A test that failed and then passed
  on the *same* fingerprint is flaky. It's listed at the end of every run until explained:
  `pytest --flaky-explain "<nodeid>" --reason "..."` (logged in `.test-review/flaky-explained.log`).
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / ".test-review"


def fingerprint() -> str:
    h = hashlib.sha256()
    for base in ("src", "tests"):
        for p in sorted((ROOT / base).rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py", ".html", ".css", ".js", ".json"}:
                h.update(str(p.relative_to(ROOT)).encode())
                h.update(p.read_bytes())
    return h.hexdigest()[:16]


def pytest_addoption(parser):
    g = parser.getgroup("review")
    g.addoption("--flaky-explain", default=None, help="Mark a flaky test as explained (node id).")
    g.addoption("--reason", default=None, help="Why: what was looked at.")


def _load(name: str) -> dict:
    try:
        return json.loads((DIR / name).read_text())
    except OSError, ValueError:
        return {}


def _save(name: str, data: dict) -> None:
    DIR.mkdir(exist_ok=True)
    tmp = DIR / f".{name}.tmp"
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
    tmp.replace(DIR / name)


def pytest_configure(config):
    if hasattr(config, "workerinput"):
        return  # only the controller keeps the books
    config._review = {"fp": fingerprint(), "history": _load("history.json"), "flaky": _load("flaky.json"), "new": []}
    nodeid = config.getoption("--flaky-explain")
    if nodeid:
        reason = config.getoption("--reason")
        if not reason:
            raise pytest.UsageError("--flaky-explain needs --reason saying what was found.")
        flaky = config._review["flaky"]
        flaky.pop(nodeid, None)
        _save("flaky.json", flaky)
        DIR.mkdir(exist_ok=True)
        with (DIR / "flaky-explained.log").open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {nodeid}: {reason}\n")


def pytest_runtest_logreport(report):
    config = getattr(pytest_runtest_logreport, "config", None)
    if config is None or not hasattr(config, "_review"):
        return
    if report.when != "call" and not (report.failed and report.when in ("setup", "teardown")):
        return
    r = config._review
    prev = r["history"].get(report.nodeid)
    outcome = "failed" if report.failed else ("skipped" if report.skipped else "passed")
    if report.failed:
        DIR.mkdir(exist_ok=True)
        with (DIR / "failures.log").open("a") as f:
            f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')} {report.nodeid} ({report.when}) fp={r['fp']}\n")
            f.write(str(report.longrepr))
            f.write("\n")
    if prev and prev.get("fp") == r["fp"] and prev.get("outcome") == "failed" and outcome == "passed":
        r["flaky"][report.nodeid] = {"fp": r["fp"], "seen": time.strftime("%Y-%m-%d %H:%M:%S")}
        r["new"].append(report.nodeid)
    r["history"][report.nodeid] = {"fp": r["fp"], "outcome": outcome}


@pytest.hookimpl(trylast=True)
def pytest_sessionstart(session):
    pytest_runtest_logreport.config = session.config


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not hasattr(config, "_review"):
        return
    r = config._review
    _save("history.json", r["history"])
    _save("flaky.json", r["flaky"])
    if r["flaky"]:
        terminalreporter.section("flaky tests (investigate, then --flaky-explain NODEID --reason ...)", yellow=True)
        for nodeid, info in sorted(r["flaky"].items()):
            terminalreporter.line(f"  {nodeid} (seen {info['seen']})")
    if exitstatus not in (0, 5):
        terminalreporter.line(f"Failures kept in {DIR / 'failures.log'}")
