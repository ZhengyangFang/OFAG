# Received practice

The lesson corpus (`../lessons/lessons.yaml`) and the procedure
(`../agent_validation_and_debugging.md`) record what this project measured on
its own field cases. That is a thin and biased sample: whole classes of
failure are missing because no case touched them. This directory holds the
other kind of knowledge — what the published literature says a practitioner
of each method has to do — so that the agents are briefed on it too.

One file per method (`gravity.md`, `magnetic.md`, `ert.md`, `seismic.md`,
`mt.md`, `tdem.md`, `fdem.md`, `boreholes.md`) and one for reading finished
inversions into a model (`model_reading.md`).

## What a section may be used for

Everything here is at the **`received`** tier of `../lessons/README.md`: a
paper, a textbook or a standard says so, and nothing in these files was
measured on this project's data. A section may propose a check. It never
passes or refuses a run until that check has been measured here, at which
point what was measured becomes a lesson and the section stays as its
background.

Agents see the difference. `ofag.retrieve` returns these passages with kind
`received` and their DOIs, and a role's brief marks each one `[received]`
beside the measured lessons.

## A section

```markdown
## A heading that states the practice as a rule

Stage: A | Step: A7 | Methods: mt

Two to four short paragraphs in our own words: what the practice is, why, and
what goes wrong without it.

**Check.** One concrete check an agent can run.

**Sources.**
- Author, A. (Year). Title. *Journal*, vol(issue), pages. doi:10.xxxx/yyyy
```

The line under the heading is read by `passages_from_knowledge` in
`src/ofag/agent/retrieval.py`, and the retrieval filters apply to it exactly
as they apply to a lesson:

| field | meaning |
| --- | --- |
| `Stage` | `A` before an inversion, `B` after a bad misfit, `C` before reading a result into a model |
| `Step` | the procedure step it belongs under, whose letter is the stage, or `none` |
| `Methods` | a comma-separated subset of `tdem, fdem, ert, mt, gravity, magnetic, seismic, boreholes` |

A file is refused when it is read — not retrieved unfiltered — if a section
lacks that line, names a method outside the vocabulary, puts a step in the
wrong stage, uses a `###` heading, or cites no DOI.

## Adding to it

Paraphrase; do not reproduce a source beyond a short phrase. Resolve every
DOI against Crossref before writing it down and check that it returns the
work cited — the procedure's step A13 applies to this directory as much as to
a case's source table. A claim is attributed only to a source that makes it.
