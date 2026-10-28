"""Show one filtered register as text, a table, a chart, a file, or an image.

The numbers come from the same Frappe filters as the written summary.
A generated file is a private file the chat can open.
"""

from __future__ import annotations

import io
import re

from erpnext_ai_assistant.services.arabic import normalize_arabic

_TEXT_PHRASES = ("as text", "كنص", "نص فقط")


def output_formats(text: str | None) -> set[str]:
	"""Which views this message asks for. A normal question stays text."""
	raw = text or ""
	if "\n" in raw:
		raw = raw.strip().split("\n")[-1]
	norm = normalize_arabic(raw)
	found: set[str] = set()
	if any(token in norm for token in ("chart", "graph", "مخطط", "رسم بياني")):
		found.add("chart")
	if "table" in norm or "جدول" in norm:
		found.add("table")
	if "csv" in norm:
		found.add("csv")
	if any(token in norm for token in ("اكسل", "excel", "xlsx")):
		found.add("xlsx")
	if any(token in norm for token in ("تصدير", "اصدر", "export", "download", "spreadsheet")):
		found.update({"csv", "xlsx"})
	if any(token in norm for token in ("صورة", "صوره", "image", "png")):
		found.add("image")
	if any(token in norm for token in _TEXT_PHRASES) or re.search(r"(?<!\w)text(?!\w)", norm):
		found.add("text")
	if not found:
		found.add("text")
	return found


def is_format_followup(text: str | None) -> bool:
	"""True when the user only changed the view and did not name a new DocType."""
	from erpnext_ai_assistant.services.targeting import match_doctype

	if match_doctype(text):
		return False
	formats = output_formats(text)
	if formats != {"text"}:
		return True
	norm = normalize_arabic(text)
	return any(token in norm for token in _TEXT_PHRASES)


def chart_marker(chart: dict) -> str:
	pairs = []
	labels = chart.get("labels") or []
	values = chart.get("values") or []
	for label, value in list(zip(labels, values))[:12]:
		safe = str(label).replace("|", " ").replace(";", " ").replace("=", " ").strip() or "—"
		try:
			number = float(value)
		except (TypeError, ValueError):
			number = 0
		shown = int(number) if number == int(number) else round(number, 2)
		pairs.append(f"{safe}={shown}")
	title = str(chart.get("title") or "Chart").replace("|", " ")
	kind = chart.get("type") if chart.get("type") in ("bar", "pie", "line", "kpi") else "bar"
	return f"[[chart:{kind}|{title}|{';'.join(pairs)}]]"


def table_markdown(doctype: str, text: str | None, lang: str) -> str:
	rows, plan = _grouped(doctype, text)
	if not rows:
		return ""
	name_h = "الاسم" if lang == "ar" else "Name"
	status_h = "الحالة" if lang == "ar" else "Status"
	count_h = "العدد" if lang == "ar" else "Count"
	amount_h = "المبلغ" if lang == "ar" else "Amount"
	header = [name_h]
	if plan.get("select"):
		header.append(status_h)
	header.append(count_h)
	if plan.get("amount"):
		header.append(amount_h)
	lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
	for row in rows[:40]:
		cells = [_cell(row.get("_name"))]
		if plan.get("select"):
			cells.append(_cell(row.get("_status")))
		cells.append(str(int(row.get("_count") or 0)))
		if plan.get("amount"):
			cells.append(f"{float(row.get('_amount') or 0):,.2f}")
		lines.append("| " + " | ".join(cells) + " |")
	return "\n".join(lines)


def chart_for(doctype: str, text: str | None, lang: str) -> dict | None:
	from erpnext_ai_assistant.services.charts.build import build_chart
	from erpnext_ai_assistant.services.targeting import _tr

	rows, plan = _grouped(doctype, text)
	if not rows:
		return None
	totals: dict[str, float] = {}
	for row in rows:
		key = row.get("_name") or "—"
		value = float(row.get("_amount") or 0) if plan.get("amount") else float(row.get("_count") or 0)
		totals[key] = totals.get(key, 0) + value
	ranked = sorted(totals.items(), key=lambda item: -item[1])[:12]
	if not ranked:
		return None
	label = _tr(doctype, lang) or doctype
	title = f"{label} — {'المبلغ' if plan.get('amount') and lang == 'ar' else 'Amount' if plan.get('amount') else 'العدد' if lang == 'ar' else 'Count'}"
	kind = "pie" if len(ranked) <= 6 else "bar"
	return build_chart(kind, title, [name for name, _value in ranked], [value for _name, value in ranked])


def image_file(chart: dict, lang: str) -> dict | None:
	"""A PNG of the chart, stored as a private file."""
	try:
		from PIL import Image, ImageDraw, ImageFont
	except Exception:
		return None
	labels = [str(label) for label in (chart.get("labels") or [])][:12]
	values = []
	for value in (chart.get("values") or [])[:12]:
		try:
			values.append(float(value))
		except (TypeError, ValueError):
			values.append(0.0)
	if not labels or not values:
		return None
	width, height = 880, 460
	image = Image.new("RGB", (width, height), "#ffffff")
	draw = ImageDraw.Draw(image)
	font = _font(16)
	small = _font(13)
	title = str(chart.get("title") or "")[:80]
	draw.text((24, 16), title, fill="#0f1b2e", font=font)
	max_value = max(values) or 1
	top, bottom = 56, height - 36
	plot_h = bottom - top
	gap = 12
	bar_w = max(18, int((width - 48 - gap * (len(values) + 1)) / len(values)))
	for index, value in enumerate(values):
		bar_h = int(plot_h * (value / max_value))
		x = 24 + gap + index * (bar_w + gap)
		y = bottom - bar_h
		draw.rectangle([x, y, x + bar_w, bottom], fill="#1d4e89")
		shown = str(int(value)) if value == int(value) else f"{value:.0f}"
		draw.text((x, max(top, y - 18)), shown, fill="#334155", font=small)
	from erpnext_ai_assistant.services.sheets import _store

	buffer = io.BytesIO()
	image.save(buffer, format="PNG")
	label = "فتح الصورة" if lang == "ar" else "Open image"
	return _store("chart.png", buffer.getvalue(), label)


def _grouped(doctype: str, text: str | None):
	import frappe
	from erpnext_ai_assistant.services.targeting import _query_filters, _sql_groups, _summary_plan

	meta = frappe.get_meta(doctype)
	plan = _summary_plan(meta)
	filters, _note, problem, empty = _query_filters(doctype, plan, text, "en")
	if problem or empty:
		return [], plan
	raw = _sql_groups(doctype, meta, plan, filters) or []
	rows = []
	for row in raw:
		rows.append(
			{
				"_name": row.get(plan.get("group_name")) or row.get(plan.get("group")) or row.get("name") or "—",
				"_status": row.get(plan.get("select")) or "",
				"_count": row.get("total") or 0,
				"_amount": row.get("amount") or 0,
			}
		)
	return rows, plan


def _cell(value) -> str:
	return str(value or "—").replace("|", " ").replace("\n", " ")


def _font(size: int):
	from PIL import ImageFont

	for path in (
		"/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
		"/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
	):
		try:
			return ImageFont.truetype(path, size)
		except Exception:
			continue
	return ImageFont.load_default()
