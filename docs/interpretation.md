# Building a geological model from finished inversions

`ofag.services.interpretation_service` turns separate inversions into one
labelled volume. It is **not** a joint inversion: the methods are solved apart
and read together, and every cell records which method decided it and how far
away that method's nearest measurement was.

Use it when you have two or more finished inversions over the same ground and
want a unit model out of them. Everything here came out of Utah FORGE (case 1),
and the numbers quoted as examples are that field's.

```python
from ofag.core.schemas import UnitRule, UnitRuleKind
from ofag.services.interpretation_service import InterpretationService, LayeredSection

service = InterpretationService()
```

## The four steps

### 1. Measure what each method resolved

```python
band = service.resolved_band(section, starting_values, threshold=0.1)
band.deepest_m          # 130.0 -- below this the layers never left their prior
band.describe()         # the decay, layer by layer
```

A 1D inversion that runs out of data does not say so. It returns the model it
started with, at full resolution, indistinguishable from ground. This compares
each layer against the starting model and reports the deepest one that actually
moved. **Do this before reading a layered section for anything**, and before
comparing two methods: in case 1 the TEM and the magnetotellurics appeared to
disagree by a factor of 21 at 180 m, and most of that was one method's prior
being compared with the other's data.

The threshold is in decades of `|log10(recovered / starting)|`. 0.1 is a factor
of 1.26 and is the default because it is roughly where the case's TEM departure
curve flattened.

### 2. Pick a contact

```python
picks = service.pick_contact(
    section, band_m=(20.0, band.deepest_m), minimum_slope=0.3, within=mask
)
picks.depth_m.size, picks.attempted     # 46 of 48
```

The sharpest step in the logged property, per station, inside the band. Set the
band from step 1, never by eye.

A station whose steepest step is gentler than `minimum_slope` **contributes
nothing** rather than contributing its band edge. That matters more than it
sounds: a pick made at the edge of a search window is the window, and a surface
fitted through a set of them is a flat contact that looks like geology.
`increasing=False` picks a drop instead of a rise.

### 3. Fit a surface, and let the data choose the estimator

```python
surface = service.fit_surface("cover base", picks, targets_m=cell_centres)
surface.report.estimator                 # 'smooth 1e+02'
surface.report.held_out_error            # 15.1 m
surface.report.candidates                # every candidate's score
surface.report.furthest_from_a_pick_m    # 3580.0
surface.predict(points)                  # defined everywhere
```

Six estimators — the picks' mean, a plane, nearest neighbour, and three
smoothing strengths — are scored by leave-one-out and the best wins. **The mean
is in the list on purpose.** An estimator that cannot beat a constant is not
adding spatial information, and in case 1 nearest neighbour did not: 28.1 m
against the mean's 26.1, while wearing a 1,500 m distance guard that made the
whole arrangement look careful (F027).

The fitted surface is defined everywhere and carries no guard. What makes that
honest is `furthest_from_a_pick_m`, which is the number to print beside it — a
distance measured after the fact, not a radius chosen in advance.

### 4. Assign units

```python
rules = (
    UnitRule(name="granitoid basement", source="gravity + 3D seismic + well 58-32",
             kind=UnitRuleKind.BELOW_SURFACE, surface="basement"),
    UnitRule(name="shallow conductor", source="TEM",
             kind=UnitRuleKind.ABOVE_SURFACE, surface="shallow"),
    UnitRule(name="intermediate conductor", source="MT",
             kind=UnitRuleKind.PROPERTY_THRESHOLD, section="mt", threshold=5.0,
             resolved_from_depth_m=105.0, reach_m=2_000.0),
    UnitRule(name="basin fill", source="gravity", kind=UnitRuleKind.REMAINDER),
)
model = service.assign_units(
    rules,
    cell_centres_m=centres, cell_volume_m3=volume,
    depth_below_ground_m=depth,
    surfaces={"basement": top_elevation, "shallow": base_depth},
    sections={"mt": mt_section},
)
model.unit                  # index into rules, -1 if nothing claimed it
model.source                # the deciding method, per cell
model.support_distance_m    # how far the nearest measurement was, or NaN
```

**Order is precedence and the first match wins**, so the order is a statement
about which evidence is harder. Put the seismic horizon before the
soundings-derived blanket: the other way round, a cover rule relabels
outcropping bedrock as cover, and the model still sums to 100 per cent.

`BELOW_SURFACE` takes an **elevation** per cell and `ABOVE_SURFACE` a **depth
below ground**. They are different quantities and named so deliberately — a
cell 1,600 m above sea level read as 1,600 m down produces a plausible model.

## What the report is for

```python
model.report.units[2].volume_share          # 0.044
model.report.units[2].beyond_reach_share    # 0.110
model.report.undecided_cells                # 0
```

Shares are **by volume**, never by cell count. On an octree the cells run 30 m
at the surface and hundreds of metres at depth, so counting them gives a thin
cover the same weight as the basement under it: 89.9 per cent against a true
69.1 in case 1 (F013, F026).

`beyond_reach_share` is the one to read twice. A `PROPERTY_THRESHOLD` rule with
a `reach_m` declines to judge cells too far from any station, and they fall
through to a later rule. That is the right behaviour and it is invisible: 11
per cent of case 1's volume is labelled "not the conductor" by a rule that
never looked at it. **Absence of evidence rendered as evidence of absence is
what this field exists to prevent.** Print it beside the shares.

`undecided_cells` should be zero whenever a `REMAINDER` rule is declared. If it
is not, a rule is silently dropping cells.

## Things worth not repeating

| | |
| --- | --- |
| Clip the model volume on **every** constant that defines it, horizontal and vertical (F026) | a share is always plausible, so a wrong one looks like a result |
| Score an estimator before guarding it (F027) | a guard bounds damage; it never says the estimator is worse than a constant |
| Derive a figure's numbers from this report, not from a second copy (F025) | a figure has no misfit |
| Check a layered section is not placeless before trusting its coordinates (F029) | a central-loop sounding's receiver offset is the origin for every station |

## What it does not do

It does not interpolate an implicit geological model — `GeologyService` and the
GemPy adapter do that, and its conventions are checked before it runs. GemPy is
the right tool for contacts at genuinely varying elevation and the wrong one
for a topography-conformable blanket, which it will render as a surface in
absolute elevation and thicken wherever the ground rises. Case 1's write-up has
the measurement.

It also does not decide the rules. Which method is competent at which depth is
the judgement the whole exercise rests on, and it is made from step 1's
measurements, in the case script, in the open.
