# src/visualisation.py
# Consolidated dashboard for the Indonesia Reserve Stress Test.

import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from typing import Dict, Optional

sns.set_theme(style="whitegrid")


def plot_full_report(
    results: dict,
    figsize: tuple = (18, 10),
    save_path: Optional[str] = None,
    close_fig: bool = True,
):
    """
    Create a single dashboard figure with all key plots.
    Layout: 3 columns x 2 rows
      Row 1: Reserve paths | Import cover | Guidotti–Greenspan ratio
      Row 2: ARA ratio       | Burnout probabilities | (info)
    """
    det = results["deterministic"]
    mc = results["monte_carlo"]

    fig, axes = plt.subplots(2, 3, figsize=figsize, gridspec_kw={'hspace': 0.4})
    fig.suptitle("Indonesia Reserve Stress Test – Dashboard", fontsize=16, fontweight="bold")

    # ----- 1. Reserve paths -----
    ax1 = axes[0, 0]
    for name, df in det.items():
        ax1.plot(df["month"], df["reserves"], marker="o", label=name)
    ax1.axhline(y=0, color="black", linewidth=0.8, linestyle="--")
    ax1.set_title("Reserves (B USD)")
    ax1.set_xlabel("Month")
    ax1.set_ylabel("B USD")
    ax1.legend(fontsize=8)
    ax1.set_ylim(bottom=0)

    # ----- 2. Import cover -----
    ax2 = axes[0, 1]
    for name, df in det.items():
        ax2.plot(df["month"], df["import_cover_months"], marker="s", label=name)
    ax2.axhline(y=6.0, color="red", linestyle="--", label="Soft Burnout (6 mo)")
    ax2.axhline(y=3.0, color="darkred", linestyle=":", label="Hard Burnout (3 mo)")
    ax2.set_title("Import Cover (months)")
    ax2.set_xlabel("Month")
    ax2.set_ylabel("Months")
    ax2.legend(fontsize=8)

    # ----- 3. Guidotti–Greenspan ratio -----
    ax3 = axes[0, 2]
    for name, df in det.items():
        ax3.plot(df["month"], df["guidotti_greenspan"], marker="^", label=name)
    ax3.axhline(y=1.0, color="red", linestyle="--", label="Threshold (1.0)")
    ax3.set_title("Guidotti–Greenspan Ratio")
    ax3.set_xlabel("Month")
    ax3.set_ylabel("Ratio")
    ax3.legend(fontsize=8)

    # ----- 4. ARA ratio -----
    ax4 = axes[1, 0]
    for name, df in det.items():
        ax4.plot(df["month"], df["ara_ratio"], marker="d", label=name)
    ax4.axhline(y=1.0, color="red", linestyle="--", label="Adequate (1.0)")
    ax4.set_title("IMF ARA Ratio")
    ax4.set_xlabel("Month")
    ax4.set_ylabel("Ratio")
    ax4.legend(fontsize=8)

    # ----- 5. Burnout probabilities -----
    ax5 = axes[1, 1]
    if not mc.empty:
        mc_plot = mc.rename(columns={
            "soft_burnout_prob": "Soft Burnout",
            "hard_burnout_prob": "Hard Burnout",
            "ara_adequate_prob": "ARA Adequate",
        })
        # Convert to percentages and plot
        mc_pct = mc_plot * 100
        mc_pct.plot(kind="bar", ax=ax5)
        ax5.set_title("Monte Carlo Burnout Probabilities (Month 12)")
        ax5.set_ylabel("Probability (%)")
        ax5.set_ylim(0, 105)
        ax5.legend(fontsize=8)
        # Label the bars with the percentage values (now correctly 0–100)
        for container in ax5.containers:
            ax5.bar_label(container, fmt="%.0f%%", fontsize=8)
    else:
        ax5.text(0.5, 0.5, "No Monte Carlo data", ha="center", va="center")
        ax5.set_title("Burnout Probabilities")
        
    # ----- 6. Empty cell -----
    ax6 = axes[1, 2]
    ax6.axis("off")
    ax6.text(0.5, 0.5, "Powered by BI SEKI & World Bank",
             ha="center", va="center", fontsize=12, color="grey")

    plt.tight_layout(pad=2.0)
    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()
    if close_fig:
        plt.close(fig)


if __name__ == "__main__":
    from src.api import stress_test
    results = stress_test(n_months=12, mc_simulations=200, plot=False)
    plot_full_report(results, close_fig=False)