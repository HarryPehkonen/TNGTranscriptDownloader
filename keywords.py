"""
Keyword taxonomy for TNG transcript analysis.

Data, not logic: build_keywords.py imports CATEGORIES and TERMS from here and
does the counting. Add or re-bucket a term below and re-run; nothing in the
parser needs touching.

Counts in the comments are measured over all 176 transcripts, dialogue only
(header, scene directions and speaker labels stripped): <uses>/<episodes>.

Matching rules:
  - Whole words only. NEVER prefix/suffix wildcards: matching "targ*" catches
    target/targets/targeting and inflates 5 real hits to 92 across 51 episodes.
  - case_sensitive defaults to True. "Data" (2877) vs "data" (97) and "Lore"
    (113) vs "lore" (0) separate cleanly on capitalisation alone. Ship names
    that are also English words -- Drake, Phoenix, Cairo -- have zero lowercase
    uses, so case is sufficient for them too.
  - Tech terms are case-insensitive; they appear mid-sentence in lower case.
  - The transcripts use British spellings: "Traveller" 36, "Traveler" 0;
    "energise", not "energize". Variants list both forms where it matters.
  - needs_context: the term must follow USS/the/Starship. Only "Victory"
    needs this (10 capitalised uses vs 15 as a common noun).
  - not_followed_by: a negative lookahead. Starbase designations need it
    because short ones are prefixes of long ones -- without the guard,
    "Starbase One" would also fire inside "Starbase One Three Three".

tier: "marker"   = few episodes; indicates an episode is ABOUT this.
      "ambience" = everywhere; good for trends, useless for selection.

A term may belong to several categories: a cloaking device is Klingon AND
Romulan, and Khitomer is both, being a Romulan attack on a Klingon outpost.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    """One countable term and how to match it."""
    canonical: str
    variants: tuple
    categories: tuple
    tier: str = "marker"
    case_sensitive: bool = True
    needs_context: bool = False
    not_followed_by: str = ""


# category key -> (human label, kind)
CATEGORIES = {
    'klingon': ('Klingon', 'faction'),
    'romulan': ('Romulan', 'faction'),
    'borg': ('Borg', 'faction'),
    'ferengi': ('Ferengi', 'faction'),
    'cardassian': ('Cardassian', 'faction'),
    'android': ('Android / Soong-type', 'theme'),
    'race': ('Race or species', 'race'),
    'ship': ('Starship', 'ship'),
    'place': ('Location', 'place'),
    'character': ('Recurring character', 'character'),
    'warp': ('Warp & propulsion', 'technology'),
    'physics': ('Physics & technobabble', 'technology'),
    'transporter': ('Transporter', 'technology'),
    'holodeck': ('Holodeck', 'technology'),
    'weapons': ('Weapons & tactical', 'technology'),
    'federation': ('Federation & law', 'technology'),
    'klingon_culture': ('Klingon culture', 'technology'),
    'romulan_power': ('Romulan power', 'technology'),
    'borg_concepts': ('Borg concepts', 'technology'),
    'ferengi_culture': ('Ferengi culture', 'technology'),
    'cardassian_power': ('Cardassian power', 'technology'),
}

# Number words TNG uses when reading a starbase designation aloud. The show
# says them digit by digit: "Starbase five one five" is Starbase 515.
_NUMBER_WORD = (
    r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
    r"|zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve"
    r"|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
)

# A designation continues if another number word follows, so every starbase
# term is guarded against matching a truncated version of a longer one.
_MORE_DIGITS = r"[\s-]+" + _NUMBER_WORD

# Discovered from the transcripts rather than typed out. Numbers stay as
# words and numerals stay as numerals, matching how each is spoken.
STARBASE_DESIGNATIONS = (
    'Five One Five',                  # 12
    'One Three Three',                # 10
    'Montgomery',                     # 9
    '74',                             # 7
    'Twelve',                         # 7
    'Four One Six',                   # 5
    'One Seven Nine',                 # 5
    'Twenty Three',                   # 3
    'Two Thirty Four',                # 3
    'Earhart',                        # 2
    'Eighty Four',                    # 2
    'One Five Three',                 # 2
    'One One Two',                    # 2
    'One Seventy Three',              # 2
    'Seventy Three',                  # 2
    'Sixty Seven',                    # 2
    'Twenty Four',                    # 2
    'Two Four Seven',                 # 2
    'Two Nineteen',                   # 2
    'Two One One',                    # 2
    'Two Twelve',                     # 2
    'Two Twenty',                     # 2
    'Two Twenty Seven',               # 2
    '718',                            # 1
    'Eighty Seven',                   # 1
    'Eighty Three',                   # 1
    'Eighty Two',                     # 1
    'Fifty Five',                     # 1
    'Five One Four',                  # 1
    'Forty Seven',                    # 1
    'Four Forty',                     # 1
    'Four Nine Five',                 # 1
    'Four Ten',                       # 1
    'Fourteen',                       # 1
    'G6',                             # 1
    'Lya Three',                      # 1
    'Nine',                           # 1
    'Ninety Seven',                   # 1
    'One',                            # 1
    'One Eight Five',                 # 1
    'One Eighteen',                   # 1
    'One Five Seven',                 # 1
    'One Five Two',                   # 1
    'One One Seven',                  # 1
    'One Seven Three',                # 1
    'One Two Nine',                   # 1
    'One Two One',                    # 1
    'One Two Three',                  # 1
    'One Zero Three',                 # 1
    'Seven Three',                    # 1
    'Six',                            # 1
    'Six Two One',                    # 1
    'Thirty Nine',                    # 1
    'Thirty Six',                     # 1
    'Three Four Three',               # 1
    'Three One Three',                # 1
    'Three One Zero',                 # 1
    'Three Three Six',                # 1
    'Three Twenty Eight',             # 1
    'Three Two Four',                 # 1
    'Three Zero One',                 # 1
    'Twenty Nine',                    # 1
    'Two Eighteen',                   # 1
    'Two Nine Five',                  # 1
    'Two One Four',                   # 1
    'Two Sixty',                      # 1
    'Two Three One',                  # 1
)


def starbase_terms():
    """One place term per named or numbered starbase."""
    return [
        Term(canonical=f"Starbase {d}",
             variants=(f"Starbase {d}",),
             categories=("place",),
             case_sensitive=False,
             not_followed_by=_MORE_DIGITS)
        for d in STARBASE_DESIGNATIONS
    ]


TERMS = [
    Term('Klingon', ('Klingon', 'Klingons'), ('klingon', 'race'), tier='ambience'),
    Term('Romulan', ('Romulan', 'Romulans'), ('race', 'romulan')),
    Term('Borg', ('Borg', 'Borgs'), ('borg', 'race')),
    Term('Ferengi', ('Ferengi', 'Ferengis'), ('ferengi', 'race')),
    Term('Cardassian', ('Cardassian', 'Cardassians'), ('cardassian', 'race')),
    Term('Bajoran', ('Bajoran', 'Bajorans'), ('cardassian', 'race')),
    Term('Vulcan', ('Vulcan', 'Vulcans'), ('place', 'race')),
    Term('Betazoid', ('Betazoid', 'Betazoids'), ('race',)),
    Term('Sheliak', ('Sheliak', 'Sheliaks'), ('race',)),
    Term('Traveller', ('Traveller', 'Travellers'), ('race',)),
    Term('Tamarian', ('Tamarian', 'Tamarians'), ('race',)),
    Term('Talarian', ('Talarian', 'Talarians'), ('race',)),
    Term('Nausicaan', ('Nausicaan', 'Nausicaans'), ('race',)),
    Term('Bynar', ('Bynar', 'Bynars'), ('race',)),
    Term('Yridian', ('Yridian', 'Yridians'), ('race',)),
    Term('Gatherer', ('Gatherer', 'Gatherers'), ('race',)),
    Term('Ullian', ('Ullian', 'Ullians'), ('race',)),
    Term('Boraalan', ('Boraalan', 'Boraalans'), ('race',)),
    Term('Ornaran', ('Ornaran', 'Ornarans'), ('race',)),
    Term('Lysian', ('Lysian', 'Lysians'), ('race',)),
    Term('Pakled', ('Pakled', 'Pakleds'), ('race',)),
    Term('Ventaxian', ('Ventaxian', 'Ventaxians'), ('race',)),
    Term('Mintakan', ('Mintakan', 'Mintakans'), ('race',)),
    Term('Legaran', ('Legaran', 'Legarans'), ('race',)),
    Term('Iconian', ('Iconian', 'Iconians'), ('race',)),
    Term('Edo', ('Edo', 'Edos'), ('race',)),
    Term('Aldean', ('Aldean', 'Aldeans'), ('race',)),
    Term('Tarellian', ('Tarellian', 'Tarellians'), ('race',)),
    Term('Cairn', ('Cairn', 'Cairns'), ('race',)),
    Term('Angosian', ('Angosian', 'Angosians'), ('race',)),
    Term('Barzan', ('Barzan', 'Barzans'), ('race',)),
    Term('Ansata', ('Ansata', 'Ansatas'), ('race',)),
    Term('Acamarian', ('Acamarian', 'Acamarians'), ('race',)),
    Term('Zalkonian', ('Zalkonian', 'Zalkonians'), ('race',)),
    Term('Chrysalian', ('Chrysalian', 'Chrysalians'), ('race',)),
    Term('Kriosian', ('Kriosian', 'Kriosians'), ('race',)),
    Term('Selay', ('Selay', 'Selays'), ('race',)),
    Term('Kaelon', ('Kaelon', 'Kaelons'), ('race',)),
    Term('Antican', ('Antican', 'Anticans'), ('race',)),
    Term('Andorian', ('Andorian', 'Andorians'), ('race',)),
    Term('Rutian', ('Rutian', 'Rutians'), ('race',)),
    Term('Paxan', ('Paxan', 'Paxans'), ('race',)),
    Term('Jaradan', ('Jaradan', 'Jaradans'), ('race',)),
    Term('Brekkian', ('Brekkian', 'Brekkians'), ('race',)),
    Term('Bandi', ('Bandi', 'Bandis'), ('race',)),
    Term('Antedean', ('Antedean', 'Antedeans'), ('race',)),
    Term('Jarada', ('Jarada', 'Jaradas'), ('race',)),
    Term('Trill', ('Trill', 'Trills'), ('race',)),
    Term('Promellian', ('Promellian', 'Promellians'), ('race',)),
    Term('Bolian', ('Bolian', 'Bolians'), ('race',)),
    Term('Zakdorn', ('Zakdorn', 'Zakdorns'), ('race',)),
    Term('Ligonian', ('Ligonian', 'Ligonians'), ('race',)),
    Term('Caldonian', ('Caldonian', 'Caldonians'), ('race',)),
    Term('Ktarian', ('Ktarian', 'Ktarians'), ('race',)),
    Term('Benzite', ('Benzite', 'Benzites'), ('race',)),
    Term('Barolian', ('Barolian', 'Barolians'), ('race',)),
    Term('Vorgon', ('Vorgon', 'Vorgons'), ('race',)),
    Term('Tanugan', ('Tanugan', 'Tanugans'), ('race',)),
    Term('Mizarian', ('Mizarian', 'Mizarians'), ('race',)),
    Term('Husnock', ('Husnock', 'Husnocks'), ('race',)),
    Term('Breen', ('Breen', 'Breens'), ('race',)),
    Term('Menthar', ('Menthar', 'Menthars'), ('race',)),
    Term('Moropa', ('Moropa', 'Moropas'), ('race',)),
    Term('Kesprytt', ('Kesprytt', 'Kesprytts'), ('place', 'race')),
    Term('Hekaran', ('Hekaran', 'Hekarans'), ('race',)),
    Term('Cytherian', ('Cytherian', 'Cytherians'), ('race',)),
    Term('Tholian', ('Tholian', 'Tholians'), ('race',)),
    Term('Satarran', ('Satarran', 'Satarrans'), ('race',)),
    Term('Napean', ('Napean', 'Napeans'), ('race',)),
    Term('Malcorian', ('Malcorian', 'Malcorians'), ('race',)),
    Term('Iyaaran', ('Iyaaran', 'Iyaarans'), ('race',)),
    Term('Chalnoth', ('Chalnoth', 'Chalnoths'), ('race',)),
    Term('Melthusian', ('Melthusian', 'Melthusians'), ('race',)),
    Term('Douwd', ('Douwd', 'Douwds'), ('race',)),
    Term('Devidian', ('Devidian', 'Devidians'), ('race',)),
    Term('Stargazer', ('Stargazer',), ('ship',)),
    Term('Yamato', ('Yamato',), ('ship',)),
    Term('Lantree', ('Lantree',), ('ship',)),
    Term('Phoenix', ('Phoenix',), ('ship',)),
    Term('Pegasus', ('Pegasus',), ('ship',)),
    Term('Hood', ('Hood',), ('ship',)),
    Term('Hathaway', ('Hathaway',), ('ship',)),
    Term('Tsiolkovsky', ('Tsiolkovsky',), ('ship',)),
    Term('Vico', ('Vico',), ('ship',)),
    Term('Potemkin', ('Potemkin',), ('ship',)),
    Term('Victory', ('Victory',), ('ship',), needs_context=True),
    Term('Drake', ('Drake',), ('ship',)),
    Term('Sutherland', ('Sutherland',), ('ship',)),
    Term('Zhukov', ('Zhukov',), ('ship',)),
    Term('Cairo', ('Cairo',), ('ship',)),
    Term('Berlin', ('Berlin',), ('ship',)),
    Term('Melbourne', ('Melbourne',), ('ship',)),
    Term('Bozeman', ('Bozeman',), ('ship',)),
    Term('Repulse', ('Repulse',), ('ship',)),
    Term('Aries', ('Aries',), ('ship',)),
    Term('Fearless', ('Fearless',), ('ship',)),
    Term('Excalibur', ('Excalibur',), ('ship',)),
    Term('Trieste', ('Trieste',), ('ship',)),
    Term('Merrimac', ('Merrimac',), ('ship',)),
    Term('Bonestell', ('Bonestell',), ('ship',)),
    Term('Gandhi', ('Gandhi',), ('ship',)),
    Term('Constellation', ('Constellation',), ('ship',)),
    Term('Crazy Horse', ('Crazy Horse',), ('ship',)),
    Term('Earth', ('Earth',), ('place',), tier='ambience'),
    Term('Betazed', ('Betazed',), ('place',)),
    Term('Khitomer', ('Khitomer',), ('klingon', 'place', 'romulan')),
    Term('Risa', ('Risa',), ('place',)),
    Term('Farpoint', ('Farpoint',), ('place',)),
    Term('Romulus', ('Romulus',), ('place',)),
    Term('Minos', ('Minos',), ('place',)),
    Term('Aldea', ('Aldea',), ('place',)),
    Term('Galorndon', ('Galorndon',), ('place',)),
    Term('Nelvana', ('Nelvana',), ('place',)),
    Term('Celtris', ('Celtris',), ('place',)),
    Term('Tagus', ('Tagus',), ('place',)),
    Term('Iconia', ('Iconia',), ('place',)),
    Term('Dytallix', ('Dytallix',), ('place',)),
    Term('Dorvan', ('Dorvan',), ('place',)),
    Term('Cardassia', ('Cardassia',), ('place',)),
    Term('Ohniaka', ('Ohniaka',), ('place',)),
    Term('Turkana', ('Turkana',), ('place',)),
    Term('Vega', ('Vega',), ('place',)),
    Term('Mars', ('Mars',), ('place',)),
    Term('Qualor', ('Qualor',), ('place',)),
    Term('Atrea', ('Atrea',), ('place',)),
    Term('Rigel', ('Rigel',), ('place',)),
    Term('Bajor', ('Bajor',), ('place',)),
    Term('Tanuga', ('Tanuga',), ('place',)),
    Term('Boraal', ('Boraal',), ('place',)),
    Term('Nervala', ('Nervala',), ('place',)),
    Term('Barkon', ('Barkon',), ('place',)),
    Term('Neutral Zone', ('Neutral Zone',), ('federation', 'place', 'romulan')),
    Term('Deep Space Nine', ('Deep Space Nine',), ('place',)),
    Term("Bre'el", ("Bre'el",), ('place',)),
    Term('Gamma Quadrant', ('Gamma Quadrant',), ('place',)),
    Term('Delta Quadrant', ('Delta Quadrant',), ('place',)),
    Term('Alexander', ('Alexander',), ('character', 'klingon')),
    Term('Barclay', ('Barclay',), ('character',)),
    Term('Guinan', ('Guinan',), ('character',)),
    Term('Lore', ('Lore',), ('android', 'character')),
    Term('Lwaxana', ('Lwaxana',), ('character',)),
    Term('Gowron', ('Gowron',), ('character', 'klingon')),
    Term('Duras', ('Duras',), ('character', 'klingon')),
    Term('Lal', ('Lal',), ('android', 'character')),
    Term('Soong', ('Soong',), ('android', 'character')),
    Term('Spock', ('Spock',), ('character',)),
    Term('Sarek', ('Sarek',), ('character',)),
    Term('Moriarty', ('Moriarty',), ('character',)),
    Term('Ardra', ('Ardra',), ('character',)),
    Term('Hugh', ('Hugh',), ('borg', 'character')),
    Term('Keiko', ('Keiko',), ('character',)),
    Term('Shelby', ('Shelby',), ('character',)),
    Term('Salia', ('Salia',), ('character',)),
    Term('Fajo', ('Fajo',), ('character',)),
    Term('Vash', ('Vash',), ('character',)),
    Term('Timicin', ('Timicin',), ('character',)),
    Term('Kurn', ('Kurn',), ('character', 'klingon')),
    Term('Kosinski', ('Kosinski',), ('character',)),
    Term('Tomalak', ('Tomalak',), ('character', 'romulan')),
    Term('Brahms', ('Brahms',), ('character',)),
    Term('Armus', ('Armus',), ('character',)),
    Term('Maddox', ('Maddox',), ('android', 'character')),
    Term('Yuta', ('Yuta',), ('character',)),
    Term('Juliana', ('Juliana',), ('android', 'character')),
    Term('Jellico', ('Jellico',), ('character',)),
    Term('Lursa', ('Lursa',), ('character', 'klingon')),
    Term('Rasmussen', ('Rasmussen',), ('character',)),
    Term('Kamala', ('Kamala',), ('character',)),
    Term('Ogawa', ('Ogawa',), ('character',)),
    Term('Toral', ('Toral',), ('character', 'klingon')),
    Term('Mot', ('Mot',), ('character',)),
    Term('Sela', ('Sela',), ('character', 'romulan')),
    Term('Nechayev', ('Nechayev',), ('character',)),
    Term('Scotty', ('Scotty',), ('character',)),
    Term('Nagilum', ('Nagilum',), ('character',)),
    Term('Spot', ('Spot',), ('character',)),
    Term('Q', ('Q',), ('character',)),
    Term("K'Ehleyr", ("K'Ehleyr",), ('character', 'klingon')),
    Term("B'Etor", ("B'Etor",), ('character', 'klingon')),
    Term('Ro Laren', ('Ro Laren',), ('character',)),
    Term('Kivas Fajo', ('Kivas Fajo',), ('character',)),
    Term('warp core breach', ('warp core breach', 'warp core breachs'), ('warp',), case_sensitive=False),
    Term('warp core', ('warp core', 'warp cores'), ('warp',), case_sensitive=False),
    Term('warp drive', ('warp drive', 'warp drives'), ('warp',), case_sensitive=False),
    Term('dilithium', ('dilithium', 'dilithiums'), ('warp',), case_sensitive=False),
    Term('antimatter', ('antimatter', 'antimatters'), ('warp',), case_sensitive=False),
    Term('nacelle', ('nacelle', 'nacelles'), ('warp',), case_sensitive=False),
    Term('intermix', ('intermix', 'intermixs'), ('warp',), case_sensitive=False),
    Term('impulse', ('impulse', 'impulses'), ('warp',), tier='ambience', case_sensitive=False),
    Term('plasma', ('plasma', 'plasmas'), ('warp',), case_sensitive=False),
    Term('tachyon', ('tachyon', 'tachyons'), ('physics',), case_sensitive=False),
    Term('graviton', ('graviton', 'gravitons'), ('physics',), case_sensitive=False),
    Term('neutrino', ('neutrino', 'neutrinos'), ('physics',), case_sensitive=False),
    Term('quantum', ('quantum', 'quantums'), ('physics',), case_sensitive=False),
    Term('positronic', ('positronic', 'positronics'), ('android', 'physics'), case_sensitive=False),
    Term('subspace', ('subspace', 'subspaces'), ('physics',), tier='ambience', case_sensitive=False),
    Term('particle', ('particle', 'particles'), ('physics',), case_sensitive=False),
    Term('chroniton', ('chroniton', 'chronitons'), ('physics',), case_sensitive=False),
    Term('pattern buffer', ('pattern buffer', 'pattern buffers'), ('transporter',), case_sensitive=False),
    Term('biofilter', ('biofilter', 'biofilters'), ('transporter',), case_sensitive=False),
    Term('transporter', ('transporter', 'transporters'), ('transporter',), tier='ambience', case_sensitive=False),
    Term('energise', ('energise', 'energises'), ('transporter',), tier='ambience', case_sensitive=False),
    Term('holodeck', ('holodeck', 'holodecks'), ('holodeck',), tier='ambience', case_sensitive=False),
    Term('hologram', ('hologram', 'holograms'), ('holodeck',), case_sensitive=False),
    Term('holographic', ('holographic', 'holographics'), ('holodeck',), case_sensitive=False),
    Term('Dixon Hill', ('Dixon Hill',), ('holodeck',)),
    Term('cloaking device', ('cloaking device', 'cloaking devices'), ('klingon', 'romulan', 'weapons'), case_sensitive=False),
    Term('photon torpedo', ('photon torpedo', 'photon torpedos'), ('weapons',), case_sensitive=False),
    Term('tractor beam', ('tractor beam', 'tractor beams'), ('weapons',), case_sensitive=False),
    Term('deflector', ('deflector', 'deflectors'), ('weapons',), case_sensitive=False),
    Term('phaser', ('phaser', 'phasers'), ('weapons',), tier='ambience', case_sensitive=False),
    Term('shields', ('shields',), ('weapons',), tier='ambience', case_sensitive=False),
    Term('Prime Directive', ('Prime Directive',), ('federation',)),
    Term('court martial', ('court martial', 'court martials'), ('federation',), case_sensitive=False),
    Term('saucer separation', ('saucer separation', 'saucer separations'), ('federation',), case_sensitive=False),
    Term('self destruct', ('self destruct', 'self destructs'), ('federation',), case_sensitive=False),
    Term('Starfleet Academy', ('Starfleet Academy',), ('federation',)),
    Term('red alert', ('red alert', 'red alerts'), ('federation',), tier='ambience', case_sensitive=False),
    Term('Starfleet', ('Starfleet',), ('federation',), tier='ambience'),
    Term('Federation', ('Federation',), ('federation',), tier='ambience'),
    Term('High Council', ('High Council',), ('klingon', 'klingon_culture')),
    Term('Kahless', ('Kahless',), ('klingon', 'klingon_culture')),
    Term("bat'leth", ("bat'leth", "bat'leths"), ('klingon', 'klingon_culture'), case_sensitive=False),
    Term('discommendation', ('discommendation', 'discommendations'), ('klingon', 'klingon_culture'), case_sensitive=False),
    Term('targ', ('targ', 'targs'), ('klingon', 'klingon_culture'), case_sensitive=False),
    Term('Tal Shiar', ('Tal Shiar',), ('romulan', 'romulan_power')),
    Term('Warbird', ('Warbird',), ('romulan', 'romulan_power')),
    Term('collective', ('collective', 'collectives'), ('borg', 'borg_concepts'), case_sensitive=False),
    Term('assimilate', ('assimilate', 'assimilates'), ('borg', 'borg_concepts'), case_sensitive=False),
    Term('Locutus', ('Locutus',), ('borg', 'borg_concepts')),
    Term('drone', ('drone', 'drones'), ('borg', 'borg_concepts'), case_sensitive=False),
    Term('cube', ('cube', 'cubes'), ('borg', 'borg_concepts'), case_sensitive=False),
    Term('DaiMon', ('DaiMon',), ('ferengi', 'ferengi_culture')),
    Term('latinum', ('latinum', 'latinums'), ('ferengi', 'ferengi_culture'), case_sensitive=False),
    Term('Gul', ('Gul',), ('cardassian', 'cardassian_power')),

    # Bare "Starbase" with no designation. Guarded so it does not also count
    # the 133 designated mentions, which have their own terms below; generic
    # plus specific then sums to every mention.
    Term("Starbase", ("Starbase",), ("place",), tier="ambience",
         case_sensitive=False, not_followed_by=r"[\s-]+(?:\d|" + _NUMBER_WORD
                                              + r"|Montgomery|Earhart|Lya|G6)"),
]

TERMS += starbase_terms()
