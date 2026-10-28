# Chat Panel Design Research

Date: 2026-10-28. Scope: the floating ERPNext Desk assistant panel (AR/EN, RTL-first, read answers plus approval-gated changes).

**How to read this note.** Sources are marked as follows:
- **[Official]** means a design system or product documentation page that I fetched and read.
- **[Official, snippet only]** means an official page I could not fetch (HTTP 403 or 404). I only saw search-result excerpts of it.
- **[Vendor claim]** means marketing or blog copy written by the vendor.
- **[Secondary]** means third-party writeups or bug reports.

I could not open the SAP Fiori AI pages (all returned 403) or a Fluent 2 "AI/Copilot" page (404). I found no public, current SLDS page for Agentforce panel specs. Treat anything attributed to those three as indirect.

The current panel was read for orientation only. The relevant code is `renderCheatSheet`, `thinkingBlock`, `renderAck` and the charts in `public/js/erpnext_ai_assistant.bundle.js`.

---

## 1. Key takeaways

1. **Keep the chat as the main surface. Cards inside it should be small.** Microsoft's Copilot guidance gives these rules:
   - Inline cards stay "concise and ideally fit within a single scroll."
   - A card has at most **two actions**, placed at the bottom.
   - A card has no tabs and no internal scrolling.
   - Anything heavier moves to a wider "side-by-side" view.

   Our panel is 448 px wide, so this rule matters even more for us.
2. **Every state must be shown by the UI itself, not by model text.** Microsoft: "Never rely on model text alone to communicate system status." The states are loading, disabled, success, and error with a way to recover. This applies to the approval card's lifecycle.
3. **Human-in-the-loop is the industry norm for writes.** Sources:
   - Microsoft 365 Copilot confirms every non-GET operation and shows the data that will be sent.
   - VS Code shows the tool name and its inputs before it runs anything.
   - SAP states it keeps "humans in the loop to carefully review and approve."
   - OpenAI asks before "high-impact actions."

   The common thread is that people see exactly what will change before they approve. A generic "are you sure?" is not enough.
4. **Do not show a blank box.** An empty input with no guidance puts people off. The fix is a short welcome that says what the assistant can do, plus 3–4 clickable starter prompts that fit the current page (NN/g 2026, Salesforce 2025, Dynamics 365, Odoo 19). We already have a cheat sheet. It should send the prompt, not just copy example text into the input.
5. **Suggested follow-ups should keep coming throughout the conversation, not only at the start** (NN/g, Intercom, shape.of.ai "Suggestions"). For data questions the natural follow-ups are next steps on the same data, such as "Export to Excel", "Show as chart", or "Only this month".
6. **Show "based on these records", but do not oversell it.** HubSpot uses numbered `[#]` markers that link to records, plus a "Sources" list under each answer. NN/g (Dec 2025) warns that people rarely click citations and that a citation makes an answer look more reliable than it is. For us the honest version is better: show the real query scope (DocType, filters, count) and links to the actual records.
7. **Thinking displays are trust theatre unless they show real steps.** NN/g says step-by-step reasoning is often "rationalizations generated after the fact." Our "thinking steps" are real tool calls, such as "Counted Sales Invoice where status = Unpaid". Those are worth showing, but collapsed by default and written in plain language. Do not stream model prose.
8. **The AI disclosure should be short, visible, and tied to an action.** Examples:
   - Salesforce: "I may make mistakes, so review my responses for accuracy," placed in the welcome or under the input. "Don't bury it."
   - NN/g: put the disclaimer near the input, in plain words, with a concrete action.
   - SAP: an "AI notice" is required where decisions carry high impact.
9. **Do not auto-scroll a streaming answer to the bottom.** Keep the start of the new answer in view. NN/g lists this among its 10 guidelines, along with letting users resize the window and save or share answers. We already have expand and Excel export. The scroll behaviour needs checking.
10. **RTL needs more than flipping the panel.**
    - Mirror the layout and the icons that point in a direction.
    - Do not mirror numbers.
    - Isolate every mixed-direction run (record names, IDs, amounts) with `dir="auto"` or `<bdi>` (W3C).
    - Keep codes and IDs left-to-right.

---

## 2. Pattern table

| Pattern | Who does it (source) | Why it matters for our users | Recommendation for our panel |
|---|---|---|---|
| Side pane opened from a persistent entry point, stays across pages | Dynamics 365 Sales: Copilot icon on the command bar opens a side pane [Official] https://learn.microsoft.com/en-us/dynamics365/sales/use-sales-copilot ; Odoo 19: AI button top-right in every app, plus Ctrl+K [Official] https://www.odoo.com/documentation/saas-19.4/applications/productivity/ai.html ; NN/g "persist across pages" [Official] https://www.nngroup.com/articles/ai-chatbots-design-guidelines/ | Staff move between Sales Invoice, Customer and Stock screens mid-task | Keep the floating button. Keep the conversation when the Desk route changes. Add a keyboard shortcut. Show the current page context in the header (for example "On: Sales Invoice SINV-0042") |
| Inline vs expanded surface; cards limited to 2 actions, no tabs or internal scroll, 24 px card padding | Microsoft 365 Copilot UX guidelines [Official] https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-mcp-apps-ui-guidelines | 448 px leaves little room. Wide tables and charts get cramped | Inline: summary, small chart, or first ~5 rows. Use "Open full table" or "Expand" (we have an expand toggle) or a link to the ERPNext list view with the same filters for anything bigger |
| Agent header with identity | Microsoft (agent header, icon + name) [Official, URL above]; Salesforce "Name + Agent", name under 10 characters, consistent avatar [Vendor blog] https://www.salesforce.com/blog/ai-agent-design-tips/ | People need to know what they are talking to and how to get out | Header: small icon + short name, AR/EN toggle, New chat, History, Expand, Close. Nothing else. Move Memory and settings into an overflow menu |
| Welcome message + scope + starter prompts | NN/g "explain capabilities up front", "clickable suggested prompts" [Official]; Salesforce "a blank input field is intimidating" [Vendor blog]; Dynamics 365 starter prompts + "View Prompts" prompt guide [Official]; Odoo context-sensitive prompts [Official]; shape.of.ai "Suggestions", "Initial CTA" https://www.shapeof.ai/ | Non-technical users don't know what to ask, or that the assistant can only read what they have permission to see | One line on what it can do, one line on what it can't do / the approval rule, and 3–4 clickable prompts chosen for the current DocType. Clicking a prompt sends it |
| Follow-up suggestion chips after answers | NN/g (keep offering follow-ups) [Official]; Intercom Messenger "streaming responses with sources, citations, and suggested actions" [Vendor claim] https://www.intercom.com/integrations/connectors/messenger ; Dynamics 365 offers a follow-up prompt to search SharePoint when Dataverse has no answer [Official] | Cuts typing, especially in Arabic on mixed keyboards. Teaches what's possible | 2–3 chips under the latest answer only. They come from the result type (count → "List them", list → "Export Excel" / "Chart by status"). Remove them once the user types |
| Citations / sources | HubSpot Breeze: `[#]` hover popover + click to record, "[#] Sources" button under each answer [Official] https://knowledge.hubspot.com/ai/use-breeze-assistant ; Notion AI cites team pages vs web [Official release note] https://www.notion.com/releases/2024-09-25 ; NN/g: place sources next to claims, use descriptive labels, people rarely click [Official] https://www.nngroup.com/articles/explainable-ai/ ; shape.of.ai "Citations", "Footprints" | Accountants need to verify numbers before acting on them | A small "Based on: 37 Sales Invoices · status = Unpaid · this month" line under each data answer. It is expandable to the filter and opens the matching list view. Record names in answers are links (`/app/sales-invoice/SINV-…`) |
| Visible progress / steps | Claude.ai collapsible "Thinking" block above the answer [Secondary] https://claudemaster.net/features/extended-thinking-chat ; SAP AI progress indicator (animated AI icon + label) [Official, snippet only] https://www.sap.com/design-system/fiori-design-ios/v26-1/in-app-ai-design/components/ai-progress-indicators ; shape.of.ai "Stream of Thought"; NN/g caution on reasoning displays [Official] | Queries can take seconds. Silence reads as broken. Too much detail reads as noise | One live status line ("Reading Sales Invoices…") while it runs. Afterwards, collapse to "3 steps · 2.1 s", expandable to plain-language tool steps. Never stream raw model reasoning |
| Confirmation before writes, showing exact payload | Microsoft 365 Copilot: confirm all non-GET operations, "showing the data to be sent", allow/decline, custom localized title/body [Official] https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-confirmation-prompts ; VS Code: review tool name + input parameters, approve once/session [Official] https://code.visualstudio.com/docs/agents/run/approvals ; SAP HITL "review and approve" [Official, snippet only]; OpenAI ChatGPT agent asks before high-impact actions, user can take over [Official] https://help.openai.com/articles/11752874 ; Zendesk copilot actions run after agent approval [Secondary] https://www.eesel.ai/blog/zendesk-ai-copilot-review ; shape.of.ai "Action plan", "Verification" | Wrong writes to invoices or stock are costly and hard to undo | See §3.1. A before→after field diff, record link, the exact verb ("Create", "Update", "Submit"), two buttons. No "always allow" for writes |
| Explicit card states | Microsoft: loading, disabled, success, error with recovery [Official] | People must know whether something was saved | Card states: Pending → Running (spinner, buttons locked) → Done (green, link to record, time) / Failed (reason + Retry) / Cancelled. Show these in the card itself, not just as a new chat message |
| AI disclosure / disclaimer | Salesforce standard line, "Don't bury it" [Vendor blog]; NN/g plain language, near input, paired with action [Official]; SAP mandatory "AI notice" in high-impact UIs [Official, snippet only] https://www.sap.com/design-system/fiori-design-web/v1-136/ui-elements/local-ai-notice/usage | Sets expectations without scaring people | Keep our footer line ("Answers from the business data you can access. Nothing changes until you approve.") under the input. Add "Check totals before you send them to a customer." |
| Feedback (thumbs) | PAIR Guidebook "Feedback + Control": explain what feedback is used for, make it easy to skip [Official] https://pair.withgoogle.com/chapter/People%20+%20AI%20Guidebook%20-%20Feedback%20+%20Control.pdf ; SAP v1.90 AI feedback patterns (confirm/correct) [Secondary, community blog] https://community.sap.com/t5/technology-blog-posts-by-sap/sap-fiori-design-guidelines-version-1-90-now-available/ba-p/13509972 ; Salesforce "a path to give feedback or escalate" [Vendor blog] | Lets admins find wrong answers | Small thumbs up/down + Copy on hover/focus of each finished answer. On thumbs-down, show one optional row of reasons ("Wrong numbers", "Wrong records", "Didn't understand"). Say who sees it |
| Escalation / handoff to a human or the normal UI | Intercom Fin hands off to humans in the same thread [Vendor claim]; Microsoft side-by-side header "handoff option to the full application" [Official]; Salesforce "escalate" [Vendor blog] | When the assistant can't do it, people need a next step | On refusal or failure, offer "Open <DocType> list" / "Open new <DocType> form" buttons rather than only an apology |
| Graceful "can't do" | Odoo: when the agent cannot do something it says so instead of showing an error [Official]; Odoo's default agent cannot change records [Official] | Avoids stack-trace-looking errors | Map server errors to plain sentences + one action (Retry / Open form / Rephrase). Hide `exc_type` names |
| Avoid autoscroll, allow resize, save/share | NN/g guidelines 7–9 [Official] | Long Arabic answers stream in. Users lose their place | Scroll so the start of the new answer is in view, then stop following. Keep Expand. Keep Excel / Copy |
| RTL mirroring + bidi isolation | Material bidirectionality (mirror layout and direction icons, not numbers) [Official] https://m2.material.io/go/design-bidirectionality ; W3C inline bidi markup (`dir="auto"`, `<bdi>` for runtime text) [Official] https://www.w3.org/International/articles/inline-bidi-markup/ ; Cursor/ChatGPT RTL bug reports [Secondary] https://forum.cursor.com/t/arabic-rtl-chat-text-renders-with-broken-bidi-layout-on-windows/162815 | Arabic sentences with English DocType names, invoice IDs and amounts break visually | See §3.7 |

---

## 3. Specific recommendations

### 3.1 Approval card (highest priority)

Model it on Microsoft's confirmation pattern and VS Code's "show the inputs" pattern. Keep our checkbox, but make the checkbox mean something.

- **Title = verb + object.** Examples: "Update Sales Invoice SINV-2026-00042" / "تعديل فاتورة المبيعات SINV-2026-00042". Avoid a generic "Confirm action". The record name links to the record (new tab).
- **Body = a diff, not prose.** Use a 3-column mini table: Field | Current | New. Change only one field at a time, which our backend already enforces, so this stays one row. For creates, list the fields that will be set. Use human field labels, not fieldnames.
- **Impact line**, when relevant. Examples: "This will submit the document; it can then only be cancelled, not edited." Or "Affects 1 record." Keep it factual and in plain language.
- **Checkbox wording** names the specific thing, for example "I checked the new value for Due Date". Avoid generic consent like "I understand". If every card has the same checkbox, people learn to tick it without reading it. Consider keeping the checkbox only for submit, cancel, delete and imports, and using a single Approve click for drafts. That is a product decision for us. Microsoft and VS Code use one click.
- **Buttons:** exactly two, at the bottom. The primary button repeats the verb ("Update" / "تحديث"). The secondary button is "Cancel" / "إلغاء". Use the primary button's position for its reading direction: in RTL the primary sits on the left end (inline-end), in LTR on the right. Never show "Always allow" for writes.
- **States inside the card:**
  - Pending: buttons on, Approve disabled until the box is ticked.
  - Running: both buttons locked, spinner, "Saving…".
  - Done: compact green state "Updated · 10:42 · Open record", with the diff collapsed.
  - Failed: red text with the plain reason, plus "Try again".
  - Cancelled: grey "Cancelled. Nothing was changed."
  - Expired: show this if the pending action has timed out.
- **Never more than one live card.** If a new proposal arrives, mark the older card "Replaced" and disable it.
- **Accessibility:**
  - The card is a `role="group"` labelled by its title.
  - State changes are announced via an `aria-live="polite"` region.
  - Focus moves to the checkbox when the card appears. It does not jump to Approve.

### 3.2 Empty / first-run state

- **Greeting line** with the user's first name, plus one sentence of scope: "I can count, list and chart records you can open, export to Excel, and prepare changes you approve."
- **3–4 starter prompt buttons chosen by the current route.** On a Sales Invoice list, offer "Unpaid invoices this month", "Top 5 customers by sales", "Export overdue invoices to Excel". On a form, offer "Summarise this record" and "Show related payments". Clicking a prompt **sends** it. Today the cheat sheet only fills the input with example text.
- **Disclosure line under the input** (we already have one). Keep it one line.
- **"What can you do?"** opens the full cheat sheet as a secondary link. Do not show it by default.

### 3.3 Thinking / progress display

- **While running:** a single status row with a subtle animated icon and the current step in plain words: "Reading Sales Invoices…", "Building chart…". Update the row in place. Do not add a line per event, and do not show a typing-dots-only indicator for more than about 1 s.
- **After the answer:** collapse to "Checked 3 sources · 2.1 s" (a `details` element, closed by default). When expanded, show the steps as short phrases with the DocType and filter, no JSON. That is real "footprints" (shape.of.ai), not invented reasoning (NN/g caution).
- **Add a Stop button** to the composer while a request runs (shape.of.ai "Controls").
- **If the request takes more than about 10 s,** add "Still working, large report…" so silence never looks like a hang.

### 3.4 Results display

- **Count:** a big number plus a label, plus a "Based on" line (DocType · filters · date range) and a "View list" link to `/app/<doctype>?<filters>`.
- **List:** at most 5–8 rows inline as a compact table with 2–4 columns. Record names are links. Add a "Showing 8 of 37 · Open full list · Export Excel" footer. No horizontal scroll at 448 px. Drop columns rather than scroll.
- **Chart:**
  - One chart per answer, with a title stating metric and period.
  - Values labelled directly on bars where they fit.
  - Use "Show table" as the accessible alternative, so screen readers get the numbers.
  - Bar charts in RTL run right-to-left on the category axis, but numbers stay LTR.
- **Excel:** show a file chip (icon, filename, row count) with a Download button. Do not just print a link.
- **Do not repeat the same numbers in prose and in the card** (Microsoft "don't duplicate content"). The prose should be one or two sentences of interpretation.

### 3.5 Follow-ups

- **2–3 chips under the newest assistant message only.** Chips under older messages disappear.
- **Derive chips from the result type and the user's permissions.** For example, offer "Export" only if export is allowed.
- **Chips are short verbs**, e.g. "Chart by customer", "Only overdue", "Export Excel". Use the active UI language.
- **When the request is ambiguous, ask a clarifying question with option chips** (shape.of.ai "Follow up"). Do not guess. Example: "Which date: posting date or due date?"

### 3.6 Feedback

- **Show thumbs up/down and Copy** under each finished answer. Show them quietly (visible on hover/focus and always on touch).
- **Thumbs-down opens an optional single row of reasons** plus a free-text box. Say "Sent to your system administrator to improve answers" (PAIR: explain what feedback is used for).
- **Do not ask for feedback on approval cards.** The outcome (approved or cancelled) is already the signal.

### 3.7 RTL (Arabic) specifics

- **Use CSS logical properties throughout** (`margin-inline-start`, `padding-inline-end`, `inset-inline-end`). Then one `dir` on the root flips the whole panel. Mirror the direction icons (send arrow, back, expand chevrons). Do not mirror the logo, checkmarks or charts' numeric axes (Material).
- **Wrap runtime text in `<bdi>` or put `dir="auto"` on the element** (W3C). This covers record names, customer names, item codes, amounts and filenames. Our bubbles already set `dir` per message. Also isolate each inline value inside the message, or sentences like "تم تحديث SINV-2026-00042 بمبلغ 1,250.00 SAR" will reorder.
- **Keep IDs, codes, emails, URLs and Excel filenames `dir="ltr"`.** Keep table number columns aligned to the end with tabular figures.
- **Numerals:** use one system per locale setting. Western digits are common in Gulf business software. If supported, offer Arabic-Indic digits via the user's Frappe number format. Never mix the two in one answer.
- **Bubbles:** user messages sit at the inline-end (left in RTL), assistant messages at the inline-start. Dates and times follow the user's locale.
- **Font:** keep Cairo for Arabic. Line-height around 1.6–1.7 for Arabic body text. Avoid letter-spacing on Arabic, because it breaks joining.
- **Language toggle:** changing AR/EN should flip `dir` immediately without reloading history.

---

## 4. Things to avoid

- **Generic confirmations.** Examples: "Are you sure?", or a checkbox whose label never changes. Users learn to tick it without reading.
- **Showing raw model reasoning or long step logs by default.** It looks transparent but often isn't (NN/g).
- **Citations that look authoritative but can't be checked.** Every "based on" must open the real filtered list.
- **App-in-a-panel.** Avoid tabs, filters, pagination or settings inside answer cards (Microsoft).
- **Saying the same thing twice,** once in a card and again in prose.
- **Auto-scrolling to the bottom while text streams** (NN/g).
- **Hiding the disclaimer in a tooltip or settings page.** Also avoid scary legal wording.
- **"Always allow" or bulk silent writes.**
- **Error messages that expose `exc_type`, Python exception names or CSRF jargon.**
- **Left/right-hardcoded CSS, and unisolated mixed Arabic/English runs.**
- **Typing-dots with no text for long operations.**
- **Starter prompts that only fill the input with English sample text.**
- **More than two buttons on any card.**

---

## 5. Sources

Official design systems and documentation:
- Microsoft. User experience guidelines for MCP apps in declarative agents for Microsoft 365 Copilot (updated 2026-07) [Official]. https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-mcp-apps-ui-guidelines
- Microsoft. Confirmation prompts for MCP and API plugins for Microsoft 365 Copilot (updated 2026-07) [Official]. https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/plugin-confirmation-prompts
- Microsoft. Ask Copilot questions, Dynamics 365 Sales (updated 2026-04) [Official]. https://learn.microsoft.com/en-us/dynamics365/sales/use-sales-copilot
- Microsoft. Get information from Copilot, Dynamics 365 Sales [Official, snippet only]. https://learn.microsoft.com/en-gb/dynamics365/sales/copilot-get-information
- Fluent 2 design system (components and tokens referenced by the Microsoft guidelines). I could not open a dedicated AI page, which returned 404. https://fluent2.microsoft.design/
- VS Code. Manage approvals and permissions [Official, snippet only]. https://code.visualstudio.com/docs/agents/run/approvals
- VS Code. Use tools with agents [Official, snippet only]. https://code.visualstudio.com/docs/copilot/agents/agent-tools
- GitHub. Copilot CLI autopilot and approvals [Official, snippet only]. https://docs.github.com/en/copilot/concepts/agents/copilot-cli/autopilot
- SAP Fiori. Designing for Generative AI [Official, snippet only, 403]. https://www.sap.com/design-system/fiori-design-web/v1-148/foundations/ai-and-joule-design/overview/generative-ai-design
- SAP Fiori. Design Principles for Generative AI [Official, snippet only, 403]. https://www.sap.com/design-system/fiori-design-web/v1-151/foundations/ai-and-joule-design/guidelines/design-principles-for-generative-ai
- SAP Fiori. Local AI notice [Official, snippet only]. https://www.sap.com/design-system/fiori-design-web/v1-136/ui-elements/local-ai-notice/usage
- SAP Fiori iOS. AI progress indicators [Official, snippet only]. https://www.sap.com/design-system/fiori-design-ios/v26-1/in-app-ai-design/components/ai-progress-indicators
- SAP community. Fiori guidelines v1.90 (AI feedback patterns) [Secondary, older]. https://community.sap.com/t5/technology-blog-posts-by-sap/sap-fiori-design-guidelines-version-1-90-now-available/ba-p/13509972
- Salesforce Lightning Design System. Conversation design guidelines (Spring '21, archived, pre-Agentforce) [Official, dated]. https://spring-21.lightningdesignsystem.com/guidelines/conversation-design/overview
- Salesforce. Secure your Agentforce custom actions (record-changing actions need user verification) [Official, snippet only]. https://developer.salesforce.com/docs/platform/isvforce/guide/secure-agentforce-actions.html
- HubSpot. Use Breeze Assistant (citations, Sources button) [Official, snippet only]. https://knowledge.hubspot.com/ai/use-breeze-assistant
- Notion. Release 2.45 (AI connectors, cited sources) [Official release note, snippet only]. https://www.notion.com/releases/2024-09-25
- Odoo 19. AI documentation [Official, snippet only]. https://www.odoo.com/documentation/saas-19.4/applications/productivity/ai.html
- OpenAI. ChatGPT agent help article (confirmations, take over) [Official, snippet only]. https://help.openai.com/articles/11752874
- Zendesk. AI overview / Copilot [Official, snippet only]. https://support.zendesk.com/hc/en-us/articles/5608652527386-Zendesk-AI-overview

Guidance and research:
- Nielsen Norman Group. 10 Guidelines for Designing Your Site's AI Chatbots (2026-04-24) [Official]. https://www.nngroup.com/articles/ai-chatbots-design-guidelines/
- Nielsen Norman Group. Explainable AI in Chat Interfaces (2025-12-12) [Official]. https://www.nngroup.com/articles/explainable-ai/
- Google PAIR. People + AI Guidebook, Feedback + Control chapter [Official]. https://pair.withgoogle.com/chapter/People%20+%20AI%20Guidebook%20-%20Feedback%20+%20Control.pdf
- shape.of.ai. AI UX pattern catalogue (Suggestions, Follow up, Action plan, Verification, Citations, Stream of Thought, Controls, Disclosure, Footprints) [Official]. https://www.shapeof.ai/
- W3C Internationalization. Inline markup and bidirectional text in HTML [Official]. https://www.w3.org/International/articles/inline-bidi-markup/
- Material Design. Bidirectionality [Official]. https://m2.material.io/go/design-bidirectionality

Vendor claims, blogs and secondary sources:
- Salesforce blog. 5 Insider Design Tips for Building Your AI Agents (2025-06-19) [Vendor blog]. https://www.salesforce.com/blog/ai-agent-design-tips/
- Intercom. Deploy Fin in web and mobile live chat [Vendor claim]. https://www.intercom.com/integrations/connectors/messenger
- eesel.ai. Zendesk AI Copilot review [Secondary]. https://www.eesel.ai/blog/zendesk-ai-copilot-review
- Claude.ai thinking display description [Secondary]. https://claudemaster.net/features/extended-thinking-chat
- Cursor forum. Arabic RTL chat text renders with broken BiDi layout [Secondary, bug report]. https://forum.cursor.com/t/arabic-rtl-chat-text-renders-with-broken-bidi-layout-on-windows/162815
- Anthropic Claude Code issue on RTL support [Secondary, feature request]. https://github.com/anthropics/claude-code/issues/11050

**Gaps:**
- I found no current public spec for the Agentforce or Einstein panel layout, or for its confirmation UI.
- I found no public Joule panel spec, because the SAP pages were blocked.
- I found no Fluent 2 Copilot-specific page.
- Claude.ai and ChatGPT conventions above come from help articles and secondary descriptions, not design docs.
- None of the sources give an exact side-pane width. Our 448 px is in the usual 360–480 px range for side panes, but that is an observation, not a sourced number.
