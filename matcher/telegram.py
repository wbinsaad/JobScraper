import os, requests, time

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
PARSE_MODE = (os.getenv("TELEGRAM_PARSE_MODE") or "HTML")

def send_message(text: str) -> bool:
    if not (TOKEN and CHAT_ID): return False
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    for attempt in range(3):
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": PARSE_MODE}, timeout=10)
        if r.ok:
            return True
        time.sleep(2 * (attempt + 1))
    return False

def format_alert(row, s2: dict, score: int, label: str) -> str:
    title = row["title"] or "Working Student"
    company = row["company"] or "—"
    loc = row["location"] or "—"
    url = row["job_url"] or ""
    wm = s2.get("work_mode","unknown")
    rn = "Yes" if s2.get("requires_native_german") else "No"
    reasons = s2.get("reasons") or []
    reasons_str = "\n".join([f"• {r}" for r in reasons[:3]])
    return (
        f"<b>{title}</b>\n"
        f"{company} — {loc}\n"
        f"Mode: {wm} | Native German required: {rn}\n"
        f"Score: {score} ({label})\n"
        f"{reasons_str}\n"
        f"<a href=\"{url}\">Open</a>"
    )
