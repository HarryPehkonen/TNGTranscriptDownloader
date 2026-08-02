# TNGTranscriptDownloader

Downloads transcripts of *Star Trek: The Next Generation* episodes from
[chakoteya.net](http://www.chakoteya.net/NextGen/episodes.htm), files them by
**broadcast** season and episode, and builds a SQLite database of how many
lines each character speaks in each episode.

```
Season 1/TNG_S1E01-E02.txt
Season 1/TNG_S1E03.txt
...
Season 7/TNG_S7E25-E26.txt
tng_data.db
```

176 transcript pages cover all 178 broadcast episodes and 63,459 lines of
dialogue from 784 distinct speakers.

## Quick start

```bash
pip install requests beautifulsoup4
./build_all.sh
```

That's the whole pipeline. It takes about 10 minutes the first time, almost
all of it waiting politely between HTTP requests.

Both stages are safe to re-run. Transcripts already on disk are skipped and the
database is upserted, so if a run is interrupted — or a download fails — just
run `./build_all.sh` again and it picks up where it left off.

```
./build_all.sh --help

  --delay SECONDS   Seconds to wait between HTTP requests (default: 2)
  --out DIR         Where the "Season N" transcript directories live
  --db PATH         SQLite database path (default: ./tng_data.db)
  --rebuild         Drop and rebuild the database tables from scratch
```

## The two stages

### 1. `download_tng_transcripts.py`

```bash
python download_tng_transcripts.py                 # everything (101-277)
python download_tng_transcripts.py 127 148         # just season 2's page numbers
python download_tng_transcripts.py 149             # 149 through to the end
python download_tng_transcripts.py --out ./data --delay 5
```

Files already on disk are skipped; `--force` re-downloads anyway. Exit status is
non-zero if any transcript failed, and the failing numbers are listed.

### 2. `build_line_counts.py`

```bash
python build_line_counts.py                        # parse and upsert
python build_line_counts.py --rebuild              # start the tables over
python build_line_counts.py --transcripts-dir ./data --db-path ./tng.db
```

Schema:

| Table | Columns |
|---|---|
| `seasons` | `season_number` |
| `episodes` | `episode_id`, `season`, `episode_number`, `episode_end`, `title`, `site_transcript_id`, `filename` |
| `characters` | `character_id`, `character_name` |
| `line_counts` | `episode_id`, `character_id`, `line_count` |
| `episode_slots` | *view* — one row per broadcast episode |

Example:

```sql
-- Who speaks most across the series?
SELECT character_name, SUM(line_count) AS lines
  FROM line_counts JOIN characters USING(character_id)
 GROUP BY character_name ORDER BY lines DESC LIMIT 10;

-- Picard's lines per season
SELECT e.season, SUM(lc.line_count) AS lines
  FROM line_counts lc
  JOIN characters c USING(character_id)
  JOIN episodes   e USING(episode_id)
 WHERE c.character_name = 'PICARD'
 GROUP BY e.season ORDER BY e.season;
```

Use the `episode_slots` view rather than `episodes` whenever you need a row per
broadcast episode — see [Two pages cover two episodes each](#two-pages-cover-two-episodes-each).

## Gotchas

Everything below was discovered the hard way. They are recorded here because
each one silently produces plausible-looking but wrong output.

### The page numbers are production codes, not season/episode

The site numbers its pages 101 to 277. It is tempting to read `103` as "season
1, episode 3" and `205` as "season 2, episode 5". **Both readings are wrong.**

Those numbers are TNG *production codes*. They run continuously across the whole
series rather than restarting each season:

| Season | Production codes |
|---|---|
| 1 | 101–126 |
| 2 | 127–148 |
| 3 | 149–174 |
| 4 | 175–200 |
| 5 | 201–226 |
| 6 | 227–252 |
| 7 | 253–277 |

So season 2 begins at 127, not 201. Treating the first digit as the season
number produces nonsense as soon as you pass 126 — code 127 becomes "S1E27",
and code 200 becomes "S2E00".

### TNG was not broadcast in production order

Fixing the above with arithmetic (`episode = code - season_start + 1`) is *still*
wrong, because episodes did not air in the order they were produced. Season 1 is
reordered heavily, and several later pairs are transposed:

| Code | Site's position | Actually aired as | Title |
|---|---|---|---|
| 105 | 5th of season 1 | **S1E11** | Haven |
| 107 | 7th | **S1E05** | The Last Outpost |
| 112 | 12th | **S1E16** | Too Short A Season |
| 117 / 118 | 17th / 18th | **S1E18 / S1E17** | swapped |
| 122 / 123 | 22nd / 23rd | **S1E23 / S1E22** | swapped |
| 131 / 132 | 5th / 6th of season 2 | **S2E06 / S2E05** | swapped |
| 149 / 150 | 1st / 2nd of season 3 | **S3E02 / S3E01** | swapped |
| 176–178 | 2nd–4th of season 4 | **S4E04 / S4E03 / S4E02** | reordered |
| 207 / 208 | 7th / 8th of season 5 | **S5E08 / S5E07** | swapped |

The 207/208 case is visible on the site itself: it lists "Unification, part 2"
*before* "Unification, part 1".

Because no formula can recover broadcast order from a production code, the
script carries an explicit `EPISODE_MAP` lookup table (production code →
season + broadcast episode), built from Wikipedia's per-season episode lists and
annotated with each title. It is validated at import-time scale: 176 codes map to
178 episodes, every season contiguous from E01, no episode claimed twice.

If you would rather file by production code — which is what the site actually
publishes, and is unambiguous — change `output_filename()`.

### Page 102 does not exist

"Encounter at Farpoint" is a feature-length double episode published as page
**101**, and 102 was never used. Requesting it returns a genuine HTTP 404.

### Two pages cover two episodes each

101 ("Encounter at Farpoint", S1E01–02) and 277 ("All Good Things...",
S7E25–26). These are named `TNG_S1E01-E02.txt` and `TNG_S7E25-E26.txt`, and are
roughly twice the size of a normal transcript.

This matters downstream: there are 176 transcripts but 178 broadcast episodes,
so a naive `episodes` table has no S1E02 and no S7E26, and any join over a
complete episode list silently drops them. `episodes.episode_end` records the
range each transcript covers, and the `episode_slots` view expands it:

```sql
SELECT ep.title FROM episode_slots sl JOIN episodes ep USING(episode_id)
 WHERE sl.season = 1 AND sl.episode_number = 2;   -- Encounter at Farpoint
```

### Page 147 is malformed HTML

`147.htm` ("Peak Performance") has an unterminated attribute in its `<meta>` tag:

```html
<meta http-equiv="keywords" content="Star Trek, ... ,zakdorn, strategema, ferengi>
```

The missing closing quote makes the parser swallow markup until it finds the next
quote character. Two consequences:

- The page's `<title>` is consumed into the attribute, so `soup.title` is `None`.
  The script falls back to the `<font size="5">` heading above each transcript.
- The document nests the entire transcript *inside* the copyright footer's
  `<p>`. Naively stripping that footer therefore deletes the whole episode. The
  script now selects the transcript container **first** and refuses to remove any
  block larger than a fifth of it.

### The HTML is hard-wrapped, so newlines are meaningless

The source wraps at roughly 70 characters. Those newlines are cosmetic — only
`<br>` marks an actual line of dialogue. Splitting on the newlines already
present in the markup chops sentences in half mid-clause.

Similarly, splitting on runs of two spaces (a tempting way to clean up
`get_text()` output) breaks titles and stardates apart.

The script marks real breaks (`<br>`, `<p>`) with a sentinel character, collapses
all remaining whitespace, then converts the sentinels back to newlines.

### The transcript is in a table cell, not a `<pre>`

Each page keeps its dialogue in the single largest `<td>`. There are no `<pre>`
tags, so a "find the biggest `<pre>`" heuristic silently falls through to
scraping the entire page — including navigation and the copyright footer.

### A bad save is worse than a failed one

Combining "skip if the file already exists" with "write before validating" means
any junk written once is treated as complete forever. The script validates that
extraction yielded at least 2 KB before writing, and writes through a `.part`
file plus an atomic rename, so an interrupted run never leaves a partial file
that the next run mistakes for a finished one.

## Gotchas when parsing the transcripts

These bite the second stage rather than the download, and each one produces a
database that looks entirely reasonable until you check it against the files.

### Speaker labels are not one uppercase word

The obvious pattern — `^[A-Z][A-Z'-]+:` — is wrong twice over, and drops 878
lines (1.4% of the dialogue) across 26 labels:

- **It needs two characters.** `Q:` never matches, so Q vanishes entirely
  despite speaking **560 lines**. He is the ninth most prolific speaker in the
  series and the single largest omission this causes.
- **It only matches one word.** `GUL EVEK`, `PICARD JR`, `RO JR`, `SIR GUY`,
  `ONE ZERO` and a dozen others are silently skipped.

A label is one or more ALL-CAPS words, optionally followed by a numeric suffix,
a bracketed annotation (`[OC]`, `[on viewscreen]`) and/or a parenthetical.
Verified: the current pattern matches **63,459 of 63,459** candidate lines, with
no false positives.

### Numbered speakers are separate characters

`RIKER 2` appears only in "Second Chances"; `PICARD 2` only in "We'll Always
Have Paris" and "Allegiance". In each case the transcript is labelling a genuine
duplicate of the character, not a transcription artefact. Stripping the digits
would merge two different people, so the suffix is kept:

| Character | Lines | | Character | Lines |
|---|---|---|---|---|
| `PICARD` | 12,322 | | `PICARD 2` | 64 |
| `RIKER` | 7,402 | | `RIKER 2` | 98 |

Aggregate them in a query if you want the combined total.

### Find the header by its separator, not by prefix matching

Each transcript begins with a metadata header. Filtering it out by testing
whether lines start with `Stardate`, `Source`, `Retrieved` and so on works until
it doesn't. The files already contain an explicit `======` rule, so split on
that instead.

### `INSERT OR REPLACE` breaks foreign keys

`episodes` has an `AUTOINCREMENT` primary key and a separate `UNIQUE (season,
episode_number)`. SQLite resolves an `INSERT OR REPLACE` conflict by **deleting**
the conflicting row and inserting a new one with a *new* `episode_id`. With
`PRAGMA foreign_keys=ON` and `line_counts` referencing it, the second run of the
script dies with `FOREIGN KEY constraint failed`; without the pragma it would
quietly orphan every line count instead.

Use `INSERT ... ON CONFLICT (...) DO UPDATE`, which updates in place and keeps
`episode_id` stable.

## Being polite to the server

chakoteya.net is a long-running fan-maintained site. The script:

- waits 2 seconds between requests (`--delay` to increase), and **only** after
  requests that actually happened — a resumed run over cached files makes no
  requests and does no sleeping;
- reuses one `requests.Session`, so a full run costs the server one connection
  rather than 176;
- backs off on 429/500/502/503/504 and honours `Retry-After`, while failing fast
  on 404 and other permanent errors;
- sends an honest `User-Agent` with contact details rather than impersonating
  Chrome.

`robots.txt` permits `/NextGen/` for all agents, though it does disallow several
AI crawlers. Please keep the delay reasonable. **Change the contact address in
`USER_AGENT` to your own before running this.**

## Copyright

The transcripts are not in this repository. `.gitignore` deliberately excludes
both the `Season */` output directories and `tng_data.db`, the latter because it
is a build artifact reproducible from the transcripts and because it embeds
transcript-derived data.

*Star Trek* and related marks are trademarks of Paramount Skydance Corporation;
the transcripts are the work of chakoteya.net. Download them for personal use —
don't redistribute them.

Only the scripts themselves are covered by this repository's LICENSE.
