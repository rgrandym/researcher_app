#!/usr/bin/env python3
"""biblio.py — what the reference list at the end of a report is called.

The master document ends in a bibliography, and its heading depends on the
citation system the report was written in:

    ## Sources          the house system, cited by [E#]
    ## Works Cited      MLA
    ## References       Chicago author-date, and APA-shaped house exports
    ## Bibliography     Chicago notes-bibliography

Five scripts need to find that section: the citation audit splits the body from
it, the voice lint excludes it (titles are copied verbatim and would flood the
diction check), the reference renderer rebuilds it, the section guard treats it
as derived rather than authored, and the export check counts its entries.

They each used to carry their own `## Sources` regex. One shared definition
here means adding a citation system cannot leave one script matching a heading
the others do not.
"""
import re

# Ordered: the house heading first, then the systems a deliverable may use.
HEADINGS = ("Sources", "Works Cited", "References", "Bibliography", "Notes")

# `## Works Cited`, `# Bibliography`, `### Sources` — one to three hashes, any case.
PATTERN = (r"^#{1,3}\s*(?:" +
           "|".join(h.replace(" ", r"\s+") for h in HEADINGS) +
           r")\s*$")

RE_HEADING = re.compile(PATTERN, re.M | re.I)

# For section_guard, which compares lower-cased "## heading" keys. These sections
# are rebuilt by a script rather than written by hand, so they move on their own
# and that movement is not a containment failure.
DERIVED = tuple(f"## {h.lower()}" for h in HEADINGS) + ("## data still to obtain",)


def split_body(text):
    """Return (body, tail) where tail is the reference list and anything after.

    A report with no reference list returns the whole text as body.
    """
    m = RE_HEADING.search(text)
    if not m:
        return text, ""
    return text[:m.start()], text[m.start():]


def is_heading(line):
    """True if this single line opens the reference list."""
    return bool(re.match(PATTERN, line.strip(), re.I))
