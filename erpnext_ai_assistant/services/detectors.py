"""Intent detectors that fetch live site data before the model answers."""

from __future__ import annotations

import re
from collections import Counter

import frappe
from erpnext_ai_assistant.services.charts.build import build_chart
from erpnext_ai_assistant.services.tools import registry as tools

LEAD_SUMMARY = re.compile(
	r"(how many\s+leads?|lead\s+count|عدد\s*العملاء|كم\s*(عدد\s*)?(عميل|العملاء)|"
	r"about\s+the\s+leads?|tell\s+me\s+about\s+(the\s+)?leads?|"
	r"list\s+(the\s+)?leads?|check\s+(the\s+)?leads?|"
	r"العملاء\s*المحتمل|عرض\s*العملاء|قائمة\s*العملاء)",
	re.I,
)
CHART_HINT = re.compile(r"(chart|graph|bi\s*chart|dashboard|رسم|مخطط|بياني)", re.I)
OWNER_CHART = re.compile(
	r"(assigned|owner|user\s+assigned|lead_owner|حسب\s*(المستخدم|المسؤول|المالك)|تعيين)",
	re.I,
)
STATUS_CHART = re.compile(r"(status|حالة|الحالات)", re.I)
INVOICE_HINT = re.compile(r"(invoice|invoices|فاتورة|فواتير)", re.I)
COMPANY_HINT = re.compile(
	r"(compan(y|ies)|organization|organisations?|منشآت|المنشآت|شركات|الشركة|company\s+status)",
	re.I,
)
APP_HINT = re.compile(r"\b(app|module|installed|تطبيق)\b", re.I)
CREATE_LEAD = re.compile(
	r"(create|add|new)\s+(a\s+|new\s+)?lead|إنشاء\s*(عميل|ليد)|أضف\s*(عميل|ليد)|عميل\s*جديد",
	re.I,
)


def gather_context(
	message: str,
	route: str | None,
	lang: str,
	chat_id: str | None = None,
	session_facts: dict | None = None,
) -> dict:
	"""Return {tool_parts, charts, steps, pending}."""
	msg = message or ""
	msg_l = msg.lower()
	route = route or ""
	facts = session_facts or {}
	tool_parts: list[str] = []
	charts: list[dict] = []
	steps: list[dict] = []
	pending = None

	def add_step(sid, label_ar, label_en, tool, status="done", **extra):
		s = {"id": sid, "label_ar": label_ar, "label_en": label_en, "tool": tool, "status": status, **extra}
		steps.append(s)
		tools.publish_step(chat_id or "", s)

	# --- Create / update lead (Pending Action — never silent write) ---
	if CREATE_LEAD.search(msg) or (
		facts.get("pending_intent") == "create_lead"
		and re.search(r"(name|email|اسم|بريد|@)", msg_l)
	):
		add_step("write", "اقتراح إنشاء عميل", "Propose create lead", "propose_write", "running")
		pending = _propose_create_lead(msg, chat_id=chat_id, lang=lang)
		tool_parts.append(
			"WRITE PROPOSAL (do NOT say ضمن صلاحياتك; explain the proposal and ask user to Approve in the card):\n"
			+ frappe.as_json(pending)[:4000]
		)
		add_step("write", "اقتراح إنشاء عميل", "Propose create lead", "propose_write")

	# --- Installed apps ---
	if APP_HINT.search(msg_l) or "crm app" in msg_l:
		add_step("apps", "التطبيقات المثبتة", "Installed apps", "tool_list_installed_apps", "running")
		apps = tools.tool_list_installed_apps(query=msg) or tools.tool_list_installed_apps()
		tool_parts.append(
			"Installed apps on this site (custom apps are in scope — explain them, do not refuse):\n"
			+ frappe.as_json(apps)[:8000]
		)
		add_step("apps", "التطبيقات المثبتة", "Installed apps", "tool_list_installed_apps")

	asking_about_app = bool(
		re.search(r"\b(about|tell|explain|describe|what is|ما هو|عرفني)\b", msg_l)
		and APP_HINT.search(msg_l)
		and not LEAD_SUMMARY.search(msg)
	)

	# --- CRM Lead name search (skip when creating) ---
	if (
		not pending
		and not CREATE_LEAD.search(msg)
		and not asking_about_app
		and tools.NAME_HINT.search(msg)
		and tools._extract_name_token(msg)
	):
		add_step("erp_query", "بحث بالاسم", "Name search", "tool_erp_query", "running")
		lead_result = tools.detect_and_query_leads(msg, chat_id=chat_id)
		if lead_result is not None:
			# Never surface the bare within_permissions stub as the only fact
			if lead_result.get("error") == "within_permissions":
				tool_parts.append(
					"CRM Lead name search: user cannot read CRM Lead under current roles. "
					"Explain that clearly in one sentence; do NOT reply with only «ضمن صلاحياتك»."
				)
			else:
				tool_parts.append("CRM Lead name search:\n" + frappe.as_json(lead_result)[:6000])
		add_step(
			"erp_query",
			"بحث بالاسم",
			"Name search",
			"tool_erp_query",
			fields_used=(lead_result or {}).get("fields_used"),
		)

	# --- Lead list / count / summary (the broken cases in the user's chat) ---
	# Don't piggy-back lead summary onto invoice/company/app questions
	other_domain = bool(INVOICE_HINT.search(msg) or COMPANY_HINT.search(msg) or asking_about_app)
	want_lead_summary = bool(
		LEAD_SUMMARY.search(msg)
		or (
			not other_domain
			and ("lead" in msg_l or "عميل" in msg or "crm" in msg_l)
			and re.search(r"(how many|list|check|about|tell|عدد|كم|عرض|قائمة)", msg_l)
		)
	)
	if want_lead_summary and frappe.db.exists("DocType", "CRM Lead") and frappe.has_permission("CRM Lead", "read"):
		add_step("lead_summary", "ملخص العملاء المحتملين", "Lead summary", "tool_erp_query", "running")
		summary = _crm_lead_summary()
		tool_parts.append(
			"LIVE CRM Lead summary (use these numbers — never say there are zero leads if total>0):\n"
			+ frappe.as_json(summary)[:8000]
		)
		add_step("lead_summary", "ملخص العملاء المحتملين", "Lead summary", "tool_erp_query")

	# --- Charts (status / owner / BI), including short follow-ups using session memory ---
	followup_chart = bool(
		facts.get("topic") == "crm_leads"
		and re.search(r"(instead|by owner|by status|same|that|again|اعرض|بدل|نفس)", msg_l)
		and (OWNER_CHART.search(msg) or STATUS_CHART.search(msg) or CHART_HINT.search(msg) or "instead" in msg_l)
	)
	want_chart = bool(CHART_HINT.search(msg) or followup_chart)
	if want_chart and frappe.db.exists("DocType", "CRM Lead") and frappe.has_permission("CRM Lead", "read"):
		add_step("chart", "بناء مخطط", "Build chart", "tool_build_chart", "running")
		want_bi = bool(re.search(r"\bbi\b", msg_l)) or (
			CHART_HINT.search(msg) and not OWNER_CHART.search(msg) and not STATUS_CHART.search(msg) and not followup_chart
		)
		if OWNER_CHART.search(msg) or (followup_chart and "owner" in msg_l):
			groups = ["lead_owner"]
		elif STATUS_CHART.search(msg) or (followup_chart and "status" in msg_l):
			groups = ["status"]
		elif want_bi:
			groups = ["lead_owner", "status"]
		else:
			# "chart for that" after a lead summary → status is the natural default; BI if prior dim unknown
			groups = ["status"]
			if facts.get("last_chart_dim") == "status":
				groups = ["lead_owner", "status"]

		for field in groups:
			payload = _lead_group_chart(field, lang)
			if payload:
				charts.append(payload)
				tool_parts.append(f"Chart payload ({field}):\n" + frappe.as_json(payload)[:4000])
		add_step("chart", "بناء مخطط", "Build chart", "tool_build_chart")
		tool_parts.append(
			"IMPORTANT: Do NOT invent markdown images or base64 charts. "
			"The UI attaches the real SVG chart from Chart payload below the answer."
		)

	# --- Invoices live summary ---
	if INVOICE_HINT.search(msg):
		add_step("invoices", "ملخص الفواتير", "Invoice summary", "tool_erp_query", "running")
		inv = _invoice_summary()
		tool_parts.append(
			"LIVE invoice summary for this site (prefer these facts over generic field lists):\n"
			+ frappe.as_json(inv)[:8000]
		)
		add_step("invoices", "ملخص الفواتير", "Invoice summary", "tool_erp_query")

	# --- Companies / organizations ---
	if COMPANY_HINT.search(msg):
		add_step("orgs", "المنشآت", "Organizations", "tool_erp_query", "running")
		orgs = _organization_summary()
		tool_parts.append(
			"LIVE organizations/companies on this site:\n" + frappe.as_json(orgs)[:8000]
		)
		add_step("orgs", "المنشآت", "Organizations", "tool_erp_query")

	return {"tool_parts": tool_parts, "charts": charts, "steps": steps, "pending": pending}


def _parse_create_lead(message: str) -> dict:
	"""Extract lead fields from a create request."""
	msg = message or ""
	email = None
	m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", msg)
	if m:
		email = m.group(0)
	# name after "name" / "اسم" / "called" / "named"
	name = None
	m = re.search(
		r"(?:named|name|called|اسم(?:ه|ها)?)\s*[:\-]?\s*([A-Za-z\u0600-\u06FF][A-Za-z\u0600-\u06FF\s.'-]{1,60})",
		msg,
		re.I,
	)
	if m:
		name = m.group(1).strip()
		name = re.split(r"\s+with\s+|\s+email\s+|\s+و\s*بريد", name, maxsplit=1, flags=re.I)[0].strip()
	if not name:
		# "create new lead <name> ..."
		m = re.search(
			r"(?:create|add|new)\s+(?:a\s+|new\s+)?lead\s+([A-Za-z\u0600-\u06FF][A-Za-z\u0600-\u06FF'.-]{1,40})",
			msg,
			re.I,
		)
		if m and m.group(1).lower() not in {"name", "with", "email", "for"}:
			name = m.group(1).strip()
	parts = (name or "Lead").split()
	first = parts[0]
	last = " ".join(parts[1:]) if len(parts) > 1 else ""
	payload = {
		"first_name": first,
		"status": "New",
	}
	if last:
		payload["last_name"] = last
	if name:
		payload["lead_name"] = name
	if email:
		payload["email"] = email
	return payload


def _propose_create_lead(message: str, chat_id: str | None, lang: str) -> dict:
	if not frappe.db.exists("DocType", "CRM Lead"):
		return {"error": "CRM Lead DocType missing", "status": "failed"}
	if not frappe.has_permission("CRM Lead", "create"):
		return {
			"error": "no_create_permission",
			"status": "failed",
			"message_ar": "لا تملك صلاحية إنشاء عميل محتمل (CRM Lead).",
			"message_en": "You do not have permission to create CRM Lead.",
		}
	payload = _parse_create_lead(message)
	if not payload.get("first_name"):
		return {
			"error": "missing_name",
			"status": "need_input",
			"message_ar": "يرجى تحديد اسم العميل المحتمل.",
			"message_en": "Please provide the lead name.",
		}
	label = payload.get("lead_name") or payload.get("first_name")
	if lang == "ar":
		summary = f"إنشاء عميل محتمل جديد: {label}"
		if payload.get("email"):
			summary += f" — البريد: {payload['email']}"
		summary += f" — الحالة: {payload.get('status')}"
	else:
		summary = f"Create CRM Lead: {label}"
		if payload.get("email"):
			summary += f" — email: {payload['email']}"
		summary += f" — status: {payload.get('status')}"
	try:
		if not chat_id:
			return {"error": "missing_chat", "status": "failed", "payload": payload, "summary": summary}
		return tools.propose_write(
			chat=chat_id,
			action_type="create",
			target_doctype="CRM Lead",
			payload=payload,
			summary=summary,
		)
	except Exception as e:
		return {"error": str(e), "status": "failed", "payload": payload, "summary": summary}


def _crm_lead_summary() -> dict:
	fields = ["name", "lead_name", "status", "lead_owner", "mobile_no", "organization", "email", "modified"]
	rows = tools.tool_erp_query("CRM Lead", fields=fields, limit=200, order_by="modified desc")
	# Approximate total under permission: if we hit the page length, note it
	total = len(rows)
	capped = total >= 200
	by_status = dict(Counter((r.get("status") or "Unknown") for r in rows))
	by_owner = dict(Counter((r.get("lead_owner") or "Unassigned") for r in rows))
	sample = [
		{
			"name": r.get("name"),
			"lead_name": r.get("lead_name"),
			"status": r.get("status"),
			"lead_owner": r.get("lead_owner"),
			"organization": r.get("organization"),
			"mobile_no": r.get("mobile_no"),
		}
		for r in rows[:15]
	]
	return {
		"doctype": "CRM Lead",
		"visible_count": total,
		"count_capped_at_200": capped,
		"by_status": by_status,
		"by_owner": by_owner,
		"sample_leads": sample,
	}


def _lead_group_chart(field: str, lang: str) -> dict | None:
	rows = tools.tool_erp_query("CRM Lead", fields=[field], limit=200)
	if not rows:
		return None
	c = Counter((r.get(field) or ("غير معيّن" if lang == "ar" else "Unassigned")) for r in rows)
	# Prefer bar for owners (many labels), pie for few statuses
	ctype = "bar" if field == "lead_owner" or len(c) <= 6 else "pie"
	if lang == "ar":
		title = "العملاء حسب المالك" if field == "lead_owner" else "العملاء حسب الحالة"
	else:
		title = "Leads by owner" if field == "lead_owner" else "Leads by status"
	return build_chart(ctype, title, list(c.keys()), [float(v) for v in c.values()])


def _invoice_summary() -> dict:
	out: dict = {"sales": None, "purchase": None, "note": None}
	for dt, key in (("Sales Invoice", "sales"), ("Purchase Invoice", "purchase")):
		if not frappe.db.exists("DocType", dt) or not frappe.has_permission(dt, "read"):
			out[key] = {"error": "no_permission_or_missing"}
			continue
		rows = tools.tool_erp_query(
			dt,
			fields=["name", "customer", "supplier", "grand_total", "outstanding_amount", "status", "posting_date"],
			limit=30,
			order_by="posting_date desc",
		)
		out[key] = {
			"visible_count": len(rows),
			"sample": rows[:10],
			"status_breakdown": dict(Counter((r.get("status") or "Unknown") for r in rows)),
		}
	out["zatca"] = "ZATCA/e-invoice status is unavailable on this site (no ZATCA app installed)."
	return out


def _organization_summary() -> dict:
	# Prefer CRM Organization; fall back to ERPNext Customer / Company
	for dt, name_field in (
		("CRM Organization", "organization_name"),
		("Customer", "customer_name"),
		("Company", "company_name"),
	):
		if not frappe.db.exists("DocType", dt):
			continue
		if not frappe.has_permission(dt, "read"):
			continue
		meta = frappe.get_meta(dt)
		fields = ["name"]
		for f in (name_field, "status", "industry", "website", "email", "mobile_no", "country"):
			if meta.has_field(f):
				fields.append(f)
		rows = tools.tool_erp_query(dt, fields=fields, limit=40, order_by="modified desc")
		status_field = "status" if meta.has_field("status") else None
		return {
			"doctype": dt,
			"visible_count": len(rows),
			"by_status": dict(Counter((r.get(status_field) or "—") for r in rows)) if status_field else {},
			"sample": rows[:15],
		}
	return {"error": "no_readable_organization_doctype", "hint": "within_permissions"}
