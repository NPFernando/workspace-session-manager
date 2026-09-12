from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from workspace_session_manager.tui_status_rows import critical_health_summary, render_jobs_row


def test_jobs_row_prefers_active_work_over_recent_history() -> None:
    now = datetime.now(UTC)
    row = render_jobs_row(
        active=["scanning alerts"],
        recent_jobs=[SimpleNamespace(label="old job", severity="success", at=now)],
        now=now,
        ascii_only=False,
        spinner="◐",
    )

    assert row == "◐ Jobs: scanning alerts"


def test_jobs_row_formats_bounded_recent_history_with_ascii_markers() -> None:
    now = datetime.now(UTC)
    jobs = [
        SimpleNamespace(label=f"job {index}", severity="success", at=now - timedelta(seconds=index))
        for index in range(4)
    ]

    row = render_jobs_row(
        active=[],
        recent_jobs=jobs,
        now=now,
        ascii_only=True,
        spinner="...",
    )

    assert row.startswith("Recent jobs: OK job 0")
    assert "job 3" not in row


def test_critical_health_summary_is_actionable_and_dismissible() -> None:
    summary = critical_health_summary(names=["Disk", "Docker", "APT", "Extra"], dismissed=False)

    assert "Disk, Docker, APT" in summary
    assert "Press h to review" in summary
    assert critical_health_summary(names=["Disk"], dismissed=True) == ""
