# Test results — The ERPNext-AI-Assistant

Checklist for the pipeline. Run on a private bench; do not record site names, user names, or dates in this file.

| ID | Type | Result | Notes |
|---|---|---|---|
| T01 | unit | PASS | Guest cannot call `chat.run` / `approve_action` |
| T02 | unit | PASS | `tool_erp_query` uses `get_list`; no `ignore_permissions` / no `get_all` |
| T03 | unit | PASS | Work-only gate refuses poems and jokes (AR/EN) |
| T04 | unit | PASS | Abuse term creates ERP AI Abuse Event |
| T05 | unit | PASS | Threshold path exercised |
| T06 | unit | PASS | Blocked message in Arabic contains حظر |
| T07 | unit | PASS | RDF name label maps to `lead_name` / `first_name` / `last_name` |
| T08 | unit | PASS | CRM skill loads for a CRM leads route |
| T09 | unit | PASS | Pending Action stays pending until acknowledgment |
| T10 | unit | PASS | Reject stores rejected; no write |
| T11 | unit | PASS | Work gate is independent of persona |
| T12 | unit | PASS | Skill enable/disable is reflected in `read_skill` |
| T13 | unit | PASS | Chart payloads bar/line/pie/kpi; no Recharts import |
| T14 | unit | PASS | Non-allowlisted `run_method` rejected |
| T15 | integration | PASS | Chat + Message registered |
| T16 | integration | PASS | Workspace The ERPNext-AI-Assistant exists |
| T17 | integration | PASS | System Manager reports exist |
| T18 | browser | PASS | Host include loads the assistant bundle on an Overlay Page |
| T19 | browser | PASS | Panel 448×684; Arabic brand; thinking steps; model last |
| T20 | browser/API | PASS | Off-work Arabic refused; CSRF via `window.csrf_token`; write acknowledgment UI present |

## Config notes

- LLM key: ERP AI Settings Password field `api_key`, or site config `erp_ai_openai_api_key`, or `OPENAI_API_KEY` / `ERP_AI_API_KEY`
- Arabic: RTL panel, AR/EN toggle, `translations/ar.csv`, Arabic normalize for RAG/RDF
