from . import __version__ as app_version

app_name = "erpnext_ai_assistant"
app_title = "The ERPNext-AI-Assistant"
app_publisher = "Ahmed Abdelrahman"
app_description = "Arabic and English chat assistant for Frappe and ERPNext. Counts, charts, and imports stay inside the user's permissions."
app_email = "ahmad18189@gmail.com"
app_license = "MIT"

app_include_js = ["/assets/erpnext_ai_assistant/js/erpnext_ai_assistant.bundle.js?v=ai25"]
app_include_css = ["/assets/erpnext_ai_assistant/css/erpnext_ai_assistant.bundle.css?v=ai25"]

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
