# Case 3 — the Granite Gravel Aquifer, Llano Uplift, central Texas

For source files, execution stages, and the manuscript figure mapping, use the
[reproduction guide](../reproducibility.md). The two runs that do not meet the
target fit, the unassigned model volume, and interpretation sensitivity remain
part of the result. The development history below is retained for the agent's
retrieval corpus and should not be read as a count of independent agent
discoveries.

Case 1's write-up is `docs/case1_forge.md` and case 2's is
`docs/case2_cedar_rapids.md`; the problems logged there (F001–F030, F031–F036, and
Stillwater's F058–F075) are not repeated here. This case's own are F037–F054, logged
at the end.

One release, `doi:10.5066/F72Z14G6`: two resistivity profiles, two seismic
refraction profiles, a transient sounding, four holes and a self-potential
survey, over 276 by 175 m of weathered Precambrian granite.

**Status: four inversions are done -- two resistivity profiles, SRT2
and the transient sounding -- and two of the four fit. The holes are read,
the crossing is compared, and a model is built in which two thirds of the
volume is deliberately unclaimed and the rest says which method paid for
it.**

## Why this site

Case 1 asked whether two electrical methods agreed and found, late, that they
could not: they were 3.7 km apart and shared no resolvable depth. Case 2 put
that question first and could answer it in depth but not laterally — five 275 m
lines inside a 4.5 km² airborne survey is not a lateral test.

Here the second seismic profile **crosses** both resistivity profiles. The
three lines run at three azimuths — ERT1 at 67°, ERT2 at 155°, SRT2 at 110° —
and SRT2 cuts across the other two, closing to **0.9 m of ERT1** at ERT1
x = 104 m and **0.4 m of ERT2** at ERT2 x = 64 m. Away from those crossings the
median separation is 16 to 18 m.

So the comparison this site supports is at two points, not along a line: at
each crossing the two physics sample the same column of ground. That is
narrower than "two methods over the same line" but better posed than either of
the first two cases managed — case 1's methods shared no resolvable depth at
all, and case 2's were near each other rather than on each other.

An earlier reading of this geometry took the 0.4 and 0.9 m closest approaches
for the separation of the lines and is corrected here; see F041.

## The data

| What | Source | Identifier |
| --- | --- | --- |
| Two resistivity profiles, two refraction profiles, one transient sounding, four holes and a self-potential survey, May 2017 – August 2018 | Ikard and others, 2019, USGS data release | 10.5066/F72Z14G6 |
| Terrain, 3DEP 1 m bare-earth lidar, tile 14 x55y340 | USGS 3DEP, project TX_Hurricane_2018_D18_SUPPLEMENTAL_DRRA | — (no 3DEP collection but Seamless 1 m has a DOI; [ScienceBase 619c3717](https://www.sciencebase.gov/catalog/item/619c3717d34eb622f6931b2b)) |

Not in this repository: fetched into `data/case3_Llano/`, which `.gitignore`
excludes. `SOURCES.tsv` beside the data records which delivered file became
which path. The terrain is not part of the release and is fetched separately
by `scripts/fetch_llano_dem.py`; it is here because the release's own
elevations are contour crossings that disagree with it by eight feet (F048,
F049).

What the release contains, and what this case uses:

| | |
| --- | --- |
| ERT1, ERT2 | 48 electrodes, 4 m spacing, 0–188 m, 243 Wenner–Schlumberger readings each |
| SRT2 | 24 geophones, 4 m spacing, 0-92 m; 4 shots, 96 first arrivals |
| TDEM | one sounding, `.usf` |
| Wells | one logged hole, one hydrograph, three PDFs |

The resistivity files are RES2DINV **general array** (type 11), which writes
each measurement's own four electrode positions rather than naming a scheme.
This table called them dipole-dipole until the geometries were classified:
all 486 readings have MN nested symmetrically inside AB, which is
Wenner–Schlumberger. The label was wrong in the write-up and nothing
downstream was, because nothing downstream reads the label — which is the
argument for the format.
That is the honest form of the format: the quadrupole travels with the datum,
so nothing has to be reconstructed from a midpoint and a separation. The reader
is `src/ofag/formats/res2dinv.py` and it refuses a file that names a scheme
rather than approximating one.

Both profiles parse 243 of 243 declared readings, with no non-positive
apparent resistivity in either. Median apparent resistivity is 140.4 and
175.6 Ω·m.

## Where the surface is — and the two answers the release gives

The release states the electrode elevations twice and the two disagree.

Each `.dat` carries a trailing topography block; `electrodes_xyz.txt` tabulates
the same forty-eight positions separately. For profile 1 the two hold the
**same forty-eight elevations against the same forty-eight positions in a
different order**. For profile 2 they are not even the same set — 32 distinct
values against 26. They differ by up to 1.83 and 2.44 m. Nothing in the release
marks this.

The data cannot choose between them. Inverting each way:

| | ERT1 χ² | ERT2 χ² |
| --- | --- | --- |
| `electrodes_xyz.txt` | 3.090 | 0.762 |
| the `.dat`'s own block | 3.165 | 0.846 |
| 3DEP 1 m lidar | 3.079 | 0.760 |
| flat, no topography at all | **3.074** | **0.747** |

The shape does choose. Measured as the scatter of the second difference along
the line, the separate table is 0.23 and 0.25 m against the embedded block's
1.35 and 1.99. The embedded block steps up to 2.4 m between electrodes 4 m
apart — a 60 per cent slope on a line whose whole fall is 5 per cent. That is
not terrain, so the separate table was used, and the choice was recorded in
the script with a reversal condition: *wrong if a third elevation source
appears.*

### A third source appeared, and it says both lists are wrong

Not merely coarse — **displaced**. Every elevation in the release, 96
electrodes and 48 geophones, is a whole number of feet from 938 to 970 with
965 missing altogether, so the vertical resolution is 0.3048 m and ERT1's
entire 1.83 m of relief is six steps of it (F048). But the quantisation is the
smaller problem.

Sampled at these same stations, **two independent USGS products agree with
each other to 6 cm and both sit 2.4 to 2.7 m above the release's table**:

| | relief on ERT1 | relief on ERT2 | offset from the table |
| --- | --- | --- | --- |
| the release's table | 1.83 m | 9.75 m | — |
| 3DEP 1 m bare-earth lidar | 1.10 m | 7.49 m | +2.38, +2.68 m |
| 3DEP 1/3 arc-second | 1.11 m | 7.42 m | +2.38, +2.72 m |

Two products that disagree with a third and not with each other is not a tie.
And 2.4 m is the same eight feet the release's own two lists differ by, which
is the most likely account of all three numbers at once. Detrended, the lidar
and the table still differ by 0.72 and 0.92 m rms on the resistivity lines
against 0.17 and 0.29 on the seismic ones — so the shape is wrong too, and
worse where the elevations were read for electrodes. F049.

**The lines are now inverted on the lidar.** The misfit barely moves on the
resistivity — 3.090 to 3.079 and 0.762 to 0.760, still above flat's 3.074 —
and moves usefully on the refraction, 0.532 to **0.499**, which is what a
method whose observable is a path length would do.

**Two things changed and only one of them is worth anything.** The 2.4 m is a
translation: every section moved down together, and so did the hole, which has
no collar elevation and is placed by depth below whatever ground the model
uses. Nothing about the section's relation to the borehole changed, and an
earlier draft of this paragraph claimed it did. What the translation buys is a
datum two independent products agree on instead of one displaced by eight
feet, which matters for publishing and for nothing else here.

The **shape** is the part that is not a translation. ERT2's relief goes from
9.75 m to 7.49 and the two surfaces differ by 0.92 m rms once the offset is
removed, so the geometry the inversion sees is genuinely different — and the
refraction's misfit is the evidence that the difference was worth having,
because a traveltime's observable is a path length and a resistivity's is
not.

The DEM is USGS 3DEP 1 m, tile 14 x55y340 of project
TX_Hurricane_2018_D18_SUPPLEMENTAL_DRRA, cropped to the survey plus 400 m and
read bilinear at each station. It is cited by its
[ScienceBase item](https://www.sciencebase.gov/catalog/item/619c3717d34eb622f6931b2b)
rather than by a DOI, because there is none: of the twelve 3DEP downloadable
collections exactly one, Seamless 1 m, carries a registered DOI
(`10.5066/P13LJKFS`), and it does not reach Llano. The project's selection
rule asks that every input be permanent, and its own tables already record a
source without a DOI by writing a dash — Stillwater does it for USGS I-797.
The ScienceBase item is the persistent handle here; the S3 key is a
convenience, since the staged elevation products are republished under dated
names. A13, F030.

### Topography is in the inversion, and not for the reason it was put there

It was switched on for the fit: profile 2 falls 9.75 m over its 188 m, and a
half-space geometric factor is about five per cent wrong on terrain, so the
relief looked like something that had to be modelled.

The table above says otherwise. **Flat is the best-fitting of the three
options on both profiles.** A 9.75 m fall over 188 m is nearly a plane, and a
tilted plane is nearly a rotated half-space — which is why the authors' own
RES2DINV settings asked for the end-to-end trend to be removed before
inverting. The relief is real and it buys nothing in misfit.

It stays on anyway, for the other reason: the section has to be compared with
the holes and with a seismic profile that crosses it, and both of those are at
real elevations. Topography here buys the geometry, not the misfit.

That reading survives the lidar and is sharpened by it. The fourth row of the
table is 3.079 against flat's 3.074, so a surface measured to a decimetre
still does not beat no surface at all — and it moved every section 2.4 m
vertically. A setting worth nothing in misfit and metres in position is a
setting whose rationale has to be the position. A11, A12.

## The inversions

Both profiles are inverted on **identical settings** — λ = 20, vertical weight
1.0, 12 iterations allowed, 40 m of parameter domain, a declared 5 per cent
relative error — and that is the point. Profile 2 fits and profile 1 does not,
and that difference is worth having only if it belongs to the ground. Tuning
profile 1 until it fits would buy a number and spend the comparison.

| | χ² | iterations | median residual | over 15 % |
| --- | --- | --- | --- | --- |
| ERT1 | **3.079** | 4 | 4.0 % | 17 / 243 |
| ERT2 | 0.760 | 4 | 3.0 % | 0 / 243 |

These are on the lidar surface, which is what the case runs on. On the
release's own elevations they were 3.090 and 0.762; the table in *Where the
surface is* is the comparison the move was decided by.

The declared 5 per cent is declared, not measured. This format carries none of
the three things case 2 could measure an error from: no per-reading error
column, no reciprocal pairs, no contact resistance. It is stated in the script
so a result can be read against it.

### What ERT1's misfit is

Not a spread. The median reading fits to 4.1 per cent, inside the declared
error; **17 of 243 readings** carry the χ². Attributing each failed reading to
its four electrodes and comparing against how often each electrode is used at
all, they fall in two groups: **x = 0–12 m** and **x = 64–76 m**. A contiguous
run of four electrodes is not contact failure, which hits electrodes one at a
time.

Three explanations were tested and none of them holds.

- **Not topography.** Flat fits marginally better (3.074), and the two
  elevation lists differ by 0.08 in χ².
- **Not the norm, but not for the reason this said.** It read that L1 on the
  model constraint moves the 5–15 m band by 1 Ω·m. That number was the gap
  between the two sections' *global maxima*, which sit at 33 m depth and
  x = 85 m — twenty metres below the band and outside the window the authors'
  912 Ω·m is read in. Scored at x = 48–76 m the norm nearly doubles the
  section: **151 → 263 Ω·m** at the median, **312 → 619** at the maximum, with
  χ² falling 3.079 → 2.703. It is a large change that still misses the bar of
  2, on the worst-fitting stretch of the line, so it is ruled out as the whole
  explanation and not as a factor. L1 on the data alone takes χ² to 4.65,
  which is what an outlier weight does to a structural misfit. Both stay in
  the plugin and neither is switched on. F052.
- **Not the smoothing strength.** From λ = 50 down to λ = 2 the misfit falls
  monotonically — 4.31, 3.09, 2.73, 2.49, 2.33 — and never reaches the bar,
  while the resistive body at x = 48–76 m only reaches 158 Ω·m against the
  authors' 912.

What is left is the 2D assumption: a compact body near x ≈ 64–76 m, off the
line or too small for a smooth section to hold.

**The seismic cannot test this.** SRT2 crosses ERT1 at x = 104 m, 30 to 40 m
away from the anomaly, and the x = 0–12 m group is 68 to 79 m from the nearest
geophone. Whatever is at x = 64–76 m on ERT1, this release has no second
measurement over it. That is a limit of the survey geometry and it is recorded
rather than worked around.

## What the authors' own sections can and cannot be used for

The release ships `ert1_published.dat` and `ert2_published.dat`, which are not
data files: they are the authors' inverted sections, as X-location, elevation
and log resistivity.

Compared band by band, **ERT2 agrees with ours within about 20 per cent at
every depth** — 63/69, 164/128, 251/243 Ω·m at 0–5, 5–15 and 15–30 m. ERT1
agrees in the top 5 m (40/46) and disagrees by a factor of two below it
(249/114), concentrated on the same x = 48–76 m stretch that carries the
misfit. The two disagreements are the same feature.

They cannot be used for more than that. Forward-modelling each published
section against the delivered readings gives χ² of 13–26 and a systematic 0.86
predicted-to-observed ratio on both lines — worse than our own models by a
factor of five. Both files are exactly 361 cells with 0–4 m irregular spacing,
which is a fixed plotting export rather than an inversion mesh. **A published
model deliverable is not necessarily forward-modellable, and a disagreement
found that way is not evidence.** This was attempted as a decisive test and
withdrawn as one.

## The refraction inversions

Refraction is the one method in these three cases whose **data** carries a
theorem. The traveltime from a source at A to a receiver at B equals the
traveltime from a source at B to a receiver at A, whatever lies between them.
Where a survey shot the reverse spread, the difference between such a pair is
measurement error and nothing else.

That is worth saying plainly because case 3's resistivity had no such thing.
Its files carry no per-reading error, no reciprocal pairs and no contact
resistance, so its five per cent is declared. The refraction error is
**measured**: 3.69 ms on SRT2 from six reciprocal pairs, taken as the median
pair difference over root two.

### What had to be thrown away, and how it was found

| | read | kept | why the rest went |
| --- | --- | --- | --- |
| SRT2 | 96 | 80 | 4 zero-offset, 14 defaulted |

**The 10.000 ms default.** Exactly that value, to the last decimal, appears 14
times in SRT2, always within a few stations of the
shot -- where the arrival is shortest and hardest to pick. Picks of 9.824 ms
sit beside it, so it is not an instrument floor; it is what the program wrote
when it had nothing to write. The reader reports repeated exact values and the
case names this one.

### The sections

| | chi squared | picks | error used | rays reached |
| --- | --- | --- | --- | --- |
| SRT2 | **0.499** | 80 | 3.69 ms, measured | 74 % of 514 cells |

The last column is the one a refraction result is usually reported without. A
tomography mesh is far larger than the rays crossing it and the inversion
returns a velocity for every cell regardless, so the run records how many
cells a ray actually reached and every reading below is taken over those cells
alone. With the lidar ground used consistently, the deepest ray-reached cell
is about 15.1 m below ground.

## What the two methods say where they cross

This is what the site was chosen for, and it is two points rather than a line
(F041). At each one an electrode and a geophone stand within a metre of each
other, so the two physics sample the same column of ground.

**SRT2 x = 40 m against ERT1 x = 104 m**, 0.9 m apart:

| depth | resistivity | velocity |
| --- | --- | --- |
| 0-2 m | 46.4 Ω·m | 847 m/s |
| 2-4 m | 51.5 | 875 |
| 4-6 m | 70.4 | 942 |
| 6-10 m | 94.8 | 953 |
| 10-15 m | 180.3 | 939 |

**SRT2 x = 52 m against ERT2 x = 64 m**, 0.4 m apart:

| depth | resistivity | velocity |
| --- | --- | --- |
| 0-2 m | 50.7 Ω·m | 922 m/s |
| 2-4 m | 57.0 | 987 |
| 4-6 m | 70.7 | 1082 |
| 6-10 m | 116.7 | 1111 |
| 10-15 m | 170.4 | 1071 |

The two crossings show the same trend: **resistivity rises roughly threefold
over the top 15 m while velocity rises much less and flattens after about
6 m**. Values below the ERT and ray coverage are not used to extend this
comparison to 25 m.

The methods do not resolve a common contact in their overlapping shallow
band. The slow refraction velocities are consistent with weathered material,
but the ray coverage stops near 15 m and cannot locate the deeper fresh-rock
surface. The rising resistivity is also compatible with a gradational
weathering profile. Neither section establishes the base of the aquifer.

The borehole cannot settle it either (F040): its refusal at 2.3 m is a cemented
horizon it drilled through, with soft aquifer below to at least 7.3 m.

### One shared surface

The release's two station tables put the ground at different elevations at
the crossings. The current section comparison samples the same lidar DEM at
all ERT and SRT stations, so those released table differences no longer enter
the depth registration. The survey positions are still separate measurements,
with closest separations of 0.9 and 0.4 m.

## The transient sounding

One sounding, a 100 by 100 m fixed loop, 67 gates from 18.1 microseconds to
4 milliseconds. It is the only method here that reaches past 30 m, and getting
it read at all took six corrections, because the file is the same format as
case 1's and almost none of the same file.

**Its turn-off is a thousand times too short.** `/RAMP_TIME` says 5.1e-9 s
for the 1.5 A sweeps and 2.7e-8 s for the 9.5 A ones. The loop is about
0.73 mH, so switching 1.5 A out of it takes microseconds at any transmitter
voltage, and the IX1D project for this same sounding holds 5.1 and 27
microseconds. Nothing failed on the declared value, because the only thing
that reads it is the rule that drops gates inside the turn-off: three times
5.1 nanoseconds is 15 picoseconds against a first gate at 6.81 microseconds,
so the rule ran, rejected nothing, and reported nothing. Corrected, it drops
the first four gates of sweep 1 -- 6.81 to 14.2 microseconds, all inside the
transient -- and the misfit moves from 10.1 to 10.2, which is the useful part
of the answer: those four gates were never what was wrong, and the rule that
should have excluded them had been disabled by a number nobody checked (F054).

**It places itself nowhere.** No `/LOCATION`, and no `/Z_DIRECTION` either.
Both are now parameters the caller must supply rather than defaults, for the
same reason in each case: a placeless sounding inverted into a section puts
the ground where nobody chose (F029), and a guessed z convention inverts the
negative of the ground while every number looks healthy (F001). The position
was recovered from the self-potential survey, which is gridded 0 to 100 m
inside the same loop and carries latitude and longitude at all 437 of its
stations; an affine fit places local (50, 50) to a median 1.4 m.

That put the loop centre **0.6 m from ERT2 at x = 60 m and 2.3 m from SRT2 at
x = 48 m** — the same ground as the crossing the other two methods already
share. Three methods on one column, which is what this case has that the
first two did not.

**It names its columns, and they are not the other file's columns.** Case 1's
dialect writes `TIME, VOLTAGE, QUALITY`; this one writes `INDEX, TIME,
VOLTAGE, ERROR_BAR`. Both declare the heading and the reader took positions,
so this file's index would have been read as a time and its voltage as a
quality flag. Columns are now read by the names the file gives them.

**It states its points once for the sounding**, above the first sweep, where
the other dialect states them per sweep. Both are checked now; neither is
assumed.

**It leaves the transmitter current in.** `VOLTAGE_UNITS: V/M2`, not V/Am²,
and the current is a per-sweep setting that this sounding varied from 1.5 to
9.5 amps. The five sweeps interleave in time, so stacked without dividing it
out they make a sawtooth — while each sweep on its own is a perfectly smooth
decay. Measured: the scatter of the merged decay's log-log slope falls from
504 to 30 when the current is divided out, and the median slope lands on −2.25
where a late-time layered decay wants −2.5. The service had refused anything
but V/Am² outright, which is the guard working; it now reads V/m² and divides
the current out, once, in the one place that knows both the unit and the sweep.

## The error that was in the file, and the one that was not

The file states an error bar per gate and it reaches **0.03 per cent** at the
early gates. Read as an accuracy that claims the ground is known to three
parts in ten thousand, and the first inversion returned a chi squared of
**12,714**: the model missed the early gates by 20 per cent while they claimed
0.06.

That bar is stacking repeatability inside one repetition rate. What it leaves
out is measurable here, because the five rates overlap in time: where two of
them measured within two per cent of the same moment, their disagreement is
gain, geometry, drift and the one-dimensional assumption together. Fifteen
such pairs differ by a median of 5.8 per cent, which over root two is
**4.1 per cent on a single reading**.

With the stated bar floored at that, the misfit falls to **10.2**. It is
reported rather than improved. The residual is 13 per cent where the sounding's
own rates disagree by 13 per cent at the ninetieth percentile, so the model
fits the data about as well as the data agrees with itself, and a smaller
number would take a better measurement rather than a better inversion (A4).

## What the sounding sees that nothing else does

| layer top depth | recovered resistivity |
| --- | --- |
| 0 m | 22.7 Ω·m |
| 3.42 m | 79.2 |
| 8.38 m | 433.8 |
| 15.61 m | 956.9 |
| 26.12 m | 1428.1 |
| 41.40 m | 1670.8 |

The resistivity lines rise but run out of coverage at roughly 16–19 m; the
refraction flattens near 1100 m/s. The sounding is the only method here with
values above 1000 Ω·m, from about 19 m down. Its recovered profile rises in
discrete layers and its χ² is 10.16. It supports a resistive increase with
depth, but it does not isolate a geological contact or establish a separate
shallow conductor.

## The holes, and what they explain

Borehole D is one unit from 0.30 m to 7.32 m: granite gravel, all of it. The
"augur refusal at 7.5-8.0 ft" is 2.13 to 2.44 m and is a hard horizon *inside*
it — the next rows switch to a smaller auger, note a colour change, and then
"broke through hard horizon, GGA soft and fast cutting" to 7.32 m (F040).

That horizon explains the refraction. The release's own metadata says the
seismic "may be subject to erroneous depths ... because of the presence of
**velocity inversions within the aquifer, which were confirmed by observation
and drilling in borehole D**". A refraction survey cannot see beneath a layer
slower than the one above it, so the flat 1100 m/s below 6 m is not a failure
to find bedrock — it is a survey that was stopped by a cemented layer two
metres down, and the authors knew it.

Well A's water table at 15.5 m is the only depth in this case that no
inversion produced.

## The model

Two units, two ways of not having one, and 195 by 195 m to 40 m at 5 m cells.

| | share | resolved by |
| --- | --- | --- |
| nothing measured here | **68.4 %** | no method in reach |
| Granite Gravel Aquifer, by ERT | 16.8 % | ERT1 and ERT2, a measured resistivity |
| Town Mountain Granite | 11.7 % | TDEM, one sounding |
| Granite Gravel Aquifer, by TDEM | 1.6 % | TDEM, beyond the lines |
| in the volume, out of reach | 1.5 % | no section within reach |

**Two thirds of the volume is unclaimed, and that is the model's main
result.** Two resistivity lines that cross cover an X, not an area, and they
resolve about 16 m of a 40 m box; a cell further than 25 m from a line or deeper
than the coverage supports has nothing over it, and the model says so rather
than interpolating across the corners. Panel b of `examples/Fig8.ipynb` draws
the difference at two depths: the claimed ground is half the area and a third of
the volume.

### Which method paid for which unit

The aquifer is split by what assigned it, not by anything about the rock.
About seventeen per cent is a **measured resistivity** from the two lines; under two per
cent is the sounding speaking for ground the lines do not reach.
That is the same unit with two different amounts of evidence behind it, and
collapsing them would hide which.

This is a correction rather than a refinement. The first version of this model
made the aquifer a bare remainder — everything the granite rule did not take —
so the resistivity lines set the footprint and assigned nothing, and 40 per
cent of the volume was labelled by a rule that had looked at no data. It also
built the footprint from both lines while handing the rules only ERT2, so
ground beside ERT1 was deep enough to label and had nothing to label it with.
Both are visible only because the remainder was given a name of its own; a
remainder called "Granite Gravel Aquifer" absorbs its own mistakes.

### Where two methods reach the same ground

Checked rather than assumed. At the ERT station 0.58 m from the sounding
centre, both sections are sampled below the same lidar ground:

| depth band | ERT median | TDEM median |
| --- | --- | --- |
| 0–2 m | 66.7 Ω·m | 23.6 Ω·m |
| 2–4 m | 69.5 | 31.5 |
| 4–6 m | 84.9 | 119.8 |
| 9–12 m | 212.1 | 433.8 |
| 12–16 m | 284.1 | 779.0 |
| 16–20 m | no ERT cell at this station | 956.9 |

Within the ERT coverage, the methods place the ground on the same side of
800 Ω·m at **12 of 12 one-metre depths**, but their values differ by a median
factor of **1.88**. That is evidence for the broad increase with depth, not
for a sharp contact. Below 16 m this ERT station has no model cell to check
the sounding. SRT2's velocity flattens near 1100 m/s at the crossings and
does not give an independent granite depth.

### What the granite top is

A declared cut at 800 Ω·m through a weathering profile, claimed no further
than 50 m from the sounding — half the transmitter loop's side. Nothing
resolves a contact: the sounding rises from about 23 Ω·m at the top to 434 at
10 m, then crosses 800 at the layer beginning 15.61 m and reaches 1288 at
25 m. The release's own name for the unit says why, since a
granite gravel weathered out of the granite beneath it is a gradation.

**No second method reaches the depth it is drawn at.** The resistivity lines
stop at about 16 m and never exceed 377 Ω·m anywhere; the refraction is flat from
6 m. The granite's 11.7 per cent rests on one column of one method, and the
reach of 50 m is the only thing standing between that column and a surface
drawn across the whole site.

### Terrain frame and interpretation sensitivity

`build_model` samples the 3DEP DEM at every model column and stores each cell's
elevation as ground minus depth. Cell elevations now run from about 248 to
300 m above the datum, rather than −39.5 to −0.5 m in a local depth frame.
The same DEM is used to turn both ERT sections into depth columns and to read
their coverage. The corrected frame changed the assigned shares above.

`imports/model_sensitivity.npz` contains 27 alternative assignments: granite
cutoffs of 600, 800 and 1000 Ω·m; sounding reaches of 25, 50 and 75 m; and
ERT coverage drops of 1.5, 2.0 and 2.5 decades. Its per-cell agreement with
the baseline measures **sensitivity to declared choices**, not a probability
of granite. Across these settings, 26,836 of 64,000 cells change label at
least once. No additional sounding or deep borehole here calibrates these
choices, so the granite top remains an interpretation of one sounding.

## Problems

### F037 — The release states the surface twice, and the two disagree

Two elevation lists for the same forty-eight electrodes: the `.dat`'s own
topography block and `electrodes_xyz.txt`. Profile 1's are the same values
permuted; profile 2's are different sets. Up to 2.44 m apart, unmarked.

A reader that silently took one would have put the section up to 2.4 m off
vertically — against the few metres of section the holes speak to, that is the
whole answer — and nobody would have known a choice was made. The reader now reads the
embedded block *because* the file has it, the import compares the two and
prints the disagreement, and the script records which is used and why.

The general rule: **where a release states the same quantity twice, read both
and difference them.** The second copy is free validation, and its absence
from the first copy's documentation is not evidence they agree.

### F038 — A published model is a plot export, not a forward-modellable model

`B7` says to compare against a model the inversion never saw. That was done
here, and the comparison was run the strong way: forward-model the authors'
published section and see whether it predicts the readings. It predicts them
at χ² 13–26 against our 0.8–2.5.

The conclusion drawn from that — that the authors' sections are inconsistent
with their own data — was wrong, and was withdrawn. Both files are 361 cells at
0–4 m irregular spacing: a plotting grid. Down-sampling a model for a figure
and then forward-modelling the figure does not test the inversion that produced
it.

**Before treating a held-out model as evidence, check that it is a model.** A
deliverable with a round, identical cell count on every line, and irregular
spacing, is an export. Band medians are what it supports; a forward response is
not.

### F039 — The reason a setting was switched on was not the reason that held

Topography was enabled on an argument — 9.75 m of relief over 188 m, a
geometric factor five per cent wrong on terrain — that sounded quantitative and
was never measured. Measured, flat fits *better* on both profiles.

The setting was right and the reason was wrong, which is the dangerous
combination: it would have been carried into the next case as a rule, and the
next case's relief might not be a plane. **A setting argued for on a number
should have that number measured**, especially when measuring it costs one more
run of something that already takes five seconds.

### F040 — The refusal depth is a hard horizon, not the base of weathering

`borehole_D_log.txt` records "augur refusal at 7.5-8.0 ft", and 2.3 m was
carried into this document twice as the depth a geophysical section would have
to match.

Reading the next two rows of the same table: they switch to a smaller auger,
note a colour change and "very hard GGA" from 8 to 9 ft, and then **"broke
through hard horizon. GGA soft and fast cutting"** from 9 to 24 ft. The
refusal is a cemented layer *inside* the granite gravel, with soft aquifer
below it to at least 7.3 m. It is not bedrock and it is not the weathering
front.

A depth quoted from a log has to come with the rows on either side of it.
Refusal is a statement about the rig, not about the geology.

### F041 — Closest approach is not the separation of two lines

The site was chosen on "SRT2 is within 0.4 to 0.9 m of both resistivity
profiles", and that number is real: it is the closest approach. The lines are
not parallel. SRT2 runs at 110° across ERT1 at 67° and ERT2 at 155°, and the
median geophone-to-electrode distance is 16 to 18 m.

The cost was a plan: ERT1's unexplained readings at x = 64–76 m were to be
tested against the seismic, and the seismic crosses ERT1 at x = 104 m. The
test does not exist.

This is case 1's finding arriving a third time — survey geometry answering a
question before the comparison is attempted — and the guard is the same one
case 2 adopted and this case did not run: **compute the distance from every
station of one survey to the nearest of the other, and report the
distribution, not its minimum.** A minimum over two crossing lines is always
small and says nothing.

### F042 — Two norms were added to the plugin and neither is used

`ERTRegularizationSpec` gained `blocky_model` and `robust_data`, L1 on the
model constraint and on the data, because the authors used both and because a
weathering front is exactly the sharp boundary L2 cannot place. Neither helped:
the 5–15 m band moved by 1 Ω·m.

They are kept, and this is the argument for keeping them. Establishing that the
norm is *not* the explanation required being able to change it, and a plugin
that can only do L2 cannot answer the question at all. The two are separate
switches on purpose, because `robust_data` makes an outlier tail stop counting
rather than stop existing, and a χ² that only reaches its target under it is
reporting down-weighted readings as though they had been explained.

### F043 — A picking program writes a default that looks like a measurement

Exactly 10.000 ms, 14 times in SRT2's pick file, always within a few
stations of the shot. It is positive, it is in range, it is the right order of
magnitude, and at 4 m offset it even implies a plausible 400 m/s. At 12 m
offset it implies 1200 and at zero offset it implies nothing at all.

The tell is exactness. Real picks in these files carry six decimals --
10.308642, 9.824417, 15.179698 -- and a value repeated to the last decimal
fourteen times is not fourteen measurements. This is A1's sentinel rule with
the sentinel chosen to be unremarkable: -99999 announces itself and 10.000
does not.

The reader reports every exactly repeated traveltime and refuses to name any
of them, because a genuine tie is possible. Naming is the case's job and the
case does it in one constant with the evidence beside it.

### F044 — Retired case-specific example

The unused refraction profile and its gather diagnosis were removed from this
case. The general earliest-arrival check remains in the reader and its tests.

### F045 — An artifact path that resolved against the wrong root

Every plugin in this project writes `relative_path` as the path from the
artifact root, which begins with the run id, and both import services build
the same string by hand. Two places did not: the resistivity plugin's mesh
artifact, and both of the refraction plugin's when it was first written,
wrote a bare filename.

A consumer resolving that against the artifact root looks in the root, finds
nothing, and -- worse, if anything had ever been written there -- finds
another run's mesh. It was caught by a probe that read the artifacts back
rather than by any test, because no test read an artifact by its declared
path. There is one now.

### F046 — The same format, and almost none of the same file

Case 1's `.usf` reader was written against sixty-eight files from one
instrument and read this one wrongly in five separate ways: column order,
where the point count is declared, whether the position is there at all,
whether the z convention is, and whether the transmitter current has been
divided out. Four of the five would have produced a number.

Only one was caught by a guard: the service refused a voltage unit it did not
recognise. The rest were caught by the file failing to parse, which is luck --
the column-order one in particular would have read an index as a time had the
row width happened to match.

The rule the reader now follows: **where a file declares something about
itself, read the declaration rather than the position.** The column heading,
the point count, the unit and the current are all written down in both
dialects. The reader had been treating four of them as a layout it already
knew (A3).

### F047 — An error bar divided by nothing

Dividing the transmitter current out of the voltage and not out of its error
bar leaves every gate claiming the current's worth of precision it no longer
has -- a factor of 9.5 on this survey's high-current sweeps.

It was caught by a test written for the normalisation itself, not by the
inversion, which simply reported a different chi squared and would have gone
on reporting it. A quantity and its uncertainty travel together or the pair is
wrong, and the place to assert that is where either one is scaled.

### F048 — An elevation that is a contour crossing, not a measurement

Every surface elevation in the release — 96 electrodes and 48 geophones over
four lines — is a whole number of feet, 938 to 970, with 965 absent
altogether. The vertical resolution is therefore 0.3048 m. On ERT1 that is one
sixth of the line's entire 1.83 m of relief: forty-eight electrodes standing
on seven contours.

| | relief | distinct | steps of relief |
| --- | --- | --- | --- |
| ERT1 | 1.83 m | 7 | **6** |
| ERT2 | 9.75 m | 32 | 32 |
| SRT2 | 3.35 m | 12 | 11 |

The column is headed `Surface_Elevation_meters_above_NAVD88` and the values
are honest metres. What the heading does not say is that they were read off a
contour interval, and nothing in the release says it either. This is also why
A11's measurement could come out the way it did — below a foot there was
nothing in the numbers to fit.

`refuse_unmeasured_terrain` now measures both numbers before any geometry is
built, and reports the quantum as a grid fit rather than as the smallest gap:
a release careful enough to interpolate one station between two contours is
the case that most needs catching, and it is the one a smallest-gap test
loses. A12.

### F049 — Two sources that disagree with a third, and not with each other

The release states the surface twice (F037) and both statements are wrong, not
merely coarse. Sampled at these same stations, USGS 3DEP 1 m bare-earth lidar
and the 1/3 arc-second DEM agree with each other to **6 cm** and both sit 2.4
to 2.7 m above the release's table, carrying three quarters of its relief.

Detrended, the lidar differs from the table by 0.72 and 0.92 m rms on the two
resistivity lines against 0.17 and 0.29 on the two seismic ones, so the shape
is wrong as well as the level — and worse on the lines whose elevations were
read for electrodes.

The displacement is 2.4 m, which is the same eight feet the release's own two
lists differ by. One arithmetic slip accounts for all three numbers.

The choice of list had been recorded with a reversal condition that read
*wrong if a third elevation source appears*. A third appeared and the record
was reversed rather than defended. That is the mechanism doing the only thing
it is for.

**Agent capability:** a tie between two internal sources is not a tie. Before
recording a judgement between two statements of the same quantity, ask whether
a third is obtainable — here it was a 3 MB window out of a public COG.

### F050 — A declared cutoff with eleven metres of lever on the answer

The resistivity's resolved depth is the deepest cell whose coverage is within
two decades of the best cell's. Two decades was a bare assignment with no
comment of its own, sharing a `#:` block with an unrelated constant, and it
sits on a steep slope:

| coverage drop | 1.5 | 2.0 | 2.5 | 3.0 |
| --- | --- | --- | --- | --- |
| ERT1 resolves to | 7.6 | **13.9** | 25.2 | 36.2 m |
| ERT2 resolves to | 7.1 | **17.2** | 32.5 | 42.6 m |

Half a decade is eleven metres of claimed aquifer. The model's headline share
for the resistivity is this constant as much as it is the data, and it was
found by noticing that the share moved when the surface changed — 18.1 to 15.6
per cent — and asking why a better elevation should shrink an aquifer. It
should not, and it did not: the reach is discretised and the cut is a cliff.

**Agent capability:** a constant that selects rather than scales needs its
sensitivity printed beside its value, not only its rationale. A11 asks for the
counterfactual of a setting being on or off; this asks for the gradient of one
that is neither.

## What is not done

- ERT1 does not fit (3.09) and the survey has no second measurement over the
  ground that carries its misfit. It is kept: the misfit is 17 readings at two
  short stretches, the median reading fits to 4.1 per cent, and the crossing
  the other methods use is at x = 104 m, far from both.
- The TDEM does not fit (10.1), at the level the data disagrees with itself.
- The self-potential survey, 441 stations with contact resistance at every
  one, is read only for its grid. It is the one dataset here with a measured
  quality index of its own.
- The three PDF driller's logs are not read.
- The figures are `examples/Fig2.ipynb`, whose survey-geometry panel places
  the Llano lines, plus `examples/Fig7.ipynb` and `examples/Fig8.ipynb`: the three inversions, the
  sounding, and where the model assigns classes. Drawing where every line is,
  in the figures these replaced, is what turned F041 from a number into
  something a reader can see.
