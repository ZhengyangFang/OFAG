# Magnetotellurics: received practice

What published practice says about magnetotellurics, for the agents to consult before and after an
inversion. Everything here is tier `received` (docs/lessons/README.md, Tiers): a paper, a textbook
or a standard says so, and none of it was measured on this project's data. A section may propose a
check; it does not gate a run until the check has been measured here. Every DOI below was resolved
against Crossref when this file was written.

## Fix the time convention and the unit of the impedance before comparing it with any forward code

Stage: A | Step: A2 | Methods: mt

An impedance is a complex number, and the sign of its imaginary part depends on whether the fields
were written with a time factor of e^{+iωt} or e^{-iωt}. Over a uniform half-space Z = E/H has a
phase of +45 degrees in the first convention and -45 degrees in the second, so the xy phase of a
layered earth sits in the first quadrant (0 to 90 degrees) under e^{+iωt} and in the fourth under
e^{-iωt}, while yx = -xy sits 180 degrees away. Changing convention is a complex conjugation: it
leaves every apparent resistivity unchanged and mirrors every phase. A range check on apparent
resistivity therefore cannot catch a convention mismatch between the file and the simulation; only
the phase quadrant can, and the tipper's imaginary part flips with it.

Units are the second trap. Processing codes commonly report Z in field units of (mV/km)/nT, which is
E over B, not E over H. The SI impedance is Z[ohm] = µ0 x 10^3 x Z[(mV/km)/nT], a factor of about
1/796, and in field units the apparent resistivity is 0.2 T |Z|^2 with T in seconds. An impedance
given as E/B in SI units is also not in ohms until it is multiplied by µ0. A reader that leaves the
factor out produces apparent resistivities off by about 6 x 10^5 with phases that look perfect.

The quadrant is evidence, not proof: strong current channelling can drive a component's phase past
90 degrees at long periods, so a few out-of-quadrant sites at the long end are physics to be
explained, while a whole dataset in the mirror quadrant is a convention.

**Check.** Before any run, simulate a 100 ohm-m half-space through the same forward code and
importer path, and confirm its xy phase lands in the same quadrant as the median observed xy phase
at the shortest periods and that the imported apparent resistivity of that half-space comes back as
100 ohm-m.

**Sources.**
- Simpson, F., & Bahr, K. (2005). *Practical Magnetotellurics*. Cambridge University Press. doi:10.1017/CBO9780511614095
- Chave, A. D., & Jones, A. G. (Eds.) (2012). *The Magnetotelluric Method: Theory and Practice*. Cambridge University Press. doi:10.1017/CBO9781139020138
- Lezaeta, P., & Haak, V. (2003). Beyond magnetotelluric decomposition: Induction, current channeling, and magnetotelluric phases over 90°. *Journal of Geophysical Research: Solid Earth*, 108(B6), 2001JB000990. doi:10.1029/2001JB000990

## Read cultural noise from its signature, because coherence does not certify clean data

Stage: A | Step: A6 | Methods: mt

Single-station impedance estimates are biased by noise in whichever channel enters an auto-power:
noise on the magnetic channels drags the estimate down, noise on the electric channels pushes it up.
The remote-reference method multiplies by magnetic fields recorded at a distant site and removes the
bias provided the noise at the two sites is uncorrelated; in the paper that introduced it,
conventional estimates on the same data were biased by as much as two orders of magnitude in
apparent resistivity. A comparison of estimators on a common dataset concluded that robust
processing, which downweights outliers automatically, should be standard and that remote reference
should be used wherever possible.

Culture defeats both when its noise is coherent. Power lines, electrified railways, pipelines with
cathodic protection and fences carry currents that are correlated across channels and across sites
within reach of the source, so coherence between E and H stays high and a remote site close enough
to share the noise does not remove it. Multi-station processing detects this as a coherence
dimension greater than two, the two plane-wave polarisations. Near a grounded industrial source the
impedance becomes real and independent of period: apparent resistivity climbs at 45 degrees on a
log-log plot and the phase falls to zero. Natural signal is also weak in the audio band around 1 to
5 kHz, where estimates are unreliable for want of source energy rather than because of noise.

A high-coherence band with a rising 45-degree apparent resistivity and a phase near zero is a
near-field source, not a conductor at depth, and an inversion given it will build structure to fit
it.

**Check.** For every site and period, flag estimates where the phase is below about ten degrees
while d log(rho_a)/d log(T) is near +1, and list the known linear infrastructure within a few
kilometres of each flagged site; also record for each site whether the estimate is single-station
or remote-referenced and how far away the reference was.

**Sources.**
- Gamble, T. D., Goubau, W. M., & Clarke, J. (1979). Magnetotellurics with a remote magnetic reference. *Geophysics*, 44(1), 53-68. doi:10.1190/1.1440923
- Egbert, G. D., & Booker, J. R. (1986). Robust estimation of geomagnetic transfer functions. *Geophysical Journal International*, 87(1), 173-194. doi:10.1111/j.1365-246X.1986.tb04552.x
- Jones, A. G., Chave, A. D., Egbert, G., Auld, D., & Bahr, K. (1989). A comparison of techniques for magnetotelluric response function estimation. *Journal of Geophysical Research: Solid Earth*, 94(B10), 14201-14213. doi:10.1029/JB094iB10p14201
- Egbert, G. D. (1997). Robust multiple-station magnetotelluric data processing. *Geophysical Journal International*, 130(2), 475-496. doi:10.1111/j.1365-246X.1997.tb05663.x
- Qian, W., & Pedersen, L. B. (1991). Industrial interference magnetotellurics; an example from the Tangshan area, China. *Geophysics*, 56(2), 265-273. doi:10.1190/1.1443039
- Szarka, L. (1988). Geophysical aspects of man-made electromagnetic noise in the earth—A review. *Surveys in Geophysics*, 9(3-4), 287-318. doi:10.1007/BF01901627
- Junge, A. (1996). Characterization of and correction for cultural noise. *Surveys in Geophysics*, 17(4), 361-391. doi:10.1007/BF01901639
- Garcia, X., & Jones, A. G. (2008). Robust processing of magnetotelluric data in the AMT dead band using the continuous wavelet transform. *Geophysics*, 73(6), F223-F234. doi:10.1190/1.2987375

## Test dimensionality per site and per period before choosing a 1D, 2D or 3D inversion

Stage: A | Step: A14 | Methods: mt

Dimensionality is a property of each site at each period, not of a survey. The phase tensor needs
no assumption about dimensionality and is unaffected by galvanic distortion: for a 1D regional
structure it reduces to a single phase in every direction, for 2D it is symmetric with a principal
axis along strike and principal values equal to the TE and TM phases, and for 3D it is
non-symmetric, with a skew angle that measures the asymmetry free of distortion. Groom-Bailey
decomposition instead fits a model of regional 2D induction plus frequency-independent galvanic
distortion (twist and shear) and tests statistically whether that model is adequate; when it is,
it returns strike and the two principal impedances up to a static shift. Rotating the tensor to
minimise its diagonal, the older practice, does not in general recover the principal axes when
distortion is present. Bahr's phase-sensitive skew is the other common indicator, with values above
about 0.3 usually read as 3D.

Inverting data in a class they do not belong to is silent. Near a 3D conductive body, 1D or 2D TE
interpretation implies false low resistivities at depth because those routines omit the boundary
charges that 3D bodies carry; a 2D TM algorithm, which includes them, can model centrally located
profiles across elongate bodies more reliably. A layered model will fit a 3D site's determinant or
one polarisation to a respectable misfit and still be a statement about a different earth.

Dimensionality also changes with scale: a site can be 1D in its shortest periods, 2D in the middle
and 3D at the longest, and multi-site, multi-frequency decomposition exists precisely because
site-by-site answers scatter.

**Check.** Compute the phase tensor skew and ellipticity for every site and period with their
propagated errors, and tabulate the fraction of site-periods that are consistent with 1D (circular,
zero skew within error) and with 2D (zero skew, a stable principal axis); run a 1D inversion only
on the site-periods that pass the 1D test, and report that fraction next to any layered result.

**Sources.**
- Caldwell, T. G., Bibby, H. M., & Brown, C. (2004). The magnetotelluric phase tensor. *Geophysical Journal International*, 158(2), 457-469. doi:10.1111/j.1365-246X.2004.02281.x
- Groom, R. W., & Bailey, R. C. (1989). Decomposition of magnetotelluric impedance tensors in the presence of local three-dimensional galvanic distortion. *Journal of Geophysical Research: Solid Earth*, 94(B2), 1913-1925. doi:10.1029/JB094iB02p01913
- McNeice, G. W., & Jones, A. G. (2001). Multisite, multifrequency tensor decomposition of magnetotelluric data. *Geophysics*, 66(1), 158-173. doi:10.1190/1.1444891
- Wannamaker, P. E., Hohmann, G. W., & Ward, S. H. (1984). Magnetotelluric responses of three-dimensional bodies in layered earths. *Geophysics*, 49(9), 1517-1533. doi:10.1190/1.1441777
- Jones, A. G., & Garcia, X. (2003). Okak Bay AMT data-set case study: Lessons in dimensionality and scale. *Geophysics*, 68(1), 70-91. doi:10.1190/1.1543195
- Ledo, J. (2005). 2-D versus 3-D magnetotelluric data interpretation. *Surveys in Geophysics*, 26(5), 511-543. doi:10.1007/s10712-005-1757-8
- Simpson, F., & Bahr, K. (2005). *Practical Magnetotellurics*. Cambridge University Press. doi:10.1017/CBO9780511614095

## Fix one coordinate frame, resolve the 90-degree strike ambiguity, then assign TE and TM

Stage: A | Step: A2 | Methods: mt

A transfer-function file carries an orientation: x is normally north and y east, but north may be
geographic or magnetic, and the file may already be rotated by a declared angle. Converting between
EDI, Z-files and newer formats involves rotation choices that the metadata must record, and sites
from different contractors or years can arrive in different frames. Every strike, every mode
assignment and every tipper arrow depends on bringing all sites into one frame first.

Strike from the impedance alone is ambiguous by 90 degrees: the phase tensor, Groom-Bailey and
diagonal-minimising rotation all return an axis and its perpendicular. Which one is along strike
has to come from outside the impedance, usually from the tipper, whose magnitude is small along
strike and whose real arrows are perpendicular to it, or from mapped geology. TE is the polarisation
with the electric field along strike and TM the one with it across strike; swapping them in a 2D
inversion places the conductors wrongly and still converges. Tipper-derived strike, taken at a
period where the target dominates the response, is the published recommendation for defining the
modes near 3D bodies.

In 3D the frame still matters. Standard 3D codes do not treat components as coupled, and in a
synthetic study a pronounced 2D structure was recovered from the full tensor only when the data
were aligned with regional strike; the same structure faded when they were not.

**Check.** Read the declared rotation and north reference of every site, rotate all sites to one
geographic frame, and compute strike per site in period bands; confirm the chosen strike is
consistent across sites within its stated error and that the tipper-based choice between the two
perpendicular axes agrees at a majority of sites before assigning TE and TM, noting which arrow
sign convention the file declares.

**Sources.**
- Kelbert, A. (2020). EMTF XML: New data interchange format and conversion tools for electromagnetic transfer functions. *Geophysics*, 85(1), F1-F17. doi:10.1190/geo2018-0679.1
- Wannamaker, P. E., Hohmann, G. W., & Ward, S. H. (1984). Magnetotelluric responses of three-dimensional bodies in layered earths. *Geophysics*, 49(9), 1517-1533. doi:10.1190/1.1441777
- Berdichevsky, M. N., Dmitriev, V. I., & Pozdnjakova, E. E. (1998). On two-dimensional interpretation of magnetotelluric soundings. *Geophysical Journal International*, 133(3), 585-606. doi:10.1046/j.1365-246X.1998.01333.x
- Tietze, K., & Ritter, O. (2013). Three-dimensional magnetotelluric inversion in practice—the electrical conductivity structure of the San Andreas Fault in Central California. *Geophysical Journal International*, 195(1), 130-147. doi:10.1093/gji/ggt234

## Set impedance error floors as a fraction of the off-diagonal magnitude and report them with the misfit

Stage: A | Step: A4 | Methods: mt

The error bars that come out of processing measure the scatter of the estimate, and at high signal
they can be tiny; they do not include the error of representing a real earth with the model class
and mesh being inverted. Practice is therefore to impose a floor, as a fraction of the impedance,
below which no error is allowed to fall. One published 3D study set 5 per cent of |Z_ij| on the
off-diagonal elements and 3 per cent of |Zxy Zyx|^(1/2) on the diagonal ones, because the diagonal
elements are small and noisy and an error proportional to their own size would let them dominate
the fit. The same study showed that the choice changes the model: with some weightings a 3D
inversion recovered nothing below 10 km, and very tight diagonal errors recovered deep structure
that field data rarely support over the whole period range.

A floor as a fraction of |Z| translates directly into the other parameterisation: 5 per cent on Z
is about 10 per cent on apparent resistivity and about 2.9 degrees on phase. A fixed absolute error
on Z, by contrast, would be negligible at short periods where |Z| is large and dominant at long
periods where it is small, so the fit would be decided by the period range, not by the data quality.

The floor is a model-error term chosen by the interpreter, and a misfit of 1 against a 10 per cent
floor is not the same claim as a misfit of 1 against a 2 per cent floor. A good overall RMS can hide
large systematic misfit at particular periods and components.

**Check.** Report, with every misfit, the floor used per component, the fraction of data whose
processing error was replaced by the floor, and the misfit broken down by component and by period
band; flag any run whose floor was tuned after looking at its own misfit.

**Sources.**
- Tietze, K., & Ritter, O. (2013). Three-dimensional magnetotelluric inversion in practice—the electrical conductivity structure of the San Andreas Fault in Central California. *Geophysical Journal International*, 195(1), 130-147. doi:10.1093/gji/ggt234
- Miensopust, M. P. (2017). Application of 3-D electromagnetic inversion in practice: Challenges, pitfalls and solution approaches. *Surveys in Geophysics*, 38(5), 869-933. doi:10.1007/s10712-017-9435-1

## Size the mesh and the domain from the skin depths of the observed periods

Stage: A | Step: A7 | Methods: mt

The skin depth of a plane wave is about 503 (rho T)^(1/2) metres for resistivity rho in ohm-m and
period T in seconds. The shortest period and the most conductive near-surface ground set how thin
the top cells must be; the longest period and the most resistive ground set how far the domain and
its padding must extend, laterally and downward, before the boundary condition stops influencing
the solution. A survey spanning 10^-3 to 10^3 s over 10 to 1000 ohm-m covers skin depths from
about 50 m to about 500 km, and one mesh has to honour both ends.

Too coarse a top layer biases the short-period responses; too small a domain lets the fixed
boundary pull the long-period responses toward whatever the boundary assumes, which appears in the
data fit as a misfit concentrated at the longest periods. 3D practice reviews treat mesh design and
padding as one of the choices that most often goes wrong silently, because the inversion still
converges.

Boundary charges on 3D bodies keep affecting apparent resistivities to arbitrarily low frequency,
so large conductors outside the survey, the sea above all, can belong inside the domain even when
no site stands on them.

**Check.** Compute the skin depth at the shortest period using the lowest observed apparent
resistivity and at the longest period using the highest, compare the top-cell thickness and the
padded extent against them, and run a uniform half-space through the actual mesh to confirm that it
returns the half-space resistivity and a 45-degree phase at both ends of the period range.

**Sources.**
- Simpson, F., & Bahr, K. (2005). *Practical Magnetotellurics*. Cambridge University Press. doi:10.1017/CBO9780511614095
- Miensopust, M. P. (2017). Application of 3-D electromagnetic inversion in practice: Challenges, pitfalls and solution approaches. *Surveys in Geophysics*, 38(5), 869-933. doi:10.1007/s10712-017-9435-1
- Wannamaker, P. E., Hohmann, G. W., & Ward, S. H. (1984). Magnetotelluric responses of three-dimensional bodies in layered earths. *Geophysics*, 49(9), 1517-1533. doi:10.1190/1.1441777

## Treat static shift as a bounded frequency-independent scale and constrain it from outside the magnetotelluric data

Stage: B | Step: B5 | Methods: mt, tdem

Small near-surface bodies accumulate charge on their boundaries and scale the measured electric
field by a real factor that persists to arbitrarily low frequency. On a log-log plot the apparent
resistivity curve shifts vertically by a constant while the phase is untouched. The shift cannot be
determined from the magnetotelluric data of a single site: the phase tensor, the determinable part
of the distorted impedance, carries the phase but not the amplitude, and recovering the amplitude
requires assumptions.

The literature gives the size. Central-loop TEM next to more than 100 sites in central Oregon gave
static shifts averaging 0 to 0.2 decade, a factor up to about 1.6, while most sites in the rougher
Cascade Range were shifted by 0.3 to 0.4 decade, a factor of 2 to 2.5. The TEM apparent resistivity
did not necessarily match either the TE or the TM curve, so a single scale for both modes is itself
an assumption. Modelling with voltage differences rather than point fields found shifts of larger
spatial extent but smaller magnitude than point-field modelling suggests.

Remedies each rest on something external: a TEM sounding at the same location, whose magnetic-field
measurement is barely affected by the surface bodies; a layer whose resistivity can be taken as
constant or modal along the profile; regularised inversion that solves for a shift per site; or
inverting only distortion-free quantities such as the phase tensor, which then needs a reasonable
prior model or the tipper to fix absolute resistivity. Spatial averaging and single invariants such
as the determinant help only in limited circumstances. A shift parameter that runs well past the
published range, or that changes with period, is absorbing something other than static shift.

**Check.** Report every recovered static-shift factor with its value in decades and compare it with
the published ranges; where a TEM sounding exists at the site, compute the MT response of its 1D
model over the overlapping periods and compare that shift with the one the inversion chose, and
rerun without amplitude data (phase or phase tensor only) to see which structures survive.

**Sources.**
- Sternberg, B. K., Washburne, J. C., & Pellerin, L. (1988). Correction for the static shift in magnetotellurics using transient electromagnetic soundings. *Geophysics*, 53(11), 1459-1468. doi:10.1190/1.1442426
- Jones, A. G. (1988). Static shift of magnetotelluric data and its removal in a sedimentary basin environment. *Geophysics*, 53(7), 967-978. doi:10.1190/1.1442533
- Pellerin, L., & Hohmann, G. W. (1990). Transient electromagnetic inversion; a remedy for magnetotelluric static shifts. *Geophysics*, 55(9), 1242-1250. doi:10.1190/1.1442940
- deGroot-Hedlin, C. (1991). Removal of static shift in two dimensions by regularized inversion. *Geophysics*, 56(12), 2102-2106. doi:10.1190/1.1443022
- Bibby, H. M., Caldwell, T. G., & Brown, C. (2005). Determinable and non-determinable parameters of galvanic distortion in magnetotellurics. *Geophysical Journal International*, 163(3), 915-930. doi:10.1111/j.1365-246X.2005.02779.x
- Tietze, K., Ritter, O., & Egbert, G. D. (2015). 3-D joint inversion of the magnetotelluric phase tensor and vertical magnetic transfer functions. *Geophysical Journal International*, 203(2), 1128-1148. doi:10.1093/gji/ggv347

## Compute the best possible 1D fit before blaming a layered inversion's misfit on the earth

Stage: B | Step: B1 | Methods: mt

For a one-dimensional earth there is a complete theory of which responses are possible at all.
Parker's D+ model, a set of conducting delta functions in an insulating medium, is the solution that
fits a set of imprecise 1D responses as closely as any conductivity profile can, and its misfit is
therefore the smallest any layered model can achieve. Existence of a 1D solution is decided by
testing that misfit statistically: if the D+ misfit is improbably large at the stated errors, no 1D
model fits, whatever the parameterisation or regularisation.

This splits a bad layered misfit into two questions. If D+ fits and the layered inversion does not,
the fault is in the inversion's parameterisation, starting model, regularisation or optimizer. If
D+ does not fit, the data are not 1D at those errors, or the errors are underestimated, or some
estimates are noise; the frequencies where D+ misses most are where to look. The D+ response is
also physically valid by construction, which makes it useful for exposing scatter in raw estimates
that no causal, passive earth could produce.

The test applies to one scalar response at a time, so it inherits the choice of which polarisation
or invariant was fed to it.

**Check.** For each site handed to a 1D inversion, compute the D+ (least-possible) misfit of the
same response at the same errors and compare it with the expected chi-squared and with the layered
inversion's misfit; report sites where D+ itself fails as not 1D rather than as poorly fitted.

**Sources.**
- Parker, R. L. (1980). The inverse problem of electromagnetic induction: Existence and construction of solutions based on incomplete data. *Journal of Geophysical Research: Solid Earth*, 85(B8), 4421-4428. doi:10.1029/JB085iB08p04421
- Parker, R. L., & Whaler, K. A. (1981). Numerical methods for establishing solutions to the inverse problem of electromagnetic induction. *Journal of Geophysical Research: Solid Earth*, 86(B10), 9574-9584. doi:10.1029/JB086iB10p09574

## Read a magnetotelluric model only to the depth and detail its periods and sensitivity support

Stage: C | Step: C1 | Methods: mt

The Niblett-Bostick transform maps each period to a depth, about (rho_a T / (2 pi µ0))^(1/2), or
roughly 356 (rho_a T)^(1/2) metres, and gives a first estimate of how deep the data reach. Detection
is shallower than penetration: a buried half-space can be detected under about 1.5 skin depths of
overburden, and the signal is strong enough at long periods that instrument limits rarely set the
maximum depth. What sets it is the longest reliable period and the conductance above the target.

Within that depth the method is unevenly sensitive. A thin conductive layer is resolved by its
conductance, conductivity times thickness, not by either separately, and resistive layers between
conductors are poorly constrained. Column sums of the sensitivity matrix show which cells the data
constrain at all, and cells with low sensitivity should not enter an interpretation; forward tests
that remove or alter a feature and ask whether the misfit worsens beyond the errors establish which
features the data require. In a published 3D study many inversions with similarly acceptable
misfits produced significantly different conductivity images, so an acceptable RMS alone does not
single out one model.

**Check.** For every feature carried into the geological model, report the Niblett-Bostick depth of
the longest period used at the nearest sites, the normalised sensitivity of the cells it occupies,
and the change in misfit when the feature is replaced by the background in a forward run.

**Sources.**
- Niblett, E. R., & Sayn-Wittgenstein, C. (1960). Variation of electrical conductivity with depth by the magneto-telluric method. *Geophysics*, 25(5), 998-1008. doi:10.1190/1.1438799
- Spies, B. R. (1989). Depth of investigation in electromagnetic sounding methods. *Geophysics*, 54(7), 872-888. doi:10.1190/1.1442716
- Schwalenberg, K., Rath, V., & Haak, V. (2002). Sensitivity studies applied to a two-dimensional resistivity model from the Central Andes. *Geophysical Journal International*, 150(3), 673-686. doi:10.1046/j.1365-246X.2002.01734.x
- Tietze, K., & Ritter, O. (2013). Three-dimensional magnetotelluric inversion in practice—the electrical conductivity structure of the San Andreas Fault in Central California. *Geophysical Journal International*, 195(1), 130-147. doi:10.1093/gji/ggt234
- Simpson, F., & Bahr, K. (2005). *Practical Magnetotellurics*. Cambridge University Press. doi:10.1017/CBO9780511614095

## Before reading parallel conductors as structure, test whether electrical anisotropy explains the data

Stage: C | Step: none | Methods: mt

An anisotropic layer, one whose conductivity differs with horizontal direction because of aligned
fractures, fabric or fluid-filled faults, splits the phases of the two polarisations and makes the
impedance look two-dimensional, with a strike along the anisotropy direction. When the anisotropy
ratio exceeds about five, dimensionality analysis returns a direction close to the anisotropy
strike even if the strike appears to vary with period, and a 2D isotropic inversion of data rotated
to that angle reproduces the anisotropy as macro-anisotropy: a set of alternating conductive and
resistive bands. Those bands are the inversion's way of representing a directional property, and
they are not a sequence of individual bodies.

The two readings make different predictions. A laterally uniform anisotropic layer produces no
vertical magnetic field under plane-wave excitation and a phase split whose direction is nearly the
same across the array, whereas lateral structure produces a tipper and responses that change near
its edges. Reviews of anisotropy in magnetotellurics treat the distinction between anisotropy and
heterogeneity as a question the data must be made to answer, not a default.

**Check.** Where an inversion shows repeated parallel conductors, tabulate the phase-split azimuth
and tipper magnitude across all sites in the affected period band; if the azimuth is uniform and the
tipper is near zero, fit a 1D anisotropic model and compare its misfit with the 2D isotropic one
before interpreting the conductors individually.

**Sources.**
- Heise, W., & Pous, J. (2001). Effects of anisotropy on the two-dimensional inversion procedure. *Geophysical Journal International*, 147(3), 610-621. doi:10.1046/j.0956-540x.2001.01560.x
- Wannamaker, P. E. (2005). Anisotropy versus heterogeneity in continental solid earth electromagnetic studies: Fundamental response characteristics and implications for physicochemical state. *Surveys in Geophysics*, 26(6), 733-765. doi:10.1007/s10712-005-1832-1
- Martí, A. (2014). The role of electrical anisotropy in magnetotelluric responses: From modelling and dimensionality analysis to inversion and interpretation. *Surveys in Geophysics*, 35(1), 179-218. doi:10.1007/s10712-013-9233-3
- Heise, W., Caldwell, T. G., Bibby, H. M., & Brown, C. (2006). Anisotropy and phase splits in magnetotellurics. *Physics of the Earth and Planetary Interiors*, 158(2-4), 107-121. doi:10.1016/j.pepi.2006.03.021
