"""Compact measured quality summaries, without inventing a universal fit threshold."""

from typing import Any


def quality_summary(summary: dict[str, Any]) -> str:
    parts = []
    fitted, total = summary.get("soundings_fitting"), summary.get("sounding_count")
    if isinstance(fitted, (int, float)) and isinstance(total, (int, float)) and total > 0:
        parts.append(f"Fit {int(fitted)}/{int(total)} ({fitted / total:.0%})")
    for key, label in (
        ("chi_squared", "χ²"),
        ("chi_squared_median", "Median χ²"),
        ("chi_squared_worst", "Worst χ²"),
        ("rms", "RMS"),
    ):
        value = summary.get(key)
        if isinstance(value, (int, float)):
            parts.append(f"{label} {value:.3g}")
    return " · ".join(parts) or "Quality not reported"
