# The ERPNext-AI-Assistant

[![Frappe](https://img.shields.io/badge/Frappe-v16-0089FF)](https://frappeframework.com)
[![ERPNext](https://img.shields.io/badge/ERPNext-optional-2E7D32)](https://erpnext.com)
[![Arabic](https://img.shields.io/badge/Arabic-and%20English-0F766E)](#what-you-can-do-today)
[![License: MIT](https://img.shields.io/badge/License-MIT-111827)](license.txt)
[![Support](https://img.shields.io/badge/Support-ahmad18189%40gmail.com-111827)](mailto:ahmad18189@gmail.com)

**Ask your Frappe site in Arabic or English, from the Desk you already use.**

Count customers, open Data Import, sketch a chart, or prepare a new record. The answer uses the records your login can already open. A new record, a change, or an import waits until you press Approve.

Made by **Ahmed Abdelrahman**. Support: [ahmad18189@gmail.com](mailto:ahmad18189@gmail.com).

`#frappe` `#erpnext` `#arabic` `#ai-assistant` `#hrms` `#crm` `#data-import` `#rtl` `#openai` `#desk`

## A chat panel on your site

Staff stay in Desk. The panel sits on the page, in Arabic or English, and follows the apps you have installed. A site with only Frappe can still ask about tasks, events, and notes. When ERPNext, HR, CRM, or your own app is installed, the same panel can talk about those records too.

Guests stay out. Each person sees the records their role already allows.

<img src="docs/images/assistant-ask-en.png" alt="English assistant panel with a question ready to send" width="280">

*The English panel, ready to ask for a chart. Switch to Arabic with one button.*

## What you can do today

| You say | What you get |
|---|---|
| How many customers? / كم عدد العملاء | The count your login is allowed to see. |
| Show a chart of leads by status | A chart, plus the numbers written out. |
| Open the import tool / افتح أداة الاستيراد | A button that opens Data Import on this site. |
| Create a task for tomorrow | A draft. You read it and press Approve. |
| Here is my spreadsheet | A check of the columns, then an import after you approve. |
| What can you do? / ماذا تستطيع | A short list of these jobs. |

Today the assistant can:

- Answer a work question about this site. Ask in Arabic and the reply comes back in Arabic.
- Count and list records your role can read, and draw a simple chart from them.
- Open a Desk page, such as Data Import.
- Fill a new record or a change one field at a time, then wait for Approve.
- Read a spreadsheet, line the headers up, and start the import after you approve.
- Explain a how-to step from the ERPNext manual when ERPNext is installed.
- Remember a fact about you after you tick confirm.

You bring an OpenAI-compatible key and keep it in ERP AI Settings. The panel runs on your site.

## What we are building toward

A companion for the Frappe site a company already runs. Someone in sales, finance, HR, or the back office asks in the language they work in, lands on the right screen, and leaves with an answer they could have opened themselves. The same standard stays: your role decides what you can see, and Approve decides what gets saved.

## What's next

The next releases follow the questions teams already ask:

- More of the apps and records already installed on the site, so a question about stock, invoices, people, or a custom app lands in the right place.
- A short choice when one question could belong to two apps, so the answer matches the work in front of you.
- Charts, lists, and imports for more of the everyday jobs, still with the numbers written in a sentence you can check.
- The same promise on every new job: you see it, then you approve it, then it is saved.

## How it compares

These are other ways teams add a chat to Frappe or ERPNext. Details come from each project's public page in 2026.

| | This app | [ChangAI](https://github.com/ERPGulf/changai) | [Frappe Assistant Core](https://github.com/buildswithpaul/Frappe_Assistant_Core) | [Frappe AI](https://github.com/vyogotech/frappe_ai) | [LazyChat](https://github.com/soumyasethy/lazychat-erpnext) |
|---|---|---|---|---|---|
| Where you talk | A panel on your Desk | Inside ERPNext | Free connection for Claude, ChatGPT, or Cursor. The in-Desk chat is their cloud plan | A Desk sidebar that calls an agent you host | Inside ERPNext |
| Frappe without ERPNext | Yes. Tasks, events, and notes still work | Built for ERPNext | Built for ERPNext and Frappe data | Frappe and ERPNext | ERPNext |
| Arabic and English | Both, with a button on the panel | English and Arabic | The cloud chat can speak in your language | Your agent decides | Your model decides |
| Who pays for the model | Your OpenAI-compatible key | Gemini, Claude, or a server you run | Your key for the free connection. A subscription for the in-Desk chat | The agent service you run | Your own model key |
| Saving records | You press Approve | Questions first. Actions are still growing | The cloud chat shows the change and waits | Depends on the agent you connect | You apply each change |
| License | MIT | MIT | AGPL-3.0 for the open core | MIT | MIT |

Pick this app when the chat should live on your site, in Arabic and English, including a Frappe site that has not installed ERPNext.

## Questions people ask

**Does it work without ERPNext?**  
Yes. Tasks, events, and notes are enough for a Frappe-only site.

**Will a record change while I am still reading the answer?**  
Creates, updates, and imports wait until you press Approve.

**Which languages does it speak?**  
Arabic and English. One button switches the panel. An Arabic question gets an Arabic reply.

**Who is it for?**  
Companies that already use Frappe or ERPNext and want staff to ask from the Desk they open every day.

**Do I need another subscription for the chat?**  
You need your own model key. The panel itself is part of this app.

## Support

**Ahmed Abdelrahman**  
Email: [ahmad18189@gmail.com](mailto:ahmad18189@gmail.com)

Write with your Frappe version, the question you asked, and what the assistant replied. Leave the API key out of the email.

## Install

Frappe v16. ERPNext, HR, and CRM are optional.

```bash
cd /path/to/frappe-bench
bench get-app https://github.com/ahmad18189/erpnext_ai_assistant.git
bench --site your.site install-app erpnext_ai_assistant
bench --site your.site migrate
bench build --app erpnext_ai_assistant
bench --site your.site clear-cache
```

A new site gets a working starting point: settings, the Frappe helper, and the core skill. A value you already saved stays as you left it. Extra skills for ERPNext, CRM, HR, stock, and finance appear only when that app is installed.

### Add your key

1. Desk: ERP AI Settings → API Key
2. Or on the server, in `site_config.json`:

```json
{
  "erp_ai_openai_api_key": "YOUR_OPENAI_API_KEY"
}
```

3. Or the environment variables `OPENAI_API_KEY` or `ERP_AI_API_KEY`

Keep the key on the server. It does not belong in this repository.

The panel opens on Desk and on each installed app. Add or hide a path under ERP AI Settings → Overlay Pages.

### A spreadsheet in the chat

You can attach a picture, CSV, Excel file, PDF, or text file up to 5 MB. The file stays private to you.

- A picture is read so the assistant can talk about it.
- A CSV or Excel file is matched to a Data Import layout. You see which columns fit, which required fields are missing, and a blank header you can download.
- When the file matches one list you are allowed to import, Approve creates the import and starts it. The reply then tells you whether it succeeded, partly succeeded, failed, timed out, or is still running. Failed rows can be downloaded.

## For developers

The chat, the tools, and the DocTypes are described in [`docs/architecture.md`](docs/architecture.md). Every read and every save runs as the person who is logged in.

| Doc | What it covers |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | Product decisions |
| [`docs/SRS.md`](docs/SRS.md) | What the app is required to do |
| [`docs/architecture.md`](docs/architecture.md) | How a message travels through the app |
| [`docs/TEST_RESULTS.md`](docs/TEST_RESULTS.md) | Test notes |

```bash
bench --site your.site run-tests --app erpnext_ai_assistant
```

## License

MIT — see [`license.txt`](license.txt).
