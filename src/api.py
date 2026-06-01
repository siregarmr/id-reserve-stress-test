# src/api.py
# One-call API for the Indonesia Reserve Stress Test.

from src.data_fetchers import get_latest_baseline_data
from src.projection import run_all_scenarios
from src.monte_carlo import run_all_scenarios_monte_carlo
from src.utils import load_config, load_baseline_cache


def stress_test(
    n_months: int = 12,
    mc_simulations: int = 1000,
    seed: int = 42,
    plot: bool = False,
) -> dict:
    """
    Run the complete stress test:
      - Deterministic projections for all scenarios.
      - Monte Carlo simulations for all stochastic scenarios.
      - If `plot` is True, display the 3×2 dashboard.
    """
    config = load_config()

    # Load baseline data once
    cached = load_baseline_cache()
    if cached is not None:
        baseline_data = cached
        print("Using cached baseline data.")
    else:
        print("Fetching live data (once)...")
        baseline_data = get_latest_baseline_data()

    print("\n=== Deterministic Projections ===")
    det_results = run_all_scenarios(
        months=n_months,
        baseline_data=baseline_data,
        config=config,
    )

    print("\nFinal-month reserves and coverage:")
    for name, df in det_results.items():
        last = df.iloc[-1]
        print(f"  {name:10s}: reserves ${last['reserves']:.1f} B, "
              f"import cover {last['import_cover_months']:.1f} mo, "
              f"ARA {last['ara_ratio']:.2f}, soft burnout {last['soft_burnout']}")

    print("\n=== Monte Carlo ===")
    mc_summary = run_all_scenarios_monte_carlo(
        n_simulations=mc_simulations,
        months=n_months,
        seed=seed,
        baseline_data=baseline_data,
        config=config,
    )

    results = {
        "deterministic": det_results,
        "monte_carlo": mc_summary,
    }

    if plot:
        from src.visualisation import plot_full_report
        plot_full_report(results)

    return results


if __name__ == "__main__":
    stress_test(plot=True)