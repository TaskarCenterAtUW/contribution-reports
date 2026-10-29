from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("path", [
    "README.md", ".env.example", "docs/quest-settings.schema.json", "AGENTS.md",
])
def test_repo_file_exists_and_does_not_contain_fetch_nda(path):
    assert (REPO / path).is_file(), f"missing {path} in git-tracked tree"
    assert "fetch_nda" not in (REPO / path).read_text(), f"{path} still says fetch_nda"


BANNED_README_REFS = [
    "reports/generate_report.py",
    "reports/generate_osw_report.py",
    "reports/generate_summary.py",
    "regen.sh",
    "fetch_nda",
    "reports/output",
    "/reports/",
    "fetch_changesets.py",
    "quests/ static",
    "NDA-specific",
    "fetch_nda.py",
]


@pytest.mark.parametrize("token", BANNED_README_REFS)
def test_readme_contains_no_stale_references(token):
    readme = (REPO / "README.md").read_text()
    assert token not in readme, f"README.md still references {token!r}"
