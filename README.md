# 🛠️ SQL Corrector

An AI-powered SQL debugger built with Streamlit and GPT-4o.  
Fixes syntax errors, typos, missing JOINs, GROUP BY issues, and more — across 9 SQL dialects.

---

## ✨ Features

| Feature | Description |
|---|---|
| 🤖 GPT-4o powered | Fixes syntax, typos, JOIN issues, GROUP BY, CTEs, subqueries |
| 🎭 Auto-Masking | Replaces real table/column names with aliases before sending — real names never leave your machine |
| 🔀 Diff View | Side-by-side diff with line numbers showing exactly what changed |
| 🕐 Query History | Last 10 corrections kept in session |
| 🔍 Payload Inspector | See the exact JSON sent to OpenAI before it's sent |
| 🚫 No-Schema Mode | Send SQL only — schema never sent |
| 📋 Copy Button | One-click copy of corrected SQL |
| 9 Dialects | MySQL, PostgreSQL, SQLite, SQL Server, BigQuery, Oracle, Snowflake, Redshift, Generic |

---

## 🚀 Quick Start

### 1. Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/sql-corrector.git
cd sql-corrector
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set your OpenAI API key

**Option A — Streamlit secrets (recommended)**
```bash
mkdir -p .streamlit
echo 'OPENAI_API_KEY = "sk-..."' > .streamlit/secrets.toml
```

**Option B — Environment variable**
```bash
export OPENAI_API_KEY="sk-..."
```

**Option C — Enter in the sidebar** when the app loads (not saved between sessions).

> Get your key at [platform.openai.com](https://platform.openai.com) → API Keys.

### 4. Run
```bash
streamlit run sql_corrector.py
```

App opens at `http://localhost:8501`

---

## ☁️ Deploy to Streamlit Cloud (free)

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) → New app
3. Select your repo and `sql_corrector.py`
4. Under **Advanced settings → Secrets**, add:
```toml
OPENAI_API_KEY = "sk-..."
```
5. Click **Deploy**

---

## 🔒 Privacy

- **Auto-Masking ON**: only aliases (`t1`, `col1`) are sent to OpenAI — real table/column names never leave your browser
- **No-Schema Mode**: schema is stripped entirely before the API call
- **Payload Inspector**: shows the exact JSON sent so you can verify yourself
- Nothing is stored or logged by this app

---

## 📁 File Structure

```
sql-corrector/
├── sql_corrector.py      # Main app
├── requirements.txt      # Python dependencies
├── .gitignore            # Excludes secrets.toml and other sensitive files
├── README.md             # This file
└── .streamlit/
    └── secrets.toml      # Your API key (NOT committed to git)
```

---

## 🛠️ Local Development

```bash
# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate

pip install -r requirements.txt
streamlit run sql_corrector.py
```

---

## 📄 License

MIT — free to use and modify.
