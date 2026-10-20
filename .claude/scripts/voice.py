#!/usr/bin/env python3
"""Voice lint, measurement, and style learning for a report.

Voice is the part of a report that prose instructions guard badly: an agent
reads "do not use em-dashes", writes four paragraphs, and uses three. A regex
does not forget. This script does the mechanical half of the narrator's job so
the model can spend its attention on the half that needs judgement.

    voice.py lint    <file> [--profile P] [--strict]   # hard bans + soft ratios
    voice.py echo    <file>                            # repetition + ornate diction
    voice.py stats   <file>                            # punctuation and cadence
    voice.py mark    <file>                            # save agent-authored mirror
    voice.py learn   <file> [--slug S]                 # capture the user's edits
    voice.py profile [--rebuild]                       # show / recompute targets

`lint` exits 1 when a hard ban is hit. Soft ratios never fail the build: they
are reported so a writer can see the drift, because cadence is a preference and
preferences are not violations. `SHAPE`, `ECHO`, and `DICTION` lines are advisory
for the
same reason: a term of art repeated eight times is correct writing, and no
script can tell it from a lazy verb. Doctrine: `.claude/references/diction.md`.

`mark` stores the current text as `.voice-mirror-<name>.md` beside the report.
`learn` diffs the file against that mirror and files everything the user wrote
into `.claude/voice/corpus/`, which is what `profile --rebuild` measures. The
loop is: agent writes, agent marks, user edits by hand, `learn` captures the
user's own sentences, the profile moves toward them.
"""

import argparse
import difflib
import json
import re
import shutil
from datetime import datetime
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblio  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
from backend import edit_state  # noqa: E402
VOICE = ROOT / ".claude" / "voice"
CORPUS = VOICE / "corpus"
PROFILE = VOICE / "profile.md"
MEASURED = VOICE / "measured.json"

# ---------------------------------------------------------------- hard bans
# Each entry: (compiled pattern, what to write instead). These are the house
# rules: the constructions that most reliably read as machine prose. The
# author's own rules are added from `.claude/voice/rules.py` (see below). A hit
# is a defect, not a suggestion.
HARD = [
    (re.compile(r"\s—\s|^—\s|\s—$|\w—\w"),
     "em-dash. Use a comma, a semicolon, a colon, or parentheses"),
    (re.compile(r"(?<!\d)\s–\s(?!\d)"),
     "en-dash used as an aside. Reserve the en-dash for numeric ranges"),
    (re.compile(r"\b(?:that|which|what|who|why|it) matters\b", re.I),
     "'matters' formula. Say what the consequence is"),
    (re.compile(r"\bmatters?\s+(?:more|less|most)\b", re.I),
     "'matters more/most' formula. Rank the things explicitly"),
    (re.compile(r"\bthe (?:part|thing|question|point|one) that matters\b", re.I),
     "'the thing that matters'. Name it directly"),
    (re.compile(r"\b(?:is|are|was|were|it'?s|that'?s)\s+not\s+(?:just\s+)?[^.,;:]{1,60},\s*(?:it'?s|they'?re|that'?s|but)\b", re.I),
     "'not X, it is Y' antithesis. State Y and drop the setup"),
    (re.compile(r"\bnot (?:only|just) [^.;:]{1,60}\b(?:but|;)\s*(?:also\s+)?", re.I),
     "'not only X but also Y'. State both plainly"),
    (re.compile(r",\s*not\s+(?:just\s+|merely\s+|simply\s+|only\s+)?"
                r"(?:a|an|the|for|to|by|in|of|on|from|with|another|one|its|their|our|"
                r"your|his|her|some|any|every|each)\b[^.;:!?0-9]{0,70}(?=[.;:!?]|$)", re.I),
     "trailing 'X, not Y' corrective appositive. Cut the negated half and let X "
     "stand on its own"),
    (re.compile(r",\s*not\s+(?:just|merely|simply|only)\s+[^.;:!?0-9]{0,70}(?=[.;:!?]|$)",
                re.I),
     "trailing 'X, not just Y' concession. State X and stop"),
    (re.compile(r"\bit'?s not (?:about|that)\b", re.I),
     "'it's not about X'. Say what it is about"),
    (re.compile(r"\b(?:here'?s|there'?s) the (?:thing|catch|rub|problem with)\b", re.I),
     "conversational hook. Delete and start with the claim"),
    (re.compile(r"\b(?:at its core|make no mistake|the (?:hard|simple|uncomfortable) truth|let'?s be clear|the reality is)\b", re.I),
     "rhetorical stiffener. Delete it"),
    (re.compile(r"\bis (?:a|the) testament to\b|\bspeaks volumes\b|\bunderscore[sd]?\b|\bdelve into\b", re.I),
     "stock phrase"),
    (re.compile(r"\b(?:double-edged sword|the elephant in the room|low-hanging fruit|move the needle|paradigm shift)\b", re.I),
     "cliché"),
    (re.compile(r"[✅❌⚠️🔑📊🚀✨⇒✦●▶]|:[a-z_]+:"),
     "decorative symbol. Reports use words, tables, and figures"),
]

# ---------------------------------------------------------------- shapes
# Sentence architectures that read as machine prose even when every word is
# the author's. Advisory, because each one is occasionally the right sentence:
# the tell is using them as a default rhythm. Doctrine: references/diction.md.
SHAPE = [
    (re.compile(r",\s*(?:rather than|instead of|as opposed to)\s+"
                r"[^.;:!?]{0,70}(?=[.;:!?]|$)", re.I),
     "defines the thing by what it is not. Say what it is, then stop"),
    (re.compile(r"^(?:The|This|That|Its|Their)\s+\w+(?:\s+\w+)?\s+"
                r"(?:is|are|was|were)\s+[^.;:!?]{0,30}:\s", re.I),
     "abstract subject, copula, then a colon delivering the real content. "
     "Lead with the content"),
    (re.compile(r"\b(?:less|more) about\b[^.;:!?]{0,40}\bthan\b", re.I),
     "'less about X than Y'. State the one you mean"),
    (re.compile(r"\bnot because\b[^.;:!?]{0,60},\s*but\b", re.I),
     "'not because X, but because Y'. Give the reason and drop the foil"),
    (re.compile(r",\s*(?:making|ensuring|allowing|enabling|creating|leaving|giving|"
                r"driving|helping|reflecting|underscoring|highlighting|collapsing|"
                r"unlocking|positioning|cementing|marking)\s+[^.;:!?]{0,70}"
                r"(?=[.;:!?]|$)", re.I),
     "participial tail. If it states a new fact, make it a sentence; if it "
     "restates the clause, delete it"),
    (re.compile(r",\s*so\s+[^.;:!?]{0,70}(?=[.!?]|$)", re.I),
     "trailing 'so' clause. Check it adds a fact the reader did not already "
     "have from the clause before it"),
]

# The elliptical echo: a negated sentence answered by a short pro-verb sentence
# that repeats its verb ("Its magnitude does not transfer. The mechanism does.").
# The mechanically visible case of the punch-line rule.
# Needs the sentence before it, so it is checked separately from SHAPE.
ELLIPTIC_ECHO = re.compile(
    r"^(?:The|That|This|These|Those|It|Its|They|Their|Both|Each)\s+"
    r"(?:\w+\s+){0,2}"
    r"(?:does|do|did|is|are|was|were|can|could|will|would|has|have|had)\.$")
ELLIPTIC_NEG = re.compile(
    r"\b(?:not|never|no|nothing|neither|cannot)\b", re.I)

# ---------------------------------------------------------------- author rules
# The author's own patterns live in `.claude/voice/rules.py`, which is personal
# and kept out of the repository beside `profile.md`. It defines `HARD` and/or
# `SHAPE` lists in the same (compiled pattern, instruction) form as above, with
# `re` already imported. `/voice-rule` creates it with the first checkable rule.
RULES = VOICE / "rules.py"


def _author_rules():
    if not RULES.exists():
        return [], []
    ns = {"re": re}
    try:
        exec(compile(RULES.read_text(), str(RULES), "exec"), ns)
    except Exception as exc:
        sys.exit(f"voice.py: {RULES} does not load: {exc}")
    return list(ns.get("HARD", [])), list(ns.get("SHAPE", []))


_hard, _shape = _author_rules()
HARD += _hard
SHAPE += _shape

# ---------------------------------------------------------------- soft ratios
# Reported, never fatal. Defaults are seeded and then overwritten by
# `profile --rebuild` once the corpus of the user's own prose is big enough.
SOFT_DEFAULTS = {
    "semicolons_per_1k": (1.0, 12.0),
    "colons_per_1k": (1.0, 12.0),
    "parens_per_1k": (1.0, 20.0),
    "mean_sentence_words": (14.0, 30.0),
    "long_sentence_share": (0.0, 0.30),     # share of sentences over 40 words
    "bold_share": (0.0, 0.25),              # share of lines opening in bold
}

FENCE = re.compile(r"^```|^~~~")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(\[])")


def prose_lines(text, keep_tables=False):
    """Yield (lineno, line) for lines that are the author's own prose.

    Excluded: fenced blocks (figure JSON is data), the Sources list (titles are
    copied verbatim from publishers and their punctuation is not ours), block
    quotes (verbatim by definition), and table rows unless asked for.
    """
    fence = False
    in_sources = False
    lines = text.splitlines()
    start = 0
    # YAML frontmatter is metadata for the harness, not prose for a reader.
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                start = i + 1
                break
    for n, line in enumerate(lines[start:], start + 1):
        s = line.strip()
        if FENCE.match(s):
            fence = not fence
            continue
        if fence:
            continue
        if biblio.is_heading(s):
            in_sources = True
            continue
        if in_sources:
            if re.match(r"^#{1,3}\s+", s) and not biblio.is_heading(s):
                in_sources = False
            else:
                continue
        if s.startswith(">"):
            continue
        if not keep_tables and s.startswith("|"):
            continue
        yield n, line


FIG_BLOCK = re.compile(r"^```figure[ \t]*\n(.*?)^```", re.S | re.M)
FIG_TEXT_FIELDS = ("title", "subtitle", "note", "caption", "unit_label")


def figure_prose(text):
    """Yield (lineno, text) for the human-readable fields inside figure specs.

    A chart title is a claim and a note is prose, so both are the author's
    writing and both are linted. The numbers and the field names are not.
    """
    for m in FIG_BLOCK.finditer(text):
        start = text[: m.start()].count("\n") + 1
        try:
            spec = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue                      # figures.py reports malformed specs
        if not isinstance(spec, dict):
            continue
        for key in FIG_TEXT_FIELDS:
            val = spec.get(key)
            if isinstance(val, str) and val.strip():
                yield start, val


def strip_inline(line):
    """Remove spans whose punctuation belongs to someone else."""
    line = re.sub(r"`[^`]*`", " ", line)          # code spans
    line = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", line)  # links
    line = re.sub(r"https?://\S+", " ", line)
    line = re.sub(r"\[E\d+\]|\[\[F\d+\]\]|\{#\w+\}", " ", line)
    line = re.sub(r"\[NEEDS DATA[^\]]*\]", " ", line)
    return line


def quoted_spans(line):
    """Character ranges inside quotation marks. Verbatim quotes keep their own
    punctuation, so a source that used an em-dash does not become our defect."""
    spans = []
    for m in re.finditer(r"[\"“”][^\"“”]{0,400}[\"“”]|\*\"[^\"]{0,400}\"\*", line):
        spans.append((m.start(), m.end()))
    return spans


# ------------------------------------------------------- repetition + diction
# Words that carry no content, so repeating them is not an echo. Kept short on
# purpose: the check only ever looks at words of four letters or more.
STOP = set("""
about above across after again against all also although always among and another any
are around because been before being below beside besides between beyond both but
came can cannot come could dead did does doing done down during each either else even
ever every few first for from further had has have having here hers high him himself
his how however into its itself just least less like made make many may might more
most much must near need never next nor not now off once only onto other others our
ours out over own past per rather same seem seen several she should since some such
than that the their theirs them themselves then there these they this those though
three through thus too two under until upon used using very was way were what when
where whether which while who whom whose why will with within without would yet you
your yours been also once therefore hence instead meanwhile whereas despite versus
overall given already perhaps almost enough later earlier roughly approximately
""".split())

# Ordinary words that read as ornate, literary, or inflated in a report. Each
# maps to the plain word the author would use. Advisory: context can justify any
# of them, and the writer decides.
ORNATE = {
    "utilise": "use", "utilize": "use", "utilised": "used", "utilized": "used",
    "utilisation": "use", "utilization": "use",
    "myriad": "many", "plethora": "many", "panoply": "range", "veritable": "(cut)",
    "tapestry": "(cut the metaphor)", "realm": "field", "arena": "field",
    "landscape": "market, or field", "ecosystem": "market, or set of suppliers",
    "journey": "process", "odyssey": "process", "voyage": "process",
    "unveil": "publish, or report", "unveiled": "published", "herald": "signal",
    "heralds": "signals", "usher": "start", "showcase": "show", "showcases": "shows",
    "illuminate": "show", "illuminates": "shows",
    "bedrock": "basis", "cornerstone": "basis", "linchpin": "the critical part",
    "spearhead": "lead", "harness": "use", "harnessing": "using",
    "navigate": "deal with", "navigating": "dealing with",
    "commence": "start", "commenced": "started", "endeavour": "effort",
    "endeavor": "effort", "leverage": "use", "leveraging": "using",
    "facilitate": "help, or allow", "facilitates": "helps", "facilitated": "helped",
    "paramount": "the highest", "quintessential": "typical", "seminal": "early",
    "burgeoning": "growing", "ubiquitous": "widespread", "myriads": "many",
    "trailblazing": "first", "groundbreaking": "first", "revolutionise": "change",
    "revolutionize": "change", "transformative": "(say what it changes)",
    "unprecedented": "(say what it exceeds)", "unparalleled": "(say against what)",
    "vast": "large", "immense": "large", "profound": "large", "stark": "clear",
    "compelling": "(say why)", "remarkable": "(say what is unusual)",
    "myopic": "short-sighted", "nuanced": "(state the distinction)",
    "granular": "detailed", "actionable": "usable", "impactful": "(say the effect)",
    "holistic": "whole", "synergy": "(say what combines)", "synergies": "(as above)",
    "deep-dive": "detailed review",
}

# American forms with their British equivalents. Advisory, and deliberately
# narrow: no -ize verbs where Oxford spelling is defensible, no scientific
# vocabulary (sulfur, aluminium) where the field sets the form.
US_SPELLING = {
    "behavior": "behaviour", "behaviors": "behaviours", "behavioral": "behavioural",
    "color": "colour", "colors": "colours", "favor": "favour", "favors": "favours",
    "favorable": "favourable", "labor": "labour", "honor": "honour",
    "rigor": "rigour", "vigor": "vigour", "odor": "odour", "humor": "humour",
    "center": "centre", "centers": "centres", "centered": "centred",
    "fiber": "fibre", "fibers": "fibres", "liter": "litre", "liters": "litres",
    "theater": "theatre", "defense": "defence", "offense": "offence",
    "license": "licence (noun)", "practiced": "practised (verb)",
    "fulfill": "fulfil", "fulfillment": "fulfilment", "enrollment": "enrolment",
    "modeling": "modelling", "modeled": "modelled", "labeled": "labelled",
    "labeling": "labelling", "traveled": "travelled", "canceled": "cancelled",
    "catalog": "catalogue", "dialog": "dialogue", "analog": "analogue",
    "aging": "ageing", "judgment": "judgement", "gray": "grey",
    "toward": "towards", "afterward": "afterwards",
    "analyze": "analyse", "analyzed": "analysed", "analyzing": "analysing",
    "paralyze": "paralyse", "catalyze": "catalyse",
}

WORD = re.compile(r"[A-Za-z][A-Za-z'’-]{2,}")


def stem(w):
    """Crude suffix strip, so 'provide/provides/provided/providing' group.

    The trailing silent 'e' goes last, which is what makes 'figure' and
    'figures' land on the same stem. The result is not a word and is not meant
    to be read as one; the forms actually found are what gets printed.
    """
    w = w.lower().replace("’", "'").strip("-'")
    w = re.sub(r"'s$", "", w)                  # possessive is the same word
    if w.endswith(("ss", "us", "is")):
        pass                                   # across, versus, analysis
    elif w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("s") and not w.endswith("es"):
        w = w[:-1]
    elif w.endswith("es") and len(w) > 4:
        w = w[:-1] if not w.endswith(("ches", "shes", "xes", "zes", "sses")) else w[:-2]
    for suf in ("ingly", "edly", "ing", "ied", "ed", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)] + ("y" if suf == "ied" else "")
            break
    if len(w) > 3 and w.endswith("e"):
        w = w[:-1]
    return w.rstrip("-'")


# Ordinary vocabulary that is never a term of art, so it is never silenced by
# the document-frequency heuristic. A report that says "significant" in thirty
# paragraphs has a problem in all thirty of them.
GENERIC = set("""
approach area aspect become begin better carry case cause change clear common
consider deliver difference different direct drive effect element establish
exist explain factor feature find focus follow give ground high highlight
identify important include increase indicate issue key large level likely limit
main major make matter mean measure need note number offer often outcome part
particular perform place point possible present problem process produce provide
range reach real reason reduce relevant remain report require result role second
seem set show significant similar single specific still strong substantial
suggest support take term thing type understand use various view way whole
""".split())


def exempt_terms(path):
    """Terms of art this run repeats on purpose, one per line in voice-terms.txt."""
    f = Path(path).parent / "voice-terms.txt"
    terms = set()
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.split("#")[0].strip()
            if line:
                terms.update(stem(w) for w in WORD.findall(line))
    return terms


def allowed_spans(path):
    """Constructions this run keeps on purpose, one fragment per line in
    voice-allow.txt.

    The ban on the trailing "X, not Y" corrective carves out the case where the
    negated half carries information, and the pattern approximates that as "the
    tail contains a digit". A correction about what a figure *is* rather than
    what it equals ("this is a floor, not a quote") falls outside that proxy and
    is flagged anyway. Registering the fragment here is the author's record that
    the negation is load-bearing: it is written once, it stays visible in the
    run, and a new one still has to be argued for rather than inherited.

    Matching is on the flagged fragment, so an exemption follows the sentence
    if it moves and dies when the sentence is rewritten.
    """
    f = Path(path).parent / "voice-allow.txt"
    out = []
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.split("#")[0].strip()
            if line:
                out.append(" ".join(line.split()).lower())
    return out


def paragraphs(text):
    """Yield (lineno, paragraph_text) over prose only.

    Blank-line separated blocks, with headings, list markers, tables, fences,
    quotes, and the Sources list already excluded by `prose_lines`.
    """
    block, start = [], None
    for n, raw in prose_lines(text):
        s = raw.strip()
        if not s or s.startswith("#"):
            if block:
                yield start, " ".join(block)
                block, start = [], None
            continue
        if start is None:
            start = n
        block.append(s)
    if block:
        yield start, " ".join(block)


def echo_hits(path, near=15, times=3):
    """Repetition and diction findings. Advisory by design; see diction.md.

    Four things are looked for, and each one is a different flaw:
      ECHO       an ordinary word used `times`+ in one paragraph
      ECHO-NEAR  the same word twice inside `near` words, which the ear catches
      OPENER     consecutive sentences starting on the same word
      DICTION    ornate vocabulary, or an American spelling

    A word the whole report leans on is its subject, not an echo, so a stem that
    appears in many paragraphs is treated as the run's vocabulary and reported
    once at the end rather than flagged in every paragraph. That heuristic is
    what keeps 'electrolyte' quiet in a report about electrolytes. It is a guess: confirm it
    by writing the real terms into voice-terms.txt.
    """
    text = Path(path).read_text()
    skip = set(exempt_terms(path))
    paras = list(paragraphs(text))
    generic = {stem(w) for w in GENERIC}
    spread = {}
    for _, para in paras:
        words = {w for w in WORD.findall(strip_inline(para).lower())
                 if w not in STOP and len(w) >= 4}
        for s in {stem(w) for w in words}:
            spread[s] = spread.get(s, 0) + 1
    threshold = max(3, round(len(paras) * 0.06))
    vocabulary = sorted(s for s, c in spread.items()
                        if c >= threshold and s not in skip and s not in STOP
                        and s not in generic and len(s) >= 4)
    skip.update(vocabulary)
    out = []
    for n, para in paras:
        body = strip_inline(para)
        for a, b in reversed(quoted_spans(body)):
            body = body[:a] + " " * (b - a) + body[b:]   # quotes are not our words
        words = [(i, w.lower()) for i, w in enumerate(WORD.findall(body))]
        seen = {}
        for i, w in words:
            if len(w) < 4 or w in STOP:
                continue
            s = stem(w)
            if s in skip or len(s) < 4:
                continue
            seen.setdefault(s, []).append((i, w))
        for s, uses in sorted(seen.items(), key=lambda kv: -len(kv[1])):
            forms = sorted({w for _, w in uses})
            shown = "/".join(forms)
            if len(uses) >= times:
                out.append(f"ECHO {path}:{n} '{shown}' {len(uses)}× in one paragraph")
            elif (len(uses) == 2 and uses[1][0] - uses[0][0] <= near
                  and len(s) >= 5):
                out.append(f"ECHO-NEAR {path}:{n} '{shown}' twice within "
                           f"{uses[1][0] - uses[0][0]} words")
        sents = [x for x in SENT_SPLIT.split(body) if x.split()]
        prev, runs = None, {}
        for sent in sents:
            first = sent.split()[0].strip("*_(\"'").lower()
            if first and first == prev and len(first) > 2:
                runs[first] = runs.get(first, 1) + 1
            prev = first
        for word, count in runs.items():
            out.append(f"OPENER {path}:{n} {count} sentences in a row open "
                       f"on '{word}'")
        lowered = body.lower()
        for word, better in list(ORNATE.items()) + list(US_SPELLING.items()):
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                tag = "ornate" if word in ORNATE else "US spelling"
                out.append(f"DICTION {path}:{n} '{word}' ({tag}) → {better}")
    return out, vocabulary


def shape_hits(path):
    """SHAPE findings: sentence architectures that read as machine prose.

    Advisory like ECHO. A single hit is usually fine; two or three in one
    document is the rhythm the author objects to, and is the signal to
    restructure rather than to swap words.
    """
    text = Path(path).read_text()
    out = []
    for n, para in paragraphs(text):
        body = strip_inline(para)
        sents = [x.strip() for x in SENT_SPLIT.split(body) if x.strip()]
        for i, sent in enumerate(sents):
            for pat, why in SHAPE:
                m = pat.search(sent)
                if m:
                    out.append(f"SHAPE {path}:{n} '{m.group(0).strip()[:52]}' → {why}")
            if i and ELLIPTIC_ECHO.match(sent) and ELLIPTIC_NEG.search(sents[i - 1]):
                out.append(
                    f"SHAPE {path}:{n} '{sent[:52]}' → punch line: a short "
                    "pro-verb sentence answering the negation before it. Fold "
                    "the fact into the sentence before, or state it in full")
    return out


def echo(path, near=15, times=3):
    hits, vocab = echo_hits(path, near, times)
    hits = shape_hits(path) + hits
    for h in hits:
        print(h)
    print(f"\n{len(hits)} repetition/diction note(s) · advisory, judged not obeyed")
    if vocab:
        print(f"\ntreated as this report's vocabulary and not flagged "
              f"({len(vocab)} stems recurring across sections):")
        print("  " + ", ".join(vocab))
        print("  A word here that is NOT a term of art is a real echo. Confirm the "
              "list by writing the deliberate ones into "
              f"{Path(path).parent / 'voice-terms.txt'}")
    return 0


def lint(path, strict=False):
    text = Path(path).read_text()
    allow = allowed_spans(path)
    exempted = 0
    hits = []
    for n, raw in list(prose_lines(text, keep_tables=True)) + list(figure_prose(text)):
        line = strip_inline(raw)
        skip = quoted_spans(line)
        claimed = []
        for pat, why in HARD:
            for m in pat.finditer(line):
                if any(a <= m.start() < b for a, b in skip):
                    continue
                if any(a <= m.start() < b for a, b in claimed):
                    continue        # a longer pattern already flagged this span
                hay = " ".join(m.group(0).split()).lower()
                if any(a in hay or hay in a for a in allow):
                    claimed.append((m.start(), m.end()))
                    exempted += 1
                    continue        # registered in voice-allow.txt
                claimed.append((m.start(), m.end()))
                frag = line[max(0, m.start() - 24): m.end() + 24].strip()
                hits.append(f"VOICE {path}:{n} {why} :: …{frag}…")
    metrics = measure(text)
    targets = load_targets()
    soft = []
    # Cadence is meaningless on a short file; a caption block is not a document.
    for key, (lo, hi) in (targets.items() if metrics["words"] >= 300 else ()):
        v = metrics.get(key)
        if v is None:
            continue
        if v < lo or v > hi:
            soft.append(f"DRIFT {key}={v:.2f} outside target {lo:.2f}–{hi:.2f}")
    notes, _vocab = echo_hits(path)
    notes = shape_hits(path) + notes
    for h in hits:
        print(h)
    for s in soft:
        print(s)
    for e in notes:
        print(e)
    print(f"\n{len(hits)} voice violation(s) · {len(soft)} cadence drift(s) · "
          f"{len(notes)} repetition/diction note(s) · {metrics['words']} words")
    if exempted:
        print(f"{exempted} construction(s) exempted by "
              f"{Path(path).parent / 'voice-allow.txt'} · an entry there is a "
              f"claim that the construction carries information, and it is read "
              f"like any other line of the run")
    if notes:
        print("SHAPE/ECHO/DICTION are advisory: read them against "
              ".claude/references/diction.md, and list deliberate terms of art in "
              f"{Path(path).parent / 'voice-terms.txt'}")
    fail = bool(hits) or (strict and (soft or notes))
    sys.exit(1 if fail else 0)


def measure(text):
    body = "\n".join(l for _, l in prose_lines(text))
    body = strip_inline(body)
    words = len(body.split())
    k = max(words, 1) / 1000
    sentences = [s for s in SENT_SPLIT.split(re.sub(r"\s+", " ", body)) if len(s.split()) > 2]
    lens = [len(s.split()) for s in sentences] or [0]
    lines = [l.strip() for _, l in prose_lines(text) if l.strip()]
    bold_open = sum(1 for l in lines if l.startswith("**"))
    return {
        "words": words,
        "sentences": len(sentences),
        "semicolons_per_1k": body.count(";") / k,
        "colons_per_1k": len(re.findall(r"(?<!\d):(?!\d|//)", body)) / k,
        "parens_per_1k": body.count("(") / k,
        "emdash_per_1k": body.count("—") / k,
        "mean_sentence_words": statistics.mean(lens),
        "median_sentence_words": statistics.median(lens),
        "long_sentence_share": sum(1 for x in lens if x > 40) / max(len(lens), 1),
        "bold_share": bold_open / max(len(lines), 1),
    }


def load_targets():
    if MEASURED.exists():
        try:
            data = json.loads(MEASURED.read_text())
            return {k: tuple(v) for k, v in data.get("targets", {}).items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return SOFT_DEFAULTS


def stats(path):
    m = measure(Path(path).read_text())
    width = max(len(k) for k in m)
    for key, val in m.items():
        print(f"{key.ljust(width)}  {val:.2f}" if isinstance(val, float) else
              f"{key.ljust(width)}  {val}")


def mirror_path(path):
    p = Path(path)
    return p.parent / f".voice-mirror-{p.stem}.md"


def mark(path):
    """Record the agent's write: a mirror for diffing, and a dated snapshot.

    The mirror is the baseline `learn` and `saved_check` compare against, and
    there is only ever one. The snapshot is the safety net: a timestamped copy in
    `<run>/.history/`, kept because the author edits this file by hand in an
    editor and a stale buffer can overwrite an agent write with no error. The
    run folder is the right home for these, since it is the same folder the
    author would be restoring into and it stays out of any repository.
    """
    p = Path(path)
    shutil.copy2(p, mirror_path(p))
    print(f"mirror: {mirror_path(p)}")
    hist = p.parent / ".history"
    hist.mkdir(exist_ok=True)
    snap = hist / f"{p.stem}-{datetime.now():%Y%m%d-%H%M%S}{p.suffix}"
    if not snap.exists():
        shutil.copy2(p, snap)
    # Keep the last 40. Enough to cover a long session, small enough that the
    # folder stays readable when someone is hunting for a lost version.
    snaps = sorted(hist.glob(f"{p.stem}-*{p.suffix}"))
    for stale in snaps[:-40]:
        stale.unlink()
    print(f"snapshot: {snap.name} ({len(snaps[-40:])} kept)")


def learn(path, slug=None):
    """Capture the prose the user wrote by hand since the last `mark`.

    Only added and replaced lines are captured, and only ones long enough to
    carry cadence. Deletions tell us nothing about how the user writes.
    """
    p = Path(path)
    mp = mirror_path(p)
    author_edit = edit_state.active(p)
    baseline = edit_state.base_path(p) if author_edit else mp
    if not baseline.exists():
        print(f"no mirror at {mp}; run `voice.py mark {p}` after the next agent write")
        return 2
    old = baseline.read_text().splitlines()
    new = (edit_state.saved_path(p) if author_edit else p).read_text().splitlines()
    # A repeated /user-edits run must not count the same paragraph twice as
    # evidence of the author's cadence. Revised paragraphs remain new samples.
    known = {part.strip() for f in corpus_files()
             for part in f.read_text().split("\n\n")}
    captured = []
    for line in difflib.ndiff(old, new):
        if not line.startswith("+ "):
            continue
        s = line[2:].strip()
        if len(s.split()) < 6:
            continue
        if s.startswith(("|", ">", "```", "#", "!", "[E")):
            continue
        if s in known or s in captured:
            continue
        captured.append(s)
    if not captured:
        print("no user-authored prose found since the last mark")
        return 0
    CORPUS.mkdir(parents=True, exist_ok=True)
    slug = slug or p.parent.name
    out = CORPUS / f"{date.today().isoformat()}-{slug}.md"
    with out.open("a") as fh:
        fh.write(f"\n<!-- captured {date.today().isoformat()} from {p} -->\n\n")
        for s in captured:
            fh.write(s + "\n\n")
    words = sum(len(s.split()) for s in captured)
    print(f"captured {len(captured)} passage(s), {words} words → {out}")
    print("run `voice.py profile --rebuild` to fold them into the cadence targets")
    return 0


def corpus_files():
    """Captured passages only. README.md documents the folder and is not a sample."""
    if not CORPUS.exists():
        return []
    return sorted(f for f in CORPUS.glob("*.md") if f.name != "README.md")


def rebuild_profile():
    files = corpus_files()
    if not files:
        print("corpus is empty; nothing to measure. Targets stay at their seeded values.")
        return 1
    text = "\n\n".join(f.read_text() for f in files)
    m = measure(text)
    if m["words"] < 400:
        print(f"corpus holds {m['words']} words; too few to set targets (need 400+). "
              f"Seeded values kept.")
        return 1
    # Bands sit around the measured value: wide enough that ordinary variation
    # is not flagged, tight enough that a drift toward machine cadence is.
    def band(v, spread=0.5, floor=0.0):
        return (max(floor, round(v * (1 - spread), 2)), round(v * (1 + spread), 2))
    targets = {
        "semicolons_per_1k": band(m["semicolons_per_1k"]),
        "colons_per_1k": band(m["colons_per_1k"]),
        "parens_per_1k": band(m["parens_per_1k"]),
        "mean_sentence_words": band(m["mean_sentence_words"], 0.30),
        "long_sentence_share": (0.0, round(min(0.5, m["long_sentence_share"] * 1.5 + 0.05), 2)),
        "bold_share": (0.0, round(min(0.5, m["bold_share"] * 1.5 + 0.05), 2)),
    }
    MEASURED.parent.mkdir(parents=True, exist_ok=True)
    MEASURED.write_text(json.dumps({
        "rebuilt": date.today().isoformat(),
        "corpus_files": [f.name for f in files],
        "corpus_words": m["words"],
        "measured": {k: round(v, 3) for k, v in m.items() if isinstance(v, float)},
        "targets": targets,
    }, indent=2) + "\n")
    print(f"rebuilt from {len(files)} corpus file(s), {m['words']} words → {MEASURED}")
    for k, (lo, hi) in targets.items():
        print(f"  {k}: {lo}–{hi}")
    return 0


def show_profile():
    if PROFILE.exists():
        print(PROFILE.read_text())
    else:
        print(f"no profile at {PROFILE}")
    print("\n--- measured targets ---")
    if MEASURED.exists():
        print(MEASURED.read_text())
    else:
        print("none yet; seeded defaults in force:")
        for k, v in SOFT_DEFAULTS.items():
            print(f"  {k}: {v[0]}–{v[1]}")
    files = corpus_files()
    print(f"\ncorpus: {len(files)} file(s)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["lint", "echo", "stats", "mark", "learn", "profile"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--slug")
    ap.add_argument("--near", type=int, default=15,
                    help="word distance that counts as a close echo")
    ap.add_argument("--times", type=int, default=3,
                    help="uses of one word in a paragraph before it is reported")
    ap.add_argument("--strict", action="store_true",
                    help="fail on cadence drift and repetition as well as hard bans")
    ap.add_argument("--rebuild", action="store_true")
    a = ap.parse_args()

    if a.cmd == "profile":
        sys.exit(rebuild_profile() if a.rebuild else (show_profile() or 0))
    if not a.file:
        ap.error(f"{a.cmd} needs a file")
    if not Path(a.file).exists():
        sys.exit(f"no such file: {a.file}")
    if a.cmd == "lint":
        lint(a.file, a.strict)
    elif a.cmd == "echo":
        sys.exit(echo(a.file, a.near, a.times))
    elif a.cmd == "stats":
        stats(a.file)
    elif a.cmd == "mark":
        mark(a.file)
    elif a.cmd == "learn":
        sys.exit(learn(a.file, a.slug))


if __name__ == "__main__":
    main()
