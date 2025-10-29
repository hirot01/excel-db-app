import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
import re

st.set_page_config(page_title="Excel DB App (Flexible Mapping)", page_icon="🧭", layout="wide")

DATA_FILE = Path("data.xlsx")
SHEET_NAME = "items"
TARGET_FIELDS = ["id", "name", "category", "quantity", "updated_at"]

def guess_mapping(cols):
    """Try to guess mapping for common Japanese/English headers."""
    candidates = {
        "id": ["id", "no", "番号", "管理id", "識別子"],
        "name": ["name", "商品名", "名称", "品名", "タイトル", "件名"],
        "category": ["category", "カテゴリ", "区分", "分類"],
        "quantity": ["quantity", "qty", "在庫", "数量", "個数"],
        "updated_at": ["updated_at", "更新日時", "更新日", "最終更新", "更新"]
    }
    mapping = {k: None for k in TARGET_FIELDS}
    for field, keys in candidates.items():
        for c in cols:
            if any(k.lower() in str(c).lower() for k in keys):
                mapping[field] = c
                break
    return mapping

@st.cache_data
def load_items(path: Path, sheet: str):
    if not path.exists():
        return pd.DataFrame(columns=TARGET_FIELDS)
    df = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
    for col in TARGET_FIELDS:
        if col not in df.columns:
            df[col] = None
    return df

def save_items(df: pd.DataFrame, path: Path, sheet: str):
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet, index=False)

def normalize_df(df: pd.DataFrame, mapping: dict):
    out = pd.DataFrame(columns=TARGET_FIELDS)
    for tgt in TARGET_FIELDS:
        src = mapping.get(tgt)
        if src and src in df.columns:
            out[tgt] = df[src]
        else:
            out[tgt] = None

    if out["id"].isna().all():
        out["id"] = range(1, len(out) + 1)
    out["quantity"] = pd.to_numeric(out["quantity"], errors="coerce").fillna(0).astype(int)
    out["updated_at"] = pd.to_datetime(out["updated_at"], errors="coerce").fillna(datetime.now())
    return out

st.title("🧭 Excel DB App — 列名ちがってもOK！")

st.sidebar.header("⚙️ 設定")
uploaded = st.sidebar.file_uploader("既存Excelをアップロード（任意）", type=["xlsx"], accept_multiple_files=False)

if uploaded:
    try:
        xls = pd.ExcelFile(uploaded, engine="openpyxl")
        sheet = st.sidebar.selectbox("読み込むシート", options=xls.sheet_names, index=0)
        df_raw = pd.read_excel(xls, sheet_name=sheet, engine="openpyxl")
        st.success(f"シート '{sheet}' を読み込みました。列数: {len(df_raw.columns)} 行数: {len(df_raw)}")

        with st.expander("🔎 生データの先頭を確認"):
            st.dataframe(df_raw.head(10))

        st.subheader("🔁 列の対応付け（Mapping）")
        guessed = guess_mapping(list(df_raw.columns))
        cols = [None] + list(df_raw.columns)
        mapping = {}
        for tgt in TARGET_FIELDS:
            mapping[tgt] = st.selectbox(f"{tgt}", options=cols, index=(cols.index(guessed[tgt]) if guessed[tgt] in cols else 0))

        if st.button("✅ この対応で取り込む（data.xlsxに保存）"):
            df_norm = normalize_df(df_raw, mapping)
            save_items(df_norm, DATA_FILE, SHEET_NAME)
            st.success("取り込み＆保存が完了しました。")
            st.cache_data.clear()

    except Exception as e:
        st.error(f"読み込みでエラー：{e}")

items = load_items(DATA_FILE, SHEET_NAME)

tab1, tab2 = st.tabs(["📃 一覧", "➕ 新規追加"])

with tab1:
    st.subheader("レコード一覧")
    st.dataframe(items, use_container_width=True)

with tab2:
    st.subheader("新規追加")
    with st.form("new"):
        name = st.text_input("name")
        category = st.text_input("category")
        quantity = st.number_input("quantity", min_value=0, step=1)
        submit = st.form_submit_button("追加")
        if submit:
            new_id = items["id"].max() + 1 if not items.empty else 1
            new_row = pd.DataFrame([{
                "id": new_id,
                "name": name,
                "category": category,
                "quantity": quantity,
                "updated_at": datetime.now()
            }])
            df2 = pd.concat([items, new_row], ignore_index=True)
            save_items(df2, DATA_FILE, SHEET_NAME)
            st.success("追加しました！")
