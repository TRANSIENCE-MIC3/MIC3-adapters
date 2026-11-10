# MIC3 model I/O contracts (baseline, iron & steel)

One YAML file per model. Each contract records what the MIC3 adapters rely on in that model's public
repository: how the model runs, which native input files the baseline links write into, and which output
files the links read. Modellers can change anything else freely.

Status: draft v0.1, written from reading the repositories (no models were run). Commit pins are in each
file under `source`.

## Schema

```yaml
model: <id>                 # as in MIC3-API release.json where one exists
source: {repo, branch, commit, date}
dependencies: [...]         # licensed software/data that block containerised runs
run: {command, working_directory, config_file, config_keys}
inputs:                     # native inputs written by an adapter's import step
  - link: B0x               # IDs from Baseline_links_steel in the findings workbook
    from: <model>
    path: <relative path>   # in_repo: false if the file is not in the public repo
    format: csv | xlsx-sheet | sqlite | gdx | ...
    columns: [...]          # checked by tools/check_contracts.py where in_repo is true
    dimensions / units / time
    existing_code: {repo, path, entry}   # the team's script the adapter wraps
outputs:                    # native outputs read by an export step
  - link: B0x
    to: <model>
    path, format, columns, variables, units
open_questions: [...]
```

`tools/check_contracts.py` reads every contract and checks, against a local clone at the pinned (or latest)
commit, that each `in_repo: true` path exists and, for CSV files and xlsx sheets, that the listed columns are
present. Running it against the latest commits detects changes to a model's I/O that would break an adapter.
