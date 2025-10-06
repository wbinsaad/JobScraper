import time

class RateLimiter:
    def __init__(self, rpm: int, tpm: int, safety: float=0.9):
        self.rpm = max(1, int(rpm))
        self.tpm = max(1, int(tpm * safety))
        self.win_start = time.monotonic()
        self.req_used = 0
        self.tok_used = 0
        self.cooldown_until = 0.0

    def _refresh(self):
        if (time.monotonic() - self.win_start) >= 60.0:
            self.win_start = time.monotonic()
            self.req_used = 0
            self.tok_used = 0

    def cooldown(self, seconds: float):
        self.cooldown_until = max(self.cooldown_until, time.monotonic() + float(seconds))

    def reserve(self, est_tokens_needed: int):
        while True:
            now = time.monotonic()
            if now < self.cooldown_until:
                time.sleep(self.cooldown_until - now + 0.01); continue
            self._refresh()
            if self.req_used + 1 <= self.rpm and self.tok_used + int(est_tokens_needed) <= self.tpm:
                self.req_used += 1; self.tok_used += int(est_tokens_needed); return
            time.sleep(max(0.05, 60.0 - (time.monotonic() - self.win_start)))

    def adjust_actual(self, est_tokens: int, actual_tokens: int):
        self.tok_used += int(actual_tokens) - int(est_tokens)

def make_from_cfg(cfg):
    lim = cfg["ai"]
    return RateLimiter(rpm=int(lim["rpm"]), tpm=int(lim["tpm"]), safety=float(lim.get("safety", 0.9)))