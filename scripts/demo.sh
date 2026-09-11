#!/usr/bin/env bash
# usage: scripts/demo.sh <mock|public> <data_dir> [package_dir] [--no-imagery]
set -euo pipefail
cd "$(dirname "$0")/.."
PROVIDER=${1:-mock}; DATA=${2:-data/demo-$PROVIDER}; PKG=${3:-tests/fixtures/case_mt_2027}; shift 3 2>/dev/null || shift $#
mkdir -p "$DATA/layers"; cp tests/fixtures/layers/* "$DATA/layers/"
export EUDR_AGENTS=1 EUDR_GEO_PROVIDER=$PROVIDER EUDR_DATA_DIR=$DATA
E=.venv/bin/eudr
CID=$($E case create "$PKG" | grep -oE 'case_[a-f0-9]+' | head -1)
echo "case: $CID"
$E case run "$CID" "$@"
$E case show "$CID"
$E review list "$CID"
$E case ledger "$CID" 40
echo "$CID" > "$DATA/last_case_id"
