#!/usr/bin/env bash
#
# Run the whole pipeline:
#
#   1. download every TNG transcript from chakoteya.net into "Season N" dirs
#   2. parse those transcripts into the SQLite line-count database
#   3. count the keywords.py terms per episode into the same database
#   4. add credits, air dates and viewership from Wikipedia
#
# All three steps are safe to re-run. The downloader skips transcripts already
# on disk, and both database builds upsert rather than starting over, so an
# interrupted run is resumed by simply running this script again.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PYTHON="${PYTHON:-python3}"
DELAY=2
TRANSCRIPTS_DIR="$HERE"
DB_PATH="$HERE/tng_data.db"
REBUILD_ARGS=()

usage() {
    cat <<'EOF'
Usage: ./build_all.sh [options]

Downloads all 176 TNG transcripts, then builds the line-count and keyword
database. Safe to re-run: finished downloads are skipped, both database
steps upsert, and nothing is re-fetched unnecessarily.

Options:
  --delay SECONDS   Seconds to wait between HTTP requests (default: 2)
  --out DIR         Where the "Season N" transcript directories live
  --db PATH         SQLite database path (default: ./tng_data.db)
  --rebuild         Drop and rebuild the database tables from scratch
  -h, --help        Show this help

Environment:
  PYTHON            Python interpreter to use (default: python3)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --delay)   DELAY="${2:?--delay needs a value}";   shift 2 ;;
        --out)     TRANSCRIPTS_DIR="${2:?--out needs a value}"; shift 2 ;;
        --db)      DB_PATH="${2:?--db needs a value}";    shift 2 ;;
        --rebuild) REBUILD_ARGS=(--rebuild);             shift ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
done

step() { printf '\n==> %s\n' "$*"; }

# ---------------------------------------------------------------------------
# Preflight: fail early and say exactly what to do, rather than dying halfway
# through a ten-minute download.
# ---------------------------------------------------------------------------
step "Checking prerequisites"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
    echo "Error: '$PYTHON' not found." >&2
    echo "Install Python 3, or run with PYTHON=/path/to/python3 ./build_all.sh" >&2
    exit 1
fi
echo "  $("$PYTHON" --version)"

missing=()
for module in requests bs4; do
    "$PYTHON" -c "import $module" >/dev/null 2>&1 || missing+=("$module")
done
if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Error: missing Python package(s): ${missing[*]}" >&2
    echo "Install them with:" >&2
    echo "    $PYTHON -m pip install requests beautifulsoup4" >&2
    exit 1
fi
echo "  requests and beautifulsoup4 present"

for script in download_tng_transcripts.py build_line_counts.py \
              build_keywords.py build_credits.py keywords.py; do
    if [[ ! -f "$script" ]]; then
        echo "Error: $script not found in $HERE" >&2
        exit 1
    fi
done

# ---------------------------------------------------------------------------
# Step 1: download
# ---------------------------------------------------------------------------
step "Downloading transcripts (${DELAY}s between requests)"
echo "  A first run takes roughly 10 minutes. Transcripts already on disk are"
echo "  skipped, so re-runs finish in seconds."
echo

if ! "$PYTHON" download_tng_transcripts.py --out "$TRANSCRIPTS_DIR" --delay "$DELAY"; then
    {
        echo
        echo "Some transcripts failed to download; the numbers are listed above."
        echo "Nothing partial was written, so just run ./build_all.sh again to"
        echo "retry only the ones that failed."
    } >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Step 2: build the database
# ---------------------------------------------------------------------------
step "Building the line-count database"
echo

"$PYTHON" build_line_counts.py \
    --transcripts-dir "$TRANSCRIPTS_DIR" \
    --db-path "$DB_PATH" \
    ${REBUILD_ARGS[@]+"${REBUILD_ARGS[@]}"}

# ---------------------------------------------------------------------------
# Step 3: keyword counts (needs the episodes rows from step 2)
# ---------------------------------------------------------------------------
step "Populating keyword counts"
echo

"$PYTHON" build_keywords.py \
    --transcripts-dir "$TRANSCRIPTS_DIR" \
    --db-path "$DB_PATH" \
    ${REBUILD_ARGS[@]+"${REBUILD_ARGS[@]}"}

# ---------------------------------------------------------------------------
# Step 4: credits (needs the episodes rows from step 2)
# ---------------------------------------------------------------------------
step "Adding credits, air dates and viewership"
echo

"$PYTHON" build_credits.py \
    --db-path "$DB_PATH" \
    ${REBUILD_ARGS[@]+"${REBUILD_ARGS[@]}"}

# ---------------------------------------------------------------------------
step "Done"
echo "  Transcripts: $TRANSCRIPTS_DIR/Season N/"
echo "  Database:    $DB_PATH"
echo
echo "Try a query:"
echo "  # which episode is this, again?"
echo "  sqlite3 '$DB_PATH' \\"
echo "    \"SELECT title, season, episode_number FROM episode_index"
echo "        WHERE title LIKE '%Darmok%';\""
echo
echo "  # the most Klingon-heavy episodes"
echo "  sqlite3 '$DB_PATH' \\"
echo "    \"SELECT season, episode_number, title, occurrences FROM category_counts"
echo "        WHERE category_key='klingon' ORDER BY occurrences DESC LIMIT 5;\""
