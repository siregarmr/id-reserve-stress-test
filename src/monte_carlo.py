# src/monte_carlo.py
# Monte Carlo simulation for the Indonesia Reserve Stress Test.
# Baseline data can be pre-loaded and shared across scenarios.

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple

from src.data_fetchers import get_latest_baseline_data
from src.projection import ReserveStressTest
from src.utils import load_config, load_baseline_cache


# ----------------------------------------------------------------------
#  Distribution sampling helpers
# ----------------------------------------------------------------------
def sample_shock(dist_spec: Dict, rng: np.random.Generator) -> float:
    dist_type = dist_spec.get("type", "fixed")
    if dist_type == "fixed":
        return float(dist_spec.get("value", 1.0))
    if dist_type == "normal":
        mean = float(dist_spec["mean"])
        std = float(dist_spec.get("std", 0.0))
        return max(0.01, rng.normal(mean, std))
    if dist_type == "lognormal":
        mean = float(dist_spec["mean"])
        std = float(dist_spec.get("std", 0.0))
        return rng.lognormal(mean, std)
    if dist_type == "uniform":
        lower = float(dist_spec["lower"])
        upper = float(dist_spec["upper"])
        return rng.uniform(lower, upper)
    raise ValueError(f"Unknown distribution type: {dist_type}")


def _build_random_scenario(scenario: Dict, stoch: Dict, rng: np.random.Generator) -> Dict:
    """Create a randomised scenario dictionary from stochastic specifications."""
    sim_scenario = {
        "description": scenario.get("description", ""),
        "external": {},
        "capital_flows": {},
        "debt": {},
        "intervention_rule": scenario.get("intervention_rule", {}).copy(),
        "exchange_rate": {},
    }
    for block, specs in [("external", stoch.get("external", {})),
                         ("capital_flows", stoch.get("capital_flows", {})),
                         ("debt", stoch.get("debt", {})),
                         ("exchange_rate", stoch.get("exchange_rate", {}))]:
        for key, dist in specs.items():
            sim_scenario[block][key] = sample_shock(dist, rng)
    return sim_scenario


# ----------------------------------------------------------------------
#  Monte Carlo runner (now accepts pre-loaded baseline data and config)
# ----------------------------------------------------------------------
def run_monte_carlo(
    scenario_name: str,
    n_simulations: int = 1000,
    months: int = 12,
    seed: Optional[int] = 42,
    baseline_data: Optional[Tuple[Dict, pd.DataFrame]] = None,
    config: Optional[Dict] = None,
) -> Dict[str, pd.DataFrame]:
    """
    Run Monte Carlo for a single scenario.
    If `baseline_data` is not provided, it will be loaded once internally.
    """
    if config is None:
        config = load_config()

    scenario = config["scenarios"].get(scenario_name)
    if scenario is None:
        raise ValueError(f"Scenario '{scenario_name}' not found in config.yaml")

    stoch = scenario.get("stochastic", {})
    if not stoch:
        raise ValueError(f"No 'stochastic' block for '{scenario_name}'")

    if baseline_data is None:
        cached = load_baseline_cache()
        if cached is not None:
            flows, trade_df = cached
        else:
            print("No fresh cache, fetching live data...")
            flows, trade_df = get_latest_baseline_data()
    else:
        flows, trade_df = baseline_data

    rng = np.random.default_rng(seed)

    # Pre-allocate arrays for metrics
    reserve_paths = np.zeros((n_simulations, months))
    ic_paths      = np.zeros((n_simulations, months))
    gg_paths      = np.zeros((n_simulations, months))
    ara_paths     = np.zeros((n_simulations, months))
    soft_burnout  = np.zeros((n_simulations, months), dtype=bool)
    hard_burnout  = np.zeros((n_simulations, months), dtype=bool)
    ara_adequate  = np.zeros((n_simulations, months), dtype=bool)

    for i in range(n_simulations):
        sim_scenario = _build_random_scenario(scenario, stoch, rng)
        engine = ReserveStressTest(flows, trade_df, sim_scenario, config)
        df = engine.run(months)

        reserve_paths[i, :] = df["reserves"].values
        ic_paths[i, :]      = df["import_cover_months"].values
        gg_paths[i, :]      = df["guidotti_greenspan"].values
        ara_paths[i, :]     = df["ara_ratio"].values
        soft_burnout[i, :]  = df["soft_burnout"].values
        hard_burnout[i, :]  = df["hard_burnout"].values
        ara_adequate[i, :]  = df["ara_adequate"].values

        if (i + 1) % 100 == 0:
            print(f"  {scenario_name}: {i+1}/{n_simulations}")

    months_idx = list(range(1, months+1))
    paths_df = pd.DataFrame(reserve_paths, columns=[f"month_{m}" for m in months_idx])
    paths_df.index.name = "simulation"

    return {
        "reserve_paths": paths_df,
        "metrics": {
            "import_cover_months": pd.DataFrame(ic_paths, columns=[f"month_{m}" for m in months_idx]),
            "guidotti_greenspan": pd.DataFrame(gg_paths, columns=[f"month_{m}" for m in months_idx]),
            "ara_ratio": pd.DataFrame(ara_paths, columns=[f"month_{m}" for m in months_idx]),
        },
        "burnout_probabilities": pd.DataFrame({
            "month": months_idx,
            "soft_burnout_prob": soft_burnout.mean(axis=0),
            "hard_burnout_prob": hard_burnout.mean(axis=0),
            "ara_adequate_prob": ara_adequate.mean(axis=0),
        }).set_index("month"),
    }


# ----------------------------------------------------------------------
#  Wrapper – loads data once, runs all stochastic scenarios
# ----------------------------------------------------------------------
def run_all_scenarios_monte_carlo(
    n_simulations: int = 1000,
    months: int = 12,
    seed: Optional[int] = 42,
    baseline_data: Optional[Tuple[Dict, pd.DataFrame]] = None,
    config: Optional[Dict] = None,
) -> pd.DataFrame:
    """
    Run Monte Carlo for every scenario that has a 'stochastic' block.
    Baseline data can be provided; if not, it is loaded once.
    """
    if config is None:
        config = load_config()

    # Use provided baseline data, or load once
    if baseline_data is None:
        cached = load_baseline_cache()
        if cached is not None:
            baseline_data = cached
            print("Using cached baseline data.")
        else:
            print("Fetching live data (once)...")
            baseline_data = get_latest_baseline_data()

    scenarios = config["scenarios"]
    summary = []
    for name in scenarios:
        if "stochastic" not in scenarios[name]:
            print(f"Skipping '{name}' – no stochastic block")
            continue
        print(f"\nRunning Monte Carlo for {name} ({n_simulations} simulations)...")
        res = run_monte_carlo(
            scenario_name=name,
            n_simulations=n_simulations,
            months=months,
            seed=seed,
            baseline_data=baseline_data,
            config=config,
        )
        final = res["burnout_probabilities"].iloc[-1]
        summary.append({
            "scenario": name,
            "soft_burnout_prob": final["soft_burnout_prob"],
            "hard_burnout_prob": final["hard_burnout_prob"],
            "ara_adequate_prob": final["ara_adequate_prob"],
        })

    if not summary:
        print("No scenarios with stochastic blocks found.")
        return pd.DataFrame()

    df = pd.DataFrame(summary).set_index("scenario")
    print("\n=== Monte Carlo Summary (probabilities at month {}) ===".format(months))
    print(df.to_string(float_format=lambda x: f"{x:.2%}"))
    return df


# ----------------------------------------------------------------------
if __name__ == "__main__":
    run_all_scenarios_monte_carlo(n_simulations=200, months=12, seed=123456)