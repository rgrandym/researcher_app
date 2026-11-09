---
name: code-doc
description: Write the source-of-truth technical document for one feature, module or file of a codebase in this project, describing the implementation exactly as written, with every statement cited to the lines of code that show it. Covers responsibilities, an architecture diagram, data models, dependencies, a reproduction guide whose commands were run, graded defects and the quirks an engineer needs to change the code safely. Running it again on the same target updates the same document to match the code. Runs only when the author types /code-doc ("/code-doc app/backend/workspace.py", "/code-doc the gate hook").
argument-hint: "<feature name | file | directory>"
disable-model-invocation: true
---

# Code documentation

A code document is the single source of truth for one part of a codebase: what
it does, how, with what, and how to run it alone, written so an engineer could
rebuild the feature from the document and the repository. Its evidence is the
code. A sentence that no line of code supports is the same failure as an uncited
sentence in a report, and the workspace rules apply with that substitution: a
`path:line` reference does the work of an evidence ID, and
`[Not defined in codebase]` is the labelled gap.

## When it runs

**Only when the author types `/code-doc`**, with a target: a feature name
(`/code-doc user edits absorption`), a directory (`/code-doc app/backend/`) or a
file (`/code-doc .claude/scripts/gate.py`). No other stage makes one. A question
about code without the command is answered in chat at Tier 0 or 1 and names
`/code-doc` when a document would serve better.

The target must lie inside the project folder: the workspace's own code, or code
the author has placed in it (a repository copied under a run's `external_data/`,
for example). Nothing outside the project is read.

## The steps

### 1. Resolve the target to a scope

A path is its own scope. A feature name is resolved by searching: grep for its
terms across `app/`, `.claude/scripts/`, `.claude/skills/`, `.claude/agents/`
and any code folder the author named, then follow imports and call sites one
hop out from the entry points until the feature's boundary is clear. The scope is
the files that implement the feature; a file that only mentions it stays out.
Tests that exercise it belong in scope.

When the name matches two unrelated things, or the scope would exceed about forty
files, ask the author one concrete question (which of the two, or which part
first) and wait. Do not document a guess.

### 2. Start or find the run

```bash
python3 .claude/scripts/codedoc.py start <slug> --target "<what the author typed>" \
        --scope <path> [<path> ...] --prompt "<the author's message, verbatim>" \
        [--project outputs/<current-project>]
```

When invoked from a project's Chat tab, pass that project with `--project`. The
document and its notes, review and stamp then stay in
`<project>/code-docs/<slug>/`. Use a new top-level run only when the author starts
a new search outside a project. It prints the run folder and the master. A target already documented returns its
existing run, widens the scope if needed and appends the new request to
`prompt.md`: the document is updated in place, never written beside itself. A new
target outside a project gets `outputs/YYYY-MM-DD-code-doc-<slug>/` with the master `<slug>.md`.

On a re-run, first:

```bash
python3 .claude/scripts/saved_check.py <run>     # stop if it exits 1
python3 .claude/scripts/codedoc.py status <run>  # what moved since the last stamp
```

`status` lists each changed, deleted or new file and the sections that cite it.
Readers reread those files (step 4) and the writer updates those sections; the
rest is left alone. Text the author
wrote into the document stands (rule 7): when the code now contradicts it, keep
their text and say so in chat.

### 3. Start from what the project already knows

```bash
python3 .claude/scripts/codedoc.py inventory <run>      # files in scope, with line counts
python3 .claude/scripts/codedoc.py map <run>            # symbol index, built once per commit
python3 .claude/scripts/codefacts.py import <run>       # the project's evidence about the code, verified
python3 .claude/scripts/codefacts.py known <run> <files in scope...> --brief
python3 .claude/scripts/codedoc.py leads <run>          # change plans, reviews and notes on this target
```

A project keeps one record of what is known about its codebase, shared by every
code document and every session: verified facts (each with the exact quote from
its lines and the file's hash), the line ranges already read, every search
already run, and the statements of the code documents already written. A fact
whose quote is gone from the changed code is stale and its lines count as
unread again; nothing else expires. `import` adds the project's evidence rows
that cite the code, after checking each quote is still there; it is safe to
rerun. `known --brief` shows, per file, how much is already read and how many
facts stand: the readers start from that, and a file already read in full needs
a reader only for questions its facts do not answer.

The rule the record enforces: **no range of code is read twice at the same
version, and no search is run twice**, by any agent, in any session.

### 4. Read, in readers

**This thread never reads the code.** Code read here is re-read on every later
call of the session, and one document's worth of it costs more than all the
readers together. Your context holds the scope, the paths and the handovers.

Split the inventory into components of at most about 2,500 lines (a backend
module, a front-end panel, a shared library), and spawn one `code-reader` per
component, all in one message. Brief each with `RUN`, `COMPONENT`, `FILES`,
`QUESTIONS` (what the five sections need from it: entry points, data shapes,
behaviour, configuration, defects, the commands the reproduction guide should
run) and its `LEADS`. Each writes `notes/read-<component>.md` and returns a few
lines. A scope under about 600 lines takes one reader.

Give each reader the files of its component and nothing more: a component whose
files `known --brief` shows read in full and whose questions the facts answer
needs no reader. On a re-run, spawn readers only for the files `status` reported,
and name the sections they feed.

### 5. Write, in the writer

Spawn `code-doc-writer` with `MODE: WRITE`, the run and the master path (on a
re-run, also the sections to rewrite). The reader is an engineer who knows the
language but not this codebase, unless the author names another; the prose is
the plain professional British English of `.claude/voice/profile.md`, or the
house rules when no profile exists. The writer builds the document from the
notes, runs `codedoc.py check` and returns a short handover. Do not read the
document into this thread.

### 6. Independent review

Spawn `code-doc-reviewer` on the run. It checks the claims sheet
(`codedoc.py claims`), reruns the reproduction commands, hunts for omissions
through the symbol map and confirms or rejects each defect. Its findings go to
`<run>/review.md`. Neither the writer nor this thread reviews.

### 7. Repair and stamp

Spawn `code-doc-writer` with `MODE: REPAIR`. It applies the confirmed findings and
records each in `<run>/repair-log.md`. Then:

```bash
python3 .claude/scripts/codedoc.py check <run>/<slug>.md   # must exit 0
python3 .claude/scripts/codedoc.py stamp <run>             # record the code it describes
python3 .claude/scripts/run_check.py <run> --ship          # every stage on file
```

The stamp records the commit and a hash of each file in scope, so the next
`/code-doc` on this target, and `status`, can say exactly what drifted.

### Several documents in one command

`/code-doc` may name several targets ("the remaining node documents", a list of
files). Resolve and start each, build the map once, then run the stages as
waves across documents: all readers for a wave of documents in one message (no
more than six readers at once), then their writers together, then their
reviewers together, then the repairs. A document whose stage fails waits; the
others go on. Report one line per document.

## The document

A title, then one metadata line (the commit, from `git rev-parse --short HEAD`,
and the date, noting uncommitted changes in scope if `git status` shows any).
Then five sections, in this order, as `##` headings:

**1. Overview and responsibilities.** Two to four paragraphs: what the feature is
responsible for, the business or workflow logic it carries, and its lifecycle
(what starts it, what it produces, what ends it). Every paragraph cites.

**2. Architecture and system interactions.** One diagram in a ```` ```text ````
fence, drawn in ASCII with boxes and arrows, showing the components, the data
that passes between them and the state each one changes. The app's viewer does
not render Mermaid, so Mermaid is used only when the author asks for it, and then
alongside the ASCII version. Below the diagram, a short walk through it in prose,
cited. Draw only components and edges the code shows.

**3. Complete technical and reproduction specification**, with three `###`
subsections:

- **Detailed architecture.** Data models and schemas (fields, types, defaults,
  where each is defined), the key functions with their signatures and what they
  return, internal state (files, caches, globals, database rows) and who writes
  and reads it, and the execution flow of each entry point step by step. Shapes
  are quoted from the code in fences; a fence is evidence only if the sentence
  before it cites the lines it came from.
- **Tech stack and dependencies.** Internal imports; third-party libraries with
  the version constraint exactly as the dependency file states it (cite the
  line), or `[Not defined in codebase]` when none is pinned; external APIs and
  their contracts as the code calls them; environment variables and settings,
  with their defaults and where they are read.
- **Reproduction guide.** Numbered steps an engineer can follow to set up, run
  and test this feature alone: dependencies to install, configuration, a minimal
  input (mock data built from the shapes in the code, or a fixture the tests
  already use, cited), the command to run it, and the command to test it. Each
  command in a fence, each step saying where it comes from and whether it was run
  while writing this document and what it returned. A step that could not be run
  says why.

**4. Code health, gaps and improvements.** Each finding is one list item or table
row with: severity (**High**: wrong results, data loss, a security exposure or a
crash on a reachable path; **Medium**: a misbehaviour on an edge case, a missing
guard, debt that makes a likely change risky; **Low**: clarity, duplication,
performance with no visible effect), the `path:line`, the concrete scenario
(input or state, then what goes wrong), and an actionable fix. Order by severity.
A finding needs a failure the code can actually reach: trace it before writing
it, and label anything not traced as `Inference:`. Comments in the code such as
TODO or FIXME are cited as what they are, the author's own note. When there are
no defects worth reporting, say so in one cited sentence; do not invent any.

**5. Supplemental implementation details.** The quirks an engineer needs to
change the code safely: branches the names do not suggest, ordering
dependencies, silent fallbacks, data shape guarantees and who relies on them,
coupling to other parts of the project (which file breaks if this one changes).

## Rules that hold throughout

**Accurate to the code.** Every statement in sections 1 to 5 carries a
reference in backticks, `` `app/backend/workspace.py:91` `` or
`` `app/backend/workspace.py:91-114` ``, to lines that show it, or is marked
`[Not defined in codebase]`, or begins `Inference:` when it is reasoned from the
code rather than read in it. `codedoc.py check` rejects a statement with none of
the three, a reference to a file that does not exist, and a line beyond the end
of the file. It cannot tell whether the lines say what the sentence claims; the
reviewer can.

**Describe what is, not what should be.** The document describes the code as it
runs today, including behaviour that looks like a mistake. Intent goes in
section 4 as an improvement, never into sections 1 to 3 as a description. A
docstring or comment that disagrees with the code is a section 4 finding; the
code is the source of truth.

**Gaps are visible.** A configuration, version, limit or behaviour the code does
not define is written `[Not defined in codebase]`, never guessed, never dropped.
A table cell with no value in the code holds that label.

**Quotes are copied.** Code in a fence is copied from the file, with lines cut
only where marked `...`. Names, signatures, defaults and messages are exact.

**Commands are tested or labelled.** A command in the reproduction guide was run
while writing, or it says it was not and why. Never write a flag, script or
target that does not exist.

**No trace of the process.** The document reads as the team's reference, with
nothing about how it was written: no "I read", no reviewer, no rounds. Naming the
workspace's own files is fine when they are what the document is about.

**Length comes from the code.** A small file gets a short document. Do not pad a
section to look complete; a section with nothing to say says so in one cited
sentence.

## Report back

In chat: the document's path, the scope (file count and lines), the commit it
describes, the reproduction commands run and their results, the defects by
severity, and anything that could not be done (a command not run, a file left
unread). When a re-run changed sections, name them.
