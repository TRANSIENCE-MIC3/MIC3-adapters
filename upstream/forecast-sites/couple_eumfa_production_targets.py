# © 2026 Fraunhofer-Gesellschaft e.V., München
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Set steel production mandates (production_unit_product_mapping_in_t.csv): production per country and route
first, then per production unit by capacity. One rule for historic verification runs and forecast runs.

Stage 1 -- crude steel per country and route (tonnes), for a target year y
  Statistics: resources/model_results/STEEL_STATISTICS/steel_production_by_country_route.csv (worldsteel, 2023 and
  2025; primary = oxygen/BOF = product 121, secondary = electric/EAF = product 123). Countries missing in a year's
  table (Croatia, Hungary in 2025) take the value of the nearest year that has them.
  - y has a statistics year (2023, 2025): the statistic itself, no averaging.
  - y between two statistics years (2024): linear interpolation of the country values.
  - y after the reference year (2025): the reference-year country values, scaled with EU-MFA growth relative to the
    reference year: total with sysenv__steel_product_market, secondary with waste_management__available_scrap_sysenv,
    primary = total - secondary; country split = reference-year shares. Only growth rates are used, so the
    difference between EU-MFA steel products and crude steel cancels out.
  - any other year: not supported (raises).
Stage 2 -- production units: each country's route target is distributed over the country's production units in
  proportion to installed capacity (sum of max_process_execution_count of the processes that output the product).
  A target above capacity is still assigned (the model has to build the difference); it is printed as implied new build.
Countries without statistics (Norway, Switzerland, Latvia): mandate = installed capacity x the capacity utilisation of the
countries with statistics (per route and period). All other products stay untouched.

Writes steel_country_route_mapping.csv (reference-year base and shares) and coupling_validation_<tag>.csv
(never into the dataset folder: every *.csv there is loaded as a model table).

Run from repo root: python input/transience_coupling/couple_eumfa_production_targets.py
(applies 2025/2040/2050 in place to transience_steel; the runner uses couple() on a snapshot instead).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent))
from couple_remind_production_targets import _capacity_weights  # noqa: E402
from eumfa import read_total_by_year  # noqa: E402

ROUTE_PRODUCT = {'primary': 121, 'secondary': 123}
PERIOD_COLUMN = {
    'start': 'minimum_export_start_year_in_t',
    'interim': 'minimum_export_interim_year_in_t',
    'end': 'minimum_export_end_year_in_t',
}
STATISTICS_FILE = 'steel_production_by_country_route.csv'
MT_TO_T = 1e6
DRI_PROCESS_IDS = frozenset({1120, 1122})  # direct reduction, DRI fuel switch NG
DRI_AVAILABLE_FROM_YEAR = 2030


@dataclass(frozen=True)
class EumfaCouplingConfig:
    target_dir: Path
    year_periods: dict[str, int]
    tag: str
    eumfa_dir: Path = Path('resources/model_results/EUMFA')
    stats_dir: Path = Path('resources/model_results/STEEL_STATISTICS')
    reference_year: int = 2025
    encoding: str = 'latin-1'
    caps: bool = False  # False: a target above installed capacity is still assigned; the model builds the difference


def load_statistics(stats_dir: Path) -> dict[int, pd.DataFrame]:
    """{year: DataFrame(index country, columns primary/secondary, tonnes)} from the statistics table."""
    df = pd.read_csv(stats_dir / STATISTICS_FILE)
    return {
        int(year): group.pivot(index='country', columns='route', values='output_mt')[list(ROUTE_PRODUCT)] * MT_TO_T
        for year, group in df.groupby('year')
    }


def _filled(year: int, stats: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """Country values of `year`; countries missing in that year take the value of the nearest statistics year."""
    table = stats[year].copy()
    for country in sorted(set().union(*(t.index for t in stats.values())) - set(table.index)):
        donors = sorted((y for y, t in stats.items() if country in t.index), key=lambda y: abs(y - year))
        table.loc[country] = stats[donors[0]].loc[country]
    return table


def country_route_output(config: EumfaCouplingConfig, year: int, stats: dict[int, pd.DataFrame], countries: set[str]) -> pd.DataFrame:
    """Stage 1: crude steel per country and route for `year` (tonnes), restricted to `countries`."""
    years = sorted(stats)
    if year in stats:
        out = _filled(year, stats)
    elif years[0] < year < years[-1]:
        lower = max(y for y in years if y < year)
        upper = min(y for y in years if y > year)
        weight = (year - lower) / (upper - lower)
        out = _filled(lower, stats) * (1 - weight) + _filled(upper, stats) * weight
    elif year > config.reference_year:
        out = _eumfa_scaled(config, year, stats, countries)
    else:
        message = f'no statistics or EU-MFA rule for year {year} (statistics years {years}, reference year {config.reference_year})'
        raise ValueError(message)
    return out[out.index.isin(countries)]


def _eumfa_scaled(config: EumfaCouplingConfig, year: int, stats: dict[int, pd.DataFrame], countries: set[str]) -> pd.DataFrame:
    base = _filled(config.reference_year, stats)
    base = base[base.index.isin(countries)]
    dom = read_total_by_year(config.eumfa_dir, 'sysenv__steel_product_market', [config.reference_year, year])
    scrap = read_total_by_year(config.eumfa_dir, 'waste_management__available_scrap_sysenv', [config.reference_year, year])
    total = float(base.to_numpy().sum()) * dom[year] / dom[config.reference_year]
    secondary = float(base['secondary'].sum()) * scrap[year] / scrap[config.reference_year]
    share = base / base.sum()
    return pd.DataFrame({'primary': share['primary'] * (total - secondary), 'secondary': share['secondary'] * secondary})


def couple(config: EumfaCouplingConfig) -> pd.DataFrame:
    stats = load_statistics(config.stats_dir)
    site = _read(config, 'site.csv')
    production_unit = _read(config, 'production_unit.csv')
    sub_production_unit = _read(config, 'sub_production_unit.csv')
    id_region = _read(config, 'id_region.csv')
    process_output = _read(config, 'process_product_output_in_t_per_process_count.csv')
    mapping = _read(config, 'production_unit_product_mapping_in_t.csv')

    pu_country = (
        production_unit.merge(site, on='id_site').merge(id_region.rename(columns={'id': 'id_region', 'name': 'country'}), on='id_region')
        .set_index('id_production_unit')['country']
    )
    countries = set(pu_country)
    outputs = {period: country_route_output(config, year, stats, countries) for period, year in config.year_periods.items()}
    _write_mapping_table(config, stats, countries)

    report = []
    for route, product_id in ROUTE_PRODUCT.items():
        weights = _capacity_weights(sub_production_unit, process_output, product_id)
        for country in outputs['start'].index:
            rows = mapping.index[(mapping['id_product'] == product_id) & mapping['id_production_unit'].map(pu_country).eq(country)]
            w = mapping.loc[rows, 'id_production_unit'].map(weights).fillna(0.0)
            capacity = float(w.sum())
            for period, year in config.year_periods.items():
                target = float(outputs[period].loc[country, route])
                assigned = min(target, capacity) if config.caps else target
                if capacity > 0:
                    mapping.loc[rows, PERIOD_COLUMN[period]] = (w / capacity * assigned).to_numpy()
                report.append({'country': country, 'route': route, 'product': product_id, 'period': period, 'year': year,
                               'target_t': target, 'assigned_t': assigned if capacity > 0 else 0.0, 'capacity_t': capacity, 'n_pus': len(rows)})
    # Countries without statistics (Latvia, Norway, Switzerland): same capacity utilisation as the countries with
    # statistics, per route and period (their old mandates described 2025/2040/2050 and are replaced).
    matched = pd.DataFrame(report)
    for route, product_id in ROUTE_PRODUCT.items():
        weights = _capacity_weights(sub_production_unit, process_output, product_id)
        for period, year in config.year_periods.items():
            reference = matched[(matched['route'] == route) & (matched['period'] == period)]
            utilisation = float(reference['assigned_t'].sum() / reference['capacity_t'].sum())
            for country in sorted(countries - set(outputs['start'].index)):
                rows = mapping.index[(mapping['id_product'] == product_id) & mapping['id_production_unit'].map(pu_country).eq(country)]
                w = mapping.loc[rows, 'id_production_unit'].map(weights).fillna(0.0)
                capacity = float(w.sum())
                if capacity <= 0:
                    continue
                target = capacity * utilisation
                mapping.loc[rows, PERIOD_COLUMN[period]] = (w / capacity * target).to_numpy()
                report.append({'country': country, 'route': route, 'product': product_id, 'period': period, 'year': year,
                               'target_t': target, 'assigned_t': target, 'capacity_t': capacity, 'n_pus': len(rows)})
    mapping.to_csv(config.target_dir / 'production_unit_product_mapping_in_t.csv', index=False)
    result = _finish_report(config, pd.DataFrame(report), stats)
    _print_implied_new_build(result)
    return result


def _read(config: EumfaCouplingConfig, name: str) -> pd.DataFrame:
    return pd.read_csv(config.target_dir / name, encoding=config.encoding)


def _write_mapping_table(config: EumfaCouplingConfig, stats: dict[int, pd.DataFrame], countries: set[str]) -> None:
    """Reference-year base and country shares, inspectable; changes only with the statistics or the dataset's sites."""
    base = _filled(config.reference_year, stats)
    base = base[base.index.isin(countries)]
    share = base / base.sum()
    rows = [
        {'country': c, 'route': r, 'product_id': p, 'base_t': float(base.loc[c, r]), 'share_of_route': float(share.loc[c, r]),
         'reference_year': config.reference_year}
        for c in base.index for r, p in ROUTE_PRODUCT.items()
    ]
    pd.DataFrame(rows).to_csv(config.stats_dir / 'steel_country_route_mapping.csv', index=False)


def _finish_report(config: EumfaCouplingConfig, report: pd.DataFrame, stats: dict[int, pd.DataFrame]) -> pd.DataFrame:
    for year, table in stats.items():
        report[f'stat_{year}_t'] = [float(table[r].get(c, float('nan'))) for c, r in zip(report['country'], report['route'], strict=True)]
    report['utilisation'] = report['assigned_t'] / report['capacity_t'].where(report['capacity_t'] > 0)
    report.to_csv(config.stats_dir / f'coupling_validation_{config.tag}.csv', index=False)
    return report


def _print_implied_new_build(report: pd.DataFrame) -> None:
    over = report[(report['capacity_t'] > 0) & (report['assigned_t'] > report['capacity_t'] + 1)].copy()
    if over.empty:
        print('No country-route mandate exceeds installed capacity.')
        return
    over['implied_new_build_mt'] = (over['assigned_t'] - over['capacity_t']) / 1e6
    print('Mandates above installed capacity (the model has to build the difference):')
    print(over[['country', 'route', 'year', 'implied_new_build_mt', 'utilisation']].round(2).to_string(index=False))


def make_existing_technologies_available(target_dir: Path, available_from_year: int = 1900, encoding: str = 'latin-1') -> None:
    """Historic runs start before the technology-availability year of the existing steel technologies (2025 in
    process.csv). With optimize_start_year the start year is built from new-capacity options, which are blocked
    before tech_available_at_year, so every mandated region was infeasible in 2020. Technologies that are new
    (available from 2030, e.g. CCS, H2-DRI) stay unavailable."""
    path = target_dir / 'process.csv'
    process = pd.read_csv(path, encoding=encoding)
    mask = process['tech_available_at_year'].isin([2025, available_from_year])
    process.loc[mask, 'tech_available_at_year'] = available_from_year
    # Direct reduction (DRI) is not an existing EU route in the historic years: no new DRI before 2030
    # (installed DRI units are unaffected). H2-DRI (1121) is already 2030.
    dri = process['id_process'].isin(DRI_PROCESS_IDS)
    process.loc[dri, 'tech_available_at_year'] = DRI_AVAILABLE_FROM_YEAR
    process.to_csv(path, index=False, encoding=encoding)
    print(f'{path}: tech_available_at_year -> {available_from_year} for {int(mask.sum())} processes, DRI {sorted(DRI_PROCESS_IDS)} -> {DRI_AVAILABLE_FROM_YEAR}')


def main() -> None:
    config = EumfaCouplingConfig(
        target_dir=Path('resources/input/transience_steel'),
        year_periods={'start': 2025, 'interim': 2040, 'end': 2050}, tag='forward_2025_2050',
    )
    backup_dir = Path(tempfile.gettempdir()) / 'forecast_sites_dev_backups'
    backup_dir.mkdir(exist_ok=True)
    backup = backup_dir / 'production_unit_product_mapping_in_t.csv.bak_before_forward_coupling'
    shutil.copy2(config.target_dir / 'production_unit_product_mapping_in_t.csv', backup)
    print(f'Backup of the previous mapping: {backup}')
    report = couple(config)
    pd.set_option('display.width', 250, 'display.max_rows', 200)
    print(report.pivot_table(index=['route', 'country'], columns='period', values='assigned_t').div(1e6).round(2))


if __name__ == '__main__':
    main()
