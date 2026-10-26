# Software Requirements Specification — The ERPNext-AI-Assistant

## 1. Purpose

Workplace assistant for any Frappe site. It answers from DocTypes the signed-in user can read, on whatever apps are installed (ERPNext, HR, CRM, or a custom app). It is not a general chatbot.

Product name: **The ERPNext-AI-Assistant**.  
Module: `ERP AI Assistant`.

The header title, subtitle, and composer hint are editable in **ERP AI Settings → Panel Text**. Defaults: title `ERP Assistant`, subtitle `مساعد أعمالك`.

## 2. Actors

- Any user who can open an Overlay Page and has a role that can read the DocTypes they ask about
- System Manager (Settings, Workspace, reports)
- Managers listed in `notify_roles` (abuse alerts)
- Guest: denied

## 3. Functional requirements

| ID | Requirement |
|---|---|
| FR1 | Floating RTL panel (Cairo, navy). AR/EN toggle, chat, history, file attach, thinking steps with one row per step and a result line, SVG charts |
| FR1b | Arabic end to end: Arabic messages get Arabic replies; `translations/ar.csv` supplies DocType and field labels; Arabic normalize for RAG/RDF |
| FR1c | Panel title, subtitle, Arabic hint, and English hint come from ERP AI Settings and can be changed without a code edit |
| FR2 | Session-user reads (`get_list` / `get_doc` / `get_meta` / reports). DocPerms always apply |
| FR3 | Pipeline: Guest → Blocked User → abuse → work-only → memory + persona → model-directed tools (schema-checked) → reply. Regex detectors, skills, and RAG run only when the model is off or the key is missing |
| FR4 | ERP AI Skill is editable. Seed covers installed apps, CRM DocTypes when present, HR, stock, and invoices. RDF maps labels such as اسم to `lead_name` on Lead and CRM Lead |
| FR4b | ERP AI Persona is editable. Active persona comes from Settings. ERP AI Memory can be cleared per user |
| FR5 | Create, update, delete, submit, and cancel go through ERP AI Pending Action. The user must check the box and approve. Nothing is written before that |
| FR5b | The proposal reads the DocType schema (mandatory fields, Select options, child tables). Missing required values are asked in the chat language, using field labels, not fieldnames. DocType defaults may be applied and must be shown. Values are not invented |
| FR5c | The payload, summary, target DocType, and payload hash cannot change after the proposal. Approval rechecks `allow_pending_writes`, revalidates the payload, and runs once. Reject is allowed only from `pending`. A second approve or a reject after execute is refused |
| FR5d | Any business DocType the user can access may be written this way. System DocTypes (User, Role, DocType, File, scripts) are denied |
| FR6 | Every chat and message is stored for that user. Document name is the Title field (no naming series) |
| FR7 | Abuse scan returns `contains_abuse` on every response. Hits create ERP AI Abuse Event. Threshold can block the user and notify managers |
| FR8 | ERP AI Settings: LLM, panel text, moderation, notify roles, blocked users, writes, persona, Overlay Pages |
| FR8b | Desk Workspace and System Manager reports. A Desktop Icon is seeded for the Desk home grid |
| FR8c | Panel JS/CSS belong to this app. The panel mounts on Desk and on each installed app route from `add_to_apps_screen` / `app_icon_route` |
| FR9 | Composer accepts images, CSV, XLSX, PDF, and text (5 MB, private File). Images go to the model. Tables are scored against Frappe import templates. A blank CSV header can be downloaded. Rows are not imported automatically |
| FR10 | Thinking steps are unique by id. Abuse and the work gate always appear. Each tool the model calls is one step with its result (required labels, row count, prepared DocType, or the error). A fallback turn shows the detector result |
| FR11 | Charts and list summaries state their sample limit (leads 200, invoices 30). They are not described as a full-table total when capped |
| FR12 | Conversation history sent to the model is the newest window, then shown in chronological order |

## 4. Non-functional

| ID | Requirement |
|---|---|
| NFR1 | No `ignore_permissions` and no `allow_guest` on chat APIs. No ERP API-key store |
| NFR2 | No third-party panel framework. Charts are SVG in this app. Host apps are not rebuilt |
| NFR3 | Approval card text uses `textContent`. Record links accept only `/desk/…` and routes of installed apps |
| NFR4 | RAG chunks copied from a skill are returned only if the user has one of that skill's roles |
| NFR5 | Secrets stay out of git. The LLM key is a Password field, site config, or an environment variable |
| NFR6 | Phone numbers must be valid. A missing number is requested. It is not replaced with another person's number or a placeholder |
| NFR7 | DocType forms use tabs, sections, and columns. Child tables show their main fields in the grid and the list. Arabic labels come from `translations/ar.csv` |

## 5. Out of scope

- Packaging a desktop application
- A tool loop that inserts or updates a business document without an approval card
- Automatic Data Import of uploaded rows
- Inventing e-invoice clearance identifiers when no such app is installed
- Binding the assistant to a single product app

## 6. Acceptance

On Desk and on an installed app's route, the panel opens with the Settings title and hint. Thinking steps appear once each, with a result line. The model runs last.

Off-work prompts are refused. Abuse is stored and can block. A create names the DocType the user asked for. Missing mandatory fields are listed by label in the message language. Approve runs the payload that was shown, once. A created record has a link to its form.

## 7. Tests

See `TEST_RESULTS.md`. The pipeline module covers T01–T25.
