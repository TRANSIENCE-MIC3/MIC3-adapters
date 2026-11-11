# EU-MFA linking scripts (copy)

| File | Link | Purpose |
|---|---|---|
| `opengem_to_eumfa.R` | OPEN-GEM → EU-MFA | Growth rates of steel (and plastics) final demand from OPEN-GEM DEMAND/PROD/HC/GDP, mapped to EU-MFA sectors; writes `growth_rate.csv` and `FinalDemand.csv` |
| `remindmfa_to_eumfa.R` | REMIND-MFA → EU-MFA | Disaggregates REMIND-MFA goods and intermediate-product trade (region EUR) into EU-MFA `Import/ExportNewGoods/Products.csv` using historical EU-MFA demand shares; t → kt |
| `config.yml` | both | Extraction settings and the OPEN-GEM/REMIND-MFA ↔ EU-MFA region and sector correspondences |

- **Origin:** EU-MFA team (Wuppertal Institut), scripts used for the first MIC3 base run, received November 2026.
- **Licence:** AGPL-3.0-or-later, as for EU-MFA. The SPDX/copyright header (first three lines of each file)
  was added on copying; everything below it is unchanged.
- **Status:** kept here until the scripts are published in `wupperinst/transience-eu-mfa`; the contract
  (`contracts/eu-mfa.yaml`) will then point there.
- **Running:**
  - Both scripts expect a working folder with `config.yml`, `opengem/MACRO_BASE.csv` and `opengem/SECTOR_BASE.csv`
    (';'-separated, exported by hand from the OPEN-GEM report), `eumfatopdown/<steel|plastics>/` (templates,
    `start_value.csv`, `FinalDemand_past.csv`) and `remindmfa/<steel|plastics>_trades/` (REMIND-MFA `csv/flows` files).
  - `opengem_to_eumfa.R` sets its working directory with `rstudioapi`, so it currently runs only inside RStudio.
  - `remindmfa_to_eumfa.R` is the "fixed" version (correct disaggregation of intermediate-product trade, runnable
    with `Rscript`); it handles both `remindmfa_good` and `remindmfa_sector` keys in `config.yml`.
