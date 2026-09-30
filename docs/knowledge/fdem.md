# Frequency-domain EM: received practice

What published practice says about frequency-domain EM (especially helicopter frequency-domain
airborne EM), for the agents to consult before and after an inversion. Everything here is tier
`received` (docs/lessons/README.md, Tiers): a paper, a textbook or a standard says so, and none of it
was measured on this project's data. A section may propose a check; it does not gate a run until the
check has been measured here. Every DOI below was resolved against Crossref when this file was
written.

## Level every channel against zero readings taken at high altitude and correct the drift between them before any transform or inversion

Stage: A | Step: none | Methods: fdem

A helicopter FDEM system measures a secondary field that is several orders of magnitude smaller
than its primary, after most of the primary has been bucked out. What remains of the primary in each
in-phase and quadrature channel, the zero level, drifts with temperature and electronics during a
flight. Huang and Fraser put it plainly: the integrity of the data depends on calibration and on the
zero-level estimate, the primary cannot be determined absolutely, and a wrongly zero-levelled channel
transforms into wrong resistivities; poor levelling can create false features and remove real ones.
Valleau lists drift (zero-level) correction of every channel as a standard processing step.

Siemon describes standard zero levelling as subtracting readings recorded at high altitude, where
the ground response has vanished, which corrects long-term, quasi-linear instrument drift; short-term
drift from temperature changes with altitude is not fully removed and shows as stripes along flight
lines, which is what later, resistivity-based levelling addresses. Huang and Fraser warn that
automated levelling filters cannot tell a geological feature parallel to the flight lines from a
levelling error of the same wavelength.

A zero-level error matters most where the signal is smallest: low frequencies over resistive
ground, where a few ppm is a large fraction of the response. Brodie and Sambridge treat gain and
zero-level drift as unknowns inverted together with the conductivity model, instead of correcting
each frequency separately beforehand.

**Check.** Find the high-altitude segments in the flight record, confirm that every channel reads
near zero there after correction, and that drift is interpolated between consecutive segments, not
extrapolated past the last one. Then difference each channel at line intersections or tie lines; a
step that is constant along a whole line is levelling, and its size in ppm against the lowest
frequency's signal over the most resistive ground says whether it matters.

**Sources.**
- Siemon, B. (2009). Levelling of helicopter-borne frequency-domain electromagnetic data. *Journal of Applied Geophysics*, 67(3), 206-218. doi:10.1016/j.jappgeo.2007.11.001
- Huang, H., & Fraser, D. C. (1999). Airborne resistivity data leveling. *Geophysics*, 64(2), 378-385. doi:10.1190/1.1444542
- Valleau, N. C. (2000). HEM data processing: A practical overview. *Exploration Geophysics*, 31(4), 584-594. doi:10.1071/EG00584
- Brodie, R., & Sambridge, M. (2006). A holistic approach to inversion of frequency-domain airborne EM data. *Geophysics*, 71(6), G301-G312. doi:10.1190/1.2356112

## Treat each frequency's amplitude and phase calibration as unknown until it has been checked against ground data or a uniform conductor

Stage: B | Step: B5 | Methods: fdem

Calibration errors are systematic per frequency and survive every internal consistency check.
Fitterman analysed the calibration procedure itself: mispositioning the calibration (Q) coil can
produce errors greater than 2 per cent per centimetre of in-line displacement, and conductive ground
under the calibration site biases the result, starting in the quadrature channels below about
100 ohm-m and in the in-phase below about 10 ohm-m, with horizontal coplanar coils more affected
than vertical coaxial ones.

Deszcz-Pan, Fitterman and Labson corrected helicopter data against resistivity-depth models from
auxiliary ground data at scattered sites, fitting amplitude, phase and bias factors by least squares.
Only the amplitude and phase corrections were stable, and applying them reduced the inversion misfit
and brought the inverted bird height closer to the measured one. Ley-Cooper and Macnae recalibrated
data from a zone of uniform conductive response by inverting its altitude-corrected median
responses, attributing a systematic mismatch between measured altitude and inverted depth to surface
to altitude error and the remaining frequency-dependent misfit to calibration. It worked reliably at
high frequencies and failed at low frequencies over moderate or poor conductors, where the signal is
small. Ley-Cooper and co-authors estimated that amplitude calibration errors can put near-surface
conductors 1 to 2 m too deep or shallow.

A calibration factor recovered by fitting is a rescuing parameter. Ground data used to derive it
are no longer independent, and cannot then be used to validate the result.

**Check.** Estimate per-frequency amplitude and phase corrections against independent ground models
(TEM soundings, borehole resistivity logs) at several sites, or against seawater if the survey
crossed it, and report each correction with its spread across sites. A correction that varies from
site to site by more than it departs from unity is not a calibration. Hold some ground sites out of
the estimate and use only those to validate.

**Sources.**
- Fitterman, D. V. (1998). Sources of calibration errors in helicopter EM data. *Exploration Geophysics*, 29(1), 65-70. doi:10.1071/EG998065
- Deszcz-Pan, M., Fitterman, D. V., & Labson, V. F. (1998). Reduction of inversion errors in helicopter EM data using auxiliary information. *Exploration Geophysics*, 29(1), 142-146. doi:10.1071/EG998142
- Ley-Cooper, Y., & Macnae, J. (2007). Amplitude and phase correction of helicopter EM data. *Geophysics*, 72(3), F119-F126. doi:10.1190/1.2717498
- Ley-Cooper, Y., Macnae, J., Robb, T., & Vrbancich, J. (2006). Identification of calibration errors in helicopter electromagnetic (HEM) data through transform to the altitude-corrected phase-amplitude domain. *Geophysics*, 71(2), G27-G34. doi:10.1190/1.2187741

## Measure the sensor height twice on one vertical datum, because at high frequency a height error becomes a near-surface resistivity error

Stage: A | Step: A8 | Methods: fdem

The FDEM response depends so strongly on sensor height that height and near-surface conductivity
trade off. Fraser observed that over widespread conductive ground a change of less than 10 m in
survey altitude produces EM anomalies of apparent significance, indistinguishable at first sight
from an increase in ground conductivity. Beamish studied the canopy effect:
tree cover or any other elevated feature makes the altimeter under-read the height above ground, and
a numerical inversion given that height puts false high-resistivity zones with short wavelengths at
the surface, unless the model includes a pseudolayer, an at-surface resistor of variable thickness,
which is what makes the pseudolayer half-space transform immune to altitude errors.

The size of the error is not negligible even over flat water: Ley-Cooper and co-authors estimated
variable altitude errors of about 1.5 m over seawater. Minsley showed that the uncertainty in the
measured system elevation widens the set of layered models consistent with the data. The coils'
height is what the forward model needs, and the altimeter may be mounted elsewhere on the system.

A second height usually exists: GPS elevation minus a terrain model. Li and Götze point out that GPS
gives height above the ellipsoid while levelling and most terrain models give height above the
geoid; the two differ by the geoid undulation, which is tens of metres over much of the world, so the
difference is meaningless until both are on one datum.

**Check.** Difference the laser height against GPS height minus the terrain model on one vertical
datum, and map the residual against land cover. Where the inversion allows a free height or a
surface pseudolayer, compare the recovered height with the measured one, line by line. A recovered
height above the altimeter over forest is canopy; a thin resistive top layer that appears only over
forest or buildings is the same height error read as geology.

**Sources.**
- Fraser, D. C. (1978). Resistivity mapping with an airborne multicoil electromagnetic system. *Geophysics*, 43(1), 144-172. doi:10.1190/1.1440817
- Beamish, D. (2002). The canopy effect in airborne EM. *Geophysics*, 67(6), 1720-1728. doi:10.1190/1.1527073
- Ley-Cooper, Y., Macnae, J., Robb, T., & Vrbancich, J. (2006). Identification of calibration errors in helicopter electromagnetic (HEM) data through transform to the altitude-corrected phase-amplitude domain. *Geophysics*, 71(2), G27-G34. doi:10.1190/1.2187741
- Minsley, B. J. (2011). A trans-dimensional Bayesian Markov chain Monte Carlo algorithm for model assessment using frequency-domain electromagnetic data. *Geophysical Journal International*, 187(1), 252-272. doi:10.1111/j.1365-246X.2011.05165.x
- Li, X., & Götze, H.-J. (2001). Ellipsoid, geoid, gravity, geodesy, and geophysics. *Geophysics*, 66(6), 1660-1668. doi:10.1190/1.1487109

## Record the coil geometry, separation and normalisation of every channel, and check the primary field that normalisation implies

Stage: A | Step: A2 | Methods: fdem

A helicopter bird carries several coil pairs, typically horizontal coplanar (HCP, vertical dipoles
side by side), vertical coaxial (VCA or VCX, horizontal dipoles on a common axis) and sometimes
vertical coplanar (VCP). Each channel is delivered as the secondary field in parts per million of
the primary field at the receiver for that geometry, a calibration applied during acquisition
(Valleau). The primary is not the same for every pair: from the dipole fields in Ward and Hohmann,
the on-axis field of a coaxial pair is twice the broadside field of a coplanar pair at the same
separation, and the two point in opposite senses relative to the receiver coil. A forward code that
normalises by a different primary than the contractor did is wrong by a factor of two or by a sign,
and the ppm values of different geometries cannot be compared directly.

Geometry is not fixed in flight. Fitterman and Yin showed that pitch, roll and yaw of the bird change
the coupling of all three geometries, with a purely geometric component that is larger than the
inductive one, and that correcting for it reduces inversion misfit and gives laterally smoother
sections. Fitterman found the HCP pair more sensitive than the coaxial pair to conductive ground at
the calibration site.

**Check.** For each channel, list frequency, coil orientation, separation and the primary it is
normalised by. Forward-model a 100 ohm-m half-space at the survey's median height through the run's
own code, and compare the sign and order of magnitude of each channel with the delivered data over
ground of similar apparent resistivity. A channel off by a factor near two, or with the opposite
sign, is normalised against the wrong primary.

**Sources.**
- Valleau, N. C. (2000). HEM data processing: A practical overview. *Exploration Geophysics*, 31(4), 584-594. doi:10.1071/EG00584
- Ward, S. H., & Hohmann, G. W. (1988). Electromagnetic theory for geophysical applications. In M. N. Nabighian (Ed.), *Electromagnetic Methods in Applied Geophysics*, Vol. 1 (pp. 130-311). Society of Exploration Geophysicists. doi:10.1190/1.9781560802631.ch4
- Fitterman, D. V., & Yin, C. (2004). Effect of bird maneuver on frequency-domain helicopter EM response. *Geophysics*, 69(5), 1203-1215. doi:10.1190/1.1801937
- Fitterman, D. V. (1998). Sources of calibration errors in helicopter EM data. *Exploration Geophysics*, 29(1), 65-70. doi:10.1071/EG998065

## Above about ten kilohertz, use a forward model that includes displacement currents or down-weight those channels

Stage: A | Step: A15 | Methods: fdem

Most 1D FDEM forward codes and half-space look-up tables are quasi-static: they neglect
displacement currents. Siemon showed that at frequencies above some 10 kHz this approximation is
often not accurate enough for helicopter data, and that a full solution with displacement currents
in both the ground and the air is needed. The full solution brings numerical singularities into the
Hankel-transform evaluation, which he removed with a wavenumber shift or partial integration; the
look-up tables and approximations used for half-space inversion, and the formulas in multi-layer
inversion, also have to be replaced above that frequency. With accurate modelling the high
frequencies become usable for near-surface work.

The quasi-static choice is a library default, and its error falls on the highest frequency, which
is the channel that controls the top few metres. It shows either as a residual concentrated at the
highest frequency or, if the error model is loose enough to absorb it, as a biased top layer.

**Check.** For the highest frequency flown, forward-model a representative layered model with and
without displacement currents (or with relative permittivity 1 against a plausible ground value, if
the code allows it) and compare the difference with that channel's noise. If it exceeds the noise
and the run's code cannot include displacement currents, down-weight or exclude the channel and say
so in the run record.

**Sources.**
- Siemon, B. (2012). Accurate 1D forward and inverse modeling of high-frequency helicopter-borne electromagnetic data. *Geophysics*, 77(4), WB71-WB87. doi:10.1190/geo2011-0371.1

## Read half-space apparent resistivity and centroid-depth sections as displays of the data, not as inverted models

Stage: C | Step: none | Methods: fdem

Apparent resistivity maps are the classic FDEM product. Fraser derived them from half-space models
for each frequency and showed their value for interpretation: anomalies caused by altitude changes
are largely suppressed and the contours follow conductive units. Sengpiel showed that a complex
transfer function computed from each frequency gives the centroid depth of the in-phase current
system, and that apparent resistivity plotted against centroid depth over a broad frequency range
gives a smoothed approximation of resistivity against depth with no starting model. Siemon improved
these resistivity-depth profiles for helicopter data.

These are transforms of each frequency to a uniform half-space, and the word approximation is in
their definition. A centroid depth is not a layer boundary, a thin layer's resistivity is averaged
away, and the gridded resistivity maps carry the levelling decisions of whoever made them; Huang and
Fraser note that resistivity levelling can itself generate false features and remove real ones.

Quantitative statements (an interface depth, the thickness or resistivity of a clay layer) belong to
a layered inversion with a stated error model and a depth of investigation.

**Check.** Read the delivered product's metadata to establish whether it is a transform or an
inversion. Before a transform section is read into a model, invert a subset of soundings with a
layered model and compare; where they disagree beyond the inversion's uncertainty, use the
inversion, and record which product each claim rests on.

**Sources.**
- Fraser, D. C. (1978). Resistivity mapping with an airborne multicoil electromagnetic system. *Geophysics*, 43(1), 144-172. doi:10.1190/1.1440817
- Sengpiel, K.-P. (1988). Approximate inversion of airborne EM data from a multilayered ground. *Geophysical Prospecting*, 36(4), 446-459. doi:10.1111/j.1365-2478.1988.tb02173.x
- Siemon, B. (2001). Improved and new resistivity-depth profiles for helicopter electromagnetic data. *Journal of Applied Geophysics*, 46(1), 65-76. doi:10.1016/S0926-9851(00)00040-9
- Huang, H., & Fraser, D. C. (1999). Airborne resistivity data leveling. *Geophysics*, 64(2), 378-385. doi:10.1190/1.1444542

## Cull samples affected by cultural conductors before the inversion and carry the mask into the result

Stage: A | Step: none | Methods: fdem

Power lines, buildings, pipelines, railways and fences add a response that no layered earth can
reproduce. Siemon and co-authors applied helicopter FDEM to groundwater exploration in urban areas,
where such anthropogenic effects are dense, and eliminated the data affected by them as part of
processing, before inversion. Valleau lists removal
of non-geological noise from the raw data as a standard processing step, ahead of drift correction.

A culturally affected sample inverted as 1D ground becomes a local conductor or a spurious layer,
and a laterally constrained inversion spreads it to its neighbours. Removing the samples leaves
gaps, and a gap is not ground: an interpolated value across a removed stretch has no data behind it.

**Check.** Buffer mapped infrastructure, flag the samples inside, and compare each with its
neighbours along the line: look for narrow, high-amplitude anomalies that coincide with the
installation, and negative in-phase values that the magnetic data do not explain. Use the survey's
power-line monitor channel if one was delivered. Report the number of samples removed, and mark the
removed stretches in any section or map built from the inversion.

**Sources.**
- Siemon, B., Steuer, A., Ullmann, A., Vasterling, M., & Voß, W. (2011). Application of frequency-domain helicopter-borne electromagnetics for groundwater exploration in urban areas. *Physics and Chemistry of the Earth, Parts A/B/C*, 36(16), 1373-1385. doi:10.1016/j.pce.2011.02.006
- Valleau, N. C. (2000). HEM data processing: A practical overview. *Exploration Geophysics*, 31(4), 584-594. doi:10.1071/EG00584

## Account for magnetic susceptibility when the low-frequency in-phase is negative or the resistivity comes back too high over magnetic ground

Stage: B | Step: B3 | Methods: fdem

Magnetic ground adds its own signature to the in-phase channel. Fraser described it: eddy currents
give positive, frequency-dependent in-phase and quadrature, while magnetic polarisation gives a
frequency-independent in-phase response of negative sign. Beard and Nyquist quantified it: the
in-phase shift grows with relative permeability, with the amount of magnetic material and as the
sensor gets lower, and the quadrature changes only slightly. Over resistive magnetic ground the
shift appears as negative in-phase at low frequencies; over conductive ground it hides inside the
large positive in-phase and goes unnoticed.

Ignoring it biases the result in one direction. Huang and Fraser showed that half-space algorithms
that assume free-space permeability return erroneously high resistivity in magnetic areas; they
estimate an apparent permeability from the lowest frequency first, where conduction currents
contribute least, and recommend deriving resistivity from the quadrature at two frequencies where
the ground is strongly magnetic. Farquharson, Oldenburg and Routh found that inverting
susceptibility-affected data for conductivity alone underfits the affected data and overfits the
rest to compensate, which produces artefacts; inverting for conductivity and susceptibility together
avoids them.

A levelling error also produces negative in-phase values, so the zero levels are checked first.

**Check.** After the high-altitude zero levels have been confirmed, count samples with negative
in-phase at the lowest frequency and correlate the lowest-frequency in-phase residual with the total
magnetic intensity along the same lines. If they correlate, invert with susceptibility (or
permeability) as a parameter, or with the quadrature only, and compare the resistivities with the
conductivity-only run.

**Sources.**
- Fraser, D. C. (1981). Magnetite mapping with a multicoil airborne electromagnetic system. *Geophysics*, 46(11), 1579-1593. doi:10.1190/1.1441165
- Beard, L. P., & Nyquist, J. E. (1998). Simultaneous inversion of airborne electromagnetic data for resistivity and magnetic permeability. *Geophysics*, 63(5), 1556-1564. doi:10.1190/1.1444452
- Huang, H., & Fraser, D. C. (2000). Airborne resistivity and susceptibility mapping in magnetically polarizable areas. *Geophysics*, 65(2), 502-511. doi:10.1190/1.1444744
- Farquharson, C. G., Oldenburg, D. W., & Routh, P. S. (2003). Simultaneous 1D inversion of loop-loop electromagnetic data for magnetic susceptibility and electrical conductivity. *Geophysics*, 68(6), 1857-1869. doi:10.1190/1.1635038

## State the depth of investigation per sounding from the lowest frequency, the noise and the final model, and read nothing below it

Stage: C | Step: C1 | Methods: fdem

High frequencies see the shallow ground and low frequencies the deeper ground, through the skin
depth, about 503 times the square root of resistivity over frequency in metres. Siemon, Christiansen
and Auken's review gives typical airborne EM investigation depths from some ten metres over
conductive ground to several hundred metres over resistive ground, with helicopter FDEM suited to
about 1 to 100 m and helicopter TEM to about 10 to 400 m. The lowest frequency sets the floor, and over resistive ground its small response is
exactly where zero-level and calibration errors weigh most.

Skin depth is an upper scale, not the depth of investigation. Huang derived depth of investigation
for small-separation sensors and found it roughly proportional to the square root of the host's skin
depth for a given detection threshold and contrast; it increases with target conductivity and
contrast and decreases as the threshold rises, and the threshold depends on signal-to-noise (20 to
30 per cent for resistive targets or noisy areas, 5 to 10 per cent for conductive targets in quiet
ones). Christiansen and Auken's sensitivity-based measure applies to any 1D EM model and folds in the
actual system, the noise and the final model.

Laterally, each sample averages over a footprint. Beamish gives footprints for towed-bird and
fixed-wing FDEM systems that scale nearly linearly with altitude, with a secondary dependence on
resistivity and frequency, which sets how close a borehole has to be before it is a fair comparison.

**Check.** For each sounding compute the skin depth at the lowest frequency from the recovered
near-surface resistivity as an upper bound, then the sensitivity-based depth of investigation from
the final model with the data errors, and mask the model below it. Report the footprint at the
survey's median altitude beside any comparison with point data.

**Sources.**
- Siemon, B., Christiansen, A. V., & Auken, E. (2009). A review of helicopter-borne electromagnetic methods for groundwater exploration. *Near Surface Geophysics*, 7(5-6), 629-646. doi:10.3997/1873-0604.2009043
- Huang, H. (2005). Depth of investigation for small broadband electromagnetic sensors. *Geophysics*, 70(6), G135-G142. doi:10.1190/1.2122412
- Christiansen, A. V., & Auken, E. (2012). A global measure for depth of investigation. *Geophysics*, 77(4), WB171-WB177. doi:10.1190/geo2011-0393.1
- Beamish, D. (2003). Airborne EM footprints. *Geophysical Prospecting*, 51(1), 49-60. doi:10.1046/j.1365-2478.2003.00353.x

## Report the range of layered models the data allow, and compare with ground data the calibration never used

Stage: C | Step: none | Methods: fdem

A helicopter FDEM sample is a handful of frequencies with an in-phase and a quadrature each, and
many layered models fit it equally well. Minsley's trans-dimensional Bayesian inversion samples that
set instead of returning one model: the number of layers is left to the data, and the output is a
distribution of interface depths and resistivities that exposes the trade-offs between parameters.
The spread depends on the prior, on the system geometry and on the uncertainty of the measured
height. Siemon, Auken and Christiansen applied laterally constrained inversion to helicopter FDEM
data, and the review by Siemon, Christiansen and Auken reports that lateral constraints often
stabilise the models, particularly for noisy data. Brodie and Sambridge go further and invert the
whole survey, calibration included, as one layered model constrained by independent conductivity
and interface-depth data.

Comparison with ground data is what separates a stable model from a right one. Minsley's results
were checked against borehole resistivity and lithology logs; Steuer, Siemon and Auken compared
frequency- and time-domain helicopter EM over the same buried valley. Ground data that were used to
calibrate or constrain the survey cannot also validate it.

**Check.** For a subset of soundings, sample or bracket the equivalent models (an ensemble, or
few-layer inversions from several starting models to the same misfit) and report each interface
depth as a range. Compare against boreholes or ground soundings that no calibration or constraint
used, within the footprint, and report agreement against that range rather than against a single
model.

**Sources.**
- Minsley, B. J. (2011). A trans-dimensional Bayesian Markov chain Monte Carlo algorithm for model assessment using frequency-domain electromagnetic data. *Geophysical Journal International*, 187(1), 252-272. doi:10.1111/j.1365-246X.2011.05165.x
- Siemon, B., Auken, E., & Christiansen, A. V. (2009). Laterally constrained inversion of helicopter-borne frequency-domain electromagnetic data. *Journal of Applied Geophysics*, 67(3), 259-268. doi:10.1016/j.jappgeo.2007.11.003
- Siemon, B., Christiansen, A. V., & Auken, E. (2009). A review of helicopter-borne electromagnetic methods for groundwater exploration. *Near Surface Geophysics*, 7(5-6), 629-646. doi:10.3997/1873-0604.2009043
- Brodie, R., & Sambridge, M. (2006). A holistic approach to inversion of frequency-domain airborne EM data. *Geophysics*, 71(6), G301-G312. doi:10.1190/1.2356112
- Steuer, A., Siemon, B., & Auken, E. (2009). A comparison of helicopter-borne electromagnetics in frequency- and time-domain at the Cuxhaven valley in Northern Germany. *Journal of Applied Geophysics*, 67(3), 194-205. doi:10.1016/j.jappgeo.2007.07.001
