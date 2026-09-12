from workspace_session_manager.workspace_toolbar_view import (
    render_shortcut_rail,
    render_toolbar_summary,
)


def test_shortcut_rail_changes_with_interaction_mode_and_selection() -> None:
    assert "c Create" in render_shortcut_rail(mode="normal", selected=False)
    assert "Enter Open" in render_shortcut_rail(mode="normal", selected=True)
    assert "Ctrl+U Clear" in render_shortcut_rail(mode="search", selected=False)
    assert "Type search" in render_shortcut_rail(mode="palette", selected=True)


def test_toolbar_summary_preserves_inventory_and_settings() -> None:
    summary = render_toolbar_summary(
        shown=2,
        total=4,
        separator=" / ",
        grouping="Project",
        density="Comfortable",
        text_scale="Readable",
        motion="subtle",
        high_contrast=True,
        filter_label="Warnings",
        shortcuts="c Create | f Filter",
    )

    assert "Sessions 2/4 shown" in summary
    assert "Group: Project (g)" in summary
    assert "Contrast: on (C)" in summary
    assert "Shortcuts: c Create | f Filter" in summary
