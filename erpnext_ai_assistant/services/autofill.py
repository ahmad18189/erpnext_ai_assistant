"""Values ERPNext's own form fills before the user types anything.

A new Quotation in Desk already has the series, company, currency, price list and
exchange rates. The assistant fills the same values instead of asking a salesperson
for "Price List Exchange Rate". Business values (customer, items, quantities) are
never guessed: an item row is completed only from the Item the user named.
"""

from __future__ import annotations

import re

import frappe

_PRICE_LISTS = {
	"selling_price_list": ("Selling Settings", "selling_price_list"),
	"buying_price_list": ("Buying Settings", "buying_price_list"),
}


def fill_header(fields: list[dict], values: dict) -> list[dict]:
	"""Fill empty system fields in place. Returns [{label, value}] for what was filled."""
	by_name = {df["fieldname"]: df for df in fields}
	filled: list[dict] = []

	def put(fieldname: str, value) -> None:
		df = by_name.get(fieldname)
		if not df or df["read_only"] or values.get(fieldname) not in (None, "") or value in (None, ""):
			return
		values[fieldname] = value
		filled.append({"fieldname": fieldname, "label": df.get("label") or fieldname, "value": value})

	# "لشركة الأفق" is often read as the Company field; it is the customer. Keep only a real Company.
	if values.get("company") and not frappe.db.exists("Company", values["company"]):
		values.pop("company")
	for df in fields:
		if df["fieldtype"] == "Select" and df["reqd"]:
			options = [line.strip() for line in str(df.get("options") or "").split("\n") if line.strip()]
			if len(options) == 1:
				put(df["fieldname"], options[0])
		if df["fieldtype"] == "Link" and df.get("options") == "Company":
			put(df["fieldname"], default_company())
	company = values.get("company")
	company_currency = frappe.get_cached_value("Company", company, "default_currency") if company else None
	put("currency", company_currency or frappe.defaults.get_global_default("currency"))
	for fieldname, (settings, key) in _PRICE_LISTS.items():
		if fieldname in by_name:
			put(fieldname, frappe.db.get_single_value(settings, key))
	price_list = values.get("selling_price_list") or values.get("buying_price_list")
	price_currency = frappe.get_cached_value("Price List", price_list, "currency") if price_list else None
	put("price_list_currency", price_currency or values.get("currency"))
	# Same currency as the company: the rates are 1, exactly what the Desk form shows.
	if company_currency and values.get("currency") == company_currency:
		put("conversion_rate", 1)
	if company_currency and (values.get("price_list_currency") or price_currency) == company_currency:
		put("plc_conversion_rate", 1)
	return filled


def default_company() -> str | None:
	company = frappe.defaults.get_user_default("Company") or frappe.defaults.get_global_default("company")
	if company:
		return company
	names = frappe.get_list("Company", pluck="name", limit_page_length=2)
	return names[0] if len(names) == 1 else None


def fill_rows(children: list[dict], values: dict) -> list[str]:
	"""Complete item rows from the Item the user named: name, unit, factor, price, column defaults.

	Returns a problem line for each row whose item could not be found.
	"""
	problems: list[str] = []
	price_list = values.get("selling_price_list") or values.get("buying_price_list")
	row_dates = {field: values[field] for field in ("delivery_date", "schedule_date") if values.get(field)}
	for child in children:
		rows = values.get(child["fieldname"])
		if not isinstance(rows, list):
			continue
		child_meta = frappe.get_meta(child["child_doctype"])
		for row in rows:
			if not isinstance(row, dict):
				continue
			if not row.get("item_code") and row.get("item_name") and child_meta.has_field("item_code"):
				row["item_code"] = find_item(row["item_name"]) or None
				if not row["item_code"]:
					problems.append(f"No item matches \u201c{row['item_name']}\u201d. Send the item code or its exact name.")
			for field, value in row_dates.items():
				_put_row(child_meta, row, field, value)
			code = row.get("item_code")
			if code and frappe.db.exists("Item", code):
				item = frappe.get_cached_value("Item", code, ["item_name", "stock_uom", "description"], as_dict=True)
				if child_meta.has_field("item_name"):
					row["item_name"] = item.item_name  # the Item's own name, not what was typed
				_put_row(child_meta, row, "description", item.description or item.item_name)
				_put_row(child_meta, row, "uom", item.stock_uom)
				_put_row(child_meta, row, "stock_uom", item.stock_uom)
				_put_row(child_meta, row, "conversion_factor", 1)
				if price_list:
					rate = frappe.db.get_value("Item Price", {"item_code": code, "price_list": price_list}, "price_list_rate")
					_put_row(child_meta, row, "rate", rate)
			for cdf in child_meta.fields:
				if cdf.reqd and cdf.fieldname and row.get(cdf.fieldname) in (None, ""):
					if cdf.default not in (None, "") and not str(cdf.default).startswith(("__", "eval:")) and cdf.default not in ("Today", "Now"):
						from erpnext_ai_assistant.services.schema import typed_default

						row[cdf.fieldname] = typed_default(cdf.fieldtype, cdf.default)
					elif cdf.read_only and cdf.fieldtype in ("Float", "Int", "Currency", "Percent"):
						row[cdf.fieldname] = 0
	return problems


# Arabic broken plurals people type for common items.
_SINGULAR = {"كراسي": "كرسي", "طابعات": "طابعة", "شاشات": "شاشة", "اجهزة": "جهاز", "أجهزة": "جهاز", "حواسيب": "حاسوب", "مكاتب": "مكتب"}


def find_item(text: str) -> str | None:
	"""One readable Item whose code or name matches what the user typed, else None."""
	hint = " ".join(_SINGULAR.get(word, word) for word in (text or "").split()).strip()
	if not hint:
		return None
	rows = _items_like(hint)
	if len(rows) != 1 and hint.lower().endswith("s"):
		rows = _items_like(hint[:-1])
	return rows[0] if len(rows) == 1 else None


def _items_like(hint: str) -> list[str]:
	return frappe.get_list(
		"Item",
		or_filters=[["item_code", "like", f"%{hint}%"], ["item_name", "like", f"%{hint}%"]],
		filters={"disabled": 0},
		pluck="name",
		limit_page_length=2,
	)


# Dates the Desk form makes you pick although the DocType does not mark them required.
# They are business values: read from the sentence or asked for, never guessed.
ASKED_DATES = {"Sales Order": "delivery_date", "Purchase Order": "schedule_date", "Material Request": "schedule_date"}
_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_IN_DAYS = re.compile(r"\b(?:in|within)\s+(\d+)\s+days?\b|(?:خلال|بعد)\s+(\d+)\s+(?:ايام|أيام|يوم)", re.I)


def sentence_date(text: str | None) -> str | None:
	from erpnext_ai_assistant.services.targeting import _relative_day

	raw = (text or "").translate(_DIGITS)
	found = _ISO_DATE.search(raw)
	if found:
		return found.group(1)
	days = _IN_DAYS.search(raw)
	if days:
		return str(frappe.utils.add_days(frappe.utils.nowdate(), int(days.group(1) or days.group(2))))
	return _relative_day(raw)


_PARTY_FIELDS = (("party_name", "Customer"), ("customer", "Customer"), ("supplier", "Supplier"))
_PARTY_EN = re.compile(r"\b(?:for|to|from)\s+(?:customer\s+|supplier\s+)?(.+?)(?=\s+(?:for|with|of)\s|\s+\d|,|\.|$)", re.I)
_PARTY_AR = re.compile(r"(?<!\w)(?:لشركة|لشركه|للشركة|للعميل|لعميل|لمؤسسة|لمؤسسه|للمورد|لمورد|من\s+شركة|من\s+المورد)\s+(.+?)(?=\s+(?:لعدد|بعدد|عدد)|\s+\d|\s+و\s|،|,|$)")
_ITEM_EN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:x\s+|pcs\s+|units?\s+(?:of\s+)?)?([A-Za-z][A-Za-z0-9\- ]*?)(?=\s+(?:and|for|with|to)\b|,|\.|$)", re.I)
_ITEM_AR = re.compile(r"(\d+(?:\.\d+)?)\s+([\u0600-\u06FF][\u0600-\u06FF ]*?)(?=\s+و\s*\d|\s+(?:لشركة|للعميل|لعميل)|،|,|$)")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def sentence_values(doctype: str, text: str | None) -> dict:
	"""Party and item rows from a plain sentence: "a quotation for Delta Systems for 2 laptops".

	Only values that resolve to a record the user can read are returned; an item the
	sentence names but no Item matches is kept by name so the reply can say so.
	"""
	raw = (text or "").translate(_DIGITS)
	meta = frappe.get_meta(doctype)
	values: dict = {}
	date_field = ASKED_DATES.get(doctype)
	if date_field and meta.has_field(date_field):
		when = sentence_date(raw)
		if when:
			values[date_field] = when
	# "in 5 days" and "2026-11-20" are dates, not "5 days" of an item.
	raw = _IN_DAYS.sub(" ", _ISO_DATE.sub(" ", raw))
	for fieldname, party_doctype in _PARTY_FIELDS:
		if not meta.has_field(fieldname):
			continue
		for match in list(_PARTY_EN.finditer(raw)) + list(_PARTY_AR.finditer(raw)):
			found = _find_party(party_doctype, match.group(1))
			if found:
				values[fieldname] = found
				if fieldname == "party_name" and meta.has_field("quotation_to"):
					values["quotation_to"] = party_doctype
				break
		break
	table = next((df for df in meta.fields if df.fieldtype == "Table" and df.options and frappe.get_meta(df.options).has_field("item_code")), None)
	if table:
		rows = []
		for pattern in (_ITEM_EN, _ITEM_AR):
			for match in pattern.finditer(raw):
				name = match.group(2).strip()
				if not name or _find_party("Customer", name) or _find_party("Supplier", name):
					continue
				code = find_item(name)
				row = {"item_code": code} if code else {"item_name": name}
				row["qty"] = float(match.group(1)) if "." in match.group(1) else int(match.group(1))
				rows.append(row)
		if rows:
			values[table.fieldname] = rows
	return values


def _find_party(doctype: str, text: str) -> str | None:
	hint = (text or "").strip(" .,،")
	if len(hint) < 2 or not frappe.has_permission(doctype, "read"):
		return None
	if frappe.db.exists(doctype, hint):
		return hint
	title = "customer_name" if doctype == "Customer" else "supplier_name"
	rows = frappe.get_list(doctype, or_filters=[["name", "like", f"%{hint}%"], [title, "like", f"%{hint}%"]], pluck="name", limit_page_length=2)
	return rows[0] if len(rows) == 1 else None


def _put_row(meta, row: dict, fieldname: str, value) -> None:
	if meta.has_field(fieldname) and row.get(fieldname) in (None, "") and value not in (None, ""):
		row[fieldname] = value
