import json
import requests
import time
import re
import uuid
from db import ai_audit_start, ai_audit_finish

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
API_KEY = os.getenv("GROQ_API_KEY")

_RE_WAIT = re.compile(r"try again in ([0-9.]+)s", re.I)

class RateLimitError(Exception):
    def __init__(self, message): super().__init__(message); self.message = message

def _maybe_wait_from_error_text(msg: str):
    m = _RE_WAIT.search(msg or "")
    if m: time.sleep(float(m.group(1)) + 0.05)

def _parse_seconds(v: str | None) -> float | None:
    if not v: return None
    # examples: "7.66s", "2m59.56s" in docs; handle "Xs" or just numeric
    try:
        if v.endswith("s"): return float(v[:-1])
        if v.endswith("ms"): return float(v[:-2]) / 1000.0
        # fallback: extract leading number
        m = re.search(r"([0-9.]+)", v)
        return float(m.group(1)) if m else None
    except Exception:
        return None

def chat_json(model: str, system: str, user: str, *, max_tokens: int = 256, temperature: float = 0.0, timeout=45):
    if not API_KEY:
        raise RuntimeError("GROQ_API_KEY env var is not set")
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "temperature": temperature,
        "top_p": 1,
        "response_format": {"type": "json_object"},
        #"max_tokens": int(max_tokens),
        "messages": [{"role":"system","content":system},{"role":"user","content":user}]
    }

    req_id = uuid.uuid4().hex
    provider, endpoint = "groq", "/chat/completions"
    ai_audit_start(req_id, provider, model, endpoint, payload)
    t0 = time.perf_counter()
    r = None
    try:
        r = requests.post(GROQ_URL, headers=headers, data=json.dumps(payload), timeout=timeout)
        data = r.json()

        # Build rate info from headers (present on all responses)
        h = r.headers
        rate = {
            "limit_tokens": int(h.get("x-ratelimit-limit-tokens") or 0) or None,
            "remaining_tokens": int(h.get("x-ratelimit-remaining-tokens") or 0) or None,
            "reset_tokens_s": _parse_seconds(h.get("x-ratelimit-reset-tokens")),
            "limit_requests": int(h.get("x-ratelimit-limit-requests") or 0) or None,   # RPD
            "remaining_requests": int(h.get("x-ratelimit-remaining-requests") or 0) or None,
            "reset_requests_s": _parse_seconds(h.get("x-ratelimit-reset-requests")),
            "retry_after_s": _parse_seconds(h.get("retry-after")),
        }

        if r.status_code == 429 or (isinstance(data, dict) and data.get("error",{}).get("code") == "rate_limit_exceeded"):
            _maybe_wait_from_error_text(data.get("error",{}).get("message",""))
            latency = int((time.perf_counter() - t0) * 1000)
            ai_audit_finish(req_id, r.text if r is not None else None, r.status_code if r is not None else None, latency,
            error=data.get("error",{}).get("message","429 rate_limit_exceeded"))
            raise RateLimitError(data.get("error",{}).get("message","429 rate_limit_exceeded"))

        r.raise_for_status()
        choice = data["choices"][0]["message"]
        content = choice["content"]
        usage = data.get("usage", {})
        total_tokens = int(usage.get("total_tokens") or 0)
        finish_reason = data["choices"][0].get("finish_reason") or "stop"
        latency = int((time.perf_counter() - t0) * 1000)
        ai_audit_finish(req_id, r.text, r.status_code, latency, error=None)
        return json.loads(content), total_tokens, finish_reason, rate
    except Exception as e:
        latency = int((time.perf_counter() - t0) * 1000)
        ai_audit_finish(req_id, None, getattr(r, "status_code", None), latency, error=str(e))
        raise
