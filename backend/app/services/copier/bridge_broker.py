"""The :class:`Broker` the copier actually uses: the bridge, over HTTP.

Thin on purpose. Every call maps to one bridge route, errors are raised as
:class:`BrokerUnavailable` so the runner can record them as a failed action,
and nothing here retries — a copier that retries inside a poll loop turns one
broker hiccup into a burst of duplicate orders.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ...config import settings

log = logging.getLogger(__name__)


class BrokerUnavailable(RuntimeError):
    pass


class BridgeBroker:
    def __init__(self, base_url: str, token: str = "", timeout: float = 60.0) -> None:
        # The URL is an application setting rather than an environment one, so
        # the caller reads it and passes it in; only the token is deployment
        # level and can sensibly default.
        self.base_url = (base_url or "").rstrip("/")
        self.token = token or settings.bridge_token
        self.timeout = timeout

    # -- plumbing --------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"X-Bridge-Token": self.token} if self.token else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        if not self.base_url:
            raise BrokerUnavailable("no bridge is configured")

        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise BrokerUnavailable(f"could not reach the bridge: {exc}") from exc

        if response.status_code == 401:
            raise BrokerUnavailable("the bridge rejected our token")

        try:
            payload = response.json()
        except ValueError as exc:
            raise BrokerUnavailable(
                f"the bridge replied with something that is not JSON ({response.status_code})"
            ) from exc

        if not payload.get("ok", False):
            raise BrokerUnavailable(str(payload.get("error", "the bridge refused the request")))
        return payload.get("result")

    # -- pool ------------------------------------------------------------
    def configure(self, accounts: list[dict[str, Any]]) -> Any:
        """Tell the bridge which accounts to keep terminals for."""
        return self._request("POST", "/accounts/configure", json={"accounts": accounts})

    def workers(self) -> list[dict[str, Any]]:
        if not self.base_url:
            return []
        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.get(f"{self.base_url}/accounts", headers=self._headers())
            return response.json().get("workers", [])
        except (httpx.HTTPError, ValueError):
            return []

    # -- reads -----------------------------------------------------------
    def account(self, account_id: int) -> dict[str, Any]:
        return self._request("GET", f"/accounts/{account_id}/account")

    def positions(self, account_id: int) -> list[dict[str, Any]]:
        return self._request("GET", f"/accounts/{account_id}/positions") or []

    def symbols(self, account_id: int) -> list[str]:
        return self._request("GET", f"/accounts/{account_id}/symbols") or []

    def symbol_spec(self, account_id: int, symbol: str) -> dict[str, Any]:
        return self._request(
            "GET", f"/accounts/{account_id}/symbol_spec", params={"symbol": symbol}
        )

    # -- writes ----------------------------------------------------------
    def open(self, account_id: int, **kwargs: Any) -> dict[str, Any]:
        return self._request("POST", f"/accounts/{account_id}/open", json=kwargs)

    def close(
        self, account_id: int, ticket: int, volume: float | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"ticket": ticket}
        if volume is not None:
            body["volume"] = volume
        return self._request("POST", f"/accounts/{account_id}/close", json=body)

    def modify(
        self, account_id: int, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/accounts/{account_id}/modify",
            json={"ticket": ticket, "stop_loss": stop_loss, "take_profit": take_profit},
        )
