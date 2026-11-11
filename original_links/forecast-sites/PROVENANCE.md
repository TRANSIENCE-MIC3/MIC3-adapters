# FORECAST-Sites coupling scripts (copy)

| File | Link | Purpose |
|---|---|---|
| `couple_eumfa_production_targets.py` | EU-MFA → FORECAST-Sites | Steel production mandates per production unit from World Steel statistics and EU-MFA growth |
| `eumfa.py` | EU-MFA → FORECAST-Sites | Reader for EU-MFA flow exports |
| `couple_openprom_prices.py` | OPEN-PROM → FORECAST-Sites | Energy carrier prices and biomass availability from OPEN-PROM |
| `openprom.py` | OPEN-PROM → FORECAST-Sites | Reader for the OPEN-PROM baseline workbook |

- **Origin:** FORECAST-Sites team (Fraunhofer ISI), development version of FORECAST-Sites
  (`input/transience_coupling/`), received November 2026 with the files of the first MIC3 base run.
- **Licence:** AGPL-3.0-or-later (SPDX headers in each file), © 2026 Fraunhofer-Gesellschaft e.V.
- **Status:** verbatim copies, not modified. Kept here until the scripts are published in
  `fraunhofer-isi/forecast-sites`; the contract (`contracts/forecast-sites.yaml`) will then point there.
- **Not included:** `couple_remind_production_targets.py` (imported by `couple_eumfa_production_targets.py`
  for `_capacity_weights`) and the World Steel statistics file; both requested from the team.
- **Paths:** the scripts expect to run from the FORECAST-Sites repository root, with inputs under
  `resources/input/<dataset>` and external model results under `resources/model_results/{EUMFA,OPENPROM,STEEL_STATISTICS}`.
