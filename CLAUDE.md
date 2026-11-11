# MIC3-adapters

Adapters and I/O contracts that link the seven TRANSIENCE models into MIC3 (Model for European Industry
Circularity and Climate Change Mitigation), plus the tools that keep them in step with the model repositories.
Internal working notes (handoff notes, findings workbook) live in `.internal_docs/`, which is git-ignored.
If you have that folder, read the handoff notes there first: they record the scope, the decisions taken so
far and the open questions.

## Layout

- `contracts/` – one YAML I/O contract per model (`eu-mfa`, `remind-mfa`, `forecast-sites`, `itom`,
  `open-gem`, `open-prom`, `lca-transience`) and `repo_pins.csv` with the commit each contract was written against.
- `tools/clone_repos.sh` – clones all model, linking and platform repos from `repo_pins.csv` into
  `model-repos/` (git-ignored; pinned commits, partial EU-MFA checkout, ~100 MB).
- `tools/check_contracts.py` – checks that every path and column a contract relies on still exists.
- `docs/baseline_links_steel.csv` – the 13 baseline links (B01–B13) the contracts refer to.
- `.internal_docs/` – internal working notes, local only (git-ignored).

## Rules

- **Never modify the model repositories.** They belong to the modelling teams; clones under
  `model-repos/` are read-only references. Adapters adapt to the models, not the other way round.
  If a model change is unavoidable, propose it to the team (pull request on their repo) or, as a last
  resort, keep a small documented patch here that is applied when the platform image is built.
- **Wrap the teams' existing linking scripts** instead of rewriting them (ITOM interface, `mrprom`,
  `remind-mfa/scripts/map_*.py`, LCA `0_convert_*` converters). Where a script hardcodes paths, stage files
  into a temporary copy of its folder rather than editing it.
- **Branches:** read `main`/`master` of every repo, except `pik-piam/remind-mfa`, which uses `transience`.
- **Scope (until changed in the handoff notes):** baseline only (no loops); iron & steel only for
  multi-sector models; scenario assumptions database out of scope; carbon price from OPEN-PROM;
  REMIND-MFA regions per D7.3 (EU = EU27+1); FORECAST-Sites gets production from EU-MFA.
- **Flag ambiguities, don't guess.** Surface design decisions before writing code and confirm them one by
  one; verify structural assumptions against the actual files before reporting them.
- When a contract changes, update the commit pin, rerun the checker, and record any new finding in the
  local findings workbook. Keep finding IDs (Fxx) out of committed files.

## Commands

```bash
tools/clone_repos.sh                     # pinned commits into model-repos/
tools/clone_repos.sh --latest            # latest commit of each pinned branch
tools/clone_repos.sh --full --only transience-eu-mfa   # complete EU-MFA (needed to run it)
python tools/check_contracts.py --pins   # --repos defaults to model-repos/
```

`check_contracts.py` needs Python 3.10+ with `pyyaml` and `openpyxl`.
