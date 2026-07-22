#!/usr/bin/env bash
# one-vault.sh — finish the vault consolidation. Run once, then delete this file.
#
# Quits Obsidian (it rewrites its vault registry on exit, so it must be closed first),
# removes the two redundant nested vault configs, prunes the registry down to wiki/,
# and reopens the surviving vault.
set -euo pipefail
R="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REG="$HOME/Library/Application Support/obsidian/obsidian.json"

echo "→ quitting Obsidian"
osascript -e 'tell application "Obsidian" to quit' 2>/dev/null || true
for _ in $(seq 20); do pgrep -x Obsidian >/dev/null || break; sleep 0.5; done
pgrep -x Obsidian >/dev/null && { echo "Obsidian still running — quit it manually, rerun"; exit 1; }

echo "→ backing up registry"
cp "$REG" "$REG.bak"

echo "→ removing redundant vault configs"
rm -rf "$R/.obsidian" "$R/wiki/pages/.obsidian"
rm -f  "$R/.obsidianignore" "$R/wiki/pages/2026-07-22.md"

echo "→ pruning vault registry to wiki/ (+ any vault outside nathanbot)"
python3 - "$REG" "$R" <<'PY'
import json, sys
reg, root = sys.argv[1], sys.argv[2].rstrip("/")
d = json.load(open(reg))
keep = {}
for vid, v in d.get("vaults", {}).items():
    p = v.get("path", "").rstrip("/")
    inside = p == root or p.startswith(root + "/")
    if inside and p != f"{root}/wiki":
        print(f"   dropped {p}")
        continue
    keep[vid] = v
d["vaults"] = keep
json.dump(d, open(reg, "w"), indent=0)
print(f"   kept {len(keep)} vault(s)")
PY

echo "→ reopening Obsidian"
open -a Obsidian

cat <<'EOF'

Left to do by hand in Obsidian (one time):
  1. Settings → Community plugins → turn ON, then Enable "Git" (already downloaded).
     Auto-commit is deliberately OFF — commit from the Source Control panel, or `nb sync`.
  2. Settings → Templates → confirm folder is `_templates`.
  3. Graph view → Groups: colours are preloaded (person/project/entity/reference/archived).

Then: git add -A && git commit -m "chore(wiki): drop redundant vault configs"
EOF
