"""RDF field graph via rdflib — maps Arabic/English labels to DocType fieldnames."""

from __future__ import annotations

import json
from pathlib import Path

import frappe
from erpnext_ai_assistant.services.arabic import normalize_arabic

GRAPH_PATH = None


def _graph_file() -> Path:
	global GRAPH_PATH
	if GRAPH_PATH is None:
		site_path = Path(frappe.get_site_path("private", "files", "erp_ai_rdf.json"))
		GRAPH_PATH = site_path
	return GRAPH_PATH


def rebuild_rdf_graph(doctypes: list[str] | None = None) -> dict:
	"""Build a simple label→field map (JSON backed; rdflib used when available)."""
	targets = doctypes or [
		"CRM Lead",
		"CRM Deal",
		"Lead",
		"Customer",
		"Sales Invoice",
		"Purchase Invoice",
		"Employee",
		"Salary Slip",
		"Item",
		"Bin",
	]
	index: dict[str, list[dict]] = {}
	for dt in targets:
		if not frappe.db.exists("DocType", dt):
			continue
		try:
			meta = frappe.get_meta(dt)
		except Exception:
			continue
		for df in meta.fields:
			if not df.fieldname or df.fieldtype in ("Section Break", "Column Break", "Tab Break", "HTML"):
				continue
			labels = [df.label, df.fieldname]
			# Common Arabic aliases for CRM Lead name fields
			if dt in ("CRM Lead", "Lead") and df.fieldname in ("lead_name", "first_name", "last_name"):
				labels.extend(["اسم", "الاسم", "الاسم الكامل", "اسم العميل", "name"])
			for lab in labels:
				if not lab:
					continue
				key = normalize_arabic(lab)
				index.setdefault(key, []).append(
					{"doctype": dt, "fieldname": df.fieldname, "label": df.label, "fieldtype": df.fieldtype}
				)
	# Also store under raw fieldnames
	for dt in targets:
		if not frappe.db.exists("DocType", dt):
			continue
		try:
			meta = frappe.get_meta(dt)
		except Exception:
			continue
		for df in meta.fields:
			if df.fieldname:
				index.setdefault(normalize_arabic(df.fieldname), []).append(
					{"doctype": dt, "fieldname": df.fieldname, "label": df.label, "fieldtype": df.fieldtype}
				)

	# Optional rdflib triple dump for SM tooling
	try:
		from urllib.parse import quote

		from rdflib import Graph, Literal, Namespace, URIRef

		g = Graph()
		EX = Namespace("urn:erpnext-ai-assistant:")
		for key, rows in index.items():
			for row in rows:
				frag = quote(f"{row['doctype']}/{row['fieldname']}", safe="/_")
				s = URIRef(str(EX) + frag)
				g.add((s, EX.label, Literal(key)))
				g.add((s, EX.doctype, Literal(row["doctype"])))
				g.add((s, EX.fieldname, Literal(row["fieldname"])))
		ttl = g.serialize(format="turtle")
		Path(frappe.get_site_path("private", "files", "erp_ai_rdf.ttl")).write_text(ttl)
	except Exception:
		frappe.log_error(title="ERP AI rdflib serialize")

	path = _graph_file()
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps(index, ensure_ascii=False, indent=2))
	frappe.cache().set_value("erp_ai_rdf_index", index)
	return {"keys": len(index), "path": str(path)}


def _load_index() -> dict:
	cached = frappe.cache().get_value("erp_ai_rdf_index")
	if cached:
		return cached
	path = _graph_file()
	if path.exists():
		index = json.loads(path.read_text())
		frappe.cache().set_value("erp_ai_rdf_index", index)
		return index
	rebuild_rdf_graph()
	return frappe.cache().get_value("erp_ai_rdf_index") or {}


def lookup(query: str, doctype: str | None = None) -> list[dict]:
	index = _load_index()
	q = normalize_arabic(query)
	hits = []
	# exact key
	for row in index.get(q, []):
		if doctype and row["doctype"] != doctype:
			continue
		hits.append(row)
	# substring over keys
	if not hits:
		for key, rows in index.items():
			if q and (q in key or key in q):
				for row in rows:
					if doctype and row["doctype"] != doctype:
						continue
					hits.append(row)
	# Dedup
	seen = set()
	out = []
	for h in hits:
		k = (h["doctype"], h["fieldname"])
		if k in seen:
			continue
		seen.add(k)
		out.append(h)
	return out[:20]


def on_custom_field_change(doc, method=None):
	try:
		rebuild_rdf_graph()
	except Exception:
		frappe.log_error(title="ERP AI RDF custom field rebuild")
