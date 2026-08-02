#!/usr/bin/env python3
"""
Count the keywords defined in keywords.py across the TNG transcripts and
store the per-episode totals in the SQLite database, joined to episodes.

Run build_line_counts.py first: this script matches transcripts to the
episodes rows that script creates, so it needs them to exist.

Usage:
    python build_keywords.py [--transcripts-dir DIR] [--db-path PATH] [--rebuild]

Tables added:
    categories        (category_id, category_key, label, kind)
    keywords          (keyword_id, canonical, tier, case_sensitive,
                       needs_context)
    keyword_variants  (keyword_id, variant)
    keyword_categories(keyword_id, category_id)
    keyword_counts    (episode_id, keyword_id, occurrences)

Views added:
    episode_index          -- title -> season/episode, doubles expanded
    keyword_episode_counts -- keyword_counts with names instead of ids
    category_counts        -- per-category totals per episode

Matching follows the rules recorded in keywords.py: whole words only (never
prefix wildcards), case-sensitive unless the term says otherwise, and terms
flagged needs_context must be preceded by USS/the/Starship.
"""

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

# Reuse the transcript parsing from the line-count builder so both scripts
# agree on exactly what counts as dialogue.
from build_line_counts import SPEAKER_RE, transcript_body
from keywords import CATEGORIES, TERMS, Term

# A needs_context term must follow one of these to count.
CONTEXT_PREFIX = r"(?:USS|U\.S\.S\.|the|The|Starship|starship)\s+"


def validate_taxonomy(categories: dict, terms: list) -> list:
    """Check the taxonomy and merge any terms sharing a canonical name."""
    if not categories or not terms:
        raise ValueError("keywords.py defines no categories or no terms")

    for term in terms:
        unknown = set(term.categories) - set(categories)
        if unknown:
            raise ValueError(
                f"term {term.canonical!r} references undefined "
                f"categor{'y' if len(unknown) == 1 else 'ies'}: "
                f"{', '.join(sorted(unknown))}"
            )

    # keywords.canonical is UNIQUE in the database, so duplicates would mean
    # the last entry silently wins and the others' categories are lost --
    # which is what happened to Vulcan and Kesprytt, each of which is both a
    # race and a place. Union them instead.
    merged = {}
    duplicates = []
    for term in terms:
        if term.canonical not in merged:
            merged[term.canonical] = term
            continue
        duplicates.append(term.canonical)
        existing = merged[term.canonical]
        merged[term.canonical] = Term(
            canonical=existing.canonical,
            variants=tuple(dict.fromkeys(existing.variants + term.variants)),
            categories=tuple(dict.fromkeys(existing.categories + term.categories)),
            tier=existing.tier,
            case_sensitive=existing.case_sensitive and term.case_sensitive,
            needs_context=existing.needs_context or term.needs_context,
            not_followed_by=existing.not_followed_by or term.not_followed_by,
        )

    if duplicates:
        print(f"Merged {len(duplicates)} duplicate term(s): "
              f"{', '.join(sorted(set(duplicates)))}", flush=True)

    return list(merged.values())


def compile_matcher(term: Term) -> re.Pattern:
    """
    Build the regex for one term.

    Variants are alternated, longest first so that "warp core breach" wins over
    "warp core". Internal spaces match runs of whitespace or hyphens, because
    the source is hard-wrapped and hyphenation varies.
    """
    alternatives = []
    for variant in sorted(term.variants, key=len, reverse=True):
        escaped = re.escape(variant)
        escaped = re.sub(r'\\?\s+', r'[\\s\\-]+', escaped)
        alternatives.append(escaped)

    pattern = r'\b(?:' + '|'.join(alternatives) + r')\b'
    if term.needs_context:
        pattern = CONTEXT_PREFIX + pattern
    if term.not_followed_by:
        # Stops a short designation matching inside a longer one, e.g.
        # "Starbase One" firing inside "Starbase One Three Three".
        pattern += r'(?!' + term.not_followed_by + r')'

    flags = 0 if term.case_sensitive else re.IGNORECASE
    return re.compile(pattern, flags)


def dialogue_of(path: Path) -> str:
    """Transcript text with the header, scene directions and speaker labels
    removed, so keyword counts reflect spoken words only."""
    body = transcript_body(path.read_text(encoding='utf-8'))
    spoken = []
    for line in body.split('\n'):
        line = line.strip()
        if not line or line.startswith('['):
            continue
        spoken.append(SPEAKER_RE.sub('', line))
    return ' '.join(spoken)


def create_schema(cur, rebuild: bool):
    if rebuild:
        for view in ('category_counts', 'keyword_episode_counts'):
            cur.execute(f"DROP VIEW IF EXISTS {view}")
        for table in ('keyword_counts', 'keyword_categories',
                      'keyword_variants', 'keywords', 'categories'):
            cur.execute(f"DROP TABLE IF EXISTS {table}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            category_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            category_key TEXT NOT NULL UNIQUE,
            label        TEXT NOT NULL,
            kind         TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS keywords (
            keyword_id     INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical      TEXT NOT NULL UNIQUE,
            tier           TEXT NOT NULL,
            case_sensitive INTEGER NOT NULL,
            needs_context  INTEGER NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS keyword_variants (
            keyword_id INTEGER NOT NULL,
            variant    TEXT NOT NULL,
            PRIMARY KEY (keyword_id, variant),
            FOREIGN KEY (keyword_id) REFERENCES keywords(keyword_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS keyword_categories (
            keyword_id  INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            PRIMARY KEY (keyword_id, category_id),
            FOREIGN KEY (keyword_id)  REFERENCES keywords(keyword_id),
            FOREIGN KEY (category_id) REFERENCES categories(category_id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS keyword_counts (
            episode_id  INTEGER NOT NULL,
            keyword_id  INTEGER NOT NULL,
            occurrences INTEGER NOT NULL,
            PRIMARY KEY (episode_id, keyword_id),
            FOREIGN KEY (episode_id) REFERENCES episodes(episode_id),
            FOREIGN KEY (keyword_id) REFERENCES keywords(keyword_id)
        )
    """)

    # Look an episode up by title. NOCASE so 'the naked now' matches, and the
    # doubles are expanded so a title resolves to both of its episode numbers.
    cur.execute("CREATE INDEX IF NOT EXISTS idx_episodes_title "
                "ON episodes(title COLLATE NOCASE)")
    cur.execute("""
        CREATE VIEW IF NOT EXISTS episode_index AS
        SELECT ep.title, sl.season, sl.episode_number, ep.episode_id,
               ep.site_transcript_id, ep.filename
          FROM episode_slots sl JOIN episodes ep USING(episode_id)
    """)
    cur.execute("""
        CREATE VIEW IF NOT EXISTS keyword_episode_counts AS
        SELECT ep.season, ep.episode_number, ep.title,
               k.canonical AS keyword, k.tier, kc.occurrences
          FROM keyword_counts kc
          JOIN keywords k  USING(keyword_id)
          JOIN episodes ep USING(episode_id)
    """)
    cur.execute("""
        CREATE VIEW IF NOT EXISTS category_counts AS
        SELECT ep.season, ep.episode_number, ep.title,
               c.category_key, c.label, SUM(kc.occurrences) AS occurrences
          FROM keyword_counts kc
          JOIN keyword_categories kcat USING(keyword_id)
          JOIN categories c            USING(category_id)
          JOIN episodes ep             USING(episode_id)
         GROUP BY ep.episode_id, c.category_id
    """)


def populate_taxonomy(cur, categories: dict, terms: list) -> dict:
    """Insert categories, keywords and variants. Returns canonical -> id."""
    for key, (label, kind) in categories.items():
        cur.execute(
            """INSERT INTO categories (category_key, label, kind)
               VALUES (?, ?, ?)
               ON CONFLICT (category_key) DO UPDATE SET
                   label = excluded.label, kind = excluded.kind""",
            (key, label, kind)
        )
    category_ids = dict(cur.execute(
        "SELECT category_key, category_id FROM categories").fetchall())

    keyword_ids = {}
    for term in terms:
        canonical = term.canonical
        cur.execute(
            """INSERT INTO keywords
                   (canonical, tier, case_sensitive, needs_context)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (canonical) DO UPDATE SET
                   tier           = excluded.tier,
                   case_sensitive = excluded.case_sensitive,
                   needs_context  = excluded.needs_context""",
            (canonical, term.tier,
             int(term.case_sensitive), int(term.needs_context))
        )
        keyword_id = cur.execute(
            "SELECT keyword_id FROM keywords WHERE canonical=?",
            (canonical,)).fetchone()[0]
        keyword_ids[canonical] = keyword_id

        # Replace rather than accumulate, so edits to keywords.py take
        # effect instead of leaving the old variants and categories behind.
        cur.execute("DELETE FROM keyword_variants WHERE keyword_id=?", (keyword_id,))
        cur.executemany(
            "INSERT INTO keyword_variants (keyword_id, variant) VALUES (?, ?)",
            [(keyword_id, v) for v in dict.fromkeys(term.variants)]
        )
        cur.execute("DELETE FROM keyword_categories WHERE keyword_id=?", (keyword_id,))
        cur.executemany(
            "INSERT INTO keyword_categories (keyword_id, category_id) VALUES (?, ?)",
            [(keyword_id, category_ids[c]) for c in dict.fromkeys(term.categories)]
        )

    # Terms deleted from keywords.py should disappear from the database too.
    live = set(keyword_ids.values())
    stale = [row[0] for row in cur.execute("SELECT keyword_id FROM keywords")
             if row[0] not in live]
    for keyword_id in stale:
        for table in ('keyword_counts', 'keyword_categories', 'keyword_variants'):
            cur.execute(f"DELETE FROM {table} WHERE keyword_id=?", (keyword_id,))
        cur.execute("DELETE FROM keywords WHERE keyword_id=?", (keyword_id,))
    if stale:
        print(f"Removed {len(stale)} keyword(s) no longer in the taxonomy", flush=True)

    return keyword_ids


def build(transcripts_dir: Path, db_path: Path, rebuild: bool = False) -> int:
    try:
        terms = validate_taxonomy(CATEGORIES, TERMS)
    except ValueError as exc:
        print(f"Error: keywords.py is not usable: {exc}", file=sys.stderr, flush=True)
        return 1
    matchers = {t.canonical: compile_matcher(t) for t in terms}

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        cur = conn.cursor()

        episodes = dict(cur.execute(
            "SELECT filename, episode_id FROM episodes").fetchall())
        if not episodes:
            print("Error: no episodes in the database. "
                  "Run build_line_counts.py first.", file=sys.stderr, flush=True)
            return 1

        create_schema(cur, rebuild)
        keyword_ids = populate_taxonomy(cur, CATEGORIES, terms)
        print(f"Taxonomy: {len(CATEGORIES)} categories, "
              f"{len(terms)} keywords", flush=True)

        files = sorted(transcripts_dir.glob("Season */TNG_*.txt"))
        if not files:
            print(f"Error: no transcripts found under {transcripts_dir}",
                  file=sys.stderr, flush=True)
            return 1

        total_hits = 0
        matched_files = 0
        missing = []

        for path in files:
            episode_id = episodes.get(path.name)
            if episode_id is None:
                missing.append(path.name)
                continue

            text = dialogue_of(path)
            cur.execute("DELETE FROM keyword_counts WHERE episode_id=?", (episode_id,))

            rows = []
            for canonical, matcher in matchers.items():
                hits = len(matcher.findall(text))
                if hits:
                    rows.append((episode_id, keyword_ids[canonical], hits))
            cur.executemany(
                "INSERT INTO keyword_counts (episode_id, keyword_id, occurrences) "
                "VALUES (?, ?, ?)", rows
            )
            total_hits += sum(r[2] for r in rows)
            matched_files += 1

        conn.commit()

        if missing:
            print(f"Warning: {len(missing)} transcript(s) have no episodes row; "
                  f"re-run build_line_counts.py", file=sys.stderr, flush=True)
            for name in missing[:5]:
                print(f"  {name}", file=sys.stderr, flush=True)

        print(f"Counted {total_hits:,} keyword occurrences "
              f"across {matched_files} episodes", flush=True)

        print("\nTop categories by total occurrences:", flush=True)
        for label, total, eps in cur.execute("""
                SELECT c.label, SUM(kc.occurrences) AS total,
                       COUNT(DISTINCT kc.episode_id) AS eps
                  FROM keyword_counts kc
                  JOIN keyword_categories USING(keyword_id)
                  JOIN categories c       USING(category_id)
                 GROUP BY c.category_id ORDER BY total DESC LIMIT 10"""):
            print(f"  {total:6d}  {eps:3d} eps  {label}", flush=True)
        return 0
    finally:
        conn.close()


def main():
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description="Populate per-episode keyword counts into the database.")
    parser.add_argument('--transcripts-dir', default=str(here),
                        help='Directory containing the "Season N" subdirectories')
    parser.add_argument('--db-path', default=str(here / 'tng_data.db'),
                        help='Path to the SQLite database file')
    parser.add_argument('--rebuild', action='store_true',
                        help='Drop and rebuild the keyword tables')
    args = parser.parse_args()

    transcripts_dir = Path(args.transcripts_dir)
    db_path = Path(args.db_path)

    for label, path in (("Transcripts directory", transcripts_dir),
                        ("Database", db_path)):
        if not path.exists():
            print(f"Error: {label} not found: {path}", file=sys.stderr, flush=True)
            return 1

    print(f"Transcripts: {transcripts_dir}", flush=True)
    print(f"Taxonomy:    keywords.py", flush=True)
    print(f"Database:    {db_path}", flush=True)
    print("-" * 60, flush=True)
    return build(transcripts_dir, db_path, args.rebuild)


if __name__ == "__main__":
    sys.exit(main())
