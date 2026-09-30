# Benchmark

This is an exploratory development evaluation, separate from the three field
cases in the TLE manuscript. Its tasks and historical answers are public in
this repository, so a future run against an agent that can read the repository
is not a blind test. The summary below describes the observed limitations of
the existing runs and should not be cited as proof of improved answer quality.

The lessons in [`../../lessons/lessons.yaml`](../../lessons/lessons.yaml) are
failures that already happened. This folder turns some of them back into
work that can be handed to an agent. The agent is scored on whether it
catches the failure, without being told a failure is there.

There are two kinds of item, because failures come in two shapes:

| | a judgement | a silent failure |
| --- | --- | --- |
| what it looks like | a question the data cannot settle | a task whose result looks fine and is wrong |
| file | [`judgement.yaml`](judgement.yaml) | [`silent.yaml`](silent.yaml) |
| schema and scoring | `src/ofag/agent/replay.py` | `src/ofag/agent/noticing.py` |
| the agent is given | the question, and the output of a probe script that reads the data | the task, phrased as the job and nothing else |
| the answer is | a `DecisionRecord` | prose |
| scored on | whether it should have been a question at all; the facts it had to use (`must_name`) | whether it named the tells the defect leaves |

Each item names the lesson it came from (`lesson: F037`).

## Judgements

A judgement once decided by somebody who then wrote the answer into a
constant is posed again. `historical` holds what was decided and is withheld
from the agent. The situation comes from the data, not from prose: each item
names a probe in `scripts/development/replays/F###.py` that reads the release and prints
what was on the table, without hinting that there is a right answer.

Most of an answer's quality is checked by the `DecisionRecord` schema rather
than by opinion: two options, a cost in the project's units, a reversal
condition, and no claim that a measurement settled a judgement. The first
thing scored is whether the question should have been one at all. An answer
that returns `measured` has either found something this project missed or
claimed a measurement it did not make.

## Silent failures

The defect sits in the data, and nothing in the task says it is there. The
task must not hint: `noticing.refuse_hinting_tasks` refuses one that names a
tell. `on_path` separates two kinds of task:

- **On-path.** The task asks the very question whose answer is the tell.
- **Off-path.** The task asks for a product, and the tell sits in an input
  the work uses but is not asked about.

Off-path is where a gate is worth most, so that comparison is the one the
file exists to make. `gates` names the gate each item is about. There is no
second arm with the gate switched on, because the gates' own tests already
prove they fire. What is not settled in advance is whether a working agent
would notice the defect without the gate.

## Running it

There is no one-command runner yet. Both harnesses are a corpus plus a
scoring function, and the agent session is the caller:

```python
from ofag.agent.replay import load_replays, score            # judgements
from ofag.agent.noticing import load_silent_replays, score_noticing  # silent
```

Pose an item's `question` (with its probe's output) or its `task` to an
agent, and pass the answer to the scoring function. The agent must not be
able to read `docs/` or `scripts/case*.py`, because they hold the answers.
The results so far show this is harder than it sounds: see *Leaks* below.

## Historical results

The detailed exploratory run reports are retained in the author's local
development archive, outside the open-source release. The task definitions
remain public so the replay API can be inspected, but the earlier runs are not
part of the evidence offered for the three field cases or a claim of improved
Agent performance. They were small and some attempted blind comparisons were
contaminated by answers already present in this repository.

What the runs found is recorded as lessons: **F052, F053, F054, F091 and
F092** are defects an agent reported that nothing else had caught. **F056** is
the harness's own leak. F091 (a depth-of-investigation mask that leaks into a
conductor) and F092 (a claimed gain that was a translation) were reported
beside the question an off-path run was asked and recorded as lessons later.

## What this cannot do

- **Score itself.** Every historical record was written by the same author
  as the answers it grades. The harness exists so that somebody else, or
  another model, can run it.
- **Hide its answers from an agent that reads the repository.** A repository
  that records its reasons cannot host a blind replay against itself (F056).
  Three leaks came from three different kinds of file, and every one was
  reported by the agent that met it, not by the harness.
- **Score seeing with keywords alone.** A keyword rubric scores the
  vocabulary of the answer, not whether the agent saw the defect (F057), so
  it is reported as a lower bound.

## Checks, tested against their own claims

A separate kind of measurement lives in the test suite rather than here.
`tests/test_fault_injection.py` injects the fault that each convention check
says it catches, and asserts that the check fails. That is the `synthetic`
tier's only job: a fault invented here measures a check, not the world, so it
may never gate real work.
