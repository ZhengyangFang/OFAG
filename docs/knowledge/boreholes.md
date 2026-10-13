# Boreholes: received practice

What published practice says about boreholes, for the agents to consult before and after an
inversion. Everything here is tier `received` (docs/lessons/README.md, Tiers): a paper, a textbook
or a standard says so, and none of it was measured on this project's data. A section may propose a
check; it does not gate a run until the check has been measured here. Every DOI below was resolved
against Crossref when this file was written.

## Name the depth reference of every depth column before turning depth into elevation

Stage: A | Step: A10 | Methods: boreholes

A logged depth is a distance along the hole from a reference point, and the reference is not always
the ground. Wireline and drilling depths in the petroleum and geothermal convention are measured
from the kelly bushing or the drill floor, which stands several metres above ground level on a
rotary rig; shallow water and engineering holes are usually measured from ground level or from the
top of the casing. The log heading is where the reference and its elevation are declared, and the
standard logging texts treat recording both as part of the log, not as an optional annotation.

Mixing references produces an offset that is constant within a hole and different between holes, so
it survives every internal consistency check. A formation top taken from a kelly-bushing depth and
subtracted from a ground-level elevation lands too deep by the rig height, and a set of such holes
produces an apparent dip or step in a surface that is only a mix of rigs. Driller's depth and
wireline depth are also two measurements of the same hole that differ by pipe and cable stretch, and
can disagree by metres in deep holes; neither is the ground truth for the other.

**Check.** For each hole, record the depth reference and its elevation from the header; where both a
reference elevation and a ground elevation are given, difference them and require the offset to be
the same one applied in the conversion. Refuse to convert depths whose reference is not stated, and
report the plausible offset (the rig height) as the bound on any elevation derived from them.

**Sources.**
- Ellis, D. V., & Singer, J. M. (2007). *Well Logging for Earth Scientists* (2nd ed.). Springer. doi:10.1007/978-1-4020-4602-5
- Keys, W. S. (1990). *Borehole geophysics applied to ground-water investigations*. U.S. Geological Survey Techniques of Water-Resources Investigations 02-E2. doi:10.3133/twri02E2
- Fitzgerald, P., & Pedersen, B. K. (2007). A technique for improving the accuracy of wireline depth measurements. *SPE Annual Technical Conference and Exhibition*, SPE-110318-MS. doi:10.2118/110318-MS

## Compute a deviated hole's path with minimum curvature from its survey, and carry its position uncertainty

Stage: A | Step: A3 | Methods: boreholes

Measured depth is along the hole; true vertical depth and horizontal position come only from a
deviation survey, a list of inclination and azimuth at stations down the hole. The industry standard
for turning stations into a path is the minimum curvature method, which fits a circular arc between
successive stations; the tangential method, which projects the collar or the last station straight
on, is biased and the bias accumulates with depth. A hole with only a collar orientation has no
survey at all, and its path beyond the collar is an assumption.

Every survey tool has errors, and the published error models show that the systematic terms, not
the random ones, dominate: they do not average out along the hole, so the lateral uncertainty of a
station grows roughly with measured depth. The arithmetic is unforgiving even without a formal model:
an inclination wrong by one degree over 500 m of hole moves the bottom by about 9 m, and by three
degrees by about 26 m, which is a whole cell in most near-surface meshes. Placing a logged contact
into a model cell therefore needs the hole's position uncertainty at that depth, not just its
nominal position.

**Check.** Build every trajectory by minimum curvature from station surveys. Where only a collar
orientation exists, compute the displacement at each logged contact for plus and minus one and three
degrees of inclination and azimuth error, and compare it with the model cell size; a contact whose
displacement exceeds a cell cannot pick a cell and should be carried as an interval.

**Sources.**
- Sawaryn, S. J., & Thorogood, J. L. (2005). A compendium of directional calculations based on the minimum curvature method. *SPE Drilling & Completion*, 20(1), 24–36. doi:10.2118/84246-PA
- Williamson, H. S. (2000). Accuracy prediction for directional measurement while drilling. *SPE Drilling & Completion*, 15(4), 221–233. doi:10.2118/67616-PA
- Wolff, C. J. M., & de Wardt, J. P. (1981). Borehole position uncertainty: analysis of measuring methods and derivation of systematic error model. *Journal of Petroleum Technology*, 33(12), 2338–2350. doi:10.2118/9223-PA

## State the vertical datum of every collar elevation, and never mix ellipsoidal and orthometric heights

Stage: A | Step: A8 | Methods: boreholes

A collar elevation is a number with a datum. Satellite positioning returns heights above the
reference ellipsoid; levelling, national vertical datums and most elevation models return
orthometric heights, above a geoid or an approximation of it. The two differ by the geoid
undulation, which is tens of metres over most continents and reaches about a hundred metres
globally, and which varies smoothly enough over a survey that the difference looks like a constant
offset rather than an error. Global radar elevation models such as SRTM are referenced to a geoid
model, not to the ellipsoid, and a regional bare-earth model is referenced to the national vertical
datum; neither matches a handheld or survey-grade GNSS height without conversion.

When some collars were surveyed by GNSS and others were read from an elevation model, the holes carry
two datums, and every contact elevation inherits the difference. The geophysical side has the same
exposure: a gravity or magnetic survey that reports ellipsoidal heights and a mesh draped on a
geoid-referenced elevation model disagree by the undulation at every station.

**Check.** Where a collar elevation is given, difference it against the elevation model at the
collar. A median difference near a constant of several metres or more, with scatter much smaller
than that constant, is a datum mismatch, and its size should be compared with the geoid undulation
at the site; scatter of a metre or two around zero is elevation-model noise. Record the datum of
each collar and of the model surface before any contact is placed.

**Sources.**
- Li, X., & Götze, H.-J. (2001). Ellipsoid, geoid, gravity, geodesy, and geophysics. *Geophysics*, 66(6), 1660–1668. doi:10.1190/1.1487109
- Farr, T. G., Rosen, P. A., Caro, E., Crippen, R., Duren, R., Hensley, S., et al. (2007). The Shuttle Radar Topography Mission. *Reviews of Geophysics*, 45(2). doi:10.1029/2005RG000183

## Depth-match core to log before either calibrates the other

Stage: A | Step: A8 | Methods: boreholes

Core depths are assigned by the driller from pipe tallies and core recovery; log depths come from
the wireline cable. The two are independent measurements and routinely disagree by a shift, and
incomplete recovery makes it worse, because the recovered material could have come from anywhere in
the cored run and its assigned depth is a convention, not a measurement. The
literature on core-log integration treats depth matching as a prior step, usually done by
correlating a property measured on both (natural gamma, density), because every subsequent
calibration between the two assumes the samples are from the same depth.

Skipping the match turns a depth error into a petrophysical error: a porosity-resistivity or
density-velocity cross-plot built from mismatched pairs has a weaker correlation and a biased slope,
and a lithology boundary taken from core and a log break taken from the wireline appear as two
contacts. Core and log also sample different volumes, a few centimetres against tens of centimetres
or more, so after the match the remaining scatter is partly scale, not error.

**Check.** Where a property exists on both core and log, cross-correlate them over a window of trial
shifts and report the best shift and its correlation. If the best shift is larger than the sampling
interval, apply it before any calibration, and record it so that contacts from core and from logs
are placed on the same depth scale.

**Sources.**
- Lovell, M. A., Harvey, P. K., Jackson, P. D., Brewer, T. S., Williamson, G., & Williams, C. G. (1998). Interpretation of core and log data: integration or calibration? *Geological Society, London, Special Publications*, 136(1), 39–51. doi:10.1144/GSL.SP.1998.136.01.05
- Kerzner, M. G. (1986). Depth matching: a pattern-matching problem. In *Image Processing in Well Log Analysis* (pp. 41–60). Springer. doi:10.1007/978-94-009-4670-5_5

## A logged contact is known only to within the sample interval and the tool's vertical resolution

Stage: A | Step: A14 | Methods: boreholes

A contact in a borehole log is where something changed in the record, and the record has a
resolution. A cuttings log bins material over the sample interval, commonly one to a few metres, and
cuttings from one depth reach the surface spread over time, so the depth resolution of a mud log is
coarser than its sample spacing and degrades further in deviated holes. A wireline tool averages over
its own vertical aperture, from tens of centimetres to more than a metre depending on the tool, and
places a sharp boundary on a ramp whose midpoint is the conventional pick. A core log is sharper but
is subject to the recovery and depth problems of the previous section.

Treating a pick as a point hides this, and the error reaches the model in two ways: a surface
interpolated between points appears more certain than the data allow, and a comparison between a
contact and a model interface can report a mismatch that is inside the pick's own uncertainty.
Perturbing input contact positions within their uncertainty and rebuilding the geological model
shows how far that uncertainty spreads into the model, and it is largest where interfaces are least
constrained by data.

**Check.** Give every contact a depth interval equal to the largest of the sample interval, the tool's
vertical resolution and any lag or depth-matching uncertainty, and carry it into the model. Report a
contact-to-model mismatch only when it exceeds that interval, and flag contacts whose interval spans
more than one model cell.

**Sources.**
- Naganawa, S., Suzuki, M., Ikeda, K., Inada, N., & Sato, R. (2020). Modeling cuttings lag distribution in directional drilling to evaluate depth resolution of mud logging. *SPE Drilling & Completion*, 36(1), 63–74. doi:10.2118/189615-PA
- Ellis, D. V., & Singer, J. M. (2007). *Well Logging for Earth Scientists* (2nd ed.). Springer. doi:10.1007/978-1-4020-4602-5
- Wellmann, J. F., & Regenauer-Lieb, K. (2012). Uncertainties have a meaning: information entropy as a quality measure for 3-D geological models. *Tectonophysics*, 526–529, 207–216. doi:10.1016/j.tecto.2011.05.001

## Upscale a log to the model's cell before comparing the two, and use the average the physics requires

Stage: C | Step: C1 | Methods: boreholes, ert, tdem, fdem, mt, seismic

A log samples the ground at centimetres to a metre; a geophysical cell is metres to tens of metres
thick and, after regularization, represents a smoothed average over more than that. Comparing a log
value with the cell it falls in compares two different quantities. The right average is not the
arithmetic mean. For a stack of layers, current flowing along the layers sees the thickness-weighted
arithmetic mean of conductivity (the longitudinal conductance), current flowing across them sees the
arithmetic mean of resistivity (the transverse resistance), and the two differ whenever the layers
differ. For elastic waves longer than the layering, the equivalent medium is the Backus average,
which is transversely isotropic even when every layer is isotropic.

So a finely layered interval looks anisotropic to any method whose wavelength or footprint exceeds
the layering, and a method that mainly senses horizontal current (inductive EM) and one that also
senses vertical current (galvanic DC) will recover different values from the same log. Point-scale
petrophysical relations applied to a smoothed tomogram are biased in a way that depends on the local
resolution, so the comparison should be made after the log has been brought to the model's support.

**Check.** For each model cell a hole crosses, compute the thickness-weighted arithmetic and harmonic
means of the logged resistivity (or the Backus average of the sonic and density logs) over the cell's
vertical extent. Compare the model value with both; if the two means differ by more than the model
error, the cell value is not defined without an anisotropy assumption and a single-number comparison
is not meaningful.

**Sources.**
- Maillet, R. (1947). The fundamental equations of electrical prospecting. *Geophysics*, 12(4), 529–556. doi:10.1190/1.1437342
- Backus, G. E. (1962). Long-wave elastic anisotropy produced by horizontal layering. *Journal of Geophysical Research*, 67(11), 4427–4440. doi:10.1029/JZ067i011p04427
- Christensen, N. B. (2000). Difficulties in determining electrical anisotropy in subsurface investigations. *Geophysical Prospecting*, 48(1), 1–19. doi:10.1046/j.1365-2478.2000.00174.x
- Day-Lewis, F. D., Singha, K., & Binley, A. M. (2005). Applying petrophysical models to radar travel time and electrical resistivity tomograms: resolution-dependent limitations. *Journal of Geophysical Research: Solid Earth*, 110(B8). doi:10.1029/2004JB003569

## Calibrate a petrophysical relation on the site's own rocks before using it to read a model

Stage: C | Step: none | Methods: boreholes, ert, tdem, fdem, mt

Archie's relation between formation resistivity, pore-water resistivity and porosity was fitted to
clean sandstones, and its exponents are empirical. Archie himself reported a cementation exponent
near 1.3 for unconsolidated sands and between about 1.8 and 2.0 for consolidated sandstones; later
work ties the exponent to the connectedness of the pore network and finds a wider range across rock
types. Clay and other surface-conducting minerals add a conduction path in parallel with the pore
water, and in shaly rocks or fresh water that path can dominate, so that Archie with default
constants attributes the extra conduction to the pore water and misreads clay as high porosity or
saline water.

The failure is silent: a converted porosity or salinity section looks as smooth and plausible as the
resistivity it came from, whatever constants were used. The same holds for any density-velocity,
susceptibility-magnetite or resistivity-clay relation carried over from another site or a textbook
table.

**Check.** Fit the relation's constants on this site's paired data (core or log porosity against log
resistivity with measured water resistivity, or the analogous pair for the property in question) and
report them with confidence intervals and the number of pairs. If the fitted relation has a
significant intercept at zero porosity or the residuals correlate with clay content, use a model with
a surface-conduction term instead of Archie's. Do not convert a model with textbook constants without
saying so beside the result.

**Sources.**
- Archie, G. E. (1942). The electrical resistivity log as an aid in determining some reservoir characteristics. *Transactions of the AIME*, 146(1), 54–62. doi:10.2118/942054-G
- Glover, P. W. J. (2016). Archie's law: a reappraisal. *Solid Earth*, 7(4), 1157–1169. doi:10.5194/se-7-1157-2016
- Waxman, M. H., & Smits, L. J. M. (1968). Electrical conductivities in oil-bearing shaly sands. *Society of Petroleum Engineers Journal*, 8(2), 107–122. doi:10.2118/1863-A

## Decide for each hole whether it constrains the inversion or tests it, and never let one hole do both

Stage: B | Step: B7 | Methods: boreholes, gravity, magnetic, ert, tdem, fdem, mt, seismic

A borehole can enter an inversion as a constraint (a fixed interface, a bound, a reference value, a
petrophysical class, a weight) or stand outside it as a test. Both are legitimate; using the same
hole for both is not, because agreement with information that was put in is guaranteed and says
nothing about the rest of the model. Agreement between a model and observations only ever confirms a
model to a degree, and it confirms nothing when the observation was an input. The use can be
indirect: a hole that set the reference density, chose the depth weighting, or labelled a cluster
has been used even if its values never appear as a constraint.

With few holes the choice is costly either way, and the standard remedy is leave-one-out: constrain
on all holes but one, predict the one left out, repeat for each hole, and report the prediction
errors. Those errors, not the fit at the constraining holes, measure how well the model predicts
ground away from the holes.

**Check.** Record a role for every hole (constraint or validation) and trace every input to the run
(reference model, bounds, weights, class values, cluster labels) back to the holes it came from.
Refuse to report agreement at a hole that appears in that trace. Where the holes are too few to
spare a held-out set, report leave-one-out prediction errors instead.

**Sources.**
- Oreskes, N., Shrader-Frechette, K., & Belitz, K. (1994). Verification, validation, and confirmation of numerical models in the earth sciences. *Science*, 263(5147), 641–646. doi:10.1126/science.263.5147.641
- Chilès, J.-P., & Delfiner, P. (2012). *Geostatistics: Modeling Spatial Uncertainty* (2nd ed.). Wiley. doi:10.1002/9781118136188

## Measure how the holes sample the area before reading their statistics as the area's

Stage: C | Step: C2 | Methods: boreholes

Holes are drilled where somebody wanted to know something: on a target, along a road, near an
earlier hole that found it. Their statistics are therefore not a random sample of the model volume.
A histogram of rock types or a mean property taken over clustered holes is weighted towards the
clusters, and geostatistics treats this as preferential sampling, corrected by declustering weights
that give each hole a share of the area it represents. Spatial correlation also sets a range beyond
which a hole says nothing about its surroundings, and the variogram of the holes is the measurement
of that range.

Skipping this gives class proportions, reference values and interpolated surfaces that describe the
drilled part of the area and are presented as describing all of it. The geophysical model is usually
consulted precisely away from the holes, where their weight should be smallest.

**Check.** Compute the distance from every model cell to its nearest hole, and report the fraction of
the model beyond the variogram range of the holes (or beyond the mean hole spacing where no variogram
can be fitted). Compute declustering weights before any hole statistic becomes a prior or a class
value, and report the statistic with and without them; a large difference means the holes are
clustered on what they were drilled for.

**Sources.**
- Chilès, J.-P., & Delfiner, P. (2012). *Geostatistics: Modeling Spatial Uncertainty* (2nd ed.). Wiley. doi:10.1002/9781118136188
- Oliver, M. A., & Webster, R. (2014). A tutorial guide to geostatistics: computing and modelling variograms and kriging. *Catena*, 113, 56–69. doi:10.1016/j.catena.2013.09.006
