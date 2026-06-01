# src/data_fetchers.py
# BI SEKI data fetcher + World Bank short-term debt, with cache persistence.

import pandas as pd
import requests
from pathlib import Path
from typing import Dict, Optional, Tuple, Union
import re
import time
import warnings

from src.utils import load_config, cache_data, save_baseline_cache

warnings.filterwarnings("ignore")

# ----------------------------------------------------------------------
#  Persistent session
# ----------------------------------------------------------------------
_SESSION = None

def _session():
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
    return _SESSION

# ----------------------------------------------------------------------
#  URL builder (SEKI)
# ----------------------------------------------------------------------
ROMAN_TO_ARABIC = {
    "I": "1", "II": "2", "III": "3", "IV": "4",
    "V": "5", "VI": "6", "VII": "7", "VIII": "8", "IX": "9"
}
BASE_URL_DIRECT = "https://www.bi.go.id/SEKI/tabel/TABEL"

def _parse_table_id(table_id: str) -> Tuple[str, int, Optional[str]]:
    m = re.match(r'([IVX]+)\.(\d+)(?:\.([A-Z]))?', table_id, re.IGNORECASE)
    if not m:
        raise ValueError(f"Invalid table ID: {table_id}")
    roman, num, sub = m.groups()
    return roman.upper(), int(num), sub

def _direct_url(table_id: str) -> str:
    roman, num, sub = _parse_table_id(table_id)
    section = ROMAN_TO_ARABIC[roman]
    url = f"{BASE_URL_DIRECT}{section}_{num}"
    if sub:
        sub_idx = ord(sub.upper()) - ord('A') + 1
        url += f"_{sub_idx}"
    return url + ".xls"

# ----------------------------------------------------------------------
#  Download helpers
# ----------------------------------------------------------------------
def _download_file(url: str, filepath: Path) -> bool:
    try:
        resp = _session().get(url, timeout=20)
        resp.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(resp.content)
        time.sleep(0.3)
        return True
    except Exception as e:
        print(f"Download error {url}: {e}")
        return False

def _download_table(table_id: str) -> Optional[Path]:
    cache_dir = Path("data/raw/")
    cache_dir.mkdir(parents=True, exist_ok=True)
    filepath = cache_dir / f"seki_{table_id.replace('.', '_')}.xls"

    if filepath.exists():
        return filepath

    url = _direct_url(table_id)
    if _download_file(url, filepath):
        return filepath
    return None

# ----------------------------------------------------------------------
#  Worksheet helper – always last sheet
# ----------------------------------------------------------------------
def _choose_worksheet(filepath: Path) -> str:
    xl = pd.ExcelFile(filepath, engine="xlrd")
    sheets = xl.sheet_names
    return sheets[-1]

# ----------------------------------------------------------------------
#  Column index helper
# ----------------------------------------------------------------------
def _col_idx(letter: str) -> int:
    idx = 0
    for ch in letter.upper():
        idx = idx * 26 + (ord(ch) - ord('A') + 1)
    return idx - 1

# ----------------------------------------------------------------------
#  Number cleaning
# ----------------------------------------------------------------------
def _to_float(val) -> Optional[float]:
    if isinstance(val, (int, float)):
        if pd.isna(val):
            return None
        return float(val)
    if isinstance(val, str):
        s = val.replace(',', '').replace(' ', '').strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None

# ----------------------------------------------------------------------
#  Extraction definitions – table_id, label, key, item_col, value_col(s), is_monthly
# ----------------------------------------------------------------------
EXTRACTION_TASKS = [
    ("V.2",  "- Exports",             "exports_goods",   "CJ", "CG", False),
    ("V.2",  "- Imports",             "imports_goods",   "CJ", "CG", False),
    ("V.3",  "Services",              "services",        "CJ", "CG", False),
    ("V.4",  "Primary Income",        "primary_income",  "CJ", "CG", False),
    ("V.5",  "Secondary Income",      "secondary_income","CK", "CH", False),
    ("V.6",  "Direct Investment",     "fdi",             "CK", "CH", False),
    ("V.7",  "Portfolio Investment",  "portfolio",       "CJ", "CG", False),
    ("V.8",  "Other Investment",      "other_inv",       "CK", "CH", False),
    ("VI.1", "Total",                 "total_debt",      "CJ", "CG", False),
    ("VI.2", "Total",                 "govt_debt",       "CJ", "CG", False),
    ("VI.4", "Total",                 "private_debt",    "CK", "CH", False),
    # monthly: tuple of value columns, we take the rightmost valid
    ("V.9",  "Total",                 "reserves",        "HK", ("HE","HF","HG","HH"), True),
    ("V.40", "USD",                   "usdidr",          "DU", ("HE","HF","HG","HH"), True),
]

def _extract_value(filepath: Path, table_id: str, label: str,
                   item_col_letter: str, value_col_spec: Union[str, Tuple[str, ...]],
                   is_monthly: bool) -> Optional[float]:
    try:
        sheet_name = _choose_worksheet(filepath)
        df = pd.read_excel(filepath, sheet_name=sheet_name, header=None, engine="xlrd")

        item_col = _col_idx(item_col_letter)
        target = label.strip().lower()

        # For V.40, also try column 2 if the primary column fails
        alt_item_cols = []
        if table_id == "V.40":
            alt_item_cols.append(2)   # column C

        # Determine value columns
        if is_monthly:
            monthly_cols = [_col_idx(c) for c in value_col_spec]   # type: list[int]
        else:
            value_col = _col_idx(value_col_spec)                    # single int

        # Search for the label in the item column
        for _, row in df.iterrows():
            if item_col >= len(row):
                continue
            cell = str(row.iloc[item_col]).strip().lower()
            if target in cell:
                # Extract value
                if is_monthly:
                    # Take the rightmost valid monthly value
                    for col in reversed(monthly_cols):
                        if col < len(row):
                            v = _to_float(row.iloc[col])
                            if v is not None:
                                return v
                else:
                    if value_col < len(row):
                        v = _to_float(row.iloc[value_col])
                        if v is not None:
                            return v
                # If the expected column(s) failed, skip to next matching row
                continue

        # If primary column didn't find it, try alternate item columns
        for alt_col in alt_item_cols:
            for _, row in df.iterrows():
                if alt_col >= len(row):
                    continue
                cell = str(row.iloc[alt_col]).strip().lower()
                if target in cell or (target == "usd" and "u s d" in cell):
                    if is_monthly:
                        for col in reversed(monthly_cols):
                            if col < len(row):
                                v = _to_float(row.iloc[col])
                                if v is not None:
                                    return v
                    else:
                        if value_col < len(row):
                            v = _to_float(row.iloc[value_col])
                            if v is not None:
                                return v
                    continue

        return None
    except Exception as e:
        print(f"Parse error {filepath.name}: {e}")
        return None

# ----------------------------------------------------------------------
#  Main SEKI orchestrator
# ----------------------------------------------------------------------
@cache_data
def fetch_seki_baseline(force_refresh: bool = False) -> Dict:
    config = load_config()

    required_tables = set(task[0] for task in EXTRACTION_TASKS)
    raw = {tid: None for tid in required_tables}

    print("Downloading SEKI tables ...")
    for tid in required_tables:
        path = _download_table(tid)
        if path:
            raw[tid] = path
        else:
            print(f" {tid} ✗ download failed")

    print("\nExtracting values ...")
    result = {}
    for (tid, label, key, item_col, value_col, is_monthly) in EXTRACTION_TASKS:
        path = raw.get(tid)
        if path is None:
            result[key] = None
            print(f" {tid} ({label}) ✗ missing")
            continue
        val = _extract_value(path, tid, label, item_col, value_col, is_monthly)
        result[key] = val
        if val is not None:
            print(f" {tid} ({label}) ✓ {val:,.1f}")
        else:
            print(f" {tid} ({label}) ✗ no value")

    def bn(key, fallback=None):
        v = result.get(key)
        return fallback if v is None else v / 1000.0

    exports    = bn("exports_goods")
    imports    = bn("imports_goods")
    if imports is not None:
        imports = abs(imports)

    services   = bn("services")
    primary    = bn("primary_income")
    secondary  = bn("secondary_income")
    fdi        = bn("fdi")
    portfolio  = bn("portfolio")
    other_inv  = bn("other_inv")
    reserves   = bn("reserves")
    usdidr     = result.get("usdidr")
    total_debt   = bn("total_debt")
    govt_debt    = bn("govt_debt")
    private_debt = bn("private_debt")

    cfg = config.get("baseline", {})
    if exports is None:
        exports = cfg.get("monthly_imports_gs_bn", 25.21) * 0.94
    if imports is None:
        imports = cfg.get("monthly_imports_gs_bn", 25.21)
    if reserves is None:
        reserves = cfg.get("reserves_start_bn", 146.2)
    if usdidr is None:
        usdidr = 16000

    income_balance = None
    if primary is not None and secondary is not None:
        income_balance = primary + secondary
    elif primary is not None:
        income_balance = primary
    elif secondary is not None:
        income_balance = secondary

    final = {
        "exports_goods_bn":    exports,
        "imports_goods_bn":    imports,
        "services_balance_bn": services,
        "income_balance_bn":   income_balance,
        "fdi_net_bn":          fdi,
        "portfolio_net_bn":    portfolio,
        "other_inv_net_bn":    other_inv,
        "reserves_bn":         reserves,
        "usdidr":              usdidr,
        "total_debt_bn":       total_debt,
        "govt_debt_bn":        govt_debt,
        "private_debt_bn":     private_debt,
    }

    return final

# ----------------------------------------------------------------------
#  World Bank short-term debt
# ----------------------------------------------------------------------
def fetch_wb_shortterm_debt(force_refresh: bool = False) -> Optional[float]:
    """
    Return Indonesia's short-term external debt (in billion USD)
    from the World Bank API (indicator DT.DOD.DSTC.CD).
    Returns None if the fetch fails.
    """
    url = "http://api.worldbank.org/v2/country/ID/indicator/DT.DOD.DSTC.CD?format=json"
    try:
        resp = _session().get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for entry in data[1]:
            if entry["value"] is not None:
                value_bn = float(entry["value"]) / 1e9
                print(f"World Bank: short-term debt = ${value_bn:.1f} B")
                return value_bn
    except Exception as e:
        print(f"World Bank API failed: {e}")
    return None

# ----------------------------------------------------------------------
#  Compatibility wrapper – now saves the cache
# ----------------------------------------------------------------------
def get_latest_baseline_data() -> Tuple[Dict, pd.DataFrame]:
    seki = fetch_seki_baseline()
    st_debt_bn = fetch_wb_shortterm_debt()

    monthly_exp = (seki["exports_goods_bn"] or 0) / 3.0
    monthly_imp = (seki["imports_goods_bn"] or 0) / 3.0

    periods = pd.date_range(
        end=pd.Timestamp("2026-05-31"), periods=12, freq="ME"
    ).strftime("%Y-%m")
    trade_df = pd.DataFrame({
        "period": periods,
        "exports_gs_bn": [monthly_exp] * 12,
        "imports_gs_bn": [monthly_imp] * 12,
    })

    config = load_config()
    debt_svc = config.get("baseline", {}).get("monthly_debt_service_proxy_bn", 0.9)

    baseline_flows = {
        "reserves_start":       (seki["reserves_bn"] or 0) * 1e9,
        "monthly_imports_gs":   monthly_imp * 1e9,
        "monthly_exports_gs":   monthly_exp * 1e9,
        "monthly_debt_service": debt_svc * 1e9,
        "seki_raw":             seki,
        "short_term_debt_bn":   st_debt_bn,
    }

    # Save cache for future use
    save_baseline_cache(baseline_flows, trade_df)

    return baseline_flows, trade_df

if __name__ == "__main__":
    flows, trade = get_latest_baseline_data()
    print("\n=== Baseline Summary ===")
    for k, v in flows.items():
        if k != "seki_raw":
            if isinstance(v, float) and v > 1e6:
                print(f"{k:<25}: ${v/1e9:.2f} B")
            else:
                print(f"{k:<25}: {v}")