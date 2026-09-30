# Case 1b: the Utah FORGE site, Milford, Utah

A worked case on real, public data, against a published model of the same data,
and a log of what went wrong on the way.

For the final input sources, execution stages, and manuscript figure mapping,
start with the [reproduction guide](../reproducibility.md). The numerical and
interpretive limits below are part of the case result. This account also keeps
the development history used by the running agent's retrieval corpus; an entry
in that history does not by itself show that an agent discovered it anew.

This is the second half of case 1. The Stillwater Complex
([legacy case](stillwater.md)) established that OFAG can take a real survey from
delivery to a validated model, and ran out of two things: boreholes deep enough
to check a depth, and gravity dense enough to invert. FORGE has both, and one
thing Stillwater did not — a published inversion of the same stations, released
cell by cell, so a disagreement is a number rather than an impression.

This case's problems are F001–F030. The log is the point:
every entry is a place where the obvious reading of the data is wrong, and
where a person who did not stop to check would have produced a plausible, wrong
answer. Those are the capabilities the agent layer has to have, and
`docs/agent_validation_and_debugging.md` is the log turned round: organised by
when to act rather than by what went wrong, as procedures the agent runs —
checks before an inversion, a ladder after a bad misfit, and a third set for
reading a result into a model.

## The data

Every input has a permanent identifier -- a DOI where one exists, and the
column is headed *Identifier* because for two rows none does. The rule is the
same as Stillwater's, it governs what these cases argue from rather than what
OFAG will read, and it earned its keep again here: PACES, the gravity database
that supplied 3,321 of this survey's 3,735 regional stations, is the same one
that died during the Stillwater investigation.

| What | Source | Identifier |
| --- | --- | --- |
| FORGE 3D gravity models, data and report (Hardwick and Witter, 2019) | Utah Geological Survey / GDR | 10.15121/1542061 |
| Utah FORGE gravity and TEM, 3,735 stations / 68 soundings (Hardwick and Nash, 2018) | UGS / GDR | 10.15121/1452733 |
| Phase 3 magnetotellurics, 122 sites (Wannamaker and Maris, 2020) | GDR | 10.15121/1776598 |
| Well 16A(78)-32 wireline logs | Utah FORGE | utahforge.com |
| Seismic reflection interpretation, 3D survey geometry (Miller, Allis and Hardwick, 2019) | UGS Misc. Pub. 169-H | 10.34191/MP-169-H |
| Well and pad GPS coordinates, December 2021 (Erickson, 2021) | GDR | 10.15121/1838418 |
| Terrain, 3DEP **1 arc-second** (30 m) | USGS | no registered DOI — see below |

**Three of the four identifiers above were wrong, and are corrected.** The
gravity release is 10.15121/1542061 and not `1559241`; the TEM and gravity
release is 10.15121/1452733 and not `1452445`; the magnetotellurics are
10.15121/1776598 and not `1846183`. Each was the right shape, the right prefix
and the right agency, and each resolved to a different submission or to
nothing. They were found by dereferencing the table one identifier at a time,
which is the whole of A13 and had never been done to this table. F030.

**The terrain row was wrong in both columns and is corrected above.** It read
"3DEP 1/3 arc-second" against DOI 10.5066/F7PR7TFT. The raster is 29.99 m, so
it is 1 arc-second and not 1/3; and that DOI resolves to *Shuttle Radar
Topography Mission (SRTM) 1 Arc-Second Global*, which is a different mission,
a different sensor and a radar surface rather than bare earth. Settled by
measurement rather than by the filename: sampled at 211 points across the
survey, the raster sits 0.012 m from the current 3DEP 1 arc-second product,
which is 3DEP and not SRTM. Of the twelve 3DEP downloadable collections
exactly one, Seamless 1 m, carries a registered DOI, so there is no DOI to put
in that cell — which is the reason the wrong one went in. F030.

Not in this repository: fetched into `data/case1_Utah FORGE/`, which
`.gitignore` excludes. The citations are here; the bytes have an authoritative
origin already. The delivery was 7.75 GB and what is kept is 0.38 GB — the
whole of it seismic SEG-Y and well logs nothing here reads, minus the one DPHI
curve that mattered, kept as a 0.17 MB CSV.

## What is being looked for

The case document went a long way without saying this, which is its own kind of
defect: every number below is about how well something was measured, and none of
them mean anything without the target.

**FORGE is a Department of Energy test bed for Engineered Geothermal Systems** —
you drill into hot crystalline rock and make your own reservoir, so there is no
plume, no alteration halo and no conductor to chase. The thing that has to be
known is **how deep the granitoid basement is**, everywhere, because that is
where the wells have to land.

So the target is a *surface*, not a body: the **top of the granitoid basement**,
separating low-density basin fill above from higher-density granitoid below. It
was mapped by a 3D seismic reflection survey over ~5.5 × 4.5 km (Miller et al.,
2019) and that horizon became a fixed constraint in the gravity modelling. In
Witter's own words, the purpose was "to show where the gravity data may or may
not support this assumption" — the gravity is an **independent test of a seismic
surface**, over an 8.25 × 5.25 km area that deliberately extends east beyond the
seismic, to where granitoid crops out at the land surface.

### How many layers the published model has: two

Basin fill at **2.42 g/cm³** over granitoid basement at **2.65**, split by that
one seismic surface. Both numbers are from the neutron density log in well
58-32. The inversion then varies density around those two starting values, and
what it is read for is where it *departs* from them.

Two models were released, differing only in which surface is fixed: model 1 uses
the original seismic horizon, model 2 a version hand-modified where model 1 fitted
worst. They fit equally well — 0.0298 and 0.0295 mGal RMS — which is the
non-uniqueness in one line. This case validates against model 1 and builds its
reference from model 1's surface, which the delivery ships only inside its
workspace file (F024, F099). It first built it from model 2's.

### He tried more layers, and it failed

This is the part worth knowing, because OFAG's petrophysical inversion attacks
the same problem from the other side.

Well cuttings show basin fill lightening upward, ~2.4 g/cm³ at 660 m to ~2.0 at
surface. Witter tried to capture that by **fixing geometry and letting density
float**: extra horizontal boundaries at 200, 400 and 600 m depth, intended to
hold 2.1, 2.2 and 2.3 g/cm³ fill. The result was, in his words,
*"non-geological (e.g. a near surface sediment layer with a density of
2.75 g/cm³)"*, and he drew the general conclusion:

> Using geologically reasonable "guesses" as fixed geologic boundary constraints
> instead can lead to gravity inversion model results which are geologically
> unsatisfying and undoubtedly incorrect.

OFAG's PGI does the reverse: it **fixes the densities and lets the geometry
float**. Four declared classes, no boundary imposed, and the inversion decides
where each one goes. That produced 97 per cent of the modelled volume in the two
classes Witter used and 2.6 per cent in the two this case added — a result of
the same kind he was after, reached without guessing a depth.

It is not a clean win. The petrophysical model agrees with his released model
less well than the plain smooth one does (+0.613 against +0.773), and 9.9 per
cent of it sits below every class it was given (F009). But the comparison is
real, it is on the same data, and it is the clearest thing this case has to say
about *method* rather than about this basin.

### What the gravity actually said

Witter's conclusions, and what OFAG's smooth model says about each:

| His finding | Our model |
| --- | --- |
| The data are "largely consistent with a simple, 2-layer geologic model" | Agreed: 97% of the modelled volume falls in his two classes, and 60% of the columns support the seismic surface to within 100 m, a share that depends on how it is counted (*What the density model decides*) |
| The SW quadrant needs more low-density material, more likely lighter sediments than a deeper basement | Agreed on the reading: over the 6.6 km² he lowered by a median 402 m, the gravity asks for −120 m, a third of it |
| Four locations need higher-density rock: shallower basement, diorite, or silicified fill | All four places he raised want more mass here, three beyond chance (p = 0.007, 0.036, 0.046). *What the density model decides* |

## What is reproduced

Witter's inversion, on his stations: the same 323 of the 518 Phase 2C
measurements, matched back to the delivered observations by coordinate —
exactly, to the metre, all 323 — the same 8.25 × 5.25 km volume, the same 50 m
octree, the same two-layer starting model, the same reduction density. Where
the numbers differ, the difference is the result.

Then a second inversion the published one does not have: a petrophysically
guided inversion (PGI), told what the four rocks of this basin are and asked
which is where. That is the part OFAG contributes rather than reproduces, and
it is also the part that shows what the data will not support.

Then the survey's other two methods, which the published work treats separately
and which are here because gravity alone does not determine this model: 66
ground TEM soundings and 82 magnetotelluric sites, each inverted as a layered
earth, site by site. The magnetotellurics took four attempts to get right and
the three wrong answers are kept in the log, because each of them was plausible
and had a measurement behind it (F023).

## Problems

### F001 — SimPEG's "gz" is the negative of a gravity anomaly

The sharpest finding in either case, and the one that had been wrong in OFAG
since the gravity plugin was written.

SimPEG works in a right-handed frame with z upward, so `gz` is the **upward**
component of the field a density contrast produces. Buried excess mass pulls
downward, and `gz` comes back negative. A Bouguer anomaly is the opposite sign
by definition — excess mass reads as a high — and that is what every gravity
dataset OFAG imports contains. Fed to SimPEG unconverted, an inversion explains
a gravity high by **removing** mass.

Nothing about the run says so. It converges, chi-squared lands where it should,
no cell reaches a bound, the residual maps look like residual maps. The
recovered model is simply the negative of the ground.

What found it was the published model. Forward-modelled through OFAG's own
simulation and compared with the observed anomaly over the same 323 stations,
Witter's density model correlates at **−0.966**. Negated, **+0.966**.

| | Correlation with the published model | RMS difference | Cells at a bound |
| --- | --- | --- | --- |
| Before | +0.233 | 0.146 g/cm³ | 0.9% |
| After | **+0.766** | **0.084 g/cm³** | 0.2% |

Why OFAG's tests did not catch it: every one of them makes its data with the
same simulation it then inverts, so the two sign errors cancel exactly. A
round-trip cannot see a convention. `tests/test_gravity_sign_convention.py`
checks against arithmetic instead — the field of a point mass, which does not
care what convention anyone adopted — and all three of its tests fail if the
sign is put back.

**Agent capability:** know that a self-consistent test is not a correct one,
and validate an engine's convention against something outside the engine. The
general form is worse than the gravity case: any sign, axis or handedness
agreement between a framework and a physics library is invisible to every test
built from that library.

### F002 — The reduction density of the delivered data is not the reduction density of the modelling

Both numbers ship in the same folder and neither is wrong.

The survey's own README, describing the exact column used: *"gCBGA: Complete
Bouguer gravity anomaly using reduction density of 2.67 g/cc"*, and the ArcGIS
metadata says it a second time. The modelling report, eleven pages into the
same delivery: Nettleton and Parasnis both need relief and this basin has none,
so tests from 2.50 to 2.67 settled on *"a terrain correction density of 2.55
g/cm3 ... used for all subsequent 3D gravity modelling in this study"*.

This is not bookkeeping. A density model is a set of contrasts against the
reduction density, so the same recovered model means 2.42 g/cm³ against one
background and 2.54 against the other. Reducing at 2.67 and then reading the
result against Witter's absolute densities compares two different quantities
and reports the 0.12 difference as a finding.

Re-reducing is exact — both the slab and the terrain correction are linear in
density, and the file carries the inner and outer zone corrections separately —
and it is worth **0.404 mGal RMS** once the level is removed. Small against a
25 mGal anomaly, thirteen times the uncertainty the data is weighted by, and
correlated with elevation, which is the shape a density model turns into
structure. Independently confirmed by the forward test in F001: the published
model against the 2.55 data correlates at +0.966, against the 2.67 data
at +0.849.

**Agent capability:** treat "the reduction density" as a property of a
processing step rather than of a dataset, and look for a second one before
interpreting an absolute density. Two authoritative statements in one delivery
can both be true and still not be about the same array.

### F003 — A bottom-up error budget counts only the terms that were written down

The uncertainty here was first derived rather than taken: `errg` is 0.001 mGal,
the meter's repeatability after processing, and station elevations good to
0.05 m contribute 0.3086 × 0.05 = 0.015 mGal through the free-air gradient and
dominate it. That reasoning is sound and the number is wrong.

It is a lower bound, not a budget. It counts the terms whose size happens to be
written down and silently sets every other one to zero: horizontal position,
drift and tare, the near-field terrain correction, whatever the reduction did
between the meter and the delivered column. The Utah Geological Survey, who
made the product, state **0.03 mGal** for it.

Halving an uncertainty doubles the weight on every datum, and at 145,062 cells
against 323 observations the inversion answers by going to its bounds. At 0.015
both models saturated both bounds and agreed with the published one at 0.23.

The check that 0.03 is the right number and not the convenient one is external:
Witter's published misfit is 0.0298 mGal RMS, which is chi-squared 0.99
against 0.03 and 3.9 against 0.015. He stopped where a 0.03 uncertainty says to
stop.

**Agent capability:** prefer a stated uncertainty measured on the product to a
sum over the error terms that were easy to find, and recognise that a
bottom-up budget missing terms is not conservative — it is over-confident.

### F004 — A published model is not a published dataset

The comparison needed Witter's stations and his misfit file names them by
position only: three columns of coordinates and one of misfit, no observed
value, no station name. Matching them back to the 518 delivered observations by
coordinate recovers all 323 exactly, to the metre.

The third column then answered a question nobody had asked. His observation
elevations are **NAVD88 + 0.200 m**, with 3 mm of scatter across the survey —
the gravimeter sensor height his report states in one line and which would
otherwise have been left out. Against HAE the offset is 21.45 m with 106 mm of
scatter, and against NGVD29 1.85 m with 342 mm: the datum identifies itself.

**Agent capability:** reconstruct what a published result was computed from
rather than approximating it, and read the reconstruction for the parameters
that were never stated as parameters.

### F005 — An export can contain coordinates that no place has

1,513 of the 101,210 points in the top-of-granite surface carry an easting of
3.35 × 10¹⁵ and upward. UTM zone 12N spans 166,000 to 834,000 m of easting by
construction, so these are an export that went wrong rather than a place.

Interpolating through them drags the reference surface thousands of kilometres
east. They are refused by range rather than cleaned by guesswork, because there
is no way to recover what they were meant to be.

**Agent capability:** bound a coordinate by what its system can represent
before using it, and refuse rather than repair when the intended value is not
recoverable.

### F006 — A nearest-neighbour resample extrapolates past the edge of its source

Made here, in the comparison itself, and caught by the number being absurd.

Witter's model covers the 8.25 × 5.25 km core; OFAG's mesh pads 3 km beyond it.
Resampling his model onto ours by nearest neighbour filled 63,159 padding cells
with whatever sat on his boundary, and forward-modelling the result gave a
12.6 mGal residual. Restricted to the 81,903 cells that have one of his within
120 m, the same comparison gives 2.8 mGal.

A nearest-neighbour query always returns a neighbour. It has no concept of
being outside, and the distance it also returns is the only thing that says so.

**Agent capability:** carry the extent of a source through every resample, and
treat "no source point nearby" as missing rather than as the nearest value.

### F007 — A regularization that states a preference does not act on it

PGI was added to OFAG for this case: the inversion is given rock classes — a
mean, a spread, a share of the volume — and prefers models made of them. Built
as a regularization term alone, correctly, and verified against its own
objective, it changed nothing. The recovered model was no more petrophysical
than the smooth one: 49.6% of cells within a standard deviation of some class,
against the smooth run's 50.8%, and a broad unimodal histogram with no trace of
the four classes it had been given.

Nor did turning it up help. Across `alpha_pgi` from 0.1 to 10,000, and against
both smoothness scalings, the clustered fraction stayed between 46 and 50 per
cent — the beta estimate by eigenvalue rescales the whole regularization, so
only ratios survive, and the ratio that mattered was not this one.

The reason is structural. The smallness measures each cell against whichever
class it currently sits nearest; the smoothness penalises exactly the sharp
contacts that separating classes requires. Left to fight, the smoothness wins.
SimPEG resolves it with two directives — one re-pointing the smallness at each
cell's class mean every iteration, one letting the class-mean field become the
reference the smoothness measures against once the data is fit — and without
them a petrophysical inversion is a smooth inversion that was handed a mixture.

With them, the clustered fraction goes to 60.9% and the modes appear where the
classes are. It also takes four times as many iterations: cut off at the smooth
run's twenty it had done the clustering and not the fitting, stopping at
chi-squared 29.

**Agent capability:** know that some methods are a loop rather than a term, and
that a prior which is never acted on produces a result that looks like the
method and is not it. Measure whether the method did what it exists to do —
here, the share of the model the declared rocks actually account for — rather
than only whether the run succeeded.

### F008 — Reordering a Gaussian mixture after computing its precisions re-pairs them

SimPEG's `WeightedGaussianMixture` has `compute_clusters_precisions`, which
derives the precisions from the covariances in place, and
`order_clusters_GM_weight`, which sorts the classes by weight. Called in that
order, the second permutes means, covariances and weights and leaves the
precisions where they are. Every class is then paired with another class's
spread, and the objective is still perfectly well-formed: it evaluates, it
differentiates, it minimises. It is a different objective.

Cost here: an hour, chasing a prototype whose objective was smallest 0.15
g/cm³ away from every class mean it had been given.

**Agent capability:** treat "these arrays must stay in step" as a property to
check rather than an ordering to remember, and be suspicious of a library
offering two mutating helpers whose correctness depends on the order they are
called in.

### F009 — A Gaussian class is the wrong shape for a gradient

Three of the four rock classes here are rocks. The fourth, shallow basin fill,
is a depth trend: cuttings from well 58-32 give it falling from ~2.4 g/cm³ at
660 m to ~2.0 at surface, and 2.20 is the midpoint of that, not a value
anything has.

Given the full half-range as its standard deviation, the inversion used it as
permission: **5.6% of cells pinned at the 2.07 lower bound**, a class stated
loosely enough to reach the edge of what was allowed.

Held to 0.06 — still the widest of the four — that halves to 2.6%, and does not
go away. The cells that were spread across a wide class now sit *below* every
class instead: 8.6% of the model falls under 2.20, where the smooth inversion
puts 0.45% and the published model puts none. Narrowing the spread moved the
symptom without fixing the cause, because no spread makes a depth trend into a
rock. The tail is reported in the results rather than tuned away.

**Agent capability:** notice when a declared class is a summary of a trend
rather than a property of a material, and know that the spread of a
badly-shaped class is a licence rather than an honest statement of ignorance.
Then notice when tightening it relocated the problem instead of removing it —
the second measurement is the one that says which it was.

### F010 — A derived log carries the assumption it was derived under

The worst entry in this log, because it was not caught by checking the data. It
was written into this document as a result, and found later by asking where a
number had come from.

Well 16A(78)-32 has no bulk density log. It has `DPHI`, in the Thrubit Dipole
processed deliverables, and 2.592 g/cm³ follows from its median of 0.0353. That
was recorded here as the one petrophysical value this case measured for itself,
and as independent confirmation of the ~2.6 g/cm³ Witter reads off a different
log in a different well.

It is neither. `DPHI` is a density *porosity*, and the curve's own description
in the LAS header says which rock it assumed:

> DPHI .ft3/ft3 : Density Porosity using sandstone matrix

Sandstone matrix is 2.65. Recovering a bulk density means putting it back:
2.65 − 0.0353 × (2.65 − 1.0) = 2.592. The number starts at Witter's basement
value and comes back to within a porosity correction of it, so the agreement
was arithmetic rather than evidence — and the assumed rock is a sandstone,
applied to granitoid basement.

How much it matters, measured rather than asserted:

| Matrix assumed | Bulk density, median | 5–95% |
| --- | --- | --- |
| 2.65, sandstone — what the curve used | 2.592 | 2.560–2.618 |
| 2.62, granite | 2.563 | 2.532–2.589 |
| 2.71, limestone | 2.650 | 2.617–2.677 |

The 0.087 g/cm³ between those is larger than the 0.03 standard deviation the
class was given. The spread *within* a column is real — that is porosity
varying down the hole — and the choice *between* columns is not in the data at
all.

The value is kept, because 2.592 remains a reasonable granite density and the
within-column spread is a genuine measurement. The claim is withdrawn.

**Agent capability:** treat a derived curve as a statement about its inputs and
its assumptions, not about the rock, and read the curve description before
reading the curve. The general form is the dangerous one: a quantity that
agrees with the literature because it was computed from the literature looks
exactly like a confirmation, and this is the failure mode a petrophysically
guided inversion is most exposed to, because every class it is given is a
number somebody derived.

### F011 — A depth of investigation can measure the mesh instead of the data

Oldenburg and Li's test is simple and it is the right one to reach for: invert
the same data twice against two different reference models, and

> R = |m_a − m_b| / |reference_a − reference_b|

runs from 0 where the data decides to 1 where each run is only repeating what
it was given. Run here against constant references of −0.130 and +0.100 g/cm³,
it produces a clean-looking depth trend, and the trend is backwards.

| Depth below surface | Cells | R, as this case inverts | R, sensitivity weighting off | Median cell |
| --- | --- | --- | --- | --- |
| 0–100 m | 70,223 | 0.852 | 0.877 | 42 m |
| 100–250 m | 23,207 | 0.791 | 1.062 | 84 m |
| 250–500 m | 26,500 | 0.643 | 1.315 | 84 m |
| 500–1000 m | 12,213 | 0.471 | 1.000 | 169 m |
| 1000–2000 m | 8,337 | 0.099 | 0.817 | 337 m |
| 2000–4000 m | 2,773 | 0.079 | 0.687 | 337 m |

Read naively the third column says the deep model is well determined and the
shallow one is not, which is the opposite of what gravity does. Two things
produce it, and neither is depth.

The first is in the last column. On an octree the cells grow with depth — 42 m
near surface to 337 m at two kilometres, a factor of eight, a volume factor of
five hundred. A per-cell index asks whether *this cell* is determined, and a
337 m cell carries enough mass to move the data while a 42 m cell does not. The
index is reading cell size.

The second is the sensitivity weighting, and that is what the fourth column is
for. That directive exists to stop potential-field structure piling up at the
surface, and it works by loosening the regularization where the sensitivity is
high. Switch it off and the depth trend largely goes: R sits near or above 1
through the whole upper kilometre, peaking at **1.315** — the two runs differ by
*more* than the gap between their references, which is two models actively
disagreeing rather than two models each returning its own prior.

So this case has no depth of investigation to report, and saying "the model is
reliable above X metres" here would be reporting the octree's refinement
schedule as a property of the survey.

What the test does establish is worth more than the number it was run for.
**In the top 100 m, R is 0.85 with the weighting and 0.88 without it: the
shallow model is the reference model.** Across the whole volume the unweighted
median is 0.944, with 8 per cent of cells below the cutoff. Three hundred and
twenty-three observations do not determine 145,062 cells, and this is what that
looks like measured rather than asserted — while every one of the four runs
still fits the data to chi-squared near one. What the data determines here is
aggregate, and the cell-by-cell model is the regularization's answer to a
question the data did not settle.

The index has a second way to lie, found when it was first used to say which
cells had a measured density. Two runs that rest on the same bound agree
exactly, so R is zero and the cell reads as determined: 387 of the 18,833 cells
the weighted test calls resolved, and 634 of 10,972 unweighted, are both runs
pinned at the same bound, most of them at the 3.02 ceiling a little below the
ground. That is the solver saturating twice. Too little volume to move a
share, and enough to report the shallow conductor's resolved density as
2.97 g/cm³, which is how it was found. Cells at a bound in either run are now
excluded wherever the index is read. F100.

**Agent capability:** check that a diagnostic is measuring what its name says
before reporting it. The specific trap is per-cell metrics on a graded mesh,
where cell size varies for reasons that have nothing to do with resolution; the
general one is that a diagnostic run without its control produces a number and
no way to tell what the number is about. The control here cost one extra pair
of inversions and reversed the conclusion.

### F012 — Reporting the prior back as a result

Written into this document, three sections after F010 warned about exactly this,
and caught when a reader asked where the class values had come from.

The claim was that the petrophysical model's density histogram peaks at 2.40
and 2.55–2.60, *"within 0.03 of the two values his model concentrates at,
reached without being told they were his"*. Every part of that except the
arithmetic is wrong. The classes handed to the inversion are 2.42 and 2.592.
A petrophysically guided inversion pulls cells onto the classes it is given —
that is the whole method — so the peaks were placed there by hand and then read
back as agreement.

Worse, the values themselves are his. All four trace to Witter's report: 2.42
and 2.80 are quoted from it directly, 2.20 is the midpoint of a range it
quotes, and 2.592 is derived at a matrix density of 2.65 which is his basement
figure (F010). So the sentence claimed independence twice over, for numbers that
had none either time.

What separates a PGI result from a PGI input is narrow and worth stating
exactly:

| Given | Recovered |
| --- | --- |
| The class values — where the peaks are | The proportions — how big the peaks are |
| The spreads — how wide | Which cells belong to which class, and where they are |
| The number of classes | Whether a class survives at all |

The proportions were left unstated for precisely this reason, and they are the
part of the result that carries information: a uniform 25% prior became
1.8 / 29.6 / 68.4 / 0.3 per cent of the modelled volume. Those numbers were
first written here as 9.2 / 55.3 / 28.1 / 7.5, which is the same model counted
in cells rather than measured in ground (F013).

**Agent capability:** keep a ledger of what was asserted and what was inferred,
and refuse to report anything from the first column as evidence. This is the
failure a petrophysically guided inversion invites structurally, because its
output is shaped like its input — a model made of the rocks it was told about
looks like a discovery of those rocks. It is also the failure mode hardest to
catch by checking the data, because nothing in the data is wrong; the error is
in the sentence written about it. Both times it happened here, what caught it
was a question about provenance rather than a check of a number.

### F013 — A cell is not a unit of ground

F011 found a depth-of-investigation index reading cell size instead of depth.
The same mesh got the class proportions too, and those had already been written
down as the one part of the petrophysical result the data supplied.

Counting cells, the recovered model is 55.3% basin fill and 28.1% basement.
Weighting by volume inside the model box, it is 29.6% fill and **68.4%**
basement — the opposite ordering. Neither number is a mistake in arithmetic;
they measure different things, and only one of them is about the ground.

The octree is why. Inside Witter's box its cells run 42 m to 675 m, so one
coarse cell is worth four thousand fine ones, and the mesh is finest exactly
where the basin fill is. Counting cells therefore counts the refinement
schedule, and the refinement schedule was chosen to resolve the fill.

Two ways to get it wrong, and the second is worse because the first looks
fixed:

| Measured over | Basement share | What it is really saying |
| --- | --- | --- |
| Cells, whole mesh | 28.1% | How the mesh was refined |
| Volume, whole mesh | 84.8% | How big the padding cells are |
| **Volume, model box** | **68.4%** | How much basement the model has |

The padded mesh is forty times the model volume and its cells reach 5,398 m on
a side, so a volume share taken over all of it is dominated by ground nobody
modelled and nobody looked at. Switching from cells to volume is necessary and
not sufficient; the extent has to be right as well.

`ofag.core.cell_model.CellModel` now owns all of this — pairing a model with
the cells it covers, putting it back on the mesh, weighting a share by volume,
and cutting a slice by each cell's own size. It exists because these mistakes
had been made at six separate call sites that each re-derived the same
indexing, and two of them had it wrong.

**Agent capability:** on any mesh that is not uniform, treat a count of cells
as a statement about the mesh until proven otherwise, and state the extent a
share was taken over. The tell is that the quantity has units of "cells": a
result worth reporting is a volume, a mass or a length, and if the number
changes when the mesh is refined without new data, it was never about the
ground.

### F014 — A model of the wrong kind still returns a model and a misfit

The magnetotellurics arrived as 122 sites and a layered inversion will accept
all 122. Over ground that is not layered it returns a conductivity profile, a
chi-squared and a residual plot, and nothing in the run says that the question
it answered is not the question that was asked.

So the sites are screened before they are inverted. The screen is the phase
tensor's skew angle: zero for a layered earth and for a two-dimensional one at
any strike, non-zero only where the structure is genuinely three-dimensional,
and — uniquely among the things a tensor can be asked — untouchable by galvanic
distortion. At the conventional 3 degrees, forty of the 122 sites are refused
and 82 are kept. The cutoff is a judgement and is written down as one, because
a refusal that depends on a number nobody stated is not reproducible.

The first version of this screened on `|Zxy + Zyx| / |Zxy - Zyx|` at a cutoff
of 0.3, which refused twenty sites and kept 102. That index is multiplied by
the distortion, so the screen was a screen on the topsoil; F022 is what it cost
and what replacing it was worth.

Refusing rather than inverting-and-caveating is the point. A one-dimensional
model of a two-dimensional site is not a worse answer to the same question; it
is an answer to a different one, and it is indistinguishable on sight from the
right answer.

**Agent capability:** before running a method, check that the data is of the
kind the method's model class can represent, and refuse rather than annotate.
Every inversion returns something, so "it ran" carries no information about
whether it should have.

### F015 — Averaging two polarisations is not averaging two measurements

A layered earth has one impedance and a tensor has four numbers, so something
has to reduce the second to the first. This case used the average of the two
off-diagonals, `(Zyx - Zxy) / 2`, for two reasons that both sounded like
arithmetic: it settles which of them a code means by "xy", and averaging two
estimates of one quantity halves their scatter.

The second reason is false here. Averaging halves *noise*. Where the two
polarisations are pulled apart by structure rather than noise, their average is
a curve **neither of them is**, and no layered earth need be able to produce
it. The screen in F014 admits sites up to a departure of 0.3, which is to say it
admits exactly the sites where this happens.

Measured on the first six sites of the delivery, each fitted four times with a
36-layer model, a two per cent floor and no regularization, so that what is
compared is the data and not a choice of prior:

| Scalar given to the inversion | Median chi-squared |
| --- | --- |
| **Zxy alone** | **3.2** |
| Determinant, sqrt(Zxx Zyy - Zxy Zyx) | 8.0 |
| Zyx alone | 10.1 |
| (Zyx - Zxy) / 2 | 11.0 |

The average is the worst of the four, and the choice that looked like a
formality was worth a factor of three. Over the whole survey, switching the
import from the average to `xy` takes the median chi-squared from 19.9 to
**11.8** at 102 sites.

`edi.scalar_impedance` now names all four, returns each in the quadrant the
layered simulation answers in, and the import records which one it used —
because two inversions that reduced the tensor differently did not fit the same
data, and the file does not say which was done.

**Agent capability:** treat every reduction from many numbers to one as a
modelling choice with a misfit attached, not as pre-processing. The tell is a
step that is described with the word "just".

### F016 — The screen that admits a site does not predict whether it fits

Having built the screen in F014 and chosen the scalar in F015, the obvious next
move is to tighten the cutoff until the misfit behaves. It does not work, and
the reason is worth more than the fix would have been.

Across the 102 admitted sites, the rank correlation between a site's departure
from layered and its chi-squared is **−0.06**. Not weak — absent, and faintly
the wrong way round. The six most nearly layered sites, under 0.05, fit worse
than any other band; the eight best-fitting sites in the survey all sit between
0.146 and 0.261, and the best of all at 0.191, two thirds of the way to the
cutoff.

| Departure band | Sites | Median chi-squared | Best in band |
| --- | --- | --- | --- |
| 0.00 – 0.05 | 6 | 13.7 | 5.4 |
| 0.05 – 0.10 | 19 | 8.6 | 2.4 |
| 0.10 – 0.15 | 34 | 15.4 | 1.5 |
| 0.15 – 0.20 | 22 | 9.1 | **0.6** |
| 0.20 – 0.30 | 21 | 13.3 | 1.0 |

The index measures the **asymmetry** of the tensor, and the conclusion drawn
here first was that asymmetry is a necessary screen and not a sufficient one.
That was too generous to it. F022 is what the index was actually doing: it is
multiplied by the site's galvanic distortion, so it was reporting the few
metres under the electrodes and the cutoff was screening topsoil. The screen
has moved onto the phase tensor, which distortion cannot reach.

**Agent capability:** before using a data-quality index as a filter, check that
it predicts the thing being filtered for. An index that is theoretically
related to a failure is not the same as one that correlates with it, and a
cutoff tuned on the first is tuning on nothing.

### F017 — A transmitter that takes three microseconds to switch off is not a step

The ground TEM inversion was given a step-off waveform, which is the default
everywhere and is what a transmitter does in the limit. These files state what
this one actually did:

    /RAMP_TIME: 3.0E-6

Three microseconds to fall from 7.6 A to zero, against a first gate at **7.2**
microseconds. Two and a half ramp times, and over a 30 ohm.m halfspace the two
waveforms do not give the same curve anywhere in the recorded window:

| Gate | 0.0072 ms | 0.011 ms | 0.017 ms | 0.033 ms | 0.099 ms | 0.37 ms | 0.72 ms |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Step-off above ramp-off | 30% | 23% | 17% | 10% | 3.6% | 1.0% | 0.5% |

Thirty per cent at the first gate is not a correction; it is a different
experiment. And because it decays with time it is exactly the kind of error an
inversion can absorb: it will build shallow ground that reproduces it, and
report a converged model of a transmitter.

**It was not the only one.** Looking for the ramp turned up two more tags
beside it in every sweep, and neither had ever been applied:

| Tag | Value here | What it is | Was it used |
| --- | --- | --- | --- |
| `/RAMP_TIME` | 3.0 µs | Transmitter turn-off | Read as far as `StackedCurve`, never reached the spec |
| `/TIME_DELAY` | −1.7 µs | System latency on every gate time | Not read |
| `/FIELD_SHIFT_FACTOR` | 1.04 | Amplitude calibration | Not read |

A 1.7 µs delay on a 7.2 µs first gate is a quarter of its own time. Applied,
the best a free fifteen-layer model can do at one sounding improves from 3.4
per cent to 2.5, and its first gate from 32 per cent to 12. Four per cent of
amplitude is smaller and is the same kind of thing: a number the instrument
states about itself, which the pipeline is not entitled to leave out.

**And one gate has to go.** With all three applied, a *free* fifteen-layer fit
— no regularization anywhere to blame for it — still misses the first gate by
60 to 80 per cent at most soundings while fitting the rest to a few per cent. A
datum that no model of its own curve can reach is a datum about the instrument.
It sits 2.4 ramp times after current zero, so gates inside three ramps are
rejected: 266 across the survey, one per sounding of this configuration.

The rule is declared rather than fitted, and the alternative is why. Rejecting
leading gates whose decay is steeper than a layered earth "can" produce sounds
more principled and cuts up to 18 of 26 gates, because a conductor over a
resistor really does decay that steeply. A physical-sounding criterion that has
not been checked against the physics is worse than a stated convention.

**Agent capability:** when a misfit is concentrated at one end of the
measurement axis, suspect the instrument before the earth. Enumerate what a
file declares about its own acquisition and account for every item — used, or
ignored for a stated reason. A value that is read, stored and then not reached
by the thing that needs it is worse than one that was never read, because the
pipeline looks complete. And distinguish a datum the model *fails* to fit from
one it *cannot* fit: refit with the regularization off, and if a point is still
missed by most of its value while its neighbours are fitted, the point is about
the instrument and belongs out of the inversion rather than in its residual.

### F018 — The scatter of the repeats is not the uncertainty of the datum

The TEM uncertainty is measured rather than declared: at each gate, the scatter
of the sweeps that were stacked into it. Across this survey that is **0.17 per
cent** of the value at the median, which is a real measurement of a real thing
and is the wrong number to divide the residual by.

It measures how well the instrument repeats. The residual is divided by how
well the *model* can be expected to describe the ground — a different quantity,
larger by two orders of magnitude here, and one the data cannot supply on its
own. Divided by repeatability, the first inversion reported chi-squared
143,838 and nothing was wrong with it except the denominator.

The magnetotellurics has the same shape with a different mechanism: its
uncertainty is measured from the spectra, which gives 18.1 per cent of the
impedance at the median, and that is a statement about how well the magnetic
channels explain the electric ones — again a property of the measurement, not
of the model class. A layered model then misses by several times it.

Both are honest measurements. Neither is an error bar, and a chi-squared is
only a sentence about the model when the denominator is the model's own
expected error.

**And the obvious repair is a trap.** Wanting a floor that was measured rather
than declared, this case first set each sounding's floor to the residual its
own best halfspace left — 11.7 per cent at the median, derived from the data,
no round numbers anywhere. Chi-squared came back at **0.44**, which looks like
a well-fitted inversion and is not one: a tolerance taken from how badly a
model fits is a tolerance that will be met. Every sounding hit the target after
**one iteration** and stopped, still sitting on the halfspace it had started
from. F012 in a new costume — the prior, reported back as a result, this time
through the denominator instead of the numerator.

The floor is now a declared five per cent, which is worse as a measurement and
better as a statement, because it does not move when the model does.

**Agent capability:** keep repeatability and model error as two named
quantities and never let one be read as the other. A chi-squared far from one
is a question about the denominator as much as the numerator, and the honest
first move is to say which of the two it is — never to widen the declaration
until the number looks right. And a tolerance derived from a model's own misfit
is circular however it is measured: check what a run's stopping criterion was
made of, and treat a target reached in one iteration as a failed run.

### F019 — Reading a child's result after waiting for it to exit

The local executor ran each job in a `multiprocessing.Process`, handed the
result back through a `multiprocessing.Queue`, and waited for the process to
finish before reading it. That is the wrong order and it deadlocks: the queue
is a pipe with a buffer of about 64 kB, and a child whose result does not fit
blocks in its own flush until someone reads, which the parent will not do until
the child exits.

It went unseen because every result had been small: one model per run fits in
the pipe. A batch of sixty-six TEM soundings does not — two thousand artifact
manifests — so it wrote every artifact it owed and then hung, both processes at
zero per cent CPU, the run stuck at RUNNING and `result.json` never written.

The order made it worse than a slow read. `status` asked `process.is_alive()`,
saw RUNNING, and so nothing ever called `collect`, which is where the read was.
The parent was waiting for an exit that was waiting for the read the parent was
not doing.

So it reads before it joins, and asks the queue rather than the process whether
the work is finished — with a large result those are different questions — and
holds a message that `status` drained until `collect` asks for it. The new test
asserts the thing that looks wrong and is the point: `status` reports finished
while the child is still alive.

**Agent capability:** with any bounded channel between processes, read before
waiting, and treat a hang with no output as a buffer question rather than a
slow computation. The size at which it breaks is a property of the operating
system, so a pipeline that works on small data proves nothing about large.

### F020 — A file's idea of its own name is not an identifier

The USF soundings each declare `/SOUNDING_NAME`, and this survey has four names
used twice: the 2017 campaign restarted its numbering, so there are two
Station1, two Station2, two Station4 and two Station5. They are not repeat
occupations — the two Station1 sites are 4.2 km apart. Keyed on the declared
name, four soundings overwrote four others, the count came out at 64 of 68, and
nothing was raised.

The file stem is the identifier instead, which is the thing the acquisition
software actually kept distinct. Two soundings that would still share a name
are refused rather than merged — the magnetotelluric import does the same with
`SECTID` — because a collision is a question about the data, and answering it
by keeping whichever arrived last is a decision nobody made.

**Agent capability:** never key on a field the format allows to repeat without
checking that it does not. The failure is silent, it looks like a smaller
dataset, and a smaller dataset does not look like an error.

### F021 — An unset regularization weight is not a neutral one, twice more

Third occurrence, and the first two are F007. SimPEG scales a smoothness weight
that is left at `None` by the square of the cell size. On a 3D mesh that is a
choice with a defensible reading. On a layered earth a "cell" is a layer
thickness **in metres**, so a 20 m first layer makes the smoothness 400 times
the smallness, and the inversion returns its own starting model flattened.

That is exactly what it did: the recovered TEM median came back at 100 ohm.m,
which was the start, and the tell was that it was *exactly* the start.

| | Effective alpha_s | Effective alpha_x | Ratio |
| --- | --- | --- | --- |
| `alpha_x=None` | 1 | 400 | 400 |
| `alpha_x=1.0` | 1 | 1 | 1 |

**Then it happened a fourth time, through the other door.** Having fixed the
magnetotelluric plugin, the same fix was written into the TEM spec as
`alpha_z: 1.0` — because depth is what the smoothness smooths over, and `z` is
what depth is called. The regularization mesh is one-dimensional and its only
axis is `x`. SimPEG accepts `alpha_z` on it, raises nothing, and ignores it, so
the run looked configured and `alpha_x` stayed unset at nine times the
smallness. Naming the axis wrongly is indistinguishable from not naming it, and
`tests/test_simpeg_tdem1d.py` now asserts both halves of that.

What made it findable was a one-parameter brute force: scanning halfspaces
found one that fit to 11.7 per cent while the 30-layer inversion had reached
45.5. A 30-layer model contains every halfspace as a special case, so it cannot
be worse than the best one — and a thing that cannot happen had happened, which
localises the fault to the optimizer or its objective without any knowledge of
the physics.

Both layered plugins now refuse to pass `None` through, and the case states its
alphas.

**Agent capability:** keep a cheap model of the same data as a lower bound on
the expensive one. Any richer model that does worse than a poorer one it
contains is a solver failure, and that comparison needs no domain knowledge at
all — which makes it the one check that works when everything else is
uncertain. Treat a default of `None` in a numerical library as a value to be
looked up, never as "off". And after setting a parameter, read it back off the
object that will use it: a library that accepts an argument it does not use
turns a typo into a silent default, and four occurrences of this in one case
say the general rule is to verify configuration rather than to write it.

### F022 — A screen can be contaminated by the thing it is screening for

F016 found the magnetotelluric admissibility index uncorrelated with the misfit
and stopped there, concluding that the index was necessary but not sufficient.
That was the wrong conclusion. The index was not weak; it was measuring
something else.

    departure = |Zxy + Zyx| / |Zxy - Zyx|

Galvanic distortion multiplies the tensor by a real matrix C — the near
surface, a few metres of it, redirecting the electric field. `C Z` has a
departure that has nothing to do with the earth below, and a perfectly layered
site under a mild distortion reads **0.12**, a third of the way to the 0.3 at
which this survey was refusing sites. The screen was rejecting sites on their
topsoil.

The phase tensor is the repair and it is exact rather than approximate:

    Z = X + iY,   PHI = X^-1 Y,   so   PHI(C Z) = (C X)^-1 (C Y) = PHI(Z)

with no assumption about the ground. Its skew angle is zero for a layered earth
and for a two-dimensional one at any strike, and non-zero only for genuine
three-dimensionality. Its ellipticity is zero only for a layered earth.

Measured on this survey, and the three numbers are the whole story:

| | Median | What it says |
| --- | --- | --- |
| Phase-tensor skew | 2.14° | Not three-dimensional — 82 of 122 sites under the conventional 3° |
| Phase-tensor ellipticity | **0.238** | Not one-dimensional either |
| Regional strike | 46°, concentration 0.39 | A real common strike (chance is 0.08, and 0.21 at the worst of 200 random draws) |

**The survey is two-dimensional**, coherently, about a strike near N46°E — and
that had been invisible for as long as the diagnostic was one distortion could
move. Rank correlation with the eventual chi-squared: departure **+0.03**, skew
+0.16, ellipticity **+0.21**. Not one of them is strong, and the ordering is
the point: the distortion-free quantities carry the signal the contaminated one
had none of.

Switching the screen from departure to skew is worth a measurable amount
everywhere it can be checked:

| | Old screen | Distortion-free screen |
| --- | --- | --- |
| Sites admitted | 102 | 82 |
| Median chi-squared | 11.8 | **9.6** |
| Correlation with the published 3D model | +0.106 | **+0.302** |
| Median resistivity, ours against theirs | 10.6 / 16.7 ohm.m | **11.9 / 12.1** |
| RMS difference | 1.21 decades | 1.12 decades |

**And it changes what the repair is.** Before the screen was fixed, a free
scale per site — static shift, the standard suspect — looked like the answer: it
took the misfit from 9.0 to 2.0 at eight sites. On the screened data over 24
sites it takes 9.94 to **8.47**, and the recovered shifts are skewed rather
than log-symmetric about one. The scale was never correcting a static shift. It
was absorbing the three-dimensionality of sites the contaminated screen had let
in, and it would have been adopted, published, and reported as a distortion
correction.

**Agent capability:** when a diagnostic fails to predict what it was built to
predict, ask what it is actually measuring before concluding that the effect is
absent or that the threshold is wrong. And prefer a quantity that is provably
invariant to the nuisance over one that is merely expected to be insensitive to
it — the invariance is checkable in three lines of algebra and a test, and the
expectation is not checkable at all.

### F023 — Two simulations in one library, indexed from opposite ends

The largest error in this case, found last, and it invalidates three earlier
diagnoses that each had numbers behind them.

SimPEG's layered magnetotelluric simulation takes its arrays **bottom-first**.
Its own docstring says so — *"Layer thicknesses in meters, starting from the
bottom"* — and the first line of the routine is `thicknesses[::-1]`. The
time-domain `Simulation1DLayered` beside it, which the TEM plugin uses, takes
them top-first, and so does every other layer array in this project. OFAG had
been handing the magnetotelluric simulation a surface-first model.

Both arrays were reversed, independently, so the earth being modelled was the
recovered profile turned over **and** discretized upside down: the layer
thicknesses run 20 m to 5,000 m from the surface down, so the simulated earth
had a 5,000 m top layer and 20 m at the bottom. There was no near surface at
all. The inversion converged, the misfit was reported, no cell hit a bound.

| | Upside down | The right way up |
| --- | --- | --- |
| Median chi-squared, 82 sites | 9.57 | **0.76** |
| Sites within chi-squared 0.5 to 2 | 4 | **61** |
| Correlation with the published 3D inversion | +0.302 | **+0.747** |
| RMS difference from it | 1.12 decades | **0.71** |
| Sites fitting to chi-squared 5 or better | 16 of 67 | **61 of 67** |

**What found it was building something else.** The 2D natural-source simulation
needs validating before anything is built on it, and the honest validation is
against a different code: a layered earth is a 2D earth that does not vary
along the profile, so the 1D and 2D simulations must agree over one. They
disagreed by a factor of 67. Hand-computing the Wait recursion — four lines,
nobody's library — said the 2D was right, and then the docstring said why.

**And this is why the earlier diagnoses were wrong.** The magnetotelluric
misfit was explained three times, and each explanation was supported by a
measurement:

| Diagnosis | Evidence offered | What it really was |
| --- | --- | --- |
| A layered model is the wrong model class | chi-squared 11.8, no solver could beat it | The forward model was of a different earth |
| Static shift: the level is unrecoverable | A free scale took 9.0 to 2.0 | The scale was absorbing a 5,000 m top layer |
| The ground is 2D, so 1D cannot work | Phase-tensor ellipticity 0.238 | True, and not what was stopping the fit |

Every one of those tests — the unregularized refit, the multi-start, the
free-scale fit, the phase-only fit — called the same forward model. **A battery
of diagnostics that all invoke the same simulation cannot detect an error in
that simulation, however many of them agree, and their agreement feels like
confirmation.** Even the phase tensor, which is provably invariant to
distortion, is not invariant to the layer order; it correctly reported a 2D
earth and that finding stands, but it could not see this.

The check that works is a second implementation of the same physics. There were
two in the building the whole time and they were never asked to agree.

`tests/test_simpeg_mt1d.py` now pins the convention against the recursion
written out in the test file, with the halfspace case included and marked as
the one that passes whichever way up the model is.

**Agent capability:** hold the number of *independent* implementations of a
physics, not the number of checks. Before trusting a forward model, make it
agree with a second code or with closed-form arithmetic on a case whose answer
is asymmetric — a halfspace cannot see a reversal, a layer on a halfspace can.
And when a library exposes two solvers for related problems, verify that their
array conventions match rather than assuming a library is internally
consistent; here one documented the difference in a place nobody reads and the
other documented nothing.

### F024 — The reference model is built from the file the delivery says not to use

The gravity folder ships two published density models on the same mesh, both
fitting the same 323 stations to the same misfit — 0.0301 and 0.0299 mGal RMS —
and differing from each other by **0.0283 g/cm³** RMS across 225,063 of their
268,773 cells. Two models, equally good, visibly different: the cleanest
statement of non-uniqueness in this case, and a scale against which to read
OFAG's own 0.084 g/cm³ difference from model 1. That difference is three times
the published models' disagreement with each other, so it is not noise.

Only one of the two ships its top-of-granite surface, and it is the wrong one.
From the delivery's own README:

> Two 3D density models using 2 separate top of granite surface as a
> constraint: 1) Original top of granite density model (taken from the FORGE
> data page) 2) Modified top of granite density model (manually modified to
> test density model and misfit)

and, further down:

> The modified basement model is a **TEST** case in this layer-cake model and
> **should not be taken as a final model/interpretation**.

OFAG compares its result against **model 1** and builds its two-layer reference
model from **model 2's** surface, because model 2's is the only surface in the
folder. Model 1's came "from the FORGE data page" and was never fetched.

How much it costs, measured by deriving each model's basement top from its own
densities and differencing them column by column:

| | |
| --- | --- |
| Columns where both models have basement | 10,077 |
| Identical top-of-granite elevation | 8,300 (82%) |
| RMS difference | 65 m |
| Columns differing by more than 100 m | 495 (5%) |
| Largest difference | 1,080 m |

So the reference is right over four fifths of the area and wrong by more than
100 m over a twentieth of it — and the README says where: *"The main divergences
between the top of granite surface and density model occur outside of the
seismic data area. This is likely due to the fact the original granite surface
is an extrapolation in these areas."* The reference model, the depth-of-
investigation references and F005's 1,513 impossible points all rest on it.

Nothing about this was visible from the data. The file is named
`granite_surface_TEST.csv`, it parses, its coordinates
are in the right zone, and it produces a reference model that looks entirely
reasonable. The warning is a sentence of prose in a README, six paragraphs in.

**Agent capability:** read the delivery's own README and metadata as data, not
as packaging, and extract from them the statements that constrain use —
"should not be taken as final", "test case", "preliminary", "superseded". A
file that is present is not a file that is endorsed. Where a delivery ships
several versions of the same thing, establish which one every downstream step
is using and require them to be the same one, or state why not.

**Resolved, and the premise was wrong.** Model 1's surface was in the folder all
along: the delivery's Geoscience Analyst workspace,
`UtahFORGE_3D_Gravity_Models_May2019.geoh5`, holds both surfaces as triangulated
objects, *Original Top of Granite Surface* and *Modified Top of Granite
Surface*, beside both density models. The reference and the basement are now
built from the original, and the modified one is kept to compare against. F099.

What the substitution had cost is larger than the table above says, because
that table compared tops derived from the density models. Differencing the two
surfaces directly, Witter moved his by more than 50 m over **13.1 km²** of the
88 km² they share: raised by up to 668 m over 2.6 km² in patches east of the
FORGE site, and lowered by up to 859 m over 10.4 km² in the south-west, 4.8 km²
of it inside the model volume. Every gravity inversion here
was started from those changes, so every gravity result carried his reading of
the gravity before it produced its own (F098).

### F025 — A figure drawn from a retyped constant is still a figure

The example notebook redefined the model volume instead of importing it:

    VOLUME = (332_000, 340_250, 4_256_000, 4_261_250)   # the notebook
    VOLUME = (331_900, 340_150, 4_259_925, 4_265_150)   # the case script

3,900 m too far south. Two things were drawn on it and both came out looking
like results.

*The section comparison.* The slice fell outside the published model's northing
range entirely — every cell in it was 1,300 m from the nearest published cell —
so the third panel was filled end to end by nearest-neighbour extrapolation.
F006 again, and this time visible: **the published model lost its topography**,
because the air cells took the density of whatever lay below them. A reader
noticed. No check did.

*The class shares.* 14.5 / 15.7 / 69.2 / 0.6 per cent against the 1.8 / 29.6 /
68.4 / 0.3 the case reports for the same quantity. Two numbers for one thing,
and the wrong pair was on the figure. The first explanation reached for was the
spread-normalised class assignment, which was a real difference and not this
one; the box was.

Both are now imported from `scripts/case1_forge.py`, which is where the result
was computed, along with the elevation range, the reduction density and the
four classes. The nearest-neighbour lookup is also bounded now: a cell further
from the published model than its own width is left blank rather than given a
neighbour's value.

What makes this worth an entry is not the typo. It is that **a figure has no
misfit.** An inversion that is fed the wrong volume reports a bad chi-squared; a
figure fed the wrong volume reports nothing at all, renders cleanly, and is
believed. Every check in `docs/agent_validation_and_debugging.md` is a check on
a *number*, and a figure is where numbers go to stop being checked.

**Agent capability:** derive a figure's parameters from the code that produced
the result, never from a second copy of them — and where a figure shows a
quantity the pipeline also reports, assert that the two agree rather than
trusting that they do. This notebook now has two such ties: the class shares
against `report`, and the magnetotelluric correlation against `compare_mt`,
which caught a second disagreement (+0.803 against +0.747) on the way in.

### F026 — The model volume is two constants, and only one was used

`VOLUME` is the horizontal extent and `ELEVATION_RANGE_M` the vertical one.
The first version of `build_model` selected cells with the first and forgot
the second, so "inside the model volume" reached from the land surface to the
bottom of the mesh's vertical padding, some kilometres below anything the case
claims to model.

It did not crash and it did not look wrong. It reported:

    granitoid basement         89.9%    18,939 cells

Which is a believable number. A basin over granite *should* be mostly granite.
The corrected figure is 69.1 per cent, and the 20 points of difference were a
statement about the padding schedule wearing a geological label.

What caught it was not a test: the **section was drawn** and ran to
−6,000 m elevation, which no panel in this case does. The corrected number
then landed on 69.1 against the **68.4 per cent** the petrophysical inversion
puts in the basement-density class, and this paragraph first called that two
independent methods agreeing to within a point. They are not independent: the
petrophysical inversion starts from the two-layer model split at the seismic
surface, the same surface the 69.1 is cut from (see *What the model does
instead*). The agreement says the inversion did not walk far from where it
started, which is not a second measurement of the basement.

**Agent capability:** when a region is defined by more than one constant, select
on all of them or on none, and prefer a single named predicate over an inline
conjunction that can be written short. More generally, a share-of-volume figure
is exactly the kind of quantity that is always plausible -- it is bounded, it
sums to one, and every wrong version of it looks like a result. Tie it to
something computed another way, and when there is nothing to tie it to, say so
instead of reporting it plain.

### F027 — A guard is not a substitute for a fit

The shallow surface was first built by nearest neighbour, wrapped in a 1,500 m
reach guard: past that distance a cell was left unassigned rather than given a
far-away sounding's value. The guard cited F025, it was the right instinct, and
it reported honestly that the unit could only be drawn over 72 per cent of the
ground.

Leave-one-out against the 46 picks says what it was guarding:

| how the depth is predicted | RMS error on a pick it has not seen |
| --- | --- |
| nearest neighbour | **28.1 m** |
| the picks' own mean | 26.1 m |
| a linear trend in x, y | 25.2 m |
| a smoothed radial fit | **21.8 m** |

**Nearest neighbour was worse than using no spatial information at all.** The
guard did not fix that. It restricted a bad estimator to the places where it
was least bad, and turned the remaining 28 per cent into a caveat that read
like rigour -- a sentence about coverage, in a figure caption, that sounded
like the model being careful rather than the model being wrong.

The 28 per cent was not even a real gap. The picks span 7.8 by 5.2 km of an
8.25 by 5.22 km volume; 99 per cent of the ground is within 3 km of one and
none of it beyond 3.6 km. And there is no short-range structure to lose: a
pick's depth scatters about its own three nearest neighbours by 85 per cent of
its total spread, against 24 per cent for the base elevation. The depth is a
blanket at 73 m with 25 m of noise, and the topography it hangs from is carried
separately -- base elevation correlates +0.973 with the ground.

The smoothing constant is now chosen by that same cross-validation, and the
error is **recomputed on every run and printed**, because a stated
cross-validation score that nothing recomputes is a claim and not a check.

The four numbers above are what the picks gave at the time, with the search
band set to 150 m by eye. Once `resolved_band` measured that band at 130 m the
picks tightened and every score moved with them -- the winner is now 15.1 m
against 19.9 for the mean. Which is the point of recomputing: the table is a
record of a comparison, not a constant, and the model quotes the live one.

**Agent capability:** before adding a guard, score the estimator it is guarding
against the simplest thing that could work -- the mean. A guard bounds the
damage of an estimator; it never tells you the estimator is worse than a
constant, and it makes the resulting hole look like honesty. And when an
interpolated field is reported as covering *x* per cent, that percentage is a
property of the chosen radius, not of the data: report how far the data
actually reaches alongside it.

### F028 — Dip azimuth is the direction of descent

GemPy was tried for this surface, since OFAG ships an adapter for it and an
implicit engine is the standard tool for carrying a contact across a gap. The
first run put the top of the granitoid **2 km too high in the west**: 28 m
below ground where the seismic says 2,144 m.

The cause was a plane fit written for the occasion. Dip azimuth is the compass
direction the surface *descends* toward, and for an upward unit normal
`(nx, ny, nz)` that direction is `(nx, ny)`. The helper used `(-nx, -ny)`,
which is the way the surface rises, so a basement that deepens west was handed
to the engine as one deepening east. With the sign corrected the same model
reproduces the seismic surface to 26 m in the west and 21 m in the centre.

Two things about this are worth keeping. It was **180 degrees**, the error a
sign convention always makes, and the model still ran, still converged and
still returned a plausible three-unit stack -- the same shape as F023. And the
check that caught it was not a test but a *comparison against the surface the
points came from*, which is available for free whenever a fit is made to data
that already exists.

The schema was part of it. `SurfacePoint` was documented as a point on the
**top** of a unit and is in fact a point on its **base** -- the tested
behaviour and `basement_unit_id` both say base -- which is a one-unit offset
waiting for the next reader. Both docstrings are now corrected and say what
the test pins.

The pre-flight was keyed to inversion plugins, and GemPy is not one -- it is
reached through `GeologyService` -- so the one mechanism built for exactly this
failure mode did not cover the one engine whose inputs are pure convention.
That is now fixed rather than noted. `run_checks` keys on a **subject**, which
is a plugin id or an engine id; `ofag/engines/gempy/conventions.py` declares
two checks; and `GeologyService.readiness` runs them, so nothing can
interpolate past them. They take 2.2 seconds, cached per session and engine
version, and both hold.

**A check that cannot fail is decoration, and the first one could not.** The
azimuth check originally gave the engine five surface points spread across the
probe box. Those points pin the plane by themselves, so declaring the azimuth
backwards changed nothing and the check passed on the bug it is named after --
verified by building that exact model and watching it pass. The points now sit
on the **strike line**, where the plane is level and they say nothing about
which way it descends, leaving the orientation as the only thing that can
answer. It now passes on 090 and fails on 270, and a test asserts both.

**Agent capability:** after writing a convention check, build the error it
claims to catch and confirm the check fails. A check is a claim about a
counterfactual, and nothing else in a passing test suite tests it. The failure
here was the standard one for this kind of probe -- the case was not
*asymmetric enough*, because a second constraint in the fixture was quietly
supplying the answer the check meant to demand from the engine.

### F029 — The fixture used the field the way the bug did

Every column of the stitched TEM section claimed to be at the origin. The
batch plugin wrote `receiver_locations_m` from `system.receiver_location`,
which is the receiver's offset *inside its own loop* -- and for a central-loop
sounding, which is what this survey is, that offset is (0, 0, 0) for all 66
stations. The file knew the models and not the places.

Nothing failed. The stitched section is an artifact a reader takes away to draw
a map, and it drew one: every sounding on top of every other.

**The test passed because the fixture avoided the mistake.** It built its two
soundings with `receiver_location=[0, 0, 20]` and `[100, 0, 20]` -- the station
coordinate, put in the offset field -- and then asserted the section came back
with 0 and 100. The assertion was right, the fixture was wrong, and between
them they certified the exact misuse that broke the real case. A plugin fed
honestly, with the zeros a central loop actually has, produced a placeless
section that no test could see.

The spec now carries `station_location`, optional because a batch of repeats at
one station has nothing to put there, and the fixture uses a real central-loop
geometry: origin for the loop, the station in its own field.

Two workarounds had grown around this, one in the case script and one in the
figures notebook, both joining the section back to the case state on the
sounding id. Both are **removed** rather than kept for old runs, and replaced
with an assertion that the coordinates are not all zero. A workaround left in
place after the fix is a fix nothing exercises; the assertion fails loudly on a
section written before the change and says which stage to re-run. The TEM batch
was re-run to prove it: the coordinates now match the survey exactly and
chi-squared is 0.497, unchanged, because only metadata moved.

**Agent capability:** when a test builds the input a plugin will receive, ask
whether a real caller could produce that input. A fixture that populates a
field in a way the domain does not is not testing the plugin, it is agreeing
with it. The tell here was available for free -- `receiver_location` and
`source_location` are set to the same value in the fixture and to the same
value in the case, and only one of those two is the loop's own frame.

## What has been built

Everything here exists because this case needed it, and nothing here is
FORGE-specific.

**Petrophysically guided inversion**

| | Why |
| --- | --- |
| `ofag.engines.simpeg.petrophysics` | Declared rock classes to the Gaussian mixture SimPEG's PGI wants, holding the values that were declared rather than the ones a clustering found, over one property or several |
| `GravityRegularizationKind.PETROPHYSICAL` | A gravity or magnetic inversion told what the rocks are: `PetrophysicalClassSpec` per class, `alpha_pgi`, and `PetrophysicalDirectivesSpec` for the loop that makes it act |
| `JointPetrophysicalSpec` | The joint version: one mixture over density and susceptibility together, so a class is a rock with both |

**Reading what this survey actually shipped**

| | Why |
| --- | --- |
| `ofag.formats.usf` | The Universal Sounding Format, sweep by sweep, with each block's own tags and its instrument-set quality column |
| `ofag.services.tem_import` | 5,912 sweeps stacked into 272 curves: V/Am² to dB/dt with the Faraday sign, an equal-area loop radius, and the file stem as the identifier because `/SOUNDING_NAME` collides (F020) |
| `ofag.formats.edi` | The spectra form of an EDI, which carries no impedance: the tensor solved from seven-channel cross-powers against a remote reference, its uncertainty from the residual power, `scalar_impedance` for the four ways to reduce it to one number (F015), and `phase_tensor` with its invariants — the one description of a site that galvanic distortion cannot alter (F022) |
| `ofag.services.mt_import` | 122 EDIs to 82 sites a layered model may have, projected into the project grid, screened on phase-tensor skew, with the cutoff and the scalar both named on the request |
| `SimPEGMT1DPlugin` | A batch of independent layered inversions over SimPEG's natural-source module, one model per site |

**Other**

| | Why |
| --- | --- |
| `ofag.core.cell_model` | A model paired with the cells it covers: volume shares, per-cell slicing, true cell widths — the three graded-mesh traps of F013 in one place, replacing six call sites that each re-derived the indexing and two of which had it wrong |
| `RunService.delete` | Removing a run and all four of its indices, refused while it is in flight |
| Executor read-before-join | F019: the local executor drained a full pipe and deadlocked on every result larger than 64 kB |

Every petrophysical class requires a `source`. A class taken from a well in the survey and a
class copied from a table in someone else's paper are different kinds of claim,
and a model driven by them cannot be read without knowing which is which.

PGI is available for all three inversions — gravity alone, magnetics alone, and
the joint solve — but the joint one is not the other two run together. Its
classes are declared on the joint spec rather than on either property, because
a susceptibility class with no density is not a rock; declaring them per
property is refused. That is also what makes it a *coupling*: a cell assigned
to a unit is pulled towards that unit's density and its susceptibility at once,
so fitting the gravity moves the magnetic model.

It is therefore an alternative to the cross-gradient, not an addition to it,
and `coupling.weight` must be zero when classes are given. The two tie the
models together through different things — what the rock is, against where its
gradients point — and SimPEG's PGI directives walk an objective tree that a
cross-gradient term beside them does not fit. The cross-gradient is still
computed and reported, as a diagnostic of how structurally alike the two models
turned out without having been told to be.

One limit worth stating: the mixture's covariances are diagonal, so within a
class the two properties are taken to vary independently. Saying otherwise —
that the denser rocks of this unit are also its more magnetic ones — is a
correlation, and a correlation is a measurement.

## The rocks

Four classes, stated as absolute densities and converted to contrasts against
the 2.55 the modelling is reduced at. **All four trace back to Witter's
report**, which is the single most important thing to know about them.

| Class | Density | Spread | Where the number comes from | Ours? |
| --- | --- | --- | --- | --- |
| Shallow basin fill | 2.20 | 0.06 | Midpoint of the 2.0–2.4 range his report quotes from well 58-32 cuttings (F009) | No |
| Deep basin fill | 2.42 | 0.05 | Quoted from his report, off the 58-32 neutron density log, 660–960 m | No |
| Granitic basement | 2.592 | 0.03 | Well 16A(78)-32 DPHI, read back at the 2.65 sandstone matrix the curve assumes — and 2.65 is his basement value (F010) | No |
| Dioritic basement | 2.80 | 0.05 | Midpoint of the 2.7–2.9 his report quotes for dioritic intervals of the 58-32 log | No |

None of the four is a measurement this case made, which is not what was written
here first. The granite figure was claimed as ours — derived from well
16A(78)-32's DPHI rather than quoted, and agreeing with Witter's ~2.6 to 0.008.
It is neither derived nor agreeing: the curve is labelled *"Density Porosity
using sandstone matrix"*, so reading a density back out of it puts 2.65 in, and
2.65 is Witter's basement value. See F010.

Proportions are left unstated, so every class is equally likely before the data
speaks. They could be read off the published model — 63 per cent of it sits at
two values — but that is starting from the answer and then reporting agreement
with it.

## The result

**Import.** 323 of 518 Phase 2C stations, matched to the published inversion by
coordinate. Complete Bouguer anomaly re-reduced from the delivered 2.67 to the
modelling 2.55 (F002), a 0.404 mGal RMS change. Observation elevations NAVD88
plus the 0.2 m sensor height (F004). A −194.97 mGal level removed and recorded,
because an 8 × 5 × 3 km model cannot produce the crustal field of half a
continent. Terrain from 3DEP at 50 m. The top-of-granite surface is the
original seismic one, read out of the delivery's workspace (F024); the modified
one, with its 1,513 impossible points refused (F005), is kept to compare
against.

**Mesh.** 271,181 cells, 145,062 below topography, against the 268,773 in the
model Witter released.

**Inversions.** Both start from the same two-layer reference — basin fill over
basement, split by the original seismic top of granite — so what separates them
is the regularization alone.

| | Smooth | Petrophysical |
| --- | --- | --- |
| chi-squared | 0.754 | 0.890 |
| residual RMS | 0.026 mGal | 0.027 mGal |
| cells at a bound | **0.3%** | 2.6% |
| distinct values | 926 | 761 |
| within one spread of a declared class | 49.5% | **62.7%** |
| correlation with the published model | **+0.773** | +0.613 |
| RMS difference from it | **0.084 g/cm³** | 0.113 g/cm³ |

Witter's own misfit is 0.0298 mGal. Both inversions fit the data slightly
better than the published one, on the same stations with the same uncertainty.

**Where the two disagree with the published model, and why.** His released
model has 67 distinct density values with 63 per cent of its cells at two of
them, and correlates 0.851 with the two-layer model it started from. It is that
starting model, lightly perturbed. OFAG's smooth inversion is a continuous
field: it fits as well, agrees with his at 0.77, and differs by sitting
everywhere between his two values rather than at them. Neither is more correct;
they are answers to differently-posed questions, and the reduction density, the
uncertainty and the stopping point are all now the same, so the regularization
is what is left.

The petrophysical inversion agrees with him less and is more interpretable. Its
histogram has modes at 2.40 and 2.55–2.60, with troughs at 2.50 and 2.65–2.75
where the smooth model puts most of its cells.

Those mode *positions* are not a result. They are 2.42 and 2.592, the class
values the inversion was handed, and concentrating cells there is the
definition of the method rather than a finding of it (F012).

What the data supplied is how much ground went to each class. The prior was
uniform — proportions were deliberately left unstated, so each of the four
classes started at 25% — and the inversion moved a long way from it:

| Class | Declared value | Prior share | Recovered share of the modelled volume |
| --- | --- | --- | --- |
| Shallow basin fill | 2.20 | 25% | 2.3% |
| Deep basin fill | 2.42 | 25% | **27.0%** |
| Granitic basement | 2.592 | 25% | **70.4%** |
| Dioritic basement | 2.80 | 25% | 0.3% |

By volume, inside Witter's 8.25 × 5.25 km box between −1,200 and +2,490 m, and
both of those restrictions are load-bearing. Counting cells instead gives
72.5% basin fill against 27.5% basement — the opposite ordering — because the
octree's cells run from 42 m to 675 m inside the volume and a cell is not a
unit of ground. Taking the volume over the whole padded mesh instead gives the
basement 87.1%, which is a statement about padding: the padding is forty times
the model volume and its cells reach 5,398 m on a side.

So the result is a two-unit basin recovered from a four-unit prior, and more
sharply than the cell counts suggested: **97 per cent of the modelled ground
is in the two classes Witter used**, and the two this case added take 2.6 per
cent between them. The basement is the larger of the two at 70.4%, which the
geometry requires — the volume reaches 1,200 m below sea level and the fill is
only the upper part of it — and which a count of cells hid, because the fill is
where the mesh is finest.

The dioritic class is the clearest case of a prior overruled rather than
confirmed. It was given a quarter of the volume before the data spoke and keeps
0.3%: the gravity does not want dense intrusive rock through this volume,
whatever the logs and the outcrop say is present somewhere in the district.

It also carries a defect the smooth model does not: 9.9% of cells below
2.20 g/cm³, 2.3% of them pinned at the lower bound, against 0.46% and 0.12% in
the smooth model and none at all in the published one. That is the shallow
basin fill class failing as a class (F009), and it is why the petrophysical
model's agreement with the published one is the worse of the two.

### Ground TEM — 66 layered models, fitted

5,912 sweeps at 272 sites, stacked per configuration into 272 curves; 66 of
them on the 40 × 40 m loop with the 1,400 m² coil at 240 Hz, which is the
configuration that resolves the near surface. Each inverted as 31 layers from
3 m to 2,560 m, started on its own best halfspace.

| | Before | After |
| --- | --- | --- |
| Median chi-squared | 143,838 | **0.50** |
| Median residual, per cent of the observed value | 22.2% | **2.7%** |
| Soundings fitting to better than 5% | — | 56 of 66 |
| Soundings fitting to better than 10% | — | 62 of 66 |

Four things stood between those columns and none of them was the ground: the
smoothness weight arriving at 400 and then 9 times the smallness because it was
never set (F021), a step-off waveform in place of the transmitter's own 3 µs
ramp and two more calibrations the files declare (F017), one gate no model of
its own curve can reach (F017), and an uncertainty that was first the
instrument's repeatability and then the model's own misfit (F018).

Chi-squared at 0.50 against a declared five per cent floor means the data is
fitted to about three and a half per cent, so the floor is conservative by
roughly √2 — which is the direction a declared tolerance should err in.

Two limits, both visible in the result. The residual is still **17 per cent at
the earliest surviving gate** and two to four across the rest, which is where
the equal-area circle standing in for a square loop is expected to fail: at
times early enough to resolve the shape of the loop. And the models stop moving
at a median depth of **226 m** (10–90%: 88 to 386 m) — below that every profile
returns its starting halfspace, because a decay that ends at 0.9 ms has not
been anywhere deeper. The deeper layers of the stitched section are the prior
and are not a result (F012).

| Depth | Median recovered resistivity | 10–90% |
| --- | --- | --- |
| 0 – 50 m | 152 ohm.m | 10 – 7,059 |
| 50 – 150 m | 57 ohm.m | 10 – 797 |
| 150 – 400 m | 63 ohm.m | 36 – 74 |
| below 400 m | 63 ohm.m | the start, untouched |

### Magnetotellurics — four decisions, and the last one was worth all the others

122 sites read from EDIs in the spectra form, which carry no impedance: seven
channels of cross-power per frequency, from which the tensor is solved against
the magnetometer 83 km away. 82 sites pass the phase-tensor skew screen (F014,
F022) and are inverted, one 36-layer model each, against an uncertainty measured
from the spectra at 18.4 per cent of the impedance.

Four decisions moved the misfit. Each is a measurement rather than a
preference, and the fourth is a bug rather than a decision:

| | Sites | Median chi-squared |
| --- | --- | --- |
| Tensor averaged over its off-diagonals, screened on departure | 102 | 19.9 |
| Reduced to its xy polarisation (F015) | 102 | 11.8 |
| Screened on phase-tensor skew instead (F022) | 82 | 9.6 |
| Layers handed to the simulation the way it reads them (F023) | 82 | **0.76** |

61 of the 82 sites land between chi-squared 0.5 and 2, and 76 of 82 below 2.
Against the published Phase 3 three-dimensional inversion of the same sites,
sampled at the same points down to 5 km:

| | Upside down | The right way up |
| --- | --- | --- |
| Sites with published cells within 250 m | 67 | 67 |
| Correlation in log resistivity | +0.302 | **+0.747** |
| Median, ours against theirs | 11.9 / 12.1 ohm.m | 10.0 / 12.1 |
| RMS difference | 1.12 decades | **0.71** |
| Sites fitting to chi-squared 5 or better | 16 of 67 | **61 of 67** |
| Correlation over those alone | +0.102 | **+0.735** |

A stack of independent layered models, each fitted to its own site with no
knowledge of its neighbours, agrees at **+0.75** in log resistivity with a
three-dimensional inversion of the same data by the contractor who recorded it.
That is the strongest independent validation anything in this case has.

Two things survive from before the bug was found and neither is weakened by it.
The tensor is still better reduced to one polarisation than averaged (F015), and
the sites are still screened on a quantity distortion cannot move (F022) — both
were measured under the broken forward model and both improved the misfit
there, which is evidence about the data rather than about the simulation. What
does not survive is the interpretation: three separate explanations of why the
magnetotellurics "could not fit" (F023).

The phase tensor's reading also stands and is now a statement about the ground
rather than an excuse: median skew 2.1°, ellipticity **0.238**, a coherent
regional strike near N46°E. These are two-dimensional sites. A layered model of
the xy mode fits them and agrees with the 3D model to 0.71 decades, which is
what a good 1D approximation of a 2D earth looks like — not a substitute for a
2D inversion, and no longer a reason to withhold the result.

## What joint interpretation is possible here

The case has four methods over one field. The question is not whether they can
be inverted together -- they are not -- but whether they can be *read* together
into one geological model. That was treated as three testable conditions, each
of which a method has to meet before it is allowed to define anything: it has
to reach the target depth, there has to be a physical contrast at that depth,
and where two methods overlap they have to agree.

Two of the three tests came back negative, and the model is what survived.

### The magnetotellurics cannot see the basement

The target is the top of the granitoid basement. Across the model volume it
sits 935 m below ground at the median (p25 162 m, p75 1,625 m, p95 2,382 m).
Taking the 30 magnetotelluric sites within 2 km of the volume, and picking each
one's steepest resistivity step:

| | median |
| --- | --- |
| strongest magnetotelluric step | 376 m |
| seismic basement at those sites | 2,165 m |
| correlation, in log depth | +0.352 |
| median absolute difference | 1,729 m |

The obvious objection is that the basement step is real but weaker than a
shallow one, so the gradient was then read *at* the seismic basement depth
directly. There is nothing there:

    d(log rho)/d(log z) at the basement        -0.049
    the same at other depths, 100-4000 m       +0.146
    resistivity above the basement            12.1 ohm.m
    resistivity below the basement            13.2 ohm.m
    contrast                                       x1.00

Split by depth, only the two shallowest sites show anything (x1.35 where the
basement is above 1,000 m; x1.02 and x0.97 below). This is physically sensible
rather than a failure: at 2 km the basin fill is compacted and saturated with
saline water, and the granitoid is not conductive either. **The density
contrast across that surface is real -- 0.23 g/cm³ -- and the electrical one
does not exist.** Nothing electrical is allowed to define the basement here.

### The two electrical methods share no depth band

They were then asked to define the shallow structure together, and that failed
for a different reason. Each method's resolved band was measured rather than
assumed.

*The TEM.* Every layer of every sounding was compared against the starting
model it was given. The median departure runs 0.54 decades at 72 m, 0.32 at 88,
0.21 at 107, 0.11 at 130, 0.08 at 157, 0.02 at 226 -- and below 460 m not one
of the 66 soundings has moved at all. Information to about **130 m** -- which
is now measured by `resolved_band` on every run rather than read off this
list -- and a picture of the prior below it.

*The magnetotellurics.* Every EDI in the survey stops at the same top
frequency, 230.5 Hz. The skin depth there is 105 m in 10 ohm.m ground and 222 m
in 45, which brackets the near surface here. Nothing resolved above about
**105 m**.

So the bands touch and do not overlap. Everything else follows from that:

- the steepest step is at **80 m** in the TEM and **339 m** in the
  magnetotellurics, and across the 20 pairs within 1,500 m the two picks
  correlate **−0.62**;
- the disagreement grows with depth, from −0.47 decades at 60 m to −1.32 at
  180, which is one method running out of data while the other acquires some;
- it is **not static shift**, which was the first thing suspected. A per-site
  constant does not absorb it: the within-site scatter with depth is 0.41
  decades against 0.19 between sites, and static shift predicts the reverse.

The last point matters beyond this case. Using TEM to correct magnetotelluric
static shift is standard practice, and it requires a band where both methods
resolve. Here there is none, so the correction could have been applied, would
have produced numbers, and would have been meaningless.

### What the model does instead

Each unit is assigned by the one method competent at its depth, and which
method that was is stored per cell. No two methods constrain the same
interface, nothing is averaged, and neither electrical method checks the other.
Rules are applied hardest-evidence-first, so the seismic basement is cut before
anything above it can relabel it.

| Unit | Share by volume | Decided by |
| --- | --- | --- |
| granitoid basement | 71.3% | seismic top of granite, tested by gravity |
| shallow conductor, base at 65 m (p25 65, p75 80) | 2.0% | TEM |
| intermediate conductor, below 105 m, under 5 ohm.m | 4.4% | magnetotellurics |
| basin fill | 22.3% | above the seismic surface, no conductor |

The two gravity labels this table used to carry -- "gravity + 3D seismic + well
58-32" on the basement and "gravity" on the fill -- claimed more than the rules
did. No rule consulted a density: the basement is below a seismic surface and
the fill is what nothing else claimed. Each unit is now named for what decides
it, and what the gravity does decide is the next section.

The basement share has no independent partner. The petrophysical inversion puts
**70.4 per cent** of the same volume in the basement-density class, and this
section used to call it one, as an inversion that knew nothing of the seismic
surface. It knew it from the first iteration: both gravity inversions are
started from, and referenced to, the two-layer model split at that surface
(`_reference_model` in `scripts/case1_forge.py`), and gravity says little about
depth on its own. Two answers that start from the same surface are one answer,
and a figure within a point of its own starting model is the prior coming back.
The one dataset that never entered is the 2D seismic interpretation, held back
for exactly this (*What is not done*).

### What the density model decides

Not the basement's depth. Gravity measures how much mass a column holds and
says little about where in the column it sits (Li and Oldenburg, 1998), so a
density model cut at a threshold would return whatever depth its reference
gave it. What the FORGE work did with its gravity is what is done here: Witter
fixed the seismic surface in order "to show where the gravity data may or may
not support this assumption", Hardwick et al. (2019, UGS MP-169-F) mapped the
basement from gravity where there was no seismic, and Miller et al. (2019)
integrated their seismic picks with that gravity modelling. The method is
Witter et al. (2016) at Bradys: invert with the geological model and read where
the density has to leave it.

The density model enters the geological model three ways, each stored beside
the units in `geological_model.npz`.

**The density of every cell** (`density_g_cc`), and of each unit measured
rather than assumed where the data resolve it:

| Unit | Median, all cells | Median where resolved (share of its volume) |
| --- | --- | --- |
| granitoid basement | 2.620 | **2.602** (62%) |
| shallow conductor | 2.414 | too little resolved |
| intermediate conductor | 2.402 | none resolved |
| basin fill | 2.400 | **2.375** (18%) |

Resolved means a depth-of-investigation index below 0.2 in the weighted test,
with cells at a bound in both of its runs excluded (F100). Both resolved values
sit about 0.05 below the 2.65 and 2.42 Witter took from the 58-32 log, and
their difference, **0.227 g/cm³**, is the 0.23 contrast the two-layer model
rests on. The shallow conductor's resolved cells are 0.3 per cent of it, and a
median of those is not a unit's density.

**A verdict on the seismic surface, column by column** (`gravity_shift_m`,
`gravity_verdict`). Down each 50 m column of the model volume, the mass the
inversion added to the seismic two-layer model within 300 m of the surface is
integrated and divided by the 0.23 contrast: the distance the surface would
have to move to carry that mass alone. Positive is a column that wants more
mass than the seismic model holds, which Witter read as a shallower basement or
dioritic rock; negative wants less, a deeper basement or lighter fill. The two
readings carry the same mass and gravity cannot choose between them, so the
verdict names both.

Two things are taken out first. Mass further than the band from the surface is
not the surface's to explain, and down a whole column it is dominated by the
broad deep structure the regional level removal leaves free. And every column
shares a shift of −90 m, which is the two units coming back 0.05 g/cm³ lighter
than the reference: a statement about the unit densities, reported above, and
not about where the surface is.

| Verdict | Columns |
| --- | --- |
| supports the seismic surface, shift within 100 m | **59.7%** |
| more mass: shallower basement or dense rock | 18.7% |
| less mass: deeper basement or lighter fill | 17.0% |
| not tested, no station within 500 m | 4.5% |

The 100 m is twice the ±50 m Miller et al. give for their pick at well 58-32,
the best-imaged place in the survey; away from it the seismic is less certain,
so a flagged column is a question for the seismic and not a refutation of it.
The 500 m is against the 339 m median station spacing, and is what excludes the
south-east corner Witter called an artefact of having one station.

Both numbers move the shares, and the band moves them most:

| | Supported | More mass | Less mass |
| --- | --- | --- | --- |
| threshold 50 m | 31.8% | 33.2% | 30.5% |
| threshold 150 m | 74.8% | 12.4% | 8.3% |
| band 150 m | 80.8% | 8.7% | 6.1% |
| band 500 m | 41.6% | 30.7% | 23.2% |
| band 1,000 m | 26.2% | 35.6% | 33.6% |

So the supported share is not a result to quote without its band. What does
not move with either is below.

Two checks keep this from being the seismic surface read back out of its own
reference. The two constant-reference inversions of the depth-of-investigation
test never saw a surface; against each, the verdict map correlates at **+0.84**
and +0.76 and **94 and 95 per cent** of flagged columns are flagged the same
way, and at every band from 150 to 1,000 m the agreement stays between 84 and
100 per cent. And there is an answer a person reached from the same data: where
Witter moved the surface for model 2 (F024).

| Where Witter raised the surface | Area | Our shift there | p, same zone moved at random |
| --- | --- | --- | --- |
| E 336,990 N 4,264,256 | 0.31 km² | **+556 m** | **0.007** |
| E 337,010 N 4,262,818 | 0.53 km² | **+292 m** | **0.036** |
| E 336,565 N 4,260,185 | 0.36 km² | **+237 m** | **0.046** |
| E 337,896 N 4,262,515 | 0.04 km² | +177 m | 0.092 |

He raised it in four places, and all four want more mass here, three of them
beyond chance; at bands of 150, 500 and 1,000 m the three stay between p = 0.006
and 0.09. Where he lowered it -- 6.6 km² of the south-west inside the model
volume, by a median 402 m -- the median shift here is **−120 m**: some less
mass, and a third of the deepening he tried. That is his own conclusion --
lowering the surface did not remove the low-density zone, and between lighter
sediments and a deeper basement, *"we believe that the former is the more
likely explanation"* -- reached here without being told.

The first version of this map counted a coarse octree cell in a column of its
own, keyed by its centre, so the deep ground was missing from the columns above
it and the map came out striped; drawn, it was obviously wrong, and its shares
had looked reasonable. Each cell's mass is now spread over every 50 m column it
covers. F101.

**Dense basement** (`dense_basement`). 1,108 basement cells, 0.83 km³, reach
2.75 g/cm³ -- the low edge of the dioritic class -- under columns that want more
mass. They are the dioritic bodies Witter proposed east of the site, flagged
rather than made a unit, because the same columns are equally well explained by
a shallower basement.

What the density model does not do is move the surface. Moving it to fit the
gravity is a geometry inversion (Fullagar et al., 2008) or a geological model
that treats the seismic picks as uncertain (Wellmann et al., 2017), and either
would need the seismic interpretation's own extent, which is not published.
The 3D survey's is -- 170 inlines by 213 crosslines at 25 m, crossline 105 and
inline 93 through well 58-32, which places it at E 332,851-338,151,
N 4,260,738-4,264,963 from the well's surveyed coordinates -- but Witter's
raised zones lie inside it and he describes them as having *"poor or no
seismic interpretation"*. The picked area is smaller than the survey, and a
verdict switched at a boundary nobody can place would be the less honest map.

`uv run python scripts/case1_forge.py build_model`, and panel f of
`examples/Fig4.ipynb`. The machinery is
`ofag.services.interpretation_service`, documented in `docs/interpretation.md`;
what stays in the case script is the case -- which runs, which bands, which
four units, and the measurement behind each.

Two of the numbers above are the service's and not a choice. The TEM's resolved
depth is **130 m**, measured against the starting model each sounding was
given rather than the 150 m first assumed by eye, and the pick band follows it.
The shallow surface is then fitted through **46 picks of 48 soundings in range**
by the estimator that predicts a held-out pick best -- a light smoothing, at
**15.1 m** against 19.4 m for the picks' own spread, 17.7 for nearest neighbour
and 19.9 for the mean. No modelled cell is more than 3,580 m from a pick, which
is the number that earns drawing the surface everywhere (F027).

Three things are recorded rather than resolved.

The **intermediate conductor rule declines to judge 11.0 per cent of the
volume**, which lies further from any magnetotelluric site than its 2 km reach.
Those cells fall through to basin fill, and until the service reported it the
model was saying "not the conductor" over ground nothing had measured. It is
the same error as the shallow surface's old guard wearing the opposite face:
there a distance rule hid a bad estimator, here it hid a silence.

The TEM conductor reaches below the seismic basement in 4,109 cells (0.29 per
cent by volume) -- either the surface is wrong there or the conductor is
weathered granitoid, and the model is not entitled to choose. And the gravity
leaves 37 per cent of the columns it tested asking for a different surface or
different rock at a 300 m band, stored per cell as its verdict rather than
acted on.

### Why not an implicit engine

OFAG ships a GemPy adapter, and carrying a contact across a gap is what an
implicit engine is for, so it was tried. It reproduces the **granitoid top**
well -- 2,170 m against the seismic's 2,144 in the west, 767 against 788 in the
centre -- which is a real cross-engine check on the adapter, and it adds
nothing, because that surface already arrives as 101,210 seismic points.

For the **shallow conductor** it is the wrong tool, and measurably so. GemPy
interpolates a surface in absolute elevation, which is correct for a geological
contact and wrong for a blanket: where the ground rises 200 m into the eastern
granite outcrop the interpolated base does not rise with it, and the cover came
out 239 m thick against a measured median of 73. The quantity with spatial
meaning here is the *depth*, and the correct operation is a two-dimensional fit
to 46 numbers.

The adapter is right and available; this surface is not the one to use it on.
A case with logged contacts at genuinely varying elevation would be.

### Why this is the interesting part

Witter's released model has two layers, and he tried to add more. Fixing
boundaries at 200, 400 and 600 m and letting density float produced a
near-surface sediment layer at 2.75 g/cm³, which he called *"undoubtedly
incorrect"*, and drew the general lesson that geologically reasonable guesses
used as fixed constraints give results that are geologically unsatisfying.

The shallow unit here is that layer, and its depth is not a guess: 46 soundings
put its base at 65 to 93 m. That is what joint interpretation bought in this
area -- one unit that gravity alone cannot see and that guessing could not
supply. It did not buy a jointly-constrained basement, and the measurements
above are the reason why.

## What this case does not support

**The models are not unique, and fitting better than the published one is not
being righter than it.** Three hundred and twenty-three observations do not
determine 145,062 cells. What is defensible is that both fit to a measured
uncertainty, that the smooth one agrees with an independent published model at
0.77, and that the petrophysical one concentrates where two wells say the rocks
are. What is not defensible is reading a cell. F011 measures how far from
defensible: with the reference-model test run without its sensitivity
weighting, the median R over the whole volume is 0.944 and 8 per cent of cells
fall below the cutoff. Almost nothing here is determined cell by cell. The
aggregate is.

**There is no depth of investigation, and not because it was skipped.** It was
run, and the index it produces is dominated by the octree's cell-size gradient
and by the sensitivity-weighting directive rather than by depth (F011). Quoting
a depth from it would be reporting the mesh refinement schedule as a property
of the survey. A resolution measure that is not confounded by cell volume —
per unit volume rather than per cell — is the thing to build next, and this
case does not have one.

**Not one of the four classes is a density this case measured.** Three are read
out of Witter's report, which reads them off a log of well 58-32 that has not
been obtained here; they are quoted, and quoted values can be misquoted. The
fourth looked like an exception and was not (F010). So the petrophysical
inversion is guided by the same petrophysics the model it is compared against
was guided by, and the two agreeing about a rock is not evidence about that
rock. Getting the 58-32 density log, and a real bulk density for the granite,
is the single change that would most improve this case.

**The 20 m upward continuation is not reproduced.** Witter filtered the data
before inverting it, to suppress features from the top tens of metres. OFAG has
no upward continuation, so both inversions here are fitting short wavelengths
his did not — which is consistent with both of them reaching a slightly lower
misfit than he did, and is a difference in the data rather than in the method.

**The petrophysical model's clustering is partial, and one of its classes
misbehaves.** 62.7% of cells within one spread of a class means 37.3% that are
not, and 9.9% of the model sits below every class it was given. A model really
made of four rocks would be much closer to a mixture than this. The honest
reading is that the data supports the classes weakly — and that on the measure
that does not depend on the classes, agreement with an independent published
model, the plain smooth inversion is the better of the two here.

**No borehole validates a depth here either.** The wells constrain what the
rocks are, which is what they are used for. They do not independently check
where the model puts the contact, because the contact is the published surface
the reference model was built from.

**The TEM models are shallow, and the deep half of each one is the prior.**
They fit, and they fit only what a decay ending at 0.9 ms can see: below a
median 226 m every profile is the halfspace it started from. A stitched section
drawn to 2,560 m would show structure to the bottom of the frame and the
structure below 400 m would be the starting model drawn 66 times. The section
is cut at the depth the data reaches, and the number is reported per sounding
rather than as one figure for the survey, because it runs from 88 to 386 m.

**The magnetotelluric models are one mode of a two-dimensional earth, and the
three times this case said they were unusable are kept here on purpose.**

*"A layered model is the wrong model class"*, then *"the level is static shift
and cannot be recovered"*, then *"the ground is two-dimensional, so nothing 1D
will work"*. Three diagnoses, each with a measurement behind it, each written
into this document, and all three of them consequences of the layer order
(F023). What is true is the third one as a statement about the ground —
ellipticity 0.238, strike near N46°E — and false as a statement about what can
be fitted: a layered inversion of the xy mode reaches chi-squared 0.76 and
agrees with the published 3D model to 0.71 decades.

So the caveat that remains is the ordinary one. These are 1D models of a 2D
earth: each is a statement about the ground beneath one site, none of them
constrains its neighbours, and stitching 82 of them into a section makes a
picture that looks like a 2D result and is not one. The agreement with the
published 3D inversion is what licenses reading them at all, and it is an
agreement at +0.75, not at 1.

Two limits are now measured rather than suspected. The static shift the free
scale recovers is worth 15 per cent of the misfit, and it cannot be removed
from this survey anyway: tying the level to a transient sounding needs the two
surveys to overlap, and the median MT site is **3,698 m** from the nearest TEM
sounding with **not one** of the 82 within 250 m. And a stitched section is
still a picture; the 2D inversion that would make it a section is being built.

## Status

`python scripts/case1_forge.py report` answers this, from the stored runs
rather than from this file:

| Deliverable | State | chi-squared |
| --- | --- | --- |
| Gravity, smooth | done | 0.754 |
| Gravity, petrophysical | done | 0.890 |
| Ground TEM, 66 layered soundings | done | 0.497 |
| Magnetotellurics, 82 layered sites | done | 0.757 |
| Magnetotellurics, 2D profile | **built, not used** | 0.32, and −0.03 against the published 3D model at the same sites |

**The magnetotellurics this case delivers is the layered batch.** The 2D
profile inversion works — the plugin is verified against the layered solution,
the mesh is derived from the band, and its TE profile fits at 0.32 — but it
agrees with nothing. A model that fits its own data and disagrees with an
independent one is not a result, so it is named in the report as not used
rather than quietly left out.

The cause was recorded as static shift for a while, and that was wrong on its
face: **TE is the charge-insensitive mode**, which is exactly why it was chosen
over TM. Static shift is TM's problem, and it had already been used to explain
why TM would not invert here; reusing it for TE made it a label rather than a
diagnosis.

Measured at the same twelve sites, eight depths each:

| | correlation in log resistivity |
| --- | --- |
| 1D batch against the published 3D | **+0.730** |
| 2D TE against the published 3D | −0.029 |
| 2D TE against the 1D batch | +0.103 |

with spreads of 0.44 decades for the 2D, 0.83 for the 1D and 1.20 for the
published model. **The data carries the structure and the 2D does not recover
it** — it returns a third of the published variation. That flatness is not the
regularizer's doing: the run drove beta to 1.6e-3, effectively off, and the
model stayed smooth. It is TE behaving as TE does. TE senses conductance and is
close to blind to a resistive basement beneath conductive fill, which is this
target exactly.

So the profile is caught between its own two modes: TM carries the structure
and static shift ruins it, TE is clean and cannot see the structure. Per-site
shift parameters would let TM be used and are still the bounded piece of work
worth doing; they would not improve the TE result, which is what the earlier
note implied.


Done: import, the reproduced inversion, the petrophysical inversion, the
cell-by-cell comparison against the published model, and the reference-model
resolution test with its control — all through OFAG's own services, with the
case data outside the repository.

Also done, since: the ground TEM — 5,912 sweeps read, stacked and inverted as
66 layered models — and the magnetotellurics, 122 EDIs in the spectra form
read, 82 sites inverted to a median chi-squared of 0.76 and agreeing with the
published 3D inversion of the same data at +0.75 in log resistivity.

Not done: the joint inversion those would make possible. F011 is the argument
for it rather than a note beside it: gravity alone leaves the cell-by-cell
model undetermined, so independent physics on the same mesh is not an
enrichment of this case, it is what the case is missing. What now stands in the
way is that the two electromagnetic methods are layered models at points and
the gravity is a 3D model on an octree, and nothing here yet couples the two.

Also not done, and now the only untouched independent check left: the 2D
seismic interpretation, which the data README says both published density
models match. It is held back deliberately — it did not enter either inversion
and Witter's granite surface did, so seismic is the one dataset here that can
still falsify a model rather than confirm the prior it was built from.
