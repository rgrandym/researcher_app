# The kinds, and how each one fails

Read the entry for the kind being written. Every kind obeys the voice profile
and the dossier rule; what changes is the shape, the reader, and the mistake
that ruins it.

---

## cv

**Reader:** a person giving it twenty seconds first, and a parser before that.

A CV is not rewritten for each posting. It is **selected and reordered**: the
same true record, with the parts that answer this posting brought forward and
the parts that do not pushed back or dropped. Every line in the output exists,
verbatim in substance, in `dossier/cv/`.

- **Order by relevance to the posting.** Roles stay in reverse date order; the
  bullets inside them are ranked by what this posting asks for.
- **Every bullet states a result.** What was done, what changed, what size. The
  size comes from the dossier or it is left out. A bullet that only names a
  duty tells the reader what the job title already told them.
- **Keep the vocabulary of the posting where it is honestly the same thing.**
  If they call it "assay qualification" and the record calls it "method
  validation", use theirs and keep the meaning. Do not adopt a term for work
  the record does not show.
- **Length is a constraint, and cutting is the job.** Two pages unless the
  field says otherwise; academic CVs run long by convention and that is not a
  licence for the rest.
- **Dates, titles and employers are copied, never retyped from memory.** A
  transposed year in a CV is a lie the author signs.
- **No skills bar charts, no percentages of proficiency, no rating out of
  five.** They assert precision that does not exist.
- **Ship `.docx`.** Parsers mangle multi-column PDFs; a single-column .docx
  survives them. Offer the PDF alongside for a human reader.

Failure mode: a CV that reads well and quietly promotes a contribution. Six
months later the author is in an interview defending a sentence they did not
write.

---

## cover-letter

**Reader:** the hiring manager, who has read forty of these and is looking for a
reason to stop.

Three or four paragraphs, on one page, and it does one job: connect the
author's record to **this** posting's actual problem.

- **Open on the problem.** The strongest first line names what the group is
  trying to do, taken from the posting or their published work. An opening
  about the author's enthusiasm is the line every other applicant wrote.
- **The middle is one or two concrete pieces of work**, described so the reader
  can picture them, chosen because they map to the problem. Not a summary of the
  CV; the CV is attached.
- **Say why this employer.** One specific, verifiable thing about them. If
  nothing specific is known, ask the author or leave it out. A generic
  compliment is worse than no sentence.
- **Close with what happens next**, plainly and without pleading.
- **No paragraph the author could send to a different employer unchanged.**
  That test alone catches most bad letters.

Failure mode: a letter that restates the CV in sentences. It costs the reader a
minute and tells them nothing new.

---

## answer

An answer to a specific question on a form or in an email: "describe a time
when", "why this fellowship", "how would you approach X", a reply to a technical
question in a thread.

- **The word limit is the specification.** Land within a few words under it.
- **Answer the question asked, in its first sentence.** Forms are read in
  parallel across candidates, by section.
- **A behavioural question takes a real incident from the dossier**, with the
  situation, what the author did, and the outcome. Invented incidents are the
  single worst failure available in this lane.
- **Where the question has parts, the answer has parts, in their order.** If
  they ask three things, a reader must be able to find all three.
- Structure is invisible: no headings inside a 300-word box unless the form
  provides them.

Failure mode: a fluent answer to a slightly different question.

---

## statement

Personal statement, research statement, motivation letter, a bio. Longer than a
letter, and read as evidence of how the author thinks.

- **One argument, carried from the first paragraph to the last.** A statement
  that lists achievements has no argument and reads as a CV in prose.
- **The trajectory is the point**: what the author has been working towards,
  what they did about it, what comes next. Chronology serves that and is
  otherwise not interesting.
- **A research statement may carry citations**, and they follow the workspace's
  citation doctrine: `.claude/references/citation-style.md`. Everything else in
  this file's list does not.
- **A bio is written to length.** Ask which: 50, 100, or 250 words, and write
  that one rather than a long version to be cut later.

Failure mode: sincerity substituted for specificity. Every claim about what the
author cares about is followed by what they did about it, or it comes out.

---

## piece

Anything else the author writes and signs: a memo, a post, an email of
substance, a section of a document, a rough draft to be developed.

- **A draft the author supplied is the starting text.** Preserve its concepts,
  its order and its emphasis. Develop it; do not replace it with a better essay
  on the same subject.
- **Ask what it is for and who reads it** before writing, unless it is obvious.
  One question is cheaper than a piece aimed at the wrong reader.
- **Where it asserts something about the world, it is checkable**, and §7 of
  the skill applies: source it or flag it.

Failure mode: the author's rough draft returned as fluent prose with their
argument sanded off.
