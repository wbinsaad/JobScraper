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

def _ensure_job_decision(conn, raw_job_id: int) -> int:
    """Ensure there's a job_decisions row for the raw_job_id and return its id."""
    conn.execute("INSERT OR IGNORE INTO job_decisions(raw_job_id) VALUES (?)", (raw_job_id,))
    row = conn.execute("SELECT id FROM job_decisions WHERE raw_job_id=?", (raw_job_id,)).fetchone()
    return int(row[0])

def _mark_excluded(conn, raw_job_id: int, reason_list: list[str] | None = None):
    reasons_json = json.dumps(reason_list or ["excluded"], ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO job_decisions(raw_job_id, label, score, reasons, decided_at, status)
        VALUES(?, 'exclude', 0, json(?), CURRENT_TIMESTAMP, 'excluded')
        ON CONFLICT(raw_job_id) DO UPDATE SET
          label='exclude', score=0, reasons=excluded.reasons, decided_at=excluded.decided_at, status='excluded'
        """,
        (raw_job_id, reasons_json),
    )

def _mark_approved_if_complete(conn, raw_job_id: int):
    """If all stages are good (lang not excluded, stage1 IT role, stage2 ok), set status=approved."""
    jd = conn.execute("SELECT id FROM job_decisions WHERE raw_job_id=?", (raw_job_id,)).fetchone()
    if not jd:
        return
    jd_id = int(jd[0])
    row = conn.execute(
        """
        SELECT
          COALESCE(la.excluded, 0) AS lang_excl,
          COALESCE(s1.is_it_role, 1) AS is_it_role,
          s2.status AS s2_status
        FROM job_decisions jd
        LEFT JOIN job_language_analysis la ON la.job_decision_id = jd.id
        LEFT JOIN job_stage1_results s1 ON s1.job_decision_id = jd.id
        LEFT JOIN job_stage2_results s2 ON s2.job_decision_id = jd.id
        WHERE jd.id=?
        """,
        (jd_id,),
    ).fetchone()
    if not row:
        return
    if int(row[0]) == 0 and int(row[1] or 1) == 1 and (row[2] or '') == 'ok':
        conn.execute(
            """
            UPDATE job_decisions
            SET status='approved', decided_at = COALESCE(decided_at, CURRENT_TIMESTAMP)
            WHERE raw_job_id=?
            """,
            (raw_job_id,),
        )

def _is_excluded(conn, raw_job_id: int) -> bool:
    row = conn.execute("SELECT status FROM job_decisions WHERE raw_job_id=?", (raw_job_id,)).fetchone()
    return bool(row and row[0] == 'excluded')


def run_stage0_language_filter(conn, raw_job_id: int, description: str, cfg: dict) -> bool:
    """
    Stage 0: detect job language and optionally exclude the job.
    Creates or updates the job_decisions row safely.
    Returns True if the job should be skipped from further processing.
    """
    # 1️⃣ Detect language
    lang, conf = detect_language(description)
    exclude = should_exclude_by_lang(lang, conf, cfg)
    
    # 2️⃣ Upsert language info into normalized table
    jd_id = _ensure_job_decision(conn, raw_job_id)
    conn.execute(
        """
        INSERT INTO job_language_analysis(job_decision_id, lang_code, confidence, excluded)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(job_decision_id) DO UPDATE SET
            lang_code=excluded.lang_code,
            confidence=excluded.confidence,
            excluded=excluded.excluded,
            created_at=CURRENT_TIMESTAMP
        """,
        (jd_id, lang, conf, 1 if exclude else 0),
    )
    
    # 3️⃣ If excluded, label the row immediately
    if exclude:
        _mark_excluded(conn, raw_job_id, ["Excluded due to language policy"])  # stage0 decision
        logging.info(f"[stage0] Excluded job {raw_job_id} ({lang=}, {conf=:.2f})")
        return True

    logging.debug(f"[stage0] Job {raw_job_id} language={lang} conf={conf:.2f}")
    return False

def upsert_stage1(conn, raw_job_id: int, s1: dict):
    jd_id = _ensure_job_decision(conn, raw_job_id)
    # Persist Stage1
    conn.execute(
        """
        INSERT INTO job_stage1_results(job_decision_id, is_it_role, confidence, reason)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(job_decision_id) DO UPDATE SET
            is_it_role=excluded.is_it_role,
            confidence=excluded.confidence,
            reason=excluded.reason,
            created_at=CURRENT_TIMESTAMP
        """,
        (jd_id, s1.get("is_it_role"), s1.get("confidence"), s1.get("reason")),
    )
    # Ensure Stage2 state row exists and is pending unless already ok
    conn.execute(
        """
        INSERT INTO job_stage2_results(job_decision_id, status, attempts)
        VALUES(?, 'pending', 0)
        ON CONFLICT(job_decision_id) DO UPDATE SET
            status=CASE WHEN job_stage2_results.status='ok' THEN job_stage2_results.status ELSE 'pending' END
        """,
        (jd_id,),
    )

def finalize_exclude_from_stage1(conn, raw_job_id: int, s1: dict, note: str):
    reasons = [f"stage1: {note}"]
    jd_id = _ensure_job_decision(conn, raw_job_id)
    # Update final decision
    conn.execute(
        """
        INSERT INTO job_decisions(raw_job_id, label, score, reasons, decided_at)
        VALUES(?, 'exclude', 0, json(?), CURRENT_TIMESTAMP)
        ON CONFLICT(raw_job_id) DO UPDATE SET
            label='exclude',
            score=0,
            reasons=excluded.reasons,
            decided_at=excluded.decided_at
        """,
        (raw_job_id, json.dumps(reasons, ensure_ascii=False)),
    )
    # Persist stage1 result as well (normalize)
    conn.execute(
        """
        INSERT INTO job_stage1_results(job_decision_id, is_it_role, confidence, reason)
        VALUES(?, ?, ?, ?)
        ON CONFLICT(job_decision_id) DO UPDATE SET
            is_it_role=excluded.is_it_role,
            confidence=excluded.confidence,
            reason=excluded.reason,
            created_at=CURRENT_TIMESTAMP
        """,
        (jd_id, s1.get("is_it_role"), s1.get("confidence"), s1.get("reason")),
    )
    # Mark stage2 as ok (no need to run)
    conn.execute(
        """
        INSERT INTO job_stage2_results(job_decision_id, status, attempts)
        VALUES(?, 'ok', 0)
        ON CONFLICT(job_decision_id) DO UPDATE SET status='ok'
        """,
        (jd_id,),
    )
    _mark_excluded(conn, raw_job_id, reasons)  # exclude after stage1

def complete_stage2_success(conn, raw_job_id: int, label: str, score: int, stage2: dict):
    jd_id = _ensure_job_decision(conn, raw_job_id)
    # Update stage2 table
    conn.execute(
        """
        INSERT INTO job_stage2_results(job_decision_id, status, attempts, payload_json)
        VALUES(?, 'ok', 1, json(?))
        ON CONFLICT(job_decision_id) DO UPDATE SET
            status='ok',
            attempts=job_stage2_results.attempts + 1,
            payload_json=excluded.payload_json,
            updated_at=CURRENT_TIMESTAMP
        """,
        (jd_id, json.dumps(stage2, ensure_ascii=False)),
    )
    # Update final decision
    conn.execute(
        """
        UPDATE job_decisions
        SET label = ?,
            score = ?,
            reasons = json(?),
            decided_at = COALESCE(decided_at, CURRENT_TIMESTAMP)
        WHERE raw_job_id = ?
        """,
        (label, score, json.dumps(stage2.get("reasons") or [], ensure_ascii=False), raw_job_id),
    )
    _mark_approved_if_complete(conn, raw_job_id)

def complete_stage2_error(conn, raw_job_id: int, err: str):
    jd_id = _ensure_job_decision(conn, raw_job_id)
    conn.execute(
        """
        INSERT INTO job_stage2_results(job_decision_id, status, attempts, last_error)
        VALUES(?, 'error', 1, substr(?,1,500))
        ON CONFLICT(job_decision_id) DO UPDATE SET
            status='error',
            attempts=job_stage2_results.attempts + 1,
            last_error=substr(?,1,500),
            updated_at=CURRENT_TIMESTAMP
        """,
        (jd_id, err, err),
    )
    # Optional policy: if attempts exceed threshold or hard error, mark excluded
    too_many = conn.execute("SELECT attempts FROM job_stage2_results WHERE job_decision_id=?", (jd_id,)).fetchone()
    if too_many and int(too_many[0]) >= 5:
        _mark_excluded(conn, raw_job_id, ["Stage2 failed too many times"])  # stage2 policy

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

def fetch_for_stage0(conn, limit=500):
    # Jobs not language-triaged yet (no job_language_analysis row), and not excluded
    return conn.execute("""
        SELECT r.id, r.title, r.company, r.location, r.description, r.job_url
        FROM raw_jobs r
        LEFT JOIN job_decisions d ON d.raw_job_id = r.id
        LEFT JOIN job_language_analysis la ON la.job_decision_id = d.id
        WHERE COALESCE(d.status,'')!='excluded'
          AND la.job_decision_id IS NULL
        ORDER BY r.id ASC
        LIMIT ?
    """, (limit,)).fetchall()

def fetch_for_stage1(conn, limit=500):
    # Jobs that passed Stage-0 (language analyzed and not excluded), but have no Stage-1 result yet
    return conn.execute("""
        SELECT r.id, r.title, r.company, r.location, r.description, r.job_url
        FROM raw_jobs r
        JOIN job_decisions d ON d.raw_job_id = r.id
        JOIN job_language_analysis la ON la.job_decision_id = d.id
        LEFT JOIN job_stage1_results s1 ON s1.job_decision_id = d.id
        WHERE COALESCE(d.status,'')!='excluded'
          AND COALESCE(la.excluded,0)=0
          AND s1.job_decision_id IS NULL
        ORDER BY r.id ASC
        LIMIT ?
    """, (limit,)).fetchall()

def claim_stage2_batch(conn, limit=50):
    # Claim rows needing Stage-2 (pending/error) safely using normalized table
    with tx(conn):
        ids = [row["raw_job_id"] for row in conn.execute(
            """
            SELECT jd.raw_job_id
            FROM job_stage2_results s2
            JOIN job_decisions jd ON jd.id = s2.job_decision_id
            WHERE s2.status IN ('pending','error') AND s2.attempts < 5 AND COALESCE(jd.status,'pending')!='excluded'
            ORDER BY jd.raw_job_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()]
        if not ids:
            return []
        # mark as processing
        conn.executemany(
            """
            UPDATE job_stage2_results
            SET status='processing', updated_at=CURRENT_TIMESTAMP
            WHERE job_decision_id=(SELECT id FROM job_decisions WHERE raw_job_id=?)
            """,
            [(i,) for i in ids],
        )
    # Return full rows for processing
    q = ",".join("?" * len(ids))
    return conn.execute(
        f"""
        SELECT r.id, r.title, r.company, r.location, r.description, r.job_url
        FROM raw_jobs r
        WHERE r.id IN ({q})
        ORDER BY r.id
        """,
        ids,
    ).fetchall()

def write_exclude(conn, raw_job_id: int, stage1_json: dict, reason_note: str):
        with tx(conn):
                jd_id = _ensure_job_decision(conn, raw_job_id)
                # Final decision
                conn.execute(
                        """
                        INSERT INTO job_decisions(raw_job_id, label, score, reasons, decided_at)
                        VALUES(?, 'exclude', 0, json(?), CURRENT_TIMESTAMP)
                        ON CONFLICT(raw_job_id) DO UPDATE SET
                            label='exclude', score=0, reasons=excluded.reasons, decided_at=excluded.decided_at
                        """,
                        (raw_job_id, json.dumps([reason_note], ensure_ascii=False)),
                )
                # Persist stage1 snapshot if provided
                conn.execute(
                        """
                        INSERT INTO job_stage1_results(job_decision_id, is_it_role, confidence, reason)
                        VALUES(?, ?, ?, ?)
                        ON CONFLICT(job_decision_id) DO UPDATE SET
                            is_it_role=COALESCE(excluded.is_it_role, job_stage1_results.is_it_role),
                            confidence=COALESCE(excluded.confidence, job_stage1_results.confidence),
                            reason=COALESCE(excluded.reason, job_stage1_results.reason),
                            created_at=CURRENT_TIMESTAMP
                        """,
                        (jd_id, stage1_json.get("is_it_role"), stage1_json.get("confidence"), stage1_json.get("reason")),
                )
                # Mark stage2 as ok/no-op
                conn.execute(
                        """
                        INSERT INTO job_stage2_results(job_decision_id, status, attempts, payload_json)
                        VALUES(?, 'ok', 0, NULL)
                        ON CONFLICT(job_decision_id) DO UPDATE SET status='ok'
                        """,
                        (jd_id,),
                )

def write_final(conn, raw_job_id: int, label: str, score: int, stage1: dict, stage2: dict):
        with tx(conn):
                jd_id = _ensure_job_decision(conn, raw_job_id)
                # Update final decision
                conn.execute(
                        """
                        INSERT INTO job_decisions(raw_job_id, label, score, reasons, decided_at)
                        VALUES(?, ?, ?, json(?), CURRENT_TIMESTAMP)
                        ON CONFLICT(raw_job_id) DO UPDATE SET
                            label=excluded.label,
                            score=excluded.score,
                            reasons=excluded.reasons,
                            decided_at=excluded.decided_at
                        """,
                        (raw_job_id, label, score, json.dumps(stage2.get("reasons") or [], ensure_ascii=False)),
                )
                # Persist stage1
                conn.execute(
                        """
                        INSERT INTO job_stage1_results(job_decision_id, is_it_role, confidence, reason)
                        VALUES(?, ?, ?, ?)
                        ON CONFLICT(job_decision_id) DO UPDATE SET
                            is_it_role=excluded.is_it_role,
                            confidence=excluded.confidence,
                            reason=excluded.reason,
                            created_at=CURRENT_TIMESTAMP
                        """,
                        (jd_id, stage1.get("is_it_role"), stage1.get("confidence"), stage1.get("reason")),
                )
                # Persist stage2 payload/status
                conn.execute(
                        """
                        INSERT INTO job_stage2_results(job_decision_id, status, attempts, payload_json)
                        VALUES(?, 'ok', 1, json(?))
                        ON CONFLICT(job_decision_id) DO UPDATE SET
                            status='ok',
                            attempts=job_stage2_results.attempts + 1,
                            payload_json=excluded.payload_json,
                            updated_at=CURRENT_TIMESTAMP
                        """,
                        (jd_id, json.dumps(stage2, ensure_ascii=False)),
                )

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

    print("Stage 0: triage new jobs")
    s0_limit = max(cfg["batch"].get("stage0_size", cfg["batch"]["stage1_size"]), 1)
    s0_rows = fetch_for_stage0(conn, limit=s0_limit)
    print(f"  Found {len(s0_rows)} new jobs for stage 0")
    if s0_rows:
        for r in s0_rows:
            desc = r["description"] or ""
            with tx(conn):  # ensure commit
                run_stage0_language_filter(conn, r["id"], desc, cfg)
        progressed = True

    print("Stage 1: triage new jobs")
    s1_rows = fetch_for_stage1(conn, limit=max(cfg["batch"]["stage1_size"], 1))
    print(f"  Found {len(s1_rows)} new jobs for stage 1")
    if s1_rows:
        items = [{"job_id": r["id"], "title": (r["title"] or "")} for r in s1_rows]
        s1_results = run_stage1_with_limits(stage1_model, items, limiter=limiter, out_max=out1, per_req_soft_cap_tokens=soft_cap)
        by_id = {x["job_id"]: x for x in s1_results}
        for r in s1_rows:
            s1 = by_id.get(r["id"], {"is_it_role":None,"confidence":0.0,"reason":"missing"})
            is_it_role = s1.get("is_it_role")
            conf = float(s1.get("confidence") or 0.0)
            upsert_stage1(conn, r["id"], s1)
            # Exclude if not IT role and confidence is high
            if is_it_role is False and conf >= promote_below:
                finalize_exclude_from_stage1(conn, r["id"], s1, s1.get("reason") or "confident out")
            else:
                # ensure stage2 is pending (if not ok)
                jd_id = _ensure_job_decision(conn, r["id"])
                conn.execute(
                    """
                    INSERT INTO job_stage2_results(job_decision_id, status, attempts)
                    VALUES(?, 'pending', 0)
                    ON CONFLICT(job_decision_id) DO UPDATE SET
                        status=CASE WHEN job_stage2_results.status='ok' THEN job_stage2_results.status ELSE 'pending' END
                    """,
                    (jd_id,),
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
