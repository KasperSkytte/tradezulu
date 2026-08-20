"""Turning a slave account's stored JSON into the engine's dataclasses.

The database keeps one loose ``copy_settings`` document per account rather
than thirty columns, so the shape can grow without a migration. This module is
the single place that knows how that document maps onto :class:`SizingConfig`
and :class:`RiskConfig`, and it is forgiving in one direction only: unknown
keys are ignored, missing keys take the default, but a key that is present and
nonsense is *not* quietly turned into a permissive value.
"""

from __future__ import annotations

from typing import Any

from .risk import BreachAction, DrawdownBasis, RiskConfig
from .sizing import SizingConfig, SizingMode
from .symbols import SymbolRules, detect_affixes

#: The sizing modes that decide a volume from what the trade may lose. Each
#: needs a stop on the master to measure that against, so each implies that a
#: stopless trade is refused rather than sized some other way.
RISK_MODES = {
    SizingMode.RISK_PERCENT.value,
    SizingMode.RISK_PERCENT_BALANCE.value,
    SizingMode.RISK_AMOUNT.value,
}


def mode_needs_stop(data: dict[str, Any]) -> bool:
    return str(data.get("mode", "")).strip().lower() in RISK_MODES


def _float(source: dict[str, Any], key: str, default: float) -> float:
    value = source.get(key, default)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    # A negative limit is meaningless and would read as "no limit" downstream.
    return out if out >= 0 else default


def _int(source: dict[str, Any], key: str, default: int) -> int:
    value = source.get(key, default)
    try:
        out = int(value)
    except (TypeError, ValueError):
        return default
    return out if out >= 0 else default


def _bool(source: dict[str, Any], key: str, default: bool) -> bool:
    value = source.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _symbols(source: dict[str, Any], key: str) -> list[str]:
    value = source.get(key) or []
    if isinstance(value, str):
        value = [part for part in value.replace(",", " ").split() if part]
    if not isinstance(value, list):
        return []
    return [str(item).strip().upper() for item in value if str(item).strip()]


def sizing_from(settings: dict[str, Any] | None) -> SizingConfig:
    data = settings or {}
    raw_mode = str(data.get("mode", SizingMode.BALANCE_RATIO.value)).strip().lower()
    try:
        mode = SizingMode(raw_mode)
    except ValueError:
        mode = SizingMode.BALANCE_RATIO

    largest, refuses = _largest_position(data)
    return SizingConfig(
        mode=mode,
        fixed_lot=_float(data, "fixed_lot", 0.01),
        multiplier=_float(data, "multiplier", 1.0),
        risk_percent=_float(data, "risk_percent", 1.0),
        risk_amount=_float(data, "risk_amount", 0.0),
        max_lot=largest,
        max_lot_refuses=refuses,
        min_lot=_float(data, "min_lot", 0.0),
    )


LEGACY_LOT_REFUSAL = "max_lot_per_trade"


def _largest_position(data: dict[str, Any]) -> tuple[float, bool]:
    """The one lot limit, and whether reaching it refuses or caps.

    There were two settings for this: ``max_lot`` cut the order down to size
    and ``max_lot_per_trade`` threw it away. Both could be set, to different
    numbers, and then only the smaller ever had an effect -- with nothing on
    the form to say which.

    The old key wins while it is still there, because an account that was
    refusing must not quietly start trading a smaller size instead. It stops
    being there the moment the settings are saved: :func:`migrate` folds it in
    and drops it, so this only reads documents nobody has opened since.
    """
    cap = _float(data, "max_lot", 0.0)
    legacy = _float(data, LEGACY_LOT_REFUSAL, 0.0)
    if legacy > 0:
        return (min(cap, legacy) if cap > 0 else legacy), True
    return cap, _bool(data, "max_lot_refuses", False)


def migrate(settings: dict[str, Any] | None) -> dict[str, Any]:
    """Bring a stored settings document up to the current shape.

    Applied wherever settings are saved, so an old document is rewritten once
    rather than reinterpreted for ever. It has to happen on the way in: the
    API answers with every current field, defaults included, so a form that
    round-trips an old document would otherwise hand back a fresh
    ``max_lot_refuses: false`` beside the old key it was meant to replace --
    and the account would come out of the edit capping trades it used to
    refuse, with nobody having chosen that.
    """
    data = dict(settings or {})
    if LEGACY_LOT_REFUSAL in data:
        largest, refuses = _largest_position(data)
        data.pop(LEGACY_LOT_REFUSAL)
        data["max_lot"], data["max_lot_refuses"] = largest, refuses
    return data


def risk_from(settings: dict[str, Any] | None) -> RiskConfig:
    data = settings or {}
    raw_action = str(data.get("breach_action", BreachAction.CLOSE_ALL.value)).strip().lower()
    try:
        action = BreachAction(raw_action)
    except ValueError:
        action = BreachAction.CLOSE_ALL

    raw_basis = str(data.get("pause_drawdown_basis", DrawdownBasis.PEAK.value)).strip().lower()
    try:
        basis = DrawdownBasis(raw_basis)
    except ValueError:
        basis = DrawdownBasis.PEAK

    largest, refuses = _largest_position(data)
    return RiskConfig(
        max_risk_percent_per_trade=_float(data, "max_risk_percent_per_trade", 0.0),
        max_lot=largest,
        max_lot_refuses=refuses,
        # A percentage of equity or balance is only a percentage if there is a
        # stop to measure it against, so the two risk modes carry this whether
        # or not the toggle is on. The form shows it as implied rather than
        # letting somebody turn off a rule the mode cannot work without.
        require_stop_loss=(
            _bool(data, "require_stop_loss", False) or mode_needs_stop(data)
        ),
        min_stop_distance_points=_float(data, "min_stop_distance_points", 0.0),
        max_open_positions=_int(data, "max_open_positions", 0),
        max_same_direction=_int(data, "max_same_direction", 0),
        max_positions_per_symbol=_int(data, "max_positions_per_symbol", 0),
        max_total_lots=_float(data, "max_total_lots", 0.0),
        pause_drawdown_percent=_float(data, "pause_drawdown_percent", 0.0),
        pause_drawdown_basis=basis,
        max_daily_drawdown_percent=_float(data, "max_daily_drawdown_percent", 0.0),
        equity_stop_percent=_float(data, "equity_stop_percent", 0.0),
        equity_stop_amount=_float(data, "equity_stop_amount", 0.0),
        breach_action=action,
        take_profit_at_amount=_float(data, "take_profit_at_amount", 0.0),
        take_profit_at_r=_float(data, "take_profit_at_r", 0.0),
        daily_profit_target_percent=_float(data, "daily_profit_target_percent", 0.0),
        max_day_share_of_profit_percent=_float(data, "max_day_share_of_profit_percent", 0.0),
        allowed_symbols=_symbols(data, "allowed_symbols"),
        blocked_symbols=_symbols(data, "blocked_symbols"),
    )


def symbol_rules_from(
    prefix: str,
    suffix: str,
    overrides: dict[str, Any] | None,
    available: list[str] | None = None,
    learned: dict[str, Any] | None = None,
) -> SymbolRules:
    """Naming rules for one slave, detected unless they were set by hand.

    ``available`` is the broker's own symbol list. When nothing is configured,
    the convention is read off it -- a broker that writes ``EURUSD+`` says so
    in every symbol it reports, and nobody should have to type that in. A value
    the user did set always wins, because they may be describing something the
    list cannot show.
    """
    clean: dict[str, str] = {}
    for key, value in (overrides or {}).items():
        key, value = str(key).strip(), str(value).strip()
        if key and value:
            clean[key.upper()] = value

    prefix, suffix = (prefix or "").strip(), (suffix or "").strip()
    if not prefix and not suffix and available:
        prefix, suffix = detect_affixes(available)

    remembered = {
        str(key): str(value)
        for key, value in (learned or {}).items()
        if str(key).strip() and str(value).strip()
    }
    return SymbolRules(
        overrides=clean, prefix=prefix, suffix=suffix, learned=remembered
    )


def mirror_stops_enabled(settings: dict[str, Any] | None) -> bool:
    return _bool(settings or {}, "mirror_stops", True)


def defaults() -> dict[str, Any]:
    """The settings a freshly added slave starts with.

    Deliberately conservative: scale by balance so a small account is not
    handed a large account's lot size, and cap single-trade risk. Nothing here
    matters until the account is armed, but it is what the form shows.
    """
    return {
        "mode": SizingMode.BALANCE_RATIO.value,
        "multiplier": 1.0,
        "fixed_lot": 0.01,
        "risk_percent": 1.0,
        # Only read by the fixed-amount mode, and deliberately 0 rather than a
        # guess: a number invented here would be somebody's real money.
        "risk_amount": 0.0,
        "max_lot": 0.0,
        "max_lot_refuses": False,
        "min_lot": 0.0,
        "mirror_stops": True,
        "max_risk_percent_per_trade": 2.0,
        "require_stop_loss": False,
        "min_stop_distance_points": 0.0,
        "max_open_positions": 0,
        "max_same_direction": 0,
        "max_positions_per_symbol": 0,
        "max_total_lots": 0.0,
        "pause_drawdown_percent": 0.0,
        "pause_drawdown_basis": DrawdownBasis.PEAK.value,
        "max_daily_drawdown_percent": 0.0,
        "equity_stop_percent": 0.0,
        "equity_stop_amount": 0.0,
        "breach_action": BreachAction.CLOSE_ALL.value,
        "take_profit_at_amount": 0.0,
        "take_profit_at_r": 0.0,
        "daily_profit_target_percent": 0.0,
        "max_day_share_of_profit_percent": 0.0,
        "allowed_symbols": [],
        "blocked_symbols": [],
    }
