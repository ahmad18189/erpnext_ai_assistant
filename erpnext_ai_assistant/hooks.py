from . import __version__ as app_version

app_name = "erpnext_ai_assistant"
app_title = "The ERPNext-AI-Assistant"
app_publisher = "Ahmed Abdelrahman"
app_description = "Arabic and English chat assistant for Frappe and ERPNext. Counts, charts, and imports stay inside the user's permissions."
app_email = "ahmad18189@gmail.com"
app_license = "MIT"

# The panel is plain ordered files sharing window.erpAi (no build step). Order matters.
PANEL_FILES = ("core", "desk_compat", "render", "charts", "card", "panel")


def _asset_version() -> str:
	"""Changes whenever a panel file changes, so browsers never keep a stale copy.

	Frappe caches resolved hooks in Redis. After updating the app, run `bench migrate`
	(or `bench --site <site> clear-cache`) so Desk serves the new version string.
	"""
	import hashlib
	import os

	public = os.path.join(os.path.dirname(__file__), "public")
	digest = hashlib.sha1(app_version.encode())
	for rel in [f"js/assistant/{name}.js" for name in PANEL_FILES] + ["css/erpnext_ai_assistant.bundle.css"]:
		try:
			with open(os.path.join(public, rel), "rb") as handle:
				digest.update(handle.read())
		except OSError:
			pass
	return digest.hexdigest()[:10]


ASSET_VERSION = _asset_version()
app_include_js = [f"/assets/erpnext_ai_assistant/js/assistant/{name}.js?v={ASSET_VERSION}" for name in PANEL_FILES]
app_include_css = [f"/assets/erpnext_ai_assistant/css/erpnext_ai_assistant.bundle.css?v={ASSET_VERSION}"]

# Frappe v15 apps screen. Desk routes are /app, not /desk.
add_to_apps_screen = [
	{
		"name": "erpnext_ai_assistant",
		"logo": "/assets/erpnext_ai_assistant/images/erp-ai-logo.svg",
		"title": "The ERPNext-AI-Assistant",
		"route": "/app/the-erpnext-ai-assistant",
		"has_permission": "erpnext_ai_assistant.api.chat.has_app_permission",
	}
]

after_migrate = ["erpnext_ai_assistant.install.after_migrate"]
after_install = ["erpnext_ai_assistant.install.after_install"]

doc_events = {
	"Custom Field": {
		"after_insert": "erpnext_ai_assistant.services.rdf.graph.enqueue_rdf_rebuild",
		"on_update": "erpnext_ai_assistant.services.rdf.graph.enqueue_rdf_rebuild",
	},
	"Translation": {
		"after_insert": "erpnext_ai_assistant.services.rdf.graph.enqueue_rdf_rebuild",
		"on_update": "erpnext_ai_assistant.services.rdf.graph.enqueue_rdf_rebuild",
		"on_trash": "erpnext_ai_assistant.services.rdf.graph.enqueue_rdf_rebuild",
	},
	"ERP AI Skill": {
		"on_update": "erpnext_ai_assistant.services.rag.service.on_skill_update",
		"on_trash": "erpnext_ai_assistant.services.rag.service.on_skill_trash",
	},
	"DocType": {
		"after_insert": "erpnext_ai_assistant.services.doctype_catalog.clear_doctype_catalog",
		"on_update": "erpnext_ai_assistant.services.doctype_catalog.clear_doctype_catalog",
		"on_trash": "erpnext_ai_assistant.services.doctype_catalog.clear_doctype_catalog",
	},
}
