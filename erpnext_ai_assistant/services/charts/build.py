"""Build chart payloads (SVG rendered in the panel; plain JS only)."""

from __future__ import annotations

from typing import Any


def build_chart(
	chart_type: str,
	title: str,
	labels: list[str] | None = None,
	values: list[float] | None = None,
	value: float | None = None,
) -> dict[str, Any]:
	chart_type = (chart_type or "bar").lower()
	if chart_type not in ("bar", "line", "pie", "kpi"):
		chart_type = "bar"

	labels = [str(x) if x is not None else "—" for x in (labels or [])]
	raw_values = list(values or [])
	norm_values: list[float] = []
	for v in raw_values:
		try:
			norm_values.append(float(v))
		except (TypeError, ValueError):
			norm_values.append(0.0)

	# Align lengths
	while len(labels) < len(norm_values):
		labels.append(f"#{len(labels) + 1}")
	while len(norm_values) < len(labels):
		norm_values.append(0.0)

	# Sort bar/pie by value desc so dominant categories are clear
	if chart_type in ("bar", "pie") and labels:
		paired = sorted(zip(labels, norm_values), key=lambda x: -x[1])
		labels = [p[0] for p in paired]
		norm_values = [p[1] for p in paired]

	payload: dict[str, Any] = {
		"type": chart_type,
		"title": title or "",
		"labels": labels,
		"values": norm_values,
	}
	if chart_type == "kpi":
		payload["value"] = value if value is not None else (norm_values[0] if norm_values else 0)
	return payload
