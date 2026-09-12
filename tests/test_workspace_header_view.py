from workspace_session_manager.workspace_header_view import build_header_summary


def _summary(**overrides: object):
    values: dict[str, object] = {
        "total": 2,
        "attached": 1,
        "detached": 1,
        "stopped": 0,
        "todo": 1,
        "doing": 1,
        "done": 0,
        "warnings": 0,
        "tmux_connected": True,
        "attention_scan_error": False,
        "scanned": 2,
        "eligible": 2,
        "latency_ms": 4,
        "render_rows": 2,
        "render_ms": 1,
        "effective_profile": "ssh-safe",
        "refresh_interval": 2.0,
        "motion": "off",
        "capability": "unicode/color/motion-off",
        "ascii_only": False,
        "active_filters": [],
        "quick_filter": "all",
        "filter_query": "",
        "refreshing": False,
        "spinner": "...",
        "last_refreshed_age": 0,
    }
    values.update(overrides)
    return build_header_summary(**values)


def test_header_summary_reports_counts_and_connection() -> None:
    summary = _summary()

    assert "2 sessions" in summary.counts
    assert "1 attached" in summary.counts
    assert "No warnings" in summary.counts
    assert summary.connection == "tmux connected • Updated now"


def test_header_summary_reports_filters_and_delayed_attention() -> None:
    summary = _summary(
        warnings=2,
        attention_scan_error=True,
        active_filters=["Attention"],
        quick_filter="warnings",
        filter_query="api",
        ascii_only=True,
        tmux_connected=False,
        last_refreshed_age=None,
    )

    assert "3 known warnings / alerts delayed" in summary.counts
    assert 'Search "api"' in summary.filter_text
    assert "Quick warnings" in summary.filter_text
    assert summary.separator == " | "
    assert summary.connection == "tmux unavailable"


def test_header_summary_uses_refreshing_state_over_stale_timestamp() -> None:
    summary = _summary(refreshing=True, last_refreshed_age=30)

    assert summary.connection == "Refreshing ..."
