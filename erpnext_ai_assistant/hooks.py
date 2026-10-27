from . import __version__ as app_version

app_name = "erpnext_ai_assistant"
app_title = "The ERPNext-AI-Assistant"
app_publisher = "ERPNext AI Assistant"
app_description = "Workplace ERP/CRM assistant panel for Frappe."
app_email = "devnull@localhost"
app_license = "MIT"

app_include_js = ["/assets/erpnext_ai_assistant/js/erpnext_ai_assistant.bundle.js?v=ai21"]
app_include_css = ["/assets/erpnext_ai_assistant/css/erpnext_ai_assistant.bundle.css?v=ai21"]

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
