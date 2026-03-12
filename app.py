import asyncio
import io
import base64

import pandas as pd
import requests
import streamlit as st

from checker import DataForSEOChecker, SerpAPIChecker

st.set_page_config(page_title="URL Indexing Checker", layout="wide")

st.title("URL Indexing Checker")
st.caption("Перевірка індексації сторінок у Google через оператор site:")

# ── Session state init ────────────────────────────────────────────────────────
if "api_login"    not in st.session_state: st.session_state.api_login    = ""
if "api_password" not in st.session_state: st.session_state.api_password = ""
if "api_key"      not in st.session_state: st.session_state.api_key      = ""
if "verified"     not in st.session_state: st.session_state.verified     = False

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Налаштування API")

    provider = st.selectbox(
        "Провайдер",
        ["DataForSEO", "SerpAPI"],
        help="DataForSEO — ~$0.002/запит. SerpAPI — від $50/міс за 5 000 запитів.",
    )

    if provider == "DataForSEO":
        api_login = st.text_input(
            "Login", value=st.session_state.api_login, type="password"
        )
        api_password = st.text_input(
            "Password", value=st.session_state.api_password, type="password"
        )
        credentials_ok = bool(api_login and api_password)

        if st.button("Тест з'єднання", disabled=not credentials_ok):
            creds = base64.b64encode(f"{api_login}:{api_password}".encode()).decode()
            try:
                resp = requests.post(
                    "https://api.dataforseo.com/v3/serp/google/organic/live/regular",
                    headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
                    json=[{"keyword": "site:google.com", "location_code": 2840, "language_code": "en", "depth": 1}],
                    timeout=15,
                )
                data = resp.json()
                if data.get("status_code") == 20000:
                    st.session_state.api_login    = api_login
                    st.session_state.api_password = api_password
                    st.session_state.verified     = True
                    st.success("З'єднання OK!")
                else:
                    st.session_state.verified = False
                    st.error(f"Помилка {data.get('status_code')}: {data.get('status_message')}")
            except Exception as e:
                st.error(f"Помилка: {e}")

        if st.session_state.verified:
            st.success("Credentials збережено в сесії")

    else:
        api_key = st.text_input("API Key", value=st.session_state.api_key, type="password")
        credentials_ok = bool(api_key)
        if api_key:
            st.session_state.api_key = api_key

    concurrency = st.slider("Паралельних запитів", 1, 20, 5)

    st.divider()
    st.caption("dataforseo.com" if provider == "DataForSEO" else "serpapi.com")

# ── Resolve active credentials ────────────────────────────────────────────────
if provider == "DataForSEO":
    active_login    = api_login
    active_password = api_password
    credentials_ok  = bool(active_login and active_password)
else:
    active_key     = api_key
    credentials_ok = bool(active_key)

# ── Input ─────────────────────────────────────────────────────────────────────
st.subheader("Список URL для перевірки")

input_method = st.radio("Спосіб введення", ["Текстове поле", "CSV / TXT файл"], horizontal=True)

urls: list[str] = []

if input_method == "Текстове поле":
    raw = st.text_area(
        "По одному URL на рядок", height=250,
        placeholder="https://donor-site.com/page\nhttps://another-donor.com/article",
    )
    if raw:
        urls = [u.strip() for u in raw.splitlines() if u.strip()]
else:
    uploaded = st.file_uploader("CSV або TXT файл", type=["csv", "txt"])
    if uploaded:
        if uploaded.name.endswith(".csv"):
            df_upload = pd.read_csv(uploaded)
            url_cols = [c for c in df_upload.columns if "url" in c.lower() or "link" in c.lower()]
            default_col = url_cols[0] if url_cols else df_upload.columns[0]
            col_name = st.selectbox("Колонка з URL", df_upload.columns,
                                    index=list(df_upload.columns).index(default_col))
            urls = df_upload[col_name].dropna().astype(str).tolist()
        else:
            content = uploaded.read().decode("utf-8")
            urls = [u.strip() for u in content.splitlines() if u.strip()]

# ── Info strip ────────────────────────────────────────────────────────────────
if urls:
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("URL до перевірки", len(urls))
    col_b.metric("Орієнтовна вартість", f"~${len(urls) * 0.002:.2f}" if provider == "DataForSEO" else f"{len(urls)} запитів")
    col_c.metric("Паралельних потоків", concurrency)

st.divider()

# ── Run ───────────────────────────────────────────────────────────────────────
if not credentials_ok and urls:
    st.warning("Введіть API credentials у бічній панелі.")

if st.button("Перевірити індексацію", type="primary",
             disabled=(not urls or not credentials_ok), use_container_width=True):

    progress_bar       = st.progress(0.0)
    status_placeholder = st.empty()

    def on_progress(done: int, total: int):
        progress_bar.progress(done / total)
        status_placeholder.text(f"Перевірено {done} / {total}...")

    if provider == "DataForSEO":
        checker = DataForSEOChecker(active_login, active_password, concurrency)
    else:
        checker = SerpAPIChecker(active_key, concurrency)

    try:
        results = asyncio.run(checker.check_urls(urls, on_progress))
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(checker.check_urls(urls, on_progress))

    progress_bar.progress(1.0)
    status_placeholder.empty()

    indexed_count = sum(1 for r in results if r.indexed is True)
    not_indexed   = sum(1 for r in results if r.indexed is False)
    error_count   = sum(1 for r in results if r.error)

    m1, m2, m3 = st.columns(3)
    m1.metric("В індексі",    indexed_count)
    m2.metric("Не в індексі", not_indexed)
    m3.metric("Помилки",      error_count)

    def status_label(r):
        if r.error:
            return f"Помилка: {r.error}"
        return "в індексі" if r.indexed else "не в індексі"

    df_results = pd.DataFrame({
        "URL":    [r.url         for r in results],
        "Статус": [status_label(r) for r in results],
    })

    filter_opt = st.radio("Показати", ["Всі", "в індексі", "не в індексі", "Помилки"], horizontal=True)

    if filter_opt == "в індексі":
        display_df = df_results[df_results["Статус"] == "в індексі"]
    elif filter_opt == "не в індексі":
        display_df = df_results[df_results["Статус"] == "не в індексі"]
    elif filter_opt == "Помилки":
        display_df = df_results[df_results["Статус"].str.startswith("Помилка")]
    else:
        display_df = df_results

    st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df_results.to_excel(writer, index=False, sheet_name="Indexing")
        ws = writer.sheets["Indexing"]
        for col_cells in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col_cells)
            ws.column_dimensions[col_cells[0].column_letter].width = min(max_len + 4, 80)

    st.download_button(
        label="Скачати Excel",
        data=excel_buffer.getvalue(),
        file_name="indexing_results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )
