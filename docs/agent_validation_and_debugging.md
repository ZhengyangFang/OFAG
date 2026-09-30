# What the agent has to be able to do: validate data, debug an inversion, and read one

Three procedures, distilled from the problems logged across
`docs/development/stillwater.md` and
`docs/development/case1_forge_history.md`. They are written as things
to execute rather than things to know, because that is what the agent layer has
to turn them into.

The third is the newest and the least obvious. A and B guard a *run*, and a bad
run announces itself with a misfit. C guards the step after — reading finished
runs into a geological model — where there is no misfit at all, and every
mistake produces something that renders cleanly and sums to 100 per cent.

The reason for writing them down separately from the problem log: the log is
organised by what went wrong, and an agent needs them organised by when to act.
Each step below cites the entries it came from, so a claim can be traced back to
the case that produced it.

---

## A. Before an inversion: fifteen checks on the data and the setup

None of these is about the numerics. Every one of them, left out, produced a run
that converged, reported a healthy misfit, hit no bounds, and was wrong.

### A1. Make the unit chain falsifiable

Convert to SI at the boundary, once, and then check the result against a range
the ground has to be in. An EDI states no units at all; dropping µ₀ from the
impedance leaves the phase at a perfect 45° and puts the apparent resistivity at
5 × 10¹² Ω·m. The phase check passes, the resistivity check cannot.

> **Rule.** For every imported quantity, name a derived quantity with a known
> geological range, and assert it. A conversion that can be applied twice will
> be — return SI from the reader and never from the caller.

The same assertion catches a **sentinel null**, which is the other way a
numeric column lies. A published AEM inversion carries −99999 for every layer
below its depth of investigation — documented, and 22 per cent of the file. The
first median computed over it came back at −99999 Ω·m, which is obvious. The
dangerous version is a mean over a column that is nine per cent sentinel: it
comes back plausible, low, and wrong, and nothing in the number says which.

> **Rule.** Before any statistic, ask a numeric column for its extremes and
> check them against the quantity's own domain. A resistivity cannot be
> negative and a depth cannot be −99999; a sentinel that violates the domain is
> detectable without knowing the file, and one that does not is why the range
> has to be geological rather than merely finite.

*F004 (elevation datum), the µ₀ chain in `ofag.formats.edi`.*

### A2. Validate conventions against something outside the engine

**This one is now enforced rather than advised.** `ofag.core.conventions` runs a
plugin's convention checks inside `RunService.validate`, before anything is
dispatched, and a failure refuses the run. `ofag.engines.simpeg.conventions`
holds the shared ones, because a convention belongs to the engine and not to
whichever plugin uses it. The whole pre-flight across eleven plugins is 2.2
seconds cold and free thereafter, cached against the engine's version so it is
recomputed when SimPEG is upgraded -- the event that would silently move a
convention.

A plugin may return `UNVERIFIED`, and that is reported on every validation
rather than passing in silence. Blocking would mean no ERT or seismic run could
start, and a rule that stops the work gets deleted.

Signs, axis handedness, and array order are invisible to any test that builds
its data with the same simulation it then inverts. Both errors cancel exactly.

| Convention | How it was caught | Entry |
| --- | --- | --- |
| `gz` is the negative of a Bouguer anomaly | Forward-modelling a published model: correlation −0.966 | F001 |
| A recorded TEM voltage is the negative of dB/dt | Every accepted gate positive, every forward model negative | `tem_import` |
| MT layers are indexed bottom-first, TEM top-first | A second implementation disagreed by 67× | **F023** |

> **Rule.** Check every convention against closed-form arithmetic, a published
> result, or a second implementation — on a case whose answer is **asymmetric**.
> A halfspace cannot detect a reversed model; a layer on a halfspace can.

### A3. Account for every acquisition parameter the file declares

Enumerate them. For each: used, or ignored for a stated reason. A parameter that
is read, stored, and then not reached by the thing that needs it is worse than
one never read, because the pipeline looks complete.

The FORGE TEM files declared `/RAMP_TIME` (read as far as the curve, never
reached the run spec), `/TIME_DELAY` and `/FIELD_SHIFT_FACTOR` (never read).
Together they were worth taking the median residual from 22% to 2.7%.

*F017.*

### A4. Separate repeatability from model error

They are different quantities and only one belongs in a χ². Fifty repeats of a
TEM gate give 0.17% — a real measurement of how well the instrument reproduces
itself, and two orders of magnitude tighter than what a layered model of that
ground can be expected to achieve. Divided by it, the first inversion reported
χ² = 143,838 and nothing was wrong except the denominator.

> **Rule.** Carry `repeatability` and `model_error` as two named fields. A χ²
> far from one is a question about the denominator as much as the numerator, and
> the first move is to say which.

*F003, F018.*

### A5. Never derive a tolerance from a model's own misfit

The tempting repair for A4 is a floor "measured from the data" rather than
declared. Flooring each TEM sounding at the residual its own best halfspace left
is derived, has no round numbers, and is circular: χ² came back at 0.44 with
every sounding stopping after **one iteration** on the halfspace it started
from.

> **Rule.** A target reached in one iteration is a failed run, not a converged
> one. Check what the stopping criterion was made of.

*F012, F018.*

### A6. Check that a data-quality index predicts what it filters for

An index that is theoretically related to a failure is not the same as one that
correlates with it. The MT admissibility index `|Zxy+Zyx| / |Zxy−Zyx|` is
multiplied by galvanic distortion, so it described the few metres under the
electrodes; its rank correlation with the eventual misfit was **+0.03**.

> **Rule.** Before using an index as a gate, measure its correlation with the
> outcome. Prefer a quantity that is *provably invariant* to the nuisance over
> one merely expected to be insensitive to it — the invariance is three lines of
> algebra and a test, the expectation is not checkable at all.

*F016, F022.*

### A7. Check the discretisation against the data's own bandwidth

Layer thicknesses, cell sizes and domain extent are part of the physics, not
housekeeping. A natural-source mesh needs air above the surface and a domain
several skin depths across at the lowest frequency; without them the answer is
confident and wrong rather than noisy, by a factor of four in the first 2D
forward model written here.

> **Rule.** Derive the mesh from the band and the expected property range, and
> assert the derivation — "a lower frequency asks for a larger mesh" is a test.

*`simpeg_nsem2d`, F013 (a cell is not a unit of ground).*

### A8. Difference every quantity the release states twice

A second statement of the same quantity is free validation, and a release that
carries one rarely says which copy is authoritative — or that there are two.
The Llano resistivity files carry their own topography block *and* ship a
separate electrode table. For one profile the two hold the same forty-eight
elevations against the same forty-eight positions in a different order; for the
other they are not the same set. They differ by up to 2.44 m, against a hole
that refuses at 2.3 m.

A reader that quietly takes the first copy it finds makes that choice
invisible. Read both, difference them, and where they disagree, decide on a
stated criterion and record it — here the scatter of the second difference,
which separates a surveyed profile from a scrambled column by a factor of six.

> **Rule.** Two copies of a quantity is a test, not a redundancy. Never read
> one without differencing it against the other.

*F037. The same shape as F026 — a second constant that existed and was not used.*

### A9. Run the check that needs nothing before the check that is interesting

A refraction gather's earliest arrival sits at its shot. That is a fact about
wavefronts, it costs one array operation, it needs no second survey and no
judgement about what materials exist, and it separated a spliced record from
eight sound ones by 16 metres against 4.

It was the third check tried. Reciprocity was reached for first -- it is a
theorem, it yields a measured error, it is the thing worth writing about -- and
then apparent velocity, which needs a view on what the ground can be. Both
worked. Both are more interesting and neither is cheaper.

The bias is toward the check that would be satisfying to have written. Against
it: before reaching for the good check, ask what could be computed from the
file alone, and run that.

> **Rule.** Order the checks by what they need, not by what they show. The one
> needing nothing outside the file goes first.

*F044. Its own caveat is instructive: where a picking program writes a floor,
several traces tie for earliest and the tie has to be resolved toward the
shot, or three sound gathers also look condemned (F043).*

### A10. Read what the file declares about itself, not the layout you know

A reader written against one instrument's files met a second instrument's and
was wrong in five ways: the columns were in a different order, the point count
was declared once for the sounding instead of per sweep, the position and the
z convention were absent, and the transmitter current had not been divided
out. Four of the five would have returned a number.

Every one of them is written down in both dialects. The column heading is a
line in the file; so are the unit, the count and the current. The reader was
treating four declarations as a layout it already knew, and only the unit --
the one it actually read -- was caught by a guard.

> **Rule.** Where a format declares something about itself, parse the
> declaration. A position in a row is a guess with a good track record.

*F046. The corollary, F047: when a declared quantity is rescaled, rescale its
stated uncertainty in the same place, or the pair silently disagrees.*

### A11. Measure the effect of a setting before adopting its rationale

A setting argued for on a number should have that number measured. Topography
was switched on for both Llano profiles because one falls 9.75 m over 188 m and
a half-space geometric factor is about five per cent wrong on terrain. That
reasoning is quantitative, plausible, and false here: inverting flat fits
marginally *better* on both profiles, because a near-linear slope is nearly a
rotated half-space.

The setting was right for a different reason — the section has to be compared
with a hole and a seismic line at real elevations — and the danger is precisely
that the outcome looked like confirmation. An unmeasured rationale travels to
the next case, where the relief may not be a plane.

> **Rule.** When the run is cheap, the counterfactual is not optional. Invert
> once without the setting and report both numbers.

Whether a run is cheap is itself something to measure. `ofag.classify_question`
answers a choice with one of three verdicts -- measure, time it first, or ask --
and the middle one exists because F055 is the gravity plugin estimating
forty-one days for a run that takes minutes — an estimate is not evidence that
a measurement is expensive, and a question declined on one is a question asked
for nothing.

*F039, F055.*

### A12. Measure the ground before building on it or building without it

Two cases model terrain and neither of them measured it.

Cedar Rapids never brought it in. The model volume is a flat plane at z = 0
and the depth below that plane is handed to an argument named
`depth_below_ground_m`, over a box whose ground runs 219 m on the floodplain
to 273 m on the valley wall — 36 m between the fifth and ninety-fifth
percentiles, a quarter of it standing above the floodplain. The elevation was
never missing. The measured file carries a DTM column for all 139,602
soundings and the importer reads four columns, none of them that one; the
contractor's own inversion carries `DTM_HEM`, and its value is exactly
`ELEVATION_28_TOP[0]`, because the 28-layer product it delivers is draped on
the terrain. The reference we compare against had already put the ground where
the ground is. The five resistivity lines are flat too, at a literal
`0.00000E+00` for every electrode, and there it is nearly harmless — the same
DTM sampled along each line gives 1.31 to 2.63 m over lines of 275 m, half a
per cent to one per cent. That is now measured in `import_ert` before a file
is read. It was not, and the first version of the number was itself wrong:
sampled between the release's stated endpoints, which for one of the five
sites are 477 m apart against a 275 m line.

Llano did bring it in, from a table nobody read closely. Every elevation in
the release, 96 electrodes and 48 geophones, is a whole number of feet: 938 to
970, with 965 missing altogether. The vertical resolution is therefore 0.3048 m,
which on ERT1 is one sixth of the line's entire 1.83 m of relief. The column
is headed metres above NAVD88 and the values are honest; what the heading does
not say is that they are contour crossings. A11 measured that flat fits
marginally better than either elevation list, and this is the reason it could:
below a foot there is nothing in the numbers to fit.

> **Rule.** Two numbers before any geometry, flat or not: the relief over the
> model's own footprint, and the step the elevations are quantised to. The
> first says whether flat is a choice or an assumption; the second says
> whether the elevation is a measurement or a contour. Report both, including
> when the answer is that flat was fine.

`refuse_unmeasured_terrain` in `src/ofag/agent/gates.py` measures both from
the elevations themselves and refuses a geometry whose ground is unstated. It
asks the second as a grid fit rather than as the smallest gap, because one
interpolated point destroys the gap and the release careful enough to
interpolate is the one that most needs catching. On Llano it reports the four
lines at 6, 32, 8 and 11 steps of relief and flags ERT1 and SRT1.

*F034, F035, F048. Related: F037, the same release stating the surface twice; A11,
which measured the setting without measuring its input.*

### A13. Resolve every identifier you write down

This project selects its own cases on permanence: *every input has a permanent
DOI*, a hard selection rule written because four of the sources consulted while
choosing case 1 had already gone dead. That rule picks which published datasets
the cases argue from. It is not a bar on data anyone brings — your own survey
has no DOI and needs none — and what follows applies to both. One row of case
1's source table
named the terrain as "3DEP 1/3 arc-second" with DOI 10.5066/F7PR7TFT. The
raster is 29.99 m, so it is 1 arc-second and not 1/3; and that DOI resolves to
*Shuttle Radar Topography Mission 1 Arc-Second Global* — a different mission,
a radar surface rather than bare earth. The
bytes were right: sampled at 211 points across the survey the raster sits
0.012 m from the current 3DEP 1 arc-second product. Both columns describing
them were wrong, and neither had ever been dereferenced.

There was no DOI to put in that cell: of the twelve 3DEP downloadable
collections exactly one, Seamless 1 m, carries a registered one. What belonged
there is what the same project already does elsewhere — the Stillwater table
records USGS I-797 with a dash, and FORGE's own column is headed *Identifier*
and carries `utahforge.com` for the well logs. So the missing DOI was not the
failure and the rule did not force anything. The failure was writing down an
identifier that had never been resolved, and it would have been the same
failure if a DOI had existed.

> **Rule.** Every input records an origin, and every recorded identifier is
> dereferenced before it is written down — check that what comes back is the
> thing you have. A published source with no DOI gets a dash and another name,
> as this project's tables already do; an unpublished one gets where, when and
> who holds it. What is never recorded is a string nobody followed.

*F030. Related: F049, where the source that had no DOI was the one that was
right.*

### A14. A datum is evidence for what it measured, not for what it resembles

Six of this project's failures are one sentence: something was read as evidence
for a question it cannot answer, and it answered anyway.

A lithological log records rock types down a hole and a stratigraphic log
records a pile; turning every logged contact into a surface point is right for
the second and wrong for the first, and thirteen of Stillwater's sixteen
multi-unit holes cross the series in the regional order downward, which is the
only reason the mistake is visible. A rock name is evidence of rock type and
not of position, so no name distinguishes the Basal series from the Banded one.
Three of a hundred logged names are eighty characters long, because the column
holds descriptions and a unit map wants names.

A layered inversion will accept all 122 magnetotelluric sites and return 122
models and 122 misfits, none of which is a statement about a two-dimensional
earth. A tensor has four numbers and a layered earth has one impedance, so
averaging the two polarisations produces a quantity that neither was. A
Gaussian class has a mean and a spread, and shallow basin fill falling from
2.4 g/cm³ at 660 m to 2.0 at surface has neither: 2.20 is the mean of a thing
with no mean. Auger refusal at 2.3 m is where the auger stopped, and it was
carried twice into a write-up as the base of weathering — the next two rows of
the same log show they drilled through it to 7.3 m.

> **Rule.** Before a datum answers a question, say what it measured and what
> question that licenses. The failure is not using bad data; it is using good
> data as evidence for the neighbouring claim, and the neighbouring claim is
> the one nobody writes down.

*F069, F071, F072, F009, F014, F015, F040 — the widest group in the corpus, and
nothing enforces it yet.*

### A15. A library's default is a choice somebody else made

Four more are a second sentence: a call did what it says and not what it
means, and returned a plausible number either way.

A smoothness weight left at `None` is not a neutral weight — SimPEG scales it
by the square of the cell size — and that one arrived three times in one case.
A regularization that takes rock classes and states a preference for models
made of them does not act on that preference unless a second weight is set.
`compute_clusters_precisions` derives precisions from covariances in place and
`order_clusters_GM_weight` sorts the classes; run in that order they are
re-paired, and every class then carries another class's spread. A
nearest-neighbour resample is defined everywhere, including past the edge of
its source, where it returns the nearest edge value with no indication that it
has left the data.

> **Rule.** For every library call whose result reaches a claim, read what the
> default is and what the call does to state, not only what it returns. A
> default is somebody else's decision about your problem, and an in-place
> method is a decision about the order of your lines.

*F006, F007, F008, F021. Nothing enforces this yet, and A2 is the nearest thing:
it validates a convention against something outside the engine, which catches
the subset where the wrong behaviour is a sign or a scale.*

---

## B. After a bad misfit: a ladder, cheapest first

Run these in order. Each rules out a class of cause, and the early ones are
seconds.

### B1. Fit a one-parameter model of the same data

A halfspace, a constant, a single scale. A richer model contains it as a special
case, so it **cannot** honestly do worse. When the 30-layer TEM inversion reached
a 45% residual and a brute-force halfspace scan reached 11.7%, a thing that
cannot happen had happened, and that localises the fault to the optimizer or its
objective **with no knowledge of the physics at all**. This is the single most
useful check in the list because it needs nothing.

*F021.*

### B2. Refit with the regularization off, from several starts

Separates "the optimizer failed" from "the model class cannot fit". Use a
sensible finite-difference step if the Jacobian is numerical — scipy's default
relative step of 1.5 × 10⁻⁸ on a log-conductivity is below the forward model's
own noise and produces a Jacobian of pure rounding error, which looks exactly
like a converged local minimum.

If the free fit reaches the same misfit as the production run, the optimizer is
already doing everything it can, and the answer is elsewhere.

### B3. Look at where the residual sits

Not its size — its shape.

| Residual concentrated at | Suspect |
| --- | --- |
| The earliest times / highest frequencies | The source waveform, gate timing, receiver blanking |
| The latest times / lowest frequencies | Domain extent, the deepest layers being unconstrained |
| One datum, by 60–80%, while its neighbours fit to a few per cent | That datum, not the model |
| Uniformly, at a level (a scale) | Calibration, static shift, a unit factor |
| Uniformly, in shape | The model class |

A misfit that is large at one end of the measurement axis and gone at the other
is a statement about the instrument, not the earth.

*F017.*

### B4. Ask whether the denominator is the problem

See A4 and A5. Convert the misfit into the data's own units — per cent of the
observed value — and judge *that*. χ² = 0.44 with a 22% residual and χ² = 6.3
with a 3.4% residual are the same inversion with two different floors, and only
one of the two numbers is about the fit.

### B5. Test an explanation by bounding it physically

When a free parameter collapses the misfit, check that the value it takes is
physically possible before believing it. A free scale per MT site took χ² from
9.0 to 2.0 — by running to a factor of twenty. Held to the factor of three that
galvanic static shift actually comes in, most of the gain vanished. The scale
was absorbing something else.

> **Rule.** Any free parameter added to rescue a fit must be reported with its
> recovered value and a statement of the range it is allowed to take.

*F022.*

### B6. Run a second, independent implementation

This is the one that is usually skipped and the one that found the largest error
in the project.

**A battery of diagnostics that all invoke the same forward model cannot detect
an error in that forward model, however many of them agree — and their agreement
feels like confirmation.** The FORGE magnetotellurics was diagnosed three times,
with a measurement behind each: wrong model class, unrecoverable static shift,
two-dimensionality. The unregularized refit, the multi-start, the free-scale
test and the phase-only test all supported them. All four called the same
simulation, which was inverting the model upside down.

What broke it was building the 2D simulation and requiring it to agree with the
1D one over a layered earth — a case where both must give the same answer. They
differed by 67×. χ² then went from 9.57 to **0.76** and agreement with an
independent published inversion from +0.30 to **+0.75**.

> **Rule.** Track the number of *independent implementations* that agree, not
> the number of checks. Two codes, or one code and closed-form arithmetic, is a
> different kind of evidence from ten diagnostics sharing a solver.

*F023.*

### B7. Compare against data or a model the inversion never saw

The last resort and the only one that can falsify rather than diagnose. Witter's
published density model found the gravity sign error; the published Phase 3 3D
resistivity model is what says the MT models are now right.

Held-out data has to be actually held out: the FORGE seismic interpretation is
deliberately not used in any inversion, because the granite surface that *was*
used came from the same report and confirming a prior is not validation.

And the held-out *model* has to be a model. A published section is often a
plotting export — Llano's two arrive as exactly 361 cells each, at 0 to 4 m
irregular spacing — and forward-modelling a figure does not test the inversion
behind it. Both of Llano's predict the delivered readings at chi squared 13 to
26 against our own 0.8 to 2.5, which reads as a devastating result and is an
artifact of the deliverable. Band medians are what such a file supports.
Check the cell count and the spacing before drawing a conclusion from a forward
response, and if the count is round and identical on every line, it is an
export (F038).

---

## C. Before reading a result into a model

An inversion that passed A and B is *correct*. Reading several of them into one
geological model is a separate job with its own failure mode: every mistake
here produces a model that sums to 100 per cent, renders cleanly, and is
believed. There is no misfit at this stage. These four are what stood in for
one, and `ofag.services.interpretation_service` performs them
(`docs/interpretation.md`).

### C1. Measure each method's resolved band before reading it

Compare every layer of a recovered model against the model it started from. A
layer that never moved is a picture of the prior at full resolution, and it is
indistinguishable from ground by eye. Read only above the deepest layer that
moved.

This is not a refinement. Two methods once appeared to disagree by a factor of
21 at 180 m, and most of that was one method's prior being compared against the
other's data — a *measured* disagreement, in a real number, about nothing.

### C2. Score an estimator before guarding it

Any spatial interpolation gets compared by leave-one-out against the **mean of
the same data**. An estimator that cannot beat a constant is not adding spatial
information, whatever it is called.

A distance guard is not a substitute. It bounds an estimator's damage, it never
reveals that the estimator is worse than no estimator, and the hole it leaves
reads as caution: "drawn over 72 per cent of the ground" is a sentence that
sounds careful and was describing nearest neighbour losing to the mean (F027).
Report how far the data actually reaches, measured afterwards, instead of a
radius chosen in advance.

### C3. Select on every constant that defines the region

A region named by more than one constant — a horizontal extent *and* a vertical
one — is selected on all of them or none. Half of it silently admits the mesh's
padding, and the share that comes back is always plausible: 89.9 per cent
against a true 69.1, and nothing to compare it with (F026).

Volume shares are the worst case of this generally. They are bounded, they sum
to one, and every wrong version looks like a result. Tie one to a quantity
computed another way, and when there is nothing to tie it to, say so rather
than reporting it plain.

### C4. Walk the whole path on five samples before launching the full run

Before a job that takes more than a few minutes, run it on two to five items
and read what it wrote — not that it exited, but that the artifact is where the
next stage will look for it and contains what that stage will ask of it.

This is not caution, it is arithmetic. Twice in one case a 1,374-sounding
inversion ran to completion before anything checked it: once it had a
convention wrong and returned chi-squared 29 for every sounding, once it wrote
its section into the runs root where the next run would overwrite it. Each cost
half an hour. The five-sample walk that would have caught either took three
minutes, and the second failure was a path, which no amount of numerical care
would have found.

The check has to reach the *consumer*. "It ran" and "it wrote a file" are not
the same as "the comparison can read it", and the path bug passed the first two.

> **Rule.** For any run over a few minutes: execute the smallest honest subset,
> load its output the way the next stage will, and assert one fact about the
> contents. Then launch.

### C5. Distinguish "tested and negative" from "nobody looked"

Where a rule declines to judge — no station within reach, no coverage — those
cells fall through to some other label and the model asserts it. Report the
share, per rule. Eleven per cent of one volume was labelled "not the conductor"
by a rule that never looked at it, and every cell in it was a positive
statement the data had not made.

The per-cell form of this is a support distance stored beside the assignment,
so a reader can ask any cell what its label rests on.

---

## D. What an outcome means

| Symptom | Almost always |
| --- | --- |
| Recovered model equals the starting model, exactly | The regularization is overwhelming the data — check for an unset weight (F021) |
| Target misfit reached on iteration 1 | The tolerance is too loose, and possibly circular (A5) |
| A richer model fits worse than a simpler one it contains | The optimizer, not the physics (B1) |
| Every start converges to the same bad value | The model class, *or* a wrong forward model (B2 then B6) |
| Converges, fits, and disagrees with an independent model | A convention: sign, order, units (A2) |
| A free parameter fixes everything, at an impossible value | It is absorbing a different error (B5) |

---

## E. What this does not cover

These procedures catch errors that make a run *wrong*. They say nothing about
whether a correct result is *worth* anything — whether 323 observations
determine 145,062 cells, whether a class proportion is a finding or a restated
prior, whether a depth of investigation is measuring the mesh. Those are in the
problem log as F011, F012 and F013, and they need a different kind of check:
reporting in units of ground rather than units of discretisation, and stating
what a result would look like if the data said nothing.
