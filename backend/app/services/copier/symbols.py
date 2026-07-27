"""Turning the master's symbol into the slave broker's name for it.

The same instrument is `EURUSD` at one broker, `EURUSD.r` at another,
`EURUSDm` at a third and `EURUSD_SB` at a fourth. Getting this wrong means
either no trade or, far worse, a trade on the wrong instrument, so resolution
is explicit and ordered rather than clever.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SymbolRules:
    """Per-slave naming rules."""

    #: Explicit overrides, checked first: {"EURUSD": "EURUSD.pro"}.
    overrides: dict[str, str] = field(default_factory=dict)
    prefix: str = ""
    suffix: str = ""


def candidates(master_symbol: str, rules: SymbolRules) -> list[str]:
    """Names to try on the slave, best guess first.

    Only the first candidate is a decision; the rest are fallbacks that are
    each checked against the broker's real symbol list before use.
    """
    symbol = master_symbol.strip()
    if not symbol:
        return []

    out: list[str] = []

    def add(value: str) -> None:
        if value and value not in out:
            out.append(value)

    # 1. An explicit override is the user telling us the answer.
    override = rules.overrides.get(symbol) or rules.overrides.get(symbol.upper())
    if override:
        add(override)
        return out

    # 2. The configured prefix/suffix.
    if rules.prefix or rules.suffix:
        add(f"{rules.prefix}{symbol}{rules.suffix}")

    # 3. The name as-is.
    add(symbol)

    # 4. The bare name, in case the master carries a suffix the slave lacks.
    bare = strip_affixes(symbol, rules)
    add(bare)
    if rules.prefix or rules.suffix:
        add(f"{rules.prefix}{bare}{rules.suffix}")

    return out


def strip_affixes(symbol: str, rules: SymbolRules) -> str:
    out = symbol
    if rules.prefix and out.startswith(rules.prefix):
        out = out[len(rules.prefix) :]
    if rules.suffix and out.endswith(rules.suffix):
        out = out[: -len(rules.suffix)]
    return out


def resolve(master_symbol: str, rules: SymbolRules, available: list[str]) -> str | None:
    """The slave symbol to trade, or None when nothing matches.

    ``available`` is the broker's own symbol list. Nothing outside it is ever
    returned: guessing a name that does not exist is how a copier ends up
    silently doing nothing, and guessing one that exists but is the wrong
    instrument is how it ends up doing something much worse.
    """
    if not available:
        return None

    by_upper = {name.upper(): name for name in available}

    for candidate in candidates(master_symbol, rules):
        exact = by_upper.get(candidate.upper())
        if exact:
            return exact

    # Last resort: a unique symbol that starts with the bare name. Anything
    # ambiguous is refused rather than guessed at.
    bare = strip_affixes(master_symbol.strip(), rules).upper()
    if len(bare) >= 3:
        matches = [name for name in available if name.upper().startswith(bare)]
        if len(matches) == 1:
            return matches[0]

    return None
