# Expense Insights

A small web application for recording business expenses, viewing spending statistics, and asking an AI assistant questions about the data, such as "How much did I spend on travel this month?"

## Features

- **Expense management:** add, view, edit and delete expenses; search descriptions; filter by category, payment method, date range and amount; sort and paginate.
- **Dashboard:** total spent, number of expenses, current month's spending, highest category, largest single expense, and a category breakdown chart.
- **REST API:** CRUD plus a statistics endpoint, with consistent JSON errors and per-field validation messages.
- **AI assistant:** answers questions by first retrieving only the relevant data through four narrow, validated tools, then generating the answer. Uses Claude when an API key is configured; otherwise (or if the API fails) an offline rule-based assistant answers using the same tools.

## Architecture

```
Browser (HTML/CSS/JS) ──JSON──▶ Flask routes ──▶ validation ──▶ repository (SQL) ──▶ SQLite
                                     │
                                     ├──▶ stats service ──▶ repository
                                     │
                                     └──▶ assistant service ──▶ LLM agent ⇄ Claude (tool use)
                                                          └──▶ rule-based fallback
                                                both call ──▶ retrieval tools ──▶ repository
```

Layers depend in one direction only: routes → services → repository → database. All SQL is in `repository.py`. See **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** for diagrams, the data model, and the reasoning behind each design decision.

## Technology stack

| Part | Choice | Why |
|---|---|---|
| Backend | Python 3.10+, Flask 3 | Recommended in the brief; small and explicit, so the structure is easy to follow. |
| Database | SQLite via the standard `sqlite3` module | Zero setup; plain SQL keeps the queries visible and reviewable (no ORM needed at this size). |
| Frontend | HTML, CSS, vanilla JavaScript | No build step; served by Flask from the same origin, so no CORS configuration. |
| AI | Anthropic Messages API with tool use, called via the standard library | No SDK dependency; the HTTP transport is injectable for testing. |
| Tests | `unittest`, run with `pytest` | Works with either runner; 76 tests. |

Runtime dependencies are just `Flask` and `python-dotenv`.

## Project structure

```
expense-insights/
├── README.md
├── AI_USAGE.md                 How an AI coding agent was used
├── .env.example                Environment variable template (copy to .env)
├── docs/
│   └── ARCHITECTURE.md         Diagrams, data model, design decisions
├── frontend/                   Served by Flask at / and /static/
│   ├── index.html
│   ├── styles.css
│   └── app.js
└── backend/
    ├── run.py                  Entry point (python run.py)
    ├── requirements.txt
    ├── pytest.ini
    ├── app/
    │   ├── __init__.py         Application factory + CLI commands (init-db, seed-db)
    │   ├── config.py           Reads environment variables
    │   ├── constants.py        Categories, payment methods, limits
    │   ├── schema.sql          Table, CHECK constraints, indexes
    │   ├── db.py               Connection per request, schema creation
    │   ├── errors.py           Error types + JSON error handlers
    │   ├── validation.py       Input parsing for bodies, query strings and AI tool arguments
    │   ├── repository.py       All SQL
    │   ├── money.py            Paise ↔ rupees, ₹ formatting with Indian digit grouping
    │   ├── clock.py            Injectable "today" for deterministic tests
    │   ├── seed.py             Deterministic demo data
    │   ├── routes/             expenses.py, stats.py, assistant.py, meta.py
    │   ├── services/stats.py   Dashboard statistics
    │   └── assistant/
    │       ├── service.py      Picks LLM or rules, handles fallback
    │       ├── llm_agent.py    Tool-calling loop and system prompt
    │       ├── llm_client.py   Minimal Anthropic API client
    │       ├── tools.py        The four retrieval tools
    │       └── rule_based.py   Offline intent parser
    └── tests/
        ├── base.py             Temporary database per test, fixed date
        ├── test_expenses_api.py
        ├── test_stats.py
        ├── test_assistant.py   Rule parsing, tools, LLM loop with a fake API
        └── test_units.py       Money formatting and validation
```

## Installation

Requires Python 3.10 or newer.

```bash
git clone <your-repo-url> expense-insights
cd expense-insights

python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows (PowerShell)
.venv\Scripts\Activate.ps1

pip install -r backend/requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

## Environment variables

All are optional. The app runs with no `.env` at all, using the offline assistant.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_PATH` | `backend/instance/expenses.db` | SQLite file location. |
| `AI_PROVIDER` | `auto` | `auto` uses Claude if a key is set, else rules. `anthropic` always tries Claude. `rules` never calls an external API. |
| `ANTHROPIC_API_KEY` | (empty) | Enables the Claude-powered assistant. Never commit this. |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | Any Messages API model with tool use. `claude-haiku-4-5-20251001` is cheaper. |
| `ANTHROPIC_TIMEOUT_SECONDS` | `30` | Timeout per API call. |
| `ANTHROPIC_TOTAL_TIMEOUT_SECONDS` | `45` | Overall time limit per question; after it the rules assistant answers. |
| `HOST`, `PORT` | `127.0.0.1`, `5000` | Development server address. |
| `FLASK_DEBUG` | `0` | Set to `1` for auto-reload and debug pages (development only). |

## Database setup

The schema is created automatically when the app starts. To manage it explicitly, run these from the `backend/` folder:

```bash
cd backend
python -m flask --app run init-db            # create tables (safe to re-run)
python -m flask --app run seed-db            # add 45 demo expenses over the last four months
python -m flask --app run seed-db --reset    # wipe everything, then add demo data
python -m flask --app run init-db --reset    # wipe everything, leave the database empty
```

`python -m flask` is used because on Windows the plain `flask` command may not be on `PATH` after a user-level `pip install` (the scripts folder it installs to is not added to `PATH` automatically).

## Running the backend

```bash
cd backend
python run.py
```

The API is now at `http://127.0.0.1:5000/api`. Check it with `curl http://127.0.0.1:5000/api/health`.

## Running the frontend

There is no separate frontend server: Flask serves it. With the backend running, open **http://127.0.0.1:5000/** in a browser.

## Running tests

```bash
cd backend
pytest              # or: python -m unittest
```

Each test uses its own temporary database and a fixed date (15 October 2026), so results do not depend on the real calendar. The LLM tests use a scripted fake API (or a mocked `urlopen` for transport errors), so no key or network is needed.

What the tests cover:

- **Create:** normalisation (`"travel"` → `"Travel"`), exact money handling, every invalid field type, unknown fields, malformed JSON.
- **Retrieve:** single and list, each filter, LIKE-wildcard escaping in search, sorting, pagination, invalid query parameters, 404s.
- **Update:** `PUT` full replacement, `PATCH` partial update, failed validation leaves data unchanged, 404s.
- **Delete:** removal, 404s, only the target row is affected.
- **Statistics:** empty database, month boundaries (30 Sep and 1 Nov excluded from October), tie-breaking, date-range scoping, stats after updates and deletes.
- **Assistant:** all five example questions from the brief, period and intent parsing, tool argument validation and result caps, the LLM tool loop (including error recovery, fallback on API failure, the step limit, and the overall time limit per question).
- **Assistant robustness:** impossible periods ("last 0 days", "january 0000") get a helpful answer instead of a 500; answer wording when no category is given; fallback to rules on connection resets, undecodable responses, malformed responses and unexpected errors inside a tool (without exposing internal details); a response cut off by `max_tokens` is never shown as a complete answer; raw API error bodies stay in the server log and are not sent to the client.

## API reference

All responses are JSON. Amounts are rupees with up to 2 decimal places. Dates are `YYYY-MM-DD`.

| Method | Path | Description | Success |
|---|---|---|---|
| `GET` | `/api/expenses` | List with filters, sorting, pagination | 200 |
| `POST` | `/api/expenses` | Create (all fields required) | 201 + `Location` |
| `GET` | `/api/expenses/{id}` | Get one | 200 |
| `PUT` | `/api/expenses/{id}` | Replace (all fields required) | 200 |
| `PATCH` | `/api/expenses/{id}` | Update only the supplied fields | 200 |
| `DELETE` | `/api/expenses/{id}` | Delete | 204 |
| `GET` | `/api/expenses/stats` | Dashboard statistics; optional `start_date`, `end_date` | 200 |
| `POST` | `/api/assistant/query` | Ask a question: `{"question": "..."}` | 200 |
| `GET` | `/api/meta` | Allowed categories and payment methods | 200 |
| `GET` | `/api/health` | Health check | 200 |

**List parameters:** `q` (description search), `category`, `payment_method`, `start_date`, `end_date`, `min_amount`, `max_amount`, `sort` (`date`, `amount`, `category`, `created_at`, `id`), `order` (`asc`, `desc`), `page`, `page_size` (max 200).

**Create an expense**

```bash
curl -X POST http://127.0.0.1:5000/api/expenses \
  -H "Content-Type: application/json" \
  -d '{"date": "2026-10-05", "category": "Travel", "description": "Flight to Delhi", "amount": 5400.50, "payment_method": "Card"}'
```

```json
{"id": 1, "date": "2026-10-05", "category": "Travel", "description": "Flight to Delhi",
 "amount": 5400.5, "payment_method": "Card",
 "created_at": "2026-10-05T09:12:44Z", "updated_at": "2026-10-05T09:12:44Z"}
```

Category and payment method are case-insensitive on input and returned in canonical form. Sending back a previously received object (including `id`, `created_at`, `updated_at`) to `PUT` works; those read-only fields are ignored. Any other unknown field is rejected.

**Statistics**

```json
{
  "currency": "INR",
  "filters": {"start_date": null, "end_date": null},
  "total_amount": 140277.89,
  "expense_count": 45,
  "current_month": {"month": "2026-10", "total_amount": 5257.5, "expense_count": 2},
  "highest_category": {"category": "Food", "total_amount": 59170.44, "expense_count": 17, "percentage": 42.18},
  "highest_expense": {"id": 5, "date": "2026-06-28", "category": "Office", "description": "Desk chair", "amount": 10630.0, "...": "..."},
  "by_category": [{"category": "Food", "total_amount": 59170.44, "expense_count": 17, "percentage": 42.18}]
}
```

`current_month` always means the calendar month containing today; `start_date`/`end_date` scope everything else.

**Ask the assistant**

```bash
curl -X POST http://127.0.0.1:5000/api/assistant/query \
  -H "Content-Type: application/json" \
  -d '{"question": "Show me the three largest expenses."}'
```

```json
{
  "question": "Show me the three largest expenses.",
  "answer": "Your 3 largest expenses overall:\n1. ₹10,630.00 - Desk chair (Office, 2026-06-28, Card)\n...",
  "tool_calls": [{"tool": "get_top_expenses", "input": {"limit": 3}, "ok": true}],
  "provider": "rules"
}
```

`provider` is `anthropic` or `rules`. If Claude was configured but failed, `fallback_reason` is a short generic message; the specific cause is written to the server log.

**Errors** always use one shape:

```json
{"error": {"code": "validation_error", "message": "Expense data is invalid.",
           "details": {"amount": "must be greater than 0", "category": "must be one of: Food, Travel, Office, Software, Utilities, Marketing, Other"}}}
```

Codes: `validation_error` (400), `not_found` (404), `method_not_allowed` (405), `internal_error` (500).

## AI integration approach

The assistant **retrieves first, then answers**. It never sends the database to the model.

1. The question goes to Claude together with a system prompt (today's date, the exact date ranges for "this month", "last month", "this year", the allowed categories, and answering rules) and the definitions of four tools: `get_total_spending`, `get_category_breakdown`, `get_top_expenses`, `search_expenses`.
2. Claude replies with the tool call(s) it needs, for example `get_total_spending(category="Travel", start_date="2026-10-01", end_date="2026-10-31")`.
3. The backend validates the arguments with the same rules as the REST API and runs a parameterised SQL aggregate. Results are small: a total, a breakdown, or at most 20–25 rows.
4. The results go back to Claude, which writes the final answer from them. The loop is limited to 6 steps.

Why tool calling rather than having the model write SQL: the model can only request specific, validated operations, so there is no SQL-injection surface and no risk of the model reading or changing data it should not. Why not paste all expenses into the prompt: it does not scale, costs more, and leaks unrelated data into every request.

**Without an API key** the app still answers. A rule-based parser extracts the period, category and intent from the question and calls the same tools. It also takes over automatically if the Claude API fails or times out, so the assistant never simply breaks. Every response lists the tool calls made, and the UI shows them under "How this was answered".

Full details and a sequence diagram are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#ai-assistant-retrieve-first-then-answer).

## Assumptions and limitations

- **Single user, no authentication.** The brief describes one business user. Multi-user support would add a `users` table, a `user_id` column on expenses, and authentication on every route.
- **Currency is INR**, matching the UPI payment method. Amounts are stored in paise, so supporting another currency would mean adding a currency column and formatting by locale.
- **Future-dated expenses are allowed** (for example, a booked trip). They are included in totals.
- **The rule-based assistant** understands the common question shapes, not arbitrary phrasing. Free-form questions work best with Claude enabled.
- **Development server only.** For deployment, run behind a WSGI server such as gunicorn and set `FLASK_DEBUG=0`.

## Possible next steps

- Monthly trend chart and budgets per category.
- CSV import and export.
- Conversation memory in the assistant for follow-up questions ("and last month?").
- Database migrations (for example, Alembic) once the schema starts to change.
