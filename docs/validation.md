# Validation and audit in OFAG

OFAG validates a run specification before dispatch and stores run events and
artifacts. The Audit Agent role and `ofag.audit` tool are implemented; role,
independence, and ledger tests pass. In the agent tool workflow, a separate
audit is required before the modelling role can use a completed inversion.
The case scripts also call services directly. On 2026-09-29, the saved runs
currently selected by the three case states were adopted for retrospective
diagnosis and then reviewed through the role-restricted `ofag.audit` tool. The
[case audit register](case_audit.md) names each run, its pass or veto, and the
limits of that verdict. This does not mean the original case-script execution
passed through the agent gate at the time it ran. A successful solver exit is
not, by itself, an accepted geological interpretation.

The current checks cover declared units and coordinate conventions, method
specific input requirements, execution state, numerical diagnostics, and the
source and spatial support of interpreted units. Case-specific checks are
documented with their measured outcomes in the [Utah FORGE](case1_forge.md),
[Cedar Rapids](case2_cedar_rapids.md), and [Llano](case3_llano.md) accounts.
The [unit policy](unit_policy.md) and [interpretation guide](interpretation.md)
describe the shared contracts.

Agent roles retrieve a procedure and a corpus of recorded failure modes during
normal work. Many entries in that corpus were found during development and
then encoded as checks or prompts. A later agent use of such an entry is not
independent discovery of the original problem. The corpus records whether an
entry was found during development, while building the agent layer, or by an
agent using the completed layer. The [procedure](agent_validation_and_debugging.md)
and [corpus](lessons/) remain available for that distinction and for the
running software.

Audit has two boundaries. It can verify that the recorded evidence and
declared checks are present, and it can return a result for revision. It
cannot prove that a physically plausible measurement settles every scientific
judgement. The exploratory [benchmark](development/benchmark/) documents this limit and
is not used here as evidence that obligations improve answer quality.
