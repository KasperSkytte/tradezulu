"""The brokers TradeZulu knows about.

One file describes them, shared with the provisioner: it decides which
MetaTrader build gets installed, and it is what the account form offers so
nobody has to remember whether their server is called VantageMarkets-Live or
VantageInternational-Live.

Which terminal that implies is deliberately not exposed. It is the
provisioner's business, and asking someone to know which build their broker
needs is the setup step this is meant to remove.
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: In the image the file sits beside the app; in a checkout it is under agent/.
CANDIDATES = (
    Path(os.getenv("TZ_BROKERS_FILE", "")) if os.getenv("TZ_BROKERS_FILE") else None,
    Path("/app/brokers.json"),
    Path(__file__).resolve().parents[3] / "agent" / "brokers.json",
)


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    for path in CANDIDATES:
        if path is None or not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text())
        except (OSError, ValueError):
            log.warning("could not read %s", path)
            continue
        return {k: v for k, v in raw.items() if isinstance(v, dict)}
    log.warning("no brokers.json found; the account form will accept free text only")
    return {}


def list_brokers() -> list[dict[str, Any]]:
    """What the account form should offer.

    "Other broker" sorts last however the file is ordered: it is the fallback,
    not a choice anyone is looking for.
    """
    out = [
        {
            "key": key,
            "label": str(entry.get("label") or key),
            "servers": [str(s) for s in entry.get("servers", []) if s],
            # TradingView's exchange prefix for this broker's feed, so a chart
            # resolves without anyone having to know that Vantage is VANTAGE:.
            "tradingview_prefix": str(entry.get("tradingview_prefix") or ""),
            "matches": [str(m) for m in entry.get("matches", []) if m],
        }
        for key, entry in _load().items()
    ]
    out.sort(key=lambda b: (b["key"] == "default", b["label"].lower()))
    return out
