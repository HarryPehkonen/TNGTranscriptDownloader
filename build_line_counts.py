#!/usr/bin/env python3
"""
Parse Star Trek: TNG transcripts and build a normalized SQLite database
of line counts per character per episode.

The database is designed to be extensible for future TNG-related data.

Schema:
    seasons     (season_number)
    episodes    (episode_id, season, episode_number, episode_end, title,
                 site_transcript_id, filename)
    characters  (character_id, character_name)
    line_counts (episode_id, character_id, line_count)

    episode_slots -- view; one row per broadcast episode, expanding the two
                     double episodes so S1E02 and S7E26 are joinable.

Re-running is safe: episodes are upserted in place and each episode's line
counts are replaced, so the database can be refreshed without --rebuild.

Usage:
    python build_line_counts.py [--transcripts-dir DIR] [--db-path PATH] [--rebuild]

    --transcripts-dir  Directory containing "Season X" subdirs with TNG_*.txt files.
                       Default: same directory as this script.
    --db-path           Path to the SQLite database file.
                       Default: tng_data.db in this script's directory.
    --rebuild           Drop existing tables and rebuild from scratch.
"""

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Regex for matching dialogue speaker lines.
#
# A speaker label is one or more ALL-CAPS words, optionally followed by a
# numeric suffix, an annotation in brackets, and/or a parenthetical:
#
#     PICARD:                 one word
#     Q:                      a single letter -- Q has 560 lines in the series
#     GUL EVEK:               multiple words
#     PICARD JR:              ditto
#     RIKER 2:                numbered duplicate (kept distinct, see below)
#     WOMAN [OC]:             bracket annotation
#     DATA (LORE):            parenthetical
#
# Only the label itself is captured; the bracket and parenthetical groups sit
# outside the capture so they never reach the database.
#
# Scene directions like [Bridge] have no colon and so never match. Header
# metadata is excluded structurally instead -- see transcript_body().
# ---------------------------------------------------------------------------
SPEAKER_RE = re.compile(
    r"^([A-Z][A-Z0-9'’.\-]*"          # first word; a single letter is valid
    r"(?:[ ][A-Z][A-Z0-9'’.\-]*)*"    # further ALL-CAPS words
    r"(?:[ ]#?\d+)?)"                       # numeric suffix, captured with the name
    r"(?:\s*\[[^\]]*\])?"                   # [OC], [on viewscreen], ...
    r"(?:\s*\([^)]*\))?"                    # (LORE), ...
    r"\s*:"
)

# Transcripts written by download_tng_transcripts.py separate the metadata
# header from the dialogue with a rule of this many '=' characters.
HEADER_SEPARATOR = '=' * 60


def normalise_name(raw_name: str) -> str:
    """
    Normalise a raw speaker label to a canonical form: collapse internal
    whitespace, strip, uppercase.

    Numeric suffixes are deliberately preserved. "RIKER 2" appears only in
    "Second Chances" and "PICARD 2" only in "We'll Always Have Paris" and
    "Allegiance" -- in each case the transcript is labelling a genuine
    duplicate of the character, not a transcription artefact. Folding them
    into RIKER and PICARD would silently merge two different people.
    """
    return re.sub(r'\s+', ' ', raw_name).strip().upper()


def transcript_body(text: str) -> str:
    """
    Return just the dialogue, discarding the metadata header.

    Matching header lines by prefix is fragile; the transcripts already mark
    the boundary explicitly, so split on that. Falls back to the whole text
    if the separator is absent.
    """
    _, separator, body = text.partition(HEADER_SEPARATOR)
    return body if separator else text


def parse_filename(filename: str) -> dict:
    """
    Extract season and episode info from filename.

    Handles:
      TNG_S1E01-E02.txt  -> season=1, episode_start=1, episode_end=2 (combined)
      TNG_S1E03.txt      -> season=1, episode_start=3, episode_end=3
      TNG_S7E25.txt      -> season=7, episode_start=25, episode_end=25

    Returns dict with keys: season, episode_start, episode_end
    """
    m = re.match(r'TNG_S(\d+)E(\d+)(?:-E(\d+))?\.txt', filename)
    if not m:
        return None
    season = int(m.group(1))
    ep_start = int(m.group(2))
    ep_end = int(m.group(3)) if m.group(3) else ep_start
    return {
        'season': season,
        'episode_start': ep_start,
        'episode_end': ep_end,
    }


def extract_title(text: str) -> str:
    """
    Extract the episode title from the transcript header.

    The first line is: "Star Trek: The Next Generation - <title>"
    """
    first_line = text.split('\n')[0]
    # Remove the "Star Trek: The Next Generation - " prefix
    m = re.match(r'Star Trek:\s*The Next Generation\s*-\s*(.+)', first_line)
    if m:
        return m.group(1).strip()
    return first_line.strip()


def extract_site_transcript_id(text: str) -> str:
    """
    Extract the site transcript ID from the header.

    The second line is like: "Season 1, Episode 3 (site transcript 103)"
    or "Season 1, Episodes 1-2 (site transcript 101)"
    """
    for line in text.split('\n')[:5]:
        m = re.search(r'\(site transcript (\d+)\)', line)
        if m:
            return int(m.group(1))
    return None


def count_lines_in_transcript(filepath: Path) -> dict:
    """
    Parse a single transcript file and return a dict of
    {normalised_character_name: line_count}.

    Each "line" is one dialogue utterance (one speaker line with colon).
    """
    body = transcript_body(filepath.read_text(encoding='utf-8'))
    counts = {}

    for line in body.split('\n'):
        match = SPEAKER_RE.match(line.strip())
        if not match:
            continue
        name = normalise_name(match.group(1))
        if name:
            counts[name] = counts.get(name, 0) + 1

    return counts


def build_database(transcripts_dir: Path, db_path: Path, rebuild: bool = False):
    """
    Scan all transcript files, parse them, and populate the SQLite database.
    """
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    cur = conn.cursor()

    # -----------------------------------------------------------------------
    # Schema setup
    # -----------------------------------------------------------------------
    if rebuild:
        cur.execute("DROP VIEW  IF EXISTS episode_slots")
        cur.execute("DROP TABLE IF EXISTS line_counts")
        cur.execute("DROP TABLE IF EXISTS characters")
        cur.execute("DROP TABLE IF EXISTS episodes")
        cur.execute("DROP TABLE IF EXISTS seasons")
        conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS seasons (
            season_number INTEGER PRIMARY KEY
        )
    """)

    # episode_number is the first broadcast episode the transcript covers and
    # episode_end the last. They differ only for the two double episodes
    # ("Encounter at Farpoint" = S1E01-02, "All Good Things..." = S7E25-26).
    cur.execute("""
        CREATE TABLE IF NOT EXISTS episodes (
            episode_id          INTEGER PRIMARY KEY AUTOINCREMENT,
            season              INTEGER NOT NULL,
            episode_number      INTEGER NOT NULL,
            episode_end         INTEGER NOT NULL,
            title               TEXT,
            site_transcript_id  INTEGER,
            filename            TEXT NOT NULL,
            UNIQUE (season, episode_number),
            FOREIGN KEY (season) REFERENCES seasons(season_number)
        )
    """)

    # Migration: databases built before episode_end existed are otherwise
    # unusable without --rebuild, which would defeat the point of making
    # re-runs work at all. Backfill it from episode_number; the two doubles
    # are corrected as their transcripts are re-read below.
    columns = {row[1] for row in cur.execute("PRAGMA table_info(episodes)")}
    if columns and 'episode_end' not in columns:
        print("Migrating: adding episodes.episode_end")
        cur.execute("ALTER TABLE episodes ADD COLUMN episode_end INTEGER")
        cur.execute("UPDATE episodes SET episode_end = episode_number")
        conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS characters (
            character_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            character_name  TEXT NOT NULL UNIQUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS line_counts (
            episode_id    INTEGER NOT NULL,
            character_id  INTEGER NOT NULL,
            line_count    INTEGER NOT NULL,
            PRIMARY KEY (episode_id, character_id),
            FOREIGN KEY (episode_id)   REFERENCES episodes(episode_id),
            FOREIGN KEY (character_id)  REFERENCES characters(character_id)
        )
    """)

    # One row per broadcast episode, expanding the two doubles. Without this,
    # "S1E02" and "S7E26" simply do not exist and any join over a complete
    # episode list drops them.
    cur.execute("""
        CREATE VIEW IF NOT EXISTS episode_slots AS
        WITH RECURSIVE slots(episode_id, season, episode_number, last) AS (
            SELECT episode_id, season, episode_number, episode_end FROM episodes
            UNION ALL
            SELECT episode_id, season, episode_number + 1, last
              FROM slots WHERE episode_number < last
        )
        SELECT episode_id, season, episode_number FROM slots
    """)

    # -----------------------------------------------------------------------
    # Find and process all transcript files
    # -----------------------------------------------------------------------
    season_dirs = sorted(
        d for d in transcripts_dir.iterdir()
        if d.is_dir() and d.name.startswith("Season ")
    )

    if not season_dirs:
        print(f"Error: No 'Season X' directories found in {transcripts_dir}")
        conn.close()
        return

    total_files = 0
    total_lines = 0
    total_characters = set()

    for season_dir in season_dirs:
        season_num = int(season_dir.name.split()[-1])

        # Insert season
        cur.execute(
            "INSERT OR IGNORE INTO seasons (season_number) VALUES (?)",
            (season_num,)
        )

        txt_files = sorted(season_dir.glob("TNG_*.txt"))
        print(f"\n{season_dir.name}: {len(txt_files)} files")

        for txt_file in txt_files:
            file_info = parse_filename(txt_file.name)
            if not file_info:
                print(f"  Skipping (unrecognised filename): {txt_file.name}")
                continue

            text = txt_file.read_text(encoding='utf-8')
            title = extract_title(text)
            site_id = extract_site_transcript_id(text)

            # One row per transcript. A double episode records the range it
            # covers via episode_end; the episode_slots view expands it.
            ep_num = file_info['episode_start']
            ep_end = file_info['episode_end']

            # Upsert rather than INSERT OR REPLACE: the latter resolves the
            # UNIQUE conflict by deleting the row, which both orphans this
            # episode's line_counts and trips the foreign key on every re-run.
            cur.execute(
                """INSERT INTO episodes
                   (season, episode_number, episode_end, title,
                    site_transcript_id, filename)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (season, episode_number) DO UPDATE SET
                       episode_end        = excluded.episode_end,
                       title              = excluded.title,
                       site_transcript_id = excluded.site_transcript_id,
                       filename           = excluded.filename""",
                (season_num, ep_num, ep_end, title, site_id, txt_file.name)
            )
            episode_id = cur.execute(
                "SELECT episode_id FROM episodes WHERE season=? AND episode_number=?",
                (season_num, ep_num)
            ).fetchone()[0]

            # Clear this episode's previous counts so a re-parse cannot leave
            # stale rows behind for speakers that no longer match.
            cur.execute("DELETE FROM line_counts WHERE episode_id=?", (episode_id,))

            # Count lines
            line_counts = count_lines_in_transcript(txt_file)
            episode_total = 0

            for char_name, count in sorted(line_counts.items()):
                # Insert or get character
                cur.execute(
                    "INSERT OR IGNORE INTO characters (character_name) VALUES (?)",
                    (char_name,)
                )
                char_id = cur.execute(
                    "SELECT character_id FROM characters WHERE character_name=?",
                    (char_name,)
                ).fetchone()[0]

                cur.execute(
                    """INSERT OR REPLACE INTO line_counts
                       (episode_id, character_id, line_count) VALUES (?, ?, ?)""",
                    (episode_id, char_id, count)
                )
                episode_total += count
                total_characters.add(char_name)

            total_files += 1
            total_lines += episode_total
            print(f"  {txt_file.name}: {len(line_counts)} characters, {episode_total} lines")

    # Drop characters that no longer have any line counts -- labels an earlier
    # parser produced but the current one does not. Without this the characters
    # table accumulates names that appear in no episode, and its row count
    # silently disagrees with the parse.
    orphans = cur.execute(
        """DELETE FROM characters
           WHERE character_id NOT IN (SELECT character_id FROM line_counts)"""
    ).rowcount
    if orphans:
        print(f"\nRemoved {orphans} stale character(s) with no remaining lines")

    conn.commit()

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"Database built: {db_path}")
    print(f"  Files processed:  {total_files}")
    print(f"  Total lines:      {total_lines}")
    print(f"  Unique characters: {len(total_characters)}")

    # Show top 10 characters by total lines
    print(f"\nTop 10 characters by total line count:")
    cur.execute("""
        SELECT c.character_name, SUM(lc.line_count) as total
        FROM line_counts lc
        JOIN characters c ON lc.character_id = c.character_id
        GROUP BY c.character_id
        ORDER BY total DESC
        LIMIT 10
    """)
    for name, total in cur.fetchall():
        print(f"  {total:6d}  {name}")

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Parse TNG transcripts and build a line-count SQLite database."
    )
    parser.add_argument(
        '--transcripts-dir',
        default=str(Path(__file__).parent),
        help='Directory containing "Season X" subdirs with TNG_*.txt files'
    )
    parser.add_argument(
        '--db-path',
        default=str(Path(__file__).parent / 'tng_data.db'),
        help='Path to the SQLite database file'
    )
    parser.add_argument(
        '--rebuild',
        action='store_true',
        help='Drop existing tables and rebuild from scratch'
    )
    args = parser.parse_args()

    transcripts_dir = Path(args.transcripts_dir)
    db_path = Path(args.db_path)

    if not transcripts_dir.exists():
        print(f"Error: Transcripts directory not found: {transcripts_dir}")
        sys.exit(1)

    print(f"Transcripts directory: {transcripts_dir}")
    print(f"Database path:         {db_path}")
    print(f"Rebuild:               {args.rebuild}")

    build_database(transcripts_dir, db_path, args.rebuild)


if __name__ == "__main__":
    main()
