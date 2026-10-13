# Gravity: received practice

What published practice says about gravity, for the agents to consult before and after an
inversion. Everything here is tier `received` (docs/lessons/README.md, Tiers): a paper, a textbook
or a standard says so, and none of it was measured on this project's data. A section may propose a
check; it does not gate a run until the check has been measured here. Every DOI below was resolved
against Crossref when this file was written.

## Remove the Earth tide and the meter drift before any reduction, and close every loop on a base station

Stage: A | Step: A4 | Methods: gravity

A relative gravimeter reading changes with time for two reasons that have nothing to do with the
ground. The solid Earth tide, produced by the Moon and the Sun, moves observed gravity by up to
about 0.3 mGal over a day, and it can be computed for any place and time from closed-form
expressions. Instrument drift, the slow creep of the meter's spring, cannot be computed and has to
be measured, which is why a survey is flown or walked in loops that start and end on a base station
and why the base is reoccupied every few hours.

The standard sequence is tide first, then drift: subtract the computed tide from every reading, then
fit the remaining change at the base (usually linearly in time within a loop) and remove it. The
closure of a loop, what is left at the base after both corrections, is the survey's own measure of
repeatability. It is a separate number from the misfit of any later model and it sets the floor for
the data uncertainty. A survey delivered as anomalies alone hides both steps; a tide left in the
data looks like a smooth, loop-long trend, and a tare (a sudden jump in the meter) looks like a step
between two neighbouring stations read on different loops.

**Check.** If the release carries reading times and base reoccupations, recompute the tide for each
reading, difference it against any tide column the file states, and report the loop closures; if
it carries only anomalies, record that tide and drift removal is asserted, not verifiable, and do
not set the data uncertainty below the stated closure.

**Sources.**
- Longman, I. M. (1959). Formulas for computing the tidal accelerations due to the moon and the sun. *Journal of Geophysical Research*, 64(12), 2351-2355. doi:10.1029/JZ064i012p02351
- Nowell, D. A. G. (1999). Gravity terrain corrections — an overview. *Journal of Applied Geophysics*, 42(2), 117-134. doi:10.1016/S0926-9851(99)00028-2
- Hinze, W. J., von Frese, R. R. B., & Saad, A. H. (2012). *Gravity and Magnetic Exploration: Principles, Practices, and Applications*. Cambridge University Press. doi:10.1017/CBO9780511843129

## State whether station heights are above the ellipsoid or the geoid, and reduce with the height that matches the normal gravity

Stage: A | Step: A14 | Methods: gravity

Normal gravity from the International Gravity Formula is the attraction of a reference ellipsoid,
so the height correction that accompanies it should use height above that same ellipsoid. For most
of the history of the method the only accurate height was the levelled elevation above the geoid
(mean sea level), and anomalies were computed with it. GPS delivers ellipsoidal height instead. The
two differ by the geoid undulation, which reaches tens of metres, and through the free-air gradient
of about 0.3086 mGal/m a 30 m undulation is roughly 9 mGal. Using the elevation where the ellipsoidal
height belongs leaves this difference in the anomaly, the term geodesists and geophysicists have
argued over as the indirect effect.

Because the geoid is smooth, the error is nearly constant across an exploration-scale survey, and
the North American standard notes that it matters for regional anomalies more than for local ones.
It stops being harmless when heights of both kinds are mixed in one dataset: stations positioned by
GPS and stations tied to levelled benchmarks then differ by the undulation, station by station, and
the inversion sees a step that looks like a density contrast. The revised North American standard
reduces on the ellipsoid and asks that such anomalies be labelled "ellipsoidal".

**Check.** Find the height column's declared datum (ellipsoid, a named geoid model, or a vertical
datum such as NAVD88). If it is unstated, compare the heights against a DEM on its own datum at a
few stations; an offset near the local geoid undulation identifies ellipsoidal heights. Refuse a
dataset whose heights come from two sources until both are on one surface.

**Sources.**
- Li, X., & Götze, H.-J. (2001). Ellipsoid, geoid, gravity, geodesy, and geophysics. *Geophysics*, 66(6), 1660-1668. doi:10.1190/1.1487109
- Hinze, W. J., Aiken, C., Brozena, J., Coakley, B., Dater, D., Flanagan, G., et al. (2005). New standards for reducing gravity data: The North American gravity database. *Geophysics*, 70(4), J25-J32. doi:10.1190/1.1988183
- Hackney, R. I., & Featherstone, W. E. (2003). Geodetic versus geophysical perspectives of the 'gravity anomaly'. *Geophysical Journal International*, 154(1), 35-43. doi:10.1046/j.1365-246X.2003.01941.x

## Reproduce the delivered anomaly from its principal facts before modelling it

Stage: A | Step: A10 | Methods: gravity

A "complete Bouguer anomaly" is not one quantity. It depends on which normal gravity formula was
used (the 1930 International formula, GRS67 or GRS80), whether the height correction is first- or
second-order, whether an atmospheric correction was applied, whether the Bouguer correction is an
infinite slab or a spherical cap to 166.7 km, the reduction density, and how far out terrain was
corrected. The revised North American standard fixes each of these: closed-form normal gravity on
the GRS80 ellipsoid, the atmospheric correction, a second-order height correction, a spherical-cap
Bouguer correction and terrain correction to 166.7 km, and a density of 2670 kg/m3.

Two anomaly columns computed under different conventions can differ by several mGal with a smooth
dependence on latitude and elevation, which an inversion will happily turn into structure. The
reduction density is the most consequential choice, because the Bouguer correction is about
0.112 mGal per metre at 2670 kg/m3 and a wrong density leaves an anomaly that tracks topography.

**Check.** Take five stations with observed gravity, latitude and height, recompute the anomaly
with the conventions the release declares, and difference it against the delivered column. A
residual that correlates with height points to the density or the height datum; one that
correlates with latitude points to the normal gravity formula.

**Sources.**
- Hinze, W. J., Aiken, C., Brozena, J., Coakley, B., Dater, D., Flanagan, G., et al. (2005). New standards for reducing gravity data: The North American gravity database. *Geophysics*, 70(4), J25-J32. doi:10.1190/1.1988183
- Nowell, D. A. G. (1999). Gravity terrain corrections — an overview. *Journal of Applied Geophysics*, 42(2), 117-134. doi:10.1016/S0926-9851(99)00028-2

## Carry terrain corrections far enough out and treat the ground nearest the station as the main error

Stage: A | Step: A12 | Methods: gravity

Hammer's zone chart took terrain corrections out to about 22 km, and many surveys still stop there.
Beyond about 22 km the correction depends on station height and on the curvature of the Earth, so
stations at different elevations are affected differently, and the standard now recommended is to
continue to 166.7 km together with the curvature (Bullard B) correction. Stopping short leaves an
error that grows with elevation difference within the survey: high stations drift relative to low
ones by an amount that looks like a regional gradient.

The largest and least predictable term is closest to the meter. The innermost zones, the first
tens to hundreds of metres, often make up a large part of the whole correction and change quickly
from one station to the next. A digital elevation model coarser than that neighbourhood misses it,
and small irregularities in the local ground can by themselves exceed 0.1 mGal. With GPS heights
now accurate to centimetres, the terrain correction rather than the elevation has become the
dominant error for many surveys.

**Check.** Read the release's stated terrain-correction radius and inner-zone method. Compare the
DEM cell size against the station spacing and report how much of each station's correction comes
from the cells nearest it; where relief within a few hundred metres is large, inflate that
station's uncertainty rather than trusting the stated repeatability.

**Sources.**
- Hammer, S. (1939). Terrain corrections for gravimeter stations. *Geophysics*, 4(3), 184-194. doi:10.1190/1.1440495
- Nowell, D. A. G. (1999). Gravity terrain corrections — an overview. *Journal of Applied Geophysics*, 42(2), 117-134. doi:10.1016/S0926-9851(99)00028-2
- Leaman, D. E. (1998). The gravity terrain correction - practical considerations. *Exploration Geophysics*, 29(3), 467-471. doi:10.1071/EG998467

## A reduction density estimated from the data holds only where density does not follow topography

Stage: A | Step: A11 | Methods: gravity

Nettleton's method picks the density that makes a Bouguer profile across a topographic feature
least correlated with the topography; Parasnis's version does the same by regressing the free-air
anomaly on the Bouguer-plus-terrain term over many stations and reading the density off the slope.
Both measure the effective density of the material that makes up the relief, not the density of
the rock the survey is aimed at.

Both assume that the true anomaly is independent of the topography. That fails whenever geology
shapes the landscape: a ridge held up by a dense dipping unit, a valley cut along a low-density
fault zone or filled with sediment, an escarpment at a lithological contact. The regression then
absorbs part of the geological signal into the density, returns a value that is wrong for the rest
of the survey, and leaves an anomaly partly flattened exactly where the target is.

**Check.** Compute the anomaly at the delivered density and at two others spanning the plausible
range (for example 2400 and 2800 kg/m3), and report which features of the map change. Fit a
Nettleton or Parasnis density separately over sub-areas with different geology; a spread larger
than a few hundred kg/m3 says the topography is correlated with density and a single data-derived
value should not be adopted.

**Sources.**
- Nettleton, L. L. (1939). Determination of density for reduction of gravimeter observations. *Geophysics*, 4(3), 176-183. doi:10.1190/1.1437088
- Parasnis, D. S. (1952). A study of rock densities in the English Midlands. *Geophysical Journal International*, 6(5), 252-271. doi:10.1111/j.1365-246X.1952.tb03013.x
- Hinze, W. J., von Frese, R. R. B., & Saad, A. H. (2012). *Gravity and Magnetic Exploration: Principles, Practices, and Applications*. Cambridge University Press. doi:10.1017/CBO9780511843129

## Regional-residual separation is an interpretive choice, so invert more than one residual

Stage: A | Step: A11 | Methods: gravity

Removing a regional field to isolate the anomaly of interest has no unique answer. Applied to the
same Bouguer data, spectral filtering, upward continuation and graphical smoothing give visibly
different residuals, and each of them depends on a parameter the analyst picks (the filter cut-off,
the continuation height, the hand-drawn trend). In one comparison over greenstone belts the three
residuals all correlated with geology qualitatively, but only one of them fitted known densities
well enough for quantitative modelling.

Whatever is taken out as regional is taken out of the model: the long wavelengths removed are
exactly the ones that carry the deep and broad sources, so the depth extent and the total mass of a
body recovered from a residual are partly decided by the separation. A polynomial regional fitted
over an area that contains the target also removes part of the target.

**Check.** Build at least two residuals with different methods or parameters, invert each with the
same settings, and report which features of the recovered model survive both. Report the regional
that was removed alongside the model, as a map, so the reader can see what was assumed away.

**Sources.**
- Gupta, V. K., & Ramani, N. (1980). Some aspects of regional-residual separation of gravity anomalies in a Precambrian terrain. *Geophysics*, 45(9), 1412-1426. doi:10.1190/1.1441130
- Nabighian, M. N., Ander, M. E., Grauch, V. J. S., Hansen, R. O., LaFehr, T. R., Li, Y., et al. (2005). Historical development of the gravity method in exploration. *Geophysics*, 70(6), 63ND-89ND. doi:10.1190/1.2133785

## A misfit concentrated at high or rugged stations is a reduction error before it is a body

Stage: B | Step: B3 | Methods: gravity

The standard error model for gravity is a per-station standard deviation built from reading
repeatability, height error through the free-air and Bouguer gradients, and terrain-correction
error. The last two are not random in space: they grow with elevation, relief and distance from the
nearest well-surveyed ground. A residual map that follows the topography, larger on summits and
steep slopes and in narrow valleys, therefore points first at the reduction: a wrong density, a
terrain correction truncated at 22 km, a missing inner zone, or a height on the wrong datum.

An inversion can always absorb such a residual with shallow density contrasts placed under the
offending stations, and it will converge to a healthy misfit while doing so. Those near-surface
features, correlated with relief, are the non-physical fix to watch for.

**Check.** Correlate the final residual, and separately the shallowest layer of the recovered model,
with station elevation and with local relief. A significant correlation sends the run back to the
reduction (density, terrain radius, inner zone, height datum) before any model parameter is changed.

**Sources.**
- Nowell, D. A. G. (1999). Gravity terrain corrections — an overview. *Journal of Applied Geophysics*, 42(2), 117-134. doi:10.1016/S0926-9851(99)00028-2
- Leaman, D. E. (1998). The gravity terrain correction - practical considerations. *Exploration Geophysics*, 29(3), 467-471. doi:10.1071/EG998467

## Gravity data do not determine depth, and depth weighting is a prior rather than a result

Stage: C | Step: C1 | Methods: gravity

Any gravity anomaly can be reproduced exactly by infinitely many density distributions, including
a thin layer at the surface; the data alone carry no depth information without an assumption about
the source. A minimum-structure inversion left to itself puts the density just under the stations,
because the kernels decay with depth and shallow cells fit the data most cheaply. The standard
remedy weights cells by a function of depth that approximately cancels the decay, of the form
(z + z0) raised to a power near -1 for gravity, where z0 depends on cell size and observation
height.

The weighting makes deep structure possible; it does not make it observed. The depth at which a
body appears is set jointly by the data and by the exponent and z0 chosen, and changing them moves
the body up or down while the misfit stays the same. A density model can say where the lateral
edges of a contrast are with some confidence; its depth extent and the amplitude of the contrast
trade off against each other.

**Check.** Rerun the inversion with the depth-weighting exponent changed by a factor of about 1.5
either way, and with a different reference model, and report the depth of each interpreted body in
every run. Read into the geological model only the depths that do not move.

**Sources.**
- Skeels, D. C. (1947). Ambiguity in gravity interpretation. *Geophysics*, 12(1), 43-56. doi:10.1190/1.1437295
- Li, Y., & Oldenburg, D. W. (1998). 3-D inversion of gravity data. *Geophysics*, 63(1), 109-119. doi:10.1190/1.1444302
- Blakely, R. J. (1995). *Potential Theory in Gravity and Magnetic Applications*. Cambridge University Press. doi:10.1017/CBO9780511549816

## Pad the grid before a Fourier-domain operation and extend the model beyond the data

Stage: A | Step: A7 | Methods: gravity

Fourier-domain operations used to prepare gravity data (upward continuation, derivatives,
regional filtering) treat the grid as periodic. A grid whose opposite edges do not match wraps
around, and the discontinuity produces ringing and spurious gradients along the borders that are
then read as anomalies. The standard practice is to remove a trend, extend the grid by padding
(filling smoothly toward a common value) and taper the edges
before transforming, and to discard the padded area afterwards.

The same edge problem appears in an inversion as sources outside the data area. Mass just beyond
the survey edge contributes a gradient to the edge stations; if the model domain stops at the data
edge, that gradient has to be explained by cells inside the survey, and dense or light artefacts
collect along the boundary.

**Check.** Before a transform, confirm the grid was detrended, padded and tapered, and compare the
result's border strip against its interior for amplitude. Before an inversion, confirm the model
extends beyond the outermost station by at least the depth of the deepest cell that will be
interpreted, and look for recovered contrasts that hug the domain boundary.

**Sources.**
- Blakely, R. J. (1995). *Potential Theory in Gravity and Magnetic Applications*. Cambridge University Press. doi:10.1017/CBO9780511549816

## Tie surveys to one datum through shared stations before merging them

Stage: A | Step: A8 | Methods: gravity

Gravity surveys from different years and contractors are routinely combined, and they rarely share
every convention: the absolute datum the base stations were tied to, the normal gravity formula,
the height datum, the reduction density, the terrain-correction radius. Revising the North American
database to one set of conventions changed anomaly values, mostly in their long wavelengths. Marine
data must be converted to a Bouguer anomaly before they can be joined to land data, and differences
in the terrain-correction radius alone are a source of mismatch between surveys that standardising
the radius removes.

A merged grid with a datum step in it shows a linear anomaly along the survey boundary, and an
inversion places a contact there.

**Check.** Find stations or grid cells common to both surveys, difference their anomalies, and
report the mean and spread of the difference. A mean offset with a small spread is a datum shift to
remove before merging; a difference that varies with elevation or latitude means the reductions
differ and the surveys must be re-reduced from principal facts rather than shifted.

**Sources.**
- Hinze, W. J., Aiken, C., Brozena, J., Coakley, B., Dater, D., Flanagan, G., et al. (2005). New standards for reducing gravity data: The North American gravity database. *Geophysics*, 70(4), J25-J32. doi:10.1190/1.1988183
- Nowell, D. A. G. (1999). Gravity terrain corrections — an overview. *Journal of Applied Geophysics*, 42(2), 117-134. doi:10.1016/S0926-9851(99)00028-2
