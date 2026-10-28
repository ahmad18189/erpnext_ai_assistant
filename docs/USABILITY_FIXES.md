# Usability fixes for everyday users

Started 28 October 2026. This file tracks every fix found in the usability review and is updated as each one lands.

## Why

The assistant is for staff who don't know DocTypes or field names: sales, finance, the back office. They should be able to ask in Arabic or English, land on the right screen, and change data only after Approve. The safety design is strong. Ease of use is not there yet.

We put 14 typical questions to the dev site (`erpnext-dev`, Frappe 16.53, ERPNext 16.52, demo company Majal) as three ordinary users: `sales@demo.test`, `accounts@demo.test` and `viewer@demo.test`. The evidence column quotes what they got.

## Status

| # | Fix | Priority | Status |
|---|---|---|---|
| 1 | Counting crashes on Frappe 16 | P0 bug | ✅ Done |
| 2 | Check the target record before showing a card | P0 bug | ✅ Done |
| 3 | Let users leave an unfinished create | P0 bug | ✅ Done |
| 4 | Fill system fields the way ERPNext does | P1 ease of use | ✅ Done |
| 5 | Write approval cards in plain language | P1 ease of use | ✅ Done |
| 6 | Answer with content, not just a list link | P1 ease of use | 🟡 Started (records list + Open list) |
| 7 | Remove DocType jargon and make choices clickable | P1 ease of use | To do |
| 8 | Starter prompts based on the user's role | P1 ease of use | To do |
| 9 | Use the open form as context | P1 ease of use | To do |
| 10 | Answer report questions (receivables, aging, sales) | P2 feature | To do |
| 11 | Offer follow-up actions after an answer | P2 feature | 🟡 Started (buttons after counts and lists) |
| 12 | Document actions ERPNext already has (`make_*`) | P2 feature | To do |
| 13 | How-to answers for the current screen, faster | P2 feature | To do |
| 14 | 👍/👎 feedback on answers | P2 feature | To do |
| 15 | Counts use the wrong DocType or ignore status words | P0 bug | ✅ Done |
| 16 | Follow-ups lose the previous question's filters and context | P0 bug | ✅ Done |

---

## P0: bugs that break trust

### 1. Counting crashes on Frappe 16

- **Evidence:** "how many customers do we have?" and "كم عدد أوامر البيع المعتمدة؟" returned HTTP 417: `SQL functions are not allowed as strings in SELECT: count(name) as total`.
- **Where:** `services/targeting.py` `_sql_total`, `_sql_bounds` and `_sql_groups` pass `count(...)`, `min(...)`, `max(...)` and `sum(...)` as strings to `frappe.get_list`. Frappe 16 accepts only the dict form, such as `{"COUNT": "*", "as": "total"}`. The unit tests mock this path, so they passed.
- **Fix:** build aggregate fields in the dict form on Frappe 16 and the string form on Frappe 15, so the `version-15` port works unchanged. Keep `get_list`, so permissions still apply.
- **Done when:** both questions return a number on the dev site, and a test runs the real query without mocks.
- **✅ Done (2026-10-28):**
  - `_agg()` in `services/targeting.py` builds `{"COUNT": "*", "as": "total"}` on Frappe 16 and `count(name) as total` on Frappe 15. `_sql_total`, `_sql_bounds` and `_sql_groups` use it.
  - The model's `count_records` tool (`tool_erp_count`) goes through `DatabaseQuery`, which still accepts strings, so it was unchanged.
  - Checked on the dev site: "how many customers do we have?" → 8, "how many leads" → 10.
  - Tests: `test_usability_fixes.TestCountQueries` runs real count, min/max and group-by queries, and checks the Frappe 15 form.
  - Count answers can still be *wrong* (wrong DocType, ignored "submitted"). That is fix 15.

### 2. Check the target record before showing a card

- **Evidence:**
  - "submit the draft invoice for Blue Ocean Trading" made a card to submit a Sales Invoice *named* "Blue Ocean Trading". It doesn't exist, and that customer has no draft invoice.
  - "mark my first overdue task as completed" (viewer) made a card that updates an unrelated ToDo, shown only as `0cj1q2c7jv`.
- **Where:** `propose_write` in `services/tools/registry.py` checks the payload only for create. For update, delete, submit and cancel, the `target_name` from the model is stored without any check.
- **Fix:** before storing a card for update, delete, submit or cancel:
  - the record must exist
  - the user must have that permission on that record
  - submit needs a draft; cancel needs a submitted record
  - when the name isn't a real record, look it up by title or customer/party in the right state: one match → use it; several → list up to 5 to choose from; none → say so plainly
- **Done when:** the Blue Ocean request gets "no draft Sales Invoice for Blue Ocean Trading"; a request for a customer with a draft invoice gets a card for that real invoice; wrong-state and no-permission requests get no card.
- **✅ Done (2026-10-28):**
  - `resolve_write_target()` in `services/writes.py` runs inside `propose_write` (`services/tools/registry.py`) for every update, delete, submit and cancel, so all paths (model tools, detectors, schema writes) are covered.
  - **Exact name:** checks state, then the user's permission on that record.
  - **Not a real name:** searches the title, search fields, party and subject/description fields in the required state, scoped to the user's permissions. One match → card; 2–5 → "Which one?" list; none → "I could not find a draft Sales Invoice matching … Nothing was prepared."
  - **State rules (submittable DocTypes only):** submit and update need a draft (allow-on-submit fields excepted); cancel needs submitted; delete refuses submitted. Non-submittable DocTypes can't be submitted or cancelled.
  - The card now has a second line describing the record (title or party, amount, date, status). That is the start of fix 5.
  - `services/intent.py` now recognizes submit, cancel and delete (English and Arabic), so these requests no longer get the "Count / Show / Create" menu.
  - Checked on the dev site, as `accounts@demo.test` unless noted:

    | Request | Result |
    |---|---|
    | Blue Ocean (no draft) | Plain "none to submit" answer, no card |
    | مؤسسة النور (has a draft) | Card for ACC-SINV-2026-00001 with customer, 5,900.00, date, Draft |
    | Submit an already submitted invoice | Refused, explains why |
    | Delete a submitted invoice | "Cancel it before deleting it" |
    | Cancel as `viewer@demo.test` | Refused |

  - Tests: `test_usability_fixes.TestWriteTargets` (8 tests).
  - **Known limit:** "submit the draft quotation" with 2 drafts → the model queried 1 row and passed a real name, so the card went to one of them without asking. The card now shows customer and amount. Making the model ask when several match belongs with fix 15.

### 3. Let users leave an unfinished create

- **Evidence:** after "create a quotation for Delta Systems…", the next messages "what is overdue?" and "change customer Delta Systems group to Key Accounts" both got "Send Company…" / "Send Currency…".
- **Where:** `continue_guided_create` in `services/tools/agent.py` lets go only for how-to, count or query messages.
- **Fix:**
  - "cancel / stop / never mind / إلغاء / الغ / توقف" ends the draft and says so
  - a question, or a request with a different action or DocType, sets the draft aside with a short note and is answered normally
  - only something that looks like an answer to the missing field continues the draft
- **Done when:** the three messages above get normal answers, "cancel" clears the draft, and a plain value such as "SAR" still fills the draft.
- **✅ Done (2026-10-28):**
  - **Cause:** a question like "what is overdue?" was stored as the *value* of the missing field, and `pending_intent` was copied into every later turn's session facts, so the draft never ended.
  - `leave_draft()` in `services/tools/agent.py` classifies the message against an open draft:
    - **"cancel":** short cancel words with no DocType or record number → the draft is cleared and the reply says "Okay, I dropped the Quotation draft. Nothing was saved."
    - **"aside":** a question, or another action (update, submit, cancel, delete, count, show) or DocType → the draft keys are removed from the session and the message is answered normally, with a one-line note.
    - **None:** anything else is treated as the value and continues the draft, as before.
  - `services/run_chat.py` calls it before the chart, navigation and clarify shortcuts.
  - Checked on the dev site: the original three-message sequence now gives a normal answer, then a correct update card; "cancel" and "إلغاء" drop the draft; "SAL-QTN-.YYYY.-" still fills Series and moves on to Company.
  - Tests: `test_usability_fixes.TestLeaveDraft` (5 tests). "cancel sales invoice ACC-SINV-…" is a record action, not "drop the draft".

---

### 15. Counts use the wrong DocType or ignore status words

Found on 2026-10-28 while checking fix 1. **The most serious open problem**: the user gets a confident, wrong number and has no way to notice.

- **Evidence** (dev site truth: 4 sales orders, 3 submitted; 12 sales invoices):

  | Question | Answer |
  |---|---|
  | كم عدد اوامر البيع (how many sales orders) | "عدد أوامر البيع هو 12" (the model counted Sales Invoice) |
  | كم عدد أوامر البيع المعتمدة؟ (approved sales orders) | 0 |
  | how many sales orders are submitted? | 4 ("submitted" ignored) |
  | show a chart of sales invoices by customer | "You can see 8 Customer records." |
  | أنشئ عرض سعر لشركة الأفق (create a quotation for Al-Ofuq) | Started a **Company** draft |
  | كم عدد أوامر البيع المعتمدة؟ (asked after a customer count, same chat) | "عدد سجلات Customer الظاهرة لك: 8" (carried over the previous DocType) |

- **Where:**
  - `_PHRASES` in `services/targeting.py` has "امر بيع" but not plurals with the article ("اوامر البيع"), and has no "عرض سعر" (quotation).
  - Status words (submitted/معتمد, draft/مسودة, cancelled/ملغى, overdue/متأخر) are not turned into filters on the shortcut path.
  - "chart … by customer" matches the word "customer" as the DocType.
  - The model's free-text answer names the DocType it *meant*, not the one it counted, and the live-evidence check (`_has_live_evidence` in `services/tools/agent.py`) only checks that *some* count ran.
  - A low-confidence follow-up reuses the previous turn's `chosen_doctype`.
- **Fix:**
  - Add the missing Arabic and English phrases, with plurals and the article.
  - Map status words to `docstatus` and `status` filters.
  - When a phrase names "X by Y", treat X as the DocType and Y as the grouping.
  - Build the count sentence from the tool result (DocType label and filters used) instead of the model's wording.
  - Reuse the previous DocType only when the new message names none.
  - When several records fit a write ("the draft quotation"), list them instead of picking one.
- **Done when:** every row in the table above gives the right number or DocType, and each count answer names what was counted, e.g. "3 submitted Sales Orders".
- **✅ Done (2026-10-28):**
  - **Phrases** (`_PHRASES` in `services/targeting.py`): sales/purchase order plurals with the article (اوامر البيع), quotation (عرض سعر, عروض الاسعار), payments, delivery notes, projects, and a bare "invoices"/"فواتير" → Sales Invoice. Purchase-invoice phrases are longer, so they still win.
  - **"X by Y":** `without_grouping()` removes "by customer"/"حسب العميل" before matching, so "chart of sales invoices by customer" is about Sales Invoice. The live chart now groups by the named field (`_named_group_field` in `services/charts/live.py`) and labels it in the chat language.
  - **"X for Y":** `doctype_text()` matches the DocType on the words before "for/to/from/with/لشركة/للعميل…", then falls back to the whole sentence. "Create a quotation for Al-Ofuq company" was going to Company or Supplier and now goes to Quotation (reported from the browser on 2026-10-28).
  - **Status words → filters:** `state_filters_for()` turns submitted/معتمدة, draft/مسودة, cancelled/ملغاة into `docstatus`; overdue/paid/open/completed/closed into the DocType's own `status` options; unpaid/غير مدفوعة into "outstanding amount > 0". The words are named in the answer: "You can see 3 Sales Order records (submitted)."
  - **Count answers** use the DocType label in the chat language ("عدد سجلات طلب المبيعات الظاهرة لك: 3 (معتمدة)").
  - **Model path:** when the model's answer contains a number, a line built from the real tool result is added, e.g. "تم التحقق: 0 من فاتورة مبيعات (status = Unpaid)", so a mismatch is visible.
  - **No access:** "You cannot read Quotation." replaces "I did not check the records" when the count failed on permission.
  - Checked on the dev site: every row of the table now gives the right answer (4 sales orders, 3 submitted, a chart grouped by customer, 4 overdue, Quotation for Al-Ofuq).

### 16. Follow-ups lose the previous question's filters and context

Reported from the browser on 2026-10-28: "the chat does not continue from the old calls".

- **Evidence:**
  - After "how many overdue sales invoices?" (4), "show them" listed all 12 invoices: the overdue filter was dropped.
  - "which customer has the biggest one?" got the "Customer: Count / Show / Create" menu.
- **Where:** `services/run_chat.py` carried only the DocType (`chosen_doctype`) to the next turn. The previous question's text was reused only for "as Excel" follow-ups. A low-confidence turn's model answer was replaced by the clarify menu.
- **✅ Done (2026-10-28):**
  - `refers_back()` recognizes follow-ups: them, those, it, the biggest one, اعرضها, منها, هذه….
  - A follow-up on the same DocType reuses the previous question's text for filters ("show them" → still overdue). `last_query` stores that combined text, so chains keep it ("export them to excel" → the same 4).
  - Follow-ups skip the clarify menu, both before and after the model, and the model is told which earlier question is being continued.
  - Checked on the dev site: "how many overdue sales invoices?" → 4; "show them" → the 4 overdue invoices; "which customer has the biggest one?" → "شركة الرواد, 12,300.00"; "export them to excel" → a file with those 4; Arabic "كم عدد الفواتير المتأخرة" → "اعرضها" works too.

## Security fixes from the panel redesign review (2026-10-28)

A four-person agent review of `docs/PANEL_REDESIGN_PLAN.md` (UX, frontend, product, security) found these problems in the **current** code. Both blockers were reproduced on the dev site before fixing.

| # | Problem | Proof before the fix | Fix | After |
|---|---|---|---|---|
| S1 | **Forged approval cards.** Role "All" had create/write on ERP AI Pending Action, so any user could insert a card through `/api/resource` with any summary and payload | `viewer@demo.test` inserted `probe-forged-card` with action delete | REST create/write removed for "All" (read own cards only). `before_insert` refuses any card not created through `allow_card_insert()` (used only by `propose_write` and `propose_import`) and sets `user` to the session user | 403 on REST insert |
| S2 | **A link could approve a card.** `approve_action`, `reject_action`, `run`, `upload_attachment`, `save_my_memory` and `clear_my_memory` accepted GET, which skips Frappe's CSRF check | `GET …/reject_action?pending_action=…` returned 200 | `@frappe.whitelist(methods=["POST"])` on all six | 403 on GET |
| S3 | **Stale approvals.** A card could be approved after its record changed, or days later | — | New locked `target_modified` field stored at proposal time. Approval refuses and marks the card `expired` if the record changed, was deleted, or the card is more than 24 h old | Card says "ToDo … changed after this card was prepared. Ask again…" and nothing is written |
| S4 | **A manager could approve another user's card** | — | Only the requester approves. A System Manager can still reject | "Only the person who asked can approve this card" |
| S5 | **Approval re-checks were incomplete** | — | Per-record permission (`has_permission(dt, need, doc=name)`); DENIED_DOCTYPES checked again; update payloads re-checked with `prepare_payload(…, "update")`; protected keys (`name`, `owner`, `docstatus`, `modified`…) stripped | `test_update_cannot_set_protected_fields` |
| S6 | **Raw errors reached the user** | `str(e)` returned and stored | ERPNext validation messages are shown as plain text. Anything else is logged to the Error Log with a plain message. The card stays pending so the user can fix the cause and retry | — |
| S7 | **Model-written links to other sites were clickable** | `inlineMd` turned any `https://` link into an anchor | Only links to this site become anchors. Others are shown as text. Answer text was already HTML-escaped before markdown | — |

Tests: `test_security.py` (8 tests) covers S1–S5 and S7. Two older tests now create their cards through `allow_card_insert()`. Suite: 81 tests; only T08 and T21 fail, as before.

Still open from the security review, to be done with the redesign: `rate_message` must be POST-only, owner-checked and rate-limited; the context chip must use a server permission check; card text should be rebuilt from the payload when history is reloaded.

## P1: ease of use

### 4. Fill system fields the way ERPNext does
- **Evidence:** a quotation asked for Series, Company, Currency, Exchange Rate, Price List and Price List Exchange Rate.
- **Where:** `prepare_payload` in `services/schema.py` applies only DocType defaults.
- **Fix:** start from `frappe.new_doc()` with user and global defaults (company, currency, price list), let ERPNext's `set_missing_values` run where it exists, and auto-pick Select fields that have one option. Ask only for business fields (party, items, quantities, dates). List the filled defaults on the card.
- **Done when:** "create a quotation for Delta Systems for 2 laptops" goes straight to a card.
- **✅ Done (2026-10-28):**
  - **New `services/autofill.py`:**
    - `fill_header()` fills single-option series, the user's or the only company, the company currency, selling/buying price list from Selling/Buying Settings, price-list currency, and exchange rates of 1 when the currency is the company's. A "company" value that is not a real Company (e.g. "لشركة الأفق" read as Company) is dropped.
    - `fill_rows()` completes item rows from the Item master: real item name, description, unit, factor 1, and the price-list rate. Required column defaults are stored with their real type.
    - `sentence_values()` reads the party ("for Delta Systems", "لشركة الأفق") and "N item" pairs ("2 laptops and 1 printer", "3 كراسي مكتب", with Arabic plurals), resolved against records the user can read. An unknown item gives "No item matches “spaceships”", not a guess.
  - **Dates that orders need:** Sales Order delivery date and Purchase Order required-by date are asked for (they are business values), read from "in 10 days", "2026-11-20" or "غدا", and copied to the item rows like the Desk form does.
  - The model's DocType description lists these fields as `filled_automatically`, and the `propose_write` tool says not to ask for them.
  - The missing-field message lists only what a person types: "Items (Quotation Item: Item, Quantity)".
  - **Three existing bugs found and fixed on the way** (`services/schema.py`):
    - child tables were rejected as "Unknown field items", so no document with items could ever be proposed;
    - approval re-checked "Today"-default dates as missing, so any such create failed on Approve;
    - defaults were stored as strings, so a Check default "0" was true in Python. ERPNext then refused stock items with "Item must be a Non-Stock Item".
  - Item rows now survive the turn that asks for the delivery date (`collected` keeps row lists).
  - Checked on the dev site, approved through `approve_action` as `sales@demo.test`:

    | Request | Result |
    |---|---|
    | create a quotation for Delta Systems for 2 laptops | **SAL-QTN-2026-00005 created** |
    | أنشئ عرض سعر لشركة الأفق لعدد 3 كراسي مكتب | **SAL-QTN-2026-00006 created** |
    | sales order for Blue Ocean Trading for 5 monitors and 2 printers → "deliver in 10 days" | **SAL-ORD-2026-00005 created** |
    | "create a quotation for Delta Systems" → "3 chairs" | Card |
    | … for 2 spaceships | "No item matches “spaceships”" |

### 5. Write approval cards in plain language
- **Evidence:** the card read `update ToDo 0cj1q2c7jv / status: Completed`.
- **Where:** `summary_from_payload` in `services/writes.py`.
- **Fix:** show the record's title and key amounts, before → after for each change, field labels in the chat language, and an "Open record" link.
- **Done when:** a non-technical user can tell from the card which record changes and how.
- **✅ Done (2026-10-28):**
  - **Card text** (`summary_from_payload` in `services/writes.py`, now with the chat language):
    - a verb and the DocType label ("New Quotation", "تعديل عميل…", "اعتماد فاتورة مبيعات…")
    - the record line (party, amount, date, status)
    - field labels instead of field names, with before → after for changes ("Customer Group: Demo Customers → Key Accounts")
    - item lines with quantity and price, and a total
    - one "Filled automatically: Majal · SAR · Standard Selling" line
    - series, exchange rates, unchanged defaults and false checkboxes are left out
  - **Panel** (`public/js/erpnext_ai_assistant.bundle.js`):
    - the summary is no longer printed twice (the bubble keeps the first paragraph; the card shows the rest, line breaks kept)
    - Approve is enabled only after the checkbox, and both buttons lock while a request runs and after it lands
    - a failed approval shows "Could not save: <reason>" and can be retried
    - Reject now confirms "Rejected. Nothing was saved."
  - The cache version is bumped to `ai25` in `hooks.py` and both JS files. `hooks.py` had been left at ai23.
  - Example card: "New Quotation / Customer: Delta Systems / • 2 × Laptop @ ر.س 3,500.00 / • 1 × Office Printer @ ر.س 900.00 / Total: ر.س 7,900.00 / Filled automatically: Majal · SAR · Standard Selling".

### 6. Answer with content, not just a list link
- **Evidence:** "show my open quotations" returned only a link to the Quotation list.
- **Fix:** apply "my" (owner or assignee) and status words as filters. Show the top 5 rows inline (name, party, total, date) and an "Open full list" link with the same filters.

### 7. Remove DocType jargon and make choices clickable
- **Evidence:** "Did you mean 1. ToDo 2. Task? Name the DocType and the next step"; "Customer. What should I do? 1. Count 2. Show 3. Create". The placeholder says "Ask about a record, a DocType…".
- **Fix:** use everyday words ("Project tasks or your personal to-dos?"), render the options as buttons, and drop "DocType" from user-facing text.

### 8. Starter prompts based on the user's role
- **Evidence:** "what can you do?" gives generic examples ("how many todos").
- **Fix:** build 3–4 starter buttons from the user's roles and installed apps. Accounts: overdue invoices, who owes us, payments this week. Sales: my open quotations, new quotation. Projects: my tasks, overdue tasks.

### 9. Use the open form as context
- **Evidence:** the panel never reads the current form, so "submit this" or "summarize this invoice" can't work.
- **Fix:** send the current route's DocType and name with each message. On a form, offer Summarize, What's missing?, Submit this, and Next step.

---

## P2: features

### 10. Answer report questions
- **Evidence:** "which customers owe us money and how much?" → "Customer. What should I do? 1. Count 2. Show 3. Create".
- **Fix:** map receivables, aging, top customers and sales-by-period questions to the standard reports (Accounts Receivable, Sales Analytics), checking report permission. Reply with one sentence, a small table and the report link.

### 11. Offer follow-up actions after an answer
- **Fix:** after an answer, add buttons such as [Show them] [Chart] [Export to Excel] [Draft reminder]. "لديك 4 فواتير متأخرة." should come with the list and the total.
- **🟡 First part done (2026-10-28), at the user's request:** "when something is shown as a count, add a button or option to show it in a table or show the results".
  - After a count, the answer has three buttons: **عرض القائمة / Show the list**, **مخطط / Chart**, **تصدير Excel / Export to Excel**. After a list or chart, the views not yet shown are offered. There are no buttons after an empty result or with an approval card, and only the newest answer keeps its buttons.
  - Each button sends a fixed follow-up text from `follow_ups()` (`services/present.py`), e.g. "اعرض هذه كقائمة" or "show them as a list". It goes through the normal chat, so the previous question's filters stay (fix 16), and the button never carries an action or a card id. The label is set as plain text (`renderSuggestions` in `public/js/assistant/panel.js`).
  - **"Show the list" lists the records themselves** (part of fix 6): `records_table()` in `services/targeting.py` uses the count's own filters and permissions. It shows number, customer, date, total and status, newest first, at most 10 ("Showing the newest 10" when there are more), and an **Open list** button for the same filters in Desk (`/desk/sales-invoice?status=Overdue`).
  - The Arabic button texts use "هذه" rather than an attached pronoun ("اعرضها"), so they take the fast, exact path instead of the model.
  - Checked: "كم عدد الفواتير المتأخرة" gives 4 with the three buttons; "عرض القائمة" lists the 4 overdue invoices; "مخطط" and "تصدير Excel" work on the same 4; English is the same with drafts. The browser shows the buttons and clicking works, with no errors. Screenshots: `erpnext-dev/screenshots/followups-*.png`. Tests: `TestFollowUps11` (2 tests); suite 84, only T08 and T21 fail.
  - Still to do in fix 11: a "Draft reminder" button (it needs an email card), and buttons on model-written answers.

### 12. Document actions ERPNext already has
- **Fix:** wrap `make_sales_order`, `get_payment_entry`, lead → customer and similar functions behind the same approval card, instead of filling forms field by field.

### 13. How-to answers for the current screen, faster
- **Evidence:** "how do I make a sales order from a quotation?" described a new sales order from scratch and took 11 s.
- **Fix:** prefer the button path on the current document ("On the Quotation, click Create → Sales Order"), and cache manual lookups.

### 14. 👍/👎 feedback on answers
- **Fix:** store a rating per assistant message next to ERP AI Enhancement, and add a report showing where users get stuck.

---

## Change log

- 2026-10-28: file created from the usability review. Fixes 1–3 started.
- 2026-10-28: fixes 1, 2 and 3 done and checked on the dev site. Fix 5 started (record line on cards). Fix 15 added after testing showed wrong counts. The app suite runs 65 tests: the 15 new ones pass, and the only failures are T08 and T21, which also fail on `main`.
- 2026-10-28: fixes 15 and 16 (found while testing) done, then fixes 4 and 5. `test_usability_fixes.py` has 23 tests covering fixes 1–5, 15 and 16. Suite: 65 tests; only T08 and T21 fail, as on `main` before. Research notes added: `docs/ARCHITECTURE_REVIEW.md` (agent architecture compared with this code) and `docs/CHAT_DESIGN_RESEARCH.md` (how other assistants design their chat). Fixes 6–14 are next, with the panel redesign.
- 2026-10-28: security fixes S1–S7 from the redesign review, with `test_security.py`.
- 2026-10-28: panel redesign plan approved; phase 0 (foundations) done: live steps work, the panel is split into six files, answers are built without HTML, the conversation survives rebuilds, one automatic asset version. Details in `docs/PANEL_REDESIGN_PLAN.md`, Progress.
- 2026-10-28: next-step buttons after counts (fix 11, first part) and a real records list with an Open list link (fix 6, first part).
