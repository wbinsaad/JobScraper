import os
import yaml
from dataclasses import dataclass, field
from typing import List, Optional

def _csv_env(name: str, default: List[str]) -> List[str]:
    val = os.getenv(name)
    if not val:
        return default
    return [x.strip() for x in val.split(",") if x.strip()]

@dataclass
class Config:
    sqlite_path: str = os.getenv("SQLITE_PATH", "/app/data/jobs.db")
    search_terms: List[str] = field(default_factory=lambda: _csv_env("SEARCH_TERMS", ["Werkstudent", "working student"]))
    locations: List[str] = field(default_factory=lambda: _csv_env("LOCATIONS", ["Germany"]))
    hours_old: int = int(os.getenv("HOURS_OLD", "24"))
    results_wanted: int = int(os.getenv("RESULTS_WANTED", "500"))
    fetch_description: bool = os.getenv("FETCH_DESCRIPTION", "true").lower() == "true"
    delay_min_ms: int = int(os.getenv("REQUEST_DELAY_MS_MIN", "500"))
    delay_max_ms: int = int(os.getenv("REQUEST_DELAY_MS_MAX", "1500"))
    batch_insert_size: int = int(os.getenv("BATCH_INSERT_SIZE", "100"))

    # Optional auth/proxy
    li_at: Optional[str] = os.getenv("LI_AT") or None
    jsessionid: Optional[str] = os.getenv("JSESSIONID") or None
    bsc: Optional[str] = os.getenv("BSC") or None
    http_proxy: Optional[str] = os.getenv("HTTP_PROXY") or None

def load_config(yaml_path: Optional[str] = None) -> Config:
    if yaml_path and os.path.exists(yaml_path):
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        cfg = Config()
        # overlay YAML values if present
        for k, v in data.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
        return cfg
    return Config()
