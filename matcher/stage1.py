from typing import List, Dict, Tuple
from ai_client import chat_json, RateLimitError

SYSTEM = """You are a strict JSON classifier. Decide if each job title is an IT role.

Rules:
- Return true ONLY if the title clearly and unambiguously refers to a role in Information Technology.
- Information Technology includes roles related to computing, software, data, systems, DevOps, machine learning, or digital infrastructure.
- If the title is ambiguous or does not clearly indicate IT, classify as false.

Confidence:
- confidence ∈ [0.00, 1.00], two decimals.
- It measures how sure you are that your classification is correct (1.00 = absolute certainty).
- Prefer 0.99/0.01 over 1.00/0.00 unless absolutely certain.
- If uncertain but leaning toward one label, choose that label and lower confidence (typically 0.60-0.75).

Confidence scale (guideline):
| Range | Meaning |
|--------|----------|
| 1.00 | Certain |
| 0.95-0.99 | Very confident |
| 0.85-0.94 | Confident |
| 0.75-0.84 | Somewhat confident |
| 0.60-0.74 | Low confidence (ambiguous) |
| < 0.60 | Not allowed — pick likely label ≥ 0.60 |

Decision threshold:
- Classify as true only if the IT connection is clear and specific.
- If unsure or ambiguous, classify as false and reduce confidence accordingly.

Output (JSON ONLY):
{
  "results": [
    { "job_id": <id>, "is_it_role": true|false, "confidence": number ∈ [0.00, 1.00], "reason": <string> },
  ]
}

Constraints:
- Preserve input order.
- No extra keys, comments, or text.
- Deterministic output (temperature = 0).
"""

def build_user(items: List[Dict]) -> str:
    import json
    return "BATCH INPUT (JSON):\n" + json.dumps({"items": items}, ensure_ascii=False) + \
           "\n\nQUESTION:\nFor each item, should we keep it for full analysis? Return JSON object: { \"results\": [ ... ] }"

def stage1_batch(model: str, items: List[Dict], *, max_tokens: int = 256) -> Tuple[list[Dict], int]:
    data, used, _finish, _rate = chat_json(model, SYSTEM, build_user(items), max_tokens=max_tokens, temperature=0.0)
    results = data["results"]
    assert isinstance(results, list)
    for x in results:
        assert set(x.keys()) == {"job_id","is_it_role","confidence","reason"}
    assert isinstance(x["is_it_role"], bool)
    assert 0.0 <= float(x["confidence"]) <= 1.0
    return results, int(used)

from tokens import est_tokens_stage1_batch
from ratelimit import RateLimiter

def run_stage1_with_limits(model: str, items: list[dict], *, limiter: RateLimiter,
                           out_max: int, per_req_soft_cap_tokens: int):
    """
    Process Stage-1 in micro-batches with rate-limit handling:
    - Exponential backoff with jitter on 429s
    - Retry cap per micro-batch
    - After exceeding max retries, log and skip the batch (will be picked up next run)
    """
    import time
    import random

    results = []
    i = 0
    while i < len(items):
        # Build a micro-batch under the soft token cap
        j = i
        titles = []
        while j < len(items):
            titles_tmp = titles + [items[j]["title"] or ""]
            est = est_tokens_stage1_batch(titles_tmp, out_max=out_max)
            if est > per_req_soft_cap_tokens and titles:
                break
            titles = titles_tmp
            j += 1

        est_tokens = est_tokens_stage1_batch(titles, out_max=out_max)
        limiter.reserve(est_tokens)

        batch = items[i:j]

        # Retry policy
        max_retries = 8               # cap attempts per micro-batch
        base_delay_s = 1.0            # initial backoff
        factor = 2.0                  # exponential factor
        max_delay_s = 240.0           # cap backoff
        jitter_frac = 0.2             # ±20% jitter

        attempt = 0
        while True:
            try:
                res, used = stage1_batch(model, batch, max_tokens=out_max)
                limiter.adjust_actual(est_tokens, used or est_tokens)
                results.extend(res)
                i = j  # advance to next micro-batch on success
                break
            except RateLimitError as e:
                # If we hit the retry cap, log and skip this batch (it will be retried next run)
                if attempt >= max_retries:
                    job_ids = [x.get("job_id") for x in batch]
                    print(
                        "Stage1 RateLimitError: exceeded max retries (%d). Skipping batch ids=%s. Last error=%s",
                        max_retries, job_ids, str(e),
                    )
                    # Optional: inform limiter we didn't spend tokens successfully
                    try:
                        limiter.adjust_actual(est_tokens, 0)
                    except Exception:
                        pass
                    i = j  # skip this batch for now
                    break

                # Exponential backoff with jitter
                delay = min(max_delay_s, base_delay_s * (factor ** attempt))
                delay *= random.uniform(1.0 - jitter_frac, 1.0 + jitter_frac)
                attempt += 1
                print(
                    "Stage1 RateLimitError (attempt %d/%d). Sleeping %.2fs then retrying micro-batch of %d items.",
                    attempt, max_retries, delay, len(batch),
                )
                time.sleep(delay)
    return results
