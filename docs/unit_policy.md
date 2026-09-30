# OFAG Unit Policy

OFAG accepts quantities only with explicit units and converts at import boundaries
into the project standard for that physical quantity. The global UnitRegistry in `ofag.core.units` is the sole source
of conversion. Unit conversion is never inferred from magnitude or column names.

| Quantity type | Canonical unit |
| --- | --- |
| length, elevation, depth, cell size | m |
| time | s |
| angle | rad |
| conductivity | S/m |
| density contrast | g/cm³ |
| gravity acceleration | mGal |
| magnetic flux density | T |
| magnetic anomaly (TMI) | nT |
| susceptibility, normalized residual | dimensionless |

`z` is elevation positive upward; `depth` is positive downward below a reference
surface. A numeric geographic CRS cannot create a mesh until it is explicitly
projected. `LOCAL_CARTESIAN_METRIC` is valid only for labeled synthetic data.

Engine conversions are adapter-only. Public schemas and artifacts use the
project standard for their physical quantity: gravity stays in mGal and density
contrast stays in g/cm³, while other quantities retain their own documented
standards.
