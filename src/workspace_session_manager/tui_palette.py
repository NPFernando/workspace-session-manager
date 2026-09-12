"""Pure search policy used by the command palette."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher


def normalize_palette_key(value: str) -> str:
    """Normalize a palette label or query while removing visual decorations."""

    compact = re.sub(r"^\s*(\[[^\]]+\]|[^\w\s])\s*", "", value.strip())
    return re.sub(r"\s+", " ", compact).strip().casefold()


def palette_alias_typo_boost(
    query: str,
    display: str,
    aliases: Mapping[str, Sequence[str]],
    *,
    fuzzy_score: int = 0,
) -> int:
    """Return the additional score for semantic aliases or likely typos.

    Textual's matcher remains responsible for the normal fuzzy score and
    highlighting. This helper only contributes the application's discoverability
    boosts, making natural-language aliases independently testable.
    """

    normalized_query = normalize_palette_key(query)
    normalized_display = normalize_palette_key(display)
    if not normalized_query or not normalized_display:
        return 0

    for prefix, values in aliases.items():
        if prefix not in normalized_display:
            continue
        if any(
            normalized_query in alias.casefold() or alias.casefold() in normalized_query
            for alias in values
        ):
            return 22

    if fuzzy_score > 0 or len(normalized_query) < 3:
        return 0
    ratio = SequenceMatcher(None, normalized_query, normalized_display).ratio()
    return int(26 * ratio) if ratio >= 0.62 else 0
