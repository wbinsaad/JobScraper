import hashlib
import json
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
}


def normalize_job_url(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    parts = urlsplit(raw)
    query_pairs = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_QUERY_KEYS]
    clean_query = urlencode(query_pairs)
    normalized = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), clean_query, ""))
    return normalized


def parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def to_json_text(value: Any) -> str:
    def _default(obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    return json.dumps(value, ensure_ascii=True, default=_default)


def to_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def masked_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    out: dict[str, str] = {}
    for key, value in headers.items():
        low = key.lower()
        if "authorization" in low or "token" in low or "api-key" in low or "apikey" in low:
            out[key] = "***"
        else:
            out[key] = value
    return out
