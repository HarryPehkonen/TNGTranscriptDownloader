#!/usr/bin/env python3
"""
Download Star Trek: The Next Generation transcripts from chakoteya.net.

The site numbers its transcripts 101 to 277. Number 102 does not exist --
"Encounter at Farpoint" is a double episode published as 101.

Those numbers are production codes. They do NOT encode the season (season 2
starts at 127, not 201), and TNG was not broadcast in production order, so they
do not give the episode either: code 105 is "Haven", which aired as season 1
episode 11. This script maps production codes onto broadcast season/episode
numbers via EPISODE_MAP and files each transcript under
Season <n>/TNG_S<n>E<nn>.txt.

Usage:
    python download_tng_transcripts.py                 # the lot, 101-277
    python download_tng_transcripts.py 127 148         # just season 2
    python download_tng_transcripts.py 149             # 149 through to the end
    python download_tng_transcripts.py --out ./data --delay 5

Already-downloaded transcripts are skipped, so an interrupted run can simply be
re-run to pick up where it left off.
"""

import argparse
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup

BASE_URL = "http://www.chakoteya.net/NextGen"

# An honest User-Agent with contact details, so the site operator can get hold
# of you instead of just blocking an anonymous scraper.
USER_AGENT = (
    "TNG-transcript-archiver/1.0 "
    "(personal archive; harry.pehkonen@gmail.com)"
)

# The site's numbers are TNG production codes, and the show was NOT broadcast
# in production order -- "Haven" is code 105 but aired as season 1 episode 11,
# and codes 149/150 and 207/208 are each transposed relative to broadcast. So
# this has to be a lookup table, not arithmetic.
#
# Maps production code -> (season, (episodes it covers,)). Broadcast numbering
# is from Wikipedia's per-season episode lists; comments give the site's title.
EPISODE_MAP = {
    # --- Season 1 ---
    101: (1, (1, 2)),           # Encounter at Farpoint
    103: (1, (3,)),             # The Naked Now
    104: (1, (4,)),             # Code of Honour
    105: (1, (11,)),            # Haven
    106: (1, (6,)),             # Where No One Has Gone Before
    107: (1, (5,)),             # The Last Outpost
    108: (1, (7,)),             # Lonely Among Us
    109: (1, (8,)),             # Justice
    110: (1, (9,)),             # The Battle
    111: (1, (10,)),            # Hide & Q
    112: (1, (16,)),            # Too Short A Season
    113: (1, (12,)),            # The Big Goodbye
    114: (1, (13,)),            # Datalore
    115: (1, (14,)),            # Angel One
    116: (1, (15,)),            # 11001001
    117: (1, (18,)),            # Home Soil
    118: (1, (17,)),            # When The Bough Breaks
    119: (1, (19,)),            # Coming of Age
    120: (1, (20,)),            # Heart Of Glory
    121: (1, (21,)),            # The Arsenal Of Freedom
    122: (1, (23,)),            # Skin Of Evil
    123: (1, (22,)),            # Symbiosis
    124: (1, (24,)),            # We'll Always Have Paris
    125: (1, (25,)),            # Conspiracy
    126: (1, (26,)),            # The Neutral Zone
    # --- Season 2 ---
    127: (2, (1,)),             # The Child
    128: (2, (2,)),             # Where Silence Has Lease
    129: (2, (3,)),             # Elementary, Dear Data
    130: (2, (4,)),             # The Outrageous Okona
    131: (2, (6,)),             # The Schizoid Man
    132: (2, (5,)),             # Loud as a Whisper
    133: (2, (7,)),             # Unnatural Selection
    134: (2, (8,)),             # A Matter of Honour
    135: (2, (9,)),             # The Measure of a Man
    136: (2, (10,)),            # The Dauphin
    137: (2, (11,)),            # Contagion
    138: (2, (12,)),            # The Royale
    139: (2, (13,)),            # Time Squared
    140: (2, (14,)),            # The Icarus Factor
    141: (2, (15,)),            # Pen Pals
    142: (2, (16,)),            # Q Who?
    143: (2, (17,)),            # Samaritan Snare
    144: (2, (18,)),            # Up The Long Ladder
    145: (2, (19,)),            # Manhunt
    146: (2, (20,)),            # The Emissary
    147: (2, (21,)),            # Peak Performance
    148: (2, (22,)),            # Shades Of Gray
    # --- Season 3 ---
    149: (3, (2,)),             # The Ensigns of Command
    150: (3, (1,)),             # Evolution
    151: (3, (3,)),             # The Survivors
    152: (3, (4,)),             # Who Watches The Watchers
    153: (3, (5,)),             # The Bonding
    154: (3, (6,)),             # Booby Trap
    155: (3, (7,)),             # The Enemy
    156: (3, (8,)),             # The Price
    157: (3, (9,)),             # The Vengeance Factor
    158: (3, (10,)),            # The Defector
    159: (3, (11,)),            # The Hunted
    160: (3, (12,)),            # The High Ground
    161: (3, (13,)),            # Déjà Q
    162: (3, (14,)),            # A Matter Of Perspective
    163: (3, (15,)),            # Yesterday's Enterprise
    164: (3, (16,)),            # The Offspring
    165: (3, (17,)),            # Sins Of The Father
    166: (3, (18,)),            # Allegiance
    167: (3, (19,)),            # Captain's Holiday
    168: (3, (20,)),            # Tin Man
    169: (3, (21,)),            # Hollow Pursuits
    170: (3, (22,)),            # The Most Toys
    171: (3, (23,)),            # Sarek
    172: (3, (24,)),            # Ménage à Troi
    173: (3, (25,)),            # Transfigurations
    174: (3, (26,)),            # Best Of Both Worlds, part 1
    # --- Season 4 ---
    175: (4, (1,)),             # Best of Both Worlds, part 2
    176: (4, (4,)),             # Suddenly Human
    177: (4, (3,)),             # Brothers
    178: (4, (2,)),             # Family
    179: (4, (5,)),             # Remember Me
    180: (4, (6,)),             # Legacy
    181: (4, (7,)),             # Reunion
    182: (4, (8,)),             # Future Imperfect
    183: (4, (9,)),             # Final Mission
    184: (4, (10,)),            # The Loss
    185: (4, (11,)),            # Data's Day
    186: (4, (12,)),            # The Wounded
    187: (4, (13,)),            # Devil's Due
    188: (4, (14,)),            # Clues
    189: (4, (15,)),            # First Contact
    190: (4, (16,)),            # Galaxy's Child
    191: (4, (17,)),            # Night Terrors
    192: (4, (18,)),            # Identity Crisis
    193: (4, (19,)),            # The Nth Degree
    194: (4, (20,)),            # Qpid
    195: (4, (21,)),            # The Drumhead
    196: (4, (22,)),            # Half a Life
    197: (4, (23,)),            # The Host
    198: (4, (24,)),            # The Mind's Eye
    199: (4, (25,)),            # In Theory
    200: (4, (26,)),            # Redemption
    # --- Season 5 ---
    201: (5, (1,)),             # Redemption part 2
    202: (5, (2,)),             # Darmok
    203: (5, (3,)),             # Ensign Ro
    204: (5, (4,)),             # Silicon Avatar
    205: (5, (5,)),             # Disaster
    206: (5, (6,)),             # The Game
    207: (5, (8,)),             # Unification, part 2
    208: (5, (7,)),             # Unification, part 1
    209: (5, (9,)),             # A Matter Of Time
    210: (5, (10,)),            # New Ground
    211: (5, (11,)),            # Hero Worship
    212: (5, (12,)),            # Violations
    213: (5, (13,)),            # The Masterpiece Society
    214: (5, (14,)),            # Conundrum
    215: (5, (15,)),            # Power Play
    216: (5, (16,)),            # Ethics
    217: (5, (17,)),            # The Outcast
    218: (5, (18,)),            # Cause and Effect
    219: (5, (19,)),            # The First Duty
    220: (5, (20,)),            # Cost of Living
    221: (5, (21,)),            # The Perfect Mate
    222: (5, (22,)),            # Imaginary Friend
    223: (5, (23,)),            # I, Borg
    224: (5, (24,)),            # The Next Phase
    225: (5, (25,)),            # The Inner Light
    226: (5, (26,)),            # Time's Arrow, part 1
    # --- Season 6 ---
    227: (6, (1,)),             # Time's Arrow, part 2
    228: (6, (2,)),             # Realm of Fear
    229: (6, (3,)),             # Man of the People
    230: (6, (4,)),             # Relics
    231: (6, (5,)),             # Schisms
    232: (6, (6,)),             # True Q
    233: (6, (7,)),             # Rascals
    234: (6, (8,)),             # A Fistful of Datas
    235: (6, (9,)),             # The Quality of Life
    236: (6, (10,)),            # Chain of Command, part 1
    237: (6, (11,)),            # Chain of Command, part 2
    238: (6, (12,)),            # Ship in a Bottle
    239: (6, (13,)),            # Aquiel
    240: (6, (14,)),            # Face of the Enemy
    241: (6, (15,)),            # Tapestry
    242: (6, (16,)),            # Birthright, part 1
    243: (6, (17,)),            # Birthright, part 2
    244: (6, (18,)),            # Starship Mine
    245: (6, (19,)),            # Lessons
    246: (6, (20,)),            # The Chase
    247: (6, (21,)),            # Frame of Mind
    248: (6, (22,)),            # Suspicions
    249: (6, (23,)),            # Rightful Heir
    250: (6, (24,)),            # Second Chances
    251: (6, (25,)),            # Timescape
    252: (6, (26,)),            # Descent, part 1
    # --- Season 7 ---
    253: (7, (1,)),             # Descent, part 2
    254: (7, (2,)),             # Liaisons
    255: (7, (3,)),             # Interface
    256: (7, (4,)),             # Gambit, part 1
    257: (7, (5,)),             # Gambit, part 2
    258: (7, (6,)),             # Phantasms
    259: (7, (7,)),             # Dark Page
    260: (7, (8,)),             # Attached
    261: (7, (9,)),             # Force of Nature
    262: (7, (10,)),            # Inheritance
    263: (7, (11,)),            # Parallels
    264: (7, (12,)),            # The Pegasus
    265: (7, (13,)),            # Homeward
    266: (7, (14,)),            # Sub Rosa
    267: (7, (15,)),            # Lower Decks
    268: (7, (16,)),            # Thine Own Self
    269: (7, (17,)),            # Masks
    270: (7, (18,)),            # Eye of the Beholder
    271: (7, (19,)),            # Genesis
    272: (7, (20,)),            # Journey's End
    273: (7, (21,)),            # Firstborn
    274: (7, (22,)),            # Bloodlines
    275: (7, (23,)),            # Emergence
    276: (7, (24,)),            # Preemptive Strike
    277: (7, (25, 26)),         # All Good Things...
}

FIRST_NUMBER = min(EPISODE_MAP)
LAST_NUMBER = max(EPISODE_MAP)

# Never published; the second half of Farpoint is part of 101.
MISSING_NUMBERS = {102}

# Anything shorter than this is not a transcript -- it's an error page or a
# truncated read. Never write one of those to disk, because the skip-if-exists
# check would then treat it as a completed download forever.
MIN_TRANSCRIPT_CHARS = 2000

# Status codes that mean "not now" rather than "no".
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def season_episode(number):
    """Map a production code onto (season, tuple of broadcast episodes)."""
    try:
        return EPISODE_MAP[number]
    except KeyError:
        raise ValueError(
            f"{number} is not a TNG transcript number "
            f"(expected {FIRST_NUMBER}-{LAST_NUMBER})"
        ) from None


def output_filename(number):
    season, episodes = season_episode(number)
    tag = "".join(f"E{e:02d}-" for e in episodes[:-1]) + f"E{episodes[-1]:02d}"
    return f"TNG_S{season}{tag}.txt"


def episode_label(number):
    season, episodes = season_episode(number)
    if len(episodes) > 1:
        listed = "-".join(str(e) for e in episodes)
        return f"Season {season}, Episodes {listed}"
    return f"Season {season}, Episode {episodes[0]}"


def transcript_numbers(start, end):
    return [n for n in range(start, end + 1) if n not in MISSING_NUMBERS]


def build_session():
    """One session for the whole run: keep-alive means 176 requests cost the
    server one connection setup rather than 176 of them."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    return session


def retry_after_seconds(response, default):
    """Honour Retry-After when the server sends one we can parse."""
    try:
        return max(float(response.headers.get("Retry-After", "")), default)
    except ValueError:
        return default


def fetch(session, url, attempts=3):
    """GET url, backing off when the server asks us to wait.

    404s and other permanent errors are raised straight away -- retrying them
    would just be pestering.
    """
    last_error = None

    for attempt in range(attempts):
        wait = 5 * 2 ** attempt  # 5s, 10s, 20s
        try:
            response = session.get(url, timeout=(5, 30))
        except requests.exceptions.RequestException as exc:
            last_error = exc
        else:
            if response.status_code not in RETRYABLE_STATUS:
                response.raise_for_status()
                return response
            last_error = requests.exceptions.HTTPError(
                f"HTTP {response.status_code}", response=response
            )
            wait = retry_after_seconds(response, wait)

        if attempt < attempts - 1:
            print(f"    {last_error} -- retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)

    raise last_error


def strip_site_chrome(container):
    """Remove the 'back to the episode listing' link and the copyright footer,
    if they fall inside the transcript container.

    Only ever removes small blocks. Page 147 has an unterminated attribute in
    its <meta> tag, which confuses the parser into nesting the whole transcript
    inside the footer's <p>; decomposing that would throw the episode away.
    """
    limit = max(len(container.get_text()) // 5, 500)

    def drop(tag):
        if tag is None or tag.decomposed:
            return
        if len(tag.get_text()) <= limit:
            tag.decompose()

    for link in list(container.find_all("a", href="episodes.htm")):
        if not link.decomposed:
            drop(link.find_parent("p") or link)

    for paragraph in list(container.find_all("p")):
        if paragraph.decomposed:
            continue
        text = paragraph.get_text()
        if "Copyright" in text and "Paramount" in text:
            drop(paragraph)


# Marks a real line break while we still have the source's cosmetic newlines
# mixed in. Cannot occur in the page text, so it survives normalisation.
BREAK = "\x00"


def insert_line_breaks(node):
    """Mark the real line breaks -- <br> and <p> -- in place.

    This matters because the pages are hard-wrapped in the HTML source: the
    newlines already in the markup are cosmetic, and only <br> marks an actual
    line of dialogue. A plain "\\n" would be indistinguishable from those
    cosmetic newlines, which is how sentences end up chopped in half.
    """
    for br in node.find_all("br"):
        br.replace_with(BREAK)
    for paragraph in node.find_all("p"):
        paragraph.append(BREAK * 2)


def normalise(text):
    """Collapse the source's hard-wrapping, keep the marked line breaks."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split(BREAK)]

    collapsed = []
    for line in lines:
        # Keep single blank lines as scene separators, drop the runs.
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)

    return "\n".join(collapsed).strip()


def pick_container(soup):
    """The transcript lives in the biggest table cell on the page."""
    cells = soup.find_all("td")
    if cells:
        biggest = max(cells, key=lambda cell: len(cell.get_text()))
        if len(biggest.get_text(strip=True)) >= MIN_TRANSCRIPT_CHARS:
            return biggest
    # Layout changed, or there is no table: fall back to the whole page.
    return soup.body or soup


def page_title(soup):
    """The episode title, from <title> if usable, else the page heading.

    Page 147's unterminated <meta> attribute swallows its <title> tag, so fall
    back to the large coloured heading the site puts above every transcript.
    """
    if soup.title and soup.title.string:
        # The <title> is hard-wrapped too, so collapse it before trimming the
        # site's "... Transcripts - " prefix.
        collapsed = re.sub(r"\s+", " ", soup.title.string).strip()
        title = re.sub(r"^.*Transcripts\s*-\s*", "", collapsed)
        if title:
            return title

    heading = soup.find("font", size="5")
    if heading:
        return re.sub(r"\s+", " ", heading.get_text()).strip()
    return ""


def find_field(text, label):
    match = re.search(rf"{label}\s*:\s*(.+)", text)
    return match.group(1).strip() if match else ""


def extract_transcript(html_bytes):
    """Pull title, stardate, airdate and dialogue out of an episode page.

    Raises ValueError if the page doesn't look like a transcript.
    """
    soup = BeautifulSoup(html_bytes, "html.parser")

    title = page_title(soup)

    # Choose the container before stripping anything, so a malformed page that
    # nests the transcript inside the footer can't lose it.
    container = pick_container(soup)
    strip_site_chrome(container)
    insert_line_breaks(soup)

    page_text = normalise(soup.get_text())
    body = normalise(container.get_text())

    if len(body) < MIN_TRANSCRIPT_CHARS:
        raise ValueError(
            f"page yielded only {len(body)} characters -- not a transcript"
        )

    return {
        "title": title,
        "stardate": find_field(page_text, "Stardate"),
        "airdate": find_field(page_text, "Original Airdate"),
        "body": body,
    }


def render(number, url, data):
    """Build the file contents: metadata header, then the transcript."""
    heading = data["title"] or f"Episode {number}"
    lines = [
        f"Star Trek: The Next Generation - {heading}",
        f"{episode_label(number)} (site transcript {number})",
    ]
    if data["stardate"]:
        lines.append(f"Stardate: {data['stardate']}")
    if data["airdate"]:
        lines.append(f"Original Airdate: {data['airdate']}")
    lines += [
        f"Source: {url}",
        f"Retrieved: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 60,
        "",
        "",
    ]
    return "\n".join(lines) + data["body"] + "\n"


def write_atomically(filepath, text):
    """Write via a temp file, so an interrupted run never leaves a partial
    transcript behind for the next run to mistake for a finished one."""
    partial = filepath + ".part"
    with open(partial, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(partial, filepath)


def download_transcript(session, number, out_dir, force=False):
    """Fetch and save one transcript. Returns 'saved', 'skipped' or 'failed'."""
    season, _ = season_episode(number)
    season_dir = os.path.join(out_dir, f"Season {season}")
    filepath = os.path.join(season_dir, output_filename(number))
    relative = os.path.relpath(filepath, out_dir)

    if os.path.exists(filepath) and not force:
        print(f"{number}: already have {relative}", flush=True)
        return "skipped"

    url = f"{BASE_URL}/{number}.htm"
    print(f"{number}: fetching {url}", flush=True)

    try:
        response = fetch(session, url)
        data = extract_transcript(response.content)
    except (requests.exceptions.RequestException, ValueError) as exc:
        print(f"    failed: {exc}", flush=True)
        return "failed"

    os.makedirs(season_dir, exist_ok=True)
    write_atomically(filepath, render(number, url, data))
    print(f"    saved {relative}  ({data['title'] or 'untitled'})", flush=True)
    return "saved"


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "start", nargs="?", type=int, default=FIRST_NUMBER,
        help=f"first transcript number (default {FIRST_NUMBER})",
    )
    parser.add_argument(
        "end", nargs="?", type=int, default=None,
        help=f"last transcript number (default {LAST_NUMBER})",
    )
    parser.add_argument(
        "--out", default=os.path.dirname(os.path.abspath(__file__)),
        help="output directory (default: alongside this script)",
    )
    parser.add_argument(
        "--delay", type=float, default=2.0,
        help="seconds to wait between requests (default 2)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="re-download transcripts that are already on disk",
    )

    args = parser.parse_args()
    if args.end is None:
        args.end = LAST_NUMBER

    if not FIRST_NUMBER <= args.start <= LAST_NUMBER:
        parser.error(f"start must be between {FIRST_NUMBER} and {LAST_NUMBER}")
    if not FIRST_NUMBER <= args.end <= LAST_NUMBER:
        parser.error(f"end must be between {FIRST_NUMBER} and {LAST_NUMBER}")
    if args.end < args.start:
        parser.error("end must be >= start")
    if args.delay < 0:
        parser.error("delay must not be negative")

    return args


def main():
    args = parse_args()
    numbers = transcript_numbers(args.start, args.end)

    os.makedirs(args.out, exist_ok=True)
    print(f"Downloading {len(numbers)} transcripts ({args.start}-{args.end})", flush=True)
    print(f"Saving to: {args.out}", flush=True)
    print(f"Throttle:  {args.delay}s between requests", flush=True)
    print("-" * 60, flush=True)

    session = build_session()
    counts = {"saved": 0, "skipped": 0, "failed": 0}
    failures = []

    try:
        for index, number in enumerate(numbers):
            result = download_transcript(session, number, args.out, args.force)
            counts[result] += 1
            if result == "failed":
                failures.append(number)

            # Only pause when we actually touched the server. A resumed run
            # over cached files shouldn't spend minutes sleeping for nothing.
            if result != "skipped" and index < len(numbers) - 1:
                time.sleep(args.delay)
    except KeyboardInterrupt:
        print("\nInterrupted -- re-run to resume.", flush=True)

    print("-" * 60, flush=True)
    print(f"Saved:   {counts['saved']}", flush=True)
    print(f"Skipped: {counts['skipped']} (already on disk)", flush=True)
    print(f"Failed:  {counts['failed']}", flush=True)

    if failures:
        print("\nFailed transcripts: " + " ".join(str(n) for n in failures))
        print("Re-run the script to retry them.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
