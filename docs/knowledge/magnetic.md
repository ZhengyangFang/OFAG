# Magnetic: received practice

What published practice says about magnetic surveys, for the agents to consult before and after an
inversion. Everything here is tier `received` (docs/lessons/README.md, Tiers): a paper, a textbook
or a standard says so, and none of it was measured on this project's data. A section may propose a
check; it does not gate a run until the check has been measured here. Every DOI below was resolved
against Crossref when this file was written.

## Correct time variations with a nearby base station, and treat storm-time data as unreducible

Stage: A | Step: A4 | Methods: magnetic

The external geomagnetic field varies through the day and, during magnetic storms, by far more. The
standard correction records the field at a fixed base magnetometer and subtracts its variation from
the survey readings at the same time. This assumes that the variation at the base equals the
variation at the sensor, and that assumption weakens with distance. Referencing stations across
Ireland to a single observatory left single-correction errors of about 2 to 6 nT, and the error
tracked differences in daily amplitude between the station and the base rather than the noise level.
At high geomagnetic latitudes the difference between sites grows quickly with distance even in
quiet conditions, and is about twice as large north-south as east-west.

In auroral zones, where the variation is severe, such data are hard to level and the result
depends on careful editing of mis-ties. Survey specifications therefore suspend
acquisition when the base record exceeds a tolerance, and lines flown during disturbed intervals are
normally reflown rather than corrected. Data corrected from a distant observatory carry an error of
the size above that no later processing can see.

**Check.** Read the base station's position and its distance from the survey, and plot the base
record against the acquisition times. Flag lines flown while the base varied by more than the
survey's stated tolerance, and do not set the data uncertainty below the diurnal-correction error
implied by the base's distance.

**Sources.**
- Riddihough, R. P. (1971). Diurnal corrections to magnetic surveys—an assessment of errors. *Geophysical Prospecting*, 19(4), 551-567. doi:10.1111/j.1365-2478.1971.tb00900.x
- Beggan, C. D., Billingham, L., & Clarke, E. (2018). Estimating external magnetic field differences at high geomagnetic latitudes from a single station. *Geophysical Prospecting*, 66(6), 1227-1240. doi:10.1111/1365-2478.12641
- Mauring, E., Beard, L. P., Kihle, O., & Smethurst, M. A. (2002). A comparison of aeromagnetic levelling techniques with an introduction to median levelling. *Geophysical Prospecting*, 50(1), 43-54. doi:10.1046/j.1365-2478.2002.00300.x
- Hinze, W. J., von Frese, R. R. B., & Saad, A. H. (2012). *Gravity and Magnetic Exploration: Principles, Practices, and Applications*. Cambridge University Press. doi:10.1017/CBO9780511843129

## Remove the reference field for the survey's own date, and record which model generation was used

Stage: A | Step: A3 | Methods: magnetic

The anomaly is the measured total field minus a model of the core field, normally the International
Geomagnetic Reference Field (IGRF). The IGRF is a sequence of models at five-year epochs: a
definitive model (DGRF) for past epochs, and for the most recent five years a main-field model plus
a predicted linear secular variation. When the next generation is adopted, the predicted part is
replaced by a definitive one, so the field removed from a survey flown within the predictive window
depends on which generation was used.

The core field can change by tens of nT per year, so removing the model at the wrong
date, or at one fixed date for a survey flown over several years, leaves an offset and a smooth
gradient in the anomaly. That residue is harmless for a single small block and harmful when surveys
flown at different dates are merged, or when an inversion interprets the long wavelengths. The
inclination and declination of the model at the survey date also set the inducing field direction
the inversion assumes.

**Check.** Read the survey dates, the reference model and its generation from the release. Recompute
the model field at a few points for the actual acquisition dates and difference it against the one
removed; report the difference and use the recomputed inclination and declination as the inducing
field.

**Sources.**
- Alken, P., Thébault, E., Beggan, C. D., Amit, H., Aubert, J., et al. (2021). International Geomagnetic Reference Field: the thirteenth generation. *Earth, Planets and Space*, 73, 49. doi:10.1186/s40623-020-01288-x
- Hinze, W. J., von Frese, R. R. B., & Saad, A. H. (2012). *Gravity and Magnetic Exploration: Principles, Practices, and Applications*. Cambridge University Press. doi:10.1017/CBO9780511843129

## Correct heading error and lag before levelling, and test them on lines flown in opposite directions

Stage: A | Step: A9 | Methods: magnetic

Two acquisition errors in airborne data depend on the direction of flight. Heading error is a
reading offset that changes with the aircraft's heading, from the platform's own magnetic field and
the sensor's orientation; it is reduced by compensation calibrated on dedicated flights, and what
remains appears as level differences between lines flown in opposite directions. Lag is a time
offset between the recorded position and the magnetometer reading, from processing delays and from
the sensor sitting behind the positioning antenna; it shifts every anomaly along the line by a
fixed distance in the direction of flight.

Neither error is random. Lag shifts adjacent lines flown in opposite directions in opposite senses,
so a linear anomaly crossing them acquires a zigzag or herringbone pattern and its position is
wrong by the lag distance. Uncorrected heading error is often removed later by levelling, which
then hides it in the level corrections. Correcting such time shifts jointly with source parameters
has been shown to recover compact target positions that the shifted data blurred.

**Check.** Pick a sharp anomaly crossed by several lines of alternating direction and measure its
along-line position on each; a systematic offset between the two directions gives the residual lag.
Difference mean levels of opposite-direction lines at their tie-line crossings to estimate residual
heading error.

**Sources.**
- Kolster, M. E., & Døssing, A. (2021). Simultaneous line shift and source parameter inversion applied to a scalar magnetic survey for small unexploded ordnance. *Near Surface Geophysics*, 19(6), 629-641. doi:10.1002/nsg.12178
- Hinze, W. J., von Frese, R. R. B., & Saad, A. H. (2012). *Gravity and Magnetic Exploration: Principles, Practices, and Applications*. Cambridge University Press. doi:10.1017/CBO9780511843129

## A residual that runs along the flight lines is a levelling artefact before it is geology

Stage: B | Step: B3 | Methods: magnetic

Airborne data are levelled by comparing readings at the crossings of flight lines and tie lines and
fitting a smooth correction, polynomial in time or low-pass filtered, that minimises the mis-ties;
diurnal drift itself can be removed this way without a base station. Micro-levelling then removes
what remains by directional filtering of the grid, taking out energy that is short-wavelength across
the lines and long-wavelength along them.

Both steps can create anomalies as well as remove them. Polynomial, low-pass and spline levelling
depend on editing outlying mis-ties first, or they introduce false anomalies; median levelling is
more robust in this respect. Directional micro-levelling filters cannot tell line noise from real
geology that happens to trend parallel to the lines, and they alter the spectrum that depth
estimates rely on. An inversion fed such data fits the corrugation with elongate bodies aligned
with the survey.

**Check.** Map the final residual and the shallow part of the model, and compute their directional
power along and across the flight-line direction. Energy concentrated at the line spacing, or
features parallel to the lines, point to levelling; difference the levelled and unlevelled data (if
both are delivered) to see what the levelling put in.

**Sources.**
- Yarger, H. L., Robertson, R. R., & Wentland, R. L. (1978). Diurnal drift removal from aeromagnetic data using least squares. *Geophysics*, 43(6), 1148-1156. doi:10.1190/1.1440884
- Mauring, E., Beard, L. P., Kihle, O., & Smethurst, M. A. (2002). A comparison of aeromagnetic levelling techniques with an introduction to median levelling. *Geophysical Prospecting*, 50(1), 43-54. doi:10.1046/j.1365-2478.2002.00300.x
- Minty, B. R. S. (1991). Simple micro-levelling for aeromagnetic data. *Exploration Geophysics*, 22(4), 591-592. doi:10.1071/EG991591
- Ferraccioli, F., Gambetta, M., & Bozzo, E. (1998). Microlevelling procedures applied to regional aeromagnetic data: an example from the Transantarctic Mountains (Antarctica). *Geophysical Prospecting*, 46(2), 177-196. doi:10.1046/j.1365-2478.1998.00080.x

## Do not reduce to the pole with a plain wavenumber filter at low magnetic latitude

Stage: A | Step: none | Methods: magnetic

Reduction to the pole (RTP) recomputes the anomaly as if the field and the magnetisation were
vertical, placing anomalies over their sources. The wavenumber-domain operator divides by a term
that goes to zero as the inclination approaches zero, so near the magnetic equator it amplifies
noise and components aligned with the declination without bound, producing strong stripes in that
direction. It also assumes the magnetisation is parallel to the present field, which remanence
violates at any latitude.

Stabilised alternatives exist: posing RTP as an inverse problem through an equivalent layer, which
gives stable results even at inclinations of about 1 degree, or using the amplitude of the analytic
signal, which depends much less on the magnetisation direction and is widely used at low latitude.
A map produced by the plain filter at low inclination is not evidence of where the sources are.

**Check.** Read the inducing inclination at the survey date. At low inclination (the angle below
which this bites has to be measured here, on the grid's own noise), refuse an RTP grid made with the
unstabilised filter, compare any RTP product with the analytic-signal
amplitude, and prefer inverting the total-field anomaly directly with the correct inducing
direction over inverting an RTP grid.

**Sources.**
- Silva, J. B. C. (1986). Reduction to the pole as an inverse problem and its application to low-latitude anomalies. *Geophysics*, 51(2), 369-382. doi:10.1190/1.1442096
- MacLeod, I. N., Jones, K., & Dai, T. F. (1993). 3-D analytic signal in the interpretation of total magnetic field data at low magnetic latitudes. *Exploration Geophysics*, 24(3), 679-687. doi:10.1071/EG993679
- Blakely, R. J. (1995). *Potential Theory in Gravity and Magnetic Applications*. Cambridge University Press. doi:10.1017/CBO9780511549816

## Suspect remanence when an induced-only inversion cannot fit an anomaly's shape

Stage: B | Step: B3 | Methods: magnetic

A susceptibility inversion assumes all magnetisation is induced, parallel to the present field.
Remanent magnetisation, acquired when the rock formed and possibly reversed, adds a component in
another direction, and when it is significant the anomaly's shape no longer matches any
distribution of positive susceptibility under the present field. The unknown magnetisation
direction is the recognised obstacle to 3D susceptibility inversion where remanence is strong.

The symptom is in where the residual sits: a dipolar residual whose positive and negative lobes are
rotated from the inducing direction, a strong negative anomaly with no matching positive, or a
recovered model that needs negative susceptibility or implausibly high values to fit. Clipping
susceptibility at zero only hides the problem. Two families of remedy are standard: estimate the
total magnetisation direction and invert with it, or invert data that depend weakly on direction
(the amplitude of the anomaly vector) or invert for the full magnetisation vector.

**Check.** Compare the orientation of each major anomaly's dipole axis with the inducing field.
Where they disagree, or where the unconstrained inversion puts negative susceptibility, rerun with
an estimated magnetisation direction or an amplitude or vector inversion, and report which bodies
change.

**Sources.**
- Li, Y., Shearer, S. E., Haney, M. M., & Dannemiller, N. (2010). Comprehensive approaches to 3D inversion of magnetic data affected by remanent magnetization. *Geophysics*, 75(1), L1-L11. doi:10.1190/1.3294766
- Lelièvre, P. G., & Oldenburg, D. W. (2009). A 3D total magnetization inversion applicable when significant, complicated remanence is present. *Geophysics*, 74(3), L21-L30. doi:10.1190/1.3103249

## Magnetic data do not determine depth, and the depth-weighting exponent decides where the susceptibility goes

Stage: C | Step: C1 | Methods: magnetic

Surface magnetic data have no inherent depth resolution: the same anomaly is produced by many
distributions of magnetisation, and a minimum-structure inversion without depth weighting
concentrates susceptibility at the surface because the kernels decay rapidly with depth. The
standard remedy weights cells by (z + z0) raised to a power near -3/2, chosen to mimic the decay of
the magnetic kernel, with z0 set by cell size and observation height.

That weighting is an assumption about depth, and the recovered depth of a body moves with the
exponent and z0 while the fit stays the same. Lateral positions and edges are the better-resolved
part of a magnetic model; depth to top is moderately constrained by the short wavelengths, and depth
to bottom and the amplitude of susceptibility trade off against each other.

**Check.** Rerun with the depth-weighting exponent changed either side of the default and with a
second reference model, and report each body's depth to top and to bottom in every run. Read only
the depths that do not move into the geological model.

**Sources.**
- Li, Y., & Oldenburg, D. W. (1996). 3-D inversion of magnetic data. *Geophysics*, 61(2), 394-408. doi:10.1190/1.1443968
- Blakely, R. J. (1995). *Potential Theory in Gravity and Magnetic Applications*. Cambridge University Press. doi:10.1017/CBO9780511549816

## Treat pipelines, railways and buildings as sources to remove, not as geology

Stage: A | Step: A14 | Methods: magnetic

Steel infrastructure produces magnetic anomalies that can dominate high-resolution surveys over
developed ground: pipelines, well casings, fences, buildings and electrified railways. These
anomalies are short-wavelength, often high-amplitude and dipolar, and they sit on mapped features,
lines along roads and rails, clusters over towns; direct-current electrified railways are a
documented source in their own right. Left in the data they are fitted as small, strongly magnetic bodies at
shallow depth, and a linear chain of them reads as a dyke or a fault.

Published practice removes them locally, by manual editing against infrastructure maps or by
filtering confined to the affected area (a wavelet approach removed railway noise while leaving the
field beside it unchanged), rather than by a global low-pass filter that also removes short-wavelength
geology.

**Check.** Overlay the largest short-wavelength anomalies and the shallowest strongly magnetic cells
on a map of roads, rail, pipelines, wells and buildings. Any that coincide are to be edited out or
downweighted before inversion, and the edit reported.

**Sources.**
- Paoletti, V., Fedi, M., Florio, G., & Rapolla, A. (2007). Localized cultural denoising of high-resolution aeromagnetic data. *Geophysical Prospecting*, 55(3), 421-432. doi:10.1111/j.1365-2478.2007.00623.x
- Cuss, R. J. (2003). Manual approaches to the removal of cultural noise from high-resolution aeromagnetic data acquired over highly developed areas. *First Break*, 21(10). doi:10.3997/1365-2397.2003016
- Hinze, W. J., von Frese, R. R. B., & Saad, A. H. (2012). *Gravity and Magnetic Exploration: Principles, Practices, and Applications*. Cambridge University Press. doi:10.1017/CBO9780511843129

## Bring surveys to a common observation surface before comparing or merging them

Stage: A | Step: A8 | Methods: magnetic

Magnetic anomalies depend strongly on the distance between sensor and source, so two surveys over
the same ground flown at different heights, or one flown at constant barometric altitude and one
draped at constant terrain clearance, do not agree even when both are correct. Upward continuation
brings a lower survey to the height of a higher one exactly; continuing downward amplifies noise and
is unstable. Continuation between a level surface and a draped one needs methods designed for
uneven surfaces, such as a Taylor-series expansion, and line-based and grid-based versions of the
correction differ.

Draping a constant-altitude survey to constant terrain clearance has been shown to give amplitudes
and resolution comparable to a draped survey and a more coherent merged dataset than no correction
at all. A merge without it produces boundary steps and amplitude changes an inversion will turn into
structure; an inversion also needs the actual sensor elevation at each reading, not a nominal
clearance.

**Check.** For every survey, establish the sensor elevation of each reading (terrain plus clearance,
or GPS altitude) before any comparison. Continue both surveys to a common surface, preferably upward
to the higher, and difference them over the overlap; report the mean and spread of the difference
before merging.

**Sources.**
- Pilkington, M., & Roest, W. (1992). Draping aeromagnetic data in areas of rugged topography. *Journal of Applied Geophysics*, 29(2), 135-142. doi:10.1016/0926-9851(92)90004-5
- Pilkington, M., & Thurston, J. B. (2001). Draping corrections for aeromagnetic data: line- versus grid-based approaches. *Exploration Geophysics*, 32(2), 95-101. doi:10.1071/EG01095
- Blakely, R. J. (1995). *Potential Theory in Gravity and Magnetic Applications*. Cambridge University Press. doi:10.1017/CBO9780511549816
