# Dossier: the author's standing record

Facts about the author come from here. Nothing in a CV, a letter, an
application answer or a bio is written from the model's memory of an earlier
conversation: a date, an employer, a title, a metric, a publication or a
qualification appears in a piece only because a file in this folder says it.

That is the compose pipeline's version of the workspace's first rule. A
research report may not cite a URL nobody fetched; a CV may not claim a year
nobody can show. The failure is the same shape and it is more expensive here,
because the author signs the result and sends it to a real reader.

## Layout

Any structure works, and the four folders below are a starting point.

| Folder | What belongs in it |
|---|---|
| `cv/` | The master CV, in full, and any long-form variant of it |
| `letters/` | Letters and applications already sent, whatever the outcome |
| `bio/` | Biographies at each length, personal statements, profile text |
| `work/` | Publications, patents, talks, project write-ups, metrics, references |

Longer is better than tidier. The master CV should hold every role, date,
figure and result the author might ever want to draw on, including the ones a
two-page CV leaves out. A piece selects from the dossier; it never adds to it.

## How it is read

    python3 .claude/scripts/external_index.py scan dossier

Files are indexed by content hash and read once, so adding to this folder at
any time is cheap. Update a file when the facts change rather than writing a
second copy: two CVs with different dates for the same job is the failure this
folder exists to prevent.

## What is not here

Anything specific to one piece goes in that run's `source_material/`: the job
posting, the call, the form with its word limits, the thread being answered.
This folder is what stays true across all of them.
