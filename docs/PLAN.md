# The ERPNext-AI-Assistant — Plan

Frappe app / Python module: `erpnext_ai_assistant`.  
Module: `ERP AI Assistant`.

The panel is a 448×684 RTL shell (Cairo, navy `#0f1b2e`) with header, new chat, close, language toggle, chat/history, messages, attach, and composer. Header and hint text come from ERP AI Settings.

## Decisions

- The assistant serves every installed app. Routes come from app hooks. It is not hard-wired to one CRM.
- Permissions win. Reads use the session user. No `ignore_permissions` on business data. No Guest chat.
- Writes are a contract. Schema first, then a Pending Action whose payload cannot change, then one approval.
- Missing required fields are asked by label in the user's language. DocType defaults may be used and must be shown. Business values, including phone numbers, are not invented.
- Abuse runs before the work gate. `contains_abuse` is on every response. Blocked User is the block record.
- Skills, persona, and memory are DocTypes. RAG honors skill roles. RDF runs before a name query.
- The model is last. Retrieved text and chat summaries are context, not new authority.
- Charts are SVG in this app and are labeled when they are a sample.
- History sent to the model is the newest window.
- Uploaded tables are reviewed against Frappe import templates. They are not imported by the assistant.
- Document names are the Title (or Persona Name). No naming series.
- Secrets are not committed.

## Package

```
erpnext_ai_assistant/
  erpnext_ai_assistant/
    hooks.py
    install.py
    api/chat.py
    public/js|css|images
    services/
      run_chat.py
      schema.py
      writes.py
      apps.py
      imports.py
      detectors.py
      conversation.py
      moderation/
      rag/
      rdf/
      llm/
      tools/
    erp_ai_assistant/          DocTypes, workspace, reports
    skills/seed.py
    translations/ar.csv
  docs/PLAN.md  SRS.md  architecture.md  TEST_RESULTS.md
```

## Build order already followed

1. App, DocTypes, Workspace, panel on Overlay Pages.
2. `run_chat` gates, skills, RDF, charts.
3. Schema-backed writes, approval lock, role-filtered RAG.
4. File upload and import-template review.
5. Installed-app routes instead of a single host.

See `SRS.md` and `architecture.md`.
