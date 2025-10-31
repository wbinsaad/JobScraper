from ai_client import chat_json

SYSTEM = "You analyze a job and output STRICT JSON only."

def build_text(title, company, description, profile_summary) -> str:
    return f"""
    You are evaluating jobs for ME based on my profile.

    PROFILE:
    - {profile_summary}

    TASK:
    Given a job posting, output STRICT JSON:
    {{
    "is_it_job": true/false,
    "score_model": int 0-100,
    "confidence": float 0-1,
    "reasons": ["2-4 short bullets"],
    "best_fit_factors": ["why this matches me"],
    "bad_fit_factors": ["why this is a poor fit"]
    }}

    Rules:
    - If not IT/software, set is_it_job=false.
    - Only output valid JSON, nothing else.

    POSTING:
    Title: {title}
    Company: {company}
    Description: {description}
    """.strip()

def stage2_single(model: str, title: str, company: str, description: str, profile_summary, max_tokens: int = 512):
    # hard cap description to 500 chars to save tokens
    user = build_text(title, company, description, profile_summary)
    obj, used, finish, rate = chat_json(
        model=model,
        system=SYSTEM,
        user=user,
        max_tokens=max_tokens,
    )
    obj = _postprocess(obj)
    return obj, used, finish, rate

def _postprocess(obj: dict) -> dict:
    out = {}
    out["is_it_job"] = bool(obj.get("is_it_job"))
    out["score_model"] = int(obj.get("score_model", 0))
    out["confidence"] = float(obj.get("confidence", 0))
    out["reasons"] = [str(x) for x in (obj.get("reasons") or [])][:5]
    out["best_fit_factors"] = [str(x) for x in (obj.get("best_fit_factors") or [])][:5]
    out["bad_fit_factors"] = [str(x) for x in (obj.get("bad_fit_factors") or [])][:5]
    return out