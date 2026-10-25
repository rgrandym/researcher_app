---
name: expand
description: Continue researching over an already-finished report and weave the result into it — deepen a section, add an angle the reader asked for, refresh stale figures, close a known gap, or pivot the narrative. Use when the user has read a report and wants more on a topic/area/section, says "expand on X", "go deeper on X", "what about Y", "update this", "extend the section on Z", or hands back a finished report with follow-up questions. Updates existing sections where the topic already lives and creates new ones in logical order where it does not; preserves the audit trail and re-runs the quality gates on what changed.
disable-model-invocation: true
---

# Expand

**Which document.** When the run has more than one master (an audit and a revised
document), act on the one the request names, or ask; then read it wherever this
skill says `report.md`. A revised document keeps its own form and citations.
Doctrine: `.claude/references/masters.md`.

A finished report is a **checkpoint, not an artifact to append to.** The reader
came back with a question, which means the report was incomplete in a way the
brief did not anticipate. Your job is to research that, and then to make the
document read as though it had always covered it.

The failure mode this skill exists to prevent: a report that grows a "Additional
findings" section at the bottom, contradicting paragraph four, with a confidence
statement that no longer describes the document.

## 1. Open a round, don't start a run

Extensions live **inside the original run folder**. Never scaffold a new dated
folder — that severs the new evidence from the ledger it has to reconcile with.

```bash
python3 .claude/scripts/new_round.py outputs/<slug>          # creates and prints rounds/rN/
python3 .claude/scripts/new_round.py outputs/<slug> --list   # the rounds that exist
```

**Open rounds with the script, never by counting with `ls`.** A shell alias on `ls` (lsd,
exa, anything taking different flags) makes `ls -d …/rounds/*` fail and print
nothing, the count comes back zero, and the round is created as `r1` **on top of
an existing r1**, overwriting that round's `ask.md`, `reconcile.md` and
`diff.md`. Those files hold the author's verbatim follow-up and cannot be
reconstructed. This has happened once in this workspace.

**Never write into a round directory that already contains files.** If the
target exists, stop and recount.

Each round gets `rounds/rN/` holding `ask.md`, `notes/`, `reconcile.md`, and
`diff.md`. Evidence still appends to the run's single `evidence.jsonl` with fresh
sequential IDs — one ledger per run, always.

Write `rounds/rN/ask.md` first, before searching, and put the user's follow-up in
it **verbatim**, exactly as `prompt.md` holds the original. Then add your reading
of it: which sections it touches, and what would count as answering it.

## 2. Read the report before researching it

**First, check the saved report for the author's own edits.** Run the section
guard before anything else:

```bash
python3 .claude/scripts/section_guard.py check outputs/<slug>/report.md
```

Do not run `saved_check.py` as a prerequisite for an ordinary `/expand`. Its exit
1 means only that no author save followed the agent's last write. That is the
normal state when the author asks for new research without editing the report.
The author has already authorised the expansion, so continue from the saved
document when the guard is clean. Do not ask for confirmation on this result.

If the author says they edited the document, or the guard reports changes, first
follow `.claude/skills/user-edits/SKILL.md`, including its save check. If the
author explicitly says there is an unsaved buffer, ask them to save it before
writing to the report, then resume this expansion after the edit is absorbed.
If the guard has no baseline, report that containment cannot yet be checked and
establish a baseline from the current saved document before changing it. A
missing baseline alone does not cancel the authorised expansion.

If the guard shows sections moving that no round moved, the author edited the report
by hand: absorb that first (read `.claude/skills/user-edits/SKILL.md` and follow
it), re-snapshot, and only then open the round. The integration step proves
containment against the snapshot and restores any section that drifted, so a
round started over unabsorbed edits would put the author's own sections back to
their old text.

Then the read itself. Cheap and mandatory: you are about to spend tokens finding
things the document may already say.

```bash
python3 .claude/scripts/section_map.py outputs/<slug>      # the section map: lines, words, [E#] per section
grep -c "^{" outputs/<slug>/evidence.jsonl               # what is already sourced
cat outputs/<slug>/repair-log.md                         # what was left open on purpose
```

Read sections through the map, not the file: `section_map.py outputs/<slug> --show
"Limitations"` prints one section with its line numbers, and `--find E19` names
the sections that cite a source. The whole report is read end to end only in the
round-three coherence check below.

`repair-log.md` and the Limitations section are the highest-value read here: an
open finding or a named gap is often exactly what the user is now asking about,
and it will tell you what was already tried and why it failed. Re-running a search
that was already logged as fruitless is the most common waste in this skill.

## 3. Classify the ask — it determines everything downstream

| The user wants | Research shape | Reconciliation shape |
|---|---|---|
| **Depth** on a section that exists | 1–3 scouts, narrow briefs under the existing sub-question | Rewrite that section; the answer probably survives |
| **A new angle** the brief excluded or missed | New sub-question added to `brief.md`, 2–4 scouts | New section, plus a check that no existing conclusion assumed the angle away |
| **Refresh** — is this still true? | Re-verify the load-bearing claims first; only re-scout what moved | Surgical figure/date edits, then re-check everything downstream of each changed number |
| **Close a known gap** | Read the gap's entry first; try the channels not yet tried | Fill the hole; move it out of Limitations and out of `## Data still to obtain` |
| **Challenge** — "I don't believe finding 3" | One dissent scout tasked with building the strongest case against it | Either the finding survives with the counter-case stated, or the answer moves |
| **Pivot** — "frame this around cost, not compliance" | Usually none; occasionally 1–2 scouts for the newly load-bearing dimension | Restructure. See below — this is an editorial ask, not a research one |

**Say which one you picked.** These produce very different documents, and the user
can correct you in one word before you spend anything.

## 3b. Check what the author supplied

```bash
python3 .claude/scripts/external_index.py scan outputs/<slug>
```

An author who asks for more depth has often just dropped the source that
provides it. Unread files are read before any new searching, because they change
what still needs to be searched for. Doctrine:
`.claude/references/external-data.md`.

## 4. Update the brief, then research

Append to `brief.md` under a `## Round N` heading: the new sub-question(s), what
changed about scope, and what is still out of scope. A brief that no longer
describes the report is how a document loses its spine over three rounds.

Then research as `.claude/skills/research/SKILL.md` describes from its section 2a
onwards (supplied files, gap hunt, scouts, coverage audit): scouts, isolated
contexts, digests back. Skip its sections 1 and 2. The run folder, the prompt and
the brief already exist, and scaffolding a new run here is the failure step 1
forbids. Stage skills load from their files, never through the Skill tool. Two
rules specific to extension:

- **Give every scout the existing position.** A scout that does not know the
  report already concluded X cannot tell you it found evidence against X. Put the
  relevant claim and its `[E#]` in the brief, and ask explicitly: *does your
  evidence support, qualify, or contradict this?*
- **Start from what the workspace holds.** `python3 .claude/scripts/kb.py search
  "<terms>"` finds rows other runs already established on the round's question;
  put them in the scout brief under ALREADY ESTABLISHED (research skill §2c).
- **Claim a fresh ID range** above the current maximum, and tell each scout its
  range. `grep -o '"id":"E[0-9]*"' evidence.jsonl | sort -t E -k2 -n | tail -1`.

Each scout writes its digest to `rounds/rN/digests/<topic>.md`; name that path in
its brief.

**Steps 5 to 6 run in a `report-writer` agent** (`MODE: INTEGRATE`), so the report
never enters this thread. Brief it with the run, the round folder, the in-scope
sections you declared, and the round's digest files. It writes `reconcile.md`,
edits `report.md` within scope, writes `diff.md`, runs the gate and the section
guard, does the round's voice and diction pass, lists every new or edited claim in
`rounds/rN/to-verify.md`, and hands back a summary. If it returns `SCOPE`, declare
the wider blast radius to the author in one line and call it again with the new
set. If it returns `QUESTION` (a pivot it cannot restate in one sentence, a
placement only the author can decide), put the question to the author and call
it again with the answer. If the author
asked to see `reconcile.md` before any edit, brief the writer to stop after
writing it, show the author, then call it again to integrate. The rules below are
what the writer follows; you need them to judge its handover, not to do the work.

## 5. Reconcile — the part that is not research

New evidence lands in a document that already made commitments. Write
`rounds/rN/reconcile.md` before touching `report.md`, classifying every new
finding against the existing text.

**If the user asked to see the plan first — "show me reconcile.md before you edit"
— stop here and show it.** This is a cheap checkpoint and a good habit to honour
without being asked whenever a round produces a `CONTRADICTS`, or whenever the
placement of `NEW` material is a judgment call: catching a misplacement before it
is written costs a sentence, catching it after costs a section.

| Verdict | What it means | What you do |
|---|---|---|
| `CONFIRMS` | Independent support for something already claimed | Add the `[E#]`. Consider upgrading the language — this is the one case where confidence may rise |
| `DEEPENS` | New detail under an existing claim | Extend that section in place. Do not create a new one |
| `QUALIFIES` | The claim is true but narrower than stated | Edit the claim where it appears **and everywhere it is restated** — Answer, heading, Limitations, confidence statement |
| `CONTRADICTS` | Better evidence says otherwise | Stop. This is a blocking-class change: fix the claim, then trace every conclusion that rested on it |
| `SUPERSEDES` | Same fact, newer figure | Replace the number and its period. Check every derived figure and every chart that used it |
| `NEW` | Genuinely new ground | New section, placed by decision-relevance — not appended at the end |
| `REDUNDANT` | Already in the report | Record it and move on. Do not restate a finding for emphasis |

**Then trace the blast radius.** For every `QUALIFIES`, `CONTRADICTS`, or
`SUPERSEDES`, grep the report for the claim's evidence IDs and for the number
itself, and check each hit — including figure specs, table cells, the Answer, the
Limitations section, and the confidence statement. A changed number that survives
in one chart is the defect this whole workspace exists to prevent.

```bash
grep -n "E19\|42.5\|€42" outputs/<slug>/report.md
python3 .claude/scripts/figures.py check outputs/<slug>/report.md
```

## 5b. Narrative pivots

A pivot changes what the document *argues*, not what it knows. Two ways one
arrives: the user asks for a different frame, or a `CONTRADICTS` finding makes the
existing frame untenable.

Either way the work is the same and it is editorial, not additive:

1. Restate the thesis in one sentence under the new frame. If you cannot, the
   pivot is underspecified — ask before rewriting anything.
2. Re-derive the section order from the new thesis. Sections keep their evidence
   and lose their old connective tissue; a section that only existed to serve the
   old argument is cut, not demoted to an appendix.
3. Rewrite the title, `## Answer`, and every heading. Headings carry the argument,
   so a pivot that leaves them untouched has not happened.
4. Re-read end to end. A pivot done section-by-section produces a document arguing
   two things, which is worse than either.

**Evidence never moves to serve a frame.** If the new thesis is not supported by
what is in `evidence.jsonl`, that is a research round, not a pivot — and if the
evidence contradicts it, say so plainly rather than writing the requested story.

## 6. Integrate so the seams don't show

Edit `report.md` in place, surgically, one finding at a time. Never append a
round-shaped section — **the reader must not be able to tell which round wrote
which paragraph.** If the extension makes a section long enough to need splitting,
split it by argument, not by vintage.

**Sections you did not set out to change must come through byte-identical.** Name
the in-scope sections before editing, and prove it afterwards:

```bash
python3 .claude/scripts/section_guard.py check outputs/<slug>/report.md --allow "3.3" --allow "Limitations"
```

A `DRIFT` line is a containment failure — restore that section to its baseline
text. Blast-radius edits (§5) are legitimate and go in the `--allow` set, but they
are *named in advance*, not discovered afterwards. "I tidied it while I was there"
is the failure this check exists to catch, and it is how a user's own wording
quietly disappears between rounds.

Order of operations, because getting this backwards produces an incoherent draft:

1. Does the **top-line answer** still hold? Fix `## Answer` and the title first.
2. Section-level edits, in decision-relevance order.
3. Exhibits: update the affected figure specs, add new ones where the new data has
   a shape worth showing.
4. `## What would change this` and `## Limitations` — a closed gap comes out, a
   newly discovered one goes in.
5. `## Data still to obtain` — rebuild from `figures.py gaps`.
6. `## Sources` — add the new rows.
7. The confidence statement, last, because everything above feeds it.

Write `rounds/rN/diff.md`: what the round changed, in the reader's terms —
*"the headline moved from 'stalled' to 'stalled outside Iberia'"* — not a list of
edits. This is what the user reads to know whether their question was answered.

## 7. Re-run the gates on what changed

Extension without re-verification is how a clean report acquires an unverified
claim. This step runs from files too; the report stays out of this thread.

- **Verify** every claim in `rounds/rN/to-verify.md`: the new claims **and every
  claim the round edited**, because an edited sentence is a new claim. Read
  `.claude/skills/verify/SKILL.md` and run it scoped to that list, with
  `source-verifier` agents as usual.
- **Critique** again if the answer moved, if a `CONTRADICTS` landed, or if this is
  round three or later: read `.claude/skills/critique/SKILL.md` and spawn
  `report-critic`. Reports drift toward incoherence across rounds, and the drift
  is invisible from inside.
- **Repair** whatever those return, in a `report-writer` agent with
  `MODE: REPAIR`, the round named, and the round's sections of `verification.md`
  and `critique.md` as the findings. Verification and critique can run at the same
  time; repair waits for both.
- **The writing passes belong to the writer**, during integration and repair:
  `report/references/anti-slop.md` (rounds add hedges and throat-clearing such as
  "As noted above…"; the document has no rounds), the gate's voice findings,
  `<run>/voice.md` (the narration mode is fixed for the life of the report), and
  the `ECHO`, `ECHO-NEAR`, `OPENER` and `DICTION` lines for the touched sections
  (`.claude/references/diction.md`; deliberate terms go in `outputs/<slug>/voice-terms.txt`).
  Check its handover says the gate is clean; do not redo the pass here.

Append to `verification.md` and `critique.md` under a `## Round N` heading rather
than overwriting. The audit trail is cumulative — that is the point of it.

Then re-snapshot, so the next round and any manual edit measure from here:

```bash
python3 .claude/scripts/section_guard.py snapshot outputs/<slug>/report.md
```

## 8. Report back

```
ROUND 2 · depth on vendor pricing
Asked:    <the user's words>
Found:    9 new sources (6 primary), E44–E52
Changed:  CONFIRMS 3 · DEEPENS 2 · QUALIFIES 1 · CONTRADICTS 1 · NEW 1
ANSWER:   moved — "stalled in regulated markets" → "stalled everywhere except Iberia"
Gates:    audit clean · 11 claims re-verified · critique re-run (0 blocking)
Still open: <gap> — <what would close it>
```

State plainly if the round did **not** change the answer. "Three more sources, same
conclusion, confidence up from Medium to High" is a good outcome and a real
finding — an extension that must move the answer to feel worthwhile is an
extension that will move it whether or not the evidence says so.

## Rounds are cheap; incoherence is not

There is no limit on rounds. But from round three, before researching, have the
whole report read end to end once by a `report-critic` agent, asked the question no
individual round asks: *does this still read as one document with one argument?* If it does not, the right move
is a structural rewrite of the affected part — not another careful local edit.
