from workspace_session_manager.tui_actions import session_action_state


def test_unselected_session_disables_contextual_actions() -> None:
    state = session_action_state(enabled=False)

    assert not state.enabled
    assert state.resume_disabled
    assert state.attach_disabled
    assert state.stop_disabled
    assert state.disabled_reason == ""


def test_stopped_session_explains_why_attach_is_unavailable() -> None:
    state = session_action_state(enabled=True, pinned=True, resumable=True)

    assert state.pin_label == "Unpin"
    assert not state.resume_disabled
    assert state.attach_disabled
    assert state.stop_disabled
    assert "Use Resume or Manage" in state.disabled_reason


def test_running_session_exposes_attach_and_pin() -> None:
    state = session_action_state(enabled=True, pinned=False, resumable=False)

    assert state.pin_label == "Pin"
    assert state.resume_disabled
    assert not state.attach_disabled
    assert not state.stop_disabled
