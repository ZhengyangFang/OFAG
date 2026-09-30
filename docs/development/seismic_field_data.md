# Seismic field data used to exercise the SEG-Y importer

The elastic FWI plugin was built against a synthetic land line, which is the
right way to check that an inversion converges but says nothing about whether
the importer can read a file somebody else wrote. SEG-Y is a standard only in
outline: which header bytes hold the coordinates, whether the byte-71 scalar
multiplies or divides, what unit the numbers are in, and which traces are
recordings at all are decided by the contractor. A file OFAG produced itself
cannot test any of that.

## The dataset

A conventional multi-offset land record, which is what the FWI path actually
consumes.

| | |
| --- | --- |
| Survey | Soda Lake geothermal field, Churchill County, Nevada — 3D/3C vibroseis, 2010 |
| Source | AWS Open Data bucket `gdr-data-lake`, prefix `soda_lake/raw_seismic/2010/v1.0.0/` (no credentials) |
| Catalogue | DOE Geothermal Data Repository, submission 1655, doi:10.15121/2479167 |
| Licence | CC-BY 4.0 |
| Citation | N. Louie, J., Lu, C., & Monastero, F. (2010). *Soda Lake Geothermal: Raw 3D and 3C Seismic-Reflection Data from 2010 Survey* |
| Shape | 8,321 SEG-Y files, one per vibrator point, ~21 MB each (171 GB in total) |
| Files used | `F1000R1.SGY`, `F1001R1.SGY` — 2,602 and 2,695 traces, 2,000 samples, 2 ms, 4 s records |

One shot record per file is what makes this usable: two files are 43 MB and
already contain two source positions and about 1,700 live channels.

```powershell
curl -o data/imports/sodalake/F1000R1.SGY `
  https://gdr-data-lake.s3.amazonaws.com/soda_lake/raw_seismic/2010/v1.0.0/F1000R1.SGY
```

`data/imports/` is ignored by Git. Nothing in the test suite needs the file:
the tests it produced build their own SEG-Y with segyio and run offline.

## What the file does not tell you

Its textual header is the blank EBCDIC template — every field a contractor is
meant to fill in is empty, including `C 7 MEASUREMENT SYSTEM` and `C20 MAP
PROJECTION / ZONE ID / COORDINATE UNITS`. Trace byte 89 says `1`, which the
standard defines as "length", and the standard does not distinguish metres from
feet at that flag. So the file states no unit and no projection anywhere.

The coordinates turn out to be **decimetres of NAD83 / Nevada West (EPSG:32109)**.
That was established by projecting the field's known location into candidate
Nevada zones and matching: only 32109, divided by ten, lands within a few
kilometres. Byte 71 holds −1, so the scalar the file declares divides by one
and leaves you a factor of ten out. Nothing in the file is wrong — SEG-Y's
scalar carries a power of ten, not a unit, and a survey stored in decimetres is
perfectly legal — but no reader can recover metres from this file alone.

This is the concrete case OFAG's unit policy exists for, so the import states
it: `coordinate_unit: "dm"`, and the offsets come back at 22.6–2785.4 m over a
4.25 × 4.77 km patch, which is a vibroseis 3D patch.

## What it changed

**Auxiliary traces were being read as stations.** Each record carries one trace
with `TraceIdentificationCode` 6 or 8 and coordinates left at zero, because it
was never at a station — a sweep or timing channel. Folded into the geometry it
became a receiver at the map origin. On F1000R1 that meant a receiver count of
868 instead of 867, bounds pulled down to include (0, 0), and a largest offset
of 4,600,247 m instead of 2,785 m — which then tripped the implausible-offset
warning and sent the reader off to check byte positions that were correct all
along.

Worse, and invisibly: `SeismicPrepareService.extract()` fits the receiver line
by SVD to decide the 2D axis. One station four thousand kilometres away
dominates that fit, so the direction swings onto the bearing of the origin and
every channel's along-line position is projected onto the wrong axis. The line
length stays plausible, the positions stay monotonic, and they are all wrong.
An FWI run on that geometry would converge to a section of nowhere.

`positioned_traces()` in `services/segy_import.py` now excludes traces whose
coordinates are unset from the geometry, in both services, and the count is
reported as `unpositioned_trace_count` rather than silently dropped — a land
record has a handful, and hundreds would mean the byte mapping is wrong. The
saved geometry array keeps a row per trace, so a row index is still a trace
index. A role whose coordinates are zero on *every* trace is a different thing
and is left for the warning below to name.

**The record is 3C, and nothing says so.** Its 2,601 live traces are 3 × 867,
and the three blocks hold *identical* station coordinates. No trace header
distinguishes the components — `TraceNumber`, `cdp`, `offset` and a dozen other
candidates are all either constant or per-trace across the blocks — so the
component lives in the trace order alone, and contractors write both layouts
(all of one component and then the next, or each station's three together).

Read undeclared, a 2D elastic run would be handed three different physical
recordings at each point as if they were three stations, and asked to explain
all of them with one modelled component. It would converge. The section would
mean nothing. `_one_component()` in `services/seismic_prepare.py` therefore
refuses a shot whose stations hold more than one trace until the request states
`components` and `component_index`, and finds the chosen one by grouping on
position and counting occurrences in file order — which reads either layout
without having to be told which. `traces_per_station` on the imported dataset
is what tells the user there are three.

The same discovery showed that the workbench's selection step was rebuilding
the header mapping from the standard defaults rather than reusing what the
import was declared with. On a file stored in decimetres that is a factor of
ten between a summary the user approved and the geometry actually inverted, so
`ImportedSegyDataset` now echoes the byte positions and the unit back.

## A second file, which is not this

`PoroTomo_iDAS025_160318020917.sgy` (46 MB, NREL bucket `nrel-pds-porotomo`,
DOE GDR submission 860, CC-BY 4.0) was read first, and is DAS rather than a
shot gather: its channel position is a distance along a fibre, so `SourceX`
and `SourceY` are zero throughout and `GroupX`/`GroupY` hold one constant.
That exercises the header and scalar layer — the scalar is −100 and the
receiver lands at a real UTM position in the Brady field — but it contains no
offsets and cannot reach `extract()` or the FWI path at all. It is what
`_geometry_warning()` was written against, and it remains a useful case
precisely because it is a file the mapped bytes cannot describe:

- every coordinate is zero, so these bytes hold no geometry at all;
- the sources are zero and the receivers are not, so the offsets are measured
  from the origin;
- one source and one receiver serve every trace, so the bytes do not
  distinguish the channels;
- the largest offset exceeds 100 km, which is not an acquisition offset.

The warning is carried on `ImportedSegyDataset.geometry_warning` and shown
above the summary in the workbench. It stays a warning and not an error: the
numbers are what the file says, the import completes, and a survey whose
geometry lives in non-standard bytes is imported by pointing the byte fields at
them.

## Inverting it

Six shots in a ±70 m corridor at 122.5°, 28 channels over 1,810 m, demeaned,
band-limited 3–20 Hz and RMS-normalised per trace, on 10 m cells over a linear
gradient from 900 m/s with Vp/Vs 2.4 — chosen so the starting Rayleigh velocity
is about 345 m/s against the 335 m/s read off the gather. The ladder stops at
6 Hz because the plugin's own dispersion check refuses anything higher on 10 m
cells at these velocities, which is the same conclusion the 69 m offline
deviation reaches from the other direction: this line is not 2D above about
6 Hz.

Two defects came out of the attempt.

**Preprocessing was applied to the observed data only.** The first run sat at a
relative misfit of 0.9999998 for every iteration and moved nothing. With the
observations RMS-normalised to 1 and the synthetic left at the 2×10⁻⁷ a unit
Ricker produces on this grid, the residual *is* the data: 5×10⁶ apart, misfit
identically one, no gradient. The plugin's stage filter already low-passed both
sides for exactly this reason, and the preprocessing layer added one level up
had reintroduced the asymmetry. `ElasticFwiSpec.observed_preprocessing` now
carries the same declaration into the run and the plugin applies it to the
predicted data before the misfit. The misfit then moves: 2.06 → 0.48 over the
first stage.

**The solve left the region its own grid can represent.** The validator checks
the Courant and dispersion limits against the *starting* model, and the
inversion moves the model: the shear velocity walked from 375 m/s down through
305 to 178, at which point there are 2.2 cells per shear wavelength and the
wavefield is numerical dispersion. The misfit fell the whole way, because a
dispersive wavefield fits data too. `_bounds` now holds every iteration to the
same two conditions the run had to satisfy to start, with optional stated
bounds narrowing them further, and no cell may fall under √2 Vs and become a
fluid the free surface cannot handle.

## Against what other people got from the same data

Gao, Huang and Cladouhos (2020), *Three-dimensional seismic characterization
and imaging of the Soda Lake geothermal field*, [arXiv:2008.08003], inverted
this survey at Los Alamos. It is the right thing to check OFAG against, and it
settles the geometry outright.

| | Published | OFAG, read from the trace headers |
| --- | --- | --- |
| Common-shot gathers | 8,321 | 8,321 |
| Inline receiver interval | 67 m | 66.9 m (10–90%: 66.3–67.1) |
| Inline source interval | 33.5 m | 33.5–33.8 m between adjacent shots in the corridor |
| Receiver-line bearing | NW–SE, survey grid at 33.97° → ≈124° | 122.5°, in 5° histogram bins |
| Receiver-line interval | 167.5 m | clean to ±100 m, a neighbouring line enters by ±150 m |
| Coordinate frame | their Figure 2 spans X 773.5–780.5 km, Y 4531.5–4539 km | our shots land inside that frame |

So the decimetre scaling, the Nevada West projection and the corridor logic are
right, confirmed against numbers OFAG never saw while deriving them.

The inversions are not comparable, and the differences are the point:

| | Published | OFAG |
| --- | --- | --- |
| Data | Geokinetics-processed PP: ground roll **attenuated**, deconvolved, amplitude-corrected | raw field records, ground roll intact |
| Physics | acoustic, Vp and density | elastic, Vp and Vs |
| Starting model | Geokinetics MVA velocity model | a stated linear gradient |
| Extent | 3D, 603×603×255 at 10 m, 8,321 shots, to 2.5 km | 2D, 213×32 at 10 m, 6 shots, to 320 m |
| Misfit | correlation-based | envelope |
| Reduction | **1.000 → 0.725 over 13 iterations** | 2.06 → 0.13 over 30 |

A fifteen-fold drop next to their 27% is not a better result, it is a warning.
The functionals and normalisations differ, so the numbers do not compare at
all; and six shots on twenty-eight channels leave three orders of magnitude
more freedom to overfit than 8,321 gathers do. Their careful, bounded setup
getting 27% is a good indication of what a real reduction looks like here.

The comparison also corrected the starting model. Their model over the top
320 m runs about 1,300–1,800 m/s, against the 900–2,180 m/s used here: too slow
at the surface and far too steep. But raising Vp to 1,400 at Vp/Vs 2.4 gives a
Rayleigh velocity near 536 m/s, and the gather plainly shows 335 m/s. Both hold
only if Vp/Vs is about 3.8 — which is exactly what the companion 3C paper
reports, "a high near-surface VP/VS ratio which under-sampled shear-wave
energy". Three independent lines of evidence — their Vp model, their statement
about Vp/Vs, and a velocity read off our own gather — meet at Vp ≈ 1,400 m/s,
Vs ≈ 365 m/s. Their density, from Gardner's rule at that velocity, is
1,895 kg/m³ against the 1,900 guessed here.

There is no published Vs model from this survey to compare against: they
inverted acoustically and listed elastic multi-component inversion as future
work.

## What four runs of the same line settled

Each changes one thing, so what moved can be attributed.

| | starting model | depth | top stage | final misfit | Vp inside the published band | recovered Rayleigh |
| --- | --- | --- | --- | --- | --- | --- |
| v1 unbounded | ad-hoc 900 m/s, Vp/Vs 2.4 | 320 m | envelope | 0.133 | — | — |
| v1 bounded | same | 320 m | envelope | 0.210 | 46% | — |
| v2 | literature 1400 m/s, Vp/Vs 3.8 | 320 m | envelope | 0.150 | 94% | 404 m/s |
| v3 | same | **600 m** | envelope | 0.147 | 95% | 395 m/s |

The starting model is what decided the Vp agreement: 46% to 94% on the same
data, the same solver and a *worse* initial misfit. Nothing about the
inversion changed, only where it started, which is the ordinary lesson of FWI
stated in numbers.

Depth bought one specific thing and no more. The 2,100 m/s refraction the
gather shows arrives at 583 m under this gradient, and the 320 m model had
nowhere to put it; at 600 m the recovered median Vp passes 2,000 m/s at 480 m.
The misfit and the Vp agreement are unchanged, so the shallow section was
never being distorted by the missing refractor — it simply was not being
imaged.

Neither run fits the ground roll, which is the strongest thing in the record.
The recovered near-surface Vs implies a Rayleigh velocity of about 400 m/s
against the 335 m/s the gather plainly shows — and the *starting* model was
already at 339 m/s, so the inversion moved it away from the observation. That
is what a phase-blind misfit does: the envelope compares instantaneous
amplitude, a surface wave's velocity is a phase, and no amount of depth or
bounding changes that. It is why the misfit became a property of the stage.

### Why an L2 top stage did not rescue it

Making the misfit a property of the stage was the right change and it did not
help here, which is worth recording rather than quietly dropping. A fourth run
— same 600 m model, top stage L2 instead of envelope — recovered a model
indistinguishable from v3's: Vs medians of 451, 458, 421, 503, 541, 550 m/s
against v3's 451, 459, 423, 506, 536, 549.

The arithmetic says why. At the top stage the model's Rayleigh velocity is
about 415 m/s and the record's is 335, so over the 1,460 m of offset the two
arrivals are 0.84 s apart — **5.0 cycles at 6 Hz**, a median of 1.7 across all
traces, with only **14%** inside the half cycle where a waveform misfit can
find its way home. L2 was not given a chance; it landed in the nearest local
minimum, which is where it already was.

And the record window compounds it: 3 s over offsets to 1,460 m leaves the
335 m/s ground roll arriving at 4.36 s on the longest trace, so **11% of the
traces contain no ground roll at all**. The records are 4 s and we took 3.

The deeper point is that the starting model was *right* about this — Vs 368
gives a 339 m/s Rayleigh wave against the measured 335, a fifth of a cycle at
the far offset — and the envelope stages walked it 22% away before L2 ever
ran. A phase-blind functional is free to do that. Fixing it needs the shear
model constrained by the surface wave from the first stage, not the last, or
the ground roll muted and not pretended to.

`windowJudgement` in `seismicStability` now reports both numbers on the setup
page, from a ground-roll velocity the user reads off the gather and states.
Nothing derives it: a velocity taken from the data by the code that is about
to invert that data proves nothing.

### Removing what is not being inverted

Deciding not to invert the surface wave is not the same as being free of it.
Left in, it is still the strongest thing in the residual, and the arithmetic
above is what it does: the shear model chases an arrival the method cannot
represent and ends 22% away from the velocity the gather shows.

So the mute gained its other half. `MuteSpec` is one line through the gather at
`offset / velocity + delay`; which side survives is the field it is assigned
to. `top_mute` keeps what arrives after it, dropping the noise ahead of the
first break; `bottom_mute` keeps what arrives before it, dropping the ground
roll. Together they are a window that follows the offset, which is the only
kind that works — a flat time window either cuts the near traces or leaves the
far ones alone. The pair sums to one at every sample, so nothing is dropped
twice or kept twice.

Soda Lake's refraction moves out at about 2,100 m/s and its ground roll at 335,
so a tail mute at 800 m/s plus 0.15 s separates them at every offset rather
than at a chosen one. It is applied to the predicted data as well, like
everything else in the sequence.

Checked against the real gather, it removes the ground roll completely beyond
283 m of offset and leaves 27% of the record standing. Inside about 200 m it
keeps some, which is not a defect: at those offsets the refraction and the
surface wave have not yet separated in time and no window can take one without
the other.

The mute also does a second thing worth naming, because it comes from the
order of the sequence rather than from the mute itself. RMS normalisation runs
after it, so what is now normalised to unit energy is the muted trace — the
refraction. Before, the ground roll owned the trace's energy and the
normalisation scaled the refraction down towards nothing; the arrival the run
is actually trying to fit now carries full weight in the misfit.

### What the data can actually see

`POST /runs/sensitivity` runs one forward and one adjoint pass at the starting
model and reports how much the misfit moves per relative change in each
parameter — what the first iteration acts on. Through the same preprocessing,
the same first-stage band and the same functional the run would use, so the
answer is about this configuration rather than about the method.

| | vs / vp |
| --- | --- |
| ground roll in the window, amplitudes as recorded | 1380.6 |
| muted, amplitudes as recorded | 871.4 |
| ground roll in the window, RMS-normalised | 3.01 |
| muted, RMS-normalised | 19.09 |

Read carefully, because a first attempt at this measurement got it backwards.

This data is shear-dominated in every configuration tried. The tail mute
reduces that by about a third with the amplitudes left alone and not at all
once they are normalised — which makes sense: it keeps the ground roll inside
about 283 m of offset, and normalisation then gives those traces the same
weight as every other. **The mute does not take the shear signal away.**

What governs the balance is the trace normalisation, by three orders of
magnitude: 1380 to 3.01. Before it, the near traces are eighty times louder
than the far ones and their surface wave owns the misfit outright. That is a
larger effect than any of the physics choices around it, and it is a
preprocessing switch somebody ticks.

Only ratios within one configuration mean anything here. The absolute numbers
are in the misfit's own units and the normalisation changes their scale, so
they are not comparable down a column.

The first attempt at this was a script that applied the trace normalisation to
the synthetic data and the mute only to the observed — the exact asymmetry
`observed_preprocessing` exists to prevent, reintroduced by hand a few commits
after it was fixed. It reported the shear sensitivity collapsing 7.5-fold under
the mute, and the conclusion drawn from it, that the ground roll *was* the
shear signal, does not hold. It is the plainest argument for the probe being a
platform feature rather than something reached for ad hoc: the endpoint applies
one declaration to both sides and cannot make that mistake.

What does still hold is the diagnosis of the runs themselves. The recovered
shear model implies a 400 m/s Rayleigh wave against the 335 m/s the gather
shows, the starting model was already at 339, and the envelope stages moved it
away — a phase-blind functional acting on a signal that is plainly there. The
data sees Vs. The misfit was the wrong instrument for reading it.

## What is still not covered

Soda Lake is a 3D patch read one shot at a time, so the fixed-spread check in
`extract()` — which refuses a rolling spread — is exercised by synthetics only.
A 2D land line with a genuinely rolling spread would test it properly, and is
the same thing Phase F2 needs before SWEEP can be evaluated on anything but
synthetics.
