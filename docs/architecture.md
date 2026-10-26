# Architecture — The ERPNext-AI-Assistant

## Integration model

The assistant is a **product app**. Host apps (CRM, HRMS, Desk) load its public
JS/CSS when the current path matches **ERP AI Settings → Overlay Pages**.
Colors, fonts, and panel CSS ship inside `erpnext_ai_assistant` (Cairo/RTL/navy).
Do **not** put assistant CSS into the theme app.

## run_chat order (canonical)

1. Reject Guest
2. If on Blocked User → fixed blocked message, stop
3. Register / ensure ERP AI Chat
4. Abuse scan (event + maybe block)
5. Work-scope gate (no LLM)
6. Optional provider intent (cannot widen)
7. Load Skill(s) + Memory + active Persona
8. `retrieve()` RAG
9. For name/field questions: always `tool_rdf_lookup` before `tool_erp_query`
10. Detectors → live tools
11. **AI model last**

## DocTypes (module: ERP AI Assistant)

- ERP AI Chat / Message / Generated Query / Generated Chart
- ERP AI Knowledge Document / Knowledge Chunk / Metadata Cache
- ERP AI Pending Action / Abuse Event / Audit Log
- ERP AI Skill (+ Skill Role) / Persona (+ Persona Role) / Memory
- ERP AI Settings (Single) + children: Abuse Term, Notify Role, Blocked User, Overlay Page

## Workspace and reports

**Workspace:** The ERPNext-AI-Assistant

**Reports (System Manager):**

| Report | Purpose |
|---|---|
| ERP AI Chats by User | chats/messages count per user |
| ERP AI Abuse Summary | abuse by user/category; blocked users |
| ERP AI Pending Actions | pending/approved/rejected writes |
| ERP AI Skill Usage | skills enabled / loaded |
| ERP AI Memory Overview | memory rows by user/scope |

## Overlay Pages

Seed examples: `/crm` and `/desk`. Add more paths (HR, stock, accounts) in ERP AI Settings → Overlay Pages.

## Tool registry (summary)

Read: metadata/RAG, erp_query, erp_get_doc, erp_report, get_doctype_meta,
run_method (allowlist), read_doctype_controller (SM), build_chart, read_skill, rdf_lookup.

Write: create/update/delete → Pending Action only; `approve_action` after ack.
