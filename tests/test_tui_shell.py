from workspace_session_manager.tui_shell import ActionRailState, render_action_rail


def test_wide_action_rail_keeps_beginner_actions_visible() -> None:
    rail = render_action_rail(
        ActionRailState(
            mode="wide",
            ascii_only=False,
            concise=True,
            create_hint="c Create(Codex)",
        )
    )

    assert "Enter Attach" in rail
    assert "c Create(Codex)" in rail
    assert "/ Search" in rail
    assert "p Palette" in rail
    assert "? shortcuts" in rail


def test_detail_action_rail_uses_manage_for_stopped_sessions() -> None:
    rail = render_action_rail(
        ActionRailState(
            mode="detail",
            ascii_only=True,
            concise=True,
            create_hint="c Create",
            selected_is_stopped=True,
        )
    )

    assert "Enter Manage" in rail
    assert "Enter Attach" not in rail
    assert "Esc back" in rail


def test_search_action_rail_does_not_include_dashboard_actions() -> None:
    rail = render_action_rail(
        ActionRailState(
            mode="search",
            ascii_only=True,
            concise=False,
            create_hint="c Create",
            shortcut_pulse="Type a project name",
        )
    )

    assert "Enter apply" in rail
    assert "Ctrl+U clear" in rail
    assert "Tip: Type a project name" in rail
    assert "p Palette" not in rail
