from workspace_session_manager.tui_refresh_view import refresh_failure_copy, stale_selection_copy


def test_refresh_failure_copy_gives_retry_action() -> None:
    copy = refresh_failure_copy("tmux server unavailable")

    assert copy.title == "Refresh failed"
    assert "tmux server unavailable" in copy.message
    assert "press r to retry" in copy.message


def test_stale_selection_copy_explains_return_to_list() -> None:
    title, message = stale_selection_copy()

    assert title == "Returned to session list"
    assert "no longer available" in message
