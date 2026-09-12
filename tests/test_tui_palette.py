from workspace_session_manager.tui_palette import (
    normalize_palette_key,
    palette_alias_typo_boost,
)

ALIASES = {"dashboard · search output": ("grep", "find logs", "output search")}


def test_normalize_palette_key_removes_icons_and_collapses_whitespace() -> None:
    assert normalize_palette_key("  🔎  Dashboard · Search output  ") == (
        "dashboard · search output"
    )


def test_alias_boost_makes_natural_language_commands_discoverable() -> None:
    assert palette_alias_typo_boost("grep", "Dashboard · Search output", ALIASES) == 22


def test_alias_matching_is_bidirectional_for_short_phrases() -> None:
    assert palette_alias_typo_boost("find logs now", "Dashboard · Search output", ALIASES) == 22


def test_likely_typo_gets_a_bounded_boost() -> None:
    result = palette_alias_typo_boost("dashbord search output", "Dashboard · Search output", {})

    assert 0 < result <= 26


def test_empty_or_short_queries_do_not_get_policy_boost() -> None:
    assert palette_alias_typo_boost("", "Dashboard · Search output", ALIASES) == 0
    assert palette_alias_typo_boost("ab", "Dashboard · Search output", ALIASES) == 0


def test_typo_boost_does_not_change_textual_fuzzy_matches() -> None:
    assert (
        palette_alias_typo_boost("dashboard", "Dashboard · Search output", {}, fuzzy_score=10) == 0
    )
