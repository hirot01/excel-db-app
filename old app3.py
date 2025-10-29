import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path

st.set_page_config(page_title="Excel DB App (Style-aware)", page_icon="🍶", layout="wide")

DATA_FILE = Path("data.xlsx")
# SHEET_NAME = "items"

# 基本スキーマ（アプリで必須）
CORE_FIELDS = ["id", "name", "category", "quantity", "updated_at"]
# 追加で保持・表示したい列（任意）
EXTRA_FIELDS = ["会員氏名", "蔵元", "地域", "精米歩合", "備考", "例会", "例会日時"]
TARGET_FIELDS = CORE_FIELDS + EXTRA_FIELDS

# 日本酒の“種別”候補（列名として来る想定）
STYLE_CANDIDATES = [
    "本醸造", "特別本醸造", "純米", "特別純米", "吟醸", "純米吟醸", "大吟醸", "純米大吟醸", "その他"
]

def guess_mapping(cols):
    """列名の自動推測（ゆるめ）"""
    s = [str(c) for c in cols]
    def find(keys):
        for c in s:
            lc = c.lower()
            for k in keys:
                if k.lower() in lc:
                    return c
        return None

    mapping = {k: None for k in CORE_FIELDS + EXTRA_FIELDS}

    # name
    mapping["name"] = find(["銘柄", "商品名", "名称", "品名", "name"])
    # updated_at
    mapping["updated_at"] = find(["例会日時", "更新日", "更新日時", "updated_at"])
    # category（未設定なら後で“種別”から自動抽出）
    mapping["category"] = find(["カテゴリ", "区分", "分類", "category"])
    # id
    mapping["id"] = find(["id", "番号", "no"])
    # quantity
    mapping["quantity"] = find(["数量", "在庫", "qty", "quantity"])

    # extras
    mapping["会員氏名"] = find(["会員氏名", "氏名", "名前"])
    mapping["蔵元"]   = find(["蔵元", "メーカー", "酒造"])
    mapping["地域"]   = find(["地域", "都道府県", "エリア"])
    mapping["精米歩合"] = find(["精米歩合", "精米", "歩合"])
    mapping["備考"]   = find(["備考", "メモ", "コメント", "note"])
    mapping["例会"]   = find(["例会"])
    mapping["例会日時"] = find(["例会日時"])

    return mapping

@st.cache_data
def load_items(path: Path) -> pd.DataFrame:
    """保存済み items を読み込む（なければ空）"""
    if not path.exists():
        return pd.DataFrame(columns=TARGET_FIELDS)
    try:
        df = pd.read_excel(path, engine="openpyxl")
    except Exception as e:
        st.warning(f"既存ファイルを読み込めませんでした（{e}）")
        return pd.DataFrame(columns=TARGET_FIELDS)

    # 欠けている列は追加
    for col in TARGET_FIELDS:
        if col not in df.columns:
            df[col] = None

    # 型のざっくり整形
    df["id"] = pd.to_numeric(df["id"], errors="coerce").astype("Int64")
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
    df["updated_at"] = pd.to_datetime(df["updated_at"], errors="coerce")
    return df

def save_items(df: pd.DataFrame, path: Path, sheet: str):
    """items を保存（標準列＋追加列）"""
    cols = [c for c in TARGET_FIELDS if c in df.columns] + [c for c in df.columns if c not in TARGET_FIELDS]
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df[cols].to_excel(w, sheet_name=sheet, index=False)

def coerce_id_series(s: pd.Series) -> pd.Series:
    ids = pd.to_numeric(s, errors="coerce").astype("Int64")
    if ids.isna().all():
        ids = pd.Series(range(1, len(s)+1), dtype="Int64")
    else:
        current_max = int(pd.to_numeric(ids, errors="coerce").fillna(0).max())
        out = []
        next_id = current_max + 1 if current_max > 0 else 1
        for v in ids:
            if pd.isna(v) or int(v) == 0:
                out.append(next_id); next_id += 1
            else:
                out.append(int(v))
        ids = pd.Series(out, dtype="Int64")
    return ids

def normalize_df(df_raw: pd.DataFrame, mapping: dict, style_cols: list[str]) -> pd.DataFrame:
    """ユーザーのExcel → 標準スキーマへ正規化。"""
    out = pd.DataFrame()
    for tgt in CORE_FIELDS:
        src = mapping.get(tgt)
        out[tgt] = df_raw[src] if src in df_raw.columns else None

    out["id"] = coerce_id_series(out["id"])
    out["quantity"] = pd.to_numeric(out["quantity"], errors="coerce").fillna(0).astype(int)
    out["updated_at"] = pd.to_datetime(out["updated_at"], errors="coerce").fillna(datetime.now())

    if mapping.get("category") is None:
        def pick_style(row):
            for col in style_cols:
                if col in row.index:
                    v = row[col]
                    if pd.notna(v) and str(v).strip() not in ["", "0", "False", "false", "×", "✕", "✖"]:
                        return col
            return None
        out["category"] = df_raw.apply(pick_style, axis=1)
    else:
        out["category"] = df_raw[mapping["category"]] if mapping["category"] in df_raw.columns else None

    for extra in EXTRA_FIELDS:
        src = mapping.get(extra)
        if src in df_raw.columns:
            out[extra] = df_raw[src]
        else:
            out[extra] = None

    return out

st.title("🍶 診断士迷酒会 DB")

st.sidebar.header("⚙️ 取り込み設定")
uploaded = st.sidebar.file_uploader("既存Excelをアップロード", type=["xlsx"], accept_multiple_files=False)

if uploaded:
    xls = pd.ExcelFile(uploaded, engine="openpyxl")
    sheet = st.sidebar.selectbox("読み込むシート", options=xls.sheet_names, index=0)
    df_raw = pd.read_excel(xls, sheet_name=sheet, engine="openpyxl")
    st.success(f"シート '{sheet}' を読み込みました。列数: {len(df_raw.columns)} 行数: {len(df_raw)}")

    with st.expander("🔎 生データ（先頭20行）", expanded=False):
        st.dataframe(df_raw.head(20), use_container_width=True)

    st.subheader("🔁 列の対応付け（Mapping）")
    guessed = guess_mapping(list(df_raw.columns))
    cols = [None] + list(df_raw.columns)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        m_id = st.selectbox("id", options=cols, index=cols.index(guessed["id"]) if guessed["id"] in cols else 0)
    with c2:
        m_name = st.selectbox("name", options=cols, index=cols.index(guessed["name"]) if guessed["name"] in cols else 0)
    with c3:
        m_category = st.selectbox("category", options=cols, index=cols.index(guessed["category"]) if guessed["category"] in cols else 0)
    with c4:
        m_quantity = st.selectbox("quantity", options=cols, index=cols.index(guessed["quantity"]) if guessed["quantity"] in cols else 0)
    with c5:
        m_updated = st.selectbox("updated_at", options=cols, index=cols.index(guessed["updated_at"]) if guessed["updated_at"] in cols else 0)

    style_cols = st.multiselect("🧪 種別列（値がある列名をcategoryに採用）", options=list(df_raw.columns), default=[c for c in STYLE_CANDIDATES if c in df_raw.columns])

    if st.button("✅ 取り込む（data.xlsxに保存）"):
        mapping = {"id": m_id, "name": m_name, "category": m_category, "quantity": m_quantity, "updated_at": m_updated}
        df_norm = normalize_df(df_raw, mapping, style_cols)
        save_items(df_norm, DATA_FILE, "items")
        st.success("保存しました。")

items = load_items(DATA_FILE)
st.dataframe(items, use_container_width=True)

st.markdown("---")
st.caption("ExcelをDB的に扱うStreamlitアプリ（v1 完成版）")
