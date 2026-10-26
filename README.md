# The ERPNext-AI-Assistant

Workplace AI assistant for **Frappe / ERPNext** (and related CRM/HRMS hosts).  
It ships as a Frappe app (`erpnext_ai_assistant`) with an Arabic-first RTL chat panel, session-scoped ERP tools, RAG/RDF retrieval, abuse moderation, and a Pending Action flow for writes.

> **Product name:** The ERPNext-AI-Assistant  
> **UI subtitle (AR):** مساعد ERPNext  
> **Module:** `ERP AI Assistant`

---

## What it does

| Capability | Behavior |
|---|---|
| Chat panel | Fixed desktop FAB + overlay panel on configured routes (`/crm`, `/app`, …) |
| Live ERP reads | Session-user `get_list` / `get_doc` / reports — **no** `ignore_permissions` |
| Writes | Never silent. Creates **ERP AI Pending Action**; user must acknowledge + approve |
| Memory | Rolling chat summary + session facts so follow-ups keep context |
| Charts | Server-built SVG charts (no heavy chart libraries in the panel) |
| Moderation | Abuse term scan → event → threshold block; work-only gate before the model |
| Knowledge | Skills, Persona, Memory DocTypes + RAG chunks + RDF metadata graph |
| LLM | OpenAI-compatible chat completions called **last** in the pipeline |

Permissions and Frappe roles always win. Guests cannot chat.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Host (Desk /crm / HRMS)                                    │
│  Overlay Pages match path → load app JS/CSS                 │
│  FAB + panel (Cairo / RTL / navy)                           │
└───────────────────────────┬─────────────────────────────────┘
                            │ frappe.call run / approve_action
┌───────────────────────────▼─────────────────────────────────┐
│  api/chat.py  →  services/run_chat.py                       │
│                                                             │
│  1. Guest reject                                            │
│  2. Blocked User check                                      │
│  3. Ensure ERP AI Chat + Message                            │
│  4. Abuse scan          → contains_abuse on every response  │
│  5. Work-scope gate     (deterministic, no LLM)             │
│  6. Skills + Persona + Memory                               │
│  7. RAG retrieve                                            │
│  8. Detectors → tool registry (RDF before name queries)     │
│  9. LLM complete        (OpenAI last)                       │
│ 10. Charts / Pending Action payload back to panel           │
└─────────────────────────────────────────────────────────────┘
```

### Integration model

- This app **owns** panel JS/CSS (`public/js`, `public/css`).
- Host apps opt in via **ERP AI Settings → Overlay Pages** (`path_pattern`, e.g. `/crm`, `/app`).
- Desk also loads assets through `app_include_js` / `app_include_css`.
- CRM SPA can load a thin `crm_include.js` shim.

Do **not** put assistant CSS into a theme app.

### DocTypes (module: ERP AI Assistant)

| Area | DocTypes |
|---|---|
| Conversation | ERP AI Chat, ERP AI Message, ERP AI Generated Query, ERP AI Generated Chart |
| Knowledge | ERP AI Knowledge Document, ERP AI Knowledge Chunk, ERP AI Metadata Cache |
| Safety / writes | ERP AI Pending Action, ERP AI Abuse Event, ERP AI Audit Log |
| Config | ERP AI Skill (+ Role), ERP AI Persona (+ Role), ERP AI Memory |
| Settings (Single) | Abuse Term, Notify Role, Blocked User, Overlay Page children |

**Workspace:** `The ERPNext-AI-Assistant` (System Manager).

**Reports:** ERP AI Chats by User · Abuse Summary · Pending Actions · Skill Usage · Memory Overview.

---

## Tool registry

All tools run as the **logged-in session user**.

### Read

| Tool | Purpose |
|---|---|
| `tool_rdf_lookup` | Metadata / name graph lookup (preferred before free-form name queries) |
| `tool_erp_query` | Permission-aware `frappe.get_list` |
| `tool_erp_get_doc` | Permission-aware `get_doc` |
| `tool_erp_report` | Query Report runner |
| `tool_get_doctype_meta` | Field labels / types for a DocType |
| `tool_run_method` | Allowlisted whitelisted methods only |
| `tool_read_doctype_controller` | Controller source (System Manager only) |
| `tool_list_installed_apps` | Describe installed apps on the site |
| `build_chart` | Aggregate + SVG chart payload |
| `read_skill` | Role- and route-filtered ERP AI Skill rows |

### Write

| Tool | Purpose |
|---|---|
| `propose_write` | Creates **ERP AI Pending Action** only |
| `approve_action` / `reject_action` | API: execute or cancel after written acknowledgment |

---

## Package layout

```
erpnext_ai_assistant/
├── README.md
├── pyproject.toml
├── docs/
│   ├── PLAN.md
│   ├── SRS.md
│   ├── architecture.md
│   └── TEST_RESULTS.md
└── erpnext_ai_assistant/
    ├── hooks.py
    ├── install.py                 # seeds settings, persona, skills, overlays
    ├── api/chat.py                # whitelisted run / approve / reject / boot
    ├── public/js|css/             # panel + CRM include
    ├── services/
    │   ├── run_chat.py            # orchestrator
    │   ├── conversation.py        # history + session facts
    │   ├── detectors.py           # intent → tools/charts/pending
    │   ├── moderation/            # abuse + work_gate
    │   ├── llm/provider.py        # OpenAI-compatible client
    │   ├── rag/                   # knowledge retrieve / reindex
    │   ├── rdf/                   # metadata graph
    │   ├── charts/                # SVG builders
    │   └── tools/registry.py      # session-user tools
    ├── skills/                    # seed skill content
    └── erp_ai_assistant/          # DocTypes, Workspace, Reports
```

---

## Install

Requires **Frappe v16** and a site with ERPNext (CRM/HRMS optional).

```bash
cd /path/to/frappe-bench
bench get-app https://github.com/ahmad18189/erpnext_ai_assistant.git
bench --site your.site install-app erpnext_ai_assistant
bench --site your.site migrate
bench build --app erpnext_ai_assistant
bench --site your.site clear-cache
```

### Configure the LLM key (do not commit secrets)

Prefer one of:

1. **Desk:** ERP AI Settings → **API Key** (Password field)
2. **site_config.json** (server only):

```json
{
  "erp_ai_openai_api_key": "YOUR_OPENAI_API_KEY"
}
```

3. Environment: `OPENAI_API_KEY` or `ERP_AI_API_KEY`

Optional Settings fields: `provider_base_url` (default OpenAI), `model` (default `gpt-4o-mini`), temperature, max tokens, Overlay Pages, abuse thresholds.

### Overlay Pages

Seed includes:

- `/crm` — CRM SPA  
- `/app` — Frappe Desk  

Add more paths (e.g. HRMS) under ERP AI Settings → Overlay Pages.

---

## API surface (session user)

| Method | Role |
|---|---|
| `erpnext_ai_assistant.api.chat.run` | Send a message; returns answer + `contains_abuse` + charts/pending |
| `erpnext_ai_assistant.api.chat.approve_action` | Execute pending write after ack |
| `erpnext_ai_assistant.api.chat.reject_action` | Cancel pending write |
| `erpnext_ai_assistant.api.chat.get_boot` | Panel boot (persona, overlays, blocked flag) |

Every `run` response includes:

```json
{
  "status": "complete | refused_abuse | refused_work | blocked | …",
  "contains_abuse": false,
  "abuse": {
    "hit": false,
    "category": null,
    "score": 0,
    "matched": [],
    "event_name": null,
    "blocked_now": false
  },
  "message": "…",
  "chat_id": "…",
  "charts": [],
  "pending_action": null
}
```

Realtime thinking steps publish on `erp_ai_thinking` / room `erp_ai_chat:{chat_id}`.

---

## Security model

- **No Guest** chat.
- ERP reads/writes use the **session user** only.
- Abuse list is seeded + always unioned at scan time; hits create **ERP AI Abuse Event**.
- Threshold on Settings can append **Blocked User** and notify manager roles.
- Writes require checkbox + acknowledgment text before `approve_action`.
- API keys must live in Password / `site_config` / env — **never** in this repository.

---

## Development docs

| Doc | Contents |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Product decisions and scope |
| [`docs/SRS.md`](docs/SRS.md) | Functional requirements |
| [`docs/architecture.md`](docs/architecture.md) | Pipeline, DocTypes, tools |
| [`docs/TEST_RESULTS.md`](docs/TEST_RESULTS.md) | Pipeline test IDs |

Run app tests (bench):

```bash
bench --site your.site run-tests --app erpnext_ai_assistant
```

---

## License

MIT — see [`license.txt`](license.txt).

License: MIT. See `license.txt`.
