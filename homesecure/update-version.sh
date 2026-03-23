#!/usr/bin/env bash
# =============================================================================
# HomeSecure — update_version.sh
#
# Bumps the version string in every file that carries one.
#
# Usage:
#   ./update_version.sh [new_version]
#
# Two modes:
#   1. Pass a version argument — the script uses that as the new version and
#      derives the old version from whatever is currently in config.yaml:
#
#        ./update_version.sh 2.1.0
#
#   2. No argument — edit config.yaml first to set the new version, then run
#      the script with no arguments. It reads both the git-tracked (old) and
#      working-copy (new) versions automatically:
#
#        # edit config.yaml:  version: "2.1.0"
#        ./update_version.sh
#
# The script must be run from the repository root (the directory that contains
# config.yaml, run.sh, build-local.sh, etc.).
# =============================================================================

set -euo pipefail

# ── Locate config.yaml ───────────────────────────────────────────────────────

if [[ ! -f config.yaml ]]; then
  echo "Error: config.yaml not found. Run this script from the repository root."
  exit 1
fi

_read_version() {
  grep -m1 '^version:' "$1" | sed 's/version:[[:space:]]*"\?\([^"]*\)"\?/\1/' | tr -d '[:space:]'
}

# ── Resolve OLD and NEW ───────────────────────────────────────────────────────

if [[ $# -eq 1 ]]; then
  # Argument supplied: NEW comes from the command line, OLD from config.yaml
  NEW="$1"
  OLD=$(_read_version config.yaml)

elif [[ $# -eq 0 ]]; then
  # No argument: NEW comes from config.yaml; OLD comes from git's last commit
  NEW=$(_read_version config.yaml)
  if git rev-parse --git-dir > /dev/null 2>&1; then
    OLD=$(git show HEAD:config.yaml 2>/dev/null | grep -m1 '^version:' \
          | sed 's/version:[[:space:]]*"\?\([^"]*\)"\?/\1/' | tr -d '[:space:]') \
          || OLD=""
  fi
  if [[ -z "${OLD:-}" ]]; then
    echo "Error: could not determine old version from git history."
    echo "Either pass the new version as an argument, or ensure git is available."
    echo "  Usage: $0 <new_version>"
    exit 1
  fi

else
  echo "Usage: $0 [new_version]"
  echo "  e.g. $0 2.1.0          # pass version explicitly"
  echo "  e.g. $0                 # read new version from config.yaml (requires git)"
  exit 1
fi

# Require semver X.Y.Z
if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: new version must be in X.Y.Z format (e.g. 2.1.0), got: '$NEW'"
  exit 1
fi
if ! [[ "$OLD" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Error: old version must be in X.Y.Z format (e.g. 2.0.0), got: '$OLD'"
  exit 1
fi
if [[ "$OLD" == "$NEW" ]]; then
  echo "Error: new version ($NEW) is the same as the current version. Nothing to do."
  exit 1
fi

# Derive short forms X.Y (used in prose comments and badge labels)
NEW_SHORT="${NEW%.*}"   # strips patch  →  "2.1"
OLD_SHORT="${OLD%.*}"

echo "=================================================="
echo "  HomeSecure version bump"
echo "  $OLD  →  $NEW"
echo "=================================================="
echo ""

# ── Helper: in-place sed that works on both GNU (Linux) and BSD (macOS) ───────

_sed() {
  # $1 = extended-regex pattern, $2 = replacement, $3 = file
  if sed --version 2>/dev/null | grep -q GNU; then
    sed -i -E "$1" "$3"
  else
    sed -i '' -E "$1" "$3"
  fi
}

changed=0

update() {
  # $1 = file path  $2 = sed expression  $3 = human description
  local file="$1" expr="$2" desc="$3"
  if [[ ! -f "$file" ]]; then
    echo "  ⚠  SKIP  $file  (file not found)"
    return
  fi
  if grep -qE "${OLD//./\\.}" "$file" 2>/dev/null || grep -qE "${OLD_SHORT//./\\.}" "$file" 2>/dev/null; then
    _sed "$expr" '' "$file"
    echo "  ✓  $file  — $desc"
    (( changed++ )) || true
  else
    echo "  –  $file  — nothing to change"
  fi
}

# ── Files with X.Y.Z semver strings ──────────────────────────────────────────

echo "--- Semver (X.Y.Z) fields ---"

# config.yaml  →  version: "2.0.0"
update "config.yaml" \
  "s/^(version:[[:space:]]*\")${OLD//./\\.}(\")$/\1${NEW}\2/" \
  'addon version field'

# integration/manifest.json  →  "version": "2.0.0"
update "homesecure/custom_components/homesecure/manifest.json" \
  "s/(\"version\":[[:space:]]*\")${OLD//./\\.}(\")/\1${NEW}\2/" \
  '"version" field'

# README.md  →  version-2.0.0-blue badge
update "README.md" \
  "s/version-${OLD//./\\.}-blue/version-${NEW}-blue/" \
  'shields.io badge'

# www/README.md  (copy of the same badge)
update "www/README.md" \
  "s/version-${OLD//./\\.}-blue/version-${NEW}-blue/" \
  'shields.io badge'

# run.sh  →  HomeSecure Container  v2.0.0
update "run.sh" \
  "s/v${OLD//./\\.}/v${NEW}/" \
  'startup log banner'

echo ""
echo "--- Short version (X.Y) in prose and comments ---"

# build-local.sh  →  HomeSecure Local Build Script v2.0  (short form)
update "../../build-local.sh" \
  "s/v${OLD_SHORT//./\\.}([^0-9])/v${NEW_SHORT}\1/g" \
  'version references'

# test-homesecure.py  →  HomeSecure v2.0 …
update "test-homesecure.py" \
  "s/HomeSecure v${OLD_SHORT//./\\.}/HomeSecure v${NEW_SHORT}/g" \
  'version banner strings'

# www/homesecure-card.js  →  HomeSecure Badge Card v2.0
update "www/homesecure-card.js" \
  "s/v${OLD_SHORT//./\\.}/v${NEW_SHORT}/g" \
  'card version comment'

# www/homesecure-admin.js  →  HomeSecure Admin Panel v2.1  (may differ from
# addon version — only update if the short base (2.x) matches)
update "www/homesecure-admin.js" \
  "s/(HomeSecure Admin Panel v)[0-9]+\.[0-9]+/\1${NEW_SHORT}/" \
  'admin panel version comment'

# README.md prose references  →  "In v2.0 …"  /  "v2.0.x"
update "README.md" \
  "s/v${OLD_SHORT//./\\.}([^0-9])/v${NEW_SHORT}\1/g" \
  'prose version references'

# ADMIN_README.md
update "ADMIN_README.md" \
  "s/v${OLD_SHORT//./\\.}([^0-9])/v${NEW_SHORT}\1/g" \
  'prose version references'

# www/ADMIN_README.md
update "www/ADMIN_README.md" \
  "s/v${OLD_SHORT//./\\.}([^0-9])/v${NEW_SHORT}\1/g" \
  'prose version references'

# automations-template.yaml  →  # HomeSecure v2.0 …
update "automations-template.yaml" \
  "s/v${OLD_SHORT//./\\.}([^0-9])/v${NEW_SHORT}\1/g" \
  'prose version reference'

# SECURITY_REVIEW.md
update "SECURITY_REVIEW.md" \
  "s/v${OLD_SHORT//./\\.}([^0-9])/v${NEW_SHORT}\1/g" \
  'prose version references'

# TESTING.md  →  HomeSecure v2.0 — API Test Suite
update "TESTING.md" \
  "s/HomeSecure v${OLD_SHORT//./\\.}/HomeSecure v${NEW_SHORT}/g" \
  'version banner string'

echo ""
echo "=================================================="
echo "  Done. $changed file(s) updated."
echo ""
echo "  Suggested next steps:"
echo "    1. git diff                      — review all changes"
echo "    2. grep -r \"${OLD}\" .            — confirm no old version remains"
echo "    3. git add -A && git commit -m \"chore: bump version to ${NEW}\""
echo "    4. git tag v${NEW} && git push --tags"
echo "=================================================="
