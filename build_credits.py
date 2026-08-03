#!/usr/bin/env python3
"""
Add episode credits, air dates and US viewership to the database.

Source is Wikipedia's per-season TNG episode lists, keyed by production code --
the same numbering chakoteya.net uses, so credits join to transcripts exactly.

Only facts are stored: names, dates and numbers. Wikipedia's episode summaries
are its authors' own prose and are deliberately not copied.

Run build_line_counts.py first: this needs the episodes rows it creates.

Deliberately stores facts only and defines no notion of "similar episode".
What counts as similar depends on the question -- same writer, same director,
overlapping cast, shared subject -- so that is left to whoever is querying,
rather than frozen into a view.

Usage:
    python build_credits.py [--db-path PATH] [--cache DIR] [--refresh]
                            [--rebuild]

Tables added:
    people  (person_id, name)
    credits (episode_id, person_id, role)   role: director|writer|story|teleplay

Columns added to episodes:
    original_air_date       ISO date
    us_viewers_millions     Nielsen figure where Wikipedia has one

Views added:
    episode_credits    -- episode + person + role, readable
"""

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    sys.exit("Error: requests is required.\n"
             "    python -m pip install requests")

WIKI_URL = ("https://en.wikipedia.org/w/index.php"
            "?title=Star_Trek:_The_Next_Generation_season_{season}&action=raw")
USER_AGENT = ("TNG-transcript-archiver/1.0 "
              "(personal archive; harry.pehkonen@gmail.com)")
SEASONS = range(1, 8)
ROLES = ('director', 'writer', 'story', 'teleplay')


# ---------------------------------------------------------------------------
# Wikitext parsing
# ---------------------------------------------------------------------------

def clean(text: str) -> str:
    """Strip wiki markup down to plain text.

    Links are resolved before anything else: "[[Target|Display]]" carries an
    internal pipe, and template parameters are pipe-separated, so leaving them
    in place corrupts the parameter split.
    """
    text = re.sub(r'<ref[^>]*/>|<ref.*?</ref>', '', text, flags=re.S)
    text = re.sub(r'\{\{efn\|[^{}]*\}\}', '', text)
    text = re.sub(r'\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]', r'\1', text)
    text = re.sub(r"''+|<br\s*/?>", ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def split_names(text: str) -> list:
    """Split a credit into individual people.

    In screen credits "&" means a writing team and "and" means separate
    contributions. Both become individual people here; the distinction is not
    preserved.
    """
    return [p.strip(' .') for p in re.split(r'\s*(?:&|,|\band\b)\s*', text)
            if p.strip(' .')]


def parse_credits(written: str, directed: str) -> list:
    """Return [(role, name), ...] for one episode."""
    credits = [('director', n) for n in split_names(clean(directed))]

    text = clean(written)
    # Two templates share the same s=/t= shape. Not anchored to the end of the
    # string: one episode appends prose after the closing braces.
    match = re.search(r'\{\{(?:StoryTeleplay|WritingCredits)\|(.*?)\}\}', text)
    if match:
        params = {}
        for part in match.group(1).split('|'):
            if '=' in part:
                key, value = part.split('=', 1)
                params[key.strip()] = value.strip()
        credits += [('story', n) for n in split_names(params.get('s', ''))]
        credits += [('teleplay', n) for n in split_names(params.get('t', ''))]
    else:
        credits += [('writer', n) for n in split_names(text)]
    return credits


def parse_season(wikitext: str) -> list:
    """Return one dict per episode block that carries a production code."""
    episodes = []
    for block in re.split(r'\{\{Episode list', wikitext)[1:]:
        def field(name):
            found = re.search(rf'\|\s*{name}\s*=([^\n]*)', block)
            return found.group(1) if found else ''

        codes = re.findall(r'\d+', re.sub(r'<[^>]+>', ' ', field('ProdCode')))
        if not codes:
            continue

        date = re.search(r'\{\{Start date\|(\d+)\|(\d+)\|(\d+)',
                         field('OriginalAirDate'))
        rating = re.match(r'([\d.]+)', clean(field('Aux4')))

        episodes.append({
            'codes': [int(c) for c in codes],
            'credits': parse_credits(field('WrittenBy'), field('DirectedBy')),
            'air_date': (f"{date.group(1)}-{int(date.group(2)):02d}"
                         f"-{int(date.group(3)):02d}") if date else None,
            'viewers': float(rating.group(1)) if rating else None,
        })
    return episodes


def fetch_season(session, season: int, cache: Path, refresh: bool) -> str:
    """Wikitext for one season, cached so re-runs make no network requests."""
    path = cache / f"tng_season_{season}.wikitext"
    if path.exists() and not refresh:
        return path.read_text(encoding='utf-8')

    print(f"  fetching season {season} from Wikipedia", flush=True)
    response = session.get(WIKI_URL.format(season=season), timeout=(5, 30))
    response.raise_for_status()
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text, encoding='utf-8')
    time.sleep(1)          # be polite; only ever 7 requests
    return response.text


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def create_schema(cur, rebuild: bool):
    if rebuild:
        cur.execute("DROP VIEW IF EXISTS episode_credits")
        cur.execute("DROP TABLE IF EXISTS credits")
        cur.execute("DROP TABLE IF EXISTS people")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS people (
            person_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name      TEXT NOT NULL UNIQUE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS credits (
            episode_id INTEGER NOT NULL,
            person_id  INTEGER NOT NULL,
            role       TEXT NOT NULL,
            PRIMARY KEY (episode_id, person_id, role),
            FOREIGN KEY (episode_id) REFERENCES episodes(episode_id),
            FOREIGN KEY (person_id)  REFERENCES people(person_id)
        )
    """)

    columns = {row[1] for row in cur.execute("PRAGMA table_info(episodes)")}
    for column, decl in (('original_air_date', 'TEXT'),
                         ('us_viewers_millions', 'REAL')):
        if column not in columns:
            cur.execute(f"ALTER TABLE episodes ADD COLUMN {column} {decl}")

    cur.execute("""
        CREATE VIEW IF NOT EXISTS episode_credits AS
        SELECT ep.season, ep.episode_number, ep.title,
               p.name AS person, c.role
          FROM credits c
          JOIN people p    USING(person_id)
          JOIN episodes ep USING(episode_id)
    """)


def populate(cur, episodes: list) -> tuple:
    """Insert people, credits, air dates and viewership. Returns counts."""
    by_code = dict(cur.execute(
        "SELECT site_transcript_id, episode_id FROM episodes").fetchall())

    people, credited, dated, unmatched = set(), 0, 0, []
    for episode in episodes:
        episode_ids = {by_code[c] for c in episode['codes'] if c in by_code}
        if not episode_ids:
            unmatched.append(episode['codes'])
            continue

        for episode_id in episode_ids:
            cur.execute(
                "UPDATE episodes SET original_air_date=?, us_viewers_millions=? "
                "WHERE episode_id=?",
                (episode['air_date'], episode['viewers'], episode_id))
            dated += 1
            cur.execute("DELETE FROM credits WHERE episode_id=?", (episode_id,))

            for role, name in dict.fromkeys(episode['credits']):
                cur.execute("INSERT OR IGNORE INTO people (name) VALUES (?)",
                            (name,))
                person_id = cur.execute(
                    "SELECT person_id FROM people WHERE name=?",
                    (name,)).fetchone()[0]
                cur.execute(
                    "INSERT OR IGNORE INTO credits (episode_id, person_id, role) "
                    "VALUES (?, ?, ?)", (episode_id, person_id, role))
                people.add(name)
                credited += 1

    # People whose only credits came from a removed episode.
    cur.execute("DELETE FROM people WHERE person_id NOT IN "
                "(SELECT person_id FROM credits)")
    return len(people), credited, dated, unmatched


def build(db_path: Path, cache: Path, refresh: bool, rebuild: bool) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        cur = conn.cursor()

        if not cur.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name='episodes'").fetchone()[0]:
            print("Error: no episodes table. Run build_line_counts.py first.",
                  file=sys.stderr, flush=True)
            return 1

        session = requests.Session()
        session.headers.update({'User-Agent': USER_AGENT})

        episodes = []
        for season in SEASONS:
            episodes += parse_season(fetch_season(session, season, cache, refresh))
        print(f"Parsed {len(episodes)} episodes from Wikipedia", flush=True)

        create_schema(cur, rebuild)
        n_people, n_credits, n_dated, unmatched = populate(cur, episodes)
        conn.commit()

        if unmatched:
            print(f"Warning: {len(unmatched)} Wikipedia episode(s) matched no "
                  f"production code in the database: {unmatched[:5]}",
                  file=sys.stderr, flush=True)

        print(f"People:  {n_people}", flush=True)
        print(f"Credits: {n_credits}", flush=True)
        print(f"Dated:   {n_dated} episodes", flush=True)

        print("\nMost prolific directors:", flush=True)
        for name, n in cur.execute(
                "SELECT p.name, COUNT(*) FROM credits c JOIN people p USING(person_id) "
                "WHERE c.role='director' GROUP BY p.person_id "
                "ORDER BY 2 DESC LIMIT 5"):
            print(f"  {n:3d}  {name}", flush=True)
        print("\nMost prolific writers:", flush=True)
        for name, n in cur.execute(
                "SELECT p.name, COUNT(DISTINCT c.episode_id) FROM credits c "
                "JOIN people p USING(person_id) WHERE c.role!='director' "
                "GROUP BY p.person_id ORDER BY 2 DESC LIMIT 5"):
            print(f"  {n:3d}  {name}", flush=True)
        return 0
    finally:
        conn.close()


def main():
    here = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description="Add episode credits, air dates and viewership.")
    parser.add_argument('--db-path', default=str(here / 'tng_data.db'))
    parser.add_argument('--cache', default=str(here / '.wikicache'),
                        help='Where to keep the downloaded wikitext')
    parser.add_argument('--refresh', action='store_true',
                        help='Re-fetch from Wikipedia even if cached')
    parser.add_argument('--rebuild', action='store_true',
                        help='Drop and rebuild the credits tables')
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"Error: database not found: {db_path}", file=sys.stderr, flush=True)
        return 1

    print(f"Database: {db_path}", flush=True)
    print(f"Cache:    {args.cache}", flush=True)
    print("-" * 60, flush=True)
    return build(db_path, Path(args.cache), args.refresh, args.rebuild)


if __name__ == "__main__":
    sys.exit(main())
