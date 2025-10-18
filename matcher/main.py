import os, time, json, logging
from db import connect, tx
from stage1 import stage1_batch
from stage2 import stage2_single
from decisions import decide_label_min, should_notify
from telegram import send_message, format_alert

from ratelimit import make_from_cfg
from tokens import est_tokens_stage1_batch, est_tokens_stage2_single
from stage1 import run_stage1_with_limits
from stage0_lang import detect_language, should_exclude_by_lang

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

import json, time
LIMITER = None

def run_stage0_language_filter(conn, raw_job_id: int, description: str, cfg: dict) -> bool:
    """
    Stage 0: detect job language and optionally exclude the job.
    Creates or updates the job_decisions row safely.
    Returns True if the job should be skipped from further processing.
    """
    # 1️⃣ Detect language
    lang, conf = detect_language(description)
    exclude = should_exclude_by_lang(lang, conf, cfg)
    
    # 2️⃣ Upsert language info — create row if missing
    cursor = conn.execute("""
        INSERT INTO job_decisions(raw_job_id, lang_code, lang_confidence, lang_excluded)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(raw_job_id) DO UPDATE SET
            lang_code = excluded.lang_code,
            lang_confidence = excluded.lang_confidence,
            lang_excluded = excluded.lang_excluded;
    """, (raw_job_id, lang, conf, 1 if exclude else 0))
    
    # 3️⃣ If excluded, label the row immediately
    if exclude:
        conn.execute("""
            UPDATE job_decisions
            SET label = 'exclude',
                score = 0,
                reasons = json('["Excluded due to German language detection"]'),
                decided_at = CURRENT_TIMESTAMP
            WHERE raw_job_id = ?;
        """, (raw_job_id,))
        logging.info(f"[stage0] Excluded job {raw_job_id} ({lang=}, {conf=:.2f})")
        return True

    logging.debug(f"[stage0] Job {raw_job_id} language={lang} conf={conf:.2f}")
    return False

def upsert_stage1(conn, raw_job_id: int, s1: dict):
        conn.execute("""
                    INSERT INTO job_decisions(
                        raw_job_id, stage1_json, stage1_is_it_role, stage1_confidence, stage1_reason, stage1_at, stage2_status, stage2_attempts)
                    VALUES(?, json(?), ?, ?, ?, CURRENT_TIMESTAMP, 'pending', 0)
                    ON CONFLICT(raw_job_id) DO UPDATE SET
                        stage1_json=excluded.stage1_json,
                        stage1_is_it_role=excluded.stage1_is_it_role,
                        stage1_confidence=excluded.stage1_confidence,
                        stage1_reason=excluded.stage1_reason,
                        stage1_at=CURRENT_TIMESTAMP
                """, (
                        raw_job_id,
                        json.dumps(s1, ensure_ascii=False),
                        s1.get("is_it_role"),
                        s1.get("confidence"),
                        s1.get("reason")
                ))

def finalize_exclude_from_stage1(conn, raw_job_id: int, s1: dict, note: str):
        reasons = [f"stage1: {note}"]
        conn.execute("""
                    INSERT INTO job_decisions(
                        raw_job_id, label, score, reasons, stage1_json, stage1_is_it_role, stage1_confidence, stage1_reason, stage1_at, stage2_status, decided_at)
                    VALUES(?, 'exclude', 0, json(?), json(?), ?, ?, ?, CURRENT_TIMESTAMP, 'ok', CURRENT_TIMESTAMP)
                    ON CONFLICT(raw_job_id) DO UPDATE SET
                        label='exclude', score=0, reasons=excluded.reasons, stage1_json=excluded.stage1_json,
                        stage1_is_it_role=excluded.stage1_is_it_role,
                        stage1_confidence=excluded.stage1_confidence,
                        stage1_reason=excluded.stage1_reason,
                        stage1_at=excluded.stage1_at, stage2_status='ok', decided_at=excluded.decided_at
                """, (
                        raw_job_id,
                        json.dumps(reasons, ensure_ascii=False),
                        json.dumps(s1, ensure_ascii=False),
                        s1.get("is_it_role"),
                        s1.get("confidence"),
                        s1.get("reason")
                ))

def complete_stage2_success(conn, raw_job_id: int, label: str, score: int, stage2: dict):
    conn.execute("""
      UPDATE job_decisions
      SET stage2_json = json(?),
          stage2_status = 'ok',
          stage2_attempts = stage2_attempts + 1,
          label = ?,
          score = ?,
          reasons = json(?),
          decided_at = COALESCE(decided_at, CURRENT_TIMESTAMP)
      WHERE raw_job_id = ?
    """, (json.dumps(stage2, ensure_ascii=False),
          label, score, json.dumps(stage2.get("reasons") or [], ensure_ascii=False), raw_job_id))

def complete_stage2_error(conn, raw_job_id: int, err: str):
    conn.execute("""
      UPDATE job_decisions
      SET stage2_status='error',
          stage2_attempts=stage2_attempts + 1,
          stage2_last_error=substr(?,1,500)
      WHERE raw_job_id=?
    """, (err, raw_job_id))

def load_cfg():
    import yaml
    cfg_path = os.getenv("CONFIG_PATH", "/app/config.yaml")

    if not os.path.isfile(cfg_path):
        # fallback to local path if someone runs it outside docker
        local = "./config.yaml"
        if os.path.isfile(local):
            cfg_path = local
        else:
            raise FileNotFoundError(f"Config not found. Tried {cfg_path} and {local}")
        
    with open(cfg_path,"r",encoding="utf-8") as f:
        return yaml.safe_load(f)

def fetch_for_stage1(conn, limit=500):
    # Jobs with no job_decisions row yet
    return conn.execute("""
        SELECT r.id, r.title, r.company, r.location, r.description, r.job_url
        FROM raw_jobs r
        LEFT JOIN job_decisions d ON d.raw_job_id = r.id
        WHERE d.raw_job_id IS NULL
        ORDER BY r.id ASC
        LIMIT ?""", (limit,)).fetchall()

def claim_stage2_batch(conn, limit=50):
    # Claim rows needing Stage-2 (pending/error) safely
    with tx(conn):
        ids = [row["raw_job_id"] for row in conn.execute("""
            SELECT raw_job_id
            FROM job_decisions
            WHERE stage2_status IN ('pending','error') AND stage2_attempts < 5
            ORDER BY raw_job_id
            LIMIT ?""", (limit,)).fetchall()]
        if not ids: return []
        conn.executemany("UPDATE job_decisions SET stage2_status='processing' WHERE raw_job_id=?", [(i,) for i in ids])
    # Return full rows for processing
    q = ",".join("?"*len(ids))
    return conn.execute(f"""
        SELECT r.id, r.title, r.company, r.location, r.description, r.job_url,
               jd.stage1_json
        FROM raw_jobs r
        JOIN job_decisions jd ON jd.raw_job_id = r.id
        WHERE r.id IN ({q})
        ORDER BY r.id
    """, ids).fetchall()

def write_exclude(conn, raw_job_id: int, stage1_json: dict, reason_note: str):
    with tx(conn):
        conn.execute("""
          INSERT OR IGNORE INTO job_decisions(raw_job_id, label, score, reasons, stage1_json, stage2_json)
          VALUES(?,?,?,?,?,?)
        """, (raw_job_id, "exclude", 0, json.dumps([reason_note], ensure_ascii=False), json.dumps(stage1_json, ensure_ascii=False), None))

def write_final(conn, raw_job_id: int, label: str, score: int, stage1: dict, stage2: dict):
    with tx(conn):
        conn.execute("""
          INSERT OR REPLACE INTO job_decisions(raw_job_id, label, score, reasons, stage1_json, stage2_json)
          VALUES(?,?,?,?,?,?)
        """, (raw_job_id, label, score, json.dumps(stage2.get("reasons") or [], ensure_ascii=False),
              json.dumps(stage1, ensure_ascii=False), json.dumps(stage2, ensure_ascii=False)))

def maybe_notify(conn, row, label, score, s2, notify_threshold):
    if not should_notify(label, score, notify_threshold): return
    # check idempotency
    dec = conn.execute("SELECT id, notified_at FROM job_decisions WHERE raw_job_id=?", (row["id"],)).fetchone()
    if not dec or dec["notified_at"]: return
    if send_message(format_alert(row, s2, score, label)):
        with tx(conn):
            conn.execute("UPDATE job_decisions SET notified_at=datetime('now') WHERE id=?", (dec["id"],))

def run_once(conn, cfg, limiter):
    stage1_model = cfg["ai"]["stage1_model"]
    stage2_model = cfg["ai"]["stage2_model"]
    promote_below = float(cfg["ai"].get("stage1_promote_if_confidence_below", 0.85))
    include_th = int(cfg["thresholds"]["include"])
    maybe_th = int(cfg["thresholds"]["maybe"])
    notify_th = int(os.getenv("NOTIFY_THRESHOLD", cfg["thresholds"]["min_score_to_alert"]))

    out1 = int(cfg["ai"]["max_output_tokens_stage1"])
    out2 = int(cfg["ai"]["max_output_tokens_stage2"])
    soft_cap = int(cfg["ai"]["per_request_soft_cap_tokens"])

    progressed = False

    print("Stage 1: triage new jobs")

    s1_rows = fetch_for_stage1(conn, limit=max(cfg["batch"]["stage1_size"], 1))

    # --- Stage 0: Language Filter ---
    filtered_rows = []
    if s1_rows:
        for r in s1_rows:
            desc = r["description"] or ""
            with tx(conn):  # ensure commit
                if run_stage0_language_filter(conn, r["id"], desc, cfg):
                    continue
            filtered_rows.append(r)
    # --- End Stage 0 ---

    # --- Stage 1: triage new jobs (persist results) ---
    if filtered_rows:
        items = [{"job_id": r["id"], "title": (r["title"] or "")} for r in filtered_rows]
        s1_results = run_stage1_with_limits(stage1_model, items, limiter=limiter, out_max=out1, per_req_soft_cap_tokens=soft_cap)
        by_id = {x["job_id"]: x for x in s1_results}
        for r in filtered_rows:
            s1 = by_id.get(r["id"], {"is_it_role":None,"confidence":0.0,"reason":"missing"})
            is_it_role = s1.get("is_it_role")
            conf = float(s1.get("confidence") or 0.0)
            upsert_stage1(conn, r["id"], s1)
            # Exclude if not IT role and confidence is high
            if is_it_role is False and conf >= promote_below:
                finalize_exclude_from_stage1(conn, r["id"], s1, s1.get("reason") or "confident out")
            else:
                conn.execute(
                    "UPDATE job_decisions SET stage2_status='pending' WHERE raw_job_id=? AND stage2_status!='ok'",
                    (r["id"],)
                )
        progressed = True

    print("Stage 2: triage new jobs")

    # --- Stage 2: claim + process pending/error items ---
    to_process = [] #claim_stage2_batch(conn, limit=max(cfg["batch"]["stage2_size"], 20))
    for r in to_process:
        try:
            # estimate tokens and reserve
            desc_excerpt = (r["description"] or "")[:500]
            est = est_tokens_stage2_single(r["title"] or "", r["company"] or "", r["location"] or "", desc_excerpt, out_max=out2)
            limiter.reserve(est)
            profile = (
                cfg.matcher.profile.summary
                if getattr(cfg, "matcher", None) and getattr(cfg.matcher, "profile", None)
                else "Backend/automation engineer (ASP.NET, REST APIs, SQL, CI/CD). UX Design MSc. Avoid SAP/native-German-only. Prefer English, remote/hybrid."
            )
            s2_obj, used, finish, rate  = stage2_single(stage2_model, r["title"], r["company"], r["description"], profile, max_tokens=out2)
            
            # If not enough tokens remain for the next call, wait until TPM reset
            rem = rate.get("remaining_tokens")
            reset_s = rate.get("reset_tokens_s")
            if rem is not None and reset_s is not None and rem < max(256, est):
                time.sleep(reset_s + 0.05)


            # If not enough tokens remain for the next call, wait until TPM reset
            rem = rate.get("remaining_tokens")
            reset_s = rate.get("reset_tokens_s")
            if rem is not None and reset_s is not None and rem < max(256, est):
                time.sleep(reset_s + 0.05)

            limiter.adjust_actual(est, used or est)

            score = int(s2_obj.get("score_model") or 0)
            label = decide_label_min(s2_obj, include_threshold=include_th, maybe_threshold=maybe_th)
            complete_stage2_success(conn, r["id"], label, score, s2_obj)
            if should_notify(label, score, notify_th):
                send_message(format_alert(r, s2_obj, score, label))

            progressed = True
        except Exception as e:
            complete_stage2_error(conn, r["id"], str(e))

    return progressed

def main():
    global LIMITER
    root = load_cfg()
    cfg = root.get("matcher", {})
    if LIMITER is None:
        LIMITER = make_from_cfg(cfg)  # create once

    conn = connect(cfg["sqlite_path"])
    idle_sleep = int(cfg["batch"]["sleep_seconds_when_idle"])
    logging.info("Matcher started.")
    while True:
        try:
            progressed = run_once(conn, cfg, limiter=LIMITER)
        except Exception as e:
            logging.exception("Matcher error")
            progressed = False
        if not progressed:
            time.sleep(idle_sleep)

if __name__ == "__main__":
    main()
