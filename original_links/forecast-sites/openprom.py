# © 2026 Fraunhofer-Gesellschaft e.V., München
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Reusable reader for OPEN-PROM result exports (energy carrier prices, biomass final energy use).

See remind_mfa.py for the REMIND-side counterpart of this module -- same purpose (a thin,
dependency-free reader over one external model's native export format), different source format.

Source file: resources/model_results/OPENPROM/Prices&FinalEnergyBiomass.xlsx, two IAMC-format
sheets sharing the same Model/Scenario/Region/Variable/Unit + year-column layout:

- "Prices": Price|Final Energy|Industry|<sector>|<carrier>, unit k$2015/toe (plus one
  non-industry-scoped row, "Price|Primary Energy|Crude Oil and Feedstocks") -- use read_price for
  the former, read_variable directly for the latter.
- "FinalEnergyBiomass": Final Energy|Industry|<sector>|Biomass and Waste, unit Mtoe. There is no
  biomass PRICE row in this file; FinalEnergyBiomass is the closest available proxy for biomass
  availability -- actual observed/projected use, not a modeled ceiling -- treat it as a floor/
  reference point for calibration, not a hard availability cap, when coupling it into FORECAST's
  energy_carrier_availability_in_gj.

Region is OPEN-PROM's own code -- EU countries as 3-letter ISO3 (DEU, FRA, ...), non-EU as
REMIND-style macro-regions (CAZ, CHA, IND, JPN, LAM, MEA, NEU, OAS, REF, SSA, USA). Unlike
remind_mfa's EUR macro-region, OPEN-PROM breaks out each EU country individually -- the region
granularity matches FORECAST-Sites' own sites directly, no EUR-wide redistribution step needed.
ISO3_TO_FORECAST_REGION_ID below maps each EU27+UK code straight to this project's own id_region.

Unit conversion: read_price/read_biomass_final_energy convert to FORECAST's own units (EUR/GJ,
GJ) by default, using the same conversion this project already applied for an earlier OPEN-PROM
import (see input/_apply_transience_round2_scenario.py, which hand-rolled this exact conversion
for the steel dataset from an older OPEN-PROM export):
  - USD(2015) -> EUR(2015): ECB 2015 average rate, 1 EUR = 1.1095 USD -> factor 1/1.1095
  - toe -> GJ: 41.868 (IEA standard)
Pass convert=False to get the raw native-unit values (k$2015/toe, Mtoe) instead, e.g. to inspect
the source data directly or apply a different conversion.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

PRICES_SHEET = 'Prices'
FINAL_ENERGY_BIOMASS_SHEET = 'FinalEnergyBiomass'

USD2015_TO_EUR2015 = 1 / 1.1095
GJ_PER_TOE = 41.868

# FORECAST id_region for every EU27+UK ISO3 code this file uses (the other region codes present
# are REMIND-style non-EU macro-regions: CAZ, CHA, IND, JPN, LAM, MEA, NEU, OAS, REF, SSA, USA,
# which have no FORECAST region and are not included here). Carried over from the ISO3_TO_REGION_ID
# mapping already proven in input/_apply_transience_round2_scenario.py.
ISO3_TO_FORECAST_REGION_ID = {
    'AUT': 1, 'BEL': 2, 'CYP': 3, 'CZE': 4, 'DNK': 5, 'EST': 6, 'FIN': 7, 'FRA': 8, 'DEU': 9,
    'GRC': 10, 'HUN': 11, 'IRL': 12, 'ITA': 13, 'LVA': 14, 'LTU': 15, 'LUX': 16, 'MLT': 17,
    'NLD': 18, 'POL': 19, 'PRT': 20, 'SVK': 21, 'SVN': 22, 'ESP': 23, 'SWE': 24, 'GBR': 25,
    'ROU': 26, 'BGR': 27, 'HRV': 32,
}


@lru_cache(maxsize=8)
def _load_sheet(results_file: str, sheet_name: str) -> pd.DataFrame:
    """Read one sheet once per process -- read_variable is called per region x carrier x year set."""
    return pd.read_excel(results_file, sheet_name=sheet_name)


def read_variable(results_file: str | Path, sheet_name: str, variable: str, region: str, years: list[int]) -> dict[int, float]:
    """
    Read a single IAMC-format variable row and return {year: value} for one region.

    Args:
        results_file: path to Prices&FinalEnergyBiomass.xlsx
        sheet_name: PRICES_SHEET or FINAL_ENERGY_BIOMASS_SHEET
        variable: exact Variable string, e.g. "Price|Final Energy|Industry|Iron and Steel|Hydrogen"
        region: OPEN-PROM region code, e.g. "DEU" (see EU_ISO3_CODES)
        years: years to extract; raises if any requested year is missing as a column

    Returns:
        {year: value}, in the sheet's native unit (see module docstring)
    """
    df = _load_sheet(str(results_file), sheet_name)
    # Excel stores year headers as numbers, not text -- pandas parses them as int columns.
    df = df.rename(columns={column: int(column) for column in df.columns if isinstance(column, (int, float))})

    missing_year_columns = [year for year in years if year not in df.columns]
    if missing_year_columns:
        message = f'{sheet_name!r} sheet has no column for years {missing_year_columns}'
        raise ValueError(message)

    row = df[(df['Region'] == region) & (df['Variable'] == variable)]
    if row.empty:
        message = f"{sheet_name!r} sheet: no row for variable {variable!r}, region {region!r}"
        raise KeyError(message)

    row = row.iloc[0]
    return {year: float(row[year]) for year in years}


def read_price(
    results_file: str | Path,
    industry_sector: str,
    energy_carrier: str,
    region: str,
    years: list[int],
    convert: bool = True,
) -> dict[int, float]:
    """
    Read Price|Final Energy|Industry|<industry_sector>|<energy_carrier> for one region.

    Returns {year: price_in_eur_per_gj} by default (convert=True), using this project's
    established k$2015/toe -> EUR/GJ conversion (see module docstring). Pass convert=False for
    the raw {year: price_in_k_usd_2015_per_toe}. See available_industry_sectors/
    available_energy_carriers to discover valid spellings (e.g. "Hard Coal, Coke and Other
    Solids" -- some carrier names include punctuation).
    """
    variable = f'Price|Final Energy|Industry|{industry_sector}|{energy_carrier}'
    values = read_variable(results_file, PRICES_SHEET, variable, region, years)
    if not convert:
        return values
    return {year: _k_usd2015_per_toe_to_eur_per_gj(value) for year, value in values.items()}


def read_biomass_final_energy(
    results_file: str | Path, industry_sector: str, region: str, years: list[int], convert: bool = True
) -> dict[int, float]:
    """
    Read Final Energy|Industry|<industry_sector>|Biomass and Waste for one region.

    Returns {year: value_in_gj} by default (convert=True); pass convert=False for the raw
    {year: value_in_mtoe}. See module docstring for why this is a use/reference figure, not a
    modeled availability ceiling.
    """
    variable = f'Final Energy|Industry|{industry_sector}|Biomass and Waste'
    values = read_variable(results_file, FINAL_ENERGY_BIOMASS_SHEET, variable, region, years)
    if not convert:
        return values
    return {year: _mtoe_to_gj(value) for year, value in values.items()}


def _k_usd2015_per_toe_to_eur_per_gj(value: float) -> float:
    return value * 1000 / GJ_PER_TOE * USD2015_TO_EUR2015


def _mtoe_to_gj(value: float) -> float:
    return value * 1e6 * GJ_PER_TOE


def available_industry_sectors(results_file: str | Path, sheet_name: str = PRICES_SHEET) -> list[str]:
    """List the Industry|<sector> segment of every Variable in `sheet_name`, deduplicated."""
    df = pd.read_excel(results_file, sheet_name=sheet_name)
    sectors = {
        variable.split('|')[3]
        for variable in df['Variable'].unique()
        if variable.count('|') >= 3 and variable.split('|')[2] == 'Industry'
    }
    return sorted(sectors)


def available_energy_carriers(results_file: str | Path) -> list[str]:
    """List every <carrier> segment of the Prices sheet's Industry price variables, deduplicated."""
    df = pd.read_excel(results_file, sheet_name=PRICES_SHEET)
    carriers = {
        variable.split('|')[4]
        for variable in df['Variable'].unique()
        if variable.count('|') >= 4 and variable.split('|')[2] == 'Industry'
    }
    return sorted(carriers)
