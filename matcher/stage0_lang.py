# matcher/stage0_lang.py
import fast_langdetect as fld
from typing import Tuple, Optional

def detect_language(text: str) -> Tuple[Optional[str], float]:
    """Return detected language code (e.g., 'de', 'en') and confidence."""
    if not text or len(text) < 20:
        return None, 0.0

    try:
        result = fld.detect(text)
        # fast_langdetect returns a list of dicts, take the first item
        if isinstance(result, list) and len(result) > 0:
            top = result[0]
            lang = top.get("lang")
            conf = float(top.get("score", 0))
            return lang, conf

        # In case it's already a dict (edge case)
        if isinstance(result, dict):
            return result.get("lang"), float(result.get("score", 0))

        return None, 0.0
    except Exception as e:
        return None, 0.0


def should_exclude_by_lang(lang_code: str, confidence: float, cfg: dict) -> bool:
    """Decide if job should be excluded based on language detection."""
    if not cfg.get("language_filter", {}).get("enabled", False):
        return False
    threshold = float(cfg["language_filter"].get("german_exclude_threshold", 0.9))
    print(f'should_exclude_by_lang: {lang_code == "de" and confidence >= threshold}')
    return lang_code == "de" and confidence >= threshold
