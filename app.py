import asyncio
import io

import pandas as pd
import streamlit as st

from checker import DataForSEOChecker, SerpAPIChecker

st.set_page_config(
    page_title="URL Indexing Checker",
    layout="wide",
)

st.title("URL Indexing Checker")
st.caption("Перевірка індексації сторінок у Google через оператор site:")

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Налаштування API")

    provider = st.selectbox(
        "Провайдер",
        ["DataForSEO", "SerpAPI"],
        help="DataForSEO — ~$0.002/запит. SerpAPI — від $50/міс за 5 000 запитів.",
    )

    if provider == "DataForSEO":
        default_login    = st.secrets.get("DATAFORSEO_LOGIN", "").strip()
        default_password = st.secrets.get("DATAFORSEO_PASSWORD", "").strip()
        if default_login and default_password:
            st.success("API ключ підключено з секретів")
            api_login    = default_login
            api_password = default_password
        else:
            api_login    = st.text_input("Login", type="password")
            api_password = st.text_input("Password", type="password")
        credentials_ok = bool(api_login and api_password)
    else:
        default_key = st.secrets.get("SERPAPI_KEY", "")
        if default_key:
            st.success("API ключ підключено з секретів")
            api_key = default_key
        else:
            api_key = st.text_input("API Key", type="password")
        credentials_ok = bool(api_key)

    concurrency = st.slider(
        "Паралельних запитів",
        min_value=1, max_value=20, value=5,
        help="Більше — швидше, але вищий ризик rate limit.",
    )

    if provider == "DataForSEO":
        st.divider()
        st.caption("Реєстрація: dataforseo.com")
    else:
        st.divider()
        st.caption("Реєстрація: serpapi.com")

# ── Input ─────────────────────────────────────────────────────────────────────
st.subheader("Список URL для перевірки")

input_method = st.radio("Спосіб введення", ["Текстове поле", "CSV / TXT файл"], horizontal=True)

urls: list[str] = []

if input_method == "Текстове поле":
    raw = st.text_area(
        "По одному URL на рядок",
        height=250,
        placeholder="https://donor-site.com/page-with-my-link\nhttps://another-donor.com/article",
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
            col_name = st.selectbox("Колонка з URL", df_upload.columns, index=list(df_upload.columns).index(default_col))
            urls = df_upload[col_name].dropna().astype(str).tolist()
        else:
            content = uploaded.read().decode("utf-8")
            urls = [u.strip() for u in content.splitlines() if u.strip()]

# ── Info strip ────────────────────────────────────────────────────────────────
if urls:
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("URL до перевірки", len(urls))
    if provider == "DataForSEO":
        col_b.metric("Орієнтовна вартість", f"~${len(urls) * 0.002:.2f}")
    else:
        col_b.metric("Запитів SerpAPI", len(urls))
    col_c.metric("Паралельних потоків", concurrency)

st.divider()

# ── Run ───────────────────────────────────────────────────────────────────────
run_disabled = not urls or not credentials_ok
if not credentials_ok and urls:
    st.warning("Введіть API-ключі у бічній панелі.")

if st.button("Перевірити індексацію", type="primary", disabled=run_disabled, use_container_width=True):

    progress_bar = st.progress(0.0)
    status_placeholder = st.empty()

    def on_progress(done: int, total: int):
        progress_bar.progress(done / total)
        status_placeholder.text(f"Перевірено {done} / {total}...")

    if provider == "DataForSEO":
        checker = DataForSEOChecker(api_login, api_password, concurrency)
    else:
        checker = SerpAPIChecker(api_key, concurrency)

    try:
        results = asyncio.run(checker.check_urls(urls, on_progress))
    except RuntimeError:
        # Fallback for environments where event loop already exists
        import nest_asyncio
        nest_asyncio.apply()
        loop = asyncio.get_event_loop()
        results = loop.run_until_complete(checker.check_urls(urls, on_progress))

    progress_bar.progress(1.0)
    status_placeholder.empty()

    # ── Summary ───────────────────────────────────────────────────────────────
    indexed_count  = sum(1 for r in results if r.indexed is True)
    not_indexed    = sum(1 for r in results if r.indexed is False)
    error_count    = sum(1 for r in results if r.error)

    m1, m2, m3 = st.columns(3)
    m1.metric("В індексі",     indexed_count)
    m2.metric("Не в індексі",  not_indexed)
    m3.metric("Помилки",       error_count)

    # ── Build result DataFrame ─────────────────────────────────────────────────
    def status_label(r):
        if r.error:
            return f"Помилка: {r.error}"
        return "в індексі" if r.indexed else "не в індексі"

    df_results = pd.DataFrame({
        "URL":    [r.url    for r in results],
        "Статус": [status_label(r) for r in results],
    })

    # ── Filter & display ───────────────────────────────────────────────────────
    filter_opt = st.radio(
        "Показати",
        ["Всі", "в індексі", "не в індексі", "Помилки"],
        horizontal=True,
    )

    if filter_opt == "в індексі":
        display_df = df_results[df_results["Статус"] == "в індексі"]
    elif filter_opt == "не в індексі":
        display_df = df_results[df_results["Статус"] == "не в індексі"]
    elif filter_opt == "Помилки":
        display_df = df_results[df_results["Статус"].str.startswith("Помилка")]
    else:
        display_df = df_results

    st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

    # ── Export to Excel ────────────────────────────────────────────────────────
    excel_buffer = io.BytesIO()
    with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
        df_results.to_excel(writer, index=False, sheet_name="Indexing")

        # Auto-width columns
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
