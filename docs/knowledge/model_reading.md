# Reading inversion results into a model: received practice

What published practice says about reading inversion results into a geological model, for the
agents to consult before and after an inversion. Everything here is tier `received`
(docs/lessons/README.md, Tiers): a paper, a textbook or a standard says so, and none of it was
measured on this project's data. A section may propose a check; it does not gate a run until the
check has been measured here. Every DOI below was resolved against Crossref when this file was
written.

## Read a regularized model as one member of a family that fits the data, and name what the regularization chose

Stage: C | Step: none | Methods: tdem, fdem, ert, mt, gravity, magnetic, seismic

Geophysical data are finite and noisy, so if one model fits them to within the errors, infinitely
many do. An inversion returns one of them because a regularization term picks it: the smoothest, the
closest to a reference model, the most compact. Occam-style inversion was designed to return the
smoothest model that fits, on the argument that any structure it shows is demanded by the data; the
converse does not hold, and the absence of a sharp boundary in a smooth model is a property of the
regularization, not evidence that the ground is gradational. Reviews of geological realism in
inversion make the same point from the other side: smoothness is a mathematical convenience and
rarely resembles the geology it is read as.

The practical consequence is that the features of a model divide into those every acceptable model
shares and those this regularization added. Interface depths, thicknesses and anomaly amplitudes
read off a single smooth model mix the two, and the mix is invisible in the picture.

**Check.** Invert the same data to the same target misfit under at least two materially different
regularizations (a different reference model, a different norm or smoothness weighting). Read into
the geological model only the features common to both, and report the spread between them as a
lower bound on the non-uniqueness of each feature used.

**Sources.**
- Constable, S. C., Parker, R. L., & Constable, C. G. (1987). Occam's inversion: a practical algorithm for generating smooth models from electromagnetic sounding data. *Geophysics*, 52(3), 289–300. doi:10.1190/1.1442303
- Backus, G., & Gilbert, F. (1968). The resolving power of gross earth data. *Geophysical Journal International*, 16(2), 169–205. doi:10.1111/j.1365-246X.1968.tb00216.x
- Linde, N., Renard, P., Mukerji, T., & Caers, J. (2015). Geological realism in hydrogeological and geophysical inverse modeling: a review. *Advances in Water Resources*, 86, 86–101. doi:10.1016/j.advwatres.2015.09.019

## Compute the depth of investigation from the data and the model, and interpret nothing below it

Stage: C | Step: C1 | Methods: tdem, fdem, ert, mt, gravity, magnetic

Below some depth the data stop constraining the model, and a regularized inversion fills that depth
with whatever the regularization prefers: the reference value, or a smooth continuation of the
shallower structure. Two appraisals are standard. The first inverts the data twice with different
reference models and marks where the results converge. The second, common in airborne and ground EM,
accumulates the data-weighted sensitivity of each cell from the bottom up and places the depth of
investigation where it crosses a threshold. Both depend on the data's noise and on the recovered
model itself, so a depth of investigation belongs to one model at one location and is not a survey
constant or a rule of thumb about a system's reach.

The thresholds in either method are conventions, so the two methods, and one method with two
thresholds, give different depths. Reading a basement surface, a base of aquifer or a conductor's
bottom from below any of them reads the prior.

**Check.** Compute a depth of investigation for every sounding or model column with the method the
engine supports, report the threshold used, and mask the model below it before any interface is
picked. Where two appraisals are available, report both and read only above the shallower.

**Sources.**
- Oldenburg, D. W., & Li, Y. (1999). Estimating depth of investigation in DC resistivity and IP surveys. *Geophysics*, 64(2), 403–416. doi:10.1190/1.1444545
- Christiansen, A. V., & Auken, E. (2012). A global measure for depth of investigation. *Geophysics*, 77(4), WB171–WB177. doi:10.1190/geo2011-0393.1

## Read an anomaly's size and amplitude through the point-spread function at its location

Stage: C | Step: C1 | Methods: tdem, fdem, ert, mt, gravity, magnetic, seismic

Every recovered cell value is a weighted average of the true model, and the weights are a row of the
model resolution matrix; the corresponding column, the point-spread function, shows how a point of
true structure is spread through the recovered model. Backus and Gilbert showed that resolution and
variance trade off: a narrower averaging kernel buys a noisier estimate. In practice the spread grows
with depth and away from sources and receivers, so the same true body is recovered larger, weaker and
displaced when it lies deeper or between lines, and a small strong body and a large weak one can
produce the same image.

Read without this, a model's anomaly boundaries become geological contacts, its amplitudes become
property values, and a smeared deep body becomes a thick unit. Resolution measures such as the
resolution radius of an electrical tomogram make the spread a number that can be compared with the
feature being interpreted.

**Check.** At each location where a feature will be read, compute the point-spread function, either
from the resolution matrix where it is affordable or by inverting synthetic data from a small
perturbation at that point with the same mesh, errors and regularization. Report its half-width and
the fraction of the input amplitude recovered, and do not interpret a feature smaller than the
half-width or an amplitude without that fraction beside it.

**Sources.**
- Backus, G., & Gilbert, F. (1968). The resolving power of gross earth data. *Geophysical Journal International*, 16(2), 169–205. doi:10.1111/j.1365-246X.1968.tb00216.x
- Alumbaugh, D. L., & Newman, G. A. (2000). Image appraisal for 2-D and 3-D electromagnetic inversion. *Geophysics*, 65(5), 1455–1467. doi:10.1190/1.1444834
- Friedel, S. (2003). Resolution, stability and efficiency of resistivity tomography estimated from a generalized inverse approach. *Geophysical Journal International*, 153(2), 305–316. doi:10.1046/j.1365-246X.2003.01890.x

## Compare models from different methods at a common resolution, not cell by cell

Stage: C | Step: C1 | Methods: tdem, fdem, ert, mt, gravity, magnetic, seismic, boreholes

Two methods imaging the same ground have different sensitivity kernels, so each recovered model is a
different blur of the same truth, and the blur varies differently in space for each. A seismic
velocity model and a resistivity model placed on one mesh are therefore not two measurements of the
same cell. Work on tomograms shows that the correlation between two recovered properties is weaker
than the true correlation and biased in a way that depends on each method's local resolution, and
that spatial statistics such as variograms estimated from a tomogram differ from those of the ground.

The consequences are a spurious disagreement where one method resolves and the other does not, and
petrophysical relations fitted to co-located model values that describe the two resolutions rather
than the rocks. Field-scale relations can be recovered, but by simulating the survey and inversion on
models that obey a known point-scale relation, not by cross-plotting two inverted models.

**Check.** Before a cell-by-cell comparison or cross-plot of two models, bring them to a common
support: smooth the sharper model with the other's point-spread function, or forward-model each
model through the other method's acquisition and inversion. Otherwise compare only band or zone
medians over volumes larger than both methods' resolution, and report which was done.

**Sources.**
- Day-Lewis, F. D., Singha, K., & Binley, A. M. (2005). Applying petrophysical models to radar travel time and electrical resistivity tomograms: resolution-dependent limitations. *Journal of Geophysical Research: Solid Earth*, 110(B8). doi:10.1029/2004JB003569
- Day-Lewis, F. D., & Lane, J. W. (2004). Assessing the resolution-dependent utility of tomograms for geostatistics. *Geophysical Research Letters*, 31(7). doi:10.1029/2004GL019617
- Moysey, S., Singha, K., & Knight, R. (2005). A framework for inferring field-scale rock physics relationships through numerical simulation. *Geophysical Research Letters*, 32(8). doi:10.1029/2004GL022152

## A joint inversion's agreement between methods is the coupling assumption, not independent confirmation

Stage: C | Step: none | Methods: tdem, fdem, ert, mt, gravity, magnetic, seismic

Methods can be combined at three levels. Separate inversions are read side by side. Cooperative
inversion passes information sequentially, for example using one method's interfaces as the other's
starting model or constraint. Joint inversion fits all data at once under a coupling term, either
petrophysical (an assumed relation between the properties) or structural (shared boundaries, as with
curvature-based or cross-gradient coupling, which requires the property gradients to be parallel).
Joint inversion can reduce non-uniqueness substantially, and published comparisons show sharper and
more consistent images than separate inversions give.

What it cannot do is test its own coupling. Structural coupling makes the two models share
boundaries whether or not the ground does; petrophysical coupling makes them obey the relation that
was imposed. Two jointly inverted models that agree are therefore not two lines of evidence, and a
boundary that one method sees and the other cannot resolve is transferred into the second model
without the second data asking for it.

**Check.** Whenever a joint or cooperative result is read into the geological model, also run the
separate inversions and report where the joint model departs from each. Test the coupling on the
separate models before adopting it (for structural coupling, where their gradients are parallel; for
petrophysical coupling, whether their co-located values follow the assumed relation) and treat a
feature that appears only in the joint result as coming from the coupling.

**Sources.**
- Lines, L. R., Schultz, A. K., & Treitel, S. (1988). Cooperative inversion of geophysical data. *Geophysics*, 53(1), 8–20. doi:10.1190/1.1442403
- Haber, E., & Oldenburg, D. (1997). Joint inversion: a structural approach. *Inverse Problems*, 13(1), 63–77. doi:10.1088/0266-5611/13/1/006
- Gallardo, L. A., & Meju, M. A. (2003). Characterization of heterogeneous near-surface materials by joint 2D inversion of dc resistivity and seismic data. *Geophysical Research Letters*, 30(13). doi:10.1029/2003GL017370
- Linde, N., Binley, A., Tryggvason, A., Pedersen, L. B., & Revil, A. (2006). Improved hydrogeophysical characterization using joint inversion of cross-hole electrical resistance and ground-penetrating radar traveltime data. *Water Resources Research*, 42(12). doi:10.1029/2006WR005131

## Cross-validate an interpolated surface and check that its stated uncertainty is calibrated

Stage: C | Step: C2 | Methods: boreholes, seismic, gravity, magnetic, ert, tdem, fdem, mt

A surface interpolated between picks (holes, seismic horizons, interface depths from soundings) is
an estimate with a variance, and kriging returns both. The standard test is cross-validation: remove
each datum, predict it from the rest, and compare. Two numbers come out. The mean squared error says
whether the interpolation predicts better than simpler alternatives, and the ratio of squared errors
to kriging variances, which should be close to one, says whether the stated uncertainty is honest.
The variogram behind the kriging is itself fitted to the data and its choice changes both numbers.

A kriged surface drawn without this looks equally reliable everywhere; the variance map is often
skipped although it is the part that says where the surface is a guess. Where the data are clustered,
cross-validation is dominated by the clusters and overstates skill between them.

**Check.** Run leave-one-out cross-validation on every interpolated surface and report the mean
error, the root-mean-square error against that of the data mean, and the mean squared deviation
ratio against kriging variance. Publish the kriging standard deviation alongside the surface and mask
or flag where it exceeds the tolerance the geological question needs.

**Sources.**
- Oliver, M. A., & Webster, R. (2014). A tutorial guide to geostatistics: computing and modelling variograms and kriging. *Catena*, 113, 56–69. doi:10.1016/j.catena.2013.09.006
- Chilès, J.-P., & Delfiner, P. (2012). *Geostatistics: Modeling Spatial Uncertainty* (2nd ed.). Wiley. doi:10.1002/9781118136188

## Report the spread of acceptable models for any quantity a decision rests on

Stage: C | Step: none | Methods: tdem, fdem, ert, mt, gravity, magnetic, seismic

In the probabilistic formulation of inverse problems the answer is not a model but a distribution
over models, the posterior, combining the data, their errors and the prior. Monte Carlo methods
sample that distribution, and trans-dimensional samplers let even the number of layers be uncertain,
so a depth to an interface comes with a spread and, often, with several distinct modes. A single best
model, regularized or maximum-likelihood, is one point in that distribution and may not be typical of
it; the uncertainty of a derived quantity such as a thickness or a volume cannot be read from it.

Sampling is expensive in two and three dimensions, but the quantity the geological model needs is
usually a few numbers, and for those the cost is often affordable on a subset of locations or with a
reduced parameterization. Where it is not, the honest report is a bounded one from several
deterministic runs rather than one run presented as the answer.

**Check.** For every quantity the geological model takes from an inversion (an interface depth, a
thickness, a property value), report its spread: posterior percentiles from sampling where the
engine supports it, on a representative subset of soundings if the full set is too costly, or
otherwise the range across the runs made under the first section of this file. A quantity reported
without a spread is labelled as coming from a single model.

**Sources.**
- Tarantola, A. (2005). *Inverse Problem Theory and Methods for Model Parameter Estimation*. SIAM. doi:10.1137/1.9780898717921
- Mosegaard, K., & Tarantola, A. (1995). Monte Carlo sampling of solutions to inverse problems. *Journal of Geophysical Research: Solid Earth*, 100(B7), 12431–12447. doi:10.1029/94JB03097
- Sambridge, M., & Mosegaard, K. (2002). Monte Carlo methods in geophysical inverse problems. *Reviews of Geophysics*, 40(3). doi:10.1029/2000RG000089
- Malinverno, A. (2002). Parsimonious Bayesian Markov chain Monte Carlo inversion in a nonlinear geophysical problem. *Geophysical Journal International*, 151(3), 675–688. doi:10.1046/j.1365-246X.2002.01847.x

## Put every dataset in one declared horizontal system and one vertical datum before combining them

Stage: A | Step: A10 | Methods: tdem, fdem, ert, mt, gravity, magnetic, seismic, boreholes

Datasets that will be read together arrive in different coordinate reference systems: geographic
coordinates on different horizontal datums, several projections and zones, and heights on different
vertical references. A change of horizontal datum can move coordinates by metres, and by tens of
metres or more between older and modern continental datums, and the shift is smooth, so overlaid layers look registered and are offset. Heights are
worse: ellipsoidal heights from satellite positioning and orthometric heights from levelling or an
elevation model differ by the geoid undulation, tens of metres in most places, and the gravity
literature documents how conflating them corrupts anomalies and reductions.

A geological model built from mis-registered inputs places a contact from one dataset against the
wrong cell of another, and a mismatch between methods, or between a model and a borehole, then
appears as structure. Because each dataset is internally consistent, nothing inside a single run
reveals it.

**Check.** For every input, record the horizontal CRS as an EPSG code and the vertical datum by
name, taken from the file's own declaration and not assumed from the region; refuse an input whose
reference cannot be established. Transform all inputs to one CRS, then difference a quantity that
two inputs both state (a surveyed elevation against the elevation model, a line position against
imagery or another survey) and require the median offset to be smaller than the model's cell size.

**Sources.**
- Snyder, J. P. (1987). *Map projections: a working manual*. U.S. Geological Survey Professional Paper 1395. doi:10.3133/pp1395
- Li, X., & Götze, H.-J. (2001). Ellipsoid, geoid, gravity, geodesy, and geophysics. *Geophysics*, 66(6), 1660–1668. doi:10.1190/1.1487109
- Hackney, R. I., & Featherstone, W. E. (2003). Geodetic versus geophysical perspectives of the 'gravity anomaly'. *Geophysical Journal International*, 154(1), 35–43. doi:10.1046/j.1365-246X.2003.01941.x

## Test anisotropy as an explanation before reading a disagreement between methods as structure

Stage: C | Step: none | Methods: tdem, fdem, ert, mt, seismic, boreholes

Many rocks and most finely layered sequences are anisotropic at the scale of a survey, and different
methods sample different components of the property. For resistivity, inductive methods excite
mainly horizontal current and so sense mainly the horizontal resistivity, while galvanic methods also
drive vertical current, so the same layered ground gives two isotropic inversions with different
resistivities or thicknesses. Surface measurements alone often cannot separate a thick anisotropic
layer from a thinner isotropic one. In magnetotellurics, macroscopic anisotropy and distributed
heterogeneity can produce very similar responses. In seismics, weak anisotropy makes the velocity
that moves reflections into place differ from the vertical velocity, so seismic depths and well
depths disagree.

An agent that inverts each method isotropically and reads the disagreement as two units, a dipping
contact or a lateral change will be building geology out of a single anisotropic unit. The reverse
error, invoking anisotropy for any disagreement, is equally available, so the test has to be one the
data can fail.

**Check.** Where two methods disagree over a layered section, invert them jointly with a
transversely isotropic parameterization (or a one-dimensional anisotropic model at a few soundings)
and compare its misfit with the isotropic joint fit. Where logs exist, compute the anisotropy
coefficient from the layered log as the section on upscaling in the borehole file describes and
compare it with the ratio the two methods imply. Adopt structure only if the anisotropic model fails
to fit both.

**Sources.**
- Christensen, N. B. (2000). Difficulties in determining electrical anisotropy in subsurface investigations. *Geophysical Prospecting*, 48(1), 1–19. doi:10.1046/j.1365-2478.2000.00174.x
- Wannamaker, P. E. (2005). Anisotropy versus heterogeneity in continental solid earth electromagnetic studies: fundamental response characteristics and implications for physicochemical state. *Surveys in Geophysics*, 26(6), 733–765. doi:10.1007/s10712-005-1832-1
- Thomsen, L. (1986). Weak elastic anisotropy. *Geophysics*, 51(10), 1954–1966. doi:10.1190/1.1442051

## Keep what shaped the model apart from what tests it, because interpreters see what they expect

Stage: B | Step: B7 | Methods: tdem, fdem, ert, mt, gravity, magnetic, seismic, boreholes

Numerical models of open natural systems cannot be verified; agreement with observations confirms
them only partly, and confirms nothing when the observation helped build the model. The same
information easily enters twice: a published surface becomes a reference model and is then cited as
agreeing with the result, or a borehole sets a petrophysical class and then validates the class map.
Experiments on geoscience interpretation show the human side of the same problem: given one seismic
section, only about a fifth of several hundred geoscientists reached the interpretation it was built from,
and their answers tracked their own backgrounds, and reviews of structural interpretation document
anchoring on the first concept and the pull of what is familiar.

Agents inherit both failures. A model agreeing with its own prior reads as validation, and an
explanation settled early shapes which checks are run afterwards.

**Check.** Keep a provenance record of every input that shaped the run or its reading (reference
model, bounds, weights, class values, constraints, the geological concept) and of every dataset used
for validation, and require the two to be disjoint before reporting agreement. Before settling an
interpretation, write down at least one alternative concept and the observation that would
distinguish it, and run that check.

**Sources.**
- Oreskes, N., Shrader-Frechette, K., & Belitz, K. (1994). Verification, validation, and confirmation of numerical models in the earth sciences. *Science*, 263(5147), 641–646. doi:10.1126/science.263.5147.641
- Bond, C. E., Gibbs, A. D., Shipton, Z. K., & Jones, S. (2007). What do you think this is? "Conceptual uncertainty" in geoscience interpretation. *GSA Today*, 17(11), 4. doi:10.1130/GSAT01711A.1
- Bond, C. E. (2015). Uncertainty in structural interpretation: lessons to be learnt. *Journal of Structural Geology*, 74, 185–200. doi:10.1016/j.jsg.2015.03.003
