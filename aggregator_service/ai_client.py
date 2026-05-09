from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any

import requests

from aggregator_service.utils import to_json_text


class DailyLimitReached(Exception):
    pass


class RateLimitError(Exception):
    pass


def _parse_seconds(value: str | None) -> float | None:
    if not value:
        return None
    text = value.strip()
    try:
        if "m" in text and "s" in text:
            match = re.search(r"(?:(\d+(?:\.\d+)?)m)?\s*(\d+(?:\.\d+)?)s", text)
            if match:
                minutes = float(match.group(1) or 0)
                seconds = float(match.group(2) or 0)
                return minutes * 60.0 + seconds
        if text.endswith("ms"):
            return float(text[:-2]) / 1000.0
        if text.endswith("s"):
            return float(text[:-1])
        return float(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class RateInfo:
    limit_tokens: int | None
    remaining_tokens: int | None
    reset_tokens_s: float | None
    limit_requests: int | None
    remaining_requests: int | None
    reset_requests_s: float | None
    retry_after_s: float | None


class RateLimiter:
    def __init__(self, rpm: int, rpd: int, tpm: int, tpd: int, safety: float = 0.9):
        self.rpm = max(1, int(rpm))
        self.rpd = max(1, int(rpd))
        self.tpm = max(1, int(tpm * safety))
        self.tpd = max(1, int(tpd * safety))

        self._minute_start = time.monotonic()
        self._day_start = time.time()
        self._req_used_min = 0
        self._tok_used_min = 0
        self._req_used_day = 0
        self._tok_used_day = 0
        self._cooldown_until = 0.0

    def _refresh_minute(self) -> None:
        if (time.monotonic() - self._minute_start) >= 60.0:
            self._minute_start = time.monotonic()
            self._req_used_min = 0
            self._tok_used_min = 0

    def _refresh_day(self) -> None:
        if (time.time() - self._day_start) >= 86400.0:
            self._day_start = time.time()
            self._req_used_day = 0
            self._tok_used_day = 0

    def cooldown(self, seconds: float) -> None:
        if seconds <= 0:
            return
        self._cooldown_until = max(self._cooldown_until, time.monotonic() + float(seconds))

    def reserve(self, est_tokens_needed: int) -> None:
        est_tokens = max(1, int(est_tokens_needed))
        while True:
            now = time.monotonic()
            if now < self._cooldown_until:
                time.sleep(self._cooldown_until - now + 0.01)
                continue

            self._refresh_minute()
            self._refresh_day()

            if self._req_used_day + 1 > self.rpd or self._tok_used_day + est_tokens > self.tpd:
                raise DailyLimitReached("daily limit reached")

            if self._req_used_min + 1 <= self.rpm and self._tok_used_min + est_tokens <= self.tpm:
                self._req_used_min += 1
                self._tok_used_min += est_tokens
                self._req_used_day += 1
                self._tok_used_day += est_tokens
                return

            wait_s = max(0.05, 60.0 - (time.monotonic() - self._minute_start))
            time.sleep(wait_s)

    def adjust_actual(self, est_tokens: int, actual_tokens: int | None) -> None:
        if actual_tokens is None:
            return
        delta = int(actual_tokens) - int(est_tokens)
        self._tok_used_min += delta
        self._tok_used_day += delta


class GroqChatClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        model: str,
        rate_limiter: RateLimiter,
        timeout_seconds: int = 45,
        max_response_tokens: int | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.rate_limiter = rate_limiter
        self.timeout_seconds = timeout_seconds
        self.max_response_tokens = max_response_tokens

    def chat_json(
        self,
        *,
        con,
        system_prompt: str,
        user_prompt: str,
        est_tokens: int,
    ) -> tuple[Any, int | None, str | None, RateInfo | None, str]:
        if not self.api_key:
            raise RuntimeError("GROQ API key is not configured")

        self.rate_limiter.reserve(est_tokens)

        request_id = uuid.uuid4().hex
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "top_p": 1,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if self.max_response_tokens is not None:
            payload["max_tokens"] = int(self.max_response_tokens)

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        ai_audit_start(con=con, req_id=request_id, provider="groq", model=self.model, endpoint="/chat/completions", request_payload=payload)
        start = time.perf_counter()
        response = None
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=self.timeout_seconds)
            latency_ms = int((time.perf_counter() - start) * 1000)
            data = response.json()

            rate = _rate_info_from_headers(response.headers)
            if rate and rate.retry_after_s:
                self.rate_limiter.cooldown(rate.retry_after_s)

            if response.status_code == 429:
                ai_audit_finish(
                    con=con,
                    req_id=request_id,
                    response_payload=response.text,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                    error="rate_limit",
                )
                raise RateLimitError("rate_limit")

            response.raise_for_status()
            choice = data["choices"][0]["message"]
            content = choice.get("content") or ""
            parsed = _parse_json_content(content)

            usage = data.get("usage", {}) if isinstance(data, dict) else {}
            total_tokens = int(usage.get("total_tokens")) if usage.get("total_tokens") is not None else None
            finish_reason = data["choices"][0].get("finish_reason") if isinstance(data, dict) else None

            ai_audit_finish(
                con=con,
                req_id=request_id,
                response_payload=response.text,
                status_code=response.status_code,
                latency_ms=latency_ms,
                error=None,
            )
            self.rate_limiter.adjust_actual(est_tokens, total_tokens)
            return parsed, total_tokens, finish_reason, rate, request_id
        except requests.RequestException as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            ai_audit_finish(
                con=con,
                req_id=request_id,
                response_payload=response.text if response is not None else None,
                status_code=getattr(response, "status_code", None),
                latency_ms=latency_ms,
                error=str(exc),
            )
            raise
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            ai_audit_finish(
                con=con,
                req_id=request_id,
                response_payload=response.text if response is not None else None,
                status_code=getattr(response, "status_code", None),
                latency_ms=latency_ms,
                error=str(exc),
            )
            raise


def _rate_info_from_headers(headers: dict[str, str]) -> RateInfo | None:
    if not headers:
        return None
    return RateInfo(
        limit_tokens=_to_int(headers.get("x-ratelimit-limit-tokens")),
        remaining_tokens=_to_int(headers.get("x-ratelimit-remaining-tokens")),
        reset_tokens_s=_parse_seconds(headers.get("x-ratelimit-reset-tokens")),
        limit_requests=_to_int(headers.get("x-ratelimit-limit-requests")),
        remaining_requests=_to_int(headers.get("x-ratelimit-remaining-requests")),
        reset_requests_s=_parse_seconds(headers.get("x-ratelimit-reset-requests")),
        retry_after_s=_parse_seconds(headers.get("retry-after")),
    )


def _to_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_json_content(content: str) -> Any:
    text = (content or "").strip()
    if text.startswith("```"):
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1]
            if text.strip().startswith("json"):
                text = text.strip()[4:]
            text = text.strip()
    return json.loads(text)


def ai_audit_start(*, con, req_id: str, provider: str, model: str, endpoint: str, request_payload: dict) -> None:
    con.execute(
        """
        INSERT OR IGNORE INTO ai_audit(req_id, provider, model, endpoint, request_payload)
        VALUES (?, ?, ?, ?, ?)
        """,
        (req_id, provider, model, endpoint, to_json_text(request_payload)),
    )
    con.commit()


def ai_audit_finish(
    *,
    con,
    req_id: str,
    response_payload: str | dict | list | None,
    status_code: int | None,
    latency_ms: int,
    error: str | None,
) -> None:
    if isinstance(response_payload, (dict, list)):
        payload = to_json_text(response_payload)
    else:
        payload = response_payload
    con.execute(
        """
        UPDATE ai_audit
        SET response_payload = ?, status_code = ?, latency_ms = ?, error = ?
        WHERE req_id = ?
        """,
        (payload, status_code, latency_ms, error, req_id),
    )
    con.commit()
