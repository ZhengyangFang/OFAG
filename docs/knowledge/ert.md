# ERT: received practice

What published practice says about ERT, for the agents to consult before and after an
inversion. Everything here is tier `received` (docs/lessons/README.md, Tiers): a paper, a textbook
or a standard says so, and none of it was measured on this project's data. A section may propose a
check; it does not gate a run until the check has been measured here. Every DOI below was resolved
against Crossref when this file was written.

## Build the data error from reciprocal or repeat measurements, as an absolute term plus a term proportional to the resistance

Stage: A | Step: A4 | Methods: ert

The standard error estimate for a resistivity survey is the reciprocal: swap the current and
potential dipoles and measure again. The two readings should agree by reciprocity, so their
difference measures everything the instrument and the ground contact add. Stacking error (the
scatter of the cycles within one reading), repeat error and reciprocal error are different
estimates, and Tso and co-workers compared them as such; the stacking scatter an instrument reports
is not the reciprocal error. The accepted way to turn reciprocals into weights is to fit an envelope
with a constant term and a term proportional to the transfer resistance, e = a + b|R|, after the
gross outliers have been removed. Slater and co-workers dropped reciprocal pairs differing by more
than 10 per cent before fitting it. Zhou and Dahlin found the relative potential error falls as a
power of the potential reading across sites and arrays, which is why a purely relative error
under-weights the small readings at long offsets and a floor is needed.

The choice is not cosmetic. An Occam-type inversion fits to the error it is given: with the error
set too low the image turns rough and grows artifacts, and with it set too high the image loses
resolution. Two images of the same ground can therefore differ only because their error models do,
which matters most in time-lapse work where the noise level changes between surveys. Tso and
co-workers also found reciprocal errors are correlated between measurements that share electrodes,
so an error model that also groups by electrode explains the data better than a single linear fit.

**Check.** If the file carries reciprocal or repeated readings, fit e = a + b|R| to the reciprocal
differences and report a, b and the fraction of pairs rejected as outliers; if it carries none,
record that the error model is assumed, and state the values of both terms rather than one
percentage.

**Sources.**
- LaBrecque, D. J., Miletto, M., Daily, W., Ramirez, A., & Owen, E. (1996). The effects of noise on Occam's inversion of resistivity tomography data. *Geophysics*, 61(2), 538-548. doi:10.1190/1.1443980
- Slater, L., Binley, A. M., Daily, W., & Johnson, R. (2000). Cross-hole electrical imaging of a controlled saline tracer injection. *Journal of Applied Geophysics*, 44(2-3), 85-102. doi:10.1016/S0926-9851(00)00002-1
- Zhou, B., & Dahlin, T. (2003). Properties and effects of measurement errors on 2D resistivity imaging surveying. *Near Surface Geophysics*, 1(3), 105-117. doi:10.3997/1873-0604.2003001
- Tso, C.-H. M., Kuras, O., Wilkinson, P. B., Uhlemann, S., Chambers, J. E., Meldrum, P. I., Graham, J., Sherlock, E. F., & Binley, A. (2017). Improved characterisation and modelling of measurement errors in electrical resistivity tomography (ERT) surveys. *Journal of Applied Geophysics*, 146, 103-119. doi:10.1016/j.jappgeo.2017.09.009

## Trace outlying readings to a shared electrode before blaming the model

Stage: B | Step: B3 | Methods: ert

The large errors in a resistivity data set are usually not spread evenly. Zhou and Dahlin found
that the outliers which dominate the damage to an image tend to come with high contact resistance
at one of the electrodes in the measurement, or with a poor connection between electrode and cable,
and that power-line transients, telluric variation and instrument faults produce outliers of the
same kind. One bad electrode enters every quadripole that uses it, so it degrades many readings at
once. Deceuster and co-workers showed that ranking electrodes by the share of rejected readings
they take part in finds such an electrode, including one whose contact is slowly changing, where a
simple threshold on individual readings does not.

After a bad misfit, this means the residual should be sorted by electrode before it is read as a
statement about the earth. Residuals that concentrate on the readings sharing one electrode point
at that electrode, and removing or down-weighting its readings is a data decision, not a model one.
Zhou and Dahlin also found a smoothness-constrained least-squares inversion far more sensitive to
such outliers than a robust (L1) data norm.

**Check.** For every electrode, compute the median absolute normalized residual of the readings
that use it (as current or potential electrode) and flag any electrode whose median is several
times the survey median; rerun with its readings removed and report both misfits.

**Sources.**
- Zhou, B., & Dahlin, T. (2003). Properties and effects of measurement errors on 2D resistivity imaging surveying. *Near Surface Geophysics*, 1(3), 105-117. doi:10.3997/1873-0604.2003001
- Deceuster, J., Kaufmann, O., & Van Camp, M. (2013). Automated identification of changes in electrode contact properties for long-term permanent ERT monitoring experiments. *Geophysics*, 78(2), E79-E94. doi:10.1190/geo2012-0088.1

## Treat electrode positions as data with an error, largest in effect at short spacings

Stage: A | Step: A12 | Methods: ert

Every apparent resistivity is a measured resistance times a geometric factor computed from the
electrode positions, so a position error is a data error. For a fixed absolute mislocation the
relative error in the geometric factor grows as the spacing shrinks: a 0.1 m error is 10 per cent
of a 1 m spacing and 1 per cent of a 10 m one, so the shallowest readings carry the most. Zhou and
Dahlin computed that a 10 per cent in-line spacing error produces more than a 20 per cent error in
apparent resistivity for dipole-dipole, Wenner-beta and gamma arrays, twice the effect it has on
Wenner or Schlumberger, and that the resulting errors leave artifacts in the inverted section.

Oldenborger and co-workers showed the sensitivity to mislocation also depends on the conductivity
contrasts near the electrodes, not only on the separations, so it cannot be corrected by a fixed
factor. In their synthetic tests the data changes caused by mislocation were comparable to typical
noise and could exceed the changes caused by the ground itself, and the errors could be biased
rather than random.

**Check.** Take the positional uncertainty the survey declares (or a stated assumption of it),
propagate it to the geometric factor of each reading, and compare that relative error with the
data error model at the smallest spacings; if it is comparable, the error model must include it.

**Sources.**
- Zhou, B., & Dahlin, T. (2003). Properties and effects of measurement errors on 2D resistivity imaging surveying. *Near Surface Geophysics*, 1(3), 105-117. doi:10.3997/1873-0604.2003001
- Oldenborger, G. A., Routh, P. S., & Knoll, M. D. (2005). Sensitivity of electrical resistivity tomography data to electrode position errors. *Geophysical Journal International*, 163(1), 1-9. doi:10.1111/j.1365-246X.2005.02714.x

## Measure whether terrain matters before modelling it or leaving it out; the literature threshold is ten degrees

Stage: A | Step: A11 | Methods: ert

Terrain changes a resistivity measurement even over uniform ground, because it moves the
electrodes relative to one another and to the current flow. Fox and co-workers modelled
dipole-dipole data over 2D terrain and found that a valley gives a central apparent resistivity
low flanked by highs, a ridge the reverse, and a slope a low at its foot and a high at its top.
They put the effect as important for slopes of 10 degrees or more over a length of at least one
dipole. The IP response of a uniform earth was not affected, but the IP response of a polarizable
body was. Tsourlos and co-workers found terrain effects significant for all common arrays and
predictable by forward modelling with a mesh that follows the ground.

These are thresholds from synthetic models on particular arrays; they propose a check, they do not
decide one. The literature's own prescription is to include terrain in the forward model where it
is significant, which is a quantity to be measured on the survey at hand. A false anomaly produced
by terrain sits where the slope changes, so it is easy to read as a contact.

**Check.** Forward-model the final model (or a homogeneous half-space) on the mesh with terrain and
on a flat mesh, and compare the difference in apparent resistivity with the data error at each
reading; report where the difference exceeds the error, and whether it coincides with a feature in
the section.

**Sources.**
- Fox, R. C., Hohmann, G. W., Killpack, T. J., & Rijo, L. (1980). Topographic effects in resistivity and induced-polarization surveys. *Geophysics*, 45(1), 75-93. doi:10.1190/1.1441041
- Tsourlos, P. I., Szymanski, J. E., & Tsokas, G. N. (1999). The effect of terrain topography on commonly used resistivity arrays. *Geophysics*, 64(5), 1357-1363. doi:10.1190/1.1444640

## Keep negative apparent resistivities and negative IP readings until the geometry has been ruled out as their cause

Stage: A | Step: A2 | Methods: ert

A negative apparent resistivity (a reading whose sign is opposite to its neighbours in the
pseudosection) is routinely thrown away as an error. Jung and co-workers argued from field and
numerical experiments that in dipole-dipole surveys the main cause is often neither measurement
error, self-potential nor IP but the subsurface structure itself, for example U-shaped or crescent
conductors that make the potential rise with distance from the current electrode. Nabighian and
Elliot showed that negative IP responses arise not only from lateral structure such as dikes and
buried bodies but also over a horizontally layered earth of K or Q type, so that a polarizable
first layer can mask the response of deeper layers.

Two things go wrong when these readings are handled by habit. Discarding every negative reading
removes data that constrain the structure that caused them. And an inversion that works on the
logarithm of apparent resistivity cannot take a negative value at all, so somewhere in the chain a
sign is being dropped, clipped or taken as an absolute value. A reading whose sign flipped because
of swapped electrodes or a reversed polarity convention is a different case, and only the
geometry can tell them apart.

**Check.** Count negative apparent resistivities (and negative chargeabilities) per array type and
spacing, forward-model the recovered model at those readings to see whether it predicts the sign,
and state what the importer and the inversion each do with a negative value.

**Sources.**
- Jung, H.-K., Min, D.-J., Lee, H. S., Oh, S., & Chung, H. (2009). Negative apparent resistivity in dipole-dipole electrical surveys. *Exploration Geophysics*, 40(1), 33-40. doi:10.1071/EG08111
- Nabighian, M. N., & Elliot, C. L. (1976). Negative induced-polarization effects from layered media. *Geophysics*, 41(6), 1236-1255. doi:10.1190/1.2035915

## Read the array for what it can resolve and what noise it tolerates, and read pseudosection depth as a plotting convention

Stage: A | Step: A3 | Methods: ert

The array is an acquisition parameter with consequences for the image. Dahlin and Zhou compared ten
arrays numerically: Wenner and gamma arrays were the least contaminated by noise, while
pole-dipole, dipole-dipole and multiple-gradient arrays gave better-resolved images but were more
susceptible to noise. A strong anomaly effect did not guarantee a sharp image. The practical
reading is that a dipole-dipole section of a noisy site and a Wenner section of the same site are
not interchangeable, and that mixing arrays in one data set mixes their error behaviour too.

The pseudosection is a display, not a depth section. Edwards derived the plotting depths used for
pseudosections empirically, as the depths that make readings with different array parameters mesh
into one picture, and tied them to an effective depth derived from Roy's depth of investigation
characteristic. Barker found that the median of that characteristic is the most useful definition
of depth of investigation. Both are properties of the array over a uniform earth. A feature in a
pseudosection sits at a depth set by the plotting rule, and its shape is the array's characteristic
anomaly pattern, not the body's.

**Check.** Record the array type (or types) the file declares, the number of readings of each,
and whether the error model treats them separately; never report a depth read from a pseudosection
as a depth of the ground.

**Sources.**
- Dahlin, T., & Zhou, B. (2004). A numerical comparison of 2D resistivity imaging with 10 electrode arrays. *Geophysical Prospecting*, 52(5), 379-398. doi:10.1111/j.1365-2478.2004.00423.x
- Edwards, L. S. (1977). A modified pseudosection for resistivity and IP. *Geophysics*, 42(5), 1020-1036. doi:10.1190/1.1440762
- Barker, R. D. (1989). Depth of investigation of collinear symmetrical four-electrode arrays. *Geophysics*, 54(8), 1031-1037. doi:10.1190/1.1442728

## Mask the section below its depth of investigation, with the depth measured more than one way

Stage: C | Step: C1 | Methods: ert

Below some depth the surface data no longer constrain the resistivity, and whatever the inversion
puts there comes from the regularization and the reference model. Oldenburg and Li proposed
estimating that depth by inverting the same data with substantially different reference models:
where the recovered models agree, the data decide; where they follow their references, the data do
not. The difference, normalized, is the depth of investigation (DOI) index. They note the index
depends somewhat on the parameters used to compute it but is robust enough as a first-order limit,
and that the inverted models from different arrays differ far less than their pseudosections do.

The alternatives do not agree with one another. Caterina and co-workers compared the resolution
matrix, the cumulative sensitivity and the DOI index against synthetic benchmarks and found the
first two better indicators of whether an inverted value is right, with the DOI index mainly
qualitative. They also found no threshold that transfers between sites: they set one per survey by
inverting synthetic models built to resemble it.

**Check.** Compute the DOI index from two inversions with reference resistivities a decade apart
and also the cumulative sensitivity (coverage) of the final model; report the depth each gives
under the same line, the threshold used for each, and how much the masked depth moves when the
threshold is changed by a factor of two.

**Sources.**
- Oldenburg, D. W., & Li, Y. (1999). Estimating depth of investigation in DC resistivity and IP surveys. *Geophysics*, 64(2), 403-416. doi:10.1190/1.1444545
- Caterina, D., Beaujean, J., Robert, T., & Nguyen, F. (2013). A comparison study of different image appraisal tools for electrical resistivity tomography. *Near Surface Geophysics*, 11(6), 639-658. doi:10.3997/1873-0604.2013022

## Read the boundaries of a smoothness-regularized section as smeared and its extremes as overshoot

Stage: C | Step: none | Methods: ert

The usual ERT inversion minimizes the squared spatial change of the model, which produces the
smoothest section that fits. Loke, Acworth and Dahlin point out that where the ground is made of
nearly uniform units with sharp boundaries, this smears the boundaries and gives resistivity values
that are too low or too high, and that a blocky (L1) model norm recovers such ground better.
LaBrecque and co-workers showed a second limit: because the problem is underdetermined, reducing
the noise does not make the smooth image converge to the true section but to an asymptotic image of
its own.

So the depth of a contact in a smooth section depends on which contour is picked, and the
resistivity of a thin or small body is not its true value. A resistivity value read from the middle
of a smeared gradient is a property of the regularization, not of either unit.

**Check.** Invert the same data with an L2 and an L1 model norm at the same target misfit, and
report how far the contact depth and the extreme resistivities of the feature being interpreted
move between the two.

**Sources.**
- Loke, M. H., Acworth, I., & Dahlin, T. (2003). A comparison of smooth and blocky inversion methods in 2D electrical imaging surveys. *Exploration Geophysics*, 34(3), 182-187. doi:10.1071/EG03182
- LaBrecque, D. J., Miletto, M., Daily, W., Ramirez, A., & Owen, E. (1996). The effects of noise on Occam's inversion of resistivity tomography data. *Geophysics*, 61(2), 538-548. doi:10.1190/1.1443980

## Suspect structure beside the line before reading a deep feature in a 2D section

Stage: C | Step: none | Methods: ert

A 2D inversion assumes the ground does not change perpendicular to the line. Current does not
respect that assumption: it flows through whatever lies to the side. Bentley and Gharibi found at a
remediation site that out-of-plane anomalies produced misleading 2D images, with poor fits and
spurious conductive values at depths close to the horizontal distance of the anomaly from the line;
3D surveys were needed to place and size the bodies. Sjödahl, Dahlin and Zhou found the same kind of
3D effect significant along the crest of embankment dams, where the structure is elongated but the
line runs on top of it, and enhanced where a conductive core sits in resistive fill.

The consequence for interpretation is that a feature at depth z on a 2D section may be a body at
horizontal distance z beside the line, which includes buried pipes, fences and other culture that
parallels or crosses the survey. It also means a persistent misfit at the long offsets may be a
statement about the third dimension rather than about the error model.

**Check.** Before interpreting a deep feature, list the known structures, culture and terrain
within a line length of the profile and their distance from it, and where lines cross, compare the
two sections' resistivity at the crossing as a function of depth.

**Sources.**
- Bentley, L. R., & Gharibi, M. (2004). Two- and three-dimensional electrical resistivity imaging at a heterogeneous remediation site. *Geophysics*, 69(3), 674-680. doi:10.1190/1.1759453
- Sjödahl, P., Dahlin, T., & Zhou, B. (2006). 2.5D resistivity modeling of embankment dams to assess influence from geometry and material properties. *Geophysics*, 71(3), G107-G114. doi:10.1190/1.2198217

## Do not read the anisotropy of layered or foliated ground as structure

Stage: C | Step: none | Methods: ert

Many rocks and finely layered or fractured sequences conduct differently along and across their
fabric, yet ERT is almost always inverted as isotropic. Wiese and co-workers inverted synthetic
anisotropic data with and without anisotropy: for medium to high coefficients of anisotropy, the
isotropic inversion produced images dominated by banded artifacts aligned with the fabric, and high
misfits; for low coefficients the isotropic inversion was the better choice. Herwanger and
co-workers imaged a fractured hard-rock site and found anisotropy ranging from none to more than
300 per cent, varying across the section.

Surface data alone rarely settle the question. Christensen showed that a stack of thin layers acts
as one macro-anisotropic layer, and that neither galvanic nor inductive soundings alone resolve its
anisotropy; joint inversion of the two can, but only for layers much thicker than their overburden
and anisotropy that is not small. Banding parallel to known bedding or foliation, or a misfit that
stays high under every isotropic regularization, is the pattern to look for.

**Check.** Where the geology declares bedding or foliation, compare the orientation of elongated
features in the section with it, and where lines of different azimuth cross, compare their
resistivities at the crossing; where TEM or FDEM data share the site, compare their layered
resistivity with the ERT at the same depth.

**Sources.**
- Wiese, T., Greenhalgh, S., Zhou, B., Greenhalgh, M., & Marescot, L. (2015). Resistivity inversion in 2-D anisotropic media: numerical experiments. *Geophysical Journal International*, 201(1), 247-266. doi:10.1093/gji/ggv012
- Herwanger, J. V., Pain, C. C., Binley, A., de Oliveira, C. R. E., & Worthington, M. H. (2004). Anisotropic resistivity tomography. *Geophysical Journal International*, 158(2), 409-425. doi:10.1111/j.1365-246X.2004.02314.x
- Christensen, N. B. (2000). Difficulties in determining electrical anisotropy in subsurface investigations. *Geophysical Prospecting*, 48(1), 1-19. doi:10.1046/j.1365-2478.2000.00174.x
