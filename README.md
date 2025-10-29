# Excel DB App (Streamlit Starter)

A minimal CRUD web app that reads/writes an Excel file (`data.xlsx`) as a "table-like DB".
Perfect as a starting point to later swap Excel for a real database (e.g., SQLite/Postgres).

## Quickstart

```bash
# 1) Create and activate a virtual environment (recommended)
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 2) Install dependencies
pip install -r requirements.txt

# 3) Run
streamlit run app.py
```

The app will open in your browser. It will create `data.xlsx` automatically if not present.

## Features
- List + quick search
- Add / Edit / Delete records
- Excel persistence (sheet: `items`)
- Upload an existing workbook to replace `data.xlsx`

## Columns
- `id` (int, unique primary key)
- `name` (str, required)
- `category` (str)
- `quantity` (int, >= 0)
- `updated_at` (datetime)

## Swap Excel for a DB later
- Replace the `load_data` / `save_data` functions with DB calls (e.g., SQLAlchemy to SQLite/Postgres).
- Keep the UI code.

## Notes
- Concurrency: Excel is a single-file store. For many concurrent editors, move to a DB.
- Backups: version `data.xlsx` with git or periodic copies.
