# src/projection.py
# Five-block reserve stress test – with run_all_scenarios and parameterised loading.

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple

from src.data_fetchers import get_latest_baseline_data
from src.utils import load_config, load_baseline_cache


class ReserveStressTest:
    """
    Simulates monthly reserve evolution under a given scenario.
    Model blocks:
      1. External sector (exports, imports, services, income)
      2. Capital flows (FDI, portfolio, other investment)
      3. Debt (debt service, rollover of short-term debt)
      4. FX intervention (endogenous rule based on depreciation & adequacy)
      5. Reserve adequacy (multiple metrics)
    """

    def __init__(self, baseline: Dict, trade_df: pd.DataFrame,
                 scenario: Dict, config: Dict):
        self.baseline = baseline
        self.trade_df = trade_df.copy()
        self.scenario = scenario
        self.config = config

        # Initial reserves (billion USD)
        self.reserves = baseline["reserves_start"] / 1e9
        self.initial_reserves = self.reserves

        # Monthly baseline flows (billion USD)
        self.monthly_exports  = baseline["monthly_exports_gs"] / 1e9
        self.monthly_imports  = baseline["monthly_imports_gs"] / 1e9

        seki = baseline["seki_raw"]

        # Services and income balances – keep their sign
        svc_q = seki.get("services_balance_bn") or 0.0
        inc_q = seki.get("income_balance_bn") or 0.0
        self.monthly_services = svc_q / 3.0
        self.monthly_income   = inc_q / 3.0

        # Capital flows (quarterly net, converted to monthly)
        self.monthly_fdi       = (seki.get("fdi_net_bn")       or 0.0) / 3.0
        self.monthly_portfolio = (seki.get("portfolio_net_bn") or 0.0) / 3.0
        self.monthly_other_inv = (seki.get("other_inv_net_bn") or 0.0) / 3.0

        # Debt stocks (billion USD)
        total_debt   = seki.get("total_debt_bn")   or 0.0
        self.govt_debt    = seki.get("govt_debt_bn")    or 0.0
        self.private_debt = seki.get("private_debt_bn") or 0.0

        # Short-term debt: prefer World Bank, else fallback to 30% of total
        st_debt_wb = baseline.get("short_term_debt_bn")
        if st_debt_wb is not None and st_debt_wb > 0:
            self.short_term_debt = st_debt_wb
            print(f"Using World Bank short-term debt: ${st_debt_wb:.1f} B")
        else:
            self.short_term_debt = total_debt * 0.3
            print(f"World Bank short-term debt unavailable, falling back to 30% of total: ${self.short_term_debt:.1f} B")

        # Monthly debt service (billion USD)
        self.monthly_debt_service = baseline["monthly_debt_service"] / 1e9

        # Exchange rate
        self.usdidr = seki.get("usdidr") or 16000

        # ---- Shock parameters ----
        ext   = scenario.get("external", {})
        cap   = scenario.get("capital_flows", {})
        debt  = scenario.get("debt", {})
        fx    = scenario.get("exchange_rate", {})

        self.shock_export       = ext.get("export_shock", 1.0)
        self.shock_import       = ext.get("import_shock", 1.0)
        self.shock_services     = ext.get("services_shock", 1.0)
        self.shock_income       = ext.get("income_shock", 1.0)
        self.shock_fdi          = cap.get("fdi_shock", 1.0)
        self.shock_portfolio    = cap.get("portfolio_shock", 1.0)
        self.shock_other_inv    = cap.get("other_inv_shock", 1.0)
        self.rollover_rate      = debt.get("rollover_rate", 1.0)
        self.debt_service_shock = debt.get("debt_service_shock", 1.0)
        self.depreciation_pct   = fx.get("depreciation_pct", 0.0)

        # ---- Intervention rule parameters (endogenous) ----
        rule = scenario.get("intervention_rule", {})
        self.use_endogenous_rule = bool(rule)
        self.intensity_max = rule.get("max_monthly_bn", 10.0)
        self.import_cover_threshold = rule.get("import_cover_threshold", 6.0)
        self.depreciation_threshold = rule.get("depreciation_threshold", 2.0)
        self.alpha = rule.get("alpha", 0.5)
        self.beta  = rule.get("beta",  1.0)

        # ---- Adequacy thresholds ----
        self.soft_burnout = config["thresholds"]["soft_burnout_months"]
        self.hard_burnout = config["thresholds"]["hard_burnout_months"]
        self.ara_adequate = config["thresholds"]["ara_adequate"]

        # IMF ARA denominator (simplified)
        ara_cfg = config["ara"]
        self.ara_denom = (ara_cfg["st_debt_weight"] * ara_cfg["st_debt_bn"] +
                          ara_cfg["other_liab_weight"] * ara_cfg["other_liab_bn"] +
                          ara_cfg["m2_weight"] * ara_cfg["m2_bn"] +
                          ara_cfg["exports_annual_weight"] * ara_cfg["annual_exports_bn"])

    # ------------------------------------------------------------------
    def _monthly_step(self, month: int) -> Dict:
        """Update reserves for one month given the scenario shocks."""

        # 1. External sector (current account)
        exports     = self.monthly_exports * self.shock_export
        imports     = self.monthly_imports * self.shock_import
        services_net = self.monthly_services * self.shock_services
        income_net   = self.monthly_income * self.shock_income
        current_account = exports - imports + services_net + income_net

        # 2. Capital flows (financial account)
        fdi_net       = self.monthly_fdi * self.shock_fdi
        portfolio_net = self.monthly_portfolio * self.shock_portfolio
        other_net     = self.monthly_other_inv * self.shock_other_inv
        financial_account = fdi_net + portfolio_net + other_net

        # 3. Debt
        maturing_st_debt = self.short_term_debt / 12.0
        rolled_over = maturing_st_debt * self.rollover_rate
        net_debt_flow = rolled_over - maturing_st_debt
        debt_service = self.monthly_debt_service * self.debt_service_shock + abs(net_debt_flow)

        # 4. FX intervention (endogenous)
        if self.use_endogenous_rule:
            monthly_depreciation_pct = self.depreciation_pct / 12.0
            depreciation_pressure = max(0.0, monthly_depreciation_pct - self.depreciation_threshold)
            current_import_cover = self.reserves / (imports + 1e-9) if imports > 0 else 999.0
            adequacy_pressure = max(0.0, self.import_cover_threshold - current_import_cover)
            desired = self.alpha * depreciation_pressure + self.beta * adequacy_pressure
            intervention = min(self.intensity_max, desired)
            if intervention < 0:
                intervention = 0.0
        else:
            old_intensity = self.scenario.get("intervention", {}).get("intensity", 0.0)
            intervention = old_intensity

        # 5. Reserve change (BoP identity)
        reserve_change = (current_account + financial_account + net_debt_flow
                          - debt_service - intervention)
        self.reserves += reserve_change
        if self.reserves < 0:
            self.reserves = 0.0

        # Exchange rate (informational)
        self.usdidr *= (1.0 + self.depreciation_pct / 100.0 / 12.0)

        # Adequacy metrics
        denom_import = imports + 1e-9
        cov_import = self.reserves / denom_import
        cov_total  = self.reserves / (imports + debt_service + 1e-9)
        gg_ratio   = self.reserves / (self.short_term_debt + 1e-9)
        ara_ratio  = self.reserves / (self.ara_denom + 1e-9)

        return {
            "month": month,
            "reserves": self.reserves,
            "current_account": current_account,
            "financial_account": financial_account,
            "net_debt_flow": net_debt_flow,
            "debt_service": debt_service,
            "intervention": intervention,
            "usdidr": self.usdidr,
            "import_cover_months": cov_import,
            "import_debt_cover_months": cov_total,
            "guidotti_greenspan": gg_ratio,
            "ara_ratio": ara_ratio,
            "soft_burnout": cov_import <= self.soft_burnout,
            "hard_burnout": cov_import <= self.hard_burnout,
            "ara_adequate": ara_ratio >= self.ara_adequate,
        }

    # ------------------------------------------------------------------
    def run(self, months: int = 12) -> pd.DataFrame:
        results = []
        for m in range(1, months + 1):
            step = self._monthly_step(m)
            results.append(step)
        return pd.DataFrame(results)


# ----------------------------------------------------------------------
def _load_baseline():
    """Load baseline data from cache or fetch live."""
    cached = load_baseline_cache()
    if cached is not None:
        return cached
    print("Fetching live data (once)...")
    return get_latest_baseline_data()


def run_scenario(
    scenario_name: str,
    months: int = 12,
    baseline_data: Optional[Tuple[Dict, pd.DataFrame]] = None,
    config: Optional[Dict] = None,
) -> pd.DataFrame:
    """Run a single scenario. Load baseline data if not provided."""
    if config is None:
        config = load_config()
    if baseline_data is None:
        flows, trade_df = _load_baseline()
    else:
        flows, trade_df = baseline_data

    scenario = config["scenarios"].get(scenario_name)
    if scenario is None:
        raise ValueError(f"Scenario '{scenario_name}' not found in config.yaml")
    engine = ReserveStressTest(flows, trade_df, scenario, config)
    return engine.run(months)


def run_all_scenarios(
    months: int = 12,
    baseline_data: Optional[Tuple[Dict, pd.DataFrame]] = None,
    config: Optional[Dict] = None,
) -> Dict[str, pd.DataFrame]:
    """Run all deterministic scenarios and return a dict {scenario_name: DataFrame}."""
    if config is None:
        config = load_config()
    if baseline_data is None:
        flows, trade_df = _load_baseline()
    else:
        flows, trade_df = baseline_data
    results = {}
    for name in config["scenarios"]:
        scenario = config["scenarios"][name]
        engine = ReserveStressTest(flows, trade_df, scenario, config)
        results[name] = engine.run(months)
    return results


# ----------------------------------------------------------------------
if __name__ == "__main__":
    config = load_config()
    flows, trade_df = _load_baseline()
    for scen in config["scenarios"]:
        print(f"\n=== {scen} Scenario ===")
        df = run_scenario(scen, baseline_data=(flows, trade_df), config=config)
        first = df.iloc[0]
        print(f"First month flows (B USD):")
        print(f"  CA: {first['current_account']:.2f},  FA: {first['financial_account']:.2f}, "
              f" NetDebt: {first['net_debt_flow']:.2f},  DebtSvc: {first['debt_service']:.2f}, "
              f" Intervention: {first['intervention']:.2f}")
        print(df[["month", "reserves", "import_cover_months", "guidotti_greenspan",
                  "ara_ratio", "soft_burnout"]].to_string(index=False))