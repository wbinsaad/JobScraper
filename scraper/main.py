import argparse
import json
import logging
import os
from apscheduler.schedulers.blocking import BlockingScheduler

from .config import load_config
from .db import connect, ensure_schema, start_run, finish_run
from .ingest import run_scrape

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

def _run_once(cfg_path: str | None):
    cfg = load_config(cfg_path)
    con = connect(cfg.sqlite_path)
    ensure_schema(con)

    params = {
        "search_terms": cfg.search_terms,
        "locations": cfg.locations,
        "hours_old": cfg.hours_old,
        "results_wanted": cfg.results_wanted,
        "fetch_description": cfg.fetch_description,
    }
    run_id = start_run(con, params)
    logging.info("Scrape run started id=%s params=%s", run_id, json.dumps(params, ensure_ascii=False))

    stats = run_scrape(
        con, run_id,
        terms=cfg.search_terms,
        locations=cfg.locations,
        hours_old=cfg.hours_old,
        results_wanted=cfg.results_wanted,
        fetch_description=cfg.fetch_description,
        delay_min_ms=cfg.delay_min_ms,
        delay_max_ms=cfg.delay_max_ms,
    )

    # Determine status
    status = "success"
    if stats["error_count"] > 0 and stats["new_rows"] == 0 and stats["total_rows"] == 0:
        status = "failed"
    elif stats["error_count"] > 0:
        status = "partial"

    finish_run(
        con, run_id,
        status=status,
        total_requests=stats["total_requests"],
        total_rows=stats["total_rows"],
        new_rows=stats["new_rows"],
        error_count=stats["error_count"],
    )
    logging.info("Scrape run finished id=%s status=%s stats=%s", run_id, status, stats)
    con.close()

def serve(cfg_path: str | None):
    # run immediately, then hourly at :00
    _run_once(cfg_path)
    sched = BlockingScheduler(timezone=os.getenv("TZ", "Europe/Berlin"))
    sched.add_job(lambda: _run_once(cfg_path), trigger="cron", minute=0)
    logging.info("Scheduler started (hourly at :00)")
    sched.start()

def main():
    parser = argparse.ArgumentParser(description="Werkstudent Scraper")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="Run one scrape pass now")
    p_run.add_argument("--config", help="Path to YAML config", default=None)
    p_srv = sub.add_parser("serve", help="Run scheduler (hourly) and an immediate pass")
    p_srv.add_argument("--config", help="Path to YAML config", default=None)
    args = parser.parse_args()
    if args.cmd == "run":
        _run_once(args.config)
    elif args.cmd == "serve":
        serve(args.config)

if __name__ == "__main__":
    main()
