"""HTTP client for the five documented endpoints.

Only these are implemented on purpose — the mini-program exposes ~50 more, but
none of them are documented and all of them are out of scope here:

    GET  /api/3.0/citys
    POST /api/3.0/initialize
    GET  /gateway/wechat/api/2.0/stores
    GET  /gateway/wechat/api/2.0/getStoreById
    GET  /gateway/wechat/api/2.0/store/timeslots
"""
from __future__ import annotations

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

from . import keys, signing

BASE = "https://sapi.sushiro.com.cn"

CITIES = "/api/3.0/citys"
INITIALIZE = "/api/3.0/initialize"
STORES = "/gateway/wechat/api/2.0/stores"
STORE_BY_ID = "/gateway/wechat/api/2.0/getStoreById"
TIMESLOTS = "/gateway/wechat/api/2.0/store/timeslots"

DEFAULT_APP_VERSION = "1.1.28"
TIMEOUT = 20
_MIN_INTERVAL = 0.3  # gateway advertises X-RateLimit-Limit: 60 per minute


class ApiError(RuntimeError):
    """A call that did not produce usable data."""

    def __init__(self, message: str, *, status: int = 0, payload: object = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def business_error(payload: object) -> str | None:
    """Return the message when the envelope reports a business-level failure.

    Successful calls answer with ``status: 1``. A failed one answers HTTP 200
    with ``status: 0`` and an ``error_code``, so status alone is not enough.
    """
    if isinstance(payload, dict) and "status" in payload:
        if str(payload.get("status")) != "1":
            code = payload.get("error_code") or "?"
            message = payload.get("message") or "unknown error"
            return f"{message} (error_code={code})"
    return None


class Api:
    def __init__(self, token: str = "", *, app_version: str = DEFAULT_APP_VERSION,
                 session_id: str | None = None, base: str = BASE):
        self.token = token
        self.app_version = app_version
        self.session_id = session_id or secrets.token_hex(8)
        self.base = base
        self._last_call = 0.0

    # -- transport ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        headers = {
            "X-App-Client": "miniapp",
            "X-Miniapp-Version": self.app_version,
            "x-miniapp-session-id": self.session_id,
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # Measured 2026-11-05: no implemented endpoint rejects a missing or
        # garbage X-App-Code, so an unset AES key must not block plain reads.
        try:
            headers["X-App-Code"] = signing.app_code()
        except keys.MissingKey:
            pass
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def request(self, path: str, params: dict | None = None, *, signed: bool = False,
                method: str = "GET", retries: int = 2) -> object:
        query = signing.signed_params(params) if signed else dict(params or {})
        url = self.base + path
        body = None
        if method == "GET":
            url += "?" + urllib.parse.urlencode(query)
        else:
            body = urllib.parse.urlencode(query).encode()

        attempt = 0
        while True:
            wait = _MIN_INTERVAL - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            req = urllib.request.Request(url, data=body, headers=self._headers(), method=method)
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
                    return json.loads(response.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as exc:
                payload = exc.read().decode("utf-8", "replace")
                try:
                    parsed = json.loads(payload)
                except json.JSONDecodeError:
                    parsed = payload[:500]
                if exc.code == 429 and attempt < retries:
                    attempt += 1
                    time.sleep(2 * attempt)
                    continue
                detail = parsed.get("message") if isinstance(parsed, dict) else parsed
                raise ApiError(f"HTTP {exc.code}: {detail}", status=exc.code, payload=parsed)
            except urllib.error.URLError as exc:
                if attempt < retries:
                    attempt += 1
                    time.sleep(1.5 * attempt)
                    continue
                raise ApiError(f"network error: {exc.reason}", status=0)

    # -- documented operations --------------------------------------------

    def cities(self) -> list[dict]:
        payload = self.request(CITIES, {}, signed=True)
        error = business_error(payload)
        if error:
            raise ApiError(error, payload=payload)
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            return data.get("city_list") or []
        return data or []

    def stores(self, latitude: float = 31.23, longitude: float = 121.41,
               numresults: int = 10000) -> list[dict]:
        payload = self.request(STORES, {
            "latitude": latitude, "longitude": longitude, "numresults": numresults,
        })
        if isinstance(payload, list):
            return payload
        error = business_error(payload)
        raise ApiError(error or "unexpected store response", payload=payload)

    def store(self, store_id: int | str) -> dict:
        """Single store. The response is the store object itself, not a wrapper."""
        payload = self.request(STORE_BY_ID, {"storeId": store_id})
        error = business_error(payload)
        if error:
            raise ApiError(error, payload=payload)
        if not isinstance(payload, dict):
            raise ApiError("unexpected store response", payload=payload)
        return payload.get("data") if "data" in payload else payload

    def slots(self, store_id: int | str, numpersons: int = 2,
              table_type: str = "T") -> list[dict]:
        payload = self.request(TIMESLOTS, {
            "storeId": store_id, "numpersons": numpersons, "tableType": table_type,
        })
        if isinstance(payload, list):
            return payload
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list):
            return data
        error = business_error(payload)
        raise ApiError(error or "unexpected timeslot response", payload=payload)

    def initialize(self, js_code: str, device_id: str, long_token: int = 1) -> dict:
        """Exchange a WeChat login code for an auth token.

        ``js_code`` comes from ``wx.login()`` on the phone and is single-use, so
        this cannot run unattended. It stays here for protocol completeness and
        for parsing captured initialize responses.
        """
        return self.request(INITIALIZE, {
            "long_token": long_token, "js_code": js_code, "device_id": device_id,
        }, signed=True, method="POST")
