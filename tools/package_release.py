"""Create an allowlisted source ZIP; no simulation data or local work receipts.

Run from any directory: python tools/package_release.py --output NEW.zip
The archive contains a SHA256 manifest; every member is re-read and checked.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "README.md", "README.zh-CN.md", "pyproject.toml", "LICENSE",
    "THIRD_PARTY_NOTICES.md", ".gitignore", "CHANGELOG.md", "CONTRIBUTING.md",
    "PRODUCT.md", "DESIGN.md", "AGENTS.md", "run.py", "Open Demo.cmd", "Open Studio.cmd",
    "tools/check_studio.py", "tools/check_desktop.py", "tools/check_split_comparison.py", "tools/check_stitch_memory.py", "tools/check_compressed_report.py", "tools/check_layout_import.py", "tools/check_pick_readout.py", "tools/check_mirror_display.py", "tools/check_language.py", "tools/package_release.py",
)
DIRECTORIES = ("src", "tests", "docs", "examples", "licenses", ".github")
EXCLUDED = {"__pycache__", "node_modules", ".private", ".git", "build", "dist"}
FORBIDDEN_SUFFIXES = {".sim", ".scm", ".sce", ".log", ".pyc", ".pyo", ".class"}


def source_files():
    selected = [ROOT / name for name in FILES]
    for folder in DIRECTORIES:
        selected.extend(path for path in (ROOT / folder).rglob("*") if path.is_file())
    for path in sorted(set(selected)):
        relative = path.relative_to(ROOT)
        if any(part in EXCLUDED or part.endswith(".egg-info") for part in relative.parts):
            continue
        if not path.is_file():
            raise ValueError(f"required public file missing: {relative}")
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise ValueError(f"public files must stay inside the source tree: {relative}")
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name.endswith(".local.json"):
            raise ValueError(f"private/build file found in public allowlist: {relative}")
        yield relative.as_posix(), path.read_bytes()


def package_release(output):
    output = Path(output).resolve()
    if output.suffix.lower() != ".zip" or output.exists():
        raise ValueError("choose a new .zip output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    content = dict(source_files())
    manifest = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in content.items())
    content["SOURCE_SHA256SUMS.txt"] = manifest.encode("utf-8")
    prefix = "StarCapsule/"
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in content.items():
            item = zipfile.ZipInfo(prefix + name, date_time=(2026, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o644 << 16
            archive.writestr(item, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP CRC check failed")
        if set(archive.namelist()) != {prefix + name for name in content}:
            raise ValueError("ZIP membership mismatch")
        for name, data in content.items():
            if archive.read(prefix + name) != data:
                raise ValueError(f"ZIP content mismatch: {name}")
    return output, len(content), hashlib.sha256(output.read_bytes()).hexdigest()


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--output", required=True)
    args = cli.parse_args()
    path, count, digest = package_release(args.output)
    print(f"VERIFIED {count} members: {path}\nSHA256 {digest}")
