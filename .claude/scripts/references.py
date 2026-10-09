#!/usr/bin/env python3
"""Render evidence IDs into scientific-style citations for export.

`report.md` is the master and cites by evidence ID: `[E205]`. That is right for
the master, because an ID is stable, never renumbered, and resolves to a row in
`evidence.jsonl`. It is wrong for a deliverable, because `[E205]` tells a reader
nothing about whether the claim rests on a peer-reviewed paper, a conference
poster, a vendor datasheet or a marketing note. Those carry different evidential
weight and a scientific reader expects to see which one they are looking at
without turning to the back.

This script produces the derived, reader-facing form:

    [E205]  ->  (Halden Labs, product datasheet, 2026)
    [E1200] ->  (Glögl et al., 2024, Science)

and rebuilds `## Sources` as a formatted reference list grouped by source, with
the material type stated and the originating evidence IDs retained so the audit
trail survives.

    references.py render <styled.md> --run <run> -o <out.md> [--citemap map.json]
    references.py audit  <run>                 # what the ledger cannot render, and why
    references.py types                        # the controlled vocabulary

`report.md` is never modified. This runs on the styled copy produced by
`figures.py build`, between that step and pandoc.

Two rules it will not break, both from the workspace's non-negotiables:

- **Nothing is invented.** A row with no author gets its publisher as corporate
  author. A row with no date gets no date: the slot closes up rather than
  printing "undated" or `n.d.`, and where that would make two sources cite
  alike they are lettered instead. Neither is guessed, and `audit` reports
  every instance so the gap stays visible where it is auditable.
- **Evidence IDs are never renumbered.** They are carried into each reference
  entry exactly as the ledger holds them.
"""

import argparse
import json
import re
import sys
from collections import OrderedDict, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import biblio  # noqa: E402
from urllib.parse import urlsplit

# --------------------------------------------------------------------------
# Controlled vocabulary.
#
# Two families, as scientific practice distinguishes them:
#
#   SCHOLARLY  — author, year, venue.  Weight comes from peer review.
#   COMMERCIAL — author/company, document type, company, year.  Weight comes
#                from the issuer, and the document type is what tells a reader
#                how much to trust it.
#
# INSTITUTIONAL covers sources that are neither: regulators, standards bodies,
# patent offices, databases.  They are cited like scholarly work but their
# authority is jurisdictional rather than peer-conferred, so the type is stated.
#
# `label` is what prints.  Keep them short, lower-case, and honest: "marketing
# note" must not soften into "technical note".
# --------------------------------------------------------------------------

SCHOLARLY, COMMERCIAL, INSTITUTIONAL = "scholarly", "commercial", "institutional"

TYPES = OrderedDict([
    # scholarly
    ("peer_reviewed",   (SCHOLARLY,     "peer-reviewed article")),
    ("review",          (SCHOLARLY,     "review article")),
    ("preprint",        (SCHOLARLY,     "preprint, not peer reviewed")),
    ("conference",      (SCHOLARLY,     "conference paper")),
    ("poster",          (SCHOLARLY,     "conference poster")),
    ("abstract",        (SCHOLARLY,     "conference abstract")),
    ("thesis",          (SCHOLARLY,     "thesis")),
    ("book",            (SCHOLARLY,     "book")),
    # commercial
    ("datasheet",       (COMMERCIAL,    "product datasheet")),
    ("coa",             (COMMERCIAL,    "certificate of analysis")),
    ("sds",             (COMMERCIAL,    "safety data sheet")),
    ("white_paper",     (COMMERCIAL,    "white paper")),
    ("application_note",(COMMERCIAL,    "application note")),
    ("marketing",       (COMMERCIAL,    "marketing material")),
    ("press_release",   (COMMERCIAL,    "press release")),
    ("price_list",      (COMMERCIAL,    "price list")),
    ("catalogue",       (COMMERCIAL,    "catalogue listing")),
    ("market_report",   (COMMERCIAL,    "commercial market report")),
    ("trade_press",     (COMMERCIAL,    "trade press")),
    ("corporate",       (COMMERCIAL,    "corporate web page")),
    ("blog",            (COMMERCIAL,    "blog post")),
    ("consultancy",     (COMMERCIAL,    "consultancy commentary")),
    # institutional
    ("regulatory",      (INSTITUTIONAL, "regulatory guidance")),
    ("standard",        (INSTITUTIONAL, "standard")),
    ("pharmacopoeia",   (INSTITUTIONAL, "pharmacopoeial chapter")),
    ("patent",          (INSTITUTIONAL, "patent record")),
    ("database",        (INSTITUTIONAL, "database record")),
    ("repository",      (INSTITUTIONAL, "code repository")),
    ("ngo_report",      (INSTITUTIONAL, "NGO technical report")),
    ("statistical",     (INSTITUTIONAL, "official statistical release")),
    ("reference_work",  (INSTITUTIONAL, "reference work")),
    ("search_log",      (INSTITUTIONAL, "documented negative search")),
    ("ledger_note",     (INSTITUTIONAL, "ledger supersession note")),
    ("unlocated",       (INSTITUTIONAL, "source page not located")),
    ("news",            (INSTITUTIONAL, "news report")),
    ("unclassified",    (INSTITUTIONAL, "source type unclassified")),
])

# Ledger `type` values seen in the wild, mapped onto the vocabulary above.
# `primary`, `secondary` and `industry` describe a source's *role in an
# argument*, not the material it is, so they resolve to None and fall through
# to the heuristics below.
ALIASES = {
    "journal": "peer_reviewed", "paper": "peer_reviewed",
    "peer_reviewed": "peer_reviewed", "peer-reviewed": "peer_reviewed",
    "preprint": "preprint", "conference": "conference", "poster": "poster",
    "abstract": "abstract", "thesis": "thesis", "book": "book",
    "vendor": None, "distributor": "catalogue", "corporate": "corporate",
    "white_paper": "white_paper", "whitepaper": "white_paper",
    "marketing": "marketing", "press_release": "press_release",
    "trade_press": "trade_press", "news": "news", "blog": "blog",
    "opinion": "blog", "market_report": "market_report",
    "regulatory": "regulatory", "standards_body": "standard",
    "standard": "standard", "pharmacopoeia": "pharmacopoeia",
    "patent": "patent", "database": "database", "aggregator": "database",
    "repo": "repository", "repository": "repository",
    "ngo_report": "ngo_report", "consultancy": "consultancy",
    "statistical": "statistical", "reference_work": "reference_work",
    "primary": None, "secondary": None, "industry": None,
    "note": "ledger_note", "ledger_note": "ledger_note",
}

# Heuristics, applied only when `type` did not resolve. Ordered: first hit wins.
# Each is (regex, fields to test, vocabulary key), where "t" is title+publisher
# and "u" is the URL.
#
# `note` is deliberately NOT searched. It records how the source was fetched
# ("Abstract only; full text blocked", "via WebFetch summary of the PubMed
# abstract"), not what the source is, and reading it as material class demotes
# peer-reviewed papers to conference abstracts — inverting the exact weighting
# this vocabulary exists to convey. That bug shipped once; the fix is this
# comment plus the field restriction below.
#
# These are conservative by design. A pattern that would sometimes mislabel is
# left out, and the source falls through to `unclassified`, which prints
# honestly and appears in `audit`. Under-claiming a source type is recoverable;
# calling a marketing note a peer-reviewed article is not.
HEURISTICS = [
    (r"certificate of analysis|_coa[-_.]|-coa-",                "tu", "coa"),
    (r"safety data sheet|_sds|-sds|\bsdsen\b",                  "tu", "sds"),
    (r"application note",                                       "tu", "application_note"),
    (r"white ?paper",                                           "tu", "white_paper"),
    (r"press release|prnewswire|businesswire",                  "tu", "press_release"),
    (r"patents?\.google|espacenet|patentscope|patft",           "u",  "patent"),
    (r"\bpatent\b",                                             "t",  "patent"),
    (r"conference poster|\bposter session\b",                   "t",  "poster"),
    (r"conference abstract|meeting abstract|\babstract book\b", "t",  "abstract"),
    (r"github\.com|gitlab\.com",                                "u",  "repository"),
    (r"biorxiv|medrxiv|chemrxiv|arxiv\.org",                    "u",  "preprint"),
    (r"ncbi\.nlm\.nih\.gov/books",                              "u",  "reference_work"),
    (r"pubmed|pmc\.ncbi|doi\.org|sciencedirect|nature\.com|"
     r"science\.org|cell\.com|springer|wiley|frontiersin|mdpi|"
     r"journals\.plos|academic\.oup|tandfonline|biomedcentral|"
     r"europepmc\.org|ebi\.ac\.uk/europepmc|ncbi\.nlm\.nih\.gov/pmc|"
     r"isct-cytotherapy\.org|liebertpub|karger|elifesciences",  "u",  "peer_reviewed"),
    (r"fda\.gov|ema\.europa|ich\.org|who\.int|nibsc|"
     r"ecfr\.gov|federalregister\.gov",                         "u",  "regulatory"),
    (r"usp\.org|usp-nf|pharmacopeia|pharmacopoeia",             "tu", "pharmacopoeia"),
    (r"ecb\.europa\.eu|\.gov/stats|eurostat",                   "u",  "statistical"),
    (r"datasheet|data sheet|information sheet|"
     r"product (page|information|specification)",               "tu", "datasheet"),
    (r"/product/|/products/|\bcatalog|price list",              "tu", "catalogue"),
    (r"market (report|research|size|forecast)|grand ?view|"
     r"fact\.?mr|mordor|marketsandmarkets",                     "tu", "market_report"),
    (r"/news/|reuters\.com|bloomberg\.com|apnews",              "u",  "news"),
    (r"/blog/|//blog\.|\.blog/|/insights?/",                    "u",  "blog"),
]

# Publishers that are *hosts*, not venues. Printing "PubMed Central" in the
# journal slot of a scientific reference implies a venue that does not exist:
# PMC is where the paper was read, not where it was published. When the real
# journal is not in the ledger, the venue slot is left empty and the URL carries
# the provenance, which is honest; inventing the journal name is not.
HOSTLIKE = re.compile(
    r"^(pubmed|pubmed central|pmc|europe pmc|europepmc|ncbi|nih|"
    r"national (center|library)|researchgate|semantic scholar|crossref|"
    r"openalex|google scholar|biorxiv|medrxiv|doi\.org|sci-hub)\b", re.I)

# Publishing houses and imprints. They belong in the reference list and not in
# the middle of a sentence, and a journal is never named by one of them alone.
IMPRINT = re.compile(
    r"^(mdpi|elsevier|springer(\s*nature)?|wiley([- ]blackwell)?|nature\s+publishing|"
    r"cell\s+press|taylor\s*&?\s*francis|frontiers(\s+media)?|plos|public\s+library\s+of\s+science|"
    r"karger|oxford\s+university\s+press|oup|cambridge\s+university\s+press|sage|"
    r"american\s+chemical\s+society|acs|royal\s+society\s+of\s+chemistry|rsc|"
    r"bmj|lippincott|thieme|hindawi|bentham|ios\s+press|de\s+gruyter|emerald)\b",
    re.I)

CORPORATE_HINT = re.compile(
    r"\b(inc|ltd|llc|gmbh|corp|corporation|co|company|systems|technologies|"
    r"sciences?|biotech|labs?|laboratories|group|plc|ag|sa|bv|kk|k\.k)\b\.?$",
    re.I)


def norm_type(row):
    """Return (family, label, vocab_key) for one evidence row."""
    raw = (row.get("type") or "").strip().lower().replace("-", "_")
    key = ALIASES.get(raw, raw if raw in TYPES else None)
    if key is None:
        hay_t = " ".join(str(row.get(f, "")) for f in ("title", "publisher")).lower()
        hay_u = str(row.get("url", "")).lower()
        for pattern, fields, vocab in HEURISTICS:
            hay = (hay_t if "t" in fields else "") + " " + (hay_u if "u" in fields else "")
            if re.search(pattern, hay):
                key = vocab
                break
    u_low = str(row.get("url", "")).lower()
    if key is None and u_low.startswith(("falsification search", "n/a")):
        key = "search_log"
    if key is None and u_low.startswith(("unable to locate", "not located", "no url")):
        key = "unlocated"
    if key is None:
        # A vendor row that matched nothing is still a company document.
        key = "corporate" if raw in ("vendor", "industry") else "unclassified"
    family, label = TYPES[key]
    return family, label, key


INITIALS = re.compile(r"^(?:[A-Z]\.?){1,4}$")
NAMELIKE = re.compile(r"[A-Za-zÀ-ÿ]{2,}")


def surname(name):
    """The family name of a personal name, or the whole string if corporate.

    Handles the three forms the ledger actually contains:
      "Sugihara HY"   -> Sugihara   (PubMed: family name then initials)
      "Smith, John"   -> Smith      (inverted)
      "John Smith"    -> Smith      (natural order)
    Returns "" when the string is not a usable personal name, which tells the
    caller to fall back to the corporate author rather than print rubbish.
    """
    name = re.sub(r"\([^)]*\)", " ", name)          # drop "(GitHub user)" etc.
    name = re.sub(r"\b(19|20)\d{2}-\d{2}-\d{2}\b", " ", name)   # drop dates
    name = name.strip().strip(",;.").strip()
    if not name:
        return ""
    if CORPORATE_HINT.search(name):
        return name
    if "," in name:                                  # "Smith, John"
        head = name.split(",", 1)[0].strip()
        if NAMELIKE.search(head):
            return head
    parts = [p for p in re.split(r"\s+", name) if p]
    if not parts:
        return ""
    # An interior initial ("Dylan E. Iannitelli", "J. R. R. Tolkien") is a
    # personal name in natural order, whatever its length. Checked before the
    # organisation rule below, which would otherwise swallow it whole and print
    # the given name as the surname.
    if len(parts) >= 3 and any(INITIALS.match(t) for t in parts[1:-1]):
        last = parts[-1]
        if NAMELIKE.search(last) and last[:1].isupper():
            return last
    # Three or more tokens with no trailing initials is an organisation
    # ("Cell and Gene Therapy Insights", "ICH Expert Working Group"), and its
    # last word is not a surname.
    if len(parts) >= 3 and not INITIALS.match(parts[-1]):
        return name
    if len(parts) >= 2 and INITIALS.match(parts[-1]) and NAMELIKE.search(parts[0]):
        cand = parts[0]                              # "Sugihara HY"
    else:
        last = parts[-1]
        cand = (parts[0] if (INITIALS.match(last) or not NAMELIKE.search(last))
                else last)
    # A surname in a reference list is capitalised. A lowercase fragment is a
    # handle, a stray clause or a parse failure, and printing it would put
    # nonsense in the citation, so the corporate author takes over instead.
    return cand if cand[:1].isupper() else ""


def split_authors(raw):
    """Split an author field into individual names.

    Tolerates the three list forms the ledger contains, and refuses to split
    organisation names that merely contain "and".
    """
    raw = raw.strip()
    tail = raw.split(",", 1)[1].strip() if raw.count(",") == 1 else ""
    # "Smith, John" is one person inverted; "Sikora MJ, Johnson MD" is two in
    # PubMed order. They are the same shape, and the tell is the last token: a
    # given name ("John") against a run of initials ("MD"). Reading the second
    # as the first printed two authors as one name in every citation.
    tail_is_person = bool(tail) and not INITIALS.match(tail.split()[-1])
    if (tail and ";" not in raw and not re.search(r"\band\b|&", raw)
            and len(tail.split()) <= 2 and not INITIALS.match(tail)
            and tail_is_person):
        return [raw]                                  # "Smith, John"

    chunks = [c.strip() for c in raw.split(";") if c.strip()]
    if len(chunks) == 1:
        # "and" joins two authors ("F. Müller and K. Weber") but also sits
        # inside organisation names ("Cell and Gene Therapy Insights"). Split
        # only when both sides look like personal names.
        parts = [c.strip() for c in re.split(r"\band\b|&", raw) if c.strip()]
        if len(parts) > 1 and all(
                len(p.split()) <= 2 and p.split()[-1][:1].isupper() for p in parts):
            chunks = parts

    people = []
    for chunk in chunks:
        parts = [p.strip() for p in chunk.split(",") if p.strip()]
        merged = []
        for part in parts:
            if merged and INITIALS.match(part):       # "Smith" + "J." = one person
                merged[-1] = merged[-1] + " " + part
            else:
                merged.append(part)
        people.extend(merged)
    return people or [raw]


# Strings scouts write into `author` when they did not capture one. They are
# absent authors wearing a value, and treating them as text makes a paper cite
# to its publisher.
NON_AUTHOR = re.compile(r"^\s*(?:unknown|unspecified|not\s+captured|not\s+stated|"
                        r"n/?a|none|anon\.?|various|see\s+\w+)\b|not captured on fetch",
                        re.I)


def authors_of(row):
    """(in-text author string, full author string, is_corporate)."""
    raw = (row.get("author") or "").strip()
    if NON_AUTHOR.search(raw):
        raw = ""
    pub = (row.get("publisher") or "").strip()
    if raw:
        people = split_authors(raw)
        names = [surname(p) for p in people]
        names = [n for n in names if n]
        if names:
            if len(names) == 1:
                return names[0], people[0], False
            if len(names) == 2:
                return f"{names[0]} and {names[1]}", "; ".join(people[:2]), False
            return f"{names[0]} et al.", f"{people[0]} et al.", False
        # An author field that yields no usable name (a handle, a date, a note)
        # is not silently printed; the corporate author carries the citation.
    if pub:
        return pub, pub, True
    host = urlsplit(str(row.get("url", ""))).netloc.replace("www.", "")
    return (host or "Anon."), (host or "Anon."), True


def year_of(row):
    for field in ("published", "accessed"):
        m = re.search(r"(1[89]\d{2}|20\d{2})", str(row.get(field, "")))
        if m and field == "published":
            return m.group(1)
    m = re.search(r"(1[89]\d{2}|20\d{2})", str(row.get("published", "")))
    return m.group(1) if m else "undated"


def source_key(row):
    """Group evidence rows that came from the same document."""
    u = str(row.get("url", "")).strip()
    if u:
        s = urlsplit(u)
        return (s.scheme, s.netloc, s.path, s.query)
    return ("", "", (row.get("title") or "").lower(), "")


def venue_of(row):
    """Journal or venue for a scholarly entry, or "" when the ledger holds only
    the host it was read from."""
    pub = (row.get("publisher") or "").strip()
    if not pub or HOSTLIKE.match(pub):
        return ""
    return pub


def journal_only(venue):
    """The journal name alone, for the in-text citation.

    The ledger's `publisher` field is written to be informative in a reference
    list, so it routinely carries the imprint and the host alongside the
    journal: "Cell (Elsevier), via PMC", "Int J Mol Sci (MDPI), via PMC",
    "Stem Cell Reports (Cell Press), PubMed Central". A reader meeting that
    inline is reading provenance in the middle of a sentence. The reference
    list keeps every word of it; the parenthetical carries the journal.

    Stated by the author 2026-08-19: an in-text reference to a paper that has
    an author and a journal names those two and stops.

    This only ever *deletes*. A venue it cannot clean is returned unchanged,
    and an empty result falls back to the full string, so no citation loses
    its venue to a pattern that failed to match.
    """
    v = (venue or "").strip()
    if not v:
        return ""
    # the host the paper was read from, appended after a comma or a slash
    v = re.sub(r"\s*[,;/]\s*(via\s+)?(?=" + HOSTLIKE.pattern[1:] + r")",
               "\x00", v, flags=re.I).split("\x00")[0].strip()
    # a semicolon never appears inside a journal title, so anything after one
    # is provenance ("; open access via PubMed Central PMC11788244")
    v = v.split(";")[0].strip()
    # NIH PMC author manuscripts carry the host with no separator at all
    v = re.sub(r"\s*/?\s*(NIH\s+)?PMC\s+author\s+manuscript$", "", v, flags=re.I)
    # the imprint after a comma: "Biology (Basel), MDPI". Cut there only when
    # the tail is recognisably a publisher or a host. A comma inside a journal
    # title is common ("Drug design, development and therapy") and cutting at
    # every comma truncated those, so the tail has to earn the cut.
    depth = 0
    for i, ch in enumerate(v):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            tail = v[i + 1:].strip()
            # a tail opening on a digit is a locator (volume, issue, article
            # number), which belongs in the reference list rather than inline
            if (IMPRINT.match(tail) or HOSTLIKE.match(tail)
                    or CORPORATE_HINT.search(tail) or re.match(r"\d", tail)):
                v = v[:i]
            break
    # the imprint in parentheses after the journal: "Cell (Elsevier)". A
    # parenthetical holding a digit is data (a volume, a year, an indexed name
    # qualifier) and is left alone.
    v = re.sub(r"\s*\((?![^)]*\d)[^)]*\)\s*$", "", v).strip()
    v = v.rstrip(" ,;/")
    # A ledger row that led with the imprint rather than the journal ("MDPI
    # (Diagnostics journal), PMC copy") would clean down to the imprint alone,
    # which names no journal at all. Return the field untouched instead and let
    # the reference list carry it.
    if not v or IMPRINT.fullmatch(v):
        return (venue or "").strip()
    return v


def dot(text):
    """End a field with exactly one full stop.

    Author fields routinely already end in one ("C. Aussel et al.", "n.d."), and
    appending another produced "et al.." in every entry.
    """
    text = (text or "").strip()
    if not text:
        return ""
    return text if text[-1] in ".?!" else text + "."


def invert_first(raw_author, fallback):
    """MLA and Chicago bibliographies invert the first author: Surname, Given.

    Works from the same parsed names the in-text form uses, and gives up to the
    unmodified string rather than guessing when the name is corporate or does
    not parse.
    """
    raw = (raw_author or "").strip()
    if not raw:
        return fallback
    people = split_authors(raw)
    if not people:
        return fallback
    first = people[0].strip().strip(",")
    fam = surname(first)
    if not fam or CORPORATE_HINT.search(first):
        return fallback
    if "," in first:
        head = first                       # already inverted
    else:
        rest = first[: first.rfind(fam)].strip() if fam in first else ""
        rest = rest.strip(",").strip()
        # PubMed order is "Sugihara HY": family name first, initials after.
        if not rest and first.startswith(fam):
            initials = first[len(fam):].strip()
            head = f"{fam}, {initials}" if initials else fam
        else:
            head = f"{fam}, {rest}" if rest else fam
    if len(people) == 1:
        return head
    if len(people) == 2:
        return f"{head}, and {people[1].strip()}"
    return f"{head}, et al"


class Source:
    """One document, and every evidence row drawn from it."""

    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: int(r["id"][1:]))
        # Rows for one source are written by different scouts and differ in how
        # much they captured. Cite from the richest of them rather than from
        # whichever happens to hold the lowest id: one row saying
        # "unknown (not captured on fetch)" was making a whole paper cite to its
        # publisher while a sibling row held the full author list.
        def _completeness(r):
            a = (r.get("author") or "").strip()
            return (bool(a) and not NON_AUTHOR.search(a),
                    bool(str(r.get("published") or "").strip()),
                    len(a))
        self.head = max(self.rows, key=_completeness)
        self.ids = [r["id"] for r in self.rows]
        self.family, self.label, self.vocab = norm_type(self.head)
        self.intext_author, self.full_author, self.corporate = authors_of(self.head)
        self.year = year_of(self.head)
        self.title = (self.head.get("title") or "").strip() or "(untitled)"
        self.publisher = (self.head.get("publisher") or "").strip()
        self.url = str(self.head.get("url", ""))
        self.admiralty = (self.head.get("admiralty") or "").strip()
        self.supplied = self.url.startswith("file://") or self.head.get("origin") == "external_data"
        self.disambig = ""
        # A stable id the in-text citation links to. The lowest evidence row is
        # the source's identity here: ids are never renumbered, so the anchor
        # survives every re-render and every later round.
        self.anchor = "ref-" + self.ids[0].lower()

    # -- in-text -----------------------------------------------------------
    def cite(self):
        """The parenthetical a reader sees inline."""
        y = self.year + self.disambig
        # A source with no date says nothing where the year would go: the
        # fields either side close up around the gap rather than announcing it.
        undated = not self.year or self.year == "undated"
        if self.family == SCHOLARLY:
            venue = venue_of(self.head)
            # A paper with a named author cites to author, year and journal.
            # A corporate author is different: there the publisher *is* the
            # source, and stripping it would leave the citation with nothing.
            if not self.corporate:
                venue = journal_only(venue)
            named_venue = venue and venue.lower() != self.intext_author.lower()
            if undated:
                # with no year, the material class is what tells the reader how
                # to weigh the claim, so it takes the year's place
                if named_venue:
                    return f"{self.intext_author}, {venue}" + (
                        f", {self.disambig}" if self.disambig else "")
                return f"{self.intext_author}, {self.marked_label()}"
            if self.vocab == "preprint":
                return f"{self.intext_author}, {y}, preprint"
            if self.vocab in ("poster", "abstract", "conference"):
                return f"{self.intext_author}, {y}, {self.label}"
            if named_venue:
                return f"{self.intext_author}, {y}, {venue}"
            return f"{self.intext_author}, {y}"
        # commercial and institutional both lead with the type, because that is
        # the thing a reader needs in order to weigh the claim.
        #
        # A date the source never carried is omitted rather than announced.
        # Stated by the author 2026-08-19: printing "undated" in the middle of a
        # sentence tells the reader nothing they can use and reads as a defect
        # in the citation. The reference list still records that the source is
        # undated, so the absence stays visible where it is auditable.
        if undated:
            return f"{self.intext_author}, {self.marked_label()}"
        return f"{self.intext_author}, {self.label}, {y}"

    # -- reference list ----------------------------------------------------
    def marked_label(self):
        """The material label, carrying the disambiguating letter when the
        source has no date to carry it.

        The letter has to sit in the same place in the citation and in the
        entry, or it disambiguates nothing: a reader holding "corporate web
        page b" needs to find "[corporate web page b]" in the list.
        """
        if self.disambig and (not self.year or self.year == "undated"):
            return f"{self.label} {self.disambig}"
        return self.label

    def dateline(self):
        """`(2010).` for a dated source, and nothing at all for an undated one.

        Stated by the author 2026-08-19: a date the source does not carry is
        simply absent, and a reader can see that for themselves. Printing
        "undated" or "n.d." fills the slot with a word carrying no information.
        The ledger still records the absence and `references.py audit` still
        counts it, so the gap stays visible where it is auditable.
        """
        if not self.year or self.year == "undated":
            return ""
        return f"({self.year + self.disambig})."

    def entry(self):
        bits = []
        # The anchor the in-text citation jumps to. An empty bracketed span is
        # invisible in every output format and gives pandoc an id to target.
        bits.append(f"[]{{#{self.anchor}}}")
        if self.family == SCHOLARLY:
            venue = venue_of(self.head)
            bits.append(dot(self.full_author))
            bits.append(self.dateline())
            bits.append(f"*{self.title}*.")
            if venue and venue.lower() != self.full_author.lower():
                bits.append(f"{venue}.")
            if self.locator():
                bits.append(f"pp. {self.locator()}.")
            bits.append(f"[{self.marked_label()}]")
        else:
            bits.append(dot(self.full_author))
            bits.append(self.dateline())
            bits.append(f"*{self.title}*.")
            bits.append(f"[{self.marked_label()}]")
            if self.publisher and self.publisher != self.full_author:
                bits.append(f"{self.publisher}.")
            if self.locator():
                bits.append(f"pp. {self.locator()}.")
        if self.supplied:
            bits.append("Supplied document, " + self.url.replace("file://", ""))
        elif self.url:
            # an explicit autolink, so the entry is clickable in HTML, PDF and
            # docx. Pandoc's markdown reader does not link a bare URL unless
            # `autolink_bare_uris` is switched on, and it is not on by default.
            bits.append(f"<{self.url}>")
        if self.admiralty:
            bits.append(f"(Admiralty {self.admiralty})")
        bits.append("— " + compress_ids(self.ids))
        return " ".join(b for b in bits if b)

    def sort_key(self):
        return (self.intext_author.lower(), self.year, self.title.lower())

    # -- the other citation systems ----------------------------------------
    # MLA and Chicago want a locator (a page) in the in-text citation. The
    # ledger carries one only when the source actually had one, and a page
    # number is never inferred: an invented locator is the same class of error
    # as an invented date. MLA omits the locator for unpaginated sources, which
    # is what most web material is, so `(Author)` is correct rather than
    # degraded.
    def locator(self):
        for r in self.rows:
            pg = str(r.get("page") or r.get("pages") or "").strip()
            if pg:
                return pg
        return ""

    def cite_mla(self):
        pg = self.locator()
        who = self.intext_author + (f" {self.disambig}" if self.disambig
                                    and self.year == "undated" else "")
        return f"{who} {pg}" if pg else who

    def cite_chicago_ad(self):
        pg = self.locator()
        if self.year == "undated":
            who = self.intext_author + (f" {self.disambig}" if self.disambig else "")
            return f"{who}, {pg}" if pg else who
        y = self.year + self.disambig
        return f"{self.intext_author} {y}, {pg}" if pg else f"{self.intext_author} {y}"

    def entry_mla(self):
        """Works Cited: Author. "Title." Container, Date, URL."""
        y = self.year + self.disambig
        bits = [dot(invert_first(self.head.get("author"), self.full_author))]
        bits.append(f'"{self.title}."')
        venue = venue_of(self.head) if self.family == SCHOLARLY else ""
        container = venue or self.publisher
        if container and container.lower() != self.full_author.lower():
            bits.append(f"*{container}*,")
        bits.append(f"{y},")
        bits.append(f"[{self.label}]")
        loc = ("supplied document, " + self.url.replace("file://", "")
               if self.supplied else self.url)
        if loc:
            bits.append(loc + ".")
        bits.append("— " + compress_ids(self.ids))
        return " ".join(bits)

    def entry_chicago_ad(self):
        """References: Author. Year. "Title." Container. URL."""
        y = self.year + self.disambig
        bits = [dot(invert_first(self.head.get("author"), self.full_author)),
                dot(y)]
        bits.append(f'"{self.title}."')
        venue = venue_of(self.head) if self.family == SCHOLARLY else ""
        container = venue or self.publisher
        if container and container.lower() != self.full_author.lower():
            bits.append(f"*{container}*.")
        bits.append(f"[{self.label}]")
        loc = ("supplied document, " + self.url.replace("file://", "")
               if self.supplied else self.url)
        if loc:
            bits.append(loc + ".")
        bits.append("— " + compress_ids(self.ids))
        return " ".join(bits)

    def entry_chicago_notes(self):
        """Bibliography: Author. "Title." Container, Year. URL."""
        y = self.year + self.disambig
        bits = [dot(invert_first(self.head.get("author"), self.full_author))]
        bits.append(f'"{self.title}."')
        venue = venue_of(self.head) if self.family == SCHOLARLY else ""
        container = venue or self.publisher
        if container and container.lower() != self.full_author.lower():
            bits.append(f"*{container}*,")
        bits.append(dot(y))
        bits.append(f"[{self.label}]")
        loc = ("supplied document, " + self.url.replace("file://", "")
               if self.supplied else self.url)
        if loc:
            bits.append(dot(loc))
        bits.append("— " + compress_ids(self.ids))
        return " ".join(bits)

    def note_author(self):
        """Natural order, joined with 'and'. Chicago inverts only in the list.

        Used by both note() and note_needle(), which must stay identical: the
        needle is how check_export proves the note survived into the PDF.
        """
        return self.full_author.rstrip(".").replace("; ", " and ")

    def note_needle(self):
        """What check_export searches for when the in-text mark is a number."""
        return f'{self.note_author()}, "{self.title},"'

    def note(self):
        """A Chicago endnote: fuller than the in-text, shorter than the entry."""
        y = self.year + self.disambig
        pg = self.locator()
        venue = venue_of(self.head) if self.family == SCHOLARLY else self.publisher
        bits = [self.note_author() + ",", f'"{self.title},"']
        if venue and venue.lower() != self.full_author.lower():
            bits.append(f"*{venue}*,")
        bits.append(f"{y},")
        bits.append(f"[{self.label}]")
        if pg:
            bits.append(f"{pg}.")
        loc = ("supplied document, " + self.url.replace("file://", "")
               if self.supplied else self.url)
        if loc:
            bits.append(loc + ".")
        return " ".join(bits)


def compress_ids(ids):
    """E1200 E1201 E1202 E1205 -> E1200–E1202, E1205"""
    nums = sorted(int(i[1:]) for i in ids)
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:] + [None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(f"E{start}" if start == prev
                   else (f"E{start}, E{prev}" if prev == start + 1 else f"E{start}–E{prev}"))
        if n is not None:
            start = prev = n
    return ", ".join(out)


def load(run):
    path = Path(run) / "evidence.jsonl"
    if not path.exists():
        sys.exit(f"no evidence ledger at {path}")
    rows = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            sys.exit(f"{path}:{n}: {e}")
    return rows


def build_sources(rows, cite_fn=None):
    """Group rows into Sources and letter any that would otherwise cite alike.

    Two sources that print the same parenthetical send the reader to the
    reference list with no way to tell which entry is meant. That used to be
    tolerated for undated sources, which were skipped here on the reasoning that
    there was no year to hang a letter on: with 136 of this workspace's 235
    sources carrying no date, it meant the commonest citation in the document
    was also the least resolvable. Undated sources are now lettered too, on the
    material label rather than on the year.

    The collision test is the rendered citation itself, passed in as `cite_fn`,
    so a letter appears exactly where two citations would read identically and
    nowhere else. Without it the test falls back to author and year.
    """
    groups = defaultdict(list)
    for r in rows:
        groups[source_key(r)].append(r)
    sources = [Source(g) for g in groups.values()]
    seen = defaultdict(list)
    for s in sorted(sources, key=lambda s: min(int(i[1:]) for i in s.ids)):
        key = cite_fn(s) if cite_fn else (s.intext_author.lower(), s.year)
        seen[key].append(s)
    for group in seen.values():
        if len(group) > 1:
            for i, s in enumerate(group):
                s.disambig = chr(ord("a") + i) if i < 26 else f"-{i}"
    by_id = {}
    for s in sources:
        for i in s.ids:
            by_id[i] = s
    return sources, by_id


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

# Each system: the reference-list heading, the in-text form, and the entry form.
SYSTEMS = {
    "house": {
        "heading": "References",
        "cite": lambda src: src.cite(),
        "entry": lambda src: src.entry(),
        "blurb": "The bracketed descriptor states the class of material each claim "
                 "rests on: a peer-reviewed article, a preprint, a conference "
                 "abstract, a vendor datasheet and a marketing document carry "
                 "different evidential weight, and are not interchangeable.",
    },
    "mla": {
        "heading": "Works Cited",
        "cite": lambda src: src.cite_mla(),
        "entry": lambda src: src.entry_mla(),
        "blurb": "MLA style. In-text citations give author and page; a page is "
                 "shown only where the source carries one, since most web "
                 "material is unpaginated. The bracketed descriptor states the "
                 "class of material the claim rests on.",
    },
    "chicago-ad": {
        "heading": "References",
        "cite": lambda src: src.cite_chicago_ad(),
        "entry": lambda src: src.entry_chicago_ad(),
        "blurb": "Chicago author-date. In-text citations give author, year and "
                 "page where the source carries one. The bracketed descriptor "
                 "states the class of material the claim rests on.",
    },
    "chicago-notes": {
        "heading": "Bibliography",
        "cite": None,          # numbered notes, handled separately
        "entry": lambda src: src.entry_chicago_notes(),
        "blurb": "Chicago notes-bibliography. Superscript numbers refer to the "
                 "notes; the bibliography lists every source once. The bracketed "
                 "descriptor states the class of material the claim rests on.",
    },
}


def cmd_render(args):
    system = SYSTEMS[args.system]
    rows = load(args.run)
    # Two passes: build once to learn what each source would print, then again
    # with that as the collision key so the letters land only where two
    # citations would otherwise be indistinguishable.
    sources, by_id = build_sources(rows, cite_fn=lambda s: system["cite"](s))

    text = Path(args.source).read_text(encoding="utf-8")
    body, _tail = biblio.split_body(text)

    missing, used = set(), set()
    notes = []            # chicago-notes: ordered list of (number, Source)
    note_no = {}          # source key -> first note number, so repeats reuse it

    def swap(m):
        """Collapse a run of adjacent [E#][E#] into one citation."""
        ids = re.findall(r"E\d+", m.group(0))
        cites, seen_here, marks = [], set(), []
        for i in ids:
            src = by_id.get(i)
            if src is None:
                missing.add(i)
                cites.append(i)
                continue
            used.add(i)
            if args.system == "chicago-notes":
                key = id(src)
                if key not in note_no:
                    note_no[key] = len(notes) + 1
                    notes.append((note_no[key], src))
                if note_no[key] not in marks:
                    marks.append(note_no[key])
                continue
            c = system["cite"](src)
            if c not in seen_here:
                seen_here.add(c)
                # link the citation to its reference-list entry. Pandoc turns
                # this into an internal jump in HTML and PDF and a bookmark in
                # docx; where a format carries no links it degrades to the
                # plain text, which the letter still resolves on its own.
                cites.append(f"[{c}](#{src.anchor})")
        if args.system == "chicago-notes":
            # Markdown footnote references; pandoc renders them as endnotes.
            return "".join(f"[^{n}]" for n in marks) or ""
        return "(" + "; ".join(cites) + ")"

    body = re.sub(r"(?:\[E\d+\])+", swap, body)

    cited = set(used)
    listed = sorted({by_id[i] for i in cited}, key=lambda s: s.sort_key())

    out = [body.rstrip(), ""]

    if args.system == "chicago-notes" and notes:
        # Footnote definitions. Pandoc collects these into a Notes section.
        out.append("")
        for n, src in notes:
            out.append(f"[^{n}]: {src.note()}")
        out.append("")

    out.append(f"## {system['heading']}")
    out.append("")
    out.append(f"{len(listed)} sources, resolving to `evidence.jsonl`. "
               f"{system['blurb']} Trailing identifiers are the evidence rows "
               "drawn from that source. *Supplied document* marks material "
               "provided by the author and held in the run folder rather than "
               "fetched from a public URL.")
    out.append("")
    for src in listed:
        out.append(system["entry"](src))
        out.append("")

    Path(args.out).write_text("\n".join(out), encoding="utf-8")

    if args.citemap:
        cm = {}
        for i in sorted(cited, key=lambda x: int(x[1:])):
            src = by_id[i]
            # check_export looks for each value as text inside the exported
            # artifact. Under notes style the in-text mark is a bare superscript
            # number, which is far too short to search for, so the needle is the
            # author and title that open both the note and the bibliography
            # entry: if that is missing from the PDF, the citation really is.
            cm[i] = (src.note_needle() if args.system == "chicago-notes"
                     else system["cite"](src))
        Path(args.citemap).write_text(
            json.dumps(cm, indent=1, ensure_ascii=False), encoding="utf-8")

    fam = defaultdict(int)
    for src in listed:
        fam[src.family] += 1
    print(f"{len(cited)} citations → {len(listed)} sources "
          f"({fam[SCHOLARLY]} scholarly · {fam[COMMERCIAL]} commercial · "
          f"{fam[INSTITUTIONAL]} institutional) · {args.system} "
          f"→ ## {system['heading']} → {args.out}")
    if args.system in ("mla", "chicago-ad"):
        no_pg = [src for src in listed if not src.locator()]
        if no_pg:
            print(f"note {len(no_pg)} of {len(listed)} sources carry no page in the "
                  f"ledger, so their citations give author only. Pages are never "
                  f"inferred.")
    if missing:
        print(f"WARN {len(missing)} cited id(s) absent from the ledger, left as-is: "
              + ", ".join(sorted(missing)))
        return 1
    return 0


def cmd_audit(args):
    rows = load(args.run)
    sources, _unused = build_sources(rows)
    unclassified = [s for s in sources if s.vocab == "unclassified"]
    no_year = [s for s in sources if s.year == "undated"]
    corporate = [s for s in sources if s.corporate]
    fam = defaultdict(int)
    for s in sources:
        fam[s.family] += 1

    print(f"{len(rows)} evidence rows → {len(sources)} distinct sources")
    print(f"  scholarly {fam[SCHOLARLY]} · commercial {fam[COMMERCIAL]} "
          f"· institutional {fam[INSTITUTIONAL]}")
    print(f"  no personal author (cited corporately): {len(corporate)}")
    print(f"  no publication date (cited n.d.):       {len(no_year)}")
    print(f"  material type unclassified:             {len(unclassified)}")
    if unclassified:
        print("\nUnclassified — add a `type` to these rows, or extend HEURISTICS:")
        for s in unclassified[:args.limit]:
            print(f"  {compress_ids(s.ids):22s} {s.title[:64]}")
    if no_year and args.verbose:
        print("\nNo date — a scientific reference list wants a year:")
        for s in no_year[:args.limit]:
            print(f"  {compress_ids(s.ids):22s} {s.intext_author[:30]:32s} {s.title[:44]}")
    counts = defaultdict(int)
    for s in sources:
        counts[s.label] += 1
    print("\nMaterial types in this run:")
    for label, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4d}  {label}")
    return 0


def cmd_types(_args):
    for key, (family, label) in TYPES.items():
        print(f"  {family:14s} {key:18s} {label}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="rewrite [E#] as author-date and rebuild the list")
    r.add_argument("source")
    r.add_argument("--run", required=True)
    r.add_argument("-o", "--out", required=True)
    r.add_argument("--citemap", help="write E# -> citation JSON, for check_export")
    r.add_argument("--system", default="house", choices=sorted(SYSTEMS),
                   help="citation system: house (default), mla, chicago-ad, "
                        "chicago-notes. Chosen once per report and held to the "
                        "last line; see .claude/references/citation-style.md")
    r.set_defaults(fn=cmd_render)

    a = sub.add_parser("audit", help="what the ledger cannot render cleanly, and why")
    a.add_argument("run")
    a.add_argument("--limit", type=int, default=15)
    a.add_argument("-v", "--verbose", action="store_true")
    a.set_defaults(fn=cmd_audit)

    t = sub.add_parser("types", help="print the controlled vocabulary")
    t.set_defaults(fn=cmd_types)

    args = ap.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
