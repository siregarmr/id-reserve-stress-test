# Indonesia Reserve Stress Test

[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/siregarmr/id-reserve-stress-test/blob/main/notebooks/run_stress_test.ipynb)

A five-block balance-of-payments-consistent reserve adequacy stress test for Indonesia, built with live data from Bank Indonesia (SEKI) and the World Bank.

---

## Methodology

The model simulates the evolution of Bank Indonesia’s official reserve assets under a range of macro-financial shocks. It decomposes the balance of payments into five interacting blocks, matching the structure used by central banks and the IMF:

| Block | Description | Key Variables |
|-------|-------------|---------------|
| **1. External Sector** | Current account: goods, services, primary & secondary income | Exports, imports, services balance, income balance |
| **2. Capital Flows** | Financial account: FDI, portfolio investment, other investment | Net FDI, net portfolio flows, net other investment |
| **3. Debt** | Short-term external debt stock, debt service, rollover risk | Short-term debt (World Bank), monthly debt service, rollover rate |
| **4. FX Intervention** | Endogenous BI response to depreciation & reserve adequacy | Intervention cap, sensitivity to depreciation & import cover |
| **5. Reserve Adequacy** | Multiple metrics computed at each monthly step | Import cover, import+debt cover, Guidotti-Greenspan ratio, IMF ARA ratio |

Shocks are applied per block through configurable scenario files. The engine then projects reserves month-by-month using the balance-of-payments identity:

    Δ Reserves = Current Account + Financial Account + Net Debt Flow – Debt Service – Intervention

Reserve adequacy is assessed against four simultaneous metrics:

- **Import cover** (months) – reserves relative to monthly imports.
- **Import + debt cover** (months) – reserves relative to imports and debt service.
- **Guidotti–Greenspan ratio** – reserves relative to short-term external debt (threshold 1.0).
- **IMF ARA ratio** – reserves relative to the IMF’s Assessing Reserve Adequacy metric (threshold 1.0).

Soft- and hard-burnout flags are triggered when import cover falls below 6 months and 3 months, respectively.

### Data Sources

- **Bank Indonesia SEKI** – monthly/quarterly tables (BoP, reserves, exchange rates, external debt) downloaded directly from `https://www.bi.go.id/SEKI/tabel/`.
- **World Bank API** – short-term external debt stock (indicator `DT.DOD.DSTC.CD`) replaces the common 30%-of-total assumption.
- **Configuration fallback** – `config.yaml` stores manually-curated base values; it is never overwritten automatically.

### Automation

A GitHub Action runs the workflow `.github/workflows/update-data.yml` every Monday at 03:00 UTC.

It installs dependencies, runs `data_fetchers.py`, fetches the latest SEKI and World Bank data, and commits an updated `data/baseline_cache.pkl`. The projection engine uses this cache if it is less than 30 days old, otherwise falls back to fetching live data.

---

## Usage

### 1. Run directly in Google Colab (no installation)

Click the badge above, then click **Runtime → Run all**. The entire stress test (data fetch, deterministic projections, Monte Carlo) will execute in the cloud.

### 2. Run locally

```
git clone https://github.com/siregarmr/id-reserve-stress-test.git
cd id-reserve-stress-test
pip install -r requirements.txt
python stress_test.py --plot
```

It will show visualisations:

- Reserve paths for all scenarios
- Import cover, Guidotti–Greenspan ratio, and ARA ratio over time
- Monte Carlo burnout probabilities

---

## Configuration

All parameters are defined in `config.yaml`:

- **`baseline`**: starting values (reserves, imports, debt service proxy). These are **never** overwritten automatically; they serve as ultimate fallback.
- **`thresholds`**: soft-burnout (6 months import cover), hard-burnout (3 months), ARA adequate ratio (1.0).
- **`scenarios`**: each scenario contains independent shock multipliers for every block:
    - `external`: export/import/services/income multipliers.
    - `capital_flows`: FDI, portfolio, other investment multipliers.
    - `debt`: rollover rate, debt service multiplier.
    - `intervention_rule`: max monthly sales (Bn USD), depreciation threshold, import cover threshold, sensitivity parameters (α, β).
    - `exchange_rate`: annual depreciation percentage.
- **`ara`**: weights and denominators for the IMF ARA metric (simplified).

You can add new scenarios by adding a new named block to the `scenarios` section.

---

## Interpreting Results

For each scenario, the engine outputs a table of monthly values:

| Column | Description |
|--------|-------------|
| `reserves` | USD billion (end of month) |
| `current_account` | Net exports + services + income (USD bn) |
| `financial_account` | Net FDI + portfolio + other investment |
| `debt_service` | Total debt service (principal + interest) |
| `intervention` | FX sales by BI (USD bn) |
| `import_cover_months` | Reserves ÷ monthly imports |
| `import_debt_cover_months` | Reserves ÷ (imports + debt service) |
| `guidotti_greenspan` | Reserves ÷ short-term external debt |
| `ara_ratio` | Reserves ÷ IMF ARA metric |
| `soft_burnout` / `hard_burnout` | Boolean flags |

A **soft burnout** (import cover ≤ 6 months) indicates the economy is approaching the IMF’s traditional danger zone.  
A **hard burnout** (≤ 3 months) signals critical vulnerability.  
The **Guidotti–Greenspan ratio** below 1.0 indicates that reserves cannot cover the entire stock of short-term external debt.  
The **ARA ratio** < 1.0 indicates reserves are below the IMF’s adequacy threshold.

---

## Licence

This project is licensed under the MIT Licence – see the [LICENCE](LICENCE) file for details.