#!/usr/bin/env bash
set -euo pipefail
# Safe script to abort interrupted rebase, backup local artifacts,
# update .gitignore, untrack cached artifacts, and rebase against origin/main.

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

timestamp() { date +%Y%m%dT%H%M%S; }
BACKUP_DIR="/tmp/bloomly_backup_$(timestamp)"

echo "Repository root: $REPO_ROOT"

if [ ! -d .git ]; then
  echo "Error: no .git directory found. Run this script from the repository root." >&2
  exit 1
fi

echo "1) Checking for in-progress rebase..."
if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then
  echo "  Rebase appears in progress. Running: git rebase --abort"
  git rebase --abort || true
else
  echo "  No interactive rebase detected."
fi

echo "2) Creating backup: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

for d in .venv ml_models bloomly/ml_models; do
  if [ -e "$d" ]; then
    echo "  Backing up $d -> $BACKUP_DIR/"
    mv "$d" "$BACKUP_DIR/" || ( echo "  Failed to move $d" >&2; exit 1 )
  fi
done

echo "3) Ensuring .gitignore contains recommended entries"
IGN_ENTRIES=(".venv/" "ml_models/" "bloomly/ml_models/" "dump.rdb" "sqlite_backup.json" "vulture.txt" "media/")
for e in "${IGN_ENTRIES[@]}"; do
  if ! grep -Fxq "$e" .gitignore 2>/dev/null; then
    echo "$e" >> .gitignore
    echo "  Added $e to .gitignore"
  fi
done

echo "4) Untracking previously committed local artifacts (if any)"
git add .gitignore
git rm -r --cached --ignore-unmatch .venv ml_models bloomly/ml_models dump.rdb sqlite_backup.json vulture.txt media || true

echo "5) Commit .gitignore and removal of cached files (if any)"
if git diff --staged --quiet; then
  echo "  Nothing to commit (no staged changes)."
else
  git commit -m "chore: ignore local artifacts and untrack cached model/venv/dump files" || true
fi

echo "6) Fetching origin and attempting rebase"
git fetch origin
echo "  Running: git pull --rebase origin main"
if git pull --rebase origin main; then
  echo "Rebase/pull succeeded."
else
  echo "git pull --rebase failed. Resolve conflicts manually, then run: git rebase --continue" >&2
  exit 1
fi

echo "All done. Backups stored in: $BACKUP_DIR"
echo "If push is needed, configure auth (SSH or PAT) and run: git push -u origin main"
