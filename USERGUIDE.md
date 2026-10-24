# User guide

A workspace for producing research reports whose every claim can be traced to a source that actually says it.

The design assumption: an AI writing research prose unaided will be fluent, plausible, and occasionally wrong in ways you cannot see. So writing is separated from checking, the checking is adversarial, and the parts that can be verified by a script are verified by a script instead of by a model.

---

## Quick start

Just describe what you want researched:

```
Research how EU battery labelling rules changed in 2026 and write it up.
```

Claude picks up `/research-pipeline` and runs the whole thing. When you want to drive a single stage yourself, type the slash command:

```
/research    grid battery storage economics in Spain
/report      write it up from outputs/2026-08-12-spain-storage/
/verify      outputs/2026-08-12-spain-storage/draft.md
/critique    same draft
/repair      apply the findings
/export      pdf, Meridian style
/expand      go deeper on the permitting timeline
/user-edits  I rewrote the intro and added a note in §3 — finish it
/brain_storm  Would a more personal opening help this argument?
```

Every stage works standalone. You can hand `/verify` someone else's document and get a fact-check with no research run behind it.

`/polish` rewrites a passage in your voice without changing what it claims. To teach the agents how you write, and what you don't want to read, see **[Teaching it your style over time](#teaching-it-your-style-over-time)**.

`/brain_storm` discusses subjects, angles, structure, and prose with you in chat. It weighs reader impact against precision and evidence, makes concrete suggestions, and leaves editorial decisions with you. It does not change the document.

Three you'll use after the first report is written: **[`/export`](#applying-a-style)** puts it in a professional style and a real file format, **[`/expand`](#continuing-research-on-a-finished-report)** researches further without breaking the document you already have, and **[`/user-edits`](#editing-the-report-yourself)** picks up changes you made by hand.

---

## The pipeline

```
/research  →  /report  →  /verify  →  /critique  →  /repair  →  /export  →  /expand
  gather      write it     is it       does it      fix the      package     research
  evidence                 true?       hold up?     findings     it          further

     ↑            ↑                                       ↑
  external     /narrator                    /user-edits ──┘
  data you     who is reading it,           you edited report.md yourself
  dropped in   and in whose voice
```

**`/research`** — Writes the brief, splits your question into orthogonal sub-questions, then spawns one `research-scout` subagent per sub-question, all in parallel. Each scout searches, fetches, chases citations upstream to the primary source, and records verbatim quotes. Scouts return a ≤400-word digest; the raw material stays on disk.

**`/report`** — Turns evidence into prose. Answer first, headings that are findings rather than topics, every fact carrying its `[E#]` evidence ID, and language calibrated to what the sourcing supports.

**`/verify`** — Extracts every checkable assertion and dispatches `source-verifier` subagents to **re-fetch the cited sources**. Each claim gets one of eight verdicts and an Admiralty grade. `FABRICATED` (the source doesn't exist or doesn't say it) and `CONTRADICTED` block publication.

**`/critique`** — A different question: not "is this true?" but "does this hold up?". A `report-critic` subagent attacks the reasoning — inference gaps, hidden assumptions, missing evidence classes, rival explanations, confidence exceeding sourcing. True facts assembled into a wrong conclusion is what this stage catches.

Standalone `/critique` must launch the independent critic and produce a fresh `critique.md`. If it cannot, the app leaves the review stage incomplete. Open `critique.md` in the app to read the findings, then select **Apply feedback to article**. A popup asks which findings to address and shows any specific questions the critic identified about your intended meaning or experience. You can choose an option, write your own answer, and add directions. The app records those answers before starting `/repair`. Each finding is then recorded as fixed, open, or declined with a reason. Approved final sections stay protected; reopen one yourself if you decide to accept a proposed change there.
If the repair agent discovers another question later, the app presents it in a popup while the repair is paused. The question also remains in the conversation if you close the popup.

**`/plagiarism`** — A similarity check in the manner of Turnitin. It compares the report's wording with the full text of every source the run read, your supplied files, and pages an exact-phrase web search finds, then gives an originality percentage, a plagiarism risk score with a band, a per-section table, and each problem passage with a short fix. It catches copied runs of eight words or more and close paraphrase, and it separates quoted, cited and uncited matches. It writes `plagiarism.md` and leaves the report alone; fix by hand or with `/repair <run> plagiarism.md`. Paywalled journals and student-paper archives are outside its reach, as they are for every free checker.

**`/repair`** — Applies findings surgically, one edit per finding. Every finding ends as `fixed`, `won't fix (reason)`, or `open (needs input)`. Nothing disappears quietly.

**`/export`** — Builds `.docx` / `.pptx` / `.html` / PDF in one of five styles, rendering the report's charts on the way, but only from content that cleared the gates.

**`/expand`** — Continues researching over a report you have already read. Opens a round inside the same folder, researches your follow-up, then **reconciles** — every new finding is classified against the existing text (`CONFIRMS`, `DEEPENS`, `QUALIFIES`, `CONTRADICTS`, `SUPERSEDES`, `NEW`) and edited into place. You should not be able to tell which round wrote which paragraph.

**`/user-edits`** — For when you have opened the document and written in it yourself, whether that is `report.md` or a piece from the writing lane. Your additions, deletions and rewrites stand, and the agent repairs the document around them: grammar, flow between paragraphs, repeated words, reference numbers, and the story line the section now argues. It is an editing pass, so it researches or fact-checks only if you ask. It will not touch a section you did not edit unless it tells you first.

Your stated feelings and opinions are treated as your views. `/user-edits` may suggest a clearer way to express or place them, but does not flag them for lacking a citation. If a view includes a separate factual assertion, the agent handles that assertion under the usual evidence rules.

In the app's Edit tab, choose a report section and **Mark final** once you have approved it. Later agent rounds must leave that section byte-identical. If a new edit calls for a change there, the agent explains the proposed change; use **Reopen section** when you decide to revise it. The app also blocks saves that alter a final section until it is reopened. The HTML tab has controls to zoom the rendered report, and Markdown editors underline spelling and Markdown errors with suggestions or fixes.

**`/narrator`** — Decides who the report is written for, and holds your writing style. Two narration modes: **scientific** for specialists in the field, and **explanatory** for readers who are technically literate but not scientists. Both carry the same claims, the same citations, the same caveats and the same confidence; they differ in how much of each mechanism gets built for the reader. It also runs the style-learning loop described below. Ask for it directly ("write this for non-scientists", "this reads like AI, fix the voice"), or let `/report` invoke it before drafting.

One supporting skill fires on its own: **`/visualize`** — which findings earn a chart, and how figures are written. Context and delegation discipline is standing policy in `CLAUDE.md`, not a skill you invoke.

---

## Editing the report yourself

You are meant to. `report.md` is a plain Markdown file and it is yours to change.

The workspace records a hash of every section when it finishes a round, so it can
tell your edits from its own and prove that later work left the rest of the
document alone.

**A `/user-edits` round is an editing round.** It takes what you wrote as it
stands and repairs the document around it: grammar, sentence flow, the
transitions between paragraphs, repeated words, reference and exhibit numbers,
and the line the argument runs along. It does **not** go and research, and it
does not fact-check what you wrote, unless you ask. If it thinks a sentence needs
a source or looks wrong, it says so in chat and leaves your text alone.

**Your *concepts* are preserved, not your sentences.** Your wording may be
rewritten so a passage reads as one piece; the idea you put there never gets
dropped, diluted, or quietly argued against. It reports back item by item so you
can see where each one landed.

| You write | The agent does |
|---|---|
| A precise sentence replacing one of its own | Keeps your wording |
| A rough sentence | Keeps the point, tidies the sentence, connects it to what sits either side |
| A deletion | Respects it, then repairs what depended on it: cross-references, an orphaned source entry, a dangling "as shown above" |
| A typo fix | Nothing to do |
| A fact, with no citation | Leaves it as you wrote it and tells you it is uncited. Say the word and it researches it |
| An idea, a stub, or a note like *"say something about core facilities here"* | A note addressed to it **is** a request to write that spot, so it researches and writes it there, then removes your note |
| A question in the text | Answers it from the report's own evidence if it can; otherwise puts the question back to you |
| A reframing — a new angle, a changed emphasis, a different direction | Treats it as a **pivot**: names every section it affects, shows you that list, then rewrites the thesis, section order and headings to match |

To get the other two behaviours, ask for them:

```
you   I edited §3. Check what I added is right.        → validates your claims
you   I edited §3, and research the point I made.      → researches and sources it
```

If you delete a citation, its entry comes out of `## Sources` — but evidence IDs
are **never renumbered**, because they key the whole audit trail. `[E46]` does not
become `[E45]` when you cut `[E45]`. Exhibit numbers do renumber, automatically,
at export.

If something you wrote runs against the evidence, your concept is not discarded:
the agent writes what the evidence *does* support, states the conflict in chat with
the source that opposes you, and lets you rule. The document is yours; the
disagreement is a conversation, not a silent reversal.

**Changing the report's direction is a supported operation**, not a fight with the
document. Say what you want it to argue and the pivot runs end to end — thesis,
section order, headings, then the confidence statement. What will not bend is the
evidence: if the new direction is not supported, you get told plainly rather than
handed the story you asked for.

#### A worked example

Open `report.md`, write into it, save, then say so. Suppose you drop three lines into section 3.3:

```markdown
### 3.3 Switching cost is a function of contract length

fleet operators are their own buyer, they buy like a small customer but
run forty sites, so a bad supplier costs forty sites not one

Traction evidence is thin but no longer exclusively company-originated: …
```

Then, in chat:

```
you   I edited 3.3, have a look
```

What comes back:

```
MODE       edit (no research run)
CONTAINED  section_guard: 1 section moved (3.3). 36 byte-identical.
VOICE      1 passage captured. Filed as directive, not prose, so it is not
           learned from as a writing sample.
ABSORBED   C1  academic core facilities as a distinct buyer segment
               → the amplification argument: one lot serves many groups

           Written into ¶2 as a proper sentence and connected forwards: the
           paragraph now opens on the buyer type and closes on the exposure,
           which is what ¶3 picks up. Your line is gone; the point is in
           the argument, where you put it.
EDITED     3 grammar fixes · "lot" was used four times in the paragraph,
           now twice · ¶3 opening rebuilt so it follows from your point
REFS       no citations affected · no IDs renumbered
STORY      §3.3 now ends on buyer exposure rather than phase. Heading still
           accurate.
GATES      audit clean · voice lint clean · figures clean
FLAGGED    the "twenty experiments" multiplier has no source in this run, so
           it is stated as a mechanism, not a figure.
OFFER      want me to research the core-facilities segment and source it?
```

Three things to notice. Your rough line was not returned with the commas fixed and nothing else: the paragraph around it was rebuilt so the point sits in the argument. It landed **where you put it**, not in a more logical home. And the number you asserted was neither sourced behind your back nor deleted: you were told it is unsupported and offered the research as a separate step.

If you had instead written a *finished* sentence, in your own voice, it would have been kept verbatim and filed into the corpus as a writing sample. The workspace treats the two differently on purpose.

#### Changing direction

```
you   I edited the intro. The consistency argument should lead, not the
      cost argument. Cost is the supporting evidence.
```

That is a pivot, so the blast radius comes first and you get to approve it:

```
      This reframing reaches beyond the intro. Sections affected:
        Introduction   thesis reordered, consistency first
        §1            promoted ahead of §2; heading rewritten as a claim
        §2            reframed as the supporting economic test
        §6, §7        risk order and diligence order follow the new thesis
        Confidence    rewritten last, once the argument settles

      Proceed?
```

Say yes and it runs in that order. Say no to any line and it stays out of scope, provably.

---

## Where your work lands

One folder per run, under `outputs/`, named by date and slug:

```text
outputs/2026-08-12-eu-battery-rules/
  prompt.md         your request, word for word, plus any clarifications
  brief.md          the question broken into sub-questions, scope, success criteria
  voice.md          who the report is written for; set once, held by every later round
  external_data/    sources you drop in by hand; indexed so they are read once, not re-read
  coverage.md       every angle looked at, and its status — including the ones you didn't ask for
  evidence.jsonl    every sourced fact: quote, URL, date, source type, grade
  notes/            per-scout verbatim extracts, one file per sub-question
  draft.md          first write-up
  verification.md   claim-by-claim verdicts
  critique.md       reasoning findings, ranked blocking → material → minor
  repair-log.md     what got fixed, what didn't, what's still open
  report.md         the deliverable, always current — charts live here as data, not pictures
  .guard-report.json  section hashes, so edits can be told apart and contained
  figures/<style>/  rendered charts
  rounds/r1/        each /expand round: what you asked, what changed
  export/<style>/   .docx, .pdf, .pptx
  notebooks/        Jupyter notebooks reproducing figures and tables, made by /notebook
```

**Read `report.md` for the answer. Read `verification.md` when you need to trust it. Read `coverage.md` when you want to know what it didn't look at.**

`prompt.md` is written before any searching starts, and holds your exact words — so months later you can tell whether a disappointing report answered a badly-phrased question or answered a good one badly.

Scaffold a run manually if you like:

```bash
bash .claude/scripts/new_run.sh "eu-battery-rules" "your prompt here"
# → outputs/2026-08-12-eu-battery-rules
```

---

## Reading the outputs

### evidence.jsonl

One JSON object per line, one per sourced fact:

```json
{"id":"E7","claim":"EU labelling deadline moved to Aug 2027","quote":"…verbatim…",
 "url":"https://eur-lex.europa.eu/…","publisher":"EUR-Lex","published":"2026-02-11",
 "accessed":"2026-08-12","type":"primary","admiralty":"A1"}
```

`type` matters more than brand name: a Reuters article *about* a regulation is `secondary`; the regulation is `primary`. The pipeline prefers primary and records how many hops it took to get there.

### Verdicts in verification.md

| Verdict | Meaning | Blocks? |
|---|---|---|
| `SUPPORTED` | Source states it; quote matches | |
| `PARTIAL` | True, but the draft dropped a material qualifier | |
| `WEAK` | Only low-grade or single-origin sourcing | |
| `CIRCULAR` | Several citations collapse to one origin | |
| `UNSUPPORTED` | No cited source states it | |
| `STALE` | Was true; superseded | |
| `CONTRADICTED` | A better source says otherwise | **yes** |
| `FABRICATED` | Source doesn't exist, or doesn't contain this | **yes** |

`PARTIAL` is the most common and the most useful. "Installs grew 40%" against a source saying "shipments rose 40% in the twelve months to Q3" is directionally right and factually wrong — the kind of drift that survives casual review.

### Admiralty grades

Two independent axes, from NATO intelligence practice — source reliability `A`–`F`, information credibility `1`–`6`. A reliable outlet reporting an unconfirmed rumour is `B3`. An anonymous leak later confirmed by filings is `F1`. Load-bearing claims want `B2` or better; anything worse gets in-line attribution ("according to <vendor>…") rather than the narrator's voice. Full scale: [.claude/skills/verify/references/admiralty.md](.claude/skills/verify/references/admiralty.md).

### The confidence statement

Every finished report ships with one:

```
Confidence: Medium
Basis: 14 sources, 9 primary; strongest load-bearing source B2.
Checked: 23 of 23 extracted claims; 2 partial (qualifiers restored), 1 removed.
Weakest link: install-base figures rest on one vendor survey [E19] (D2).
Would change the answer: <specific observation>.
```

If it says Medium, the honest answer is Medium. High confidence is not available on single-origin evidence, however many outlets repeated it.

---

## Gaps and data it couldn't get

Two things happen automatically, and they are the parts most worth knowing about.

**It hunts for the questions you didn't ask.** Your brief is your model of the problem, and it's reliably incomplete — if you knew what was missing you'd have asked for it. Before searching, the run sweeps a checklist of dimensions: contested definitions, the implied comparison, jurisdiction and segment boundaries, who has an incentive to be wrong, where the dissent is, what the *negative* case looks like, second-order effects. Everything it looks at lands in `coverage.md` with a status, and every `GAP` and `THIN` row reaches the report. A gap the research noticed and you can't see is worse than one nobody noticed.

The two questions that end every run: *what would an expert immediately ask that this can't answer?* and *if the conclusion is wrong, what's the most likely reason?* — then it goes and searches for that specific thing.

**It builds the table even when it can't fill it.** When a source is paywalled, login-walled, or NDA-only, the row doesn't disappear. You get:

```
| Merid | [NEEDS DATA — 2025 list price · quote via sales portal, login required] |
```

Never `N/A`, never a blank, never a quietly deleted row — because a five-vendor comparison silently reduced to two vendors reads as complete and isn't. In charts the same hole renders as a hatched slot labelled "to obtain". Every hole is collected into a **`## Data still to obtain`** section listing what's missing and the specific step that gets it, so you can finish the document by hand.

It distinguishes three kinds of hole, and the distinction matters: **access-restricted** (someone with an account can get it), **unpublished** (nobody has it), and **not searched** (the run ran out of scope). Only the first is a task for you, and presenting the third as either of the others is treated as a defect.

**And it hands you the list.** A placeholder tells you a hole exists; it does not tell you how to close it. Every source the run could not read is registered with the exact page that failed and the reason, and written to `external_data/WANTED.md`:

```markdown
### B2 · Share of cathode-material demand from grid storage

- **URL:** https://example-analyst.com/report-2026
- **Why it failed:** paywall, GBP 3,400 single-user licence
- **Needed by:** §3.3
- **What is already known:** spot price listed at $14–19/kg by grade
```

That is the shopping list. Fetch what you can, save it anywhere under `external_data/` in any format, and the next stage picks it up as unread, mines it into evidence, and closes the row. Nothing needs renaming and you do not have to tell it which hole the file fills.

```bash
python3 .claude/scripts/wanted.py check outputs/<run>   # what is still open
python3 .claude/scripts/wanted.py build outputs/<run>   # rewrite WANTED.md
```

---

## What the workspace refuses to do

Worth knowing up front, so the behaviour doesn't surprise you:

- **It won't cite a source it didn't fetch.** No URLs, titles, authors, dates, or figures reconstructed from model memory. A blocked or paywalled page is reported as unverifiable, never guessed at from the URL slug.
- **It won't plot a number that isn't in the evidence.** Charts are validated by a script; a figure without an `[E#]` fails the check.
- **It won't export unverified content.** A styled `.pdf` looks authoritative in a way a Markdown draft doesn't. If gates are unresolved, it asks first.
- **It won't repair by going vague.** Turning a wrong number into "significant growth" hides an error instead of fixing it.
- **It won't drop a section because it was hard to source.** Partial ships partial, with the holes visible.
- **It won't claim it answered a question it couldn't.** A failed run says so in the first paragraph and states what would be needed.

---

## Controlling scope and cost

Not every question gets the pipeline. The effort is judged from your question before anything is scaffolded, and it is stated so you can correct it in one word:

| Tier | You asked | You get |
|---|---|---|
| **0 · Direct** | A fact, a date, one number | A few plain sentences in chat with the link. No run folder, no report |
| **1 · Short sourced** | A real question with one answer and a caveat | A few cited paragraphs in chat |
| **2 · Report** | Several sub-questions, a decision rides on it, or you asked for a document | The full pipeline: 3–5 scouts, full verify, one critic, `report.md` |
| **3 · Deep** | Contested or high-stakes — someone will argue with it | 6 scouts incl. a dedicated dissent scout, two critics, two repair rounds |

Say "quick answer" or "go deep on this" to pick directly, and **asking for a document always gets you at least Tier 2** — naming the deliverable is not something the agent may downgrade.

**The tier is re-judged as evidence arrives, in both directions.** A question that sounded simple but turns out contested gets escalated, and you are told. A question that sounded big but resolves to one authoritative source gets handed back short — that is a good outcome, not a shortfall, and the remaining budget is not spent justifying the first guess.

Two things this deliberately does *not* do. A small question never produces a simplified report — it produces **no** report and a short answer, because a half-register document is worse than either. And a short answer is not a looser one: plain language, same rules on sourcing, no claim without a source that says it.

**Why this is cheaper than it looks.** Scouts read in their own context windows and return short digests, so thousands of tokens of web pages never enter your main conversation. Skills load ~30 tokens of frontmatter at rest and only pull in their full instructions when triggered. Mechanical checks run as scripts, costing nothing.

### Research runs only when you type a command

A message without a command is a chat question, answered directly with a few searches at most. `/research`, `/research-pipeline`, `/expand`, `/verify` and the other stages start only when you type them; the agent can no longer start them on its own. Every command works by itself or inside the pipeline, so after a report ships you can type `/verify <run> E42` or `/repair <run> §3` for one claim or one section, and only that part is read and checked, at the full standard.

### Where the tokens go now

Most of a run's cost used to be one long conversation re-reading itself on every step: the main thread held the draft and every repair, and was re-read in full on each of a few hundred calls. That is what changed:

- **The document stays out of the main conversation.** The `report-writer` agent drafts, repairs and integrates expansion rounds in its own context and hands back a short summary; reviewers read the file from disk.
- **Each command starts a fresh conversation in the app**, working from the run folder. A reply without a command continues that conversation on the command's model, so answering the pipeline's question does not drop it to a cheaper one.
- **`/research-pipeline` runs one stage per conversation in the app**: gather, draft, review, finish. The app starts each stage when the previous one has left its files, and waits when a stage asks you something. Stop ends the chain; `/research-pipeline stage=review run=outputs/<run>` re-runs one stage. Switch it off under Models.
- **Long reports are read by section.** `python3 .claude/scripts/section_map.py <run>` prints each section's lines, length and sources; `--show "<heading>"` prints one section.
- **Pages are fetched once, for every run.** Scouts read sources through `library.py`, which keeps the page text in `library/` (never committed). A page any run has read costs nothing the next time, and a quote found verbatim in the stored copy is confirmed by a script instead of a re-fetch. Pages built by JavaScript, or behind a login, still go through WebFetch.
- **New research starts from what earlier runs found.** Before scaffolding, `/research` checks `kb.py runs` for an existing report on the same ground and asks whether to extend it instead; scout briefs list rows already established (`kb.py search "<terms>"`).

### Which model runs what

In the app, the command a message starts with picks the model, on Claude and on Codex alike:

| Tier | Claude | Codex | Commands |
|---|---|---|---|
| Frontier | Opus | `gpt-6-astra` | `/research`, `/research-pipeline`, `/expand`, `/critique`, `/report`, `/repair`, `/user-edits`, `/figures`, `/narrator`, `/polish`, `/brain_storm` |
| Workhorse | Sonnet | `gpt-6.1-sol` | `/verify`, `/plagiarism`, `/export`, `/visualize`, `/voice-rule`, and plain chat |
| Fast | Haiku (the latest, through the `haiku` alias) | `gpt-6-luna` | `/app`: questions about the app, answered from this guide |

Inside a run, scouts and the fact-checker run on Sonnet; the critic and the writer run on Opus. Change the maps, or switch routing off, under Models. `python3 .claude/scripts/cost_report.py --last 1` shows where the last session's tokens went.

### Chatting inside a project

Open a project and choose **Chat**. The conversation is tied to that run: the agent is told which project it is in, so a question needs no run named, and a command acts on the project. The tab reopens the same conversation next time; **New conversation** starts another on the same project, and **Open full** shows it with its activity panel.

---

## Length and completeness

The default is **complete**: every sub-question answered, every material caveat stated, every contradiction surfaced. Length is driven by evidence, not by a target.

That's paired with a hard anti-padding rule — no preamble, no restating your question, no methodology narration, no "it is important to note". The test used throughout: a paragraph with no `[E#]` is either unsourced fact (fix it) or filler (cut it). See [.claude/skills/report/references/anti-slop.md](.claude/skills/report/references/anti-slop.md).

Ask for brevity explicitly when you want it: "one page", "just the answer", "executive summary only".

Length is an output, never a target. It is not padded to look thorough and not trimmed to look efficient — if a report needs twelve pages to answer its brief it gets twelve, and if four will do it stops at four.

---

## How the report reads

### Three document shapes

Every report is written as one of three, chosen before the first line and held to
the last:

| | Reads like | Choose when |
|---|---|---|
| **Scientific** | A research paper | The question is empirical and you need to judge the evidence yourself |
| **Consultancy** | A firm's report to a client | A decision rides on it and you need to act |
| **Hybrid narrative** | A scholarly article or long-form essay | The answer is an argument to be followed start to finish |

The hybrid runs Title and subtitle → a standalone 150–200 word abstract →
introduction → thematic sections named by topic rather than by finding →
a conclusion that synthesises rather than recaps → notes if the citation system
uses them → the reference list. Ask for it by name ("write this as an article",
"I want an essay"), or let the register rules pick it when the brief asks for a
piece to be read straight through.

It carries the same evidence standards as the other two. An article that reads
beautifully and quietly drops the caveats is the failure this shape invites, so
`## Limitations` and `## Data still to obtain` survive into it unchanged.

### Citation systems

`report.md` always cites `[E#]`. What a *reader* sees is chosen at export:

| System | In text | List |
|---|---|---|
| house (default) | (Halden Labs, product datasheet, 2026) | References |
| MLA | (Aussel 14), or (Aussel) if unpaginated | Works Cited |
| Chicago author-date | (Aussel 2022, 14) | References |
| Chicago notes | a superscript number | Bibliography, with endnotes |

One system per report, recorded in `<run>/voice.md` so a re-export months later
does not switch convention. Changing it costs one command, not a rewrite.

Page numbers are shown only where the source actually carried one. Most web
material is unpaginated, so an author-only MLA citation is correct rather than
missing, and a page is never inferred to fill the slot.

Every finished report is written as **a scientific report or a consultancy report** — never a chat answer that grew headings. The two make different promises, so one is chosen up front and held throughout:

| | Scientific | Consultancy |
|---|---|---|
| Chosen when | The question is empirical — you need to judge the evidence | The question serves a decision — you need to act |
| Opens with | The finding and its confidence | The recommendation and what it turns on |
| Argues by | Method, evidence, alternatives tested | Implication, option, trade-off |
| Ends with | What remains unresolved | What to do, and what to watch |

Both ban chat voice, meta-commentary ("this section will examine…"), rhetorical questions, and marketing adjectives. Both require every quantity to carry its unit, period, and basis. Say "write this as a scientific paper" or "make this a decision memo" to pick directly. Rules: [.claude/skills/report/references/register.md](.claude/skills/report/references/register.md).

### Who it is written for

Separate from register, and chosen separately: **narration mode** decides how much explaining the report does.

| | `scientific` | `explanatory` |
|---|---|---|
| Reader | A specialist in the field | Technically literate, not a specialist here |
| Terms | Used directly | Defined at first use, in the sentence, then used normally |
| Mechanisms | Stated at full detail | Built in a sentence or two before the finding leans on them |
| Numbers | Interval, n, basis | The same, plus what the number is large or small against |
| Sentences | Whatever the argument needs | Fewer subordinate clauses; the ideas stay as complex as the evidence |

**What does not change between them: every claim keeps its evidence ID, every caveat ships, the calibrated language is identical, and the confidence statement is identical.** `explanatory` is a different reader, not a lower standard, and it is not a shorter report. If you want it shorter, ask for that separately.

Say who it is for and the mode follows: "for our investors" gets `explanatory`, "for the R&D team" gets `scientific`. If you say nothing, you are asked once, before drafting, and the answer is written to `voice.md` in the run folder so every later round keeps the same voice. Changing mode after the report exists is a full rewrite, so it is worth the ten seconds up front.

#### Asking for it

Any of these picks the mode without a further question:

```
research supplier concentration in cathode materials and write it up for our investors
        → explanatory, recorded before drafting

/narrator this is for the R&D team, not for the board
        → scientific

/narrator rewrite this for readers who are not cell biologists
        → re-narrates the finished report, section by section

/narrator who is this currently written for?
        → reads outputs/<run>/voice.md and tells you
```

The last one is worth knowing about. Once `voice.md` exists, nothing re-asks and nothing re-decides, so a report written for investors in round one stays that way through every later expansion.

#### What actually changes

The same finding, same evidence, same caveat, in both modes:

```
scientific
  E. coli-derived rhBMP-2 showed ~31% of the relative potency of CHO-derived
  material in an ALP osteogenic bioassay, EC50 78.6 vs 22.1 ng/mL [E724][E725].

explanatory
  The same protein made in two different host cells is not equally active.
  BMP-2 grown in bacteria reached about a third of the potency of the same
  protein grown in mammalian (CHO) cells: it took roughly three and a half
  times more of the bacterial material to produce the same response,
  78.6 against 22.1 ng/mL [E724][E725].
```

Both carry `[E724][E725]`. Neither drops the qualifier "in an ALP osteogenic bioassay"; the explanatory version turns it into "to produce the same response" and keeps the assay named where the section first introduces it. If a caveat disappears in the rewrite, that is a defect, and it is why the re-narration re-runs the citation audit rather than trusting itself.

#### Re-narrating a finished report

A mode change touches every section, so it is declared as a document-wide edit before anything moves:

```
you   /narrator rewrite this for a non-specialist reader

      Blast radius: the whole document. Claim set and structure held fixed.
      Baseline snapshotted.
      … works section by section …
      Done. 37 sections rewritten. Cited-ID set unchanged (217 IDs before and
      after), heading set unchanged, 1 figure caption reworded.
      voice.md now records: explanatory.
```

If a heading has to change to survive the new mode, you get asked rather than told. Structure is a separate decision from voice.

### Your writing style

The workspace learns how you write, from the rules you state and the edits you
make by hand.

#### Building your own voice

Your voice is personal, so none of it ships with the workspace. A fresh clone
has no profile, no rules of yours and no samples of your writing. Until you add
some, the agents write to the **house rules** that `voice.py lint` enforces for
everyone: no em-dashes used as asides, no "what matters is" formula, no "it is
not X, it is Y" antithesis, no stock phrases or clichés, no decorative symbols,
and plain professional British English.

Everything you add lives in `.claude/voice/`, and git ignores all of it, so it
stays on your machine and is never pushed with the workspace:

| File | What it holds | Created by |
|---|---|---|
| `profile.md` | Your rules in prose, each with an example and the rebuild, plus a dated history | `/voice-rule`, or by hand |
| `rules.py` | The patterns that check the rules a script can check | `/voice-rule` |
| `corpus/` | Finished sentences you wrote into reports, kept as samples | `/user-edits` |
| `measured.json` | Your cadence, measured from the corpus | `voice.py profile --rebuild` |

To build it from nothing:

1. **Record your first rule.** Run a report, read it, and the first time a
   sentence grates, say why: *"I never open a sentence with 'Notably'. Record
   that."* `/voice-rule` creates `profile.md` and, when the rule can be checked
   by a script, `rules.py`, then tests the new check against your reports.
2. **Or write the profile yourself.** Create `.claude/voice/profile.md` with
   three headings and fill in what you already know about how you write:

   ```markdown
   # Voice profile

   ## Stated rules
   - **No sentence opens on "Notably".** Start with the fact.
     "Notably, yields fell." → "Yields fell."

   ## History
   - 2026-10-09: profile created; first rule recorded by hand.
   ```

   Rules written by hand are followed by every writer agent from the next piece
   of writing. They are only checked by script once a pattern for them is in
   `rules.py`; ask the agent to add one with `/voice-rule`.
3. **Edit the reports in your own words.** Every finished sentence you write
   into a report is filed into `corpus/` the next time `/user-edits` runs.
4. **Let the cadence follow you.** Once the corpus holds a few reports' worth
   of your prose, `python3 .claude/scripts/voice.py profile --rebuild` measures
   it, and the targets for sentence length, semicolons and bold move from the
   defaults to yours.

Back up `.claude/voice/` yourself if you want it on another machine. A clone
of the workspace does not carry it, by design.

#### Teaching it your style over time

Every agent that writes prose reads one file before it starts,
`.claude/voice/profile.md`, and a checker enforces what
can be checked on every save. So the way to improve how the agents write is to
improve that file, a little at a time, as you read their work. Five ways in, from
the quickest:

1. **Say what you don't like, in any conversation.** In the app's Chat tab, a
   project's conversation or VS Code, write it as a rule: *"I never open a
   sentence with 'Notably'"*, *"stop ending paragraphs on a summary line"*, *"use
   'about', not 'approximately'"*. The agent records it with `/voice-rule` in that
   turn, without being asked, and tells you where it went. You can also type
   `/voice-rule` yourself.
2. **Paste the sentence you dislike, and say why.** *"This reads like a machine:
   'The result is clear: supply is the constraint.' I don't build sentences around
   a colon reveal."* A concrete example teaches more than a general instruction,
   and the agent uses it to test the new check in both directions: it must catch
   your example and stay quiet on reports you already accepted.
3. **Rewrite it yourself.** Edit the report in the app's Edit tab or in VS Code,
   save, then run `/user-edits`. Your rewrites stand as written; your finished
   sentences are filed as samples of how you write, and the measured targets
   (sentence length, how often you use a semicolon, how much you bold) move
   toward yours over a few rounds. Rough notes telling the agent what to write
   are treated as instructions and are not learned from as style.
4. **Edit the rules directly.** In the app, open **Workspace → Voice →
   profile.md**. The file is private, so a save writes it to disk and is not
   committed to the repository; keep your own copy if you want to undo. Use this to
   reword a rule, delete one you no longer want, or add a preference that is too
   subtle to state in a sentence of chat.
5. **Check how a report measures up.** `python3 .claude/scripts/voice.py lint
   outputs/<run>/report.md` lists every rule a report breaks, by line;
   `voice.py profile` shows the rules and the current targets.

What makes a rule stick:

- **Name the construction, give an example, say what you would write instead.**
  *"No 'X, not Y' endings. 'It is a floor, not a quote' becomes 'It is a floor.'"*
- **Say whether it is a rule or a one-off.** A rule applies to every later report; a one-off ("cut this sentence") is an edit and is left there. One
  changed semicolon is never turned into a rule on a guess: you are asked, or the
  agent waits for the pattern to repeat.
- **Rules that a script can check become hard failures** that block a report until
  fixed. Rules that need judgement ("the closing clause is usually unnecessary")
  are recorded in the profile and followed by the writer, without a script.

The profile is shared by every agent and both providers: Claude in the app and in
VS Code, and Codex, which reads it through `AGENTS.md`. A rule recorded once
applies everywhere from the next piece of writing.

The rest of this section explains the machinery.

Two halves, and they work differently:

- **Rules you state** live in `.claude/voice/profile.md`, and the ones a script can check are enforced mechanically through patterns in `.claude/voice/rules.py`, on top of the house rules in `voice.py`. Tell the agent a new rule and ask it to record it; a rule that lives only in a conversation is lost by the next session.
- **Cadence it observes** is measured from your own sentences: how often you reach for a semicolon, how long your sentences run, how much you bold. This is reported, never enforced, because cadence is a tendency rather than a rule.

The loop runs by itself. An agent writes, then records what it wrote. You edit the document by hand. The next time `/user-edits` runs, it separates your sentences from the agent's, files yours into a corpus, and re-measures. Over a few rounds the cadence targets move toward you.

Two things to know about it:

- Your edits are read twice, for two different things. As **content** they are editorial direction, and `/user-edits` absorbs them. As **voice** only your finished prose counts; a rough note telling the agent what to write is content, and it gets discarded from the corpus rather than learned from.
- The corpus is small and hand-editable on purpose. Open `.claude/voice/corpus/` and delete anything that is not a sample of how you write.

#### Teaching it a rule

State the rule. `/voice-rule` records it in that turn, into the profile with the
date, and into the checker when it can be checked mechanically. You can type the
command yourself, and an agent that hears you state a rule is meant to run it
without being asked, because a rule left in the conversation is gone by the next
session:

```
you   I never write "leverage" as a verb. Record that.

      Added to .claude/voice/profile.md under Stated rules (2026-08-15) and to
      the HARD list in .claude/voice/rules.py. It now fails the gate rather
      than relying on an agent remembering.
```

A rule is never guessed from one edit. If you replace a single semicolon with a full stop, nothing is inferred; you get asked, or it waits for the pattern to repeat.

A new pattern is tested in both directions before it ships: it has to catch the
construction you objected to, and it has to stay quiet on a report you already
accepted. A checker that fires every third sentence is one you would start
ignoring, so a rule that cannot be narrowed is filed as advisory instead of a
hard failure. Rules like *the tail is usually unnecessary* are judgement calls no
regex can make, and those are recorded in the profile and left to the writer.

#### What a fix looks like

The checker flags the construction, and the fix is a rebuilt sentence rather than a swapped character:

```
flagged   The window is wide — 10-fold — and no page says what it governs.
wrong     The window is wide, 10-fold, and no page says what it governs.
right     The window spans 10-fold, and no page states what it governs.
```

Swapping the em-dash for a comma leaves a sentence still built around an aside, which is the habit rather than the punctuation. The rebuild puts the real subject back in charge.

#### Repeated words, and the words it will not use

Agents repeat themselves inside a paragraph, and so does everyone writing at
speed. Every skill that writes prose now runs a repetition and word-choice pass:

- **No ordinary word echoes in a paragraph.** Three uses of the same verb, or two
  inside a few words, gets fixed. The first fix is a rebuilt sentence, then a
  pronoun, and only then a synonym.
- **A term of art never varies.** The word naming the thing under study stays put
  however often it repeats. Calling an assay a test, then a trial, then an
  experiment reads as three different things, and that is the worse defect.
- **A synonym never moves the claim.** "Reduced" is not "eliminated" and "linked
  to" is not "causes", so a word swapped for rhythm that changes the strength of
  a finding is treated as a factual error.
- **Plain professional British English**, not literary. No *utilise*, *myriad*,
  *tapestry*, *unveil*, *showcase*, *cornerstone*, no landscape-as-metaphor, and
  no metaphor carrying an argument.

The check is advisory on purpose: a report about electrolytes says "electrolyte" two hundred
times and should. It reports what it sees, and the writer decides.

```bash
python3 .claude/scripts/voice.py echo outputs/<run>/report.md
```

If it keeps flagging a term you repeat deliberately, write it into
`outputs/<run>/voice-terms.txt`, one per line, and it stops asking. The doctrine
is [.claude/references/diction.md](.claude/references/diction.md).

The banned constructions have a matching escape, and it is deliberately less
comfortable. When the lint flags a sentence where the construction is carrying
information (*"this is a floor, not a quote"* corrects what the reader is about
to assume the number is), write the flagged fragment into
`outputs/<run>/voice-allow.txt`, one per line, with a comment saying what it
corrects. The lint then reports it as exempted rather than failed. An entry
there is a claim you are making about that sentence, it sits in the run beside
the evidence, and it is read like any other line of it.

#### Seeing where a report stands

```bash
python3 .claude/scripts/voice.py profile              # rules and current targets
python3 .claude/scripts/voice.py stats  outputs/<run>/report.md   # how this report reads
python3 .claude/scripts/voice.py lint   outputs/<run>/report.md   # violations, exit 1 if any
python3 .claude/scripts/voice.py echo   outputs/<run>/report.md   # repetition and diction, advisory
```

`stats` on a report written before the profile existed is a useful baseline:

```
words                  11999
semicolons_per_1k       5.25
emdash_per_1k          13.25      ← 191 em-dashes
mean_sentence_words    46.68      ← target band tops out at 30
bold_share              0.34      ← a third of lines open in bold
```

`lint` names each one with its line number, so a voice pass is a worklist rather than a rewrite from scratch.

---

## Giving it your own sources

Drop files into `outputs/<run>/external_data/`: datasheets, PDFs you bought or were sent, certificates of analysis, spreadsheets, scans, internal memos. Any folder structure you like; subfolders per vendor or per topic work well. Nothing in the pipeline ever modifies or deletes what you put there.

In the app, open a project and use **Import** above its file list. Select one or more files; they go into that project's `external_data/` without replacing an existing file. You can import while an agent is working, including when it asks you to obtain a source. Tick **AI generated material** first to put those files in `ai_reports/`, where they can supply leads but not evidence. The file list also lets you remove a supplied file; the app moves it to the project's hidden `.trash/external_data/` folder so it can be recovered. Removal waits until any agent working on the project has finished its turn.

They are treated as sources, not as background reading: verbatim quote, evidence row, citation in the report, Admiralty grade like anything else. A fact from a PDF on your disk carries exactly the weight of the same fact from a URL, no more and no less. A vendor datasheet stays a vendor source because you were the one who supplied it.

**Add files whenever you like, including after the report is finished.** The folder is indexed by content hash, so the agents can answer one question cheaply: which files has nobody read yet? Unread files get read; already-mined files are never re-opened. That is what keeps a run with forty PDFs in it affordable.

The scan runs at the start of research, verification, expansion, and edit absorption. Say "I added some files" and it runs immediately.

```bash
python3 .claude/scripts/external_index.py scan   outputs/<run>    # what is unread
python3 .claude/scripts/external_index.py status outputs/<run>    # one-line summary
```

Two things worth knowing:

- **A file you supply can break a claim, not only support one.** If it contradicts something the report already says, that is a finding, and it gets reconciled openly rather than quietly dropped.
- **A claim resting only on a file you supplied** cannot be checked by anyone outside the run folder. That limit gets stated in the report's Limitations when the claim is load-bearing.

Files nobody can open, such as an image or a scan with no text layer, are listed and flagged rather than guessed at. You will be asked what is in them.

### One folder is reserved: `ai_reports/`

Put AI-generated material in `external_data/ai_reports/`: chatbot research summaries, generated business cases, AI-drafted memos. Everything in that folder is treated as **always unverified**, and the rest of `external_data/` is treated as real documents from real sources.

| | `ai_reports/` | Everywhere else |
|---|---|---|
| What it is | Model output | A real document |
| How it is used | Leads only | A source, graded and cited |
| Can a fact be cited to it? | No | Yes |

A file in there is read for the claims and pointers it contains. Those claims go into a notes file, each with the search that would settle it, and every one is then sourced independently from a real document before it can appear in the report. Its own citations are leads too: a reference inside a generated report is unverified until somebody fetches it, and invented references are exactly what that kind of document gets wrong.

This is enforced rather than trusted. The indexer refuses to attach evidence to a file in that folder:

```
$ python3 .claude/scripts/external_index.py register outputs/<run> \
      ai_reports/business_case.pdf --evidence E900

ERROR ai_reports/business_case.pdf is under ai_reports/ and is AI-generated
content. It is a LEAD, not a source: a fact never enters evidence.jsonl on its
authority.
  Mine it for claims and pointers, source each claim independently from a real
  document, then register this file with:
    --leads N --notes notes/<file>.md
```

The scan flags them on sight:

```
NEW      ai_reports/business_case_report.pdf  (14p, 311KB)  [AI: leads only, verify independently]
```

What comes back after one is read looks like this, with the leads kept separate from the findings so nothing gets mistaken for the other:

```
LEADS (from ai_reports/business_case_report.pdf, unverified)
- claims the addressable market is $1.2B by 2028
      → no source given in the document; searched, found nothing that
        supports it. Logged as a GAP, not written into the report.
- claims Northwind has a recycling partnership
      → sourced independently to the partner's own announcement [E1131].
        Now a finding, cited to that, not to the business case.
- cites "Venkatesan et al. 2023" for a cost figure
      → the paper exists but is 2022 and gives a different number.
        Corrected against the paper itself [E1004].
```

**The one exception**, and it is narrow: the report can cite a file in `ai_reports/` when it is saying something *about that document*, such as what it assumed or what it got wrong. "The supplied business case assumes a 40% gross margin" is fine, and the text says where that comes from. "Gross margin is 40%" sourced to the same file is not.

If a lead cannot be sourced, it does not quietly become true and it does not quietly vanish. It is logged as a gap, and if the report needs the claim, it ships as a visible hole with its provenance stated.

### Using supplied files to extend a report

This is the common case: the report is finished, it has a hole in it, and you go and find the document that fills the hole.

*The transcripts below show the shape of an exchange, not a record of one. Evidence IDs in them are illustrative.*

```
you   I dropped the Northwind datasheets into external_data. Use them to
      close the NW-200 questions in section 1.2.
```

The scan runs first, and it reports only what is unread:

```
NEW      northwind/NW-200_SDS_240918.pdf  (8p, 319KB)
NEW      northwind/NW-200_information_sheet_v250226.pdf  (1p, 152KB)
NEW      northwind/Northwind_FAQ-061625.pdf  (4p, 128KB)
INDEXED  rnd/supplier-audit.pdf  (2p, 491KB)
…
31 file(s) · 3 unread · 28 already mined · 0 missing
```

The three unread files go to a scout in an isolated context. Nothing about a 319KB PDF enters the main conversation; what comes back is a digest, and what lands on disk is verbatim extracts plus evidence rows. Then each file is registered so no later round opens it again.

What you get back distinguishes the three outcomes that actually happen:

```
CLOSED     [NEEDS DATA — NW-200 coating chemistry] in §1.2
           The information sheet states the coating process [E1125].
           Placeholder removed, sentence rewritten, Data still to obtain
           updated. The conditional risk in that paragraph is now resolved
           rather than hypothetical.

CONFIRMED  Storage and handling figures match what the report already
           said from the vendor's web page. No text change; second source
           recorded [E1126].

CONTRADICTS  The FAQ states a shelf life that disagrees with the figure in
           §2.6 assumption 3 [E1127] vs [E304]. The supplied document is
           newer. Blast radius: §2.6 and the one sentence in §1.1 that
           leans on it. Declaring before editing — proceed?

UNCHANGED  The safety data sheet held no citable figure. Registered with a
           note saying so, so nobody reads it again.
```

The `CONTRADICTS` row is the one to pay attention to. A supplied file that disagrees with the draft does not quietly lose; the conflict is surfaced, the blast radius is declared, and you decide.

#### Adding files mid-run

You do not have to wait for a stage boundary:

```
you   adding a few more PDFs now, hold on
      … drop files …
      ok, added three from MedChemExpress
```

The next scan picks up exactly those three. Everything already mined stays closed. This is what makes it safe to keep feeding a run over weeks: the cost of adding the fortieth file is the cost of reading one file, not forty.

#### Checking it yourself

```bash
python3 .claude/scripts/external_index.py scan   outputs/<run>   # exits 2 if anything is unread
python3 .claude/scripts/external_index.py status outputs/<run>   # how many, and which evidence came from them
python3 .claude/scripts/external_index.py show   outputs/<run> northwind/NW-200_SDS_240918.pdf
```

`show` tells you what a given file produced: the evidence IDs, the notes file holding its verbatim extracts, and a one-line summary of what it was. If a claim in the report rests on a document you supplied, that is the chain back to it.

---

## Improving a document you already have

A business plan, an investor deck, a cash-flow model, a two-pager: put it in a project's `external_data/` and the workspace can research it, propose changes, and produce a new version that reads and looks like the original.

```text
/audit     what is right, wrong, stale, missing or weak, with evidence   → report.md
/changes   a change plan you accept, reject or rewrite line by line
/revise    a new version of a Word, PowerPoint, Excel or Markdown file
/rebuild   a new file in the original's design, for a PDF or a new deck
```

**Name the document in the command.** `/audit the business plan and the cash flow in external_data, for UK angel investors` declares both files as the documents being improved. The audit verifies their claims, checks what a document of that kind needs for its readers, compares figures across the documents, and writes a cited report. `/changes add Activin A as the third target` skips the audit and works from your instruction.

**You accept every change.** In the app, the project's **Changes** button opens the plan: each change shows the text it replaces, the new text, why, and its sources. Accept, reject, or rewrite it in your own words (your wording is used exactly). Then **Apply accepted changes**. For a Word document, choose tracked changes, which appear in Word's review pane under the name you give, or a clean copy. In VS Code, say it in chat ("accept all except C04") and the agent records exactly that. A change the agent edits after you accepted it comes back to you.

**The original is never touched.** Each version is written to `deliverable/<document>/v1/`, `v2/` and so on, rebuilt from the untouched original every time.

**It stays your document.**

- **Citations** follow its system. A plan that links source names in parentheses gets linked source names in parentheses; a footnoted one gets footnotes; a numbered one gets the next number and a reference-list entry.
- **Voice** follows the document: its "we", its way of writing "500,000 pounds" or "USD 9.7 billion", its terms.
- **Formatting** comes from the document's own paragraphs, tables and slides. A check fails any version that uses a font, colour or style the original does not use, links to a page nobody fetched, or changes anything you did not accept.
- **Spreadsheets** keep their formulas and charts, and recalculate when opened.

**A PDF cannot be edited**, so `/rebuild` makes a new deck in its design: its fonts, colours, type sizes, images and motifs, read from the PDF and checked slide by slide against its pages. If you have the `.pptx` or `.docx` the PDF came from, add it instead: editing beats rebuilding.

To copy a design without using a document's content, declare it as a template: put it in `external_data/template/`, or ask for it ("use the two-pager as the template").

```bash
python3 .claude/scripts/subject.py list   outputs/<run>          # documents declared, and their state
python3 .claude/scripts/changes.py status outputs/<run>          # proposed, accepted, rejected, stale
python3 .claude/scripts/run_check.py      outputs/<run> --deliver
```

---

## Tables and charts

To improve the charts in a finished report, type `/figures` with what you want:
`/figures F4 is unreadable, make it horizontal and sort it`, or `/figures all use
one highlight colour`. It changes how a chart looks freely; it adds a number only
from the evidence ledger, never drops a missing value to tidy a chart, and lists any
figure whose message changed for `/verify`. Inside a project's Chat tab no run needs
naming.

Charts live **inside** the report, and they're written as data rather than pasted as pictures:

````markdown
```figure
{"id": "F2", "type": "bar",
 "title": "Adoption stalled in the two regulated markets",
 "subtitle": "Installed base, thousands of units, year end",
 "source": "[E7][E12]", "unit": "k",
 "categories": ["Germany", "France", "Spain"],
 "series": [{"name": "2024", "values": [120, 98, 76]},
            {"name": "2025", "values": [124, 101, 112]}]}
```
````

That has three consequences worth knowing:

- **A chart is auditable like a sentence.** Its numbers are in the source, it cites `[E#]`, and a script checks that every figure has evidence behind it and that no series has more values than categories.
- **Restyling is free.** The same report renders in any style; the chart is drawn at export time.
- **Nothing is plotted from memory.** If a number isn't in `evidence.jsonl`, the check fails.

Fourteen chart types: `bar`, `hbar`, `stacked_bar`, `line`, `area`, `scatter`, `dot`, `dumbbell`, `slope`, `waterfall`, `heatmap`, `donut`, `stat` tiles. Tables and charts share one **Exhibit** sequence numbered in document order, and `[[F2]]` in the prose resolves to "Exhibit 4" so insertions renumber cleanly.

The default is a table. Charts are for when the *shape* of the data is the finding — a gap, a crossing, a cluster, an outlier. Three exhibits in a ten-page report is normal; ten is a deck pretending to be a report.

```bash
python3 .claude/scripts/figures.py types                # what's available
python3 .claude/scripts/figures.py check <report.md>    # validate specs
python3 .claude/scripts/figures.py gaps  <report.md>    # what's still missing
```

---

## Applying a style

### The five

| Style | Reads as | Reach for it when |
|---|---|---|
| **Meridian** | Navy, serif throughout, thin rules | Board papers, policy and regulatory work; it should look like an institution wrote it |
| **Verdant** | Deep green and sand, sans headings over serif body | Long-form market or sustainability work someone reads end to end |
| **Ember** | Crimson on charcoal, all sans, high contrast | A recommendation you want acted on this week |
| **Graphite** | Near-monochrome with slate references and dark charts | Technical work for readers who resent decoration |
| **Helix** | Violet and magenta, geometric sans, airy | Technology strategy, for audiences who expect current |

Plus `none` for unstyled pandoc output. A style sets the palette, fonts, table treatment, page margins, chart colours and cover — the same across PDF, Word, HTML and slides, because all four are generated from one JSON file.

In the app, open a report's **HTML** tab and select **Palette and layout**. The controls open beside the report; drag their left edge to change the width. Select **Entire report** for the page palette, fonts, chart defaults, and table rules, or select a named Figure or Table to adjust that item alone. Individual Figures have their own colours, line and bar settings, and fonts. Individual Tables have their own colours, font, text size, spacing, and width. Select **Apply changes** to save the choices with that report in `.report-style.json`. The app uses them for its preview, PDF export, and saved figures. **Reset report** restores the selected style's defaults; **Reset this item** clears one item's overrides when you apply the change.

### Just say it

Style is a parameter of the export, not of the research. Name it whenever you ask for a file:

```
/export pdf, Meridian
/export docx and pdf in Graphite
give me a Word version, Ember
export the deck — Helix
```

Format and style can arrive in any order, in any phrasing. If you name neither, Claude asks once — both in the same question — and waits. If you name a format but not a style, it asks only for the style.

There is one exception: in a **non-interactive** session it can't ask, so it defaults to `.docx` with no styling and tells you it defaulted.

### Look before you commit

You don't have to pick from a description. Two commands, a few seconds each:

```bash
python3 .claude/scripts/style.py list                                # all styles + what each is for
python3 .claude/scripts/style.py swatch verdant -o /tmp/verdant.png  # the palette, one image
python3 .claude/scripts/figures.py demo --style verdant -o /tmp/v    # eight real charts in that style
```

Or just ask: *"show me what Ember and Graphite look like"* — Claude runs these and shows you the images.

### Changing your mind is cheap

Re-exporting in another style costs one command and touches nothing in the content:

```
/export the same report in Graphite instead
```

Each style writes to its own directory, so nothing gets overwritten:

```text
outputs/2026-08-12-eu-battery-rules/export/
  meridian/   report.pdf  report.docx  report.html  style.css  reference.docx
  graphite/   report.pdf  …
```

The charts are redrawn in the new palette on the way through — that's why they're stored as data rather than as images.

**Styling an older report** works the same way. Point at the folder:

```
/export outputs/2026-06-04-grid-storage/report.md as pdf, Verdant
```

### Using your own corporate template

If you have a real branded `.docx` or `.pptx`, it overrides the generated one entirely:

```
export as docx using our house template at ~/templates/acme-report.docx
```

Pandoc's `--reference-doc` takes over; the built-in styles step aside. Note this replaces the Word styling only — PDF still comes from CSS, so mention it if you want both to match.

### Making a sixth style

A style is a file. Copy the closest one and edit the values:

```bash
cp .claude/styles/meridian.json .claude/styles/harbour.json
```

Change the hex colours, the font stacks, `table.style` (`banded` or `rules`), `page.cover`, `page.margin_mm`. Then check it loads and see it:

```bash
python3 .claude/scripts/style.py show harbour          # fails loudly if a key is missing
python3 .claude/scripts/figures.py demo --style harbour -o /tmp/harbour
```

It's immediately available to `/export harbour` in every format. No code changes anywhere. Or skip the editor: *"make me a style like Meridian but in our brand green #0A5C3A, sans-serif"* — and Claude writes the file.

**Tweaking one thing** in an existing style — "the table headers are too dark", "make the body text bigger" — is a one-line edit to that style's JSON. Ask for it in those words. Field-by-field schema and the palette rules are in [.claude/styles/README.md](.claude/styles/README.md).

---

## Exporting

Verified working on this machine — pandoc 3.8.3, matplotlib 3.10, weasyprint 69:

| Format | Notes |
|---|---|
| PDF | via weasyprint from the styled HTML; running footers, landscape pages for wide tables |
| Word | generated `reference.docx` carries the style's fonts, heading colours, and table treatment |
| HTML | single self-contained file, images embedded |
| Slides | generated `reference.pptx` carries the theme; the report is **restructured** first, since reading prose makes bad slides |

Ask for several at once — `/export docx and pdf, Meridian` — but you get exactly the set you asked for. It won't emit all four because it can.

Every conversion is checked afterwards:

```bash
python3 .claude/scripts/check_export.py <source.md> <out.pdf> <out.docx> <out.html>
```

It compares the set of evidence IDs, the exhibit count and the placeholder count in each artifact against the source. A renderer that clips a table doesn't warn and produces a document that reads as complete — this is the only thing that catches it. If a format proves lossy, the workspace changes the renderer, never the report.

### Analysis notebooks

`/notebook` writes a Jupyter notebook for the figures and tables you name, in `<run>/notebooks/`. Each is written the way a data analyst documents their own work: the sources, how each dataset was obtained (downloaded, copied from a held file with its checksum, or transcribed with the page named), every cleaning step, the method with its formulas, all the code, and the rebuilt chart or table. A final section checks every reproduced number against the published one and fails if any differ beyond rounding, so a figure that no longer follows from its data cannot pass unnoticed.

Notebooks are made only when you type the command, never by `/export` or any drafting stage, so you choose when the analysis is settled enough to document:

```text
/notebook figure 1 and table 1 together
/notebook all
```

To run one: `pip install -r requirements.txt` in that folder, open the notebook, and choose *Restart and Run All*. If you edit the report after a notebook exists, `/notebook` on the same item finds it stale and updates its published values; the check then shows which numbers moved. Installing `nbclient` and `ipykernel` lets the workspace save results into each notebook so a reader sees them without running anything.

---

## Continuing research on a finished report

You've read the report and want more. That's `/expand` — and the point of it is that the document stays **one document**: no "Additional findings" section at the bottom quietly contradicting paragraph four.

### Start from the run folder

```
/expand outputs/2026-08-12-eu-battery-rules — the vendor pricing section is thin, go deeper
```

If you've just been working on that report, the folder is implied and you can skip it. Everything lands in `rounds/r1/`, `rounds/r2/`… inside the same folder, and new evidence appends to the same `evidence.jsonl`. A new dated folder would sever the new evidence from the ledger it has to reconcile against, so `/expand` never makes one.

### Phrase the ask so it lands where you want it

The wording steers the whole round. Five shapes, and they produce very different documents:

| Say something like | What you get |
|---|---|
| *"go deeper on the permitting timeline"* | **Depth** — that section rewritten with more evidence; the answer probably survives |
| *"what about the US regime?"* | **New angle** — a new sub-question, and a check that no existing conclusion assumed it away |
| *"is the 2025 cost figure still current?"* | **Refresh** — load-bearing claims re-verified first, only what moved gets re-researched |
| *"close the gap on Merid and Orbis pricing"* | **Gap closing** — reads why it failed last time, tries the untried channels |
| *"I don't believe finding 3"* | **Challenge** — a dissent scout builds the strongest case against it |

Claude names which one it picked before spending anything, so you can correct it in one word.

**Say "work it into the argument", not "add a section on X."** The first invites integration; the second invites appending, which is exactly the failure mode. If new material genuinely deserves its own section, Claude will place it by relevance rather than at the end.

### Keeping the story aligned — what to watch, and how to steer

This is the part worth learning. Three levers:

**1. Ask to see the plan before the edits.**

```
/expand go deeper on vendor pricing — show me reconcile.md before you touch the report
```

`rounds/rN/reconcile.md` classifies every new finding against what the document already says, *before* anything is rewritten:

| | |
|---|---|
| `CONFIRMS` | independent support — the `[E#]` is added, confidence may rise |
| `DEEPENS` | new detail — that section is extended in place |
| `QUALIFIES` | the claim is narrower than stated — fixed everywhere it's restated |
| `CONTRADICTS` | better evidence says otherwise — blocking; every dependent conclusion is traced |
| `SUPERSEDES` | newer figure — replaced, and every chart and derived number rechecked |
| `NEW` | new ground — a new section, placed by relevance |
| `REDUNDANT` | already in the report — recorded, not restated |

Reading this is how you catch a misplacement before it's written, which is far cheaper than catching it after.

**2. Read `diff.md`, not the diff.** After each round, `rounds/rN/diff.md` says what changed *in the reader's terms* — "the headline moved from 'stalled' to 'stalled outside Iberia'" — rather than listing edits. That's the file that tells you whether your question was actually answered.

**3. Watch the top of the document.** When a round produces a `QUALIFIES` or `CONTRADICTS`, the title and the `**Answer:**` paragraph get fixed *first*, before anything else — a repaired body under a stale headline is worse than the original. If the headline didn't move and you expected it to, say so.

### When it does drift

Multi-round documents drift, and the drift is invisible from inside a round. From round three, Claude re-reads the whole report end to end before researching, asking the question no individual round asks: *does this still read as one document with one argument?*

You can force that at any point:

```
before you research anything — re-read the whole report and tell me whether it still hangs together
the middle sections don't flow anymore; restructure by argument, not by what we added when
this reads like three rounds stapled together — fix the through-line
```

The right response to real drift is a structural pass on the affected part, not another careful local edit. Ask for it in those words.

### A round that changes nothing is a good round

```
ROUND 2 · depth on vendor pricing
Found:    9 new sources (6 primary), E44–E52
Changed:  CONFIRMS 3 · DEEPENS 2 · QUALIFIES 1
ANSWER:   unchanged; confidence Medium → High
```

An extension that has to move the answer to feel worthwhile is one that will move it whether or not the evidence says so. "Three more sources, same conclusion, confidence up" is a real finding — take it as one.

### Then re-export

The extended report is still just `report.md`, so the styled deliverable is one command away and picks up every change, including redrawn charts:

```
/export pdf, Meridian
```

Rounds are unlimited. The audit trail is cumulative — `verification.md` and `critique.md` gain a `## Round N` heading rather than being overwritten — so a claim added in round four is as defensible as one from round one.

---

## Live usage display

The status bar at the bottom of Claude Code shows spend, context, and your plan limits while the agents work:

```text
◆ Opus · high · claude_research
ctx ████████░░░░░░░░  48% (96k)  ·  $1.83 · 24m
5h  ████░░░░░░░░░░░░  24% resets 15:03 (2h10m)  ·  7d 41% resets Sun 16
run 2026-08-12-eu-battery · ⟳ 3 agents · 31 fetches · 1.2M in / 48k out · 14 sources
```

| Row | Shows |
|---|---|
| 1 | Model, effort level, project, active agent name |
| 2 | Context window used (green → yellow → red), session cost, elapsed time |
| 3 | **5-hour and 7-day plan limits with reset times** — the same numbers as the Usage tab in the Claude portal |
| 4 | Current run folder, live subagent count, web fetches, cumulative tokens, sources gathered |

Row 3 comes from Claude Code itself (`rate_limits.five_hour` / `seven_day`), so the percentages and reset times are authoritative rather than estimated. It disappears if you're on API-key billing, which has no such windows. `/usage` still gives the full breakdown; this is the always-visible version.

Row 4 is the research-specific one. Token counts include **subagent usage**, which is the point — during a fan-out, scouts spend most of the tokens and the main thread shows almost none. `⟳ 3 agents` counts scouts currently in flight.

Configured in [.claude/settings.json](.claude/settings.json), implemented in [.claude/statusline.py](.claude/statusline.py):

- **`refreshInterval: 30`** keeps the countdown and agent counter live during long subagent runs, when no new main-thread message would otherwise trigger a redraw.
- The script parses the transcript **incrementally** (byte-offset cache in `/tmp`), so it stays at ~25ms even on a long session.
- It never throws: on any internal error it degrades to a one-line model + cost display rather than printing a traceback into your status bar.

To change what's displayed, edit `render()` in the script — or ask Claude to. Turn it off by deleting the `statusLine` block from settings.json.

## Working with the subagents

Three specialists, spawned automatically:

| Agent | Model | Job |
|---|---|---|
| `research-scout` | Sonnet | High-volume searching and fetching; returns digests |
| `source-verifier` | Opus | Re-fetches sources, issues verdicts and grades |
| `report-critic` | Opus | Attacks the reasoning, returns ranked findings |

You can call one directly — "have the report-critic look at this draft" — for an independent read that doesn't consume your main conversation's context. Definitions live in [.claude/agents/](.claude/agents/) and are plain Markdown; edit the prompts to taste.

---

## Customizing

| To change… | Edit |
|---|---|
| **Colours, fonts, tables, page layout** | [.claude/styles/](.claude/styles/) — one JSON per style; copy one to add one |
| **Chart types and defaults** | [.claude/scripts/figures.py](.claude/scripts/figures.py) — add `_draw_<name>` and list it in `TYPES` |
| When a finding earns a chart | [.claude/skills/visualize/SKILL.md](.claude/skills/visualize/SKILL.md) |
| Voice — scientific vs consultancy | [.claude/skills/report/references/register.md](.claude/skills/report/references/register.md) |
| Writing structure, citation format | [.claude/skills/report/SKILL.md](.claude/skills/report/SKILL.md) |
| Banned phrases and padding rules | [.claude/skills/report/references/anti-slop.md](.claude/skills/report/references/anti-slop.md) |
| Which angles get swept for gaps | [.claude/skills/research/references/gap-hunt.md](.claude/skills/research/references/gap-hunt.md) |
| Source grading thresholds | [.claude/skills/verify/references/admiralty.md](.claude/skills/verify/references/admiralty.md) |
| How scouts are briefed | [.claude/skills/research/references/scout-brief.md](.claude/skills/research/references/scout-brief.md) |
| How follow-up research is reconciled | [.claude/skills/expand/SKILL.md](.claude/skills/expand/SKILL.md) |
| How your own edits are absorbed | [.claude/skills/user-edits/SKILL.md](.claude/skills/user-edits/SKILL.md) |
| What counts as an agent artifact | [.claude/scripts/audit_citations.py](.claude/scripts/audit_citations.py) — `ARTIFACTS` and `SLOP` |
| Your writing rules | `.claude/voice/profile.md` for the prose; `.claude/voice/rules.py` for the patterns that check them (both private, see [Building your own voice](#building-your-own-voice)); [.claude/scripts/voice.py](.claude/scripts/voice.py) `HARD` for the house rules |
| How much explaining a report does | [.claude/references/voice.md](.claude/references/voice.md) — the two narration modes |
| How supplied sources are handled | [.claude/references/external-data.md](.claude/references/external-data.md) |
| Handling of data that couldn't be obtained | [.claude/references/gaps.md](.claude/references/gaps.md) |
| Gates and stage order | [.claude/skills/research-pipeline/SKILL.md](.claude/skills/research-pipeline/SKILL.md) |
| Workspace-wide rules | [CLAUDE.md](CLAUDE.md) |

Skills are Markdown with YAML frontmatter. The `description` field is what Claude matches against your request, so if a skill isn't triggering when you expect, widen its description with the words you actually use.

---

## Running the audit yourself

The checks run on their own. A hook fires after every write an agent makes to a
run's master document, `report.md` or `draft.md`. It runs the voice lint, the citation audit and the
figure check together, and hands any hard failure straight back to the agent to
fix. You do not have to ask for it and an agent cannot skip it.

```bash
python3 .claude/scripts/gate.py outputs/<run>/report.md      # what the hook runs
python3 .claude/scripts/run_check.py outputs/<run> --ship    # did every stage run?
```

`run_check` is the one that catches a stage skipped rather than failed. It reads
the artefact each stage leaves behind and treats a file still holding its
scaffolded template as a stage that never happened, which is how a report once
shipped with an empty coverage table and no verification pass.

A passing gate is not a passing report: it checks what a script can check.
Evidence quality, coverage and reasoning are still `/verify` and `/critique`.

The individual checks, if you want one on its own:

```bash
python3 .claude/scripts/audit_citations.py outputs/2026-08-12-my-run report.md
```

Catches, at zero model cost:

- `[E#]` references with no matching evidence row — the fabricated-citation signature
- malformed or duplicated evidence rows; the same URL recorded twice; all evidence from one or two domains
- substantial paragraphs carrying no citation
- `[NEEDS DATA]` placeholders that don't say where to get the data, or aren't collected into `## Data still to obtain`
- **reference drift** — an entry in `## Sources` that nothing in the body cites any more (what a deleted citation leaves behind), or a citation with no entry
- **agent artifacts** — internal filenames, `[BLOCKING]` tags, round headings, "I searched", and other pipeline scaffolding that must never reach a reader

Exits non-zero on errors, so you can wire it into a hook or CI.

Three more, same idea:

```bash
python3 .claude/scripts/figures.py check <report.md>       # figure specs
python3 .claude/scripts/check_export.py <src> <artifacts…> # nothing lost in conversion
python3 .claude/scripts/section_guard.py check <report.md> # nothing outside scope moved
python3 .claude/scripts/voice.py lint <report.md>          # writing style violations
python3 .claude/scripts/wanted.py check <run>              # sources it could not read
python3 .claude/scripts/external_index.py scan <run>       # supplied sources nobody read
```

`section_guard` is the one that backs the promise that editing one section leaves
the rest of the document alone. It hashes every section, so the claim is checked
rather than trusted:

```bash
python3 .claude/scripts/section_guard.py sections <report.md>   # the section map
python3 .claude/scripts/section_guard.py snapshot <report.md>   # set the baseline
python3 .claude/scripts/section_guard.py check    <report.md> --allow "3.3"
```

It reports `ALLOWED` for sections you scoped in, `DERIVED` for `## Sources` and
`## Data still to obtain` (rebuilt, so they move on their own), and `DRIFT` —
which exits non-zero — for anything else that changed.

---

## Troubleshooting

**A skill didn't trigger.** Invoke it explicitly with `/name`. If it should have fired, add your phrasing to its `description`.

**The report feels thin.** Check `brief.md` — thin reports usually trace to sub-questions that were too broad to search well. Re-run `/research` with narrower ones.

**Verification found a lot of `WEAK` / `CIRCULAR`.** That's the topic, not the pipeline: coverage tracing back to a single press release. Either accept lower confidence explicitly or ask for a dissent scout on the specific claim.

**A run stalled or lost the thread.** Everything is on disk. Start a fresh session and point it at the folder — a clean context reading a good checkpoint beats a full one.

**You disagree with a critique finding.** Say so. Findings are proposals; `/repair` records `won't fix` with your reason rather than arguing.

**The report is missing an angle you care about.** Check `coverage.md` first — it may be there as an explicit `OUT OF SCOPE` decision with a reason, which tells you whether it was a judgment call or an oversight. Either way, `/expand` is the fix.

**A table is full of `[NEEDS DATA]`.** That's the design, not a failure — the sources were restricted. `## Data still to obtain` tells you the access route for each one. If a hole says "not searched", that was a scope decision and `/expand` will close it.

**A chart looks wrong.** The numbers are in the report source as JSON, so you can read them directly. `figures.py check` validates structure; if the *data* is wrong that's a `/verify` question, not a rendering one.

**You edited the report and want it finished.** `/user-edits`. It keeps your concepts, emphasis, and deliberate wording, then repairs the surrounding flow. It researches or verifies only when you ask. You get a concept-by-concept account of where each change landed. Run it *before* `/expand` so the next research round sees your edits.

**You want the report to argue something different.** Say so, in the document or in chat. A change of direction is a supported operation: the agent names every section the new framing touches, shows you that list, then rewrites thesis, section order and headings together. What it will not do is bend the evidence — if the new direction isn't supported you get told, and you get what is.

**Your editor reformatted the whole file.** Harmless. Markdown formatters reflow table pipes across every table, which makes many sections look changed. The containment check distinguishes this from real edits by comparing content with whitespace normalised, and reports it rather than treating it as damage.

**You edited a file under `export/`.** Those are disposable copies, rebuilt from `report.md` on every export — your edits there will be destroyed. Edit `report.md`. If you already did, `/user-edits` will spot it and move the work across.

**You deleted a citation and the source list looks wrong.** `audit_citations.py` reports it and `/user-edits` fixes it. Evidence IDs are never renumbered: cutting `[E45]` doesn't turn `[E46]` into `[E45]`, because those IDs key the evidence ledger and every note file.

**A style doesn't suit the audience.** Re-export — `/export pdf, Graphite` — it costs one command and rebuilds from the same `report.md`. Nothing about the content changes.
