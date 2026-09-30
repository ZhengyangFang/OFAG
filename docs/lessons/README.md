# Lessons

This is a development and runtime knowledge corpus, not a tally of problems
first discovered by the completed agent system. The `found_by` field separates
development, building, and agent findings; its meaning is defined below. An
agent retrieving a recorded lesson may apply a check without independently
discovering the original failure.

`lessons.yaml` records every failure found while developing and testing the
agent system on three field cases —
Utah FORGE, Cedar Rapids and the Llano Uplift — plus a legacy aeromagnetic
case (Stillwater), a seismic field record (Soda Lake), and while building the
agent layer. Each one is a record,
not an essay: the rule it teaches, the sentence it came from, the method
whose data it happened on, the procedure step that covers it, and the test
that fails if it comes back.

Most of them **ran clean**: the inversion converged, the misfit looked
healthy, nothing raised an error, and the answer was wrong. An agent whose
objective is "the run succeeded" is satisfied by every one of those. That is
why this corpus is a list of obligations rather than a knowledge base to
consult when stuck, and why the obligations are enforced in code rather than
asked for in a prompt.

For current counts, run:

    uv run python scripts/development/what_the_mechanism_reaches.py

It prints the corpus by source, method, finder, decision and owning role,
then which of the lessons something enforces and which a test checks. This
README states no counts, so it does not go out of date when a lesson is
added.

## How the multi-agent system uses them

The lessons are one of three layers. Each layer is used by different parts
of the system:

| layer | what | where | used by |
| --- | --- | --- | --- |
| knowledge | lessons and the procedure they are placed in; published practice beside them, marked `received` | `lessons.yaml`, [`../agent_validation_and_debugging.md`](../agent_validation_and_debugging.md), [`../knowledge/`](../knowledge/) | every role, through retrieval |
| enforcement | the gates and tests that refuse a lesson's failure | `covered_by`, `src/ofag/agent/retrospect.py` | the tool surface, at the moment of the call |
| evaluation | lessons posed again as work, to see whether an agent catches them | [`../development/benchmark/`](../development/benchmark/) | exploratory development experiments |

In practice:

- **Retrieval.** `ofag.retrieve` and each role's brief quote the lessons and
  procedure steps that bear on the role's stage and task
  (`src/ofag/agent/retrieval.py`). `ofag.lessons` filters them by step,
  method, decision or coverage.
- **Ownership.** Each procedure step belongs to the role whose tools act at
  it (`STEP_OWNER` in `src/ofag/agent/roles.py`), and a lesson belongs to its
  step's role. Ownership is derived from the step, never stored with the
  lesson.
- **Audit.** The audit role owns no step. Every lesson that ran clean is on
  its list, because those are the ones the role that produced a run cannot
  see in its own work.
- **Growth.** Any role that meets a failure the corpus does not name proposes
  it with `ofag.propose_lesson`. A person decides whether it becomes a lesson
  (see [Adding a lesson](#adding-a-lesson)).

## A lesson

```yaml
- id: F054
  former_id: L19
  title: "A declared turn-off ramp a thousand times too short, and the rule that needed it"
  source: case3_llano
  methods: [tdem]
  found_by: agent
  tier: measured
  silent: true
  decision: none
  procedure: A1
  covered_by: tests/test_tem_dialects.py
  evidence: "The Llano .usf declares /RAMP_TIME 5.1e-9 s for its 1.5 A sweeps ..."
```

| field | meaning |
| --- | --- |
| `id` | `F` and three digits, never reused. See [Identifiers](#identifiers). |
| `former_id` | the identifier the lesson had before 2026-09-24, kept because papers and commit messages cite it |
| `title` | the rule, not the incident: "A cell is not a unit of ground" |
| `source` | where it was found: `case1_forge`, `case2_cedar_rapids`, `case3_llano`, `case1_stillwater`, `soda_lake` for the seismic field record the SEG-Y importer and the elastic FWI were exercised on ([`../development/seismic_field_data.md`](../development/seismic_field_data.md); not one of the paper's cases), or `agent` for the agent layer itself |
| `methods` | the method whose data it happened on: `tdem`, `fdem`, `ert`, `mt`, `gravity`, `magnetic`, `seismic`, `boreholes`. Empty when no survey data was involved, such as a scheduler, a harness, or a constant in a script. |
| `found_by` | `development`: while the agent system was developed and tested on the field cases. `agent`: reported by an agent through the agent layer that nothing else had caught. `building`: while building or checking the agent layer. |
| `tier` | what stands behind the lesson, and so what it may be used for. See [Tiers](#tiers). |
| `silent` | the run finished, looked healthy, and was wrong |
| `decision` | whether it was a choice, and whose. See [Decisions](#decisions). |
| `procedure` | the step of the procedure that covers it, or null. A null means no procedure step covers the lesson, so nothing can enforce it. |
| `covered_by` | a test that fails if the defect returns, or null. A null is a gap, not a silence. |
| `evidence` | quoted, word for word, from a document in `docs/`: the case write-up where there is one, otherwise the procedure or a benchmark result. `tests/test_lessons.py` fails if the quote no longer appears, so the record cannot drift from the account it came from. |

`found_by: development` records when a lesson was found, not by whom. Only
`agent` is a claim about the finder: an agent working through the finished
agent layer reported it and nothing else had caught it.

## Identifiers

Lessons are `F001`, `F002`, and so on: F for a recorded failure. F001–F075
were assigned in the order of the paper's cases at the renumbering on
2026-09-24; a lesson added after that takes the next number, from F076, and a
number is never reused. The number says nothing about where a lesson came
from; `source` says that.

Until 2026-09-24 the identifiers were lettered by site: `P` for Stillwater
and Utah FORGE, `C` for Cedar Rapids, `L` for Llano, `S` for the agent layer.
Two things were wrong with that. The letters meant nothing to a reader
outside the project. Worse, `C1` to `C5` were both Cedar Rapids lessons and
steps of the procedure. The renumbering kept the order of the paper's cases:

| lessons | source | were |
| --- | --- | --- |
| F001–F030 | Utah FORGE (case 1) | P19–P48 |
| F031–F036 | Cedar Rapids (case 2) | C1–C6 |
| F037–F054 | Llano Uplift (case 3) | L1–L16, L18, L19 |
| F055–F057 | the agent layer | S1, S2, S4 |
| F058–F075 | Stillwater (legacy) | P1–P18 |

There was no `L17` or `S3` to renumber: L17 was withdrawn into F044 the day
it was written, and S3 was absorbed into F056. `ofag.lessons` accepts either form of
identifier (`{"id": "P19"}` returns F001), and every lesson's retrieval
passage carries its former identifier, so a query copied from an old note
still finds it.

Procedure steps keep their names (`A1`–`A15`, `B1`–`B7`, `C1`–`C5`), and no
lesson can be mistaken for one.

## Tiers

A lesson's tier asks the same question as `ConventionCheck.against`: *what
do you have, outside your own reasoning, that says this is true?* The answer
decides whether the lesson may gate real work.

| tier | what stands behind it | may |
| --- | --- | --- |
| `measured` | we hit it, on real data, and measured it | become a mandatory obligation |
| `reproducible` | someone else hit it and left a minimal reproduction | be promoted by reproducing it here |
| `declared` | the engine's own documentation says so | become a check, with the tolerance measured here and never quoted |
| `received` | a textbook or a standard says so | only propose a check |
| `synthetic` | injected on purpose to see whether a check fires | only measure coverage, never gate work |

Every lesson so far is `measured`. `measured` says the lesson was measured
when it was found. It does not say the data is still on disk: the Stillwater
release was removed when that case left the paper. Whether a lesson can be
replayed is answered by code (`Lesson.data_present`, and a benchmark probe
that runs), not by this field.

The tiers exist because of **F039**. A rule that sounded quantitative — 9.75
m of relief over 188 m, so topography must be modelled — had never been
measured, turned out to be false, and was right by accident. It would have
been carried into the next case as a reason. A `received` lesson that cannot
gate anything until it is measured makes that mistake structurally
impossible.

## Decisions

| value | meaning | what an agent should do |
| --- | --- | --- |
| `none` | a defect; nobody chose anything | fix it |
| `measurable` | a choice the data can settle | **measure it, do not ask** |
| `judgement` | a choice the data cannot settle | ask, record the reason, and record what would reverse it |

The middle row is the one a decision agent gets wrong. Asking about a
question the data can answer turns a measurement into a guess with a
signature on it. `asking.classify` enforces this by running the cheap probe
instead of posing the question.

## Adding a lesson

**From a case, by hand.** Take the next free `F` number and append the
record. The loader refuses a malformed or repeated identifier, a method
outside the vocabulary, and a `covered_by` that names a missing file.
`tests/test_lessons.py` refuses a `procedure` that is not a step.

**From an agent.** A proposal made with `ofag.propose_lesson` lands in the
project's `candidate_lessons.jsonl`. It never lands in this file.
`ofag.journal` lists pending proposals. To admit one, check `seen_at`, copy
the proposal in with the next `F` number and `found_by: agent`, and quote
the evidence from where it was seen.

**When writing a check for a lesson,** cite the lesson's identifier in the
test's docstring and set `covered_by`. A grep cannot tell a write-up's
citation from a check's, so coverage is only measurable if checks say what
they are for.

## Where more could come from

These are the mistakes this project made, on the methods it attempted, so
the sample is thin and biased. Whole classes are absent because nothing here
touched them: datum shifts, diurnal and tidal corrections, instrument drift,
anisotropy read as structure, culture noise.

Three sources have been surveyed:

- **The literature enters at `received`, in [`../knowledge/`](../knowledge/).**
  One file per method, each section a practice a paper or a textbook states,
  with its DOI, placed at a stage and a procedure step like a lesson. The
  classes above are covered there first. A section only proposes a check;
  measuring the check here is what would make it a lesson.

- **Engine issue trackers enter at `reproducible`.** pyGIMLi and SimPEG
  between them hold on the order of a hundred closed convention-class
  reports with reproductions attached. Several independently match lessons
  here: pyGIMLi #900 is F037, and SimPEG #1691 is the impedance ground of
  F015 and F023. An issue is promoted only by running its reproduction here.
- **A release's own metadata enters at `declared`, per dataset.**
  `src/ofag/formats/fgdc.py` separates what an FGDC record concedes from
  what it claims. **A claim in a metadata record is a hypothesis with a
  citation**: the Llano record says reciprocal times "were generally
  acceptable", and F044 is a pair that disagrees by 39 ms.
