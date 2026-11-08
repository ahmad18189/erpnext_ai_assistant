"""Personal ToDo list for the assistant panel. Chat writes still use approval cards."""

from __future__ import annotations

import frappe
from frappe.utils import add_to_date, cint, get_datetime, getdate, now_datetime, strip_html

ALARM_AT = "custom_erp_ai_alarm_at"
ALARM_ENABLED = "custom_erp_ai_alarm_enabled"
ALARM_FIRED = "custom_erp_ai_alarm_fired"
_STATUSES = {"Open", "Closed", "Cancelled"}
_PRIORITIES = {"High", "Medium", "Low"}
_SNOOZE = {5, 10, 15}


def _login():
	if frappe.session.user == "Guest":
		frappe.throw("Login required", frappe.PermissionError)


def _alarms_ready() -> bool:
	meta = frappe.get_meta("ToDo")
	return bool(meta.has_field(ALARM_AT) and meta.has_field(ALARM_ENABLED) and meta.has_field(ALARM_FIRED))


def _require_alarms():
	if not _alarms_ready():
		frappe.throw("ToDo alarm fields are not installed. Run bench migrate.", frappe.ValidationError)


def _owns(doc) -> bool:
	"""Allocated to this user, or owned by them when nobody is allocated."""
	user = frappe.session.user
	allocated = (doc.get("allocated_to") or "").strip()
	if allocated:
		return allocated == user
	return doc.get("owner") == user


def _mine_or_throw(name: str):
	if not name or not frappe.db.exists("ToDo", name):
		frappe.throw("ToDo not found", frappe.DoesNotExistError)
	doc = frappe.get_doc("ToDo", name)
	if not _owns(doc):
		frappe.throw("You can only change your own to-dos", frappe.PermissionError)
	return doc


def _plain(value) -> str:
	return strip_html(value or "").strip()


def _row(source) -> dict:
	alarm_at = source.get(ALARM_AT) if _alarms_ready() else None
	return {
		"name": source.get("name"),
		"description": _plain(source.get("description"))[:2000],
		"date": str(source.get("date")) if source.get("date") else None,
		"status": source.get("status"),
		"priority": source.get("priority"),
		"alarm_at": str(alarm_at) if alarm_at else None,
		"alarm_enabled": 1 if alarm_at and cint(source.get(ALARM_ENABLED)) else 0,
		"alarm_fired": 1 if alarm_at is not None and cint(source.get(ALARM_FIRED)) else 0,
	}


def _parse_date(value):
	if value in (None, ""):
		return None
	try:
		return getdate(value)
	except Exception:
		frappe.throw("Invalid date", frappe.ValidationError)


def _parse_datetime(value):
	if value in (None, ""):
		return None
	try:
		return get_datetime(value)
	except Exception:
		frappe.throw("Invalid alarm time", frappe.ValidationError)


def _flag(value) -> bool:
	return value in (True, 1, "1", "true", "True")


@frappe.whitelist()
def list_my_todos(status: str = "Open"):
	"""Open to-dos allocated to the user, or owned by them when unallocated."""
	_login()
	status = (status or "Open").strip()
	filters: list = []
	if status != "All":
		if status not in _STATUSES:
			status = "Open"
		filters.append(["ToDo", "status", "=", status])
	user = frappe.session.user
	ready = _alarms_ready()
	fields = ["name", "description", "date", "status", "priority", "owner", "allocated_to"]
	if ready:
		fields.extend([ALARM_AT, ALARM_ENABLED, ALARM_FIRED])
	rows = frappe.get_list(
		"ToDo",
		filters=filters,
		or_filters=[["allocated_to", "=", user], ["owner", "=", user]],
		fields=fields,
		order_by="modified desc",
		limit_page_length=50,
	)
	items = [_row(row) for row in rows if _owns(row)]
	items.sort(key=lambda item: (item.get("alarm_at") or "9999-12-31", item.get("date") or "9999-12-31"))
	return {"items": items}


@frappe.whitelist(methods=["POST"])
def create_my_todo(description: str, date=None, alarm_at=None, priority: str = "Medium"):
	"""Insert a ToDo for the signed-in user. No approval card — this is their own list."""
	_login()
	text = _plain(description)[:2000]
	if not text:
		frappe.throw("Description is required", frappe.ValidationError)
	if priority not in _PRIORITIES:
		priority = "Medium"
	when = _parse_datetime(alarm_at)
	if when:
		_require_alarms()
	due = _parse_date(date) or (getdate(when) if when else None)
	doc = frappe.get_doc(
		{
			"doctype": "ToDo",
			"description": text,
			"priority": priority,
			"allocated_to": frappe.session.user,
			"assigned_by": frappe.session.user,
		}
	)
	if due:
		doc.date = due
	if when:
		doc.set(ALARM_AT, when)
		doc.set(ALARM_ENABLED, 1)
		doc.set(ALARM_FIRED, 0)
	doc.insert()
	return {"ok": True, "item": _row(doc)}


@frappe.whitelist(methods=["POST"])
def update_my_todo(
	name: str,
	status=None,
	description=None,
	date=None,
	priority=None,
	alarm_at=None,
	alarm_enabled=None,
	alarm_fired=None,
	clear_alarm=None,
	snooze_minutes=None,
):
	"""Update one of the user's own to-dos: complete, set an alarm, snooze, or mark it fired."""
	_login()
	doc = _mine_or_throw(name)
	changed = False
	if description is not None:
		text = _plain(description)[:2000]
		if not text:
			frappe.throw("Description is required", frappe.ValidationError)
		doc.description = text
		changed = True
	if date is not None:
		doc.date = _parse_date(date)
		changed = True
	if priority is not None:
		if priority not in _PRIORITIES:
			frappe.throw("Invalid priority", frappe.ValidationError)
		doc.priority = priority
		changed = True
	if status is not None:
		if status not in _STATUSES:
			frappe.throw("Invalid status", frappe.ValidationError)
		doc.status = status
		changed = True

	snooze = None
	if snooze_minutes not in (None, ""):
		try:
			snooze = int(snooze_minutes)
		except (TypeError, ValueError):
			snooze = 0
		if snooze not in _SNOOZE:
			frappe.throw("Snooze must be 5, 10, or 15 minutes", frappe.ValidationError)

	wants_alarm = any(value not in (None, "") for value in (alarm_at, alarm_enabled, alarm_fired, clear_alarm, snooze))
	if wants_alarm:
		_require_alarms()
	if snooze:
		doc.set(ALARM_AT, add_to_date(now_datetime(), minutes=snooze, as_datetime=True))
		doc.set(ALARM_ENABLED, 1)
		doc.set(ALARM_FIRED, 0)
		changed = True
	elif _flag(clear_alarm):
		doc.set(ALARM_AT, None)
		doc.set(ALARM_ENABLED, 0)
		doc.set(ALARM_FIRED, 0)
		changed = True
	elif alarm_at not in (None, ""):
		doc.set(ALARM_AT, _parse_datetime(alarm_at))
		doc.set(ALARM_ENABLED, 0 if alarm_enabled is not None and not _flag(alarm_enabled) else 1)
		doc.set(ALARM_FIRED, 0)
		changed = True
	if not snooze and not _flag(clear_alarm):
		if alarm_enabled is not None and alarm_at in (None, ""):
			doc.set(ALARM_ENABLED, 1 if _flag(alarm_enabled) else 0)
			changed = True
		if alarm_fired is not None:
			doc.set(ALARM_FIRED, 1 if _flag(alarm_fired) else 0)
			changed = True
	if not changed:
		return {"ok": True, "item": _row(doc)}
	doc.save()
	return {"ok": True, "item": _row(doc)}


@frappe.whitelist()
def due_my_alarms():
	"""Open alarms whose time has arrived and have not been dismissed."""
	_login()
	if not _alarms_ready():
		return {"items": []}
	user = frappe.session.user
	rows = frappe.get_list(
		"ToDo",
		filters=[
			["ToDo", "status", "=", "Open"],
			["ToDo", ALARM_ENABLED, "=", 1],
			["ToDo", ALARM_FIRED, "=", 0],
			["ToDo", ALARM_AT, "is", "set"],
			["ToDo", ALARM_AT, "<=", now_datetime()],
		],
		or_filters=[["allocated_to", "=", user], ["owner", "=", user]],
		fields=["name", "description", "date", "status", "priority", "owner", "allocated_to", ALARM_AT, ALARM_ENABLED, ALARM_FIRED],
		order_by=f"{ALARM_AT} asc",
		limit_page_length=20,
	)
	return {"items": [_row(row) for row in rows if _owns(row)]}
