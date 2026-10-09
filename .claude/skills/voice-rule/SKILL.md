---
name: voice-rule
description: Record a writing rule the author has stated, so it survives the session. Use whenever the author says to avoid a construction, a word, or a habit ("stop starting sentences with While", "don't use that phrasing", "I never write it that way"), whether they say it in chat or write it into the report. Appends the rule to the voice profile, adds a pattern to the linter when the rule is mechanically checkable, and tests the pattern before it ships.
---

# Record a voice rule

The author states rules about their own writing in passing, usually while
reacting to a sentence they did not like. A rule that stays in the conversation
is gone by the next session, and the same construction comes back. This skill
is the path from a spoken correction to an enforced rule.

**Run it the moment the author states a rule.** Not at the end of the round, and
not only when they use the word "rule": *"avoid that kind of sentence"*, *"I
wouldn't say it like that"*, and *"stop doing X"* are all rules.

## 1. Say the rule back before recording it

One line, and wait for the answer when anything is ambiguous. The distinction
that matters is scope:

- **A ban** applies everywhere and goes to `HARD` in `voice.py`.
- **A preference** is right most of the time and goes to `SHAPE`, which is
  advisory.
- **A one-off** is a reaction to a single sentence. Fix the sentence, record
  nothing. Ask if you cannot tell.

**Never infer a rule from a single edit.** One replaced semicolon is not a
policy. A rule is recorded when the author states it, or when the same
correction has landed three times and you have put it to them.

## 2. Write it into the profile

`.claude/voice/profile.md` is the authority. It is personal and kept out of the
repository, so a fresh clone has none: if it is missing, create it with three
headings, `# Voice profile`, `## Stated rules` and `## History`, then record the
rule. Add the rule under *Stated rules*,
in the section it belongs to, with an example of the construction and the
rebuild that replaces it. Then add a dated line under *History* saying what was
recorded and where it came from. The profile is hand-maintainable on purpose:
keep it short, and put the rule where a reader would look for it rather than
appending it to the end.

## 3. Make it mechanical, when it can be

A rule the linter cannot see is a rule that will be broken. Add a pattern to
`.claude/scripts/voice.py`: `HARD` for a ban, `SHAPE` for a preference. Each
entry is a compiled regex and the instruction that replaces it, written as a
repair rather than a complaint: *"em-dash. Use a comma, a semicolon, a colon,
or parentheses"* tells the writer what to do.

**Test the pattern against real prose before you finish**, both directions:

```bash
python3 .claude/scripts/voice.py lint <a file with the construction>   # must catch it
python3 .claude/scripts/voice.py lint outputs/<a finished report>.md   # must not flood
```

A pattern that fires on every third sentence of an accepted report is wrong,
and the author will start ignoring the whole linter because of it. Narrow it,
or file the rule as `SHAPE`. Say in chat which list you used and why.

Some rules are not mechanisable: *"the tail is usually unnecessary"* is a
judgement about whether a clause carries a fact. Record those in the profile
and say plainly that no pattern enforces them.

## 4. Report back

Three lines: the rule as recorded, where it went (`HARD`, `SHAPE`, or profile
only), and what the test found. If the new pattern flags existing reports, say
how many hits and offer to fix them; do not go and rewrite a finished document
on the strength of a rule recorded a minute ago.
