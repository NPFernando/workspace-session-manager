from workspace_session_manager.tui_interaction import interaction_mode_presentation


def test_normal_mode_has_no_overlay_or_search_state() -> None:
    result = interaction_mode_presentation("normal")

    assert result.mode_class == "mode-normal"
    assert result.overlay_active is False
    assert result.searching is False


def test_search_mode_is_not_an_overlay() -> None:
    result = interaction_mode_presentation("search")

    assert result.mode_class == "mode-search"
    assert result.overlay_active is False
    assert result.searching is True


def test_modal_modes_activate_overlay_state() -> None:
    for mode in ("filter", "form", "command_palette", "manage", "confirmation"):
        result = interaction_mode_presentation(mode)

        assert result.mode_class == f"mode-{mode}"
        assert result.overlay_active is True
        assert result.searching is False


def test_unknown_mode_fails_closed_to_normal() -> None:
    result = interaction_mode_presentation("future-mode")

    assert result.mode_class == "mode-normal"
    assert result.overlay_active is False
    assert result.searching is False
