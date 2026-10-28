# Assistant panel redesign plan

Status: **approved 2026-10-28. Phase 0 done** (see the progress table below). Nothing in sections 1–7 is built yet. The security blockers found in review are already fixed and committed (S1–S7 in `docs/USABILITY_FIXES.md`).

## 1. Brief

- **Subject:** an assistant inside ERPNext Desk. It answers questions about business records and prepares documents that are saved only after a person approves them.
- **Audience:** sales, accounts and back-office staff, often Arabic-first. They know their documents ("the overdue invoices", "a quotation for Delta"), not DocTypes or field names. They use the panel in short bursts while working in Desk.
- **Primary job:** a correct, checkable answer, or a ready-to-approve document, in one or two turns, without leaving the page.
- **Constraints:**
  - vanilla JS/CSS in this app; no framework, no host rebuild (NFR2)
  - record and model text is never rendered as raw HTML
  - Arabic and English are both first-class
  - Frappe v16 (`/desk`) and v15 (`/app`)
  - nothing is written before approval (FR5)

## 2. What is wrong today

| Problem | Evidence |
|---|---|
| Enter does not send | No keyboard handler in the panel |
| Live "thinking" steps never arrive | Published to room `erp_ai_chat:<id>`, which Frappe's socket server never joins (verified in `realtime/handlers.js`). Steps appear only when the answer returns |
| Opens in the wrong language | `detectLang()` falls back to Arabic for English users |
| The empty state lists abilities instead of offering actions | Six sentences; clicking one only fills the box |
| Crowded header | Four text buttons and three tabs |
| A floating box covers Desk | 448×684 at top 212px, z-index 1200, which is above Frappe dialogs |
| Choices are typed numbers; results are prose; no follow-ups, no feedback, no record context | Fixes 6, 7, 9, 11, 14 |
| The card is built from a text summary | No structured data to draw a proper card or its states |
| Fragile code shape | One 1,600-line file; the root is rebuilt on every render (draft text and scroll are lost); 1-second route polling; a whole-document DOM watcher |

## 3. Decisions (reviewers' recommendations; confirm or change)

| # | Decision | Recommendation | Reviewers |
|---|---|---|---|
| D1 | Checkbox on cards | **Only** for submit, cancel, delete, imports and changes to a submitted document. Its text names the consequence or the value checked, e.g. "I understand this invoice can't be edited after submitting / أفهم أنه لا يمكن تعديل الفاتورة بعد اعتمادها". Create and update approve with one button named for the action. Amend SRS FR5 | All four agree |
| D2 | Panel placement | **Docked side panel.** Push the page aside at ≥1280px so Desk's Save/Submit and the record stay visible; overlay below that; full screen at ≤640px. Remember the width | UX, product, frontend |
| D3 | Arabic font | **Keep Cairo for the first release** (one less change; the research also says to keep it). Self-host it (today's Google Fonts `@import` is a privacy and offline problem), line-height 1.7, at least 14px. Try IBM Plex Sans Arabic later with real users | Split: product vs UX; this is the lower-risk choice |

## 4. Design

### Concept
Quiet and native to Desk everywhere except **one** place: the approval card, drawn like a paper document. It has a header (type, number, party), ledger lines for what changes, item lines with a total, and a stamp area that shows the outcome. The design name "voucher" is internal only; users never see it, because سند means Journal or Payment Entry in ERPNext.

### Tokens
| Token | Hex | Role | Contrast on Paper |
|---|---|---|---|
| Ink | `#18222D` | Body text, icons | 15.5 |
| Carbon | `#5D6873` | Secondary text, the based-on line | 5.48 |
| Paper | `#FAFBFA` | Panel background | — |
| Rule | `#DCE2E6` | Dividers and table rules only (decorative) | 1.26 (not for controls) |
| Border | `#8A949C` | Outlines of inputs, chips, starters, the checkbox | ≥ 3:1 |
| Ledger | `#0F6B5C` | Primary action, focus ring, links (underlined), Saved stamp | 6.18 |
| Seal | `#B42318` | Destructive actions, errors | 6.34 |

Rejected and expired cards use a grey background, not opacity, so text keeps its contrast. Dark mode maps the same names under `[data-theme="dark"]`; its values are computed and checked in phase 1.

### Type
- **Arabic:** Cairo, self-hosted and subset with `unicode-range`. 14px minimum, line-height 1.7, no letter-spacing.
- **Latin:** the Desk font stack. Body 14px, line-height 1.45.
- Sentence case everywhere; no all-caps labels.
- **Numbers:** Western digits, from the user's Frappe number format, never mixed in one answer. Tabular figures. An amount and its currency go together in one `<bdi dir="ltr">`.
- **Record IDs:** shown in full, never shortened, wrapped in `<bdi>`.

### Layout
```
Desk ≥1280px: page pushed aside           Desk <1280px: overlay      ≤640px: full screen
┌──────────────────────┬─────────────┐
│ Sales Invoice …0012  │ Assistant ⟳⋯✕│   header: title, New chat (text), History, menu (expand, language, memory), Close
│ [Save] [Submit]      │ On this invoice │   context chip on a form (fix 9)
│                      │ ─────────────│
│  (form stays usable) │ messages      │
│                      │ composer      │
└──────────────────────┴─────────────┘
```
Header buttons are at least 32px, with visible tooltips; New chat has a text label. The panel is a non-modal `role="complementary"` region (a dialog with trapped focus only at ≤640px). z-index about 1015, under Frappe dialogs. The conversation survives Desk route changes.

**Empty state:** "مرحبًا، <bdi>عمر</bdi>" and one line of scope, then 3–4 starters that the user's roles can actually run today. Clicking one sends it.

| Role | Starters (MVP) |
|---|---|
| Accounts | Overdue invoices · Draft invoices · Payments this month |
| Sales | My open quotations · New quotation · Sales orders to deliver |
| Projects / others | My tasks · Overdue tasks |

"Who owes us money?" waits for fix 10; "Send reminders" is cut until emails have their own card.

**Answer anatomy:**
```
                      how many overdue invoices?  ◖          user bubble at inline-start
✓ 2 steps · 0.5 s ▸                                          status: role=status, expands to the real steps
You can see 4 overdue sales invoices.                        answer text (DOM nodes, not innerHTML)
 ACC-SINV-2026-00012   شركة الرواد        ر.س 12,300.00       up to 6 rows; at <400px each row stacks
 ACC-SINV-2026-00011   متجر الورد          ر.س 2,550.00
Based on Sales Invoice · status Overdue · 4 records  Open list   server-built route, same filters (fixes 6/15)
[ Export to Excel ] [ Chart by customer ] [ Only this month ]     2–3 chips, newest answer only (fix 11)
⧉ 👍 👎                                                       visible on focus and touch, not only on hover (fix 14)
```
Clarifying questions show buttons ("Project tasks or your to-dos?"), with no numbers to type and no DocType words (fix 7). No auto-scroll while text arrives; "Still working…" after 10 s, with a Stop button.

### Cards (one per action type; at most one live card per chat)
| Type | Body | Primary button | Checkbox |
|---|---|---|---|
| Create | Party, item lines (qty × item @ rate), total from the server, "Filled for you: Company Majal · Currency SAR · Price list Standard Selling", status "Not saved yet / لم يُحفظ بعد" | "Create quotation" | No |
| Update | Record line + Field \| Current \| New | "Save changes" | Only if the document is submitted |
| Submit | Record line, amount, impact: "After submitting, it can only be cancelled" | "Submit invoice" | Yes, naming the consequence |
| Cancel | Record line, impact: "Cancelling keeps a record and reverses its entries" | "Cancel invoice" (Seal) | Yes |
| Delete | Record line, impact: "This can't be undone" | "Delete to-do" (Seal) | Yes |
| Import | Rows, columns mapped, warnings | "Start import" | Yes |

The secondary button is always "Reject / رفض", never "Cancel".

| State | Shows | Focus goes to |
|---|---|---|
| Pending | As above | Card heading |
| Saving | Buttons disabled, progress line | — |
| Saved | Stamp "Saved as draft · SAL-QTN-2026-00007" (or "Submitted", "Deleted"), "Open quotation" | "Open …" |
| Failed | Reason in plain words, "Try again", "Open form" | "Try again" |
| Rejected | "Rejected. Nothing was saved." (grey) | Composer |
| Expired | "This record changed after the card was made" or "This card is a day old", "Prepare again" | Composer |
| Replaced | "A newer card replaced this one" | — |

State changes are announced in a polite live region. The card's text is rebuilt on the server from the payload; the stored summary is not trusted.

### Principles
1. One bold place (the card); everything else is quiet and Desk-like.
2. Every number is checkable: "Based on … Open list".
3. Click, don't type: starters, choices and follow-ups are buttons that send text through the normal chat (never an action or a card id).
4. Plain words in the user's language; a button's verb matches its result ("Create quotation" → "Quotation created").
5. RTL is native: logical CSS properties only, mirror only icons that point (send, disclosure, expand), never mirror numbers, isolate every value.

## 5. Server contract (built before the UI that uses it)

| Change | For | Notes |
|---|---|---|
| `request_id` from the client; steps published to `user=` with `request_id` in the payload | Live status line | Fixes the dead realtime room |
| `cancel_run(request_id)` (POST): a cache flag checked between model and tool steps | Stop button | |
| `lang` passed to `run()`; `bootstrap()` returns `frappe.boot.lang` | Correct language | |
| `pending_card`: {action, destructive, doctype_label, name, party, lines: [{label, current, new}], items, total, currency, filled, impact, needs_checkbox, checkbox_text} | Card | Built by `services/writes.py` from the payload |
| Approve and reject return `{status, reason}`; card states `replaced` and `expired` | Card states | Expired is already done (S3) |
| `based_on`: {label, filters_text, total, route[], route_options} | Based-on line | Route built by the server and URL-encoded; `/app` or `/desk` from `desk_compat` |
| `rows` + `columns` (≤ 6) | Inline table | Only fields readable at the user's permlevel |
| `choices` and `suggestions`: [{label, send}] | Buttons | Server templates; `send` capped at 200 characters |
| `bootstrap().starters` | Empty state | From roles and readable DocTypes |
| `context`: {doctype, name, title, status} | Context chip | From `cur_frm` in the browser, checked with `has_permission(dt, "read", doc=name)` on the server; "this record" still goes through `resolve_write_target` |
| "My" filter (owner or assignee) | "My open quotations" | Part of fix 6 |
| Multiple matches listed for submit/cancel ("the draft quotation" with 2 drafts) | Safety | Must ship before "Submit this" |
| `rate_message` (POST, owner-checked, rating enum, reason ≤ 500, rate-limited, System Manager-only storage) | 👍/👎 | |
| `get_chat_messages` returns stored structured parts (cards with server-computed state, tables, charts) | Reopening history | |

## 6. Phases

| # | Phase | Scope | Done when |
|---|---|---|---|
| 0 | Foundations | Realtime fix + `request_id`; split the bundle into ordered files sharing `window.erpAi` (`core`, `desk_compat`, `render` (DOM-based markdown), `charts`, `card`, `panel`); all CSS scoped to `#erp-ai-root` with resets for Desk elements; one version string from `app_version`; `frappe.router.on("change")` instead of polling; no full re-render | Same look as today, live steps arrive, existing tests pass, no `innerHTML` for model or record text |
| 1 | Shell | Tokens, self-hosted Cairo, docked panel (push or overlay), header, composer (Enter / Shift+Enter, IME-safe), language from the user, Stop, focus and Esc, a11y roles | Screenshots EN/AR at 1440/1280/375; axe (scoped to the panel) has no serious issues; keyboard-only send, stop and close |
| 2 | Server contract | Everything in section 5 except feedback | Unit tests for each field; the 4 recorded scenarios return the new fields |
| 3 | Answers | Status line, inline table, based-on and Open list, choice buttons, follow-up chips, copy | The scenarios render as in the wireframe, in EN and AR |
| 4 | Cards | All 6 card types and 7 states, D1 checkbox rules, focus moves | Approve, reject, failed, expired and replaced pass in Playwright, as `sales@` and `accounts@` |
| 5 | Start and context | Role starters; context chip with Summarize and "Submit this" (needs the multiple-match listing) | Each demo user sees their own starters; on an invoice form, "Submit this" makes a card for that invoice |
| 6 | Feedback | 👍/👎 with optional reasons | A rating is stored, and readable only by System Manager |

**After each phase:**
- screenshots before and after
- the `code-review` skill on the diff
- update `docs/USABILITY_FIXES.md`
- the full suite on the dev site
- port to `version-15` through `desk_compat.js`, and commit both when you say "commit"

Playwright scenarios run against a stub model so screenshots are repeatable; a short live run with the real model happens at the end of each phase.

**Release 2 (not in this plan's build):**
- make sales order from quotation (fix 12, highest value for sales)
- report questions (fix 10) and the "Who owes us?" starter
- more follow-ups (11), how-to for the current screen (13)
- 640px expand, dark-mode polish, the feedback report, IBM Plex Sans Arabic trial

### Progress

| Phase | Status | Notes |
|---|---|---|
| 0. Foundations | ✅ Done, 2026-10-28 | See below |
| 1–6 | Not started | |

**Phase 0 result:**
- **Live steps:** `publish_step` (`services/tools/registry.py`) now sends to the asking user's own room, with `chat_id` and a `request_id`. `api.chat.run` accepts `request_id`. The panel keeps only steps for the message it is waiting on.
- **Files:** the 1,630-line `erpnext_ai_assistant.bundle.js` is replaced by six ordered files in `public/js/assistant/` sharing `window.erpAi`: `core` (state, text, calls, version), `desk_compat` (v15/v16 paths and links), `render`, `charts`, `card`, `panel`. The code was moved by a script at function boundaries; a static check confirmed every cross-file call is imported or called at run time. `crm_include.js` loads the same six files in order (`async = false`).
- **Rendering:**
  - `render.js` builds answers as DOM nodes (paragraphs, headings, nested lists, tables, code, links to this site only); no model or record text goes through `innerHTML`
  - `el()` now sets text, never HTML
  - `test_security.test_answers_are_built_as_text_nodes` guards both
- **No full rebuilds:** the conversation lives in one log element that survives shell rebuilds. Switching language, attaching a file or changing tabs used to erase the conversation on screen; now the messages, the draft text and the scroll position are kept. The starter list follows the language.
- **Bug found and fixed:** every finished steps list kept the id `erp-ai-thinking-live`, so live steps for a second question updated the first answer's list. Only the in-progress list carries it now.
- **Version:** `hooks.py` computes one version from the files' contents (`ASSET_VERSION`) for all six scripts and the stylesheet; `core.js` reads it from its own URL. The hand-bumped `ai25` strings are gone.
- **CSS:** all 86 rules are scoped to `#erp-ai-root` / `#erp-ai-fab`. Desk resets come with the tokens in phase 1, so the look stays identical.
- **Desk hooks:** route changes come from `frappe.router.on("change")` with one bootstrap per route, instead of a 1-second poll. The DOM watcher looks at body's children only.
- **Dev stack:** live steps also needed the socket wired. `DEV_SERVER=1` on the web service (Desk then connects to port 9000), and `webserver_host=web`, `webserver_port=8000` so the socket server can check the session (`erpnext-dev/compose.yaml`).
- **Checked in the browser** (Playwright, `accounts@demo.test`):
  - live steps arrived while waiting (2, then 4)
  - after a language switch: 2 messages before and after, and the draft kept
  - a table answer rendered
  - no console errors
- **Tests:** 82 ran; only T08 and T21 fail, as before.
- **Code review** (the `code-review` skill, medium effort) found 10 issues; all are fixed:
  1. The boot guard was lost in the split, so the panel could start twice. It is restored, every file now runs once, and `crm_include.js` skips loading when Desk has already loaded the panel.
  2. A second Send while an answer was running mixed the two requests' steps. Now one request at a time.
  3. A late reply after "New chat" or opening a history chat landed in the wrong chat. It is now dropped (`forgetRequest`).
  4. Cached bootstrap per route never refreshed, so blocking or persona changes were missed. Entries expire after 60 s.
  5. The asset version lags if Redis keeps old hooks. Documented in `hooks.py`: `bench migrate` or `clear-cache` after updating.
  6. `crm_include.js` without `?v=` re-downloaded everything on every page. It now falls back to the date (one download a day).
  7. Bold and italic could not contain links or code. They now render their contents with the same rules.
  8. The launcher never hid (CSS display beat `[hidden]`; this was already broken before phase 0). Fixed with `#erp-ai-fab[hidden]`.
  9. Remounts added more watchers and handlers, and a removed launcher never came back. Watchers attach once, and each missing part is re-created.
  10. Any `/desk/<page>` overlay pattern matched every Desk page (also older than phase 0). Only `/desk` itself covers all of Desk now.
  - Cleanups: 12 unused imports removed from `panel.js`; the HTML test now allows only `innerHTML = ""` and the two fixed icons.
  - Browser re-check: the launcher hides while the panel is open, and a busy second Send is ignored; all earlier checks still pass with no console errors. Suite: 82 tests; only T08 and T21 fail, as before.
- **Seen for phase 1:** an English answer that mentions Arabic names gets `dir="rtl"` as a whole, so "(overdue)." moves and table columns reverse. Per-element direction and `<bdi>` will fix this.

## 7. Success measures (tracked after release, split by language and role)
- Task success: an answer or a saved document within 2 turns.
- Wrong-write proxy: documents created by the assistant that are edited, cancelled or deleted within 24 h. Target close to 0.
- Card outcomes: approve, reject, expire and replace rates; median time to approve (under 2 s on submit cards suggests users are not reading).
- Use: starter and chip clicks; "Open list" clicks after counts.
- Quality: thumbs-down rate and reasons; "Checked:" mismatch lines; how often the clarify question is shown.
- Speed: p50/p90 latency.

## 8. Review (four agents, 2026-10-28)

Reviewers: UX, accessibility and RTL; senior frontend (Frappe Desk); product and end users; security. Their main findings follow. The plan will be revised against them before building.

### Agreed by several reviewers
- **Checkbox:** option (b), with FR5 in the SRS amended. Keep the box for submit, cancel, delete, imports and changes to submitted documents. Its text names the consequence or the checked value, e.g. "I understand this invoice can't be edited after submitting". Never use "I checked these details". The server cannot tell whether the box was ticked, so real safety comes from the server-built card, a button named for the action, and the stale check (now done).
- **Docked panel:** yes, but **push the page aside at ≥1280px** so Desk's Save/Submit buttons and the record stay visible; overlay only below that. Remember the width. Use z-index about 1015, under Frappe dialogs.
- **Wording:**
  - The card must not say "Draft" before saving (in ERPNext a draft is already saved); use "Not saved yet / لم يُحفظ بعد".
  - The stamp says "Saved as draft · SAL-QTN-…", and "Submitted / تم الاعتماد" only for real submits.
  - Never label a card button "Cancel"; that word means ERPNext's document Cancel. Keep "Reject / رفض".
  - Users never see the word "voucher" (سند means Journal or Payment Entry).
- **Draw every card type:** create, update (Field | Current | New), submit and cancel (with an impact line), delete. Add a "Replaced" state when a newer card arrives, and allow only one live card.
- **An Arabic copy table**, reviewed by a native speaker, before building.

### UX, accessibility, RTL
- **Contrast:** Rule on Paper is 1.26:1, so add a Border token (about `#8A949C`) for interactive outlines. No opacity on text in the Rejected state. Underline links.
- **Screen readers:**
  - the panel is `role="complementary"` with a label, not a modal
  - the status line is `role="status"` (throttled), and "Answer ready" is announced once
  - the card is `role="group"`, and its state changes go to a polite live region
- **Focus rules:**
  - when a card appears, focus moves to its heading
  - after Saved, focus moves to "Open quotation"
  - after Reject or Expired, focus returns to the composer
  - Esc returns focus to the launcher
- **Arabic type:** line-height 1.7, at least 14px, no letter-spacing. Western digits, never mixed. Amount and currency go in one `<bdi dir="ltr">`. Never shorten record IDs.
- **Accessibility floor:**
  - targets of 32px or more
  - copy and feedback buttons visible on focus and touch, not on hover only
  - at 320px, table rows stack
  - reduced motion turns off the slide, the stamp animation and the shimmer
  - no auto-scroll while an answer streams
  - "Still working…" after 10 s

### Frontend (Frappe)
- **Blockers:**
  - the thinking channel never reaches the browser (custom room); publish to `user=` with a `request_id`
  - Stop needs `cancel_run(request_id)` with a cache flag checked between steps
  - the card needs a structured `pending_card` from the server
  - approval must return structured `{status, reason}`
  - assistant text should be built as DOM nodes, not `innerHTML` (it is already escaped today)
- **Structure:**
  - split the bundle into ordered plain files sharing `window.erpAi` (core, desk_compat, markdown, charts, card, panel)
  - put every v15/v16 difference in `desk_compat.js`
  - prefix all CSS with `#erp-ai-root` and reset Desk element styles; no Shadow DOM
  - one version string derived from `app_version`
- **Composer:** Enter sends unless Shift or IME composition is active (`isComposing`, keyCode 229, Safari `compositionend`). Language comes from `frappe.boot.lang` and is passed to `run()`.
- **Performance:** use `frappe.router.on("change")` instead of 1-second polling. Narrow the DOM watcher. Don't rebuild the root on every render, which loses the draft and the scroll position.
- **Phase order:**
  0. Realtime fix, module split, DOM rendering, single version
  1. Shell
  2. Server contract
  3. Answers
  4. Card
  5. Context and starters
  6. Feedback
  - Port to v15 in every phase.

### Product (personas)
- **MVP:**
  - phases 1–3
  - choice buttons (7)
  - inline table, "my" filter, based-on line, Open list (6)
  - starters that already work (8)
  - context chip with Summarize and Submit this (9)
  - thumbs without a report
- **Release 2:**
  - make sales order from quotation (12) first
  - report questions (10), and only then the "Who owes us?" starter
  - more follow-up chips (11) and how-to (13)
  - chart chip, 640px expand, dark mode, feedback report
- **Cut:** "Send reminders" until emails have their own card.
- **Before "submit this" ships:** listing several matching drafts (the fix 2 limit) must be done.
- **Success metrics:**
  - task success within 2 turns
  - documents created by the assistant then edited or cancelled within 24 h (a proxy for wrong writes)
  - approve, reject, expire and replace rates, and time to approve
  - starter and chip click rates
  - thumbs-down reasons, and "Checked:" mismatch lines
  - p50/p90 latency

### Security
- **Done now (S1–S7):** forged cards blocked; POST-only endpoints; stale and 24 h expiry; requester-only approval; per-record permission, denied-DocType and update re-checks; plain errors; same-site links only.
- **For the redesign:**
  - chips and starters only send text through `run()` (never an action or a card id), built from server templates, capped in length, labels set with `textContent`
  - `based_on.route` is built by the server and URL-encoded, and passes `safeLocalPath`, which must also allow `/app/` for v15
  - inline rows include only fields the user may read at their permlevel
  - the context chip calls `has_permission(dt, "read", doc=name)` and shows only the title and status; "this record" still goes through `resolve_write_target`
  - `rate_message` is POST-only, owner-checked, an enum rating with a reason of at most 500 characters, rate-limited, and readable only by System Manager
  - `get_chat_messages` returns the card state computed on the server

### Open decision still split
- **Arabic font:** UX recommends IBM Plex Sans Arabic (self-hosted, subset, line-height 1.7). Product recommends keeping Cairo for the MVP and testing Plex later. Your call.
