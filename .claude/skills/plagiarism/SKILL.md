---
name: plagiarism
description: Check a report for plagiarism risk, the way Turnitin does: compare its wording with the full text of every source the run read, the author's supplied files and pages found by an exact-phrase web search, then score originality and plagiarism risk, rank the sections, and give a short fix for each problem passage. Use when the author asks for a plagiarism, similarity, originality or copying check, before a report is published or submitted, or when wording looks lifted from a source. Writes plagiarism.md and does not edit the report.
disable-model-invocation: true
---

# Plagiarism

A gate, not an editor. You produce a similarity report; the author or `/repair`
acts on it.

**Scope comes from the request.** The default is the run's master (`runmeta.py`
names it). A path to any Markdown file works too, with no run behind it: then only
`--urls` and `--corpus library` supply sources. When the author names a section,
check the whole document (scores need it) and report that section's rows.
If the request refers to a hand edit, run `saved_check.py <run>` first and stop
when it exits 1.

## What it catches, and what it cannot

| Detector | Catches | Misses |
|---|---|---|
| Verbatim (word 5-gram fingerprints, longest common run, 8 words or more) | copied sentences and fragments, with or without a citation | text never stored or found |
| Close paraphrase (content-word overlap and word order within one source window) | a source sentence with words swapped, "patchwriting" | heavy restructuring, translation |
| Exact-phrase web search | wording from pages the run never read, including text a model reproduced from memory | paywalled journals, student-paper archives |

Turnitin's advantage is its private archive of papers and journals; no free tool
reaches it, and free web checkers search only public pages. The sources most likely
to have been copied here are the ones the run read, and those are checked in full.
`plagiarism.md` says what was not covered; repeat that limit to the author.

## 1. Check against the run's own sources

```bash
python3 .claude/scripts/plagiarism.py check outputs/<slug>
```

The corpus is the stored copy of every evidence row's URL in `library/` (the
row's quote when no copy exists), plus every file in `external_data/`. Text from
`external_data/ai_reports/` is classed `ai-report` and always rated High: model
output is not a source. Add `--corpus library` to compare with every page in the
shared library too, which catches wording carried over from another run.

## 2. Search the web for the passages no source explains

```bash
python3 .claude/scripts/plagiarism.py probes outputs/<slug> --limit 12
```

It prints the most distinctive sentences that matched nothing, each as a ten-word
exact phrase. Spawn one `general-purpose` subagent with the phrases and the run
path. It must:

1. Run each phrase as a quoted WebSearch.
2. For each plausible hit, confirm with
   `python3 .claude/scripts/library.py fetch <url> --run <slug> --grep "<three or four distinctive words>"`.
   A snippet alone is not a match.
3. Write the confirmed URLs, one per line, to `outputs/<slug>/notes/plagiarism-web-urls.txt`.
4. Return at most 150 words: phrases searched, URLs confirmed, phrases with no hit.

Then rerun the check with those pages added:

```bash
python3 .claude/scripts/plagiarism.py check outputs/<slug> --urls outputs/<slug>/notes/plagiarism-web-urls.txt
```

Skip this step only when the author asks for a sources-only check; say so in the summary.

## 3. Review the findings

Read `plagiarism.md` (not the whole report: each finding carries its sentence and
line). For every High and Medium finding decide:

- **Dismiss** a match that is a proper name, a title, an organisation, a defined
  technical term, a regulation or a figure with its unit. These are not plagiarism.
- **Confirm** the rest, and write a fix specific to the passage in one or two
  lines: which words to quote, or what to lead the rewritten sentence with.
  Never write the replacement sentence: that is the author's or `/repair`'s.

Append to `plagiarism.md`:

```markdown
## Assessment

Originality 97.8%, risk 1.4% (Low). 3 findings confirmed, 2 dismissed.

| # | Section | Decision | Fix |
|---|---|---|---|
| P1 | 3. Market size | Confirmed | Quote "the largest single-year rise since records began" with [E14], or lead with the figure and drop the source's phrase. |
| P2 | Limitations | Dismissed | "Golden Triangle of London, Oxford and Cambridge" is a place name. |
```

Leave the script's rows unchanged. The scores are the script's; when dismissals
change the picture, say so in the Assessment line rather than editing a number.

## 4. Report to the author

In chat, give: originality, risk score and band, the sections rated High or Very
high, each confirmed High finding with its fix, and what the check did not cover.
Point to `plagiarism.md` for the rest. To apply the fixes, the author edits by hand
or types `/repair <run> plagiarism.md`.

| Band | Risk score | Meaning |
|---|---|---|
| Low | under 5% | normal for a cited report; review any High finding anyway |
| Moderate | 5 to 15% | fix the High and Medium findings before publishing |
| High | 15 to 30% | the report reuses source wording in several places; fix before it goes out |
| Very high | 30% and over | sections are assembled from source text; rewrite them from the evidence |

Quoted text that matches its source is excluded from originality, as Turnitin's
"exclude quotes" does, but a quoted share above 10% is worth mentioning: the
report leans on other people's words.

## Anti-patterns

- Reporting "no plagiarism" from a low score. The score covers the corpus that was checked, nothing more.
- Rewriting the report from this stage. It writes findings; it does not edit `report.md`.
- Treating a cited verbatim run as acceptable. A citation credits the idea; copied wording still needs quotation marks.
- Dismissing an `ai-report` finding because the text is accurate. It still has no source.
