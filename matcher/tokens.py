# matcher/tokens.py
import math
import re
_WORD_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)

def est_tokens_text(s: str) -> int:
    if not s: return 0
    # conservative: ~1 token / 4 chars; floor by "dense" word count
    chars = len(s)
    words = len(_WORD_RE.findall(s))
    return max(math.ceil(chars/4), math.ceil(words*0.8))

def est_tokens_stage1_batch(titles: list[str], sys_overhead=140, out_max=256) -> int:
    return sys_overhead + sum(est_tokens_text(t) for t in titles) + out_max

def est_tokens_stage2_single(title: str, company: str, location: str, desc_excerpt: str,
                             sys_overhead=220, out_max=512) -> int:
    body = " ".join(x for x in [title, company, location, desc_excerpt] if x)
    return sys_overhead + est_tokens_text(body) + out_max
