"""Translated label index for DocType and field names.

The on-disk JSON is the only index. Turtle is written only when a System
Manager passes force_ttl. Business records are never stored here.
"""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic, strip_al
from erpnext_ai_assistant.services.schema import DENIED_DOCTYPES

_LAYOUT = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Fold", "Heading"}
_LEAD_ALIASES = ("اسم", "الاسم", "الاسم الكامل", "اسم العميل", "name")
_LEAD_FIELDS = ("lead_name", "first_name", "last_name")


def _graph_file() -> Path:
	"""Path for the current site. Always include frappe.local.site in the path."""
	site = getattr(frappe.local, "site", None) or ""
	sites_path = getattr(frappe.local, "sites_path", None) or "."
	return Path(sites_path) / site / "private" / "files" / "erp_ai_rdf.json"


def _cache_key() -> str:
	return f"erp_ai_rdf_index:{getattr(frappe.local, 'site', '')}"


def _empty_index() -> dict:
	return {"version": 2, "fields": {}, "doctypes": {}}


def _field_index(index: dict | None) -> dict:
	if not isinstance(index, dict):
		return {}
	fields = index.get("fields")
	if isinstance(fields, dict):
		return fields
	# Legacy flat map: label -> list of rows.
	return {key: rows for key, rows in index.items() if isinstance(rows, list)}


def _doctype_index(index: dict | None) -> dict:
	if not isinstance(index, dict):
		return {}
	rows = index.get("doctypes")
	return rows if isinstance(rows, dict) else {}


def _app_for_doctype(doctype: str) -> str:
	try:
		return frappe.get_doctype_app(doctype) or ""
	except Exception:
		return ""


def _translation_forward() -> dict[str, list[str]]:
	"""English source (context stripped) -> Arabic strings."""
	try:
		raw = frappe.translate.get_all_translations("ar") or {}
	except Exception:
		raw = {}
	forward: dict[str, list[str]] = {}
	for raw_source, translated in raw.items():
		if not raw_source or not translated:
			continue
		source = str(raw_source).split(":", 1)[0].strip()
		key = normalize_arabic(source)
		if not key:
			continue
		bucket = forward.setdefault(key, [])
		text = str(translated).strip()
		if text and text not in bucket:
			bucket.append(text)
	return forward


def _add_label(bucket: dict, label: str, row: dict) -> None:
	key = normalize_arabic(label)
	if not key or len(key) < 2:
		return
	ident = (row["doctype"], row.get("fieldname") or "")
	slot = bucket.setdefault(key, {})
	previous = slot.get(ident)
	if not previous or row.get("boost"):
		slot[ident] = row
	stripped = strip_al(key)
	if stripped and stripped != key and len(stripped) >= 2:
		slot2 = bucket.setdefault(stripped, {})
		previous2 = slot2.get(ident)
		if not previous2 or row.get("boost"):
			slot2[ident] = row


def rebuild_rdf_graph(doctypes: list[str] | None = None, force_ttl: bool = False) -> dict:
	"""Index every non-child DocType, or the list passed in (tests and partial builds)."""
	if doctypes is None:
		names = frappe.get_all(
			"DocType",
			filters={"istable": 0},
			pluck="name",
			limit_page_length=5000,
		)
	else:
		names = list(doctypes)
	forward = _translation_forward()
	bucket: dict[str, dict] = {}
	doctype_rows: dict[str, dict] = {}
	for dt in names:
		if not dt or dt in DENIED_DOCTYPES:
			continue
		if not frappe.db.exists("DocType", dt):
			continue
		try:
			meta = frappe.get_meta(dt)
		except Exception:
			continue
		if getattr(meta, "istable", 0):
			continue
		module = getattr(meta, "module", None) or ""
		app = _app_for_doctype(dt)
		labels = [dt]
		for translated in forward.get(normalize_arabic(dt), []):
			labels.append(translated)
		# DocType-level keys stay out of the field map so lookup stays field-only.
		seen_labels = []
		for label in labels:
			if label and label not in seen_labels:
				seen_labels.append(label)
		doctype_rows[dt] = {"module": module, "app": app, "labels": seen_labels}
		for df in meta.fields:
			if not df.fieldname or df.fieldtype in _LAYOUT:
				continue
			row = {
				"doctype": dt,
				"fieldname": df.fieldname,
				"label": df.label or df.fieldname,
				"fieldtype": df.fieldtype,
			}
			_add_label(bucket, df.label or "", row)
			_add_label(bucket, df.fieldname, row)
			for translated in forward.get(normalize_arabic(df.label or ""), []):
				_add_label(bucket, translated, row)
			if dt in ("CRM Lead", "Lead") and df.fieldname in _LEAD_FIELDS:
				boosted = dict(row)
				boosted["boost"] = 1
				for alias in _LEAD_ALIASES:
					_add_label(bucket, alias, boosted)

	fields = {key: list(rows.values()) for key, rows in bucket.items()}
	index = {"version": 2, "fields": fields, "doctypes": doctype_rows}
	if force_ttl:
		_write_turtle(fields)
	path = _graph_file()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(index, ensure_ascii=False))
	frappe.cache().set_value(_cache_key(), index)
	try:
		from erpnext_ai_assistant.services.doctype_catalog import clear_doctype_catalog

		clear_doctype_catalog()
	except Exception:
		pass
	return {"keys": len(fields), "doctypes": len(doctype_rows), "path": str(path)}


def _write_turtle(fields: dict) -> None:
	from urllib.parse import quote

	from rdflib import Graph, Literal, Namespace, URIRef

	graph = Graph()
	ns = Namespace("urn:erpnext-ai-assistant:")
	for key, rows in fields.items():
		for row in rows:
			frag = quote(f"{row['doctype']}/{row['fieldname']}", safe="/_")
			subject = URIRef(str(ns) + frag)
			graph.add((subject, ns.label, Literal(key)))
			graph.add((subject, ns.doctype, Literal(row["doctype"])))
			graph.add((subject, ns.fieldname, Literal(row["fieldname"])))
	ttl = graph.serialize(format="turtle")
	Path(frappe.get_site_path("private", "files", "erp_ai_rdf.ttl")).write_text(ttl)


def _load_index() -> dict:
	cached = frappe.cache().get_value(_cache_key())
	if isinstance(cached, dict) and cached:
		return cached
	path = _graph_file()
	if path.exists():
		try:
			index = json.loads(path.read_text())
		except Exception:
			index = _empty_index()
		if isinstance(index, dict):
			frappe.cache().set_value(_cache_key(), index)
			return index
	return _empty_index()


def labels_for_doctype(doctype: str) -> list[str]:
	row = _doctype_index(_load_index()).get(doctype) or {}
	labels = row.get("labels") or []
	return [label for label in labels if label]


def doctype_app(doctype: str) -> str:
	row = _doctype_index(_load_index()).get(doctype) or {}
	return row.get("app") or ""


def field_aliases(doctype: str) -> dict[str, list[str]]:
	"""fieldname -> normalized label keys from the index."""
	out: dict[str, list[str]] = {}
	for key, rows in _field_index(_load_index()).items():
		for row in rows:
			if row.get("doctype") != doctype or not row.get("fieldname"):
				continue
			bucket = out.setdefault(row["fieldname"], [])
			if key not in bucket:
				bucket.append(key)
	return out


def lookup(query: str, doctype: str | None = None) -> list[dict]:
	fields = _field_index(_load_index())
	q = normalize_arabic(query)
	q_stripped = strip_al(q)
	hits = []
	for key in {q, q_stripped}:
		if not key:
			continue
		for row in fields.get(key, []):
			if doctype and row.get("doctype") != doctype:
				continue
			hits.append(row)
	if not hits and q:
		for key, rows in fields.items():
			if q in key or key in q or (q_stripped and (q_stripped in key or key in q_stripped)):
				for row in rows:
					if doctype and row.get("doctype") != doctype:
						continue
					hits.append(row)
	seen = set()
	out = []
	for hit in sorted(hits, key=lambda row: int(row.get("boost") or 0), reverse=True):
		ident = (hit.get("doctype"), hit.get("fieldname"))
		if not ident[1] or ident in seen:
			continue
		seen.add(ident)
		if not _can_see(hit["doctype"]):
			continue
		if not _can_read_field(hit["doctype"], hit["fieldname"]):
			continue
		out.append(
			{
				"doctype": hit["doctype"],
				"fieldname": hit["fieldname"],
				"label": hit.get("label"),
				"fieldtype": hit.get("fieldtype"),
			}
		)
	return out[:20]


def _can_see(doctype: str) -> bool:
	return bool(frappe.has_permission(doctype, "read") or frappe.has_permission(doctype, "create"))


def _can_read_field(doctype: str, fieldname: str) -> bool:
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return False
	permitted = set(meta.get_permitted_fieldnames(permission_type="read") or [])
	if not permitted:
		return True
	return fieldname in permitted


def enqueue_rdf_rebuild(doc=None, method=None):
	"""Translation and Custom Field changes rebuild in the background."""
	try:
		from erpnext_ai_assistant.services.doctype_catalog import clear_doctype_catalog

		clear_doctype_catalog()
	except Exception:
		pass
	try:
		frappe.enqueue(
			"erpnext_ai_assistant.services.rdf.graph.rebuild_rdf_graph",
			queue="long",
			timeout=900,
			enqueue_after_commit=True,
			job_id="erp_ai_rdf_rebuild",
			deduplicate=True,
		)
	except Exception:
		frappe.log_error(title="ERP AI RDF enqueue")


def on_custom_field_change(doc, method=None):
	enqueue_rdf_rebuild(doc, method)
