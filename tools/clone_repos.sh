#!/usr/bin/env bash
# Clone every model, linking and platform repository listed in contracts/repo_pins.csv.
#
# Repositories are cloned read-only reference copies: never commit to them from here.
# By default each one is checked out at the commit recorded in repo_pins.csv, fetching only
# that commit (no history). Repositories with sparse_paths (currently EU-MFA) fetch only the
# folders the contracts need, which keeps the total at roughly 100 MB instead of ~450 MB.
#
# Usage:
#   tools/clone_repos.sh [--dest DIR] [--latest] [--full] [--only NAME[,NAME...]]
#
#   --dest DIR   where to put the clones (default: model-repos/ inside this repo, git-ignored)
#   --latest     check out the latest commit of each pinned branch instead of the pinned commit
#                (use this before running tools/check_contracts.py to detect upstream changes)
#   --full       ignore sparse_paths and fetch the complete working tree (needed to run EU-MFA)
#   --only       clone only the named entries (the 'name' column of repo_pins.csv)
#
# Re-running the script updates existing clones in place. Private repositories (MIC3-WEB)
# need your own GitHub access; failures are reported and the script continues.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"
pins="$root/contracts/repo_pins.csv"
dest="$root/model-repos"
latest=0
full=0
only=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dest) dest="$2"; shift 2 ;;
    --latest) latest=1; shift ;;
    --full) full=1; shift ;;
    --only) only=",$2,"; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

mkdir -p "$dest"
failed=()

while IFS=, read -r name repo branch commit date sparse; do
  [[ "$name" == "name" || -z "$name" ]] && continue
  [[ -n "$only" && "$only" != *",$name,"* ]] && continue

  dir="$dest/$name"
  ref="$commit"
  [[ $latest -eq 1 ]] && ref="$branch"
  echo "== $name ($repo @ ${ref:0:12})"

  if [[ ! -d "$dir/.git" ]]; then
    git init -q "$dir"
    git -C "$dir" remote add origin "https://github.com/$repo.git"
  fi

  if [[ -n "$sparse" && $full -eq 0 ]]; then
    git -C "$dir" sparse-checkout set --no-cone ${sparse//;/ }
  else
    git -C "$dir" sparse-checkout disable 2>/dev/null || true
  fi

  if git -C "$dir" fetch -q --depth 1 --filter=blob:none origin "$ref" \
     && git -C "$dir" checkout -q --detach FETCH_HEAD; then
    head="$(git -C "$dir" rev-parse HEAD)"
    if [[ $latest -eq 0 && "$head" != "$commit" ]]; then
      echo "   WARNING: checked out $head, expected $commit" >&2
    fi
    echo "   $(git -C "$dir" log -1 --format='%h %cs') $(du -sh "$dir" | cut -f1)"
  else
    echo "   FAILED (no access, or the commit no longer exists upstream)" >&2
    failed+=("$name")
  fi
done < "$pins"

echo
echo "Clones in: $dest ($(du -sh "$dest" | cut -f1))"
if [[ ${#failed[@]} -gt 0 ]]; then
  echo "Failed: ${failed[*]}" >&2
  exit 1
fi
