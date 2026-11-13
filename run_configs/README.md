# Model run configurations

Configuration files used for MIC3 model runs, kept so that each run can be reproduced. One folder per
model and dataset/run version; files are copied unchanged from the run outputs.

| Model | Version | File | Run |
|---|---|---|---|
| FORECAST-Sites | v1.3 (10 Nov 2026) | `forecast-sites/v1.3/simulation_options_steel_forward_2025_2050.toml` | Steel baseline, 2025–2050 (interim 2040), scenarios 1 = low CO2 and 2 = high CO2, dataset `transience_steel`, production mandates from EU-MFA |
| FORECAST-Sites | v1.3 (10 Nov 2026) | `forecast-sites/v1.3/simulation_options_steel_verification_2023_2025.toml` | Historic verification 2023–2025, scenario 1, dataset `transience_steel_1_corrected` |

Notes:
- FORECAST-Sites configs go to `src/simulation_options.toml`; paths inside are relative to the FORECAST-Sites
  repository root. The production mandates are built before the run with `input/run_steel_config.py <toml> --mandates`
  (FORECAST-Sites development version, not yet public). The input datasets are not public.
