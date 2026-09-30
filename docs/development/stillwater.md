# Case 1: the Stillwater Complex, Montana

A worked case on real, public data, and a log of what went wrong on the way.

The log is the point. Every entry is a place where the obvious reading of the
data is wrong, and where a person who did not stop to check would have produced
a plausible, wrong answer. Those are the capabilities the agent layer has to
have: not "run an inversion", but "notice that this file is not what it looks
like".

Each problem is recorded as what was observed, the number that establishes it,
why it is dangerous, and what an agent would have to do to catch it. A problem
with no measurement behind it is not in this list.

## The data

Every input has a permanent DOI. That is a hard selection rule, not a
preference: four of the sources consulted while choosing this case had already
disappeared, including the regional gravity database that the published study
of this very area cites as its own input.

**It selects the cases; it does not gate the software.** The rule exists
because a case is an argument and an argument whose data has gone dead cannot
be checked. It says nothing about what OFAG will read, and nothing about
anybody else's survey: data you collected yourself has no DOI and needs none.
What every input owes — ours and yours — is a recorded origin. For a published
source that is a resolvable identifier, with a dash where none exists, as
USGS I-797 has below. For your own it is where and when it was acquired and
who holds it, which is the same obligation answered by the only means there
is.

| What | Source | DOI |
| --- | --- | --- |
| Airborne EM and magnetics, May 2000 (v2.0, June 2020) | USGS | 10.5066/P92R4OL2 |
| Gravity, 168 stations, 2013/2014/2020 | USGS | 10.5066/P9X33770 |
| Digital drill core logs (v2.0, March 2026) | USGS | 10.5066/P9D66THM |
| Geologic map of the Stillwater Complex, 1:12,000 | USGS I-797 | — |
| Published 3D model for comparison | Finn et al., *Precambrian Research* 348 (2020) 105860 | 10.1016/j.precamres.2020.105860 |

Dead while choosing this case: `paces.geo.utep.edu` (the gravity database Finn
et al. cite, accessed by them 2017-04-20), `computation.geosci.xyz`,
`opendata.utah.gov` ("this domain has been decommissioned").

The repository carries the citations and not the bytes. The four releases
above come to about 1.3 GB, they already have an authoritative origin, and a
committed copy would be a second one that nothing keeps in step. Fetched into
`data/case1_Stillwater Complex/`, which `.gitignore` excludes for that reason.

## What the data can and cannot see

Measured from the files, not assumed.

| | Footprint | Sampling | Depth of investigation |
| --- | --- | --- | --- |
| DIGHEM EM | 45.1 × 23.2 km | 263 lines at 020°, 199 m apart, 1.6 m along line | median ~0 m, p90 10–18 m, max 60–190 m |
| Airborne magnetics | same | same, sensor 34 m above ground | no intrinsic limit; line spacing caps lateral resolution |
| Gravity | 100 × 105 km, 48 of 168 stations inside the airborne box | 1.65 km median nearest neighbour, 24 km largest gap | kilometres |
| Drill core | 35.6 × 13.3 km, all 30 holes inside the airborne box | — | median 71 m, 4 holes > 300 m, deepest 614 m |
| The target | ~2,240 km² buried | — | 7,000–12,000 m thick |

The EM sees tens of metres and the body is kilometres thick, which is why this
case drops the EM rather than forcing a joint inversion of instruments that are
not looking at the same thing.

## Problems

### F058 — The magnetic field is the total field, not an anomaly

`MAGDL` has a median of 55,762 nT and a standard deviation of 907 nT over
917,961 readings. That is the main field. The data dictionary says so —
"lagged diurnal corrected **total** magnetic field" — so the diurnal variation
has been removed and the IGRF has not.

Dangerous because the unit is right. OFAG's importer asks for a `tmi_column`
and a `tmi_unit`; nT is correct, and nothing in the unit policy notices that
the *quantity* is wrong by 55,000 nT. The unit travels with the value, as the
policy requires, and the value is still not what the field name implies.

**Agent capability:** check the quantity's plausible range against its declared
type, not only its unit. A total magnetic intensity *anomaly* whose mean is
within a few per cent of a plausible main field is almost certainly not an
anomaly.

**OFAG change:** the magnetic importer should raise this itself. This is the
first defect class 4 found in OFAG's own policy rather than in someone else's
file.

### F059 — There is no observation elevation

The survey carries `ALTBIRDM`, the height of the bird above ground (median
34 m), and no elevation. A potential-field forward model needs the observation
point in the same vertical frame as the mesh. Terrain relief across the survey
exceeds 1,000 m, so this is not a constant offset that cancels.

**Agent capability:** recognise that a required quantity is absent rather than
zero, and know that it can be derived — here from a DEM plus the height above
ground — rather than stopping or substituting a constant.

### F060 — The Banded series is reversely magnetised

Blakely and Zientek (1985), quoted by Finn et al.: the Banded series "is
reversely magnetized with a natural remanent magnetization intensity comparable
to the susceptibility". A Koenigsberger ratio near one, with the remanence
opposing the present field.

`MagneticsModelSpec` defaults to `lower_bound = 0.0`. Over reversely magnetised
ground an induced-only inversion with a non-negative bound cannot fit the data;
it will drive the model to the bound and report the residual as noise.

Finn et al. handled this by accepting that their recovered "susceptibility"
absorbs the remanence, and saying so. Matching that treatment is the honest
option; claiming to recover susceptibility is not.

**Agent capability:** connect a rock-property statement in the literature to a
numerical bound in a run specification, and qualify what the recovered quantity
means in the summary.

### F061 — The anomaly reaches 45% of the main field

Against a main field near 55,700 nT the anomaly runs from −4,399 to
+25,345 nT. 5.98% of readings exceed 1,000 nT, 0.75% exceed 5,000 nT, and
0.147% (1,346 readings) exceed 10,000 nT.

SimPEG's magnetic simulation is linear in susceptibility and neglects
self-demagnetisation, which is a good approximation while the induced field is
small against the inducing one. At 45% it is not obviously good.

**Agent capability:** check a method's validity domain against the data before
running it, and say which measurements fall outside it. Excluding them is a
decision that needs a reason; excluding them because the fit is poor is not
one.

### F062 — The sampling is strongly anisotropic

1.6 m along line, 199 m between lines. Lateral resolution is capped by the line
spacing, not by the along-line sampling: nothing finer than roughly 400 m
across strike is resolved, whatever the along-line density suggests.

Decimating along line to the line spacing is correct. Decimating *across* lines
aliases. Claiming resolution finer than the line spacing is unsupportable
however fine the model mesh is made.

**Agent capability:** derive the resolution limit from the acquisition geometry
and carry it into both the mesh choice and the claims made about the result.

### F063 — Drill depths are in feet

Every depth in the drill core release — collar total depth, and the `From` and
`To` of every logged interval — is in feet. The data dictionary states it for
each column. Nothing in the column names does.

Read as metres, a hole of 2,015 units becomes 2,015 m instead of 614 m, and
every logged contact is placed 3.28 times too deep.

**Agent capability:** read the data dictionary that ships with a release
instead of assuming SI, and refuse to import a depth whose unit has not been
stated. OFAG's `Borehole` already names its fields `_m`, which is what makes
the conversion a visible step rather than an invisible assumption.

### F064 — Drill collars have no elevation

Collars carry latitude and longitude and no elevation. As with F059, the
elevation has to come from a DEM. A contact logged at a depth below a collar
whose elevation is wrong is in the wrong place by that error.

### F065 — The boreholes can only validate the near surface

30 holes, spread over 35.6 × 13.3 km, all inside the airborne footprint, which
is better spatial coverage than expected. But the median depth is 71 m and the
median *vertical* penetration, after the inclination is accounted for, is 60 m.
Four holes exceed 300 m; the deepest reaches 614 m.

A magnetic inversion to 3–5 km cannot be validated by holes that reach 60 m. It
can be validated in the top hundred metres — which is where a survey flown 34 m
above ground with 199 m line spacing is most sensitive, so this is not a
worthless check, but it is a check on a small part of the model.

This has to be stated as a limit on the claim rather than discovered by a
reader.

**Agent capability:** judge whether the validation data can support the claim
being made, and bound the claim when it cannot. This is the capability that
distinguishes assistance from automation.

### F066 — Only 7 of 30 holes are vertical, and none is surveyed

Inclinations run from −34° to −90°; azimuths are given at the collar. There is
no downhole deviation survey, so the holes can only be placed on a straight
line from the collar.

OFAG represents this correctly: `Borehole.vertical` must be stated and a
`survey` overrides it, with the failure mode named on the type — "a hole
drilled at an angle and read as vertical places every contact too shallow and
too near the collar, and nothing downstream can tell". The straight-line
assumption stays explicit.

### F067 — The lithology tables are not all in one encoding

Four of the five are UTF-8 and `SWTR_JM_Reef_drill_logs_lithology.csv` is
Windows-1252. Nothing in the release declares this and pandas raises on byte
0x92, a right single quote, 30,909 bytes in.

Raising is the good case. A reader that falls back silently turns that quote
into mojibake, and because the rock name is the key that groups intervals into
units, one mangled name becomes one spurious unit.

**Agent capability:** treat encoding as something to detect and *report*, not
to guess quietly. The reader records which encoding it used for each file.

### F068 — Inclination is measured from the other end

The logs give inclination from horizontal with down negative: −90 is a hole
going straight down, −34 is a shallow one. OFAG's `BoreholeSurveyStation`
measures from vertical, so the same holes are 0 and 56.

Passing the number through is caught, because the schema refuses a negative
inclination. The dangerous case is the third convention: a release measuring
from horizontal with down *positive* would hand over 50, which is a legal
angle off vertical, and the hole would be placed twenty degrees wrong with
nothing raised anywhere.

So the reader requires the reference to be stated whenever an inclination is
mapped. Two of the three conventions are numerically indistinguishable, and a
field that only sometimes needs declaring is a field nobody declares.

**Agent capability:** recognise that an angle is meaningless without its
reference, and find the reference in the release's own documentation.

### F069 — A logged rock name can be a paragraph

Three of the hundred names exceed eighty characters, the longest being
"bronzite plagioclase cumulate/plagioclase cumulate/plagioclase bronzite
cumulate/bronzite cumulate". That is a description of an interval, not the name
of a unit in a pile, and `StratigraphicUnit.name` allows eighty characters
because eighty characters is a name.

Refused with a pointer to the unit map rather than truncated. Truncating would
have produced two units sharing their first eighty characters.

**Agent capability:** recognise that a vocabulary of a hundred petrographic
descriptions is not a stratigraphy, and that collapsing it is an interpretation
to state rather than a string operation to perform.

### F070 — The data uncertainty is not the instrument noise

The survey's own along-line fourth differences give 0.60 nT, which is a good
airborne magnetometer. Used as the data uncertainty, the inversion reached
chi-squared 6,291 and looked like a failure.

It was not. A 400 m mesh cannot produce a feature shorter than about twice its
cell, and this survey — flown 35 m above the ground — is full of them.
High-passing the observations at that scale leaves **451 nT RMS out of a total
of 801**: fifty-six per cent of the signal's amplitude sits at wavelengths this
parameterisation cannot represent, whatever the solver does.

With the uncertainty set to that measured floor the same inversion reaches
chi-squared 0.91 with a 428 nT residual. Nothing about the physics changed; the
first number was an answer to a different question.

**Agent capability:** set the uncertainty from what the chosen parameterisation
cannot represent, not from the instrument sheet — and measure it rather than
tune it until chi-squared comes out at one.

### F071 — A lithological log is not a stratigraphic log

`GeologicalModel.borehole_points()` turns every logged contact into a surface
point, which is right for a log that records a pile and wrong for one that
records rock types. This cumulate pile alternates at the metre scale: "Banded
series" is logged over a hundred times in a single hole, and every one of those
tops is a bedding contact inside a series rather than the base of the series
above it.

Handed to the interpolator as 419 surface points they described no surface at
all. The first model put younger intrusions through 53 per cent of the section
and left the Ultramafic series out of it entirely.

Collapsed to one interval per unit, from where it first appears downward, the
same holes give 38 contacts that do define surfaces.

**Agent capability:** tell a log that records a pile from one that records rock
types, and collapse the second before using it as geometry.

### F072 — A name cannot tell the Basal series from the Banded series

Thirteen of the sixteen holes that see more than one unit cross them in the
regional order downward: Banded series, Ultramafic series, metasedimentary
footwall. Three do not — the Crescent Creek holes collar in the Ultramafic
series and pass down into plagioclase-bearing rocks.

Regionally those would be the *Basal* series, which lies **below** the
ultramafics. A classifier working from rock names cannot tell it from the
Banded series: both are plagioclase-bearing, and what separates them is their
position relative to the ultramafics rather than their mineralogy.

Those four holes are dropped rather than reordered. Out of order means the pile
is wrong there, and interpolating through them would hide it.

**Agent capability:** notice when a classification that works on names
contradicts the geometry, and prefer dropping the contradiction to smoothing it.

### F073 — A library call with the wrong arguments returned plausible angles

`ppigrf.get_inclination_declination` takes the field's three components. Called
with a longitude, a latitude and a height it returns angles rather than
raising: here, **−1.1° inclination and −67.6° declination** — a nearly
horizontal field pointing west-north-west, where Montana's is **70.5° down and
13.9° east**.

The inversion ran to convergence on it. What gave it away was the recovered
model saturating at both bounds — 29 per cent of cells — because a solver given
the wrong field direction needs extreme values to fit anything. What confirmed
it was checking the two angles against where in the world the survey is.

With the field right: saturation zero, residual 450 → 428 nT, explained
variance 60 → 69 per cent, and convergence in three iterations instead of
twenty-five.

**Agent capability:** sanity-check a derived physical quantity against
independent knowledge of the place, not only against the function's own
success. This is the sharpest case in the log of a call that succeeds and is
wrong.

### F074 — A run started by a process that then exits is lost

`LocalProcessExecutor` dispatches a daemon child, so a caller that starts a run
and returns takes the run with it. The record then reads "the service stopped
while this run was executing", which is exactly what happened and reads like a
crash.

**Agent capability:** know that starting work is not the same as having it
done, and stay attached or poll — fire-and-forget loses the run.

### F075 — The reported misfit carries a factor of one half

SimPEG's `phi_data` is 0.5·Σ(r/σ)², so a reader computing chi-squared as
`phi_data / N` gets half the true value. Here that was 0.58 against a true
1.17 — the difference between "suspiciously overfitted" and "fits".

The ERT plugin reports `chi_squared` in its summary and the potential-field
plugins do not, so one project answers the same question two ways.

**Agent capability:** none, really — this one is OFAG's to fix. A summary that
reports an engine's internal objective without saying which convention it is in
invites the mistake.

## Withdrawn as a case, kept as evidence

This site is no longer one of the project's cases — those are Utah FORGE,
Cedar Rapids and the Llano Uplift. Its data directory was emptied, and
`scripts/case1_stillwater.py` and `scripts/case1_units.py` were deleted with
it: a case script whose release is gone cannot be run, and keeping it would
say otherwise. Both are recoverable from git history.

What this document is for now is F058–F075. Those eighteen recorded failures
stay in `docs/lessons/lessons.yaml` because they are real, they are what
procedures A1, A2 and A3 were generalised from, and the retrospective counts
them. This is the only record of the evidence behind them, which is why it
survives the case it describes. `ofag.agent.lessons` already treats the
missing directory correctly: it derives replayability from what is on disk,
so the six Stillwater judgements show up as un-replayable in the count rather
than as a silent gap.

What follows below was written while the case was live, and describes a
workflow that no longer exists.

Three services and two core modules exist because this case needed them:

| | Why |
| --- | --- |
| `ofag.formats.tables` | Rows from separated text, Excel and vector attribute tables, reporting the encoding and the CRS the file declares |
| `ofag.formats.raster` | Elevations from a GeoTIFF at given points, projecting them first |
| `ofag.core.crs.reproject` | Coordinates between systems, east-like argument first, a swap refused |
| `ofag.core.geomagnetism` | The reference field, and the three numbers an inversion needs from it |
| `ofag.services.borehole_import` | Drill core logs to `Borehole` records |
| `ofag.services.aeromagnetic_import` | A flown survey to anomaly observations at their true elevation |
| `ofag.services.import_store` | The one place that knows where an imported dataset goes |

## The result

**Import.** 919,297 readings to 9,589 observations at 201 m along 266 lines,
reduced from a total field of 56,094 nT to an anomaly of −3,167 to +13,871 nT,
observation elevations from a 3DEP DEM plus the bird's 35 m. Thirty drill holes
and 903 logged intervals, collars placed on the same DEM, depths converted from
feet, inclinations converted from dip-negative-down to angle-off-vertical.

**Inversion.** `simpeg.pf.magnetics3d` on a 400 m octree — 98,240 cells, 48,855
below topography — converged in three iterations.

| | |
| --- | --- |
| chi-squared | **0.91** |
| residual RMS | **428 nT**, against a 451 nT floor set by what the mesh cannot represent |
| explained variance | **69.0%** |
| recovered effective susceptibility | −0.161 to +0.280 SI, median +0.0003 |
| cells at a bound | **0** |

**Validation, against data that did not constrain the inversion.** The
recovered susceptibility at each of the thirty drill holes, grouped by the unit
logged there:

| Unit | Holes | Median effective susceptibility |
| --- | --- | --- |
| Ultramafic series | 12 | **+0.0120** |
| Banded series | 18 | **−0.0017** |

Mann-Whitney U = 206, one-sided p = **1.8 × 10⁻⁵**, over 216 hole pairs with 10
inversions. The ordering, the sign and the magnitude all agree with the
published rock properties: Blakely and Zientek measure ~0.0063 SI for the
Ultramafic series, and report the Banded series as reversely magnetised — which
in an induced-only parameterisation is exactly a negative effective
susceptibility.

**Geological model.** 26 of 30 holes are consistent with the regional pile; the
four at Crescent Creek are not and are dropped (F072). Their 903 lithological
intervals collapse to 38 stratigraphic contacts (F071), giving fitted attitudes
of 5.8° towards 209° for the Banded series and 1.1° towards 226° for the
Ultramafic series. GemPy interpolates them, and a 26.2 km section along the
line the holes lie on resolves 62% footwall, 37% Banded series, 0.7%
Ultramafic series.

## What this case does not support

Stated here rather than left for a reader to find.

**The geological model is thin.** Thirty-eight contact points over 23 km, from
holes with a median depth of 71 m, constrain the near-surface distribution of
the units and not a cross-section at depth. Cut through the centroid of the
collars rather than along them, the section was 89% basement — not because the
interpolation failed but because almost any box drawn around these holes is
mostly ground nothing constrains. The 0.7% Ultramafic series in the final
section is a thin band, and it is thin because the data says so.

**The dips are shallow and the holes disagree about them.** Fitted over all
holes the Banded series dips 5.8°; fitted within the four Picket Pin holes, over
3.6 km, it dips 38.4° with 8 m of scatter. The regional fit is an average of
local attitudes that differ, not a measurement of a regional one.

**The magnetic model is not unique.** A potential-field inversion never is.
What is defensible here is that it fits to within a measured floor, that it
saturates no bound, and that it separates two rock units it was never told
about. What is not defensible is reading structure from it below the depth the
data constrains, and nothing in this case establishes what that depth is — a
depth-of-investigation analysis is the obvious next thing and has not been done.

**The unit scheme is coarse and partly wrong.** Four units from a hundred
logged names, by a rule that reads mineralogy and cannot see position, so basal
norites are labelled Banded series (F072). A scheme built from depth context
rather than names would be better and is not what this case has.

**Remanence is not modelled.** It is absorbed into the recovered quantity,
which is therefore an effective susceptibility and not a susceptibility. Finn
et al. did the same and said so.

**The gravity was not used.** 168 stations with 48 inside the airborne
footprint cannot constrain a 3D model at this scale, and a joint inversion
would have implied they could.

## Status

Done: import, inversion, validation, geological model, all through OFAG's own
services with the case data outside the repository.

Not done: the depth of investigation; a section through the magnetic model
beside the geological one; the 1:12,000 geologic map, which is an ArcInfo e00
and needs converting; the 308 additional gravity stations in USGS OFR 85-209,
which are a scanned table.
