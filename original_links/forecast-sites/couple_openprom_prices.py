# © 2026 Fraunhofer-Gesellschaft e.V., München
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Apply OPEN-PROM's own industry-sector prices/biomass availability on top of an existing FORECAST
scenario, for whichever dataset/sector/carriers/regions the caller specifies.

Generic counterpart of what used to be a hardcoded, ammonia/methanol-only one-off script -- the
engine (apply_openprom_prices) is now parameterized by target dataset, scenario ids, industry
sector, carrier mapping and region scope, so a future sector (e.g. steel's own Iron and Steel
sector, or a different carrier set) reuses this module instead of copy-pasting a new one-off
script. See openprom.py for the reader this builds on, and couple_remind_production_targets.py
for the REMIND-side counterpart of this same generic-engine/thin-invocation split.

Because OPEN-PROM only ever supplies a handful of carriers (Electricity, Natural Gas, Hydrogen,
Biomass and Waste, Steam, ...) for one industry sector, applying it is always a two-step process:
1. Seed the target scenario as a full copy of some existing BASE scenario, across every
   scenario/region-scoped economic table -- otherwise a run against the new scenario fails
   outright on the first untouched table (e.g. region_interest_rate) with no data for it.
2. Override just the requested carriers' price/availability cells with OPEN-PROM's own values,
   for whichever regions OPEN-PROM actually covers (see openprom.ISO3_TO_FORECAST_REGION_ID) --
   any FORECAST region OPEN-PROM has no row for (e.g. Norway, grouped into OPEN-PROM's own non-EU
   macro-region) keeps the base scenario's value, left untouched.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent))
import openprom  # noqa: E402

DEFAULT_OPENPROM_FILE = Path('resources/model_results/OPENPROM/Prices&FinalEnergyBiomass.xlsx')

# Every scenario/region-scoped economic table that a BASE-scenario seed copy needs to cover.
BASE_SCENARIO_TABLES = (
    'energy_carrier_availability_in_gj',
    'energy_carrier_emission_in_t_co2_per_gj',
    'energy_carrier_lower_heating_value_in_gj_per_t',
    'energy_carrier_minimum_use_in_gj',
    'energy_carrier_purchase_price_in_euro_per_gj',
    'energy_carrier_sell_price_in_euro_per_gj',
    'energy_carrier_subsidies_in_euro_per_gj',
    'energy_carrier_taxes_in_euro_per_gj',
    'product_availability_in_t',
    'product_emission_in_t_co2_per_t',
    'product_purchase_price_in_euro_per_t',
    'product_sell_price_in_euro_per_t',
    'by_product_availability_in_t',
    'by_product_emission_in_t_co2_per_t',
    'by_product_purchase_price_in_euro_per_t',
    'by_product_sell_price_in_euro_per_t',
    'co2_cost_in_euro_per_t_co2',
    'region_interest_rate',
)


@dataclass(frozen=True)
class OpenPromPriceCouplingConfig:
    target_dir: Path
    base_scenario: int
    target_scenario: int
    industry_sector: str
    target_regions: set[int]
    # carrier name (OPEN-PROM's Variable segment, e.g. "Natural Gas") -> id_energy_carrier
    price_carrier_name_to_id: dict[str, int] = field(default_factory=dict)
    availability_carrier_name_to_id: dict[str, int] = field(default_factory=dict)
    openprom_file: Path = DEFAULT_OPENPROM_FILE
    years: tuple[int, ...] = (2025, 2030, 2035, 2040, 2045, 2050)
    iso3_to_region_id: dict[str, int] = field(default_factory=lambda: dict(openprom.ISO3_TO_FORECAST_REGION_ID))
    target_scenario_name: str | None = None
    seed_from_base: bool = True


def apply_openprom_prices(config: OpenPromPriceCouplingConfig) -> None:
    """Seed `config.target_scenario` from `config.base_scenario` (if requested) and override its
    price/availability for the configured carriers with OPEN-PROM's own data."""
    if config.seed_from_base:
        for table in BASE_SCENARIO_TABLES:
            _copy_scenario(config, f'{table}.csv', config.base_scenario, config.target_scenario)

    if config.price_carrier_name_to_id:
        price_reader = lambda iso3, carrier_name: openprom.read_price(  # noqa: E731
            config.openprom_file, config.industry_sector, carrier_name, iso3, list(config.years)
        )
        region_prices = _read_openprom_by_region(config, config.price_carrier_name_to_id, price_reader)
        _apply_overrides(config, 'energy_carrier_purchase_price_in_euro_per_gj.csv', region_prices)

    if config.availability_carrier_name_to_id:
        availability_reader = lambda iso3, _carrier_name: openprom.read_biomass_final_energy(  # noqa: E731
            config.openprom_file, config.industry_sector, iso3, list(config.years)
        )
        region_availability = _read_openprom_by_region(config, config.availability_carrier_name_to_id, availability_reader)
        _apply_overrides(config, 'energy_carrier_availability_in_gj.csv', region_availability)

    if config.target_scenario_name:
        _update_scenario_name(config)


def backup_dataset(target_dir: Path, tag: str) -> None:
    backup_dir = target_dir.parent / f'{target_dir.name}_backup_before_{tag}'
    if not backup_dir.exists():
        shutil.copytree(target_dir, backup_dir)
        print(f'Backed up {target_dir} to {backup_dir}')


def _read_openprom_by_region(
    config: OpenPromPriceCouplingConfig, carrier_name_to_id: dict[str, int], reader
) -> dict[tuple[int, int], dict[int, float]]:
    """{(forecast_region_id, carrier_id): {year: value}} for every target region OPEN-PROM covers."""
    values: dict[tuple[int, int], dict[int, float]] = {}
    for iso3, region_id in config.iso3_to_region_id.items():
        if region_id not in config.target_regions:
            continue
        for carrier_name, carrier_id in carrier_name_to_id.items():
            try:
                values[(region_id, carrier_id)] = reader(iso3, carrier_name)
            except KeyError:
                continue
    return values


def _copy_scenario(config: OpenPromPriceCouplingConfig, table_name: str, source_scenario: int, target_scenario: int) -> None:
    """Copy source_scenario's rows (for config.target_regions) into target_scenario, as the
    starting point that OPEN-PROM's own values then get overridden on top of."""
    path = config.target_dir / table_name
    df = pd.read_csv(path)

    source_rows = df[(df['id_scenario'] == source_scenario) & (df['id_region'].isin(config.target_regions))].copy()
    source_rows['id_scenario'] = target_scenario

    result = pd.concat([df[df['id_scenario'] != target_scenario], source_rows], ignore_index=True)
    result.to_csv(path, index=False)
    print(f'{table_name}: seeded scenario {target_scenario} with {len(source_rows)} rows from scenario {source_scenario}')


def _apply_overrides(
    config: OpenPromPriceCouplingConfig, table_name: str, region_carrier_values: dict[tuple[int, int], dict[int, float]]
) -> None:
    path = config.target_dir / table_name
    df = pd.read_csv(path)

    is_target_scenario = df['id_scenario'] == config.target_scenario
    updated = 0
    for (region_id, carrier_id), year_values in region_carrier_values.items():
        row_mask = is_target_scenario & (df['id_region'] == region_id) & (df['id_energy_carrier'] == carrier_id)
        if not row_mask.any():
            continue
        for year, value in year_values.items():
            df.loc[row_mask, str(year)] = round(value, 6)
        updated += int(row_mask.sum())

    df.to_csv(path, index=False)
    print(f'{table_name}: overrode {updated} (region, carrier) rows with OPEN-PROM {config.industry_sector} data')


def _update_scenario_name(config: OpenPromPriceCouplingConfig) -> None:
    path = config.target_dir / 'id_scenario.csv'
    df = pd.read_csv(path)
    df.loc[df['id'] == config.target_scenario, 'name'] = config.target_scenario_name
    df.to_csv(path, index=False)


# -- default invocation: ammonia/methanol scenario 3, OPEN-PROM Chemicals prices (Europe) --------

AMMONIA_METHANOL_REGIONS = {1, 2, 4, 6, 8, 9, 10, 11, 13, 15, 18, 19, 21, 23, 25, 26, 27, 29, 32}


def main() -> None:
    config = OpenPromPriceCouplingConfig(
        target_dir=Path('resources/input/ammonia_methanol'),
        base_scenario=1,
        target_scenario=3,
        industry_sector='Chemicals',
        target_regions=AMMONIA_METHANOL_REGIONS,
        price_carrier_name_to_id={
            'Electricity': 1,
            'Natural Gas': 6,
            'Biomass and Waste': 12,
            'Hydrogen': 26,
        },
        availability_carrier_name_to_id={
            'Biomass and Waste': 12,
        },
        target_scenario_name='OPEN-PROM Chemicals prices (Europe)',
    )
    backup_dataset(config.target_dir, 'openprom_chemicals_prices')
    apply_openprom_prices(config)
    print('Done.')


if __name__ == '__main__':
    main()
