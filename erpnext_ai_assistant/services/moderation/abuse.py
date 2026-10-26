"""Abuse scan + Blocked User threshold for The ERPNext-AI-Assistant."""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.utils import now_datetime

from erpnext_ai_assistant.services.arabic import normalize_arabic

# Canonical seed list — scanned always (union with ERP AI Settings.abuse_terms).
# Scores: 1 mild / 2 strong / 3 threat-or-severe.
DEFAULT_ABUSE_TERMS = [
	# English — insult
	{"term": "idiot", "language": "en", "category": "insult", "score": 1},
	{"term": "stupid", "language": "en", "category": "insult", "score": 1},
	{"term": "dumb", "language": "en", "category": "insult", "score": 1},
	{"term": "moron", "language": "en", "category": "insult", "score": 1},
	{"term": "imbecile", "language": "en", "category": "insult", "score": 1},
	{"term": "retard", "language": "en", "category": "insult", "score": 2},
	{"term": "retarded", "language": "en", "category": "insult", "score": 2},
	{"term": "loser", "language": "en", "category": "insult", "score": 1},
	{"term": "useless", "language": "en", "category": "insult", "score": 1},
	{"term": "worthless", "language": "en", "category": "insult", "score": 1},
	{"term": "pathetic", "language": "en", "category": "insult", "score": 1},
	{"term": "incompetent", "language": "en", "category": "insult", "score": 1},
	{"term": "asshole", "language": "en", "category": "insult", "score": 2},
	{"term": "ass hole", "language": "en", "category": "insult", "score": 2},
	{"term": "jackass", "language": "en", "category": "insult", "score": 1},
	{"term": "bastard", "language": "en", "category": "insult", "score": 2},
	{"term": "bitch", "language": "en", "category": "insult", "score": 2},
	{"term": "son of a bitch", "language": "en", "category": "insult", "score": 2},
	{"term": "scumbag", "language": "en", "category": "insult", "score": 2},
	{"term": "piece of shit", "language": "en", "category": "insult", "score": 2},
	{"term": "shut up", "language": "en", "category": "insult", "score": 1},
	{"term": "go to hell", "language": "en", "category": "insult", "score": 1},
	# English — profanity
	{"term": "fuck", "language": "en", "category": "profanity", "score": 1},
	{"term": "fucking", "language": "en", "category": "profanity", "score": 1},
	{"term": "fucker", "language": "en", "category": "profanity", "score": 2},
	{"term": "motherfucker", "language": "en", "category": "profanity", "score": 2},
	{"term": "shit", "language": "en", "category": "profanity", "score": 1},
	{"term": "bullshit", "language": "en", "category": "profanity", "score": 1},
	{"term": "crap", "language": "en", "category": "profanity", "score": 1},
	{"term": "damn you", "language": "en", "category": "profanity", "score": 1},
	{"term": "cunt", "language": "en", "category": "profanity", "score": 2},
	{"term": "dickhead", "language": "en", "category": "profanity", "score": 2},
	{"term": "piss off", "language": "en", "category": "profanity", "score": 1},
	# English — sexual / harassment
	{"term": "slut", "language": "en", "category": "harassment", "score": 2},
	{"term": "whore", "language": "en", "category": "harassment", "score": 2},
	{"term": "prostitute", "language": "en", "category": "harassment", "score": 2},
	{"term": "rape you", "language": "en", "category": "harassment", "score": 3},
	{"term": "sexual harassment", "language": "en", "category": "harassment", "score": 2},
	# English — violence / threat
	{"term": "kill you", "language": "en", "category": "violence", "score": 3},
	{"term": "kill yourself", "language": "en", "category": "violence", "score": 3},
	{"term": "i will kill", "language": "en", "category": "violence", "score": 3},
	{"term": "murder you", "language": "en", "category": "violence", "score": 3},
	{"term": "beat you", "language": "en", "category": "violence", "score": 2},
	{"term": "hurt you", "language": "en", "category": "violence", "score": 2},
	{"term": "bomb", "language": "en", "category": "violence", "score": 2},
	{"term": "shoot you", "language": "en", "category": "violence", "score": 3},
	{"term": "die bitch", "language": "en", "category": "violence", "score": 3},
	{"term": "you should die", "language": "en", "category": "violence", "score": 3},
	# English — hate / discrimination (mapped to harassment Select options)
	{"term": "terrorist", "language": "en", "category": "harassment", "score": 2},
	{"term": "nazi", "language": "en", "category": "harassment", "score": 2},
	# Arabic — insult
	{"term": "غبي", "language": "ar", "category": "insult", "score": 1},
	{"term": "اغبياء", "language": "ar", "category": "insult", "score": 1},
	{"term": "عبيط", "language": "ar", "category": "insult", "score": 1},
	{"term": "اهبل", "language": "ar", "category": "insult", "score": 1},
	{"term": "متخلف", "language": "ar", "category": "insult", "score": 2},
	{"term": "حمار", "language": "ar", "category": "insult", "score": 1},
	{"term": "يا حمار", "language": "ar", "category": "insult", "score": 1},
	{"term": "كلب", "language": "ar", "category": "insult", "score": 1},
	{"term": "يا كلب", "language": "ar", "category": "insult", "score": 1},
	{"term": "ابن الكلب", "language": "ar", "category": "insult", "score": 2},
	{"term": "ابن الـكلب", "language": "ar", "category": "insult", "score": 2},
	{"term": "حقير", "language": "ar", "category": "insult", "score": 1},
	{"term": "الحقير", "language": "ar", "category": "insult", "score": 1},
	{"term": "سافل", "language": "ar", "category": "insult", "score": 1},
	{"term": "تافه", "language": "ar", "category": "insult", "score": 1},
	{"term": "فاشل", "language": "ar", "category": "insult", "score": 1},
	{"term": "نذل", "language": "ar", "category": "insult", "score": 2},
	{"term": "خسيس", "language": "ar", "category": "insult", "score": 2},
	{"term": "وسخ", "language": "ar", "category": "insult", "score": 1},
	{"term": "قذر", "language": "ar", "category": "insult", "score": 1},
	{"term": "زفت", "language": "ar", "category": "insult", "score": 1},
	{"term": "زبالة", "language": "ar", "category": "insult", "score": 1},
	{"term": "لعين", "language": "ar", "category": "insult", "score": 1},
	{"term": "ملعون", "language": "ar", "category": "insult", "score": 1},
	{"term": "ابن الحرام", "language": "ar", "category": "insult", "score": 2},
	{"term": "يا ابن", "language": "ar", "category": "insult", "score": 1},
	{"term": "اخرس", "language": "ar", "category": "insult", "score": 1},
	{"term": "اسكت", "language": "ar", "category": "insult", "score": 1},
	{"term": "انقلع", "language": "ar", "category": "insult", "score": 1},
	{"term": "اطلع بره", "language": "ar", "category": "insult", "score": 1},
	{"term": "روح في داهية", "language": "ar", "category": "insult", "score": 1},
	{"term": "تفو", "language": "ar", "category": "insult", "score": 1},
	{"term": "يا حيوان", "language": "ar", "category": "insult", "score": 1},
	{"term": "بهيمة", "language": "ar", "category": "insult", "score": 1},
	# Arabic — profanity / strong
	{"term": "كس ام", "language": "ar", "category": "profanity", "score": 2},
	{"term": "كسمك", "language": "ar", "category": "profanity", "score": 2},
	{"term": "كسك", "language": "ar", "category": "profanity", "score": 2},
	{"term": "شرموطة", "language": "ar", "category": "harassment", "score": 2},
	{"term": "ش رموطة", "language": "ar", "category": "harassment", "score": 2},
	{"term": "عاهرة", "language": "ar", "category": "harassment", "score": 2},
	{"term": "قحبة", "language": "ar", "category": "harassment", "score": 2},
	{"term": "منيك", "language": "ar", "category": "profanity", "score": 2},
	{"term": "يلعن", "language": "ar", "category": "profanity", "score": 1},
	{"term": "انعل", "language": "ar", "category": "profanity", "score": 1},
	{"term": "خرا", "language": "ar", "category": "profanity", "score": 1},
	{"term": "خراء", "language": "ar", "category": "profanity", "score": 1},
	{"term": "زب", "language": "ar", "category": "profanity", "score": 2},
	{"term": "طيز", "language": "ar", "category": "profanity", "score": 2},
	# Arabic — violence / threat
	{"term": "اقتلك", "language": "ar", "category": "violence", "score": 3},
	{"term": "ساقتلك", "language": "ar", "category": "violence", "score": 3},
	{"term": "حتقتل", "language": "ar", "category": "violence", "score": 3},
	{"term": "اضربك", "language": "ar", "category": "violence", "score": 2},
	{"term": "اكسر راسك", "language": "ar", "category": "violence", "score": 3},
	{"term": "ادبحك", "language": "ar", "category": "violence", "score": 3},
	{"term": "تموت", "language": "ar", "category": "violence", "score": 2},
	{"term": "انتحر", "language": "ar", "category": "violence", "score": 3},
]


def get_settings():
	return frappe.get_single("ERP AI Settings")


def is_user_blocked(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user in ("Guest", "Administrator") and user == "Guest":
		return False
	settings = get_settings()
	now = now_datetime()
	for row in settings.blocked_users or []:
		if row.user != user:
			continue
		if row.cleared_on:
			continue
		if row.blocked_until and now > row.blocked_until:
			continue
		return True
	return False


def blocked_message(lang: str = "ar") -> str:
	if lang == "en":
		return (
			"Your access to The ERPNext-AI-Assistant has been blocked due to repeated "
			"disrespectful or abusive messages. Contact your manager."
		)
	return (
		"تم حظر وصولك إلى مساعد ERPNext بسبب رسائل مسيئة متكررة. "
		"يرجى التواصل مع مديرك."
	)


def _iter_terms(settings) -> list[dict]:
	"""Union of Settings rows + DEFAULT_ABUSE_TERMS (dedupe by normalized term)."""
	seen: set[str] = set()
	out: list[dict] = []
	rows = []
	for row in settings.abuse_terms or []:
		rows.append(
			{
				"term": row.term,
				"language": getattr(row, "language", None) or "en",
				"category": getattr(row, "category", None) or "other",
				"score": float(getattr(row, "score", None) or 1),
			}
		)
	rows.extend(DEFAULT_ABUSE_TERMS)
	for row in rows:
		term = (row.get("term") or "").strip()
		if not term:
			continue
		key = normalize_arabic(term).lower() or term.lower()
		if key in seen:
			continue
		seen.add(key)
		out.append(row)
	return out


def scan_abuse(message: str, chat: str | None = None) -> dict:
	"""Return {hit/contains_abuse, category, score, matched, event_name, blocked_now}."""
	settings = get_settings()
	empty = {
		"hit": False,
		"contains_abuse": False,
		"category": None,
		"score": 0,
		"matched": [],
		"event_name": None,
		"blocked_now": False,
	}
	if not settings.moderation_enabled:
		return empty
	text = normalize_arabic(message or "")
	raw_lower = (message or "").lower()
	matched: list[str] = []
	total = 0.0
	category = "other"
	for row in _iter_terms(settings):
		term = (row.get("term") or "").strip()
		if not term:
			continue
		norm_term = normalize_arabic(term)
		hit = False
		if norm_term and norm_term in text:
			hit = True
		elif term.lower() in raw_lower:
			hit = True
		if hit:
			matched.append(term)
			total += float(row.get("score") or 1)
			category = row.get("category") or category
	if not matched:
		return empty
	event = frappe.get_doc(
		{
			"doctype": "ERP AI Abuse Event",
			"user": frappe.session.user,
			"chat": chat,
			"category": category,
			"excerpt": (message or "")[:140],
			"score": total,
			"matched_terms": ", ".join(matched),
		}
	)
	event.insert(ignore_permissions=True)
	blocked_now = _maybe_block_user(settings, total)
	return {
		"hit": True,
		"contains_abuse": True,
		"category": category,
		"score": total,
		"matched": matched,
		"event_name": event.name,
		"blocked_now": blocked_now,
	}


def _maybe_block_user(settings, last_score: float) -> bool:
	user = frappe.session.user
	days = int(settings.abuse_threshold_days or 30)
	count_limit = int(settings.abuse_threshold_count or 3)
	score_limit = float(settings.abuse_score_limit or 5)
	since = now_datetime() - timedelta(days=days)
	events = frappe.get_all(
		"ERP AI Abuse Event",
		filters={"user": user, "creation": (">=", since)},
		fields=["name", "score"],
	)
	total_score = sum(float(e.score or 0) for e in events)
	if len(events) < count_limit and total_score < score_limit and last_score < score_limit:
		return False
	if is_user_blocked(user):
		return True
	doc = get_settings()
	hours = int(doc.block_duration_hours or 0)
	blocked_until = None
	if hours > 0:
		blocked_until = now_datetime() + timedelta(hours=hours)
	doc.append(
		"blocked_users",
		{
			"user": user,
			"blocked_on": now_datetime(),
			"reason": f"Abuse threshold reached ({len(events)} events, score {total_score})",
			"blocked_until": blocked_until,
		},
	)
	doc.save(ignore_permissions=True)
	_notify_managers(doc, user, len(events), total_score)
	return True


def _notify_managers(settings, user: str, count: int, score: float):
	roles = [r.role for r in (settings.notify_roles or []) if r.role]
	recipients = set()
	for role in roles:
		for u in frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"):
			if u not in ("Guest", "Administrator"):
				recipients.add(u)
	for email in (settings.notify_emails or "").replace(";", ",").split(","):
		email = email.strip()
		if email:
			recipients.add(email)
	if not recipients:
		return
	subject = f"[ERP AI] User blocked: {user}"
	message = f"User {user} was blocked after {count} abuse events (score {score})."
	try:
		frappe.sendmail(recipients=list(recipients), subject=subject, message=message, delayed=True)
	except Exception:
		frappe.log_error(title="ERP AI abuse notify failed")
	for r in list(recipients)[:20]:
		if frappe.db.exists("User", r):
			try:
				frappe.get_doc(
					{
						"doctype": "Notification Log",
						"subject": subject,
						"email_content": message,
						"for_user": r,
						"type": "Alert",
						"document_type": "ERP AI Settings",
						"document_name": "ERP AI Settings",
					}
				).insert(ignore_permissions=True)
			except Exception:
				pass
