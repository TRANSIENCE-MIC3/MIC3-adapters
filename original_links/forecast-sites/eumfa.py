# © 2026 Fraunhofer-Gesellschaft e.V., München
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Reader for EU-MFA (steel) result exports, resources/model_results/EUMFA.

Each flow is one CSV "<source>__<target>.csv" with columns region, time, sector, intermediate,
product, element, value (kt). Region is "EU27+1" (EU27 + UK). element "All" is total steel, "Cu" the
copper tracer. Relevant flows for production coupling:
- sysenv__steel_product_market: domestic steel product supply (production). dom + imports - exports =
  product_market -> goods_manufacturing exactly (mass balance checked 2025/2040/2050).
- waste_management__available_scrap_sysenv: scrap available to the steel industry (no `sector` column).
EUMFA counts finished steel PRODUCTS, not crude steel, and tracks real plant output poorly before 2023
(see couple_eumfa_production_targets.py) -- use it as an index, never as a level.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

KT_TO_T = 1000.0


def read_total_by_year(results_dir: str | Path, flow_name: str, years: list[int], element: str = 'All') -> dict[int, float]:
    """Sum a flow over all sectors/products for `element`; returns {year: tonnes}."""
    df = pd.read_csv(Path(results_dir) / f'{flow_name}.csv')
    df = df[df['element'] == element]
    totals = df.groupby('time')['value'].sum()
    missing = [y for y in years if y not in totals.index]
    if missing:
        message = f'{flow_name}: no data for years {missing}'
        raise ValueError(message)
    return {y: float(totals[y]) * KT_TO_T for y in years}
