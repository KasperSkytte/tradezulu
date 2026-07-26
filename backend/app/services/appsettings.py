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
        "accent": "violet",
    },
    "risk": {
        # Trades whose |realized R| is below this are treated as breakeven.
        "breakeven_threshold_r": 0.1,
        # excluded | loss | win  -- how breakevens affect win rate & stats.
        "breakeven_handling": "excluded",
        # Also treat tiny money outcomes as breakeven when no R is available.
        "breakeven_threshold_money": 1.0,
        # How risk is determined when the broker gave us no stop loss.
        # from_stop | fixed_amount | percent_of_balance
        "fallback_risk_mode": "percent_of_balance",
        "fixed_risk_amount": 100.0,
        "risk_percent": 1.0,
        # Account size used for percentage metrics; 0 => use account balance.
        "account_size": 0.0,
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
        "weights": {
            "win_rate": 1.0,
            "profit_factor": 1.0,
            "avg_win_loss": 1.0,
            "max_drawdown": 1.0,
            "recovery_factor": 1.0,
            "consistency": 1.0,
        },
        # Value at which a component scores 100.
        "targets": {
            "win_rate": 55.0,  # percent
            "profit_factor": 2.0,
            "avg_win_loss": 2.0,
            "max_drawdown": 20.0,  # percent, lower is better
            "recovery_factor": 3.0,
            "consistency": 100.0,  # percent
        },
    },
    "mt5": {
        # ea      -> the Expert Advisor pushes to /api/mt5/ingest
        # bridge  -> this server pulls from a MetaTrader5 bridge service
        # off     -> manual import only
        "sync_mode": "ea",
        "bridge_url": "http://mt5-bridge:8080",
        "bridge_timeout_seconds": 60,
        "auto_sync_on_load": True,
        "auto_sync_min_interval_seconds": 120,
        "history_days_on_full_sync": 730,
    },
    "charts": {
        # local -> replay from candles stored by the EA/bridge
        # tradingview -> free TradingView Advanced Chart widget
        "provider": "local",
        "default_timeframe": "M15",
        "candles_before": 120,
        "candles_after": 60,
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


def get_app_settings(db: Session) -> dict[str, Any]:
    row = db.get(Setting, SETTINGS_KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    return deep_merge(DEFAULT_SETTINGS, stored)


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
