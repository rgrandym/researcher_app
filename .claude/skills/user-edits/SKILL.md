---
name: user-edits
description: Absorb edits the user made by hand to a run's master document, the research report.md: take their additions, deletions and rewrites as they stand, then fix the grammar, flow, transitions, repetition and reference numbers around them so the document reads as one piece again. Editing is the default and no research runs unless the user asks for it. Use when the user says they edited/changed/added/deleted something in the report, hands back a manually modified report or piece, or wants the story line adjusted around their changes. Every concept they introduced survives into the result; changes stay inside the sections they touched unless a wider blast radius is declared first.
disable-model-invocation: true
---

# User edits

The user has written in their own document. Your job is to make the document
work with what they wrote: their additions kept, their deletions respected,
their rewrites left standing, and the prose around all of it repaired so a
reader cannot tell where the seam was.

The invariant is **their concepts, not their sentences.**

```
PRESERVE   every idea, angle, framing and emphasis they introduced
REPAIR     the grammar, flow, transitions, repetition, and reference numbers
NEVER      drop a concept, dilute it, or quietly argue against it
```

**The default job is editorial, not investigative.** Grammar, flow, connective
tissue, repetition, reference integrity, and the line the argument runs along.
No searching, no new sources, no fact-checking of what they wrote, unless the
user asks for it in this round. See §0.

## 0. Decide which job you are doing

Three jobs, and only the first runs by default.

| Job | Runs when | What it does |
|---|---|---|
| **Edit** (default) | Always | Absorbs their changes; fixes grammar, flow, transitions, repetition, reference numbers, and the story line around them |
| **Develop** | The user asks, or their text is an explicit note to you ("add something on X", "expand here") | Researches and writes the new material, per §5 |
| **Validate** | The user asks: "check this", "is that right?", "verify what I added" | Fact-checks their statements against sources, per §6 |

Rules for choosing:

- **Do not research on your own initiative.** A sentence the user asserted is
  taken as written. If it needs a citation it does not have, or if you believe
  it is wrong, **say so in chat and leave the text alone**. Their claim, their
  call.
- A note plainly addressed to you is a request to develop that spot, and only
  that spot. Everything else in the round stays editorial.
- When their text needs a fact you do not have, do not invent one and do not go
  looking. Write what the surrounding evidence already supports, and list the
  gap in your report-back.
- If you think a round would benefit from research or validation, offer it in
  one line at the end. Do not perform it.

## 1. Establish containment and scope

**Name the document first.** A run's master is `report.md`, as `.run.json`
declares through `runmeta.py`. Every command below is written against `$doc`,
and this is where it comes from:

```bash
run=outputs/<slug>
doc=$(python3 .claude/scripts/runmeta.py $run --masters | head -1)
mirror=$run/.voice-mirror-$(basename $doc .md).md
```

The rule that decides the round: **their
concepts, not their sentences.**

**Run the save check next, before anything else.** It answers the one question
you cannot answer by reading: is the edit the user is describing actually on
disk, or still in their editor?

```bash
python3 .claude/scripts/saved_check.py $run $(basename $doc)   # exit 1 = nothing saved, STOP
```

An agent reads files; an editor holds unsaved buffers; nothing bridges the two.
When this exits 1, **stop the round and say so in one line.** Do not proceed to
the diff, do not infer the edit from the chat, and do not report a clean result:
a round run against the agent's own text will find no changes and will say so
confidently, which reads as "your edit was fine" rather than "your edit is not
here". Offer `--wait 120` if the user is at the keyboard, and `--rescue` if a
previous save has been overwritten and needs recovering from editor history.

The same exit-1 state is also the warning that the user's *next* save will
overwrite whatever the agent wrote in the meantime, because their buffer
predates it. Say that too; it is the more expensive half.

Then the normal checks:

```bash
python3 .claude/scripts/section_guard.py check $doc   # which sections moved
python3 .claude/scripts/audit_citations.py $run $(basename $doc)       # what broke
python3 .claude/scripts/voice.py learn $doc           # capture how they write
```

Run `learn` **before you touch the file**, or the capture is contaminated with
your own prose. It diffs the report against the mirror of what an agent last
wrote and files the author's passages into `.claude/voice/corpus/`. If it
reports no mirror, say so: the voice sample for this round is lost, and the fix
is to run `voice.py mark` at the end of every write from now on.

`check` names the changed sections. Read **only those** — a user edit is local.

Run `external_index.py scan $run` only when the user dropped a file in or asked
for research. In an editorial round there is nothing to mine.

If the baseline is missing or stale, say so; you can still work, but you cannot
prove containment and the user should know which they are getting.

If the guard shows nothing and the user says they edited something, the cause is
almost always an unsaved buffer, which `saved_check.py` names directly. Failing
that, **check the export copies** (`export/<style>/report.md`): editing a derived
file instead of the master is a rarer but destructive mistake, and their work is
one `/export` from deletion.

Declare your `--allow` set now, in writing. It starts as the sections they
touched. It grows only by the rule in §7, and only out loud.

## 2. Read what they actually did

Get the real diff before interpreting anything:

```bash
diff -u $mirror $doc | head -200
```

Four kinds of change, and each is handled differently:

| They did | You do |
|---|---|
| **Added text** | Keep the idea. Rewrite as needed so it sits in the paragraph properly, carries the surrounding register, and connects to what comes before and after |
| **Deleted text** | Respect it, and do not raise it. Then repair only what depended on it: a dangling "as shown above", a citation now orphaned in `## Sources`, an exhibit reference, a sentence whose subject was in the deleted line |
| **Rewrote a sentence or paragraph** | Their wording stands. Fix only what is broken around it: agreement with the next sentence, a repeated word, a transition that no longer lands |
| **Reordered or moved material** | Follow the new order. Rebuild the openings so each paragraph opens on something the previous one handed it |

Then read the edit as intent:

| Signal | Almost always means |
|---|---|
| A note addressed to you — "expand here", "add something on X" | Develop that spot (§5). Delete the note |
| A question in the text | Answer it if you can from the report's own evidence; otherwise put the question to the user and leave the text unchanged |
| A bare concept or fragment dropped mid-section | They want it stated properly in the prose. Write it out from what the section already supports; flag it if it needs a source you do not have |
| Rough prose asserting something new | Their point, their claim. Tidy the sentence, keep the assertion, mark it for validation only if they asked |
| A reframing of an opening, a heading, or a claim's emphasis | Directive, and often document-wide — see §7 |
| A precise, finished sentence replacing yours | Literal. Keep the wording |
| A typo or grammar fix | Literal. Nothing to do |

**A deletion is a finished decision, and it is not reported back.** An author
who removes a sentence usually did so because they did not like how it sounds,
or because the text works without it. Do not list what they cut, do not offer to restore it,
and do not carry it into the report-back as a loss. Repair what depended on the
deleted line and carry on.

The single exception is meaning: raise it only when the deletion **changes what
the document claims** — a qualifier that bounded a figure, a caveat a conclusion
rested on, or a registered gap that would otherwise vanish from the reader's
view. Then it is one line, naming what the claim now says without it. Taste is
never the reason, and "it was well sourced" is not a reason.

**When you cannot tell, ask in one line rather than guessing.** Guessing wrong
in the editorial direction costs a comma; guessing wrong in the research
direction costs a round the user did not want.

**The same edit is read twice, for two different things.** As *content* it is
handled by the tables above. As *voice* it is a sample of how the author writes,
and only the finished-prose rows are that: a rough note or a question is
content, and it is noise in the corpus. After `learn` has captured the round,
open the corpus file and delete the captures that were directives rather than
prose. See `.claude/references/voice.md`, and `/narrator` §4.

## 3. List what you are keeping, before you edit

Write the list out explicitly, in chat, or in `rounds/rN/ask.md` for a large
absorb. One line per thing the user introduced or removed:

```
C1  opening reframed as an introduction that sets up the question, not answer-first
C2  new sentence on academic core facilities as a distinct buyer segment
C3  deleted the paragraph on distributor margins
C4  "consistency argument outweighs the cost argument", added in §3.3
```

**This list is the contract.** Every entry is accounted for in the finished
text, and reported line by line when you are done. It prevents the two failure
modes: a concept quietly dropped because it was awkward to place, and a concept
technically present but buried in a subordinate clause carrying none of the
weight the user gave it.

If a concept sits against the report's own evidence, **it still does not
disappear.** Leave what they wrote, flag the conflict in chat with the opposing
`[E#]`, and let the user rule.

## 4. Edit: the default round

This is the work. Take it section by section, over the sections the guard named.

**Grammar and sentence mechanics.** Agreement, tense, articles, plurals,
punctuation per `.claude/voice/profile.md` (no em-dashes), British spelling. A
sentence the user typed quickly gets tidied; a sentence they clearly crafted is
left alone.

**Repetition and word choice.** Their new sentence usually repeats a word from
the sentence beside it, because they wrote it in isolation.

```bash
python3 .claude/scripts/voice.py echo $doc
```

Fix the ordinary echoes by restructuring first, pronoun second, synonym third
and only when it carries the same meaning exactly. Terms of art stay fixed and
go into `$run/voice-terms.txt`. Never let a synonym move the strength of a
claim: "reduced" is not "eliminated". Doctrine:
`.claude/references/diction.md`.

**Flow within the paragraph.** The inserted sentence sits where the argument
reaches it, not where the cursor was. Old information at the front of the
sentence, new information at the end, so each sentence hands the next one its
subject.

**Flow between paragraphs.** Read the whole section aloud in your head, then
check that each paragraph opens on something the previous paragraph put in the
reader's hands. Rewrite the openings, do not bolt on connectives: a paragraph
that now begins "Additionally," is a paragraph that was appended.

**The story line.** A user edit often moves the argument slightly, and the
section has to move with it. Read the section's paragraph openers in sequence:
they should trace the line the section now argues. If the edit changed what the
section concludes, adjust the section's own framing to match, and check the
heading still describes it. If the line moves beyond this section, that is §7.

**Reference numbers.** Their edit almost always breaks something here:

- Evidence IDs that travelled with a moved sentence, or vanished with a deleted
  one. `[E#]` stays attached to the claim it supports, and only to that claim.
- `## Sources` entries now cited by nothing, and citations with no entry. The
  gate reports both directions after each write.
- Exhibit numbers and their references in the text, renumbered only by
  `figures.py build`.
- Cross-references: "as section 3 showed", "the table above", "see below". A
  deletion or a reorder strands these silently.

**The seam.** When you are done, a reader cannot point at the sentence where the
edit starts. Their note, stub, or question does not ship: it was an instruction
to you.

## 5. Develop: only when asked

Runs when the user asked for research, or where they left a note asking for
material that does not exist yet. It is scoped to that spot, not to the round.

- Spawn `research-scout` subagents, one per concept needing evidence, in a
  single message. Give each the specific statement and ask explicitly whether
  the evidence **supports, qualifies, or contradicts** it.
- Claim a fresh evidence ID range above the current maximum. Append to the run's
  `evidence.jsonl`; never rewrite it.
- Then write the passage properly: the claim, the evidence, the qualifier that
  matters, and the implication. Depth matches the neighbouring prose, because a
  developed concept thinner than the text around it reads as a patch.
- Placement follows their placement. They chose where the idea goes. Moving it
  to a more logical home is a structural decision: propose it, do not perform
  it.

| Evidence says | The text becomes |
|---|---|
| Supports | The concept, stated plainly and cited. Their emphasis preserved |
| Qualifies | The concept with its real boundary. Say in chat that you narrowed it and why |
| Nothing found | The concept stays, marked `[UNVERIFIED]`, with what you searched reported. Never attach a loosely-related citation to make it look sourced |
| Contradicts | Their concept stated with the counter-evidence beside it. Flag in chat. Do not silently write the opposite of what they asked for |

## 6. Validate: only when asked

Runs when the user asks you to check what they wrote. Then, and only then, their
sentences are treated as claims: extracted, traced to sources, and graded as
`/verify` would. Report the verdicts and let the user decide what changes. Do
not rewrite their assertion on the strength of your own check without saying so.

An unasked-for validation pass is not a favour. It spends a round on work the
user did not request, and it tends to end with the agent arguing against the
document's owner.

## 7. When the edit changes the report's direction

A reframing, a changed emphasis, or a concept that contradicts an existing
finding has **blast radius beyond the edited section**, and this is the case the
strict section-containment rule must not block.

The reconciliation: containment was never "nothing else may change". It is
**"nothing else changes without being declared first."**

1. Name the blast radius before editing: which sections the new direction
   touches, and what happens to each. `grep` the report for the claim and its
   `[E#]`s.
2. **Show the user that list and get agreement** when the answer, the title, or
   a top-line conclusion moves. This is cheap now and expensive later.
3. Add those sections to `--allow`, so the guard reports them as in-scope rather
   than as drift.
4. Then work in the order of `expand`'s pivot procedure (§5b there): thesis
   first, then section order, then headings, then the confidence statement last.

A user asking to change the report's direction is making a legitimate request,
not attacking the document. Carry it out fully: a half-pivoted report argues two
things and is worse than either. What you must not do is let the evidence bend.
If the new direction is not supported, say so plainly and write what is.

## 8. Reference integrity

```bash
python3 .claude/scripts/audit_citations.py $run $(basename $doc)
```

Reports both directions: a `## Sources` entry nothing cites any more (what a
deleted citation strands), and a citation with no entry. Fix both, and add
entries for any rows a `develop` pass produced.

**Evidence IDs are identifiers, not sequence numbers.** When `[E45]` leaves the
document, `[E46]` does **not** become `[E45]` — renumbering would break every
row in `evidence.jsonl`, every note file, and the audit trail. The Sources list
loses the entry; the ledger keeps the row. Exhibits are the opposite:
positional, and renumbered only by `figures.py build`.

## 9. Close out

```bash
python3 .claude/scripts/section_guard.py check $doc --allow "<sec>"…
python3 .claude/scripts/audit_citations.py $run $(basename $doc)
python3 .claude/scripts/figures.py check $doc
python3 .claude/scripts/voice.py lint $doc               # must exit 0
python3 .claude/scripts/section_guard.py snapshot $doc   # only when clean
python3 .claude/scripts/voice.py mark $doc               # only when clean
python3 .claude/scripts/voice.py profile --rebuild                 # fold in what you learned
```

The prose you wrote around the author's edit obeys `<run>/voice.md` and
`.claude/voice/profile.md` like any other prose. This is the stage where the
seam shows most: their sentences already sound like them, and yours have to.
`ECHO` and `DICTION` lines from the lint are advisory, and the paragraphs you
edited are exactly where they are worth reading.

`check` must exit 0. `ALLOWED` is expected; `DERIVED` covers `## Sources` and
`## Data still to obtain`, which are rebuilt; `DRIFT` is a failure — restore
that section or declare it under §7 and re-run.

Renaming a heading appears as `REMOVED` + `ADDED`, so allow **both** names.

Verification runs only on material a `develop` pass produced, or when the user
asked for it. An editorial round changes no claims, and it does not need one.

If the user edited an export copy, rebuild it from the master afterwards so the
two agree.

## 10. Report back against the list

```
MODE      edit (no research run)
ABSORBED  4 changes in 2 sections (§1 Introduction, §3.3)
  C1 introduction reframed   → §1 openings rebuilt; answer now lands in ¶2
  C2 core facilities sentence → kept, tidied, connected to the segment argument in ¶3
  C3 distributor paragraph deleted → respected, not itemised; two cross-references
                                     repaired, [E812] now orphaned in Sources and removed
  C4 consistency over cost   → kept as written; reads against [E724], see FLAGGED
EDITED    11 grammar fixes · 6 echoes removed · 3 paragraph openings rebuilt
REFS      1 Sources entry removed · 2 exhibit references renumbered · no IDs renumbered
STORY     §3.3 now concludes on consistency; heading unchanged, still accurate
VOICE     2 passages captured to corpus (1 filed as prose, 1 discarded as directive)
          lint clean · no new stated rule inferred
CONTAINED 31 of 34 sections byte-identical · guard exit 0
FLAGGED   C4 as written reads against [E724]. Left as you wrote it; say the word
          and I will check it or rewrite it
OFFER     C2 asserts a segment size with no source in the run. Want me to research it?
```

State the mode and the containment result every time, including when clean, and
account for every entry on the list, including the ones that survived unchanged.
An unstated guarantee is not one, and a concept you cannot point to in the text
was not integrated.
