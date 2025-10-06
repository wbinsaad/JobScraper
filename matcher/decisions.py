def decide_label_min(stage2: dict, include_threshold: int, maybe_threshold: int) -> str:
    score = int(stage2.get("score_model") or 0)
    if score >= include_threshold: return "include"
    if score >= maybe_threshold:   return "maybe"
    return "exclude"

def should_notify(label: str, score: int, min_score_to_alert: int) -> bool:
    return label == "include" and score >= int(min_score_to_alert)
