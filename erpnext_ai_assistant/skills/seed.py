"""Seed content for ERP AI Skill records (inserted once on install/migrate)."""

from __future__ import annotations

CRM_ROLES = [
	{"role": "System Manager"},
	{"role": "Sales Manager"},
	{"role": "Sales User"},
]

SKILL_SEEDS = [
	{
		"title": "Site installed apps",
		"enabled": 1,
		"priority": 5,
		"routes": "",
		"doctypes": "",
		"roles": [
			{"role": "System Manager"},
			{"role": "Sales User"},
			{"role": "Sales Manager"},
			{"role": "All"},
		],
		"description": """# Site installed apps (in scope)

Users may ask about any custom or standard app installed on this site. That is workplace scope.

Use the installed-apps tool list when it is provided. Summarize the app title, description, and DocTypes you can actually read. Do not invent apps that are not installed.
""",
	},
	{
		"title": "CRM leads & deals",
		"enabled": 1,
		"priority": 10,
		"routes": "/crm\n/crm/leads\n/crm/deals",
		"doctypes": "CRM Lead, CRM Deal",
		"roles": list(CRM_ROLES),
		"description": """# CRM leads & deals

## Routes
- `/crm/leads` → List **CRM Lead**
- `/crm/leads/{name}` → Form **CRM Lead**
- `/crm/deals` → **CRM Deal**

## Finding a person by name (Arabic or English)
Always use `or_filters` on:
- `lead_name` (EN Full Name / AR الاسم الكامل)
- `first_name`
- `last_name`

Never filter on the Arabic label `اسم` as a fieldname.

## Fields to show
- Lead: `status`, `lead_owner` (not `_assign`), `mobile_no`, `organization` (Data), `email`, `name`
- Deal: `deal_owner`, Link `organization` + `organization_name`

## Permissions
Respect session user DocPerms and CRM permission query conditions.
If the user cannot read leads, say clearly that CRM Lead is not readable under their roles.
Never reply with only «ضمن صلاحياتك».
For create/update/delete: propose a Pending Action and ask the user to Approve — never write silently.
""",
	},
	{
		"title": "HR / payroll",
		"enabled": 1,
		"priority": 20,
		"routes": "/app/hrms\n/app/employee\n/app/salary-slip",
		"doctypes": "Employee, Salary Slip, Leave Application, Attendance",
		"roles": [{"role": "System Manager"}, {"role": "HR Manager"}, {"role": "HR User"}],
		"description": """# HR / payroll

Use DocTypes **Employee**, **Salary Slip** (`gross_pay`, `net_pay`, `start_date`, `end_date`, `employee`),
Leave Application, Attendance.
Never invent pay figures. Only return rows the session user can read.
""",
	},
	{
		"title": "Stock",
		"enabled": 1,
		"priority": 30,
		"routes": "/app/stock\n/app/item\n/app/bin",
		"doctypes": "Item, Bin, Stock Ledger Entry",
		"roles": [{"role": "System Manager"}, {"role": "Stock Manager"}, {"role": "Stock User"}],
		"description": """# Stock

- **Item**, **Bin.actual_qty**, Stock Ledger Entry
- Invoice line `qty` is not warehouse bin balance — do not confuse them.
""",
	},
	{
		"title": "Finance / invoices",
		"enabled": 1,
		"priority": 40,
		"routes": "/app/accounts\n/app/sales-invoice\n/app/purchase-invoice",
		"doctypes": "Sales Invoice, Purchase Invoice",
		"roles": [
			{"role": "System Manager"},
			{"role": "Accounts Manager"},
			{"role": "Accounts User"},
		],
		"description": """# Finance / invoices

## Sales Invoice / Purchase Invoice
Fields: `grand_total`, `outstanding_amount`, `posting_date`, `status`, `docstatus`,
`taxes_and_charges`, `total_taxes_and_charges`, `customer` / `supplier`.

## VAT
Use the site's Sales Taxes and Charges Template when one is configured. Do not invent a template name or rate.

## E-invoice
If no e-invoicing app is installed, say clearance status is unavailable. Never invent clearance IDs.
""",
	},
]
