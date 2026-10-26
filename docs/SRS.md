# Software Requirements Specification — The ERPNext-AI-Assistant

## 1. Purpose

Workplace assistant for a Frappe / ERPNext site (CRM, HR, stock, finance).  
Product name: **The ERPNext-AI-Assistant**. Not a general chatbot.

## 2. Actors

- Sales User / Sales Manager / System Manager / CRM User (when those roles exist)
- Managers listed in `notify_roles` (abuse alerts)
- Guest: denied

## 3. Functional requirements

| ID | Requirement |
|---|---|
| FR1 | Floating 448×684 RTL panel; brand The ERPNext-AI-Assistant; Arabic-first UI (AR/EN toggle, Cairo, RTL); chat + history; thinking steps; SVG charts |
| FR1b | Arabic end to end: Arabic messages get Arabic replies; `translations/ar.csv`; Arabic normalize for RAG/RDF; display name maps to `lead_name` |
| FR2 | Session-user ERP reads (`get_list` / `get_doc` / `get_meta` / reports); respect DocPerms |
| FR3 | Pipeline: Guest → Blocked User → abuse → work-only → skill(s)+memory+persona → RAG → RDF → detectors → tools → model last |
| FR4 | ERP AI Skill DocType; seed CRM / HR / stock / finance; RDF maps labels to fieldnames |
| FR4b | ERP AI Persona editable; active persona from Settings; ERP AI Memory with clear controls |
| FR5 | CRUD only via Pending Action + written acknowledgment + Approve |
| FR6 | All chats and messages registered per user |
| FR7 | Abuse events persisted; threshold blocks the user; managers notified |
| FR8 | ERP AI Settings: LLM, moderation, notifies, blocks, writes, persona, Overlay Pages |
| FR8b | Desk Workspace + Reports for System Manager |
| FR8c | Panel JS/CSS owned by `erpnext_ai_assistant`; hosts opt in via Overlay Pages |

## 4. Non-functional

| ID | Requirement |
|---|---|
| NFR1 | No `ignore_permissions`, no `allow_guest` on chat APIs, no ERP API-key store |
| NFR2 | No third-party panel code reuse; no Recharts; no host-app rebuild required |
| NFR3 | Arabic normalize for keyword RAG; realtime thinking via `publish_realtime` |
| NFR4 | Secrets not in git; LLM key is a Password field, site config, or environment variable |

## 5. Out of scope (v1)

- Desktop packaging
- Open agentic tool-calling loops
- Auto-delete of abuse history
- Inventing e-invoice / clearance identifiers when no such app is installed

## 6. Acceptance

On a configured Overlay Page (for example `/crm` or `/desk`): the panel is **The ERPNext-AI-Assistant** at 448×684 RTL, with thinking steps, and the model runs last.  
Off-work prompts are refused. Abuse is registered; the threshold can block and notify. Chats are stored. Writes need acknowledgment.

## 7. Tests

See `TEST_RESULTS.md` for the T01–T20 checklist.
