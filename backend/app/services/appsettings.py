"""User-facing application settings: defaults, persistence and merge logic.

Everything a user can tweak from the Settings page lives here as a single JSON
document in the ``setting`` table under the key ``app``. Storing it as one
document keeps migrations trivial: unknown keys are ignored, missing keys fall
back to the defaults below.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from ..models import Setting

SETTINGS_KEY = "app"

DEFAULT_SETTINGS: dict[str, Any] = {
    "general": {
        # IANA timezone used to bucket trades into days for the calendar.
        "timezone": "Europe/Copenhagen",
        "currency": "USD",
        "currency_symbol": "$",
        "week_starts_on": "monday",  # monday | sunday
        "default_period": "last_30_days",
        "date_format": "yyyy-MM-dd",
        "theme": "dark",  # dark | light | system
        "accent": "jade",
        # Swaps the profit/loss green-red pair for a blue-amber pair that
        # stays distinguishable with red-green colour blindness.
        "colorblind_mode": False,
        # Money is hidden by default so a screenshot of the dashboard can be
        # shared without showing what the account is worth. Percentages and R
        # say everything about how it is going and nothing about its size.
        "show_amounts": False,
    },
    "risk": {
        # Trades whose |realized R| is below this are treated as breakeven.
        "breakeven_threshold_r": 0.1,
        # excluded | loss | win  -- how breakevens affect win rate & stats.
        "breakeven_handling": "excluded",
        # Also treat tiny money outcomes as breakeven when no R is available.
        "breakeven_threshold_money": 1.0,
        # ... or as a share of account size, for people who think in percent
        # rather than in their account currency. Zero disables it.
        "breakeven_threshold_percent": 0.0,
        # How risk is determined when the broker gave us no stop loss.
        # from_stop | fixed_amount | percent_of_balance
        "fallback_risk_mode": "percent_of_balance",
        "fixed_risk_amount": 100.0,
        "risk_percent": 1.0,
        "include_commission_in_pnl": True,
        "include_swap_in_pnl": True,
        # Count costs against the risk when computing realized R.
        "r_uses_net_pnl": True,
    },
    "stats": {
        "risk_free_rate": 0.0,  # annual, as a percentage
        "trading_days_per_year": 252,
        "sharpe_basis": "daily",  # daily | trade
        "min_trades_for_score": 10,
    },
    "zulu_score": {
        # A weight of 0 switches a component off, and every one of them can be
        # off: the score is then withheld rather than reported as zero, because
        # "nothing was measured" and "everything measured badly" are not the
        # same statement.
        "weights": {
            "win_rate": 1.0,
            "profit_factor": 1.0,
            "avg_win_loss": 1.0,
            "max_drawdown": 1.0,
            # Off by default, but kept: how even the losses were is a real
            # thing to want, and it is the honest measure when trades are all
            # you have. It is not what most people mean by risk.
            "loss_consistency": 0.0,
            "recovery_factor": 1.0,
            "consistency": 1.0,
        },
        # Value at which a component scores 100.
        "targets": {
            "win_rate": 55.0,  # percent
            "profit_factor": 2.0,
            "avg_win_loss": 2.0,
            "max_drawdown_pct": 20.0,  # a drawdown this deep scores 0
            "worst_loss_multiple": 3.0,  # the worst loss may be 3x a typical one
            "recovery_factor": 3.0,
            "consistency": 100.0,  # percent
        },
    },
    # Tags are grouped so a long list stays navigable. The three defaults are
    # the ones that earn their place -- what you were trading, what you got
    # wrong, and what you were feeling -- but they are only defaults.
    # The economic calendar. High-impact dollar releases only by default: a
    # calendar showing forty entries a day is one nobody reads, which is worse
    # than not having one because it looks like cover.
    "news": {
        "countries": ["us"],
        "importance": 1,  # 1 high, 0 medium and up, -1 everything
    },
    "tags": {
        "categories": [
            {"value": "setup", "label": "Setup"},
            {"value": "mistake", "label": "Mistake"},
            {"value": "emotion", "label": "Behaviour"},
        ],
    },
    "mt5": {
        # ea  -> a terminal's Expert Advisor pushes to this server
        # off -> manual import only
        "sync_mode": "ea",
        # When to restart the terminals so MetaTrader's own updates install
        # during a quiet hour. Monday=0; Sunday at 3am by default.
        "restart_weekday": 6,
        "restart_hour": 3,
        "auto_sync_on_load": True,
        "auto_sync_min_interval_seconds": 120,
        "history_days_on_full_sync": 730,
    },
    "charts": {
        # local -> replay from candles stored by the Expert Advisor
        # tradingview -> free TradingView Advanced Chart widget
        "provider": "local",
        "default_timeframe": "M5",
        # Counted in bars of whichever timeframe is being shown, so zooming out
        # widens the window rather than drawing the same afternoon as four
        # candles. Half a day either side at the collected timeframe, so the
        # chart opens on the session the trade happened in rather than on the
        # twenty bars around the entry.
        "candles_before": 144,
        "candles_after": 144,
        # Maps broker symbols to TradingView tickers, e.g. {"EURUSD": "OANDA:EURUSD"}
        "tradingview_prefix": "",
        "symbol_map": {},
    },
}

# Tags created on first run so the journal is useful immediately.
DEFAULT_TAGS: list[dict[str, Any]] = [
    {"name": "A+ setup", "color": "#22c55e", "category": "setup"},
    {"name": "B setup", "color": "#84cc16", "category": "setup"},
    {"name": "C setup", "color": "#eab308", "category": "setup"},
    {"name": "Breakout", "color": "#38bdf8", "category": "setup"},
    {"name": "Pullback", "color": "#60a5fa", "category": "setup"},
    {"name": "Reversal", "color": "#a78bfa", "category": "setup"},
    {"name": "News trade", "color": "#f472b6", "category": "setup"},
    {"name": "Bad entry", "color": "#ef4444", "category": "mistake"},
    {"name": "Late entry", "color": "#f97316", "category": "mistake"},
    {"name": "Overrisked", "color": "#dc2626", "category": "mistake"},
    {"name": "Moved stop", "color": "#e11d48", "category": "mistake"},
    {"name": "No stop loss", "color": "#b91c1c", "category": "mistake"},
    {"name": "Early exit", "color": "#fb923c", "category": "mistake"},
    {"name": "Held too long", "color": "#f59e0b", "category": "mistake"},
    {"name": "No setup", "color": "#ea580c", "category": "mistake"},
    {"name": "Overtrading", "color": "#d946ef", "category": "emotion"},
    {"name": "FOMO trade", "color": "#c026d3", "category": "emotion"},
    {"name": "Revenge trade", "color": "#9333ea", "category": "emotion"},
    {"name": "Hesitation", "color": "#8b5cf6", "category": "emotion"},
    {"name": "Good execution", "color": "#14b8a6", "category": "emotion"},
]


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``."""
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


#: Modes that no longer exist, and what they became.
RETIRED_SYNC_MODES = {
    # "bridge" drove a containerised MetaTrader that this server logged in and
    # polled. It never worked -- see docs/metatrader.md -- and an install that
    # upgrades while still set to it would otherwise land on a mode nothing
    # implements, which reads as the sync being broken rather than moved.
    "bridge": "ea",
}


def get_app_settings(db: Session) -> dict[str, Any]:
    row = db.get(Setting, SETTINGS_KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    merged = deep_merge(DEFAULT_SETTINGS, stored)
    mode = merged.get("mt5", {}).get("sync_mode")
    if mode in RETIRED_SYNC_MODES:
        merged["mt5"]["sync_mode"] = RETIRED_SYNC_MODES[mode]
    _migrate_score_weights(stored, merged)
    return merged


def _migrate_score_weights(stored: dict[str, Any], merged: dict[str, Any]) -> None:
    """Give drawdown its place back on an install that predates it.

    Anyone who has opened the score settings has the whole weight table saved,
    so the new component would merge in at the default weight while the one it
    replaces kept the weight it was given when it was the only choice --
    leaving both counted, which is neither what the defaults say nor what
    anyone chose. Only an untouched weight is moved; a deliberate one is left
    exactly as it is.
    """
    weights = stored.get("zulu_score", {}).get("weights") or {}
    if "max_drawdown" in weights:
        return
    merged["zulu_score"]["weights"]["max_drawdown"] = 1.0
    if weights.get("loss_consistency") == 1.0:
        merged["zulu_score"]["weights"]["loss_consistency"] = 0.0


def save_app_settings(db: Session, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge ``patch`` into the stored settings and return the effective result."""
    row = db.get(Setting, SETTINGS_KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    merged = deep_merge(stored, patch)
    # Drop anything that is not part of the schema so the document stays clean.
    merged = _prune_unknown(merged, DEFAULT_SETTINGS)
    if row is None:
        row = Setting(key=SETTINGS_KEY, value=merged)
        db.add(row)
    else:
        row.value = merged
    db.flush()
    return deep_merge(DEFAULT_SETTINGS, merged)


def _prune_unknown(value: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in value.items():
        if key not in schema:
            continue
        # Free-form maps keep whatever the user put in them.
        if isinstance(val, dict) and isinstance(schema[key], dict) and schema[key]:
            out[key] = _prune_unknown(val, schema[key])
        else:
            out[key] = val
    return out
