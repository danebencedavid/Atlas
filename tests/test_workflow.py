from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_archive_step_guards_optional_status_record() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(
        encoding="utf-8"
    )

    assert "git add reports/daily reports/periods reports/status" not in workflow
    assert "if [ -f reports/status/withheld.json ]; then" in workflow
    assert "git add -u -- reports/status/withheld.json" in workflow
