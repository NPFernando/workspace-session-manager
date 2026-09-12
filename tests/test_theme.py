from __future__ import annotations

from pathlib import Path

from workspace_session_manager.config import AppConfig
from workspace_session_manager.context import build_context
from workspace_session_manager.paths import AppPaths
from workspace_session_manager.theme import ThemeManager


def make_paths(tmp_path: Path) -> AppPaths:
    return AppPaths(tmp_path / "config", tmp_path / "state", tmp_path / "cache")


def test_builtin_theme_resolution_is_data_only(tmp_path: Path) -> None:
    manager = ThemeManager(make_paths(tmp_path))
    record = manager.resolve("omarchy")
    assert record.palette.accent == "#f2a65a"
    assert record.palette.source == "builtin"
    assert "auto" in manager.list_names()


def test_custom_theme_is_loaded_from_colors_toml(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    theme_dir = paths.themes_dir / "test-theme"
    theme_dir.mkdir(parents=True)
    (theme_dir / "colors.toml").write_text(
        'mode = "dark"\nbackground = "#101010"\nforeground = "#eeeeee"\naccent = "#ff8800"\n',
        encoding="utf-8",
    )
    record = ThemeManager(paths).resolve("test-theme")
    assert record.palette.name == "test-theme"
    assert record.palette.source == "custom"
    assert record.path.endswith("test-theme/colors.toml")


def test_invalid_custom_theme_falls_back_without_execution(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    theme_dir = paths.themes_dir / "broken"
    theme_dir.mkdir(parents=True)
    (theme_dir / "colors.toml").write_text('accent = "not-code"\n', encoding="utf-8")
    record = ThemeManager(paths).resolve("broken")
    assert record.palette.source == "builtin"


def test_omarchy_state_palette_is_optional(tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "omarchy-state"
    colors = state / "omarchy" / "current" / "theme"
    colors.mkdir(parents=True)
    (colors / "colors.toml").write_text(
        'mode = "dark"\nbackground = "#000001"\nforeground = "#fffffe"\naccent = "#123456"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    record = ThemeManager(make_paths(tmp_path)).resolve("auto")
    assert record.palette.source == "omarchy"
    assert record.following_system


def test_no_color_wins_over_omarchy(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    record = ThemeManager(make_paths(tmp_path)).resolve("auto")
    assert record.palette.name == "monochrome"


def test_context_composes_theme_and_session_services(tmp_path: Path) -> None:
    paths = make_paths(tmp_path)
    context = build_context(paths, AppConfig())
    assert context.paths == paths
    assert context.sessions.paths == paths
    assert context.themes.resolve("omarchy").palette.name == "omarchy"
