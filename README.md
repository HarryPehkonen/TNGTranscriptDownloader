# TNGTranscriptDownloader

Downloads transcripts of *Star Trek: The Next Generation* episodes from
[chakoteya.net](http://www.chakoteya.net/NextGen/episodes.htm) and files them by
**broadcast** season and episode.

```
Season 1/TNG_S1E01-E02.txt
Season 1/TNG_S1E03.txt
...
Season 7/TNG_S7E25-E26.txt
```

176 transcript pages cover all 178 broadcast episodes.

## Usage

```bash
pip install requests beautifulsoup4

python download_tng_transcripts.py                 # everything (101-277)
python download_tng_transcripts.py 127 148         # just season 2's page numbers
python download_tng_transcripts.py 149             # 149 through to the end
python download_tng_transcripts.py --out ./data --delay 5
```

Files already on disk are skipped, so an interrupted run resumes by simply
re-running it. `--force` re-downloads anyway. Exit status is non-zero if any
transcript failed, and the failing numbers are listed.

A full run takes about 10 minutes at the default 2-second delay.

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

The transcripts are not in this repository, and `.gitignore` excludes the
`Season */` output directories deliberately. *Star Trek* and related marks are
trademarks of Paramount Skydance Corporation; the transcripts are the work of
chakoteya.net. Download them for personal use — don't redistribute them.

Only the downloader itself is covered by this repository's LICENSE.
