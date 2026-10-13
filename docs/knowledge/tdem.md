# Time-domain EM: received practice

What published practice says about time-domain EM (ground and airborne TEM), for the agents to
consult before and after an inversion. Everything here is tier `received` (docs/lessons/README.md,
Tiers): a paper, a textbook or a standard says so, and none of it was measured on this project's
data. A section may propose a check; it does not gate a run until the check has been measured here.
Every DOI below was resolved against Crossref when this file was written.

## Model the whole system response, waveform, gate integration and receiver filters included, or the early gates describe the instrument

Stage: A | Step: A3 | Methods: tdem

A recorded TEM transient is not the earth's step response. It is that response convolved with the
transmitter current waveform, including its turn-off ramp and the repetition of the waveform,
integrated over each gate's open and close times, passed through the receiver's low-pass filters
and blanked until the front gate opens. Christiansen, Auken and Viezzoli forward-modelled a nominal
helicopter TEM system against three reference models and sorted the errors of an inaccurate system
description by where they land: low-pass filters, current turn-off and receiver-transmitter timing
act mainly on the early gates; waveform repetition, gate integration, altitude and geometry act
mainly on the late gates; amplitude, gain and current errors scale the whole sounding. Each of them,
left out of the forward model, can move the inverted model a long way from the true one.

Filters are the least obvious item. Effersø, Auken and Sørensen showed that broadcast transmitters
in the TEM band make band-limiting the receiver mandatory, and that inverting band-limited data with
an unfiltered forward model recovers the wrong resistivity model; with the filters in the forward
model the recovered model no longer depended on the cut-off frequency. Fitterman and Anderson made
the effect of a finite transmitter turn-off time on transient soundings: the part of the transient
close to the ramp is not a step response, so a step-off forward model mis-states the early gates,
and the early gates are the shallow model.

The system description is therefore data in its own right: waveform samples, gate centres and
widths, filter cut-offs and the front-gate time. A nominal value from a brochure is not the value
that was flown, and a residual concentrated in the first gates points here first.

**Check.** Forward-model the final model (or a half-space of its median resistivity) twice, once
with the declared waveform, gate integration and filters and once as a step-off response sampled
at gate centres, and report the earliest gate at which the two agree within the data's standard
deviation. Every gate before it depends on the system description, and the run must carry that
description in full.

**Sources.**
- Christiansen, A. V., Auken, E., & Viezzoli, A. (2011). Quantification of modeling errors in airborne TEM caused by inaccurate system description. *Geophysics*, 76(1), F43-F52. doi:10.1190/1.3511354
- Effersø, F., Auken, E., & Sørensen, K. I. (1999). Inversion of band-limited TEM responses. *Geophysical Prospecting*, 47(4), 551-564. doi:10.1046/j.1365-2478.1999.00135.x
- Fitterman, D. V., & Anderson, W. L. (1987). Effect of transmitter turn-off time on transient soundings. *Geoexploration*, 24(2), 131-146. doi:10.1016/0016-7142(87)90087-1

## Remove soundings coupled to power lines, fences and pipes before the inversion, because no layered earth can fit them

Stage: A | Step: none | Methods: tdem

Man-made conductors couple to the transmitter field, galvanically or capacitively, and the
response they add is a property of the installation, not of the ground. Andersen and co-authors
describe airborne TEM data flown over populated areas as contaminated by couplings to power lines,
fences and pipes, state that coupled soundings must be removed before inversion, and note that the
signature of a coupling can be subtle and hard to describe mathematically, which is why removal was
mostly an expert's manual task until they trained a neural network on manually processed reference
data. The SkyTEM processing scheme of Auken and co-authors culls coupled raw data explicitly, so
that coupled transients are not averaged into the uncoupled ones around them.

Leaving them in is not a matter of a few noisy soundings. Viezzoli, Jørgensen and Sørensen compared
different levels of processing of the same helicopter TEM data and showed that the resistivity
models, and the hydrogeological quantities derived from them, change materially with the level of
processing applied to the raw data. A coupled sounding inverted as a 1D earth tends to come back as
a spurious conductor or layer, and a laterally constrained inversion spreads it to its neighbours.

Coupling is systematic, so it cannot be absorbed by enlarging the error bars. The same applies to
ground TEM: a loop laid next to a fence or buried cable measures the fence as well.

**Check.** Intersect sounding positions with mapped infrastructure (power lines, pipelines,
railways, and fences where known) and list the soundings inside a stated buffer. For each, compare
its transient with the median of uncoupled neighbours along the line: look for a band of gates that
departs in slope or sign, an anomaly strongest at the crossing, and a feature that follows the
installation across geological strike. Report how many soundings were removed and the buffer used.

**Sources.**
- Andersen, K. K., Kirkegaard, C., Foged, N., Christiansen, A. V., & Auken, E. (2016). Artificial neural networks for removal of couplings in airborne transient electromagnetic data. *Geophysical Prospecting*, 64(3), 741-752. doi:10.1111/1365-2478.12302
- Auken, E., Christiansen, A. V., Westergaard, J. H., Kirkegaard, C., Foged, N., & Viezzoli, A. (2009). An integrated processing scheme for high-resolution airborne electromagnetic surveys, the SkyTEM system. *Exploration Geophysics*, 40(2), 184-192. doi:10.1071/EG08128
- Viezzoli, A., Jørgensen, F., & Sørensen, C. (2013). Flawed processing of airborne EM data affecting hydrogeological interpretation. *Groundwater*, 51(2), 191-202. doi:10.1111/j.1745-6584.2012.00958.x

## Weight every gate by a measured noise model and drop the gates that have reached the noise floor

Stage: A | Step: A4 | Methods: tdem

The TEM signal falls steeply with delay time: over a half-space the late-time impulse response
decays as t^-5/2 (Nabighian and Macnae). Ambient noise from sferics, power-line harmonics and radio
transmitters does not, and for white noise averaged over gates whose width grows with time the gate
noise falls only about as t^-1/2. Every sounding therefore has a delay time past which its gates
record noise rather than the earth. Munkholm and Auken showed that an inadequate estimate of the
noise leads to an erroneous interpretation, and replaced the manual, subjective culling of poor data
with an automatic noise model that assigns an uncertainty to each delay time, which is what makes the
late gates usable at all.

The standard error model is two terms per gate: the measured noise (from a background record with
the transmitter off, or the scatter of the stacked sweeps) and a relative floor for what the
system description and a layered model cannot reproduce. Only the first is a measurement.

The noise floor is also what sets the depth of investigation. Spies showed that where a sounding
can see a buried body depends on instrument sensitivity, signal strength and the ambient noise
level as much as on diffusion, so the same system reaches a different depth at a quiet and a noisy
site. Gates below the floor that are kept and fitted turn noise into deep structure.

**Check.** For each sounding, plot the late gates on log-log axes against a noise estimate (the
transmitter-off record or the stack scatter) and against a t^-5/2 reference slope. Cut at the first
gate where the signal falls below a stated multiple of the noise, and report the number of gates
kept per sounding. A late decay that flattens toward the noise slope over several gates is noise,
not a deep conductor.

**Sources.**
- Munkholm, M. S., & Auken, E. (1996). Electromagnetic noise contamination on transient electromagnetic soundings in culturally disturbed environments. *Journal of Environmental and Engineering Geophysics*, 1(2), 119-127. doi:10.4133/JEEG1.2.119
- Nabighian, M. N., & Macnae, J. C. (1991). Time domain electromagnetic prospecting methods. In M. N. Nabighian (Ed.), *Electromagnetic Methods in Applied Geophysics*, Vol. 2 (pp. 427-520). Society of Exploration Geophysicists. doi:10.1190/1.9781560802686.ch6
- Spies, B. R. (1989). Depth of investigation in electromagnetic sounding methods. *Geophysics*, 54(7), 872-888. doi:10.1190/1.1442716

## Read a negative transient or an anomalously slow late decay as polarisation or superparamagnetism, not as resistivity structure

Stage: B | Step: B3 | Methods: tdem

A layered resistivity model without dispersion cannot fit a sign reversal in a coincident-loop or
central-loop transient. Flis, Newman and Hohmann reproduced such reversals by giving the ground a
Cole-Cole chargeability: a polarisation current charges during the early transient and discharges
later, with the opposite sign to the induced eddy current. Over conductive ground the polarisation
current may never show; over moderately conductive ground it can dominate. Kaminski and Viezzoli
found IP effects increasingly evident in helicopter TEM as signal-to-noise improves, often as
negative voltages but sometimes as subtler distortions of the positive transient, and fitted them by
inverting for all four Cole-Cole parameters (resistivity, chargeability, relaxation time and
frequency exponent).

Superparamagnetic soils produce the opposite symptom. Buselli traced an anomalous late transient
over lateritic cover to superparamagnetic grains: the induced voltage decays as t^-1, the apparent
resistivity falls at late times where the geology says it should rise toward basement, and the
effect comes from within about 3 m of the transmitter loop, so it is seen only when the receiver is
close to the transmitter. He noted that it affects frequency-domain systems as well.

Both effects are routinely absorbed by non-physical fixes: dropping the negative gates, taking
absolute values, or letting a resistivity-only inversion invent a deep conductor for a slow decay or
a resistive basement for a depressed one. The positive gates next to a reversal are distorted too,
so removing only the negative ones does not leave a clean sounding.

**Check.** After the noise-floor cut, count the soundings with a sign change and map them; spatial
clustering points to the ground, isolated cases to noise. For positive late gates, fit the log-log
slope: a sustained slope near t^-1 over several gates, on weathered or lateritic cover, flags
superparamagnetism. Flagged soundings are either inverted with a dispersive (Cole-Cole) model or
excluded and reported, not refitted with resistivity alone.

**Sources.**
- Flis, M. F., Newman, G. A., & Hohmann, G. W. (1989). Induced-polarization effects in time-domain electromagnetic measurements. *Geophysics*, 54(4), 514-523. doi:10.1190/1.1442678
- Kaminski, V., & Viezzoli, A. (2017). Modeling induced polarization effects in helicopter time-domain electromagnetic data: Field case studies. *Geophysics*, 82(2), B49-B61. doi:10.1190/geo2016-0103.1
- Buselli, G. (1982). The effect of near-surface superparamagnetic material on electromagnetic measurements. *Geophysics*, 47(9), 1315-1324. doi:10.1190/1.1441392

## Report the depth of investigation from the final model's sensitivity and the data noise, and cut the model there

Stage: C | Step: C1 | Methods: tdem

For a diffusive method there is no depth below which the data say nothing at all, so a depth of
investigation is a statement of how deep the model can be trusted. Christiansen and Auken proposed a
measure computed from the inversion's own output: the sensitivity (Jacobian) matrix recalculated at
the final model, using the actual system response rather than plane waves over a half-space, with
the data noise and the number of data built in. Their threshold is global and absolute, not a
percentage of the largest sensitivity, so the depths are comparable from one sounding to the next.
The familiar skin-depth estimate assumes exactly the plane-wave, uniform-ground picture that this
replaces.

Spies gives the scaling that explains why the number varies. For TEM a buried inhomogeneity is
detectable under about one diffusion depth of overburden; for a conventional voltage (impulse
response) receiver the depth of investigation grows only as the one-fifth power of source moment and
ground resistivity, while for a magnetometer (step response) receiver it grows as the one-third
power of moment and no longer depends on resistivity. Conductive cover and a noisy site both make
it shallower.

Below that depth a smooth inversion returns whatever the regularisation and the starting model
supply, and it renders exactly like resolved ground. Delivered airborne models often mark those
cells with a sentinel value or grey them, and any statistic over a section has to leave them out.

**Check.** At the final model, recompute the Jacobian, weight each row by that datum's standard
deviation, sum the absolute sensitivity per layer, accumulate it from the bottom up, and report the
depth where the cumulative value crosses one fixed threshold used for every sounding. Mask the model
below it and report the fraction of the section that was masked.

**Sources.**
- Christiansen, A. V., & Auken, E. (2012). A global measure for depth of investigation. *Geophysics*, 77(4), WB171-WB177. doi:10.1190/geo2011-0393.1
- Spies, B. R. (1989). Depth of investigation in electromagnetic sounding methods. *Geophysics*, 54(7), 872-888. doi:10.1190/1.1442716

## Read a thin layer by what the data fix, usually its conductance, and do not take interface depths from a smooth model alone

Stage: C | Step: none | Methods: tdem

Layered TEM models are not unique. Mallick and Verma computed equivalent three-layer models and
found that for a conductive middle layer (H-type) the early part of the transient separates the
true model from its equivalents only partly and the ambiguity persists at late times, while for a
resistive middle layer (K-type) the true and equivalent models cannot be told apart over the whole
sampling period. In both cases a combination of the middle layer's thickness and resistivity is
what the data constrain, not the two separately. That is why a thin conductor is reported by its
conductance and why a thin resistor between conductors is close to invisible to TEM.

The choice of inversion style decides which non-uniqueness shows. Vignoli and co-authors note that
smooth, Occam-type inversions with a fixed vertical discretisation cannot reproduce sharp horizontal
boundaries, while few-layer inversions with free thicknesses can but require choosing a number of
layers, which is hard to justify across a large survey; they propose a focusing regularisation that
favours few resistivity changes. A boundary read from a smooth model is where the regulariser spread
a gradient; a layer resistivity from a few-layer model depends on how many layers were allowed.

Minsley, Foks and Bedrosian address the same problem by sampling: a trans-dimensional Bayesian
inversion lets the number of layers be an unknown, returns a distribution of models for time- or
frequency-domain AEM, and can also solve for data errors and instrument-height corrections.

**Check.** On five to twenty representative soundings, run a smooth and a few-layer (or sharp)
inversion to the same misfit and compare interface depths and layer resistivities. For the
few-layer run report the uncertainty of each layer's thickness, resistivity and their ratio from the
posterior covariance or an ensemble. Where thickness and resistivity are loose but their ratio is
tight, read conductance; where the two styles place an interface differently by more than the layer
thickness, do not read the interface depth.

**Sources.**
- Mallick, K., & Verma, R. K. (1979). Time-domain electromagnetic sounding: Computation of multi-layer response and the problem of equivalence in interpretation. *Geophysical Prospecting*, 27(1), 137-155. doi:10.1111/j.1365-2478.1979.tb00962.x
- Vignoli, G., Fiandaca, G., Christiansen, A. V., Kirkegaard, C., & Auken, E. (2015). Sharp spatially constrained inversion with applications to transient electromagnetic data. *Geophysical Prospecting*, 63(1), 243-255. doi:10.1111/1365-2478.12185
- Minsley, B. J., Foks, N. L., & Bedrosian, P. A. (2020). Quantifying model structural uncertainty using airborne electromagnetic data. *Geophysical Journal International*, 224(1), 590-607. doi:10.1093/gji/ggaa393

## Constrain neighbouring soundings to each other rather than inverting each alone, and measure what the constraint changes

Stage: A | Step: A11 | Methods: tdem

Soundings inverted one at a time each carry their own equivalence and their own noise, so a line of
them scatters from sounding to sounding in ways the ground does not. Viezzoli and co-authors'
spatially constrained inversion ties the model parameters of nearest neighbours (found by Delaunay
triangulation, so the constraints adapt to data density) and inverts data, models and constraints
as one system. Information then migrates sideways and resolves layers that are poorly resolved
locally, and the elongated artefacts typical of line-by-line interpretation are suppressed. Auken and
co-authors used laterally constrained inversion of TEM data to study how well buried valleys are
resolved.

The constraint is a prior. It smooths lateral change by design, its strength is somebody's choice,
and the method was presented for sedimentary settings where layers are laterally continuous. Across
steep valley flanks or faults it can smear a real edge, and a 1D forward model there is itself an
approximation. Vignoli and co-authors show that focusing regularisation can be applied horizontally
to keep lateral boundaries such as faults.

**Check.** Invert one representative line both independently and with lateral constraints and
report both misfits. Where the constrained misfit rises in a local cluster of soundings while the
independent fits stay good, the constraint is fighting real lateral change or 3D structure there.
Record the constraint's value and its distance scaling with the run.

**Sources.**
- Viezzoli, A., Christiansen, A. V., Auken, E., & Sørensen, K. (2008). Quasi-3D modeling of airborne TEM data by spatially constrained inversion. *Geophysics*, 73(3), F105-F113. doi:10.1190/1.2895521
- Auken, E., Christiansen, A. V., Jacobsen, L. H., & Sørensen, K. I. (2008). A resolution study of buried valleys using laterally constrained inversion of TEM data. *Journal of Applied Geophysics*, 65(1), 10-20. doi:10.1016/j.jappgeo.2008.03.003
- Vignoli, G., Fiandaca, G., Christiansen, A. V., Kirkegaard, C., & Auken, E. (2015). Sharp spatially constrained inversion with applications to transient electromagnetic data. *Geophysical Prospecting*, 63(1), 243-255. doi:10.1111/1365-2478.12185

## For airborne TEM, correct the altimeter for tilt, measure the height twice on one vertical datum, and treat it as uncertain

Stage: A | Step: A8 | Methods: tdem

An airborne TEM forward model needs the transmitter and receiver height and attitude at every
sounding. Christiansen, Auken and Viezzoli found that errors in altitude and geometry act mainly on
the late gates, so a height error does not stay in the shallow model. In the SkyTEM processing
scheme of Auken and co-authors the frame's inclinometer data are used to correct the laser altimeter
readings to the vertical and to apply an approximate correction of the EM data for transmitter pitch
and roll.

There are usually two independent heights, and they disagree for known reasons. A laser altimeter
returns the distance to whatever it hits first, which over forest or buildings is less than the
height above ground. A GPS elevation minus a terrain model depends on both being on the same
vertical datum: Li and Götze point out that GPS delivers height above the ellipsoid, whereas
levelling and most terrain models give height above the geoid, and the two differ by the geoid
undulation, which is tens of metres over much of the world.

Height can also be left free in the inversion; Minsley, Foks and Bedrosian solve for corrections to
the measured instrument height. A recovered correction is a rescuing parameter and has to be reported
with its value and the range it was allowed.

**Check.** Per flight line, compute the tilt-corrected laser height and GPS height minus the
terrain model after putting both on one vertical datum, and map the difference. A constant offset
is a datum or antenna-offset error; a patchy offset that follows forest or towns is the laser
reflecting above ground. If height is inverted, report the recovered departure from the measured
height against the altimeter's stated accuracy.

**Sources.**
- Christiansen, A. V., Auken, E., & Viezzoli, A. (2011). Quantification of modeling errors in airborne TEM caused by inaccurate system description. *Geophysics*, 76(1), F43-F52. doi:10.1190/1.3511354
- Auken, E., Christiansen, A. V., Westergaard, J. H., Kirkegaard, C., Foged, N., & Viezzoli, A. (2009). An integrated processing scheme for high-resolution airborne electromagnetic surveys, the SkyTEM system. *Exploration Geophysics*, 40(2), 184-192. doi:10.1071/EG08128
- Li, X., & Götze, H.-J. (2001). Ellipsoid, geoid, gravity, geodesy, and geophysics. *Geophysics*, 66(6), 1660-1668. doi:10.1190/1.1487109
- Minsley, B. J., Foks, N. L., & Bedrosian, P. A. (2020). Quantifying model structural uncertainty using airborne electromagnetic data. *Geophysical Journal International*, 224(1), 590-607. doi:10.1093/gji/ggaa393

## Check the system against a reference site and against boreholes whose quality has been rated first

Stage: B | Step: B7 | Methods: tdem

A gain or timing error in a TEM system shifts every sounding the same way (Christiansen, Auken and
Viezzoli found amplitude, gain and current errors affect the entire sounding), and a model fitted to
those data converges and looks plausible. Foged and co-authors describe the Danish TEM test site
and a calibration scheme recommended for ground and airborne systems: reference sections from
ground-based measurements, and airborne data compared with them both as models and gate by gate in
data space. For a well-calibrated helicopter system, repeated flights at different heights and
directions agreed within the data standard deviation, and the airborne data matched the ground
reference data generally within 1.5 times that standard deviation.

Boreholes are the other outside reference, and they have their own errors. Schamper and co-authors
compared early-time helicopter TEM with borehole logs and found that about three-quarters of the
boreholes within 15 m of a sounding matched the EM result; of the remaining quarter, half were
boreholes of very poor quality or with inaccurate coordinates, and only a few mismatches were due to
strong lateral or vertical geological variation. A borehole disagreement is first a question about
the borehole.

**Check.** If the survey crossed a reference site or repeated a line, difference the repeated or
reference transients gate by gate in units of their standard deviation; a consistent departure
above about 1.5 standard deviations in level is calibration, in time is timing, and both are fixed
before inversion. For boreholes, restrict the comparison to a stated distance, rate each borehole's
quality and position first, and report the match rate per quality class.

**Sources.**
- Foged, N., Auken, E., Christiansen, A. V., & Sørensen, K. I. (2013). Test-site calibration and validation of airborne and ground-based TEM systems. *Geophysics*, 78(2), E95-E106. doi:10.1190/geo2012-0244.1
- Schamper, C., Jørgensen, F., Auken, E., & Effersø, F. (2014). Assessment of near-surface mapping capabilities by airborne transient electromagnetic data: An extensive comparison to conventional borehole data. *Geophysics*, 79(4), B187-B199. doi:10.1190/geo2013-0256.1
- Christiansen, A. V., Auken, E., & Viezzoli, A. (2011). Quantification of modeling errors in airborne TEM caused by inaccurate system description. *Geophysics*, 76(1), F43-F52. doi:10.1190/1.3511354
