"""Check the exact source files intended for publication, without reading local settings."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    ".gitattributes", ".gitignore", "LICENSE", "README.md", "SECURITY.md",
    "kick_toplu_indir.py", "klip.example.txt",
    "requirements.txt", "tests/test_downloader.py", "tools/check_release.py",
    ".github/workflows/tests.yml",
}


def main():
    tracked = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=ROOT
    ).decode().split("\0")
    actual = set(filter(None, tracked))
    if actual != ALLOWED:
        raise SystemExit(f"Unexpected or missing tracked paths: {sorted(actual ^ ALLOWED)}")
    for name in sorted(actual):
        text = (ROOT / name).read_text(encoding="utf-8")
        if re.search(r"\bgh[pousr]_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}", text):
            raise SystemExit(f"Possible GitHub credential in {name}")
        if re.search(r"(?<![A-Za-z0-9])[a-fA-F0-9]{48,}(?![A-Za-z0-9])", text):
            raise SystemExit(f"Possible secret-like value in {name}")
        if "C:\\Users\\tinitaVolkan" in text:
            raise SystemExit(f"Personal local path in {name}")
    print(f"Publication check passed: {len(actual)} source/documentation files.")


if __name__ == "__main__":
    main()
