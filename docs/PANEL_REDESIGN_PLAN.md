# Assistant panel redesign plan

Status: **reviewed, revision pending**, 2026-10-28. Nothing is built yet. Security blockers from the review are fixed (see `docs/USABILITY_FIXES.md`, S1–S7).

## 1. Brief

- **Subject:** an assistant that lives inside ERPNext Desk. It answers questions about business records and prepares documents (quotations, orders, invoices, tasks) that are saved only after a person approves them.
- **Audience:** non-technical staff in sales, accounts and the back office, often Arabic-first. They know their documents ("the overdue invoices", "a quotation for Delta"), not DocTypes or field names. They use the panel in short bursts while doing other work in Desk.
- **Primary job:** get a correct, checkable answer or a ready-to-approve document in one or two turns, without leaving the page they are on.
- **Constraints:**
  - vanilla JS and CSS in this app only; no framework, no host-app rebuild (SRS NFR2)
  - all record text is rendered as text, never HTML (NFR3)
  - Arabic (RTL) and English must both be first-class
  - it must work on Frappe v16 (`/desk`) and v15 (`/app`)
  - the approval step stays: nothing is written before the user approves (FR5)

## 2. What is wrong today (from screenshots and testing)

| Problem | Evidence |
|---|---|
| Enter does not send | The panel has no keyboard handler; the question stays in the box until the send button is clicked |
| The empty state is a capability list, not actions | Six sentences like "عدّ أو اعرض السجلات التي تستطيع قراءتها"; clicking one only fills the box |
| Crowded header | Close, expand, New and language as four text buttons, plus Chat / History / Memory tabs |
| A floating box covers Desk content | Fixed at top 212px, left 24px, 448×684; it overlaps the page the user is working on |
| Wrong language on open | An English user got the Arabic panel |
| Choices are typed numbers | "1. Count 2. Show 3. Create … reply with a number" (fix 7) |
| Results are prose | Lists and counts are text; no "based on" line, no link to the filtered list (fix 6) |
| No follow-ups or feedback | Nothing to click after an answer (fix 11); no 👍/👎 (fix 14) |
| The panel ignores the open record | No "this invoice" (fix 9) |
| "Work only" in the placeholder | Reads like a warning, not help |

## 3. Skills, tools and checks used

| Need | What we use |
|---|---|
| Visual direction, type, copy | `frontend-design` skill (installed in `~/.claude/skills/frontend-design`) |
| Charts in answers (palette, marks, accessible table fallback) | `dataviz` skill (already available) |
| Driving the real app and screenshots | Playwright script against the dev stack (`erpnext-dev`, http://localhost:8000), in EN and AR, as the three demo users |
| Accessibility | axe-core run inside Playwright; keyboard-only pass; reduced-motion pass; 200% zoom; 375px width |
| Code review of the diff | `code-review` skill after each phase |
| Frappe knowledge | Desk include hooks, `frappe.set_route`, realtime events, v15/v16 route differences |

No new skill install is required beyond `frontend-design`. `dataviz` and `code-review` are already available.

## 4. Design direction

### Concept: "the voucher"

ERP work is documents: quotations, invoices, vouchers, signed and stamped. The panel stays quiet and native to Desk everywhere except **one** place, the approval card. That card is drawn like a paper voucher:
- a document header (type, number, party)
- ledger lines for what changes (field, before → after)
- item lines with a total
- a stamp area that turns into an "Approved" or "Saved" stamp when the action succeeds

That is the memorable element, and it is also the moment that matters most for safety. Everything else (messages, chips, header) is calm and dense like Desk itself.

### Tokens

| Token | Hex | Role |
|---|---|---|
| Ink | `#18222D` | Body text, icons |
| Carbon | `#5D6873` | Secondary text, timestamps, the "based on" line |
| Paper | `#FAFBFA` | Panel background (cool, not cream) |
| Rule | `#DCE2E6` | Dividers, table rules, voucher ledger lines |
| Ledger | `#0F6B5C` | Primary action, focus ring, approval stamp, links |
| Seal | `#B42318` | Destructive actions (delete, cancel), errors |
| Voucher | `#FFFFFF` with a `Rule` border and a perforated top edge | Approval card surface |

Contrast target: AA for all text. Ledger on Paper and Ink on Paper both pass. Dark mode follows Desk's theme attribute when present, with the same names remapped.

### Type

- **Arabic:** IBM Plex Sans Arabic (OFL), self-hosted woff2 in `public/fonts`, weights 400/500/600. It is designed for business UI, has clear numerals, and pairs with the Latin face.
- **Latin:** the Desk UI font (`var(--font-stack)`, Inter on v16), so English text sits natively in Desk.
- **Numbers and record IDs** keep tabular figures (`font-variant-numeric: tabular-nums`) and are wrapped in `<bdi>` so `ACC-SINV-2026-00012` and `12,300.00` never flip in RTL.
- **Scale:** 13 / 14 (body) / 16 (titles) / 20 (empty-state greeting). Line height 1.55 for Arabic, 1.45 for Latin. Sentence case everywhere; no all-caps labels.

### Layout

A docked side sheet on the inline-end edge of Desk (right in English, left in Arabic). It is full height below the Desk navbar and 420px wide, with an "expand" to 640px. At narrow widths (≤ 640px) it becomes full screen. It overlays Desk with a soft edge shadow and does not reflow the page. Esc closes it and focus returns to the launcher.

```
┌──────────────────────────── 420px ─┐
│ Assistant              ⟲  ☰  ⤢  ✕ │  header: title; new chat, history, expand, close (icons + labels for screen readers)
│ On: Sales Invoice ACC-SINV-…0012 ✕ │  context chip, only on a form (fix 9)
├────────────────────────────────────┤
│                                    │
│  Good morning, Omar                │  empty state: greeting + one line of scope
│  Ask about your records, or have   │
│  me prepare a document for you to  │
│  approve.                          │
│                                    │
│  [ Overdue invoices            ]   │  4 starters from the user's roles (fix 8);
│  [ Who owes us money?          ]   │  clicking one sends it
│  [ Payments this week          ]   │
│  [ New quotation               ]   │
│                                    │
├────────────────────────────────────┤
│ ┌────────────────────────────────┐ │
│ │ Ask or describe a document…    │ │  composer: Enter sends, Shift+Enter new line
│ └────────────────────────────────┘ │
│  📎                          [ ➤ ] │
│  Changes are saved only after you  │
│  approve them.                     │
└────────────────────────────────────┘
```

**Answer anatomy:** assistant answers are not bubbles. They use the full width with readable type; the user's messages are compact bubbles at the inline-start.

```
                     how many overdue invoices?  ◖   user bubble
✓ 2 steps · 0.5 s                          ▸        collapsed status (expandable to the real steps)
You can see 4 overdue sales invoices.               answer text
┌──────────────────────────────────────────────┐
│ ACC-SINV-2026-00012  شركة الرواد   12,300.00  │  up to 6 rows inline, no horizontal scroll
│ ACC-SINV-2026-00011  متجر الورد     2,550.00  │
│ …                                             │
└──────────────────────────────────────────────┘
Based on Sales Invoice · status Overdue · 4 records   Open list   (fix 6/15: links to the same filters in Desk)
[ Chart by customer ] [ Export to Excel ] [ Send reminders ]   follow-ups, newest answer only (fix 11)
⧉  👍  👎                                            copy, feedback (fix 14)
```

**Clarifying question (fix 7):** "Project tasks or your to-dos?" with two buttons. No numbers to type, and no DocType words.

**Voucher card states:**

```
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐   perforated top edge
  New quotation                 Draft
  Customer   Delta Systems
  ─────────────────────────────────────
  2 × Laptop            3,500.00
  1 × Office Printer      900.00
  ─────────────────────────────────────
  Total              ر.س 7,900.00
  Filled for you: Majal, SAR, Standard Selling
  ☐ I checked these details
  [ Reject ]          [ Create quotation ]
└───────────────────────────────────────┘
```

| State | What the card shows |
|---|---|
| Pending | The voucher above. The primary button names the action ("Create quotation", "Submit invoice", "Delete to-do" in Seal red) |
| Saving | Both buttons disabled with a progress line |
| Saved | The stamp "Saved · SAL-QTN-2026-00007" with "Open quotation" |
| Failed | The reason in plain words, and "Try again" |
| Rejected | "Rejected. Nothing was saved." The card is dimmed |
| Expired | "This card is out of date. Ask again to prepare a new one." Shown when the record changed after the card was made (see the architecture review) |

### Principles

1. **One bold place.** The voucher is distinctive; the rest stays quiet and Desk-like.
2. **Every number is checkable.** It is shown next to "Based on…" and a link to the same list in Desk.
3. **Click, don't type.** Choices, follow-ups and starters are buttons; typing is for new questions.
4. **Plain words.** The user's terms, never DocType or field names. The verb on a button matches the result ("Create quotation" → "Quotation created").
5. **RTL is native.** Use CSS logical properties only, mirror icons that point, never mirror numbers, and isolate every value with `<bdi>`.

### Review against generic defaults (frontend-design pass 2)

| Draft choice | Generic? | Revision |
|---|---|---|
| Navy header bar with a white title (current) | Yes, a common SaaS chat look | Header is Paper with an Ink title; color is reserved for the action color and the voucher |
| Rounded cards for every block | Yes ("SaaS-card kit") | Only the voucher is a card; results are a ruled table; starters are plain outlined rows |
| Gradient avatar or sparkle icon for the assistant | Yes | No avatar and no sparkles; answers are distinguished by layout, not decoration |
| Middle-dot meta strings ("2 steps · 0.5 s") | Flagged by the skill as a tell | Kept only where it is real metadata (status line, based-on line); not used as decoration elsewhere |
| Cairo font (current) | The default Arabic web font | IBM Plex Sans Arabic for a business, document-like voice that matches tabular numbers |

## 5. Server changes the design needs

| Field or endpoint | Used by | Fix |
|---|---|---|
| `choices: [{label, send}]` on clarify replies | Choice buttons | 7 |
| `suggestions: [{label, send}]` after counts, lists and charts | Follow-up chips | 11 |
| `based_on: {doctype_label, filters_text, total, route}` | "Based on … Open list" | 6, 15 |
| `rows: [...]` (top 6) + `columns` for list answers | Inline table | 6 |
| `bootstrap().starters` from roles and readable DocTypes | Empty state | 8 |
| `route` with doctype/name → permission-checked context | Context chip, "this invoice" | 9 |
| `rate_message(message_id, rating, reason)` + ERP AI Message fields | 👍/👎 | 14 |
| Card `modified` snapshot + `expired` state at approval | Expired voucher | review rec. |
| `user_lang` from the Desk user | Opening in the user's language | — |

Fixes 10 (report questions), 12 (document actions like "make sales order from quotation") and 13 (how-to for the current screen) are server features. They plug into the same answer anatomy (table + based-on + follow-ups) and into the voucher (for 12).

## 6. Phases

| Phase | Scope | Done when |
|---|---|---|
| 1. Shell | Tokens, fonts, docked sheet, header icons, composer (Enter/Shift+Enter, IME-safe, stop button), language from the user, focus and Esc | Screenshots EN/AR at 1440 and 375; axe has no serious issues; keyboard-only send and close work |
| 2. Answers | Status line, answer text, inline table, based-on line, follow-up chips, choice buttons, copy | The 4 recorded scenarios render as in the wireframe in EN and AR |
| 3. Voucher | Card layout and all 6 states; action-named button; Seal for destructive | Approve, reject, failure and expired flows pass in Playwright |
| 4. Start and context | Role starters; form context chip; "this record" | Accounts, sales and viewer users each see their own starters; on an invoice form, "submit this" makes a card for that invoice |
| 5. Feedback | 👍/👎 with optional reason; report | A rating is stored and visible to the System Manager |
| 6. QA | Visual review against this plan, `code-review` skill, v15 port | Both branches committed after "commit" |

Each phase updates `docs/USABILITY_FIXES.md`. Before/after screenshots go in the change log.

## 7. Decisions needed from you

1. **Checkbox on the voucher.** The SRS (FR5) says "the user must check the box". The research suggests a checkbox is only useful when it says something specific. Options:
   - (a) keep it on every card
   - (b) keep it only for submit, cancel, delete and imports; the action-named button alone confirms create and update
2. **Docked side sheet vs floating box.** The plan docks it (it no longer covers Desk content). Some teams prefer the floating box.
3. **Arabic font.** IBM Plex Sans Arabic (proposed, self-hosted) vs keeping Cairo.

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
