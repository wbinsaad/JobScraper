from typing import List, Dict, Tuple
from ai_client import chat_json, RateLimitError

SYSTEM = """You are a strict JSON classifier. Decide if each job title is an IT role.

Normalize before deciding:
- Lowercase; strip bracketed gender tags (e.g., "(f/m/d)"), seniority (intern/working student/trainee), and hiring suffixes.
- Ignore company names, locations, team names, and emojis.
- Expand synonyms: "ux"="user experience", "ui"="user interface", "sre"="site reliability", "it"="information technology".

Definitions:
- IT roles include: software engineering/dev, data/analytics/ML/AI, cloud/devops/sre, security/infosec, IT support/systems/admin, QA/testing (software), databases/platform/infrastructure, and *digital product design for software (ux/ui/user research)* [INCLUSIVE_POLICY=on].
- If you prefer to exclude UX/UI from IT, set [INCLUSIVE_POLICY=off] and only treat "ux engineer" or "ui developer" as IT.

Non-IT (unless title explicitly ties to software/tech build): marketing, sales, HR, finance, operations, general "support" or "customer support", office admin, non-technical design (graphic/visual/brand), industrial design, content/copywriting.

Ambiguity rule:
- If the IT connection is **clear and specific**, classify `true`.
- If ambiguous/unclear, classify `false`.

Confidence:
- `confidence` ∈ [0.60, 1.00], two decimals. Never output < 0.60.
- 0.95–0.99 = very confident; 0.85–0.94 = confident; 0.75–0.84 = somewhat; 0.60–0.74 = low (ambiguous).
- Prefer 0.99/0.61 over 1.00/0.60 unless absolutely certain.

Output (JSON ONLY):
{
  "results": [
    { "job_id": <id>, "is_it_role": true|false, "confidence": number, "reason": <short phrase> }
  ]
}
Constraints:
- Preserve input order.
- Deterministic output (temperature = 0).
- `reason` must mention the deciding keyword(s).

Examples (INCLUSIVE_POLICY=on):
- "UX Designer" → true, "digital product design"
- "User Experience Researcher" → true, "ux research for software"
- "Customer Support Specialist" → false, "non-technical support"
- "QA Engineer" → true, "software testing"
- "IT Support Technician" → true, "it support"
- "Graphic Designer" → false, "non-technical design"

Examples (INCLUSIVE_POLICY=off):
- "UX Designer" → false, "design, not engineering"
- "UX Engineer" → true, "engineering"
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
