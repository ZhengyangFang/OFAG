# Agent procedure

This public procedure defines the generic checks used to brief OFAG agents. Project-specific measurements and research records are supplied separately by the project owner.

## A. Before an inversion

### A1. Check units

Read each file's declared units, convert once at the import boundary, and compare a derived quantity with a plausible range before running an inversion.

### A2. Check conventions

Verify signs, axes, coordinate systems, and engine conventions against an independent calculation or a documented standard.

### A3. Check acquisition parameters

Read instrument geometry, timing, and waveform parameters from the input and confirm that the forward model uses the same values.

### A4. Separate repeatability and model error

Estimate observation uncertainty from repeats or documented measurement limits. Keep model inadequacy separate from measurement noise.

### A5. Set uncertainty before fitting

Set the uncertainty model from measurements or a stated assumption before viewing the inversion misfit.

### A6. Check quality filters

Measure which observations a quality rule removes and whether the retained set still covers the intended survey area.

### A7. Check discretisation

Compare mesh dimensions and time or frequency sampling with the data bandwidth and the intended model scale.

### A8. Compare duplicate fields

When two sources state the same quantity, compare them explicitly and record the chosen source before processing.

### A9. Run inexpensive checks first

Perform schema, domain, and unit checks before expensive forward or inverse calculations.

### A10. Read format declarations

Parse a file's own header and metadata rather than assuming that a familiar layout has familiar units or columns.

### A11. Measure parameter effects

Test how a proposed setting changes data fit and model behaviour on a small sample before using it broadly.

### A12. Check terrain assumptions

Measure ground elevation across the model area before choosing a flat or terrain-following geometry.

### A13. Resolve identifiers

Verify dataset identifiers and citations against their original source before including them in a project record.

### A14. Match evidence to claims

State what each observation measures and avoid assigning it a resolution or physical meaning it does not support.

### A15. Review defaults

Record library defaults that affect physics, uncertainty, regularization, or stopping behaviour.

## B. After a difficult fit

### B1. Fit a simple model

Fit a low-dimensional model to check whether the data and uncertainty can support the requested complexity.

### B2. Vary starts and regularization

Use controlled changes to initial conditions and regularization to separate optimizer behaviour from data support.

### B3. Inspect residual structure

Map residuals by location, channel, time, or frequency and identify systematic patterns.

### B4. Review uncertainty

Check whether the chosen error bars explain the reported normalized misfit.

### B5. Bound explanations

Test suspected physical explanations against independent magnitude and geometry constraints.

### B6. Compare implementations

Where feasible, compare a small forward problem with an independent implementation or analytic solution.

### B7. Use held-out evidence

Compare interpretations with data that did not drive the inversion.

## C. Before interpretation

### C1. Measure resolved depth

Use sensitivity or coverage information to identify the part of a model constrained by observations.

### C2. Test estimators

Check interpolation, classification, and aggregation methods on known examples before using their output for interpretation.

### C3. Define regions completely

Record every threshold and coordinate convention used to select an interpretation region.

### C4. Sample the workflow

Run a small end-to-end sample before a full project calculation and inspect all intermediate units.

### C5. Record negative checks

Distinguish a completed check with a negative result from a check that has not been run.
