"""Run focused desktop checks; native STAR operations are mocked, not CFD-tested."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".private/desktop-checks"))
    args = parser.parse_args(argv)
    project = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project / "src"))
    suite = unittest.defaultTestLoader.discover(str(project / "tests"), "test_desktop.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    receipt = {
        "schema": "cfd-review-desktop-checks", "version": 1,
        "checkedUtc": datetime.now(timezone.utc).isoformat(),
        "testsRun": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "passed": result.wasSuccessful() and result.testsRun > 0,
        "scope": "Synthetic fixtures, mocked native adapter, and native Tk widget interactions when a display is available.",
        "realStarLaunched": False,
        "realCfdValidated": False,
        "failureDetails": [{"test": str(test), "detail": detail} for test, detail in result.failures + result.errors],
        "skipDetails": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
    }
    args.output.mkdir(parents=True, exist_ok=True)
    path = args.output / "desktop-checks.json"
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(path.resolve())
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
