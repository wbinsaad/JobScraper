from __future__ import annotations

import logging
import os
import shlex
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger


LOGGER = logging.getLogger("seek-scheduler")
RUN_LOCK = threading.Lock()
BACKFILL_LOCK = threading.Lock()


@dataclass(frozen=True)
class SchedulerConfig:
    timezone: str
    weekday_schedule_times: Tuple[Tuple[int, int], ...]
    weekend_schedule_times: Tuple[Tuple[int, int], ...]
    scrapy_bin: str
    scrapy_project_dir: str
    spider_name: str
    spider_args: Tuple[str, ...]
    run_on_start: bool
    backfill_after_scrape: bool
    backfill_python_bin: str
    backfill_project_dir: str
    backfill_args: Tuple[str, ...]


def configure_logging() -> None:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def parse_schedule_times(value: str) -> Tuple[Tuple[int, int], ...]:
    raw_times = [item.strip() for item in value.split(",") if item.strip()]
    if not raw_times:
        raise ValueError("SCHEDULE_TIMES cannot be empty")

    parsed: List[Tuple[int, int]] = []
    for item in raw_times:
        parts = item.split(":")
        if len(parts) != 2:
            raise ValueError(f"Invalid time '{item}'. Expected HH:MM")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"Invalid time '{item}'. Hour 0-23, minute 0-59")
        parsed.append((hour, minute))

    # de-duplicate and sort
    return tuple(sorted(set(parsed)))


def parse_spider_args(value: str) -> Tuple[str, ...]:
    value = value.strip()
    if not value:
        return tuple()

    # Expected format: "region=Melbourne,classification=6281"
    args = [item.strip() for item in value.split(",") if item.strip()]
    for arg in args:
        if "=" not in arg:
            raise ValueError(
                f"Invalid spider arg '{arg}'. Expected key=value format in SPIDER_ARGS"
            )
    return tuple(args)


def parse_backfill_args(value: str) -> Tuple[str, ...]:
    value = value.strip()
    if not value:
        return tuple()
    try:
        return tuple(shlex.split(value, posix=os.name != "nt"))
    except ValueError as exc:
        raise ValueError(f"Invalid BACKFILL_ARGS: {exc}") from exc


def build_config() -> SchedulerConfig:
    timezone = os.getenv("SCHEDULER_TIMEZONE", "Australia/Melbourne")
    legacy_schedule = os.getenv("SCHEDULE_TIMES")
    if legacy_schedule:
        weekday_schedule_times = parse_schedule_times(legacy_schedule)
        weekend_schedule_times = parse_schedule_times(legacy_schedule)
    else:
        weekday_schedule_times = parse_schedule_times(
            os.getenv("WEEKDAY_SCHEDULE_TIMES", "08:00,10:00,12:00,14:00,16:00,18:00,22:00,22:40,01:40")
        )
        weekend_schedule_times = parse_schedule_times(
            os.getenv("WEEKEND_SCHEDULE_TIMES", "10:00,14:00,18:00,22:00")
        )
    scrapy_bin = os.getenv("SCRAPY_BIN", "scrapy")
    scrapy_project_dir = os.getenv("SCRAPY_PROJECT_DIR", "/app")
    spider_name = os.getenv("SPIDER_NAME", "seek")
    spider_args = parse_spider_args(os.getenv("SPIDER_ARGS", "region=Melbourne"))
    run_on_start = os.getenv("RUN_ON_START", "true").lower() == "true"
    backfill_after_scrape = os.getenv("BACKFILL_AFTER_SCRAPE", "false").lower() == "true"
    backfill_python_bin = os.getenv("BACKFILL_PYTHON_BIN", "python")
    backfill_project_dir = os.getenv("BACKFILL_PROJECT_DIR", "/app")
    backfill_args = parse_backfill_args(os.getenv("BACKFILL_ARGS", ""))

    # Validate timezone early
    ZoneInfo(timezone)

    return SchedulerConfig(
        timezone=timezone,
        weekday_schedule_times=weekday_schedule_times,
        weekend_schedule_times=weekend_schedule_times,
        scrapy_bin=scrapy_bin,
        scrapy_project_dir=scrapy_project_dir,
        spider_name=spider_name,
        spider_args=spider_args,
        run_on_start=run_on_start,
        backfill_after_scrape=backfill_after_scrape,
        backfill_python_bin=backfill_python_bin,
        backfill_project_dir=backfill_project_dir,
        backfill_args=backfill_args,
    )


def stream_pipe(pipe, log_fn) -> None:
    try:
        for line in iter(pipe.readline, ""):
            log_fn(line.rstrip())
    finally:
        pipe.close()


def build_scrapy_command(config: SchedulerConfig) -> List[str]:
    cmd = [config.scrapy_bin, "crawl", config.spider_name]
    for arg in config.spider_args:
        cmd.extend(["-a", arg])
    return cmd


def build_backfill_command(config: SchedulerConfig) -> List[str]:
    cmd = [config.backfill_python_bin, "-m", "SeekSpider.backfill"]
    cmd.extend(config.backfill_args)
    return cmd


def run_spider_job(config: SchedulerConfig) -> None:
    if not RUN_LOCK.acquire(blocking=False):
        LOGGER.warning("Previous run still active. Skipping this trigger.")
        return

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    cmd = build_scrapy_command(config)
    exit_code = None

    LOGGER.info("Job started | run_id=%s", run_id)
    LOGGER.info("Executing command: %s", " ".join(shlex.quote(part) for part in cmd))
    LOGGER.info("Working directory: %s", config.scrapy_project_dir)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=config.scrapy_project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=os.environ.copy(),
        )

        stdout_thread = threading.Thread(
            target=stream_pipe,
            args=(process.stdout, LOGGER.info),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=stream_pipe,
            args=(process.stderr, LOGGER.info),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        exit_code = process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        if exit_code == 0:
            LOGGER.info("Job finished successfully | run_id=%s | exit_code=%s", run_id, exit_code)
        else:
            LOGGER.error("Job failed | run_id=%s | exit_code=%s", run_id, exit_code)

    except Exception:
        LOGGER.exception("Unhandled exception while running spider | run_id=%s", run_id)
    finally:
        RUN_LOCK.release()

    if exit_code == 0 and config.backfill_after_scrape:
        run_backfill_job(config, parent_run_id=run_id)


def run_backfill_job(config: SchedulerConfig, parent_run_id: str | None = None) -> None:
    if not BACKFILL_LOCK.acquire(blocking=False):
        LOGGER.warning("Previous backfill run still active. Skipping this trigger.")
        return

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    cmd = build_backfill_command(config)
    parent_info = parent_run_id or "none"

    LOGGER.info("Backfill started | run_id=%s | parent_run_id=%s", run_id, parent_info)
    LOGGER.info("Executing command: %s", " ".join(shlex.quote(part) for part in cmd))
    LOGGER.info("Working directory: %s", config.backfill_project_dir)

    try:
        process = subprocess.Popen(
            cmd,
            cwd=config.backfill_project_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=os.environ.copy(),
        )

        stdout_thread = threading.Thread(
            target=stream_pipe,
            args=(process.stdout, LOGGER.info),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=stream_pipe,
            args=(process.stderr, LOGGER.info),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        exit_code = process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        if exit_code == 0:
            LOGGER.info("Backfill finished successfully | run_id=%s | exit_code=%s", run_id, exit_code)
        else:
            LOGGER.error("Backfill failed | run_id=%s | exit_code=%s", run_id, exit_code)

    except Exception:
        LOGGER.exception("Unhandled exception while running backfill | run_id=%s", run_id)
    finally:
        BACKFILL_LOCK.release()


def schedule_jobs(scheduler: BlockingScheduler, config: SchedulerConfig) -> None:
    for hour, minute in config.weekday_schedule_times:
        job_id = f"seek-weekday-{hour:02d}{minute:02d}"
        scheduler.add_job(
            func=run_spider_job,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=hour,
                minute=minute,
                timezone=ZoneInfo(config.timezone),
            ),
            kwargs={"config": config},
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        LOGGER.info(
            "Scheduled weekday job '%s' at %02d:%02d (%s)",
            job_id,
            hour,
            minute,
            config.timezone,
        )

    for hour, minute in config.weekend_schedule_times:
        job_id = f"seek-weekend-{hour:02d}{minute:02d}"
        scheduler.add_job(
            func=run_spider_job,
            trigger=CronTrigger(
                day_of_week="sat,sun",
                hour=hour,
                minute=minute,
                timezone=ZoneInfo(config.timezone),
            ),
            kwargs={"config": config},
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        LOGGER.info(
            "Scheduled weekend job '%s' at %02d:%02d (%s)",
            job_id,
            hour,
            minute,
            config.timezone,
        )

    if config.run_on_start:
        scheduler.add_job(
            func=run_spider_job,
            trigger="date",
            kwargs={"config": config},
            id="startup-run",
            replace_existing=True,
        )
        LOGGER.info("RUN_ON_START enabled: one immediate run scheduled.")


def main() -> None:
    configure_logging()
    config = build_config()

    LOGGER.info("Scheduler starting...")
    LOGGER.info(
        "Config | timezone=%s | weekday_times=%s | weekend_times=%s | spider=%s | args=%s",
        config.timezone,
        ",".join(f"{h:02d}:{m:02d}" for h, m in config.weekday_schedule_times),
        ",".join(f"{h:02d}:{m:02d}" for h, m in config.weekend_schedule_times),
        config.spider_name,
        ",".join(config.spider_args) if config.spider_args else "(none)",
    )
    LOGGER.info(
        "Backfill | after_scrape=%s | args=%s",
        config.backfill_after_scrape,
        " ".join(shlex.quote(arg) for arg in config.backfill_args) if config.backfill_args else "(none)",
    )

    scheduler = BlockingScheduler(timezone=ZoneInfo(config.timezone))
    schedule_jobs(scheduler, config)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        LOGGER.info("Scheduler stopped.")


if __name__ == "__main__":
    main()