"""Document names come from the Title (or Persona Name) field. No naming series."""

from __future__ import annotations

import re

import frappe


def as_title(doctype: str, base: str | None) -> str:
	"""Return a unique Title that will also be the document name."""
	text = re.sub(r"[#/?%\\]+", " ", (base or "").strip())
	text = " ".join(text.split())[:120] or doctype
	name = text
	n = 2
	while frappe.db.exists(doctype, name):
		suffix = f" ({n})"
		name = text[: 140 - len(suffix)].rstrip() + suffix
		n += 1
		if n > 40:
			break
	return name
