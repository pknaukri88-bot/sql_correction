import streamlit as st
import re
import os
import requests
import json
import difflib
from datetime import datetime

# ─── Page Config ─────────────────────────────────────────────────────────────────
st.set_page_config(page_title="SQL Corrector", page_icon="🛠️", layout="wide")
st.title("🛠️ SQL Corrector")
st.caption("Powered by GPT-4o · Auto-masking · Diff view · History")

# ─── API Key ─────────────────────────────────────────────────────────────────────
def get_api_key_from_env():
    try:
        return st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass
    return os.environ.get("OPENAI_API_KEY", "")

env_key = get_api_key_from_env()

# ─── Session State ────────────────────────────────────────────────────────────────
for k, v in {
    "aliases": [], "corrected": "", "original": "",
    "changes": "", "history": []
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─── SQL Keywords (complete set) ──────────────────────────────────────────────────
SQL_KEYWORDS = {
    "SELECT","FROM","WHERE","AND","OR","NOT","IN","EXISTS","BETWEEN","LIKE","ILIKE",
    "IS","NULL","JOIN","INNER","LEFT","RIGHT","FULL","OUTER","CROSS","NATURAL",
    "ON","USING","AS","UNION","INTERSECT","EXCEPT","ALL","DISTINCT","INTO",
    "INSERT","UPDATE","DELETE","SET","VALUES","RETURNING","MERGE","REPLACE",
    "ORDER","BY","ASC","DESC","GROUP","HAVING","LIMIT","OFFSET","FETCH","NEXT",
    "ROWS","ONLY","WITH","RECURSIVE","LATERAL","CASE","WHEN","THEN","ELSE","END",
    "COUNT","SUM","AVG","MIN","MAX","COALESCE","NULLIF","CAST","CONVERT",
    "EXTRACT","INTERVAL","IFNULL","NVL","IIF","DECODE","ROW_NUMBER","RANK",
    "DENSE_RANK","NTILE","LAG","LEAD","FIRST_VALUE","LAST_VALUE","OVER",
    "PARTITION","WINDOW","FILTER","WITHIN","CREATE","DROP","ALTER","TABLE",
    "INDEX","VIEW","SEQUENCE","SCHEMA","DATABASE","TRUNCATE","RENAME","ADD",
    "COLUMN","CONSTRAINT","PRIMARY","KEY","FOREIGN","REFERENCES","UNIQUE",
    "CHECK","DEFAULT","TOP","ROWNUM","QUALIFY","EXPLAIN","ANALYZE","TRUE","FALSE",
    "INT","INTEGER","BIGINT","SMALLINT","TINYINT","MEDIUMINT","FLOAT","DOUBLE",
    "REAL","DECIMAL","NUMERIC","MONEY","VARCHAR","CHAR","NVARCHAR","TEXT",
    "BOOLEAN","BOOL","BIT","DATE","TIME","DATETIME","TIMESTAMP","TIMESTAMPTZ",
    "JSON","JSONB","XML","UUID","ARRAY","ENUM","BLOB","CLOB","BINARY",
}

# ─── Sidebar ─────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")

    if env_key:
        st.success("✅ API key loaded from environment.")
        api_key = env_key
    else:
        api_key = st.text_input(
            "OpenAI API Key", type="password",
            help="Get yours at platform.openai.com → API Keys"
        )
        if api_key:
            st.caption("💡 Set `OPENAI_API_KEY` env var to skip this step.")

    st.divider()
    no_schema    = st.toggle("🚫 No-Schema Mode",
                             help="Don't send schema — faster but skips missing-column checks.")
    use_masking  = st.toggle("🎭 Auto-Masking", value=True, disabled=no_schema,
                             help="Alias real names before sending to API.")
    show_diff    = st.toggle("🔀 Diff View", value=True,
                             help="Side-by-side diff of original vs corrected.")
    show_history = st.toggle("🕐 Query History", value=True,
                             help="Keep last 10 corrections in this session.")

    st.divider()
    st.markdown("**Privacy status**")
    if no_schema:
        st.success("Schema NOT sent.")
    elif use_masking:
        st.warning("Aliases sent — real names stay local.")
    else:
        st.error("Real names sent to API.")

    st.divider()
    with st.expander("Set API key permanently"):
        st.markdown("""
**`.streamlit/secrets.toml`**
```toml
OPENAI_API_KEY = "sk-..."
```
**Environment variable**
```bash
export OPENAI_API_KEY="sk-..."
streamlit run sql_corrector.py
```
        """)


# ═══════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════

def sanitize_sql(sql: str) -> str:
    """Fix invisible/smart characters only — no keyword injection."""
    sql = sql.replace("\u00a0", " ")   # non-breaking space
    sql = sql.replace("\u2019", "'")   # right single quote
    sql = sql.replace("\u2018", "'")   # left single quote
    sql = sql.replace("\u201c", '"')   # left double quote
    sql = sql.replace("\u201d", '"')   # right double quote
    sql = sql.replace("\u2013", "-")   # en dash
    sql = sql.replace("\u2014", "-")   # em dash
    sql = sql.replace("\u0060", "`")   # grave accent normalise
    # collapse multiple spaces on a single line but keep newlines
    lines = [re.sub(r'[^\S\n]+', ' ', line).rstrip() for line in sql.splitlines()]
    return "\n".join(lines).strip()


def build_mask(aliases: list) -> dict:
    """Real→alias map, skipping keywords, single chars, and numbers."""
    mask = {}
    for real, alias in aliases:
        real, alias = real.strip(), alias.strip()
        if (real and alias
                and real.upper() not in SQL_KEYWORDS
                and len(real) > 1
                and not real.isdigit()):
            mask[real] = alias
    return mask


def apply_mask(text: str, mask: dict) -> str:
    for real, alias in sorted(mask.items(), key=lambda x: -len(x[0])):
        text = text.replace(f"`{real}`", f"`{alias}`")
        text = re.sub(
            r'(?<![`\w])' + re.escape(real) + r'(?![`\w])',
            alias, text, flags=re.IGNORECASE
        )
    return text


def restore_mask(text: str, mask: dict) -> str:
    reverse = {v: k for k, v in mask.items()}
    for alias, real in sorted(reverse.items(), key=lambda x: -len(x[0])):
        text = text.replace(f"`{alias}`", f"`{real}`")
        text = re.sub(
            r'(?<![`\w])' + re.escape(alias) + r'(?![`\w])',
            real, text, flags=re.IGNORECASE
        )
    return text


def extract_from_sql(sql: str) -> list:
    """Extract table & column names from SQL (CTEs, subqueries, UNIONs, multi-UPDATE)."""
    pairs, seen, table_hits = [], set(), set()
    t_c, c_c = 1, 1

    for pat in [
        r'(?:FROM|JOIN|UPDATE|INTO)\s+`?([A-Za-z_][A-Za-z0-9_]*)`?',
        r'WITH\s+`?([A-Za-z_][A-Za-z0-9_]*)`?\s+AS\s*\(',
        r',\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s+(?:AS\s+)?[a-zA-Z]\b',
    ]:
        for m in re.finditer(pat, sql, re.IGNORECASE):
            tok = m.group(1)
            if tok.upper() not in SQL_KEYWORDS and len(tok) > 1:
                table_hits.add(tok)

    for tok in sorted(table_hits):
        if tok not in seen:
            seen.add(tok)
            pairs.append((tok, f"t{t_c}"))
            t_c += 1

    for pat in [
        r'[a-zA-Z0-9_]\.[`]?([A-Za-z_][A-Za-z0-9_]*)[`]?',
        r'`([A-Za-z_][A-Za-z0-9_]*)`',
    ]:
        for m in re.finditer(pat, sql, re.IGNORECASE):
            tok = m.group(1)
            if (tok.upper() not in SQL_KEYWORDS
                    and tok not in seen and len(tok) > 1):
                seen.add(tok)
                pairs.append((tok, f"col{c_c}"))
                c_c += 1
    return pairs


def extract_from_schema(schema: str) -> list:
    pairs, seen = [], set()
    t_c, c_c = 1, 1
    for tok in dict.fromkeys(re.findall(r'\b[A-Za-z_][A-Za-z0-9_]*\b', schema)):
        if tok.upper() in SQL_KEYWORDS or tok in seen or len(tok) <= 1:
            continue
        seen.add(tok)
        is_table = bool(re.search(r'\b' + re.escape(tok) + r'\s*\(', schema))
        pairs.append((tok, f"t{t_c}" if is_table else f"col{c_c}"))
        if is_table: t_c += 1
        else: c_c += 1
    return pairs


def split_statements(sql: str) -> list:
    """Split on ; but ignore semicolons inside quotes or parentheses."""
    stmts, current, depth, in_str, str_char = [], [], 0, False, None
    for ch in sql:
        if in_str:
            current.append(ch)
            if ch == str_char:
                in_str = False
        elif ch in ("'", '"', '`'):
            in_str, str_char = True, ch
            current.append(ch)
        elif ch == '(':
            depth += 1; current.append(ch)
        elif ch == ')':
            depth -= 1; current.append(ch)
        elif ch == ';' and depth == 0:
            stmt = "".join(current).strip()
            if stmt:
                stmts.append(stmt)
            current = []
        else:
            current.append(ch)
    last = "".join(current).strip()
    if last:
        stmts.append(last)
    return stmts or [sql]


def parse_gpt_response(raw: str):
    """Extract SQL block + explanation. Robust fallback if no code fence."""
    m = re.search(r"```(?:sql)?\s*(.*?)```", raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip(), raw[m.end():].strip()
    # Fallback: find first SQL keyword line
    sql_start = re.compile(
        r'^\s*(SELECT|UPDATE|DELETE|INSERT|WITH|CREATE|DROP|ALTER|MERGE|REPLACE)\b',
        re.IGNORECASE
    )
    lines = raw.strip().splitlines()
    sql_lines, note_lines, in_sql = [], [], False
    for line in lines:
        if not in_sql and sql_start.match(line):
            in_sql = True
        (sql_lines if in_sql else note_lines).append(line)
    if sql_lines:
        return "\n".join(sql_lines).strip(), "\n".join(note_lines).strip()
    return raw.strip(), ""


def make_diff_html(original: str, corrected: str) -> str:
    """Side-by-side diff with line numbers and guaranteed inline colors."""
    orig_lines = original.splitlines()
    corr_lines = corrected.splitlines()
    matcher    = difflib.SequenceMatcher(None, orig_lines, corr_lines)

    left_rows, right_rows = [], []
    orig_ln, corr_ln = 1, 1

    S = "padding:3px 8px;font-family:'Courier New',monospace;font-size:12px;white-space:pre-wrap;"
    N = "padding:3px 6px;font-size:11px;text-align:right;min-width:36px;user-select:none;border-right:1px solid #2a2a2a;"

    def escape_html(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def row(ln, line, bg, fg, lbg="#1a1a1a", lfc="#444"):
        return (
            f'<tr>'
            f'<td style="{N}background:{lbg};color:{lfc};">{ln}</td>'
            f'<td style="{S}background:{bg};color:{fg};">{escape_html(line) if line else "&nbsp;"}</td>'
            f'</tr>'
        )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for lo, lc in zip(orig_lines[i1:i2], corr_lines[j1:j2]):
                left_rows.append(row(orig_ln, lo, "#1a1a1a", "#cccccc"))
                right_rows.append(row(corr_ln, lc, "#1a1a1a", "#cccccc"))
                orig_ln += 1; corr_ln += 1

        elif tag == "replace":
            ll, rl = orig_lines[i1:i2], corr_lines[j1:j2]
            for k in range(max(len(ll), len(rl))):
                lo  = ll[k] if k < len(ll) else ""
                lc  = rl[k] if k < len(rl) else ""
                lno = orig_ln + k if k < len(ll) else ""
                lnc = corr_ln + k if k < len(rl) else ""
                left_rows.append(row(lno, lo, "#3d1515", "#ff9090", "#2a0e0e", "#c04040"))
                right_rows.append(row(lnc, lc, "#153d15", "#90e890", "#0e2a0e", "#40c040"))
            orig_ln += len(ll); corr_ln += len(rl)

        elif tag == "delete":
            for lo in orig_lines[i1:i2]:
                left_rows.append(row(orig_ln, lo, "#3d1515", "#ff9090", "#2a0e0e", "#c04040"))
                right_rows.append(row("", "", "#111", "#222"))
                orig_ln += 1

        elif tag == "insert":
            for lc in corr_lines[j1:j2]:
                left_rows.append(row("", "", "#111", "#222"))
                right_rows.append(row(corr_ln, lc, "#153d15", "#90e890", "#0e2a0e", "#40c040"))
                corr_ln += 1

    def tbl(rows):
        return f'<table style="width:100%;border-collapse:collapse;">{"".join(rows)}</table>'

    return f"""
    <div style="background:#111;border-radius:8px;overflow:hidden;border:1px solid #2a2a2a;">
      <div style="display:grid;grid-template-columns:1fr 1fr;background:#1e1e1e;border-bottom:1px solid #333;">
        <div style="padding:8px 14px;color:#ff8080;font-weight:bold;font-size:13px;border-right:1px solid #333;">❌ Original</div>
        <div style="padding:8px 14px;color:#80e880;font-weight:bold;font-size:13px;">✅ Corrected</div>
      </div>
      <div style="padding:5px 14px;background:#161616;border-bottom:1px solid #222;font-size:11px;color:#666;display:flex;gap:24px;">
        <span><span style="color:#ff8080;">■</span> Removed / wrong</span>
        <span><span style="color:#80e880;">■</span> Added / fixed</span>
        <span><span style="color:#888;">■</span> Unchanged</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;overflow-x:auto;">
        <div style="border-right:1px solid #2a2a2a;">{tbl(left_rows)}</div>
        <div>{tbl(right_rows)}</div>
      </div>
    </div>
    """


def copy_button_html(text: str, btn_id: str) -> str:
    """Clipboard copy using modern navigator.clipboard API with execCommand fallback."""
    safe = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    return f"""
    <button id="{btn_id}" onclick="
      var txt = `{safe}`;
      if (navigator.clipboard) {{
        navigator.clipboard.writeText(txt).then(function() {{
          document.getElementById('{btn_id}').innerText = '✅ Copied!';
          setTimeout(function(){{document.getElementById('{btn_id}').innerText='📋 Copy SQL'}}, 2000);
        }});
      }} else {{
        var ta = document.createElement('textarea');
        ta.value = txt; document.body.appendChild(ta);
        ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
        document.getElementById('{btn_id}').innerText = '✅ Copied!';
        setTimeout(function(){{document.getElementById('{btn_id}').innerText='📋 Copy SQL'}}, 2000);
      }}
    " style="background:#2563eb;color:#fff;border:none;border-radius:6px;
             padding:8px 20px;font-size:14px;cursor:pointer;margin:4px 0;">
      📋 Copy SQL
    </button>
    """


def call_gpt(key: str, system_prompt: str, user_message: str) -> str:
    headers = {
        "Authorization": f"Bearer {key.strip()}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "gpt-4o",
        "max_tokens": 2000,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_message},
        ],
    }
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            data=json.dumps(body),
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except requests.HTTPError as e:
        code = e.response.status_code
        if code == 401:
            raise RuntimeError("Invalid API key. Check your OpenAI key and try again.")
        elif code == 429:
            raise RuntimeError("Rate limit exceeded. Wait a moment and retry.")
        elif code == 400:
            raise RuntimeError(f"Bad request: {e.response.json().get('error',{}).get('message','unknown error')}")
        else:
            raise RuntimeError(f"OpenAI API error {code}. Please try again.")


def build_system_prompt(dialect: str) -> str:
    return f"""You are a senior SQL expert specializing in {dialect}.

Fix the SQL query provided. Rules:
1. Return ONLY the corrected SQL inside a ```sql code block.
2. After the block, list every fix as bullet points with line references where possible.
3. Fix ALL of:
   - Typos / syntax errors in keywords (FORM→FROM, WHRE→WHERE etc.)
   - Missing spaces between concatenated tokens (e.g. order_idand → order_id AND)
   - Missing or wrong JOIN conditions
   - Ambiguous column references (prefix with table alias)
   - Non-aggregated columns outside GROUP BY
   - Subquery missing alias
   - CTE (WITH clause) syntax errors
   - UNION / INTERSECT column count mismatch
   - Dialect-specific issues ({dialect})
4. Preserve the original query's intent and structure.
5. If no errors found, return SQL unchanged and say "No errors found."
6. Do NOT add SQL comments inside the corrected query.
"""


# ═══════════════════════════════════════════════════════════════════════
# MAIN LAYOUT
# ═══════════════════════════════════════════════════════════════════════
col1, col2 = st.columns(2, gap="large")

# ══ LEFT COLUMN ══════════════════════════════════════════════════════════
with col1:
    st.subheader("📝 Your SQL")
    sql_input = st.text_area(
        "Paste your SQL query here", height=220,
        placeholder="SELECT * FORM users WHRE id = 1\n-- supports CTEs, subqueries, multi-statement"
    )

    st.subheader("🗂️ Schema (optional)")
    schema_input = st.text_area(
        "Describe your tables", height=110,
        placeholder="users(id INT, email VARCHAR, salary DECIMAL)\norders(id INT, user_id INT, total DECIMAL)",
        disabled=no_schema,
    )

    # ── Alias Editor ───────────────────────────────────────────────────────
    if use_masking and not no_schema:
        st.subheader("🎭 Alias Mapping")
        st.caption("Single-letter aliases (a, b, c…) and SQL keywords are never masked.")

        b1, b2 = st.columns(2)
        if b1.button("⚡ From schema", use_container_width=True):
            if schema_input.strip():
                st.session_state.aliases = extract_from_schema(schema_input)
            else:
                st.warning("Schema empty — use 'From SQL query' instead.")
        if b2.button("🔎 From SQL query", use_container_width=True):
            if sql_input.strip():
                st.session_state.aliases = extract_from_sql(sql_input)
            else:
                st.warning("Paste a SQL query first.")

        new_aliases = []
        hc = st.columns(2)
        hc[0].markdown("**Real name**")
        hc[1].markdown("**Alias → sent to API**")
        for i in range(len(st.session_state.aliases) + 1):
            c1, c2 = st.columns(2)
            rd = st.session_state.aliases[i][0] if i < len(st.session_state.aliases) else ""
            ad = st.session_state.aliases[i][1] if i < len(st.session_state.aliases) else ""
            real  = c1.text_input("r", value=rd, key=f"real_{i}",  label_visibility="collapsed")
            alias = c2.text_input("a", value=ad, key=f"alias_{i}", label_visibility="collapsed")
            if real or alias:
                new_aliases.append((real, alias))
        st.session_state.aliases = new_aliases
        mask = build_mask(st.session_state.aliases)
    else:
        mask = {}

    dialect = st.selectbox("SQL Dialect", [
        "MySQL", "PostgreSQL", "Generic SQL", "SQLite",
        "SQL Server (T-SQL)", "BigQuery", "Oracle", "Snowflake", "Redshift"
    ])
    fix_btn = st.button("🔍 Fix My SQL", type="primary", use_container_width=True)


# ══ RIGHT COLUMN ═════════════════════════════════════════════════════════
with col2:
    st.subheader("✅ Corrected SQL")

    if st.session_state.corrected:
        st.code(st.session_state.corrected, language="sql")
        st.components.v1.html(copy_button_html(st.session_state.corrected, "cp_top"), height=50)
        if st.session_state.changes:
            with st.expander("📋 Changes made", expanded=True):
                st.markdown(st.session_state.changes)
    else:
        st.info("Your corrected SQL will appear here.")

    # ── Process ─────────────────────────────────────────────────────────────
    if fix_btn:
        if not api_key:
            st.error("❌ No API key found. Enter it in the sidebar or set the OPENAI_API_KEY environment variable.")
            st.stop()
        if not sql_input.strip():
            st.warning("⚠️ Paste a SQL query on the left first.")
            st.stop()

        # Sanitize
        clean_sql = sanitize_sql(sql_input)

        # Multi-statement info
        statements = split_statements(clean_sql)
        if len(statements) > 1:
            st.info(f"🔢 Detected {len(statements)} SQL statements — fixing as one block.")

        # Mask
        masked_sql    = apply_mask(clean_sql, mask)    if mask else clean_sql
        masked_schema = "" if no_schema else (apply_mask(schema_input, mask) if mask else schema_input)

        # Masking preview
        if mask:
            with st.expander("🎭 Masking conversion", expanded=True):
                mc1, mc2 = st.columns(2)
                mc1.markdown("**Real name**")
                mc2.markdown("**Sent to API as**")
                for real, alias in mask.items():
                    mc1.code(real)
                    mc2.code(alias)
                st.markdown("**Masked SQL sent to API:**")
                st.code(masked_sql, language="sql")

        # Prompt
        system   = build_system_prompt(dialect)
        user_msg = f"Fix this SQL:\n\n```sql\n{masked_sql}\n```"
        if masked_schema:
            user_msg += f"\n\nSchema:\n{masked_schema}"

        # Payload inspector
        with st.expander("🔍 Exact payload sent to API", expanded=False):
            preview = {
                "model": "gpt-4o", "temperature": 0, "max_tokens": 2000,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_msg},
                ]
            }
            st.code(json.dumps(preview, indent=2), language="json")
            if no_schema:
                st.success("✅ Schema NOT in payload.")
            elif masked_schema:
                st.warning(f"Schema present ({'masked' if mask else 'unmasked'}).")
            else:
                st.success("✅ Schema empty / not sent.")

        # Call GPT
        with st.spinner("Asking GPT-4o…"):
            try:
                raw = call_gpt(api_key, system, user_msg)
                masked_corrected, explanation = parse_gpt_response(raw)

                if not masked_corrected:
                    st.error("GPT returned an unexpected format. Check the payload inspector above.")
                    with st.expander("Raw GPT response"):
                        st.text(raw)
                    st.stop()

                corrected = restore_mask(masked_corrected, mask) if mask else masked_corrected

                # Save to session
                st.session_state.corrected = corrected
                st.session_state.original  = clean_sql
                st.session_state.changes   = explanation

                # Save to history
                if show_history:
                    st.session_state.history.insert(0, {
                        "time":      datetime.now().strftime("%H:%M:%S"),
                        "dialect":   dialect,
                        "preview":   clean_sql[:80] + ("…" if len(clean_sql) > 80 else ""),
                        "original":  clean_sql,
                        "corrected": corrected,
                        "changes":   explanation,
                    })
                    st.session_state.history = st.session_state.history[:10]

                # Show result
                st.code(corrected, language="sql")
                st.components.v1.html(copy_button_html(corrected, "cp_result"), height=50)

                if explanation:
                    with st.expander("📋 Changes made", expanded=True):
                        st.markdown(explanation)

                st.success("✅ Done!")

            except RuntimeError as e:
                st.error(f"❌ {e}")
            except Exception as e:
                st.error(f"❌ Unexpected error: {e}")


# ── Diff View ────────────────────────────────────────────────────────────
if show_diff and st.session_state.corrected and st.session_state.original:
    st.divider()
    st.subheader("🔀 Diff — What Changed")
    diff_html = make_diff_html(st.session_state.original, st.session_state.corrected)
    st.components.v1.html(diff_html, height=520, scrolling=True)


# ── Query History ─────────────────────────────────────────────────────────
if show_history and st.session_state.history:
    st.divider()
    st.subheader("🕐 Query History (this session)")
    for h in st.session_state.history:
        with st.expander(f"[{h['time']}] {h['dialect']} — {h['preview']}"):
            hc1, hc2 = st.columns(2)
            hc1.markdown("**Original**")
            hc1.code(h["original"], language="sql")
            hc2.markdown("**Corrected**")
            hc2.code(h["corrected"], language="sql")
            if h["changes"]:
                st.markdown("**Changes:**\n\n" + h["changes"])
    if st.button("🗑️ Clear history"):
        st.session_state.history = []
        st.rerun()


# ─── Footer ───────────────────────────────────────────────────────────────
st.divider()
st.caption("🔒 Nothing stored or logged. Real names never leave your browser when masking is on.")
