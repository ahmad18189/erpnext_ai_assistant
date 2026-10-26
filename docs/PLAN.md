# The ERPNext-AI-Assistant — Plan

Product name: **The ERPNext-AI-Assistant**. Frappe app / Python module: `erpnext_ai_assistant`.  
Panel title uses the same product name (Arabic subtitle: مساعد ERPNext).

The panel is a 448×684 shell (`top: 212px`, `left: 24px`) with header, new chat, close, chat/history tabs, messages, and composer. Cairo, RTL, navy `#0f1b2e`.

## Canonical decisions

- Permissions and roles always win. Session-user `get_list` / `get_doc` / report / method / write. No `ignore_permissions`. No ERP API-key store.
- CRUD only with written acknowledgment and approval (Pending Action).
- Chats are registered (ERP AI Chat + Message). Guest chat is off.
- Work-only content guard (deterministic). Abuse scan before the work gate. Blocked User on ERP AI Settings is the block source of truth.
- Editable ERP AI Skill / Persona / Memory DocTypes.
- `run_chat` order: Guest → Blocked User → register Chat → abuse → work-scope → optional intent → Skill(s) + Memory + Persona → RAG → RDF before name queries → detectors → tools → **AI model last**.
- Thinking via `frappe.publish_realtime` on `erp_ai_chat:{chat_id}`.
- Charts are plain SVG/CSS (no Recharts). Panel JS/CSS are owned by this app.
- Hosts opt in via ERP AI Settings → Overlay Pages.
- Finance skill documents Sales/Purchase Invoice fields and VAT. Do not invent e-invoice clearance data.

## Package layout

```
erpnext_ai_assistant/
  erpnext_ai_assistant/
    hooks.py
    public/js|css
    api/chat.py
    services/...
    erp_ai_assistant/doctype|workspace|report
    skills/
  docs/PLAN.md SRS.md architecture.md
```

## Implement order

1. App + docs
2. Core DocTypes + Workspace
3. App-owned panel on Overlay Pages
4. `run_chat` gate skeleton
5. CRM skill seed + RDF before name query

See `SRS.md` and `architecture.md`.
