# src/utils.py
import yaml
import joblib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple
import pandas as pd


def load_config() -> dict:
    """Load config.yaml if it exists, otherwise return a sensible default."""
    config_path = Path("config.yaml")
    if not config_path.exists():
        print("config.yaml not found – using built-in fallbacks.")
        return {
            "baseline": {
                "monthly_imports_gs_bn": 25.21,
                "reserves_start_bn": 146.2,
                "monthly_debt_service_proxy_bn": 0.9,
            }
        }
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def cache_data(func):
    """Decorator that caches a function's return value to disk using joblib."""
    def wrapper(*args, **kwargs):
        force_refresh = kwargs.pop("force_refresh", False)
        cache_dir = Path("data/processed/")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / f"{func.__name__}_{datetime.now().strftime('%Y%m')}.pkl"

        if not force_refresh and cache_file.exists():
            return joblib.load(cache_file)

        result = func(*args, **kwargs)
        joblib.dump(result, cache_file)
        return result

    return wrapper


def save_baseline_cache(flows: Dict, trade_df: pd.DataFrame,
                        path: str = "data/baseline_cache.pkl"):
    """Save baseline flows and trade DataFrame to a single pickle file."""
    cache_path = Path(path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump((flows, trade_df), cache_path)
    print(f"Baseline cache saved to {cache_path}")


def load_baseline_cache(path: str = "data/baseline_cache.pkl",
                        max_age_days: int = 30) -> Optional[Tuple[Dict, pd.DataFrame]]:
    """
    Load baseline cache if it exists and is not older than `max_age_days`.
    Returns (flows, trade_df) tuple, or None if missing / stale.
    """
    cache_path = Path(path)
    if not cache_path.exists():
        return None
    mtime = datetime.fromtimestamp(cache_path.stat().st_mtime)
    age = datetime.now() - mtime
    if age > timedelta(days=max_age_days):
        print(f"Baseline cache is {age.days} days old, ignoring.")
        return None
    try:
        flows, trade_df = joblib.load(cache_path)
        print(f"Loaded baseline cache from {cache_path} (age {age.days} days)")
        return flows, trade_df
    except Exception as e:
        print(f"Failed to load baseline cache: {e}")
        return None