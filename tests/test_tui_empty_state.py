from workspace_session_manager.tui_empty_state import empty_state_copy


def test_no_sessions_copy_has_first_action_and_palette_path() -> None:
    copy = empty_state_copy("no_sessions")

    assert copy.title == "No sessions"
    assert "press c to create" in copy.overview
    assert "p palette" in copy.metadata


def test_filtered_copy_explains_how_to_clear_the_filter() -> None:
    copy = empty_state_copy("filtered")

    assert copy.title == "No matches"
    assert "clear search" in copy.overview
    assert "1 for All sessions" in copy.overview


def test_disconnected_copy_points_to_recovery_commands() -> None:
    copy = empty_state_copy("disconnected")

    assert copy.title == "Runtime disconnected"
    assert "doctor --actionable" in copy.metadata


def test_attention_copy_distinguishes_scan_in_progress() -> None:
    checking = empty_state_copy("attention", attention_checking=True, scanned=2, eligible=4)
    clear = empty_state_copy("attention", attention_checking=False, scanned=4, eligible=4)

    assert checking.title == "Checking session alerts"
    assert "Checked 2 of 4" in checking.overview
    assert clear.title == "No sessions need attention"
    assert "no warning" in clear.overview
