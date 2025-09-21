import random
import time
from typing import Dict, List, Tuple
from datetime import date, datetime
import math
import numpy as np
from datetime import date, datetime
import pandas as pd
from jobspy import scrape_jobs

from .db import insert_payloads, log_error

def polite_sleep(ms_min: int, ms_max: int):
    time.sleep(random.uniform(ms_min/1000.0, ms_max/1000.0))

def scrape_pair(term: str, location: str, hours_old: int, results_wanted: int, fetch_description: bool) -> pd.DataFrame:
    df = scrape_jobs(
        site_name=["linkedin"],
        search_term=term,
        location=location,
        results_wanted=results_wanted,
        hours_old=hours_old,
        linkedin_fetch_description=fetch_description,
    )
    if df is None:
        return pd.DataFrame()
    # Guard and dedupe in-memory
    if "job_url" in df.columns:
        df = df.dropna(subset=["job_url"]).drop_duplicates(subset=["job_url"])
    return df

def run_scrape(con, run_id: int, *, terms: List[str], locations: List[str], hours_old: int, results_wanted: int, fetch_description: bool, delay_min_ms: int, delay_max_ms: int) -> Dict[str, int]:
    total_requests = 0
    total_rows = 0
    new_rows = 0
    error_count = 0

    for term in terms:
        for loc in locations:
            scope = f"{term} @ {loc}"
            attempts = 0
            success = False
            while attempts < 3 and not success:
                attempts += 1
                total_requests += 1
                try:
                    df = scrape_pair(term, loc, hours_old, results_wanted, fetch_description)
                    count = len(df)
                    total_rows += count
                    if count > 0:
                        payloads = _df_to_payloads(df)
                        new_rows += insert_payloads(con, payloads)
                    success = True
                except ValueError as e:
                    # Likely data/serialization issues (e.g., NaN when allow_nan=False)
                    error_count += 1
                    log_error(con, run_id, scope, "data_serialization", str(e), {"attempt": attempts})
                    # Non-retryable: break the loop for this pair
                    break
                except Exception as e:
                    error_count += 1
                    etype = "http_429" if "429" in str(e) else ("timeout" if "timed out" in str(e).lower() else "error")
                    log_error(con, run_id, scope, etype, str(e), {"attempt": attempts})
                    time.sleep(2 ** attempts)  # 1s, 2s, 4s backoff
            polite_sleep(delay_min_ms, delay_max_ms)

    return {
        "total_requests": total_requests,
        "total_rows": total_rows,
        "new_rows": new_rows,
        "error_count": error_count,
    }

def _sanitize(obj):
    """Recursively convert values to JSON-safe types:
       - datetimes/dates -> ISO 8601 strings
       - NaN/Inf -> None
       - numpy scalars -> native Python
    """
    if obj is None:
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, np.generic):            # numpy scalars
        obj = obj.item()
    if isinstance(obj, float):                 # NaN/Inf -> None
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize(v) for v in obj]
    return obj

def _df_to_payloads(df: pd.DataFrame) -> list[dict]:
    df = df.copy()

    # Convert pandas datetime64 columns to ISO strings
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = df[col].dt.strftime("%Y-%m-%dT%H:%M:%S")

    # Replace NaN/NaT with None
    df = df.where(pd.notnull(df), None)

    # Convert to records then deep-sanitize (handles nested/remaining NaN/Inf & numpy scalars)
    records = df.to_dict(orient="records")
    return [_sanitize(r) for r in records]