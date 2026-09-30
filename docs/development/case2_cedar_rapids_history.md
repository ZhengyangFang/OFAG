# Case 2 — the Cedar River alluvial aquifer, Cedar Rapids, Iowa

For source releases, execution stages, and the manuscript figure mapping, use
the [reproduction guide](../reproducibility.md). The ERT lines that do not reach
the target misfit and the limits of the ERT–AEM comparison remain part of the
reported result. The development history below is retained for the agent's
retrieval corpus and should not be read as a count of independent agent
discoveries.

Sand and gravel over glacial till over carbonate bedrock, and it is the city's
drinking water. Two surveys cover it: thirteen ground resistivity profiles at
five sites in April 2015 (`doi:10.5066/P9YXJDHX`) and a CGG RESOLVE
frequency-domain helicopter EM survey of 53 km² in May 2017
(`doi:10.5066/P9BS882S`). The published interpretation of the airborne data is
`doi:10.3133/sim3423`.

Case 1's write-up is `docs/case1_forge.md`; the problems logged there (F001–F030,
and Stillwater's F058–F075) are the reason most of the decisions below are measured rather than chosen.

## What is being looked for

Not a surface this time. Case 1's target was the top of the granitoid basement
— one interface in a two-layer basin. Here it is a **body**: a sand-and-gravel
aquifer of finite thickness, between a fine-grained cover above and glacial
till below, with two contacts rather than one.

The AEM says what it looks like. Inside the modelling volume, over 16,073
soundings:

| depth | p25 | median | p75 |
| --- | --- | --- | --- |
| 0 m | 23.8 | **35.4** | 57.5 |
| 13 m | 118.3 | 168.4 | 232.5 |
| 26.5 m | 188.2 | **280.5** | 356.1 |
| 48.7 m | 121.1 | 178.8 | 231.7 |
| 85.4 m | 49.5 | **80.1** | 123.4 |

A resistive layer peaking at **26.5 m** and about **58 m thick** above
100 ohm·m, between conductive ground above and below, with a factor of **nine**
against the surface. That is the aquifer, and it is the first thing this case
measured rather than read off a published map sheet.

## Why the modelling volume is where it is

`VOLUME = (603_500, 606_500, 4_650_000, 4_651_500)`, in EPSG:26915. Three
candidate boxes were scored the way case 1 learned to score them — coverage
first, then whether the target is actually there.

| box | km² | AEM | per km² | ERT sites |
| --- | --- | --- | --- | --- |
| **this one** | 4.5 | 16,073 | **3,572** | 4 |
| all five sites + 500 m | 8.4 | 21,962 | 2,601 | 5 |
| all five sites + 1,000 m | 15.5 | 31,019 | 1,998 | 5 |

and, more to the point, what the aquifer looks like inside each:

| region | peak depth (p10–p90) | peak | thickness |
| --- | --- | --- | --- |
| this box | 26.5 m (16–49) | **304 ohm·m** | **58 m** |
| the rest of the survey | 31.0 m (0–85) | 168 ohm·m | 38 m |
| within 500 m of Edwards CW3 | 22.5 m (11–36) | 194 ohm·m | 42 m |

The box is the part of the survey where the aquifer is thickest, most
resistive and most consistently present — a p10-to-p90 depth range of 16 to
49 m against 0 to 85 for everywhere else, and a depth of 0 m is what "no
coherent resistive layer here" looks like as a number.

**It costs Edwards CW3**, 2.2 km east, where the aquifer is thinner and weaker.
That is worth more as a control than as a fifth site inside: ground the model
never saw, where the airborne data says conditions differ.

## The thing case 1 could not do

Case 1's central negative result was geometric. Its two electrical methods sat
3.7 km apart and shared no depth band in which both resolved, so they could not
check each other, and that was discovered late.

Here:

| | |
| --- | --- |
| ERT sites inside the AEM footprint | 5 of 5 |
| nearest AEM sounding to each | **4 to 63 m** |
| AEM depth of investigation, median | 112 m |
| ERT investigation depth, median / max | 10–14 m / ~51 m |
| the target | 10–70 m, peaking at 26.5 |

The two methods overlap over the top ~50 m, and **the aquifer's peak at 26.5 m
sits in the middle of that overlap**. ERT resolves the cover and the top of the
aquifer; only the AEM resolves its base. So there is a band where they must
agree and a band where only one speaks, and both are known before anything was
inverted.

The ERT depth figures come from the array geometry through Edwards' (1977)
fraction of the array span, which is a rule of thumb and is labelled as one in
the code. The real number comes from the inversion's own sensitivity.

## The data

| What | Source | Identifier |
| --- | --- | --- |
| Electrical resistivity, 13 SuperSting R8-IP surveys at five sites, April 2015, raw | Johnson and others, 2020, USGS data release | 10.5066/P9YXJDHX |
| Borehole geophysics, four logged wells inside the volume | the same release | 10.5066/P9YXJDHX |
| Airborne EM and magnetics, CGG RESOLVE, May 2017, measured and inverted | Deszcz-Pan and others, 2018, USGS data release | 10.5066/P9BS882S |
| Published interpretation, for comparison | Valder and others, 2019, USGS SIM 3423 | 10.3133/sim3423 |

Not in this repository: fetched into `data/case2_Cedarrapids/`, which
`.gitignore` excludes. Which delivered file became which path, and under what
original name, is in `SOURCES.tsv` beside the data — eighteen rows, because a
file renamed for legibility and not matched back to its delivery is a file
with no provenance.

**The release cites its own DOI wrongly, twice.** Both
`ert/metadata.xml` and `wells/metadata.xml` give
`http://dx.doi.org/10.5066/P9XJDHX` in their cross-reference. That is one
letter short of `F066YXJDHX` and it does not resolve; the correct identifier is
in the release's own `Read_Me_ERT_CR-IA.txt`. Found by dereferencing the
table above rather than by reading it (A13).

### ERT

Thirteen surveys, **not the fifteen the metadata states**: `SVP_CW6` and
`SVP_S10` have no Schlumberger. AGI SuperSting R8-IP, 56 electrodes at 5 m, a
275 m line per site, 18,519 measurements in all.

Three arrays over the same ground at three of the sites is this case's free
independent check — dipole-dipole, Schlumberger and inverse Schlumberger are
sensitive to different things and must nonetheless recover the same earth. It
is the check case 1 had to construct out of two different methods.

`.stg` is read by `ofag.formats.stg`, written here rather than delegated: the
release documents the format field by field, the parse is forty lines, and the
vendor path this project already has is recorded as having applied its own
reciprocal filter and returned 24 measurements of 264 with nothing saying so.
The reader is checked on import by recomputing the geometric factor from the
electrode coordinates and comparing against the instrument's own apparent
resistivity — **they agree to 0.0% on all thirteen files**, which is what
confirms A, B, M, N were read in that order.

### AEM

RESOLVE, six frequencies (400, 1800, 3300, 8200, 40k, 140k Hz; 3300 coaxial,
the rest coplanar), in-phase and quadrature in ppm, 139,602 soundings. The
release also carries the contractor's EM1DFM inversion — 139,599 soundings,
28 layers each, with a depth of investigation — which is the independent model
to check against, in the role Witter's density model played in case 1.

## The ERT inversions

Thirteen 2D sections, one per survey, through `pygimli.ert.dcip`. Six fit and
seven do not.

| site | dipole-dipole | Schlumberger | inverse Schlumberger |
| --- | --- | --- | --- |
| SVP_S10 | **0.473** | — | **0.584** |
| SVP_CW6 | 45.266 | — | **0.873** |
| Edwd_CW3 | 70.425 | **1.239** | **1.141** |
| Ellis_CW1 | 10.167 | **0.376** | 6.683 |
| SVPDemo-Day | 37.206 | 32.803 | 30.050 |

A run is delivered when it fits, not when it converges. The first version of
the report called every one of these complete, because each was SUCCEEDED and
each had a chi-squared — a test of the harness rather than of the result.

### What the misfit is, and what it is not

The ladder in `docs/agent_validation_and_debugging.md`, in order.

**B1, a one-parameter model.** The best single resistivity for the same
measurements gives chi-squared 29 to 170. Every inversion beats it — 169.8 to
70.4 at the worst, 38.6 to 0.47 at the best — so the optimizer is working and
the models carry real information. Every run stopped after 2 to 6 iterations
against a limit of 12, on stagnation rather than on a cap.

**B3, where the residual sits.** Split by geometric factor, the misfit is at
**small** |K|, not large:

| |K| decile, low first | | | | | | | | | |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 672.9 | 19.0 | 48.1 | 21.6 | 24.5 | 25.3 | 25.1 | 30.9 | 14.7 | 11.9 |

for Edwd_CW3's dipole-dipole. The hypothesis this was written to test was the
opposite one — that a dipole-dipole survey's noise grows with the geometric
factor and swamps the deep readings — and the measurement refused it. Small
|K| is short offsets, which is the shallowest ground and the fewest electrodes
between the pairs.

**So the residual was resolved per electrode**, and it is not spread at all:

| survey | chi² | worst electrodes | share of the misfit they touch |
| --- | --- | --- | --- |
| Edwd_CW3 dipole-dipole | 70.4 | 20, 21, 23, 24 | **91%** |
| SVPDemo-Day dipole-dipole | 37.2 | 33, 34, 35, 36 | **97%** |
| SVPDemo-Day Schlumberger | 32.8 | 33, 34, 35 | 80% |
| SVP_CW6 dipole-dipole | 45.3 | 37, 41, 45, 49 | 68% |
| Ellis_CW1 dipole-dipole | 10.2 | 33 | 83% |

**The three arrays at SVPDemo-Day independently blame the same electrodes.**
Three measurement geometries, three separate inversions, electrodes 33 to 36
each time. That is what three arrays over one line were supposed to buy, and
it is the check case 1 had to build out of two different methods.

### Contact resistance, as a pre-inversion index

The `.crs` files measure the contact resistance of every current pair before
anything is inverted, which makes them the non-circular way to judge this —
culling on a model's own misfit is what A5 forbids.

It works, partly.

| | worst four electrodes | site median | r(log crs, log chi²) |
| --- | --- | --- | --- |
| SVPDemo-Day dipole-dipole | **13,428 ohm** | 1,243 | +0.609 |
| SVP_CW6 dipole-dipole | 946 | 464 | +0.439 |
| Ellis_CW1 dipole-dipole | 187 | 215 | **−0.611** |
| Edwd_CW3 dipole-dipole | — | — | **no .crs in the release** |

At two sites it flags the electrodes the misfit blames, at one it points the
other way, and at the worst survey of the thirteen the file does not exist.

There is also a site-level reading of the same numbers, and it is the cleaner
one: **SVPDemo-Day's median contact resistance is 1,243 ohm against 215 to 540
everywhere else** — two to six times worse coupling across the whole line. It
is also the only site where all three arrays fail. That is a site explanation,
and it does not need the per-electrode correlation to stand.

### What fixed it: two indices the data measured about itself

**The reciprocals.** Half of every dipole-dipole file is `(M, N, A, B)` where
the other half is `(A, B, M, N)` — about 1,500 pairs in 3,000 readings, the
same measurement twice. Collapsing them halves the data and, far more usefully,
their difference is a **two-sample error estimate per datum**, measured on this
ground by this instrument before anything is inverted.

The median of that difference is 0.14 to 0.29 per cent, and reading only the
median is how this was nearly missed:

| survey | n | pairs over 5% | p50 | p95 | max |
| --- | --- | --- | --- | --- | --- |
| Edwd_CW3 | 1,506 | 163 | 0.26% | **162.9%** | 199.5% |
| SVP_CW6 | 1,600 | 201 | 0.27% | **130.5%** | 197.1% |
| SVPDemo-Day | 1,591 | 185 | 0.29% | 77.6% | 198.9% |
| Ellis_CW1 | 1,506 | 72 | 0.16% | 3.0% | 196.9% |
| SVP_S10 | 1,600 | **0** | 0.14% | 0.6% | 1.3% |

**SVP_S10 has not one pair over five per cent, and it is the one survey that
fitted from the start.** Every other has 72 to 201 of them, some disagreeing by
a factor of two. A median of 0.26 per cent and a p95 of 163 per cent are the
same data.

Using `max(declared floor, this datum's reciprocal)` as the error down-weights
exactly those readings, and no threshold was tuned to do it:

| survey | before | after |
| --- | --- | --- |
| Edwd_CW3 dipole-dipole | 70.4 | **1.04** |
| SVP_CW6 dipole-dipole | 45.3 | **0.64** |
| Ellis_CW1 dipole-dipole | 10.2 | **0.79** |
| SVP_S10 dipole-dipole | 0.47 | 0.29 |
| SVPDemo-Day dipole-dipole | 37.2 | 12.8 |

**The contact resistance.** The `.crs` files measure it per current pair before
acquisition. At one survey and one only — SVPDemo-Day's dipole-dipole —
electrodes 33, 34, 35, 36 and 38 read up to **72,575 ohm** against a survey
median of 1,243, and those are the electrodes the misfit independently blames.
Every quadrupole using one is dropped, at a declared 5 kohm, which is where an
instrument runs out of compliance voltage rather than a number fitted to the
answer. It removes 498 of 1,591 readings at that survey and nothing anywhere
else. The count of non-positive apparent resistivities there falls from 61 to
13 at the same time, which is a second, unasked-for corroboration.

The cull is judged **per site**, not per survey, and that is what makes it
work. Only the dipole-dipole's own `.crs` caught the spike; the two
Schlumberger files at the same site read a harmless 1,896 ohm maximum. But the
three arrays ran the same day down the same line, so a badly coupled electrode
belongs to the deployment. Taking the union of what each file found removes
498, 117 and 109 readings at SVPDemo-Day and nothing anywhere else:

| SVPDemo-Day | before | after |
| --- | --- | --- |
| dipole-dipole | 37.2 | **1.05** |
| Schlumberger | 32.8 | **1.09** |
| inverse Schlumberger | 30.1 | 4.87 |

**Eleven of the thirteen surveys now fit.** What remains is two inverse
Schlumberger sections — Ellis_CW1 at 6.68 and SVPDemo-Day at 4.87 — and they
are left as not fitting. Both are close enough that a little more culling would
bring them under, and that is the reason not to: the criteria used so far were
measured before the inversion, and the next turn of the handle would be fitted
to the misfit it was removing.

**Agent capability:** a dataset that measures itself twice has told you its
error, and the file usually does not say so — look for reciprocal pairs before
declaring an error budget. And read the *distribution* of a quality index, not
its centre: the median said this data was excellent and the ninety-fifth
percentile said a fifth of it was unusable, and only one of those was true of
the readings that mattered.

 The temptation is to drop the quadrupoles
touching the worst electrodes until the chi-squared comes down, and that is
circular — the threshold would be fitted to the misfit it is removing. What a
cull needs is a criterion from outside the inversion, and the contact
resistance is only half of one. The two surveys that still do not fit are named in
the report as not fitting and are not part of any model.

## The AEM inversion

`simpeg.aem.fdem1d`, written for this case: SimPEG's `frequency_domain`
module, six coil pairs, one layered earth per sounding. 1,374 soundings inside
the model volume, thinned to 25 m from the delivery's 2.3 m along-line spacing
— the 10 Hz sample rate against the helicopter's speed, not a statement about
resolution, since the footprint at 51 m altitude is tens of metres across.

    chi-squared median   0.895
    soundings fitting    1,240 of 1,374   (90 per cent)

### F033 — A sign convention that also cost three times the runtime

The coaxial pair comes back with the opposite sign to the five coplanar ones,
and it is not a defect: SimPEG divides the secondary field by the primary the
geometry actually produces, and a coaxial pair's on-axis primary opposes a
coplanar pair's broadside one. CGG reports every channel positive, so it
normalised by the magnitude.

Read with a coplanar sign the inversion did what this project's problem log
keeps describing: it did not fail. It ran to its iteration limit, returned a
model, and reported chi-squared 29. The best-fitting **halfspace** gives 32.5
with the sign as delivered and **1.1** with the coaxial pair negated.

It also made the run three times slower — 3.88 s a sounding against 1.35 —
because every sounding burned its full iteration budget and line search
chasing a target it could not reach. Eighty-nine minutes became thirty.

**The pre-flight missed it, and that is the part worth keeping.** Two checks
were written before the first run, and both used a coplanar pair. A system
that is five-sixths coplanar passed its conventions and then met its coaxial
channel. A probe that never exercises a geometry the data contains is not a
probe of that geometry — the same failure as F028, one case later, by the same
hand. The third check now sets a coaxial pair against a coplanar one over the
same halfspace and requires their quadratures to differ in sign.

Three conventions are declared in the spec rather than inferred: the frequency
(383, 1820, 3315, 8488, 40840 and 133530 Hz, against column names that say
400, 1800, 3300, 8200, 40k and 140k), the coil geometry, and this sign.

## Do the two methods agree?

The question case 1 could not ask. Compared as a depth profile, which needs no
lateral registration — 1,868 ERT cells against the AEM soundings within 300 m
of each line:

| depth | ERT | AEM | ratio |
| --- | --- | --- | --- |
| 10 m | 122.5 | 143.1 | 0.86 |
| 15 m | 149.0 | 209.9 | 0.71 |
| 20 m | 193.3 | 236.5 | 0.82 |
| 25 m | **265.6** | **242.9** | **1.09** |
| 30 m | 311.9 | 226.8 | 1.38 |
| 35 m | 403.8 | 191.5 | 2.11 |
| 45 m | 587.0 | 163.1 | 3.60 |

**Above 30 m they agree to within forty per cent, and both put the aquifer's
resistivity peak at 25 m.** Two methods with nothing in common but the ground —
four electrodes pushing current from the surface, and a coil pair inducing it
from 51 m up — over the same few tens of metres, arriving at the same number.
That is the case's result.

Figure 4e draws it with a narrower and stricter selection, the one panel b
shows: the dipole-dipole section at each of the four sites inside the box,
every model cell on the line against every fitting sounding within 300 m, in
2.5 m bands. There the medians agree to within 15 per cent from 10 to 20 m
(ratios 1.03, 0.88, 0.92, 1.02, 1.14) and part at 25 m (1.47), and 25 m is
where the median ERT coverage passes two decades below its maximum (2.03,
from 1.87 at 22.5 m). The two methods agree exactly as far down as the ERT
has data.

Below 30 m the ratio climbs monotonically to 3.6. That is not a disagreement
about the earth: it is the ERT running out of data and the smoothness term
carrying its model upward, the same shape as case 1's TEM sitting at its prior
below 226 m. The AEM, with a depth of investigation of 112 m, turns over at
30 m and finds the conductive till beneath the aquifer; the ERT cannot see it.

### What could not be measured

**Lateral agreement.** A cell-by-cell correlation over the shared band gives
+0.30, and it does not mean what it looks like. The 1,868 ERT cells match only
about fifty distinct AEM soundings, so the statistic is dominated by the depth
profile both methods share. Sliding each ERT line along its own azimuth, to
test whether the release's unreliable endpoint coordinates had misplaced them,
produced a curve that rises in *both* directions from the stated position with
no interior peak — which is the signature of a statistic that is not measuring
alignment at all, not of a placement error. The comparison set stays at 1,868
cells and 43 to 51 soundings throughout, so it is not an artefact of which
cells survive. Reported as not established rather than as a weak positive.

**A resolved band for a dipole-dipole section.** `resolved_band_from_sensitivity`
reads a 2D inversion's own coverage, divided by cell size — an inversion mesh
coarsens with depth, so raw coverage *rises* and read raw says a 275 m line
resolves to 58 m. It gives a consistent 48 m across all five Schlumberger-family
sections at four sites, and 2 to 8 m for every dipole-dipole, which is not
credible for three thousand measurements on a 275 m line. The normalisation is
the suspect: a dipole-dipole's near-surface sensitivity spikes between adjacent
electrodes, and dividing by the top ten metres flattens everything below it.
Left as measured and unused; the depth-profile result above does not depend on
it.

## The model

Four units over the volume, on a 50 by 50 by 2 m grid to 98 m, 88,200 cells.

| unit | share by volume | resolved by |
| --- | --- | --- |
| resistive: sand, gravel or bedrock | 56.4% | AEM, **not separable** |
| finer basin fill | 32.2% | AEM |
| above the resistivity rise | 9.6% | AEM, **not a rock contact** |
| below the investigation depth | 1.7% | AEM, **nothing claimed** |

**The model stops where the AEM stops seeing.** The depth of investigation
varies by column from 56 to 146 m, median 112, and the floor is its tenth
percentile, 98 m: nine columns in ten are resolved all the way down. The model
used to run to 120 m, the depth of the inversion itself, and 8.4 per cent of it
was then ground below the investigation depth that it could only label as
unseen. What remains of that unit, 1.7 per cent, is the columns whose depth of
investigation is shallower than 98 m.

`uv run python scripts/case2_cedar_rapids.py build_model`.

The build also writes `imports/ert_aem_local_comparison.csv`: 2,676 matched
values at ERT electrode positions and depths of 5–30 m across four sites
inside the box. Each row records the ERT run, distance to the nearest AEM
sounding, distance to the sampled ERT model cell, the ERT coverage drop, and
whether it is inside the contractor's investigation depth. These rows reuse the
same soundings and sections, so they are **local checks, not 2,676 independent
measurements**. Their median ERT/AEM ratio is 1.10 at 10 m and 1.88 at 30 m;
the 30 m rows have a median ERT coverage drop of 2.33 decades, past the
declared two-decade bar. They are shown for diagnosis, not treated as
validated agreement. All rows are within the contractor's AEM DOI; 1,778
of 2,676 also pass the ERT two-decade coverage check, whose normalisation
is itself uncertain for dipole-dipole arrays.
The ERT lines are intentionally not extended into the 3D grid: the release's
endpoint locations are approximate and the lines do not constrain the space
between them.

`imports/model_sensitivity.npz` stores 27 alternative assignments made from
the finished AEM inversion: resistive cutoffs of 100, 120 and 140 Ω·m;
horizontal reaches of 200, 300 and 400 m; and 0.8, 1.0 and 1.2 times the
contractor's stated investigation depth. The fractions describe sensitivity
to these **declared choices**, not calibrated probabilities. Across the 27
settings, 25,132 of 88,200 cells change label at least once (28.5 per cent;
it was 41,173 of 108,000 when the model ran to 120 m, and most of the
difference is the unseen ground the floor no longer carries). The contractor's
investigation depth remains an external bound; this case still has no
independent investigation-depth calculation for its own inversion.

**The volume hangs on the ground, and it did not used to.** Every cell sat at
minus its depth from a plane at zero, over a box whose ground runs 215 m on
the floodplain to 273 m on the valley wall — 58 m of relief across 1,800
columns. The elevation had been in both airborne files the whole time: a DTM
column for all 139,602 measured soundings, and in the contractor's own
inversion a `DTM_HEM` whose value is exactly `ELEVATION_28_TOP[0]`, because
the 28-layer product this case compares itself against is delivered draped on
the terrain.

Each column hangs at the ground of the one sounding it reads, not on a surface
interpolated between them: the flight lines are 400 m apart, and an
interpolated surface would draw the valley wall at a resolution the survey
does not have and put a column's depths under a different ground than the one
they were measured from. The result is blocky across lines on purpose.

The unit shares did not move — 9,063, 8,456, 53,303 and 37,178 cells before
and after, on the 120 m floor the model had then — and that is the point
rather than an anticlimax. Every rule in
this model is depth-referenced except one, and the exception is
`below the investigation depth`, which compares `cell_centres_m[:, 2]` against
an elevation. Draping the cells without moving that surface with them would
have left the floor of the claim at sea level under the bluff and 273 m up
under the floodplain, and the unit shares would have moved a long way. The
identical counts are the check that they did not. F034, F035, A12.

**One contact is mapped and it is measured, not asserted.** The base of the
fine-grained cover is picked at 1,219 of the 1,240 soundings that fit, median
7.6 m, and the fitted surface predicts a held-out pick to **3.6 m** against the
picks' own spread of 4.6.

**The base of the aquifer is not mapped, and the data is the reason, not the
setup.** The contractor's own 28-layer inversion to 217 m has the same shape as
our 20-layer one to 120: a single broad peak — theirs 280 ohm·m at 26.5 m,
ours 185 at 22 — and then a smooth monotone decline with no second inflection.

| depth | contractor | slope | cells with a value |
| --- | --- | --- | --- |
| 13.0 m | 168.4 | +1.05 | 100% |
| 26.5 m | **280.5** | −0.24 | 100% |
| 48.7 m | 178.8 | −1.48 | 100% |
| 74.5 m | 94.0 | −1.17 | 95% |
| 97.9 m | 63.2 | −5.95 | 74% |
| 112.0 m | 28.4 | −6.72 | 38% |

The plunge below 90 m is the investigation depth taking the profile away —
the share of soundings that still carry a value falls with it — not a contact.
So `doi:10.3133/sim3423` separates till from bedrock by cutting that smooth
decline at a chosen value, with boreholes and seismic beside it, rather than by
resolving an interface in the resistivity. This case does not do that, because
the resistivity alone does not support it.

The same conclusion from our own inversion: the
pick lands on the same layer — 87.1 m — at 1,090 of 1,240 soundings, with the
twenty-fifth, fiftieth and seventy-fifth percentiles all equal. That is the
depth of investigation cutting the profile, not a contact. The published
interpretation of this survey (`doi:10.3133/sim3423`) separates glacial till
from bedrock; this case cannot, and the difference is visible in the setup: 20
layers to 120 m against their 28 to 217, and our inversion computes no depth of
investigation of its own, so the bound used here is the contractor's.

So the model carries a unit that is not geology. "Below the investigation
depth" is 1.7 per cent of the volume where nothing is claimed, and the
resistive rule separately declines to judge 2.9 per cent as further than
300 m from any sounding — untested rather than negative.

### The wells, on the one surface this case did map

The four boreholes inside the volume were brought in to check the shallow
surface, which is the thing they can actually reach — they bottom at 16 to
19 m. Two carry a lithology column whose depths can be read: the plots are
rotated, so the depth axis runs along x, and the labels convert through it.
GX-2's own text calibrates the offset, logging "shaley limestone at 55 feet"
where the drawn label sits at 17.2 m.

| | the well's fine-to-coarse change | the AEM's steepest rise |
| --- | --- | --- |
| GX-1 | ~3.1 m | **12.7 m** |
| GX-2 | ~3.0 m | **7.6 m** |

They are not the same boundary. At GX-1 the resistivity is *falling* where the
well changes — 104 ohm·m at 0.6 m down to 76 at 4.9, and only then rising — so
the surface this case mapped sits 9.6 m below the lithologic contact and moves
the opposite way across it.

That is the same result as the bedrock one, at the other end of the profile,
and together they settle what this model is. **Neither thing it names is a rock
contact.** The AEM resolves one resistivity boundary and one resistive body;
the wells show the shallow one is not the fine-to-coarse change and the deep
one contains bedrock. The published study lists the reason without needing the
wells: the resistivity "may reflect several characteristics of subsurface
materials including variations in lithology, porosity, water quality, grain
sorting, and degree of saturation".

So both units are named for the measurement — "above the resistivity rise",
"resistive: sand, gravel or bedrock" — and the model is honest about being a
resistivity model rather than a lithologic one. Two wells is thin evidence and
it is stated as such; what makes it worth acting on is that both point the same
way, and that the published interpretation says the same thing about the same
survey.

### How the published study separated till from bedrock, and why this one cannot

Not from the resistivity. `doi:10.3133/sim3423` says so in its own words:

> "Some overlap in the expected resistivity value ranges for the three
> lithologic units made interpretation of contacts based upon resistivity
> values alone difficult."

> "Interpretation of the resistivity profiles in these areas was informed by
> well lithologic logs that consistently indicated the contact between the
> alluvial deposits and the bedrock to be **deeper than the area of resistivity
> contrast in the AEM data**."

Three things carried the delineation, and none of them is the AEM. The
**lithologic logs** placed the contacts, from the Iowa Geological Survey's well
database. A **stratigraphic order was imposed**: "bedrock was *assumed* to be
the lowest unit in a profile, glacial till was deposited on a bedrock surface".
And the cut was **context-dependent** rather than a threshold: "resistivity
values used to delineate the bedrock surface beneath till differ from values
used beneath alluvial deposits". The AEM interpolates between the logs; it does
not find the contact. They also state the constraint is thin — "given the few
lithologic logs available in the Cedar Rapids area, some uncertainty in exact
placement of lithologic boundaries may exist" — and that bedrock has no mapped
bottom "because of the limitation of the AEM investigation depth".

**Confirmed here at a well.** Four of the release's nine logged boreholes fall
inside the model volume, and one, GX-2, carries a numeric pick: *shaley
limestone at 55 feet* below a casing top 0.73 m above ground, so **16.0 m below
ground**. The AEM beneath it:

| depth | resistivity |
| --- | --- |
| 11.2 m | 144.1 ohm·m |
| **16.0 m** | — **the well says bedrock** |
| 17.9 m | 191.0 ohm·m |
| 22.4 m | 202.6 ohm·m |
| 27.8 m | **203.4 ohm·m** — the AEM's peak |

The profile rises smoothly through the contact and peaks 12 m below it.
**There is no resistivity feature where the rock changes.** So the resistive
body this case maps is not the aquifer: at GX-2 everything it contains below
16 m is limestone, and the unit is named for that rather than for what would be
convenient.

That is the honest end of this thread. Separating the two would mean doing what
the published study did — placing the contact from the logs, assuming the
stratigraphic order, and varying the cut by context — and the result would be a
map of the boreholes interpolated by the AEM, not a result the resistivity
supports. The four wells inside the volume are 16 to 19 m deep and only one
reaches rock, which is not enough to place a surface across 4.5 km².

### What this case says about the interpretation service

The service was built for case 1, where the rule was *one method per depth*
because the two electrical methods shared no band in which both resolved. Case
2 does not use that at all: all four units here are assigned by the AEM, and
the ERT does not appear in the model.

Not because the ERT is worse — over 0 to 30 m it agrees with the AEM to within
about half, which is the case's result — but because five 275 m lines occupy a
negligible fraction of a 4.5 km² volume. **The two methods are separated by
coverage, not by depth**, and the service has no way to express that: it can
give a unit to the method that resolves its depth, and cannot give a unit to
the method that resolves its *place*.

What did carry over worked. `fit_surface` chose the estimator by leave-one-out
and reported 3.6 m; `beyond_reach_share` surfaced the 2.9 per cent no sounding
covers; the `REMAINDER` rule left no cell unassigned. What is missing is a
coverage-weighted assignment, and that is the next case's problem rather than a
defect in this one.

## Problems

### F031 — A null value that is a number

`RES2_FINAL` carries **−99999** for every layer below the depth of
investigation: 22.4 per cent of all layer values in the file. It is documented,
and it is also a float in a numeric column, so the first statistics computed
over it came back with a median resistivity of −99999 ohm·m.

That is the harmless version. The dangerous one is the statistic that does
*not* look absurd — a mean over a column that is nine per cent sentinel comes
back plausible, low, and wrong, and nothing in the number says which.

**Agent capability:** before any statistic, ask a numeric column what its
extreme values are and whether they are physical. A resistivity cannot be
negative, a depth cannot be −99999, and a sentinel that violates the quantity's
own domain is detectable without knowing the file. This belongs beside A1 in
`docs/agent_validation_and_debugging.md`: the unit chain is falsifiable, and so
is the domain.

### F032 — Half of an asked-for convention check does not exist

The ERT plugin's UNVERIFIED note named two checks to write: the apparent
resistivity of a halfspace, and "an asymmetric array to catch a reversed
electrode order". The first is now written and passes to 0.24 per cent.

The second cannot be written as asked. The geometric factor

    K = 2*pi / (1/AM - 1/BM - 1/AN + 1/BN)

is *identically* unchanged when the current pair is exchanged with the
potential pair, and reciprocity leaves the measured resistance unchanged too.
`(A, B, M, N)` and `(M, N, A, B)` are therefore indistinguishable over any
earth, by any array, in principle — the same shape of result as case 1's
Groom–Bailey indeterminacy, where site gain and anisotropy are provably not
separable.

A probe for it was written first and **reported itself blind rather than
passing**, which is the behaviour a check must have when what it is asked to
see does not exist. What is observable is the swap *within* a pair: exchanging
A and B negates K, so the engine must negate the resistance with it. That is
what is checked, and it catches a reader that sorted a quadrupole or a file
whose columns are B, A, M, N.

**Agent capability:** when a convention check cannot be made to fail on the
error it names, establish whether that is a weak probe or a theorem before
strengthening the probe. Both look identical from a passing test.

### F034 — A model volume with a flat top over ground that is not

Every cell sat at minus its depth from a plane at zero, and the depth below
that plane was handed to an argument named `depth_below_ground_m`. The ground
inside the model's own 3 by 1.5 km box spans 195.4 to 273.4 m, with 36.2 m
between the fifth and ninety-fifth percentiles of `DTM_HEM` (219.0 and 255.2),
and a quarter of the box standing above the floodplain. The two figures are
different statistics and not a range: an earlier draft read "219 m to 273 m"
and called the gap 36, which is the fifth percentile against the maximum.

Nothing in the output said so. A volume on a plane renders, reports unit
shares, and is read as geology exactly like one that is not.

Fixing it is a geometry change and not a re-interpretation, and the check that
it is, is that the unit shares did not move: 9,063, 8,456, 53,303 and 37,178
cells before and after. Every rule in this model is depth-referenced except
`below the investigation depth`, which compares `cell_centres_m[:, 2]` against
an elevation — so draping the cells without moving that surface with them
would have put the floor of the claim at sea level under the bluff, and the
shares would have moved a long way.

**The five resistivity lines are still flat, and now it is on purpose.** Every
`.stg` carries a literal `0.00000E+00` for each electrode's y and z, and all
thirteen runs report `topography_applied=False`. `import_ert` now places each
line on the earth and measures the ground under it before reading a single
file:

| line | relief | of its 275 m | nearest DTM reading |
| --- | --- | --- | --- |
| Ellis_CW1 | 1.31 m | 0.5 % | 32 m |
| Edwd_CW3 | 1.57 m | 0.6 % | 59 m |
| SVP_CW6 | 1.93 m | 0.7 % | 114 m |
| SVP_S10 | 2.63 m | 1.0 % | 72 m |
| SVPDemo-Day | 1.92 m | 0.7 % | 78 m |

A floodplain, under one per cent, against an investigation depth of tens of
metres. Flat is fine, and now it is fine in the run rather than in this
paragraph.

The first version of this table read 1.81 to 2.62 m over 243 to 477 m,
because it sampled between the README's stated endpoints — and Ellis CW1's
stated endpoints are 477 m apart against a 275 m electrode line, which is the
one thing the release is already known to get wrong here. The lines are placed
from the stated midpoint and azimuth instead, which are the parts of the
statement that survive its own contradiction.

**Agent capability:** when correcting a frame, predict which results must not
change and check that they did not. A geometry fix that moves the answers is
either not a geometry fix or was not finished.

### F035 — The terrain shipped with the survey and nothing read it

The elevation was never missing. The measured file carries a `DTM` column for
every one of its 139,602 soundings, and the importer reads four columns —
`LINE`, `X`, `Y`, `LASER` — none of them that one. The contractor's own
inversion carries `DTM_HEM`, and its value is exactly `ELEVATION_28_TOP[0]`,
because the 28-layer product this case compares itself against is delivered
draped on the terrain. From that file this case read three columns: `X`, `Y`
and `DOI`.

So the reference product had already put the ground where the ground is, and
the comparison against it was made in a frame it does not use.

**Agent capability:** a release's column list is a statement about what the
survey measured. Reading four of ninety is a decision about the other
eighty-six, and it is one nothing here had ever been asked to justify. A12.

### F036 — A comment that described a construction nobody had written

`ERT_SITES` held five pairs of degrees under a paragraph ending *"the midpoint
and azimuth are used, the stated length is not"*. Nothing used them. The
dictionary was iterated for its keys, to find the directories; the coordinates
sat in the file unread from the day they were typed until A12 asked where the
ground was.

The audit counted it as a recorded choice regardless, because the comment
contains the word *used*. So the project's one number for how completely its
choices are written down — fifty-six of a hundred and three — included a
sentence that described no code at all.

**Agent capability:** an audit of comments measures whether something was
written down, not whether what was written is true. The two come apart most
easily in the present tense: a paragraph saying what the code *does* is a
claim, and claims are the thing this project checks everywhere except here.
A12, F055.
