# Architecture — The ERPNext-AI-Assistant

## Integration model

The assistant is a Frappe app. It is not part of one CRM or HR product.

- Desk loads `app_include_js` / `app_include_css`.
- Any other installed app can show the same panel. `services/apps.py` reads `add_to_apps_screen` and `app_icon_route`. Install seeds those paths into **ERP AI Settings → Overlay Pages**, together with `/desk` and `/app`.
- A host may also load `public/js/crm_include.js`. That file only injects this app's bundle. It does not contain product logic.
- Colors, Cairo, and RTL live in this app. Do not copy the panel CSS into a theme app.

`bootstrap` returns `overlay_pages`, `app_routes`, and `branding` (title, subtitle, hint, hint_en).

## run_chat order

1. Reject Guest.
2. Settings `enabled` off → fixed disabled message, stop.
3. Blocked User → fixed message, stop.
4. Abuse scan. Every response includes `contains_abuse` and `abuse`.
5. Work-scope gate. No model. A route under Desk or any installed app route counts as work. Follow-ups reuse recent user text.
6. Load confirmed user-scope ERP AI Memory and the active persona.
7. DocType targeting (`services/targeting.py`): create, count, or list when the wording names a DocType. Count uses `count_records` with no model call.
8. Tool loop (`services/tools/agent.py`): describe, query, count, list DocTypes, list apps, lookup field, search knowledge, search ERPNext manual (`docs.frappe.io`), propose write. How-to questions skip DocType shortcuts and use `search_manual`. Retrieved text is quoted data in `conversation.py`, not a new system policy. A live quantity or list question with no tool call returns a fixed not-verified sentence.
9. When the model is off or the key is missing, the regex detectors run instead, then skills and role-filtered RAG, then one completion.
10. Per-user daily call cap and turn deadline stop further provider calls. Each provider call writes an ERP AI Audit Log row with DocType names, field names, image count, and request byte size only.

## Writes

`propose_write` stores a canonical JSON payload and `payload_hash`. The summary is generated from that payload.

`ERPAIPendingAction.validate` allows only these status moves:

| From | To |
|---|---|
| pending | approved, rejected, executed, failed |
| approved | executed, failed |
| executed, rejected, failed | none |

Payload, summary, target, user, and hash stay fixed unless `frappe.flags.erp_ai_mutate_pending` is set by approve/reject. Approval locks the row, checks the hash, checks `allow_pending_writes`, validates the payload again with defaults turned off, then executes once.

Opening a saved record uses `/desk/{doctype-slug}/{name}`. If the DocType's module belongs to an installed app, `crm_route` is that app's own home route from hooks, not a hard-coded path.

## DocTypes

Forms use tabs, sections, and column breaks. Child tables set `in_list_view` and `columns` (grid and list). Naming rule is **By fieldname** (`field:title` or `field:persona_name`). There is no naming series.

| Area | DocTypes |
|---|---|
| Conversation | ERP AI Chat, ERP AI Message, ERP AI Generated Query, ERP AI Generated Chart |
| Knowledge | ERP AI Knowledge Document (`source_roles`), ERP AI Knowledge Chunk, ERP AI Metadata Cache |
| Safety / writes | ERP AI Pending Action (`payload_hash`), ERP AI Abuse Event, ERP AI Audit Log |
| Config | ERP AI Skill (+ Role), ERP AI Persona (+ Role), ERP AI Memory |
| Settings | Single: Abuse Term, Notify Role, Blocked User, Overlay Page |

**Workspace:** The ERPNext-AI-Assistant.  
**Desktop Icon:** same label, logo `public/images/erp-ai-logo.svg`.

**Reports:** Chats by User, Abuse Summary, Pending Actions, Skill Usage, Memory Overview.

## Services

| Module | Role |
|---|---|
| `run_chat.py` | Orchestrator. One step record per id, with `detail` / `detail_ar` |
| `conversation.py` | Newest `HISTORY_TURNS` messages, then chronological order |
| `detectors.py` | Fallback when the model is off: leads, calls, charts, invoices |
| `schema.py` | DocType contract and `propose_schema_write` |
| `writes.py` | Payload hash and summary |
| `apps.py` | Installed app routes |
| `imports.py` | Header vs import-template match. No row insert |
| `moderation/` | Abuse terms and work gate |
| `rag/` | Keyword overlap on stored chunks, filtered by skill roles. Not embeddings |
| `rdf/` | JSON label-to-fieldname index for the current site, including Arabic name labels. Not a graph of business records |
| `llm/provider.py` | OpenAI-compatible chat, including tool calls. Images are optional data URLs |
| `tools/agent.py` | The seven tools the model may call (includes `count_records`). Memory save is panel-only |
| `tools/registry.py` | Session-user tools and `propose_write` |

## Tools

Read: `tool_rdf_lookup`, `tool_erp_query` (`get_list`), `tool_erp_count` (`DatabaseQuery`), `tool_erp_get_doc` (field-level strip), `tool_erp_report`, `tool_get_doctype_meta`, allowlisted `tool_run_method`, `tool_read_doctype_controller` (System Manager), `tool_list_installed_apps`, `build_chart`, `read_skill`.

Write: `propose_write` only. `approve_action` / `reject_action` after acknowledgment.

## Files and import review

Upload is private, owned by the session user, max 5 MB: png, jpeg, webp, gif, csv, xlsx, txt, pdf.

A table is scored against importable columns (fieldname and label, child tables included). The reply lists the best DocTypes, mapped columns, missing required fields, and unmatched columns. `blank_import_template` returns a header-only CSV. Starting a Data Import stays in Desk.

## Thinking channel

`frappe.publish_realtime` event `erp_ai_thinking`, room `erp_ai_chat:{chat_id}`. The panel replaces a step with the same `id` and renders `detail` under the label. The list stays open.

## Translations

English strings stay in DocType JSON. Arabic is `erpnext_ai_assistant/translations/ar.csv`, loaded by Frappe when the user language is `ar`. Suggestion text calls `get_all_translations(lang)` so field labels follow the chat language.
