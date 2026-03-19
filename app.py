import asyncio
import io
import base64

import pandas as pd
import requests
import streamlit as st

from checker import DataForSEOChecker, SerpAPIChecker
from page_checker import check_pages

st.set_page_config(page_title="URL Indexing Checker", layout="wide")

st.title("URL Indexing Checker")
st.caption("Перевірка індексації, HTTP статусу, noindex та nofollow")

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
        secret_login    = st.secrets.get("DATAFORSEO_LOGIN", "").encode("ascii", "ignore").decode().strip()
        secret_password = st.secrets.get("DATAFORSEO_PASSWORD", "").encode("ascii", "ignore").decode().strip()

        if secret_login and secret_password:
            api_login    = secret_login
            api_password = secret_password
            st.success("API credentials з секретів")
        else:
            api_login    = st.text_input("Login",    value=st.session_state.api_login,    type="password")
            api_password = st.text_input("Password", value=st.session_state.api_password, type="password")
        credentials_ok = bool(api_login and api_password)

        if st.button("Тест з'єднання", disabled=not credentials_ok):
            creds = base64.b64encode(f"{api_login}:{api_password}".encode()).decode()
            try:
                resp = requests.get(
                    "https://api.dataforseo.com/v3/appendix/user_data",
                    headers={"Authorization": f"Basic {creds}"},
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

    st.divider()
    check_page_meta = st.toggle("Перевіряти HTTP / Noindex / Nofollow", value=True)
    target_domain = st.text_input(
        "Ваш домен (для nofollow)",
        placeholder="mysite.com",
        help="Парсер знайде всі посилання на ваш домен і перевірить rel атрибут. Якщо не вказати — покаже тільки page-level nofollow.",
    )

    st.divider()
    st.caption("dataforseo.com" if provider == "DataForSEO" else "serpapi.com")

concurrency = 5
URL_LIMIT = 500

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
st.caption(f"Максимум {URL_LIMIT} URL за один запуск.")

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

# ── Deduplicate URLs ──────────────────────────────────────────────────────────
if urls:
    unique_urls = list(dict.fromkeys(urls))
    removed = len(urls) - len(unique_urls)
    if removed > 0:
        st.info(f"Знайдено {removed} дублікатів — видалено. Залишилось {len(unique_urls)} унікальних URL.")
    urls = unique_urls

# ── Info strip ────────────────────────────────────────────────────────────────
if urls:
    if len(urls) > URL_LIMIT:
        st.error(f"Занадто багато URL: {len(urls)}. Максимум — {URL_LIMIT} за один запуск. Скоротіть список.")
        urls = []
    else:
        estimated_cost = len(urls) * 0.002
        col_a, col_b = st.columns(2)
        col_a.metric("URL до перевірки", len(urls))
        if provider == "DataForSEO":
            col_b.metric("Орієнтовна вартість", f"~${estimated_cost:.2f}")
        else:
            col_b.metric("Запитів", len(urls))

st.divider()

# ── Run ───────────────────────────────────────────────────────────────────────
if not credentials_ok and urls:
    st.warning("Введіть API credentials у бічній панелі.")

if st.button("Перевірити", type="primary", disabled=(not urls or not credentials_ok), use_container_width=True):

    # — Balance check (DataForSEO only) —
    if provider == "DataForSEO":
        try:
            creds = base64.b64encode(f"{active_login}:{active_password}".encode()).decode()
            resp_balance = requests.get(
                "https://api.dataforseo.com/v3/appendix/user_data",
                headers={"Authorization": f"Basic {creds}"},
                timeout=10,
            )
            balance_data = resp_balance.json()
            balance = (
                ((balance_data.get("tasks") or [{}])[0].get("result") or [{}])[0]
                .get("money", {}).get("balance", None)
            )
            estimated_cost = len(urls) * 0.002
            if balance is not None:
                if balance < estimated_cost:
                    st.warning(f"Увага: баланс ${balance:.2f}, а запуск коштує ~${estimated_cost:.2f}. Частина URL може не перевіритись.")
                else:
                    st.caption(f"Баланс: ${balance:.2f} / Вартість запуску: ~${estimated_cost:.2f}")
        except Exception:
            pass  # не блокуємо запуск якщо перевірка балансу не вдалась

    # — Indexing check —
    st.write("**Крок 1/2:** Перевірка індексації...")
    progress_bar       = st.progress(0.0)
    status_placeholder = st.empty()

    def on_progress(done: int, total: int):
        progress_bar.progress(done / total)
        status_placeholder.text(f"Індексація: {done} / {total}...")

    if provider == "DataForSEO":
        checker = DataForSEOChecker(active_login, active_password, concurrency)
    else:
        checker = SerpAPIChecker(active_key, concurrency)

    try:
        index_results = asyncio.run(checker.check_urls(urls, on_progress))
    except RuntimeError:
        import nest_asyncio
        nest_asyncio.apply()
        loop = asyncio.get_event_loop()
        index_results = loop.run_until_complete(checker.check_urls(urls, on_progress))

    progress_bar.progress(1.0)
    status_placeholder.empty()

    # — Page meta check —
    page_results_map = {}
    if check_page_meta:
        st.write("**Крок 2/2:** Перевірка HTTP / Noindex / Nofollow...")
        progress_bar2      = st.progress(0.0)
        status_placeholder2 = st.empty()

        def on_progress2(done: int, total: int):
            progress_bar2.progress(done / total)
            status_placeholder2.text(f"Сторінки: {done} / {total}...")

        try:
            page_results = asyncio.run(check_pages(urls, target_domain.strip(), concurrency, on_progress2))
        except RuntimeError:
            import nest_asyncio
            nest_asyncio.apply()
            loop = asyncio.get_event_loop()
            page_results = loop.run_until_complete(check_pages(urls, target_domain.strip(), concurrency, on_progress2))

        progress_bar2.progress(1.0)
        status_placeholder2.empty()
        page_results_map = {r.url: r for r in page_results}

    # — Summary metrics —
    indexed_count = sum(1 for r in index_results if r.indexed is True)
    not_indexed   = sum(1 for r in index_results if r.indexed is False)
    error_count   = sum(1 for r in index_results if r.error)

    m1, m2, m3 = st.columns(3)
    m1.metric("В індексі",    indexed_count)
    m2.metric("Не в індексі", not_indexed)
    m3.metric("Помилки",      error_count)

    # — Build DataFrame —
    def index_label(r):
        if r.error:
            return f"Помилка: {r.error}"
        return "в індексі" if r.indexed else "не в індексі"

    rows = []
    for r in index_results:
        row = {"URL": r.url, "Індексація": index_label(r)}
        if check_page_meta and r.url in page_results_map:
            pr = page_results_map[r.url]
            row["HTTP статус"] = str(pr.http_status) if pr.http_status else f"Помилка: {pr.error}"
            row["Noindex"]  = "так" if pr.noindex else ("ні" if pr.noindex is False else "—")
            row["Тип посилання"] = pr.nofollow or "—"
        rows.append(row)

    df_results = pd.DataFrame(rows)

    # — Filter & display —
    filter_opt = st.radio("Показати", ["Всі", "в індексі", "не в індексі", "Помилки"], horizontal=True)

    if filter_opt == "в індексі":
        display_df = df_results[df_results["Індексація"] == "в індексі"]
    elif filter_opt == "не в індексі":
        display_df = df_results[df_results["Індексація"] == "не в індексі"]
    elif filter_opt == "Помилки":
        display_df = df_results[df_results["Індексація"].str.startswith("Помилка")]
    else:
        display_df = df_results

    st.dataframe(display_df, use_container_width=True, hide_index=True, height=400)

    # — Export Excel —
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
