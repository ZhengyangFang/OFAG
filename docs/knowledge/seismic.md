# Seismic refraction: received practice

What published practice says about seismic refraction, for the agents to consult before and after
an inversion. Everything here is tier `received` (docs/lessons/README.md, Tiers): a paper, a
textbook or a standard says so, and none of it was measured on this project's data. A section may
propose a check; it does not gate a run until the check has been measured here. Every DOI below was
resolved against Crossref when this file was written.

## Estimate the picking error from reciprocal traveltimes before the first inversion

Stage: A | Step: A4 | Methods: seismic

A first-arrival time from a source at A to a receiver at B must equal the time from a source at B
to a receiver at A. Refraction interpretation has leaned on this since the reciprocal method, which
builds its depth estimates from forward and reverse shots tied together by the reciprocal time
between them. Zelt lists traveltime reciprocity alongside arrival picking and data uncertainty as
part of preparing refraction traveltimes for modelling, because it is the one error estimate that
needs no model: any difference between a reciprocal pair is picking, timing or geometry error.

Two patterns in the differences mean different things. A scatter centred on zero measures picking
precision, and its size is the natural floor for the pick uncertainties handed to the inversion. A
consistent offset for every pair involving one shot says that shot's timing or position is wrong,
and no pick uncertainty should be inflated to absorb it; the shot should be corrected or removed.

**Check.** Collect every source-receiver pair recorded in both directions, report the median and
spread of the reciprocal differences overall and the mean difference per shot, and flag any shot
whose mean departs from zero by more than the overall spread.

**Sources.**
- Hawkins, L. V. (1961). The reciprocal method of routine shallow seismic refraction investigations. *Geophysics*, 26(6), 806-819. doi:10.1190/1.1438961
- Zelt, C. A. (1999). Modelling strategies and model assessment for wide-angle seismic traveltime data. *Geophysical Journal International*, 139(1), 183-204. doi:10.1046/j.1365-246X.1999.00934.x

## Give every pick an uncertainty and judge the fit by a normalized misfit near one

Stage: B | Step: B4 | Methods: seismic

A traveltime inversion is only as honest as the uncertainties attached to the picks. Zelt makes
assigning them a requirement for inverse modelling, to avoid over- or under-fitting, and puts the
target at an overall normalized chi-squared misfit of one. An inversion driven below that is
fitting picking noise and will grow structure that is not in the ground; one that stops well above
it has either an inadequate model or uncertainties that are too small.

The pick uncertainty also dominates what the result is worth. Watts and co-workers propagated
survey and interpretation errors through the plus-minus method by Monte Carlo simulation and found
first-break pick accuracy the largest source of uncertainty in layer thickness, with the variance of
thickness growing roughly exponentially with pick uncertainty. They recommend reducing it at
acquisition, with more source energy and stacking, and reporting the resulting uncertainty with the
model.

**Check.** After a poor fit, report the misfit both as normalized chi-squared and as RMS
traveltime residual in milliseconds beside the reciprocal-difference spread; if the RMS residual is
near that spread while chi-squared is large, the uncertainties are the problem, not the model.

**Sources.**
- Zelt, C. A. (1999). Modelling strategies and model assessment for wide-angle seismic traveltime data. *Geophysical Journal International*, 139(1), 183-204. doi:10.1046/j.1365-246X.1999.00934.x
- Watts, H., Booth, A. D., Clark, R. A., & Reinardy, B. T. I. (2023). The sensitivity of seismic refraction velocity models to survey geometry errors, assessed using Monte Carlo analysis. *Journal of Applied Geophysics*, 208, 104888. doi:10.1016/j.jappgeo.2022.104888

## Carry geophone and shot positions, elevations and shot timing as measured inputs with their own errors

Stage: A | Step: A12 | Methods: seismic

The survey geometry enters every traveltime directly. The USGS guidance on refraction surveys has
the crew level and locate every geophone and shotpoint between shots, and record the elevation of
each, because the interpretation needs them. Zelt discusses crooked-line geometry as one of the
things a 2D model has to handle rather than ignore. Watts and co-workers included geophone
mislocation among the error sources in their Monte Carlo analysis and found that the combined
survey and interpretation errors act on layer thickness about a thousand times more strongly than
on velocity, so a geometry error that barely moves a velocity can move a depth appreciably.

Shot timing is part of the geometry. A trigger that fires late or early shifts every pick of that
shot by the same amount, which looks like a change in near-surface delay under that shot rather
than an error. Elevations that come from a different vertical datum from the one the terrain
model uses, or from a contour map rather than a survey, carry their error into every depth below
the line.

**Check.** Fit the direct-arrival picks of each shot against offset and report the intercept at
zero offset (it should be near zero); report the vertical datum and source of the elevations,
their relief along the line, and the horizontal offset of each geophone from the straight line the
2D model assumes.

**Sources.**
- Haeni, F. P. (1988). Application of seismic-refraction techniques to hydrologic studies. *U.S. Geological Survey Techniques of Water-Resources Investigations*, book 2, chapter D2. doi:10.3133/twri02D2
- Zelt, C. A. (1999). Modelling strategies and model assessment for wide-angle seismic traveltime data. *Geophysical Journal International*, 139(1), 183-204. doi:10.1046/j.1365-246X.1999.00934.x
- Watts, H., Booth, A. D., Clark, R. A., & Reinardy, B. T. I. (2023). The sensitivity of seismic refraction velocity models to survey geometry errors, assessed using Monte Carlo analysis. *Journal of Applied Geophysics*, 208, 104888. doi:10.1016/j.jappgeo.2022.104888

## Assume first arrivals can miss a thin layer and any layer slower than the one above it

Stage: C | Step: none | Methods: seismic

First arrivals only record layers that deliver a first arrival. Soske described the blind zone: an
intermediate layer between the surface layer and a fast marker that never appears as a first break
because of its thickness and the velocity contrast of the layer below, typically a water-table zone
above bedrock; he showed that allowing for it improved the agreement of refraction depths with core
drilling. Banerjee and Gupta showed that conventional interpretation fails to find an intermediate
layer that is slower than the beds above and below it, and also one that is faster than both, and
that in either case the depth to bedrock comes out wrong.

Tomography does not escape this. Sheehan, Doll and Mandell found refraction tomography better than
layer-based methods where the velocity varies by gradients, but in a blind test of eight inversion
algorithms on synthetic first-arrival data, Zelt and co-workers found that none of the fourteen models
recovered a subtle low-velocity zone, while all recovered the large bedrock offset and the top of a
steep low-velocity fault zone in smoothed form. A velocity that only increases with depth is what
first arrivals prefer to show, whether or not the ground has one.

**Check.** Before a depth to bedrock is used, check the borehole or other logs at the site for a
low-velocity or thin layer (a clay, a saturated zone, a weathered band under a harder cap), and
report the depth error that such a layer, at the thickness the logs allow, would introduce.

**Sources.**
- Soske, J. L. (1959). The blind zone problem in engineering geophysics. *Geophysics*, 24(2), 359-365. doi:10.1190/1.1438597
- Banerjee, B., & Gupta, S. K. (1975). Hidden layer problem in seismic refraction work. *Geophysical Prospecting*, 23(4), 642-652. doi:10.1111/j.1365-2478.1975.tb01550.x
- Sheehan, J. R., Doll, W. E., & Mandell, W. A. (2005). An evaluation of methods and available software for seismic refraction tomography analysis. *Journal of Environmental and Engineering Geophysics*, 10(1), 21-34. doi:10.2113/jeeg10.1.21
- Zelt, C. A., Haines, S., Powers, M. H., Sheehan, J., Rohdewald, S., Link, C., Hayashi, K., Zhao, D., Zhou, H., Burton, B. L., Petersen, U. K., Bonal, N. D., & Doll, W. E. (2013). Blind test of methods for obtaining 2-D near-surface seismic velocity models from first-arrival traveltimes. *Journal of Environmental and Engineering Geophysics*, 18(3), 183-194. doi:10.2113/jeeg18.3.183

## Read a tomogram only where rays pass, and do not take a checkerboard test as proof of resolution

Stage: C | Step: C1 | Methods: seismic

A traveltime tomogram has values in every cell, including cells no ray crosses; those values are
the starting model and the smoothing. Ray diagrams are the first appraisal, and Lanz, Maurer and
Green used them together with residual analysis, crossing-profile comparison, inversions from
different input models and bootstrap error analysis to judge a near-surface tomogram. Zelt and
co-workers used checkerboard tests to put the lateral resolution of a 3D refraction survey at 7.5
to 10 m, and still noted that the model was very smooth, particularly vertically, given the size of
the first Fresnel zone.

The standard tests can mislead. Lévěque, Rivera and Wittlinger showed that a checkerboard of small
cells can be well recovered while larger structures are poorly recovered, contrary to the usual
intuition, so a good checkerboard does not certify the scale being interpreted. And a gap in the
coverage is itself information: Flecha and co-workers note that rays avoid low-velocity bodies, so
such bodies are undersampled, and that low ray density in the coverage diagram can be evidence for
one. Masking unsampled cells is necessary; reading the mask as empty ground is a second mistake.

**Check.** Mask cells below a stated ray-coverage threshold before interpretation, run a recovery
test at the size of the feature being interpreted (not only a small checkerboard), and report any
coverage gap surrounded by covered cells as a candidate low-velocity body rather than as missing
data.

**Sources.**
- Lévěque, J.-J., Rivera, L., & Wittlinger, G. (1993). On the use of the checker-board test to assess the resolution of tomographic inversions. *Geophysical Journal International*, 115(1), 313-318. doi:10.1111/j.1365-246X.1993.tb05605.x
- Zelt, C. A., Azaria, A., & Levander, A. (2006). 3D seismic refraction traveltime tomography at a groundwater contamination site. *Geophysics*, 71(5), H67-H78. doi:10.1190/1.2258094
- Lanz, E., Maurer, H., & Green, A. G. (1998). Refraction tomography over a buried waste disposal site. *Geophysics*, 63(4), 1414-1433. doi:10.1190/1.1444443
- Flecha, I., Martí, D., Carbonell, R., Escuder-Viruete, J., & Pérez-Estaún, A. (2004). Imaging low-velocity anomalies with the aid of seismic tomography. *Tectonophysics*, 388(1-4), 225-238. doi:10.1016/j.tecto.2004.04.031

## Invert from more than one starting model and keep only the features they share

Stage: B | Step: B2 | Methods: seismic

Traveltime tomography is nonlinear: the rays depend on the model, so the answer depends on where
the iteration starts. Zelt treats the choice of starting model as part of the modelling strategy,
and argues that the best way to learn whether a feature is required by the data is to derive
alternative models that also fit the data satisfactorily; statistics, ray diagrams and resolution
kernels address the question only indirectly. Zelt and co-workers chose their preferred 3D model
only after systematically testing the free parameters of the inversion, the starting model among
them, and Lanz and co-workers included inversions with diverse input models among their reliability
tests.

A single inversion from a single start therefore cannot separate a feature of the ground from a
feature of the start. Where two starts that fit equally well disagree, the data do not decide, and
the region of disagreement should be treated like a region without coverage.

**Check.** Rerun the inversion from at least two starting models that differ materially (for
example two different vertical gradients, or a gradient and a layered model), to the same target
misfit, and report the difference between the final models in the region being interpreted.

**Sources.**
- Zelt, C. A. (1999). Modelling strategies and model assessment for wide-angle seismic traveltime data. *Geophysical Journal International*, 139(1), 183-204. doi:10.1046/j.1365-246X.1999.00934.x
- Zelt, C. A., Azaria, A., & Levander, A. (2006). 3D seismic refraction traveltime tomography at a groundwater contamination site. *Geophysics*, 71(5), H67-H78. doi:10.1190/1.2258094
- Lanz, E., Maurer, H., & Green, A. G. (1998). Refraction tomography over a buried waste disposal site. *Geophysics*, 63(4), 1414-1433. doi:10.1190/1.1444443

## Do not read velocity anisotropy as a change of material or a change of depth

Stage: C | Step: none | Methods: seismic

Thomsen observed that most bulk elastic media are weakly anisotropic and that some anisotropic effects matter in
exploration even when the anisotropy is weak. Refraction rays travel mostly horizontally, so a
refraction velocity in bedded or foliated ground is closer to the velocity along the fabric than
across it, while a depth is a vertical distance. Banik found that seismic depths to reflectors in
the North Sea were often larger than the depths in wells, traced the misfit to velocity anisotropy
in shales, and gave a correction; the same mismatch between the direction a velocity was measured
in and the direction it is used in applies to depths from refraction.

Anisotropy also varies with azimuth where the fabric is steep. Two refraction lines at different
azimuths over the same unit can then return different velocities that describe the same rock, and
a velocity change along a single line can follow a change in the orientation of the fabric rather
than a change of rock.

**Check.** Where lines of different azimuth cross, compare their velocities at the crossing by
depth; where the geology declares bedding or foliation, record its orientation relative to each
line, and where a borehole has a sonic log, compare its vertical velocity with the refraction
velocity of the same unit.

**Sources.**
- Thomsen, L. (1986). Weak elastic anisotropy. *Geophysics*, 51(10), 1954-1966. doi:10.1190/1.1442051
- Banik, N. C. (1984). Velocity anisotropy of shales and depth estimation in the North Sea basin. *Geophysics*, 49(9), 1411-1419. doi:10.1190/1.1441770

## Test a refraction interface against boreholes, and state which velocity was taken to be the interface

Stage: C | Step: none | Methods: seismic

The USGS guidance calls comparison with wells or test holes the best test of a refraction
interpretation, and falls back on the internal consistency of reversed shots only when none exist.
Lanz and co-workers found that even a well-appraised tomogram needed complementary geological and
geophysical data to tell velocity anomalies of the target from natural variation in the near
surface. Olona and co-workers characterized a weathered granite with refraction, surface waves and
ERT against a single reference borehole, and note that lateral heterogeneity of weathering makes
boreholes alone inadequate, which cuts both ways: one borehole does not calibrate a whole line.

A tomogram has no interfaces, only a smooth velocity field; the blind test of Zelt and co-workers
recovered a sharp bedrock offset only as a smooth expression of it. A bedrock surface drawn on a
tomogram is therefore the choice of one velocity contour, and its depth changes with that choice.
The borehole can say which contour matches the contact where the borehole is; it cannot say that
the same contour matches elsewhere.

**Check.** Report the velocity contour used as the interface, the depth to that contour at each
borehole beside the logged contact depth, and the depth range across the line between the
neighbouring contours (for example plus and minus 500 m/s); hold at least one borehole out of the
calibration where more than one exists.

**Sources.**
- Haeni, F. P. (1988). Application of seismic-refraction techniques to hydrologic studies. *U.S. Geological Survey Techniques of Water-Resources Investigations*, book 2, chapter D2. doi:10.3133/twri02D2
- Lanz, E., Maurer, H., & Green, A. G. (1998). Refraction tomography over a buried waste disposal site. *Geophysics*, 63(4), 1414-1433. doi:10.1190/1.1444443
- Olona, J., Pulgar, J. A., Fernández-Viejo, G., López-Fernández, C., & González-Cortina, J. M. (2010). Weathering variations in a granitic massif and related geotechnical properties through seismic and electrical resistivity methods. *Near Surface Geophysics*, 8(6), 585-599. doi:10.3997/1873-0604.2010043
- Zelt, C. A., Haines, S., Powers, M. H., Sheehan, J., Rohdewald, S., Link, C., Hayashi, K., Zhao, D., Zhou, H., Burton, B. L., Petersen, U. K., Bonal, N. D., & Doll, W. E. (2013). Blind test of methods for obtaining 2-D near-surface seismic velocity models from first-arrival traveltimes. *Journal of Environmental and Engineering Geophysics*, 18(3), 183-194. doi:10.2113/jeeg18.3.183
