# AGENTS.md

Machine-oriented notes. Human-facing docs are in `README.md`.

Scrapes Star Trek: TNG transcripts from chakoteya.net, files them by broadcast
season/episode, builds a SQLite database of per-episode line counts and keyword
counts.

## Setup

```
pip install requests beautifulsoup4
```

- `beautifulsoup4` imports as `bs4`. Pip name != import name. A dependency
  check on `import beautifulsoup4` always fails; check `import bs4`.
- Only two third-party deps: `requests`, `beautifulsoup4`.
- PyYAML was removed deliberately. Do not reintroduce it.

## Commands

| Command | Effect |
|---|---|
| `./build_all.sh` | Full pipeline: download → line counts → keyword counts |
| `./build_all.sh --rebuild` | Same, dropping tables first |
| `python download_tng_transcripts.py [start] [end]` | Fetch pages 101–277 |
| `python build_line_counts.py` | Populate `episodes`/`characters`/`line_counts` |
| `python build_keywords.py` | Populate keyword tables (needs stage 2 first) |

All steps idempotent. Re-run to resume. Exit 0 on success, 1 on any failure.

## Files

| File | Role |
|---|---|
| `download_tng_transcripts.py` | Scraper. `EPISODE_MAP` = prod code → (season, episodes) |
| `build_line_counts.py` | Dialogue parser. Exports `SPEAKER_RE`, `transcript_body` |
| `keywords.py` | Taxonomy data. `CATEGORIES`, `TERMS`, `Term`, `starbase_terms()` |
| `build_keywords.py` | Keyword counter. Imports from the two above |
| `build_all.sh` | Orchestrator |

`Term` fields: `canonical`, `variants`, `categories`, `tier`, `case_sensitive`,
`needs_context`, `not_followed_by`.

## Invariants

| Fact | Value |
|---|---|
| Transcript files | 176 |
| Broadcast episodes | 178 |
| `episodes` rows | 176 |
| `episode_slots` / `episode_index` rows | 178 |
| Dialogue lines | 63,459 |
| Distinct speakers | 784 |
| Keyword terms / categories | 303 / 21 |
| Keyword occurrences | 12,161 |

If a change moves these, it is a regression unless intended.

## Traps

**Page numbers are production codes.** 101–277, continuous across the series.
Not season/episode. Season 2 starts at 127, not 201.

**TNG did not air in production order.** No formula converts a production code
to a broadcast episode. Use `EPISODE_MAP`. Code 105 = S1E11 ("Haven"), 149/150
and 207/208 are transposed, season 1 is heavily reordered.

**102 does not exist** (HTTP 404). 101 and 277 are double episodes. Hence 176
files for 178 episodes.

**`episodes` has 176 rows, not 178.** S1E02 and S7E26 are not rows. Join
`episode_slots` or `episode_index` for per-broadcast-episode queries.

**Categories are many-to-many.** A term may hold several. Do not assume one.

| Term | Categories |
|---|---|
| `Vulcan` | `place`, `race` |
| `Kesprytt` | `place`, `race` |
| `Romulan` | `race`, `romulan` |
| `cloaking device` | `klingon`, `romulan` |
| `Khitomer` | `klingon`, `romulan` |

`keywords.canonical` is UNIQUE. Duplicate canonicals are merged by
`validate_taxonomy()` — unioning categories/variants. Without that merge the
last entry wins and the others' categories are lost silently.

**Never use prefix/suffix wildcards in term matching.** `targ\w*` matches
target/targets/targeting: 5 real hits become 92 across 51 episodes. Whole words
only.

**Case is load-bearing.** `Data` 2,877 vs `data` 97. `Lore` 113 vs `lore` 0.
Default `case_sensitive=True`. Tech terms set it False.

**British spellings.** `Traveller` 36, `Traveler` 0. `energise`, not `energize`.

**Starbase designations are read digit by digit.** "Starbase five one five" =
515. There is no Starbase 5. 67 distinct starbases. Short designations are
prefixes of long ones, so every starbase term needs `not_followed_by`, and bare
`Starbase` is guarded inversely. Invariant: 196 mentions = 63 bare + 133
designated.

**`RIKER 2` / `PICARD 2` are distinct characters**, not typos. Duplicates from
"Second Chances", "We'll Always Have Paris", "Allegiance". Do not strip digits
from speaker names.

**Speaker labels are not one uppercase word.** Must match single characters
(`Q:` — 560 lines) and multi-word labels (`GUL EVEK:`, `PICARD JR:`). A
`^[A-Z][A-Z'-]+:` pattern drops 878 lines across 26 labels.

**Header boundary is `'=' * 60`.** Use `transcript_body()`. Do not filter header
lines by prefix matching.

**Source HTML is hard-wrapped.** Only `<br>` is a real line break; newlines in
the markup are cosmetic. Splitting on them chops sentences. Do not split on
double spaces either.

**Page 147 is malformed** — unterminated `<meta>` attribute swallows `<title>`
and nests the transcript inside the copyright footer. Select the container
before stripping chrome; never remove a block larger than 1/5 of the container.

**`INSERT OR REPLACE` breaks foreign keys.** It deletes the row and reinserts
with a new AUTOINCREMENT id, orphaning children and tripping
`foreign_keys=ON`. Use `ON CONFLICT (...) DO UPDATE`.

**`--rebuild` must drop dependents first.** `build_line_counts.py` discovers
them via `PRAGMA foreign_key_list` rather than hardcoding names. Adding a table
with an FK into `episodes`/`characters`/`seasons` requires no change there.

**`print()` needs `flush=True`.** Stdout is block-buffered when redirected;
without it, progress is invisible and stderr interleaves out of order.

## Rules

- **Do not commit `tng_data.db` or `Season */`.** Gitignored. Transcripts are
  chakoteya.net's work, Paramount's copyright, personal use only.
- **Be gentle with chakoteya.net.** 2 s between requests minimum, one shared
  `requests.Session`, honest User-Agent, back off on 429/5xx and honour
  `Retry-After`, fail fast on 404. Do not bulk re-fetch what is on disk.
- `robots.txt` allows `/NextGen/`, disallows several AI crawlers.
- Change the contact address in `USER_AGENT` before running as someone else.

## Verifying a change

```sql
PRAGMA foreign_key_check;                     -- must return nothing
SELECT COUNT(*) FROM episode_slots;           -- 178
SELECT SUM(line_count) FROM line_counts;      -- 63459
SELECT SUM(occurrences) FROM keyword_counts;  -- 12161
```

Cross-check keyword counts against the transcripts directly rather than
trusting the database; that is how the `targ` and starbase errors surfaced.
