"""Plain-HTML paginated table helper.

st.dataframe renders through glide-data-grid, a canvas + ResizeObserver
component whose auto-sizing got stuck permanently unmeasurable (52px wide,
zero canvases mounted) during one browser-automation audit session -- see
DECISIONS.md. st.table renders a static HTML <table>: no canvas, no
ResizeObserver, immune to that failure mode by construction. Pagination
keeps each page a manageable size to scan, since st.table has none of
st.dataframe's built-in row virtualization for the wider tables (Service
tab's per-outlet breakdown, the full matched-SKU list).

Trade-off: st.table has no built-in search/sort/fullscreen, so this drops
those relative to st.dataframe. A manual "Download as CSV" button (of the
FULL, unpaginated data) replaces the one st.dataframe provided natively.
"""
import math

import pandas as pd
import streamlit as st


def paginated_table(df, formats=None, page_size=15, key="table"):
    """Render df as a paginated plain-HTML table.

    formats: optional dict of {column: (display_label, printf_format)}.
    Either element of the tuple may be None to skip that transform
    (keep the original column label, or leave values unformatted).
    """
    if df is None or len(df) == 0:
        st.caption("No rows.")
        return

    n = len(df)
    n_pages = max(1, math.ceil(n / page_size))
    if n_pages > 1:
        page = st.number_input("Page", min_value=1, max_value=n_pages, value=1, step=1,
                                key=f"{key}_page")
    else:
        page = 1

    start = (page - 1) * page_size
    view = df.iloc[start:start + page_size].reset_index(drop=True).copy()
    formats = formats or {}
    numeric_cols = set(view.select_dtypes(include="number").columns)

    # st.table falls back to pandas' default float display (four decimals,
    # thousands separators) for any numeric column with no explicit format --
    # "106,578.0000" for a whole-number eaches count. Give every unformatted
    # numeric column a sane default instead of leaving that to chance.
    for col in numeric_cols:
        if col in formats:
            continue
        non_null = view[col].dropna()
        whole = (non_null % 1 == 0).all() if len(non_null) else True
        view[col] = view[col].map(lambda v: "" if pd.isna(v) else (f"{v:,.0f}" if whole else f"{v:,.2f}"))

    rename = {}
    for col, (label, fmt) in formats.items():
        if col not in view.columns:
            continue
        if fmt:
            view[col] = view[col].map(lambda v, f=fmt: (f % v) if pd.notna(v) else "")
        if label:
            rename[col] = label
    view = view.rename(columns=rename)

    # A Styler (needed to hide the index / right-align numeric columns
    # cleanly) requires jinja2>=3, and this environment's jinja2 is 2.11.2 --
    # pandas raises ImportError on .style with no fallback. The pandas index
    # column (a meaningless per-page 0/1/2.. that CSS alone can hide, unlike
    # per-column alignment) is dropped via app.py's CSS instead; see
    # `th.blank, th.row_heading { display: none }` there.
    st.table(view)
    if n_pages > 1:
        st.caption(f"Page {page} of {n_pages} -- {n:,} rows total.")

    st.download_button("Download as CSV", df.to_csv(index=False).encode("utf-8"),
                        file_name=f"{key}.csv", mime="text/csv", key=f"{key}_dl")
