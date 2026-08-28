from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_archive_step_guards_optional_status_record() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(
        encoding="utf-8"
    )

    assert "git add reports/daily reports/periods reports/status" not in workflow
    assert "if [ -f reports/status/withheld.json ]; then" in workflow
    assert "git add -u -- reports/status/withheld.json" in workflow
    assert "Snapshot existing withheld notice" in workflow
    assert 'current_sha256\" != \"${{ steps.withheld-before.outputs.sha256 }}' in workflow
    assert "predates this run and is not its failure reason" in workflow


def test_pushes_validate_without_refetching_or_deploying_weather() -> None:
    workflow = (ROOT / ".github" / "workflows" / "pages.yml").read_text(
        encoding="utf-8"
    )

    assert '- cron: "17 11 * * *"' in workflow
    assert "verify-push:" in workflow
    assert "Run tests without refreshing weather data" in workflow
    assert "build:\n    # Pushes validate source only." in workflow
    assert "if: github.event_name != 'push'" in workflow
    assert "git add reports/daily reports/periods" in workflow


def test_watchdog_recovers_only_missing_or_failed_authoritative_runs() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "archive-watchdog.yml"
    ).read_text(encoding="utf-8")

    assert '- cron: "17 13 * * *"' in workflow
    assert "['schedule', 'workflow_dispatch'].includes(run.event)" in workflow
    assert "activeOrSuccessful" in workflow
    assert "createWorkflowDispatch" in workflow


def test_cold_workflow_records_restore_checked_retention_plan() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "cold-archive.yml"
    ).read_text(encoding="utf-8")

    assert "Upload and independently verify release asset" in workflow
    assert "atlas-cold retention-plan --before" in workflow
    assert 'git add "reports/cold/retention-plan.v1.json"' in workflow


def test_cold_watchdog_recovers_oldest_missing_verified_month() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "cold-archive-watchdog.yml"
    ).read_text(encoding="utf-8")

    assert '- cron: "30 5 * * *"' in workflow
    assert "for (const collection of ['daily', 'periods', 'weeks'])" in workflow
    assert "atlas.cold-release-verification/1" in workflow
    assert "checks.restored_editions === true" in workflow
    assert "now.getUTCDate() < 2" in workflow
    assert ".sort()" in workflow
    assert "activeRun" in workflow
    assert "createWorkflowDispatch" in workflow
    assert "inputs: { month: targetMonth }" in workflow
