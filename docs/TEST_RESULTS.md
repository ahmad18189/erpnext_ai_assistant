# Test results — The ERPNext-AI-Assistant

Checklist for `erp_ai_assistant/doctype/erp_ai_chat/test_erp_ai_assistant_pipeline.py`.  
Run on a private bench. Do not record site names, user names, or dates here.

```bash
bench --site your.site run-tests --app erpnext_ai_assistant --module erpnext_ai_assistant.erp_ai_assistant.doctype.erp_ai_chat.test_erp_ai_assistant_pipeline
```

| ID | What it checks |
|---|---|
| T01 | Guest cannot call `chat.run` or `approve_action` |
| T02 | `tool_erp_query` uses `get_list` and does not use `get_all` or `ignore_permissions` |
| T03 | Work gate refuses poems and jokes in Arabic and English |
| T04 | An abuse term creates ERP AI Abuse Event |
| T05–T06 | Threshold blocks the user; Arabic blocked text contains حظر |
| T07 | RDF lookup of اسم includes `lead_name` on Lead or CRM Lead |
| T08 | A CRM skill loads for a leads route when that skill is seeded |
| T09–T10 | Pending Action stays pending until reject; reject does not write the target |
| T11 | Work gate does not depend on persona |
| T12 | Disabling a skill removes it from `read_skill` |
| T13 | Chart payloads are bar, line, pie, and kpi, with no Recharts import |
| T14 | A method outside the allowlist is rejected |
| T15 | `chat.run` stores ERP AI Chat and the user message |
| T16 | Workspace The ERPNext-AI-Assistant exists |
| T17 | System Manager reports exist |
| T18 | History returns the newest 16 messages, oldest of that window first |
| T19 | A call with no phone number is not given a placeholder number |
| T20 | Changing `payload_json` after propose raises ValidationError |
| T21 | A second approve and a reject after execute leave status `executed` |
| T22 | Another user cannot approve the owner's pending action |
| T23 | A skill limited to System Manager is not returned by RAG for a user without that role |
| T24 | `prepare_payload("ToDo")` lists `description` until it is supplied |
| T25 | The approval summary in the panel script uses `textContent`, and links go through `safeLocalPath` |

## Config notes

- LLM key: ERP AI Settings Password `api_key`, or site config `erp_ai_openai_api_key`, or `OPENAI_API_KEY` / `ERP_AI_API_KEY`
- Arabic: `translations/ar.csv` plus `get_all_translations` for suggestion labels
- Panel copy: ERP AI Settings fields `panel_title`, `panel_subtitle`, `panel_hint`, `panel_hint_en`
