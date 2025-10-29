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
STYLE_CANDIDATES = ["本醸造", "特別本醸造", "純米", "特別純米", "吟醸", "純米吟醸", "大吟醸", "純米大吟醸", "その他"]

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
        return df
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
    # 列の並びをなるべく固定
    cols = [c for c in TARGET_FIELDS if c in df.columns] + [c for c in df.columns if c not in TARGET_FIELDS]
    with pd.ExcelWriter(path, engine="openpyxl") as w:
        df[cols].to_excel(w, sheet_name=sheet, index=False)

def coerce_id_series(s: pd.Series) -> pd.Series:
    ids = pd.to_numeric(s, errors="coerce").astype("Int64")
    if ids.isna().all():
        ids = pd.Series(range(1, len(s)+1), dtype="Int64")
    else:
        # 足りないところは連番補完
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
    """
    ユーザーのExcel → 標準スキーマへ正規化。
    categoryが未指定なら、style_colsの中で「値が入っている列名」をcategoryにセット。
    """
    out = pd.DataFrame()

    # まず core fields をマッピング
    for tgt in CORE_FIELDS:
        src = mapping.get(tgt)
        out[tgt] = df_raw[src] if src in df_raw.columns else None

    # 数値・日時の整形
    out["id"] = coerce_id_series(out["id"])
    out["quantity"] = pd.to_numeric(out["quantity"], errors="coerce").fillna(0).astype(int)
    out["updated_at"] = pd.to_datetime(out["updated_at"], errors="coerce").fillna(datetime.now())

    # category の自動推定（styleベース）
    if mapping.get("category") is None:
        # rowごとに、style_colsの中で最初に値が入っている列名を採用
        def pick_style(row):
            for col in style_cols:
                if col in row.index:
                    v = row[col]
                    if pd.notna(v) and str(v).strip() not in ["", "0", "False", "false", "×", "✕", "✖"]:
                        return col
            return None
        out["category"] = df_raw.apply(pick_style, axis=1)
    else:
        # すでに category マッピングがあるならそれを使う
        out["category"] = df_raw[mapping["category"]] if mapping["category"] in df_raw.columns else None

    # 追加列の取り込み（存在すれば）
    for extra in EXTRA_FIELDS:
        src = mapping.get(extra)
        if src in df_raw.columns:
            out[extra] = df_raw[src]
        else:
            # 自動で拾えるもの（例会日時など）が category と被らないようにだけ注意
            if extra in df_raw.columns and extra not in out.columns:
                out[extra] = df_raw[extra]
            else:
                out[extra] = None

    return out

st.title("🍶 診断士迷酒会 DB")

st.sidebar.header("⚙️ 設定")
uploaded = st.sidebar.file_uploader("既存Excelをアップロード", type=["xlsx"], accept_multiple_files=False)

if uploaded:
    try:
        xls = pd.ExcelFile(uploaded, engine="openpyxl")
        sheet = st.sidebar.selectbox("読み込むシート", options=xls.sheet_names, index=0)
        df_raw = pd.read_excel(xls, sheet_name=sheet, engine="openpyxl")
        st.success(f"シート '{sheet}' を読み込みました。列数: {len(df_raw.columns)} 行数: {len(df_raw)}")

        with st.expander("🔎 生データ（先頭20行）", expanded=False):
            st.dataframe(df_raw.head(20), use_container_width=True)

        # マッピングUI
        st.subheader("🔁 列の対応付け（Mapping）")
        guessed = guess_mapping(list(df_raw.columns))
        cols = [None] + list(df_raw.columns)

        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            m_id = st.selectbox("id（無ければNoneでOK）", options=cols, index=cols.index(guessed["id"]) if guessed["id"] in cols else 0)
        with c2:
            m_name = st.selectbox("name（銘柄など）", options=cols, index=cols.index(guessed["name"]) if guessed["name"] in cols else 0)
        with c3:
            m_category = st.selectbox("category（※未選択なら“種別”から自動）", options=cols, index=cols.index(guessed["category"]) if guessed["category"] in cols else 0)
        with c4:
            m_quantity = st.selectbox("quantity（数量）", options=cols, index=cols.index(guessed["quantity"]) if guessed["quantity"] in cols else 0)
        with c5:
            m_updated = st.selectbox("updated_at（更新/例会日時）", options=cols, index=cols.index(guessed["updated_at"]) if guessed["updated_at"] in cols else 0)

        # 追加列
        c6, c7, c8, c9, c10, c11, c12 = st.columns(7)
        with c6:  m_member = st.selectbox("会員氏名", options=cols, index=cols.index(guessed["会員氏名"]) if guessed["会員氏名"] in cols else 0)
        with c7:  m_brew = st.selectbox("蔵元", options=cols, index=cols.index(guessed["蔵元"]) if guessed["蔵元"] in cols else 0)
        with c8:  m_area = st.selectbox("地域", options=cols, index=cols.index(guessed["地域"]) if guessed["地域"] in cols else 0)
        with c9:  m_polish = st.selectbox("精米歩合", options=cols, index=cols.index(guessed["精米歩合"]) if guessed["精米歩合"] in cols else 0)
        with c10: m_note = st.selectbox("備考", options=cols, index=cols.index(guessed["備考"]) if guessed["備考"] in cols else 0)
        with c11: m_mt = st.selectbox("例会", options=cols, index=cols.index(guessed["例会"]) if guessed["例会"] in cols else 0)
        with c12: m_mt_dt = st.selectbox("例会日時", options=cols, index=cols.index(guessed["例会日時"]) if guessed["例会日時"] in cols else 0)

        # 種別の自動抽出に使う列（存在するものから自動プリセット）
        existing_styles = [c for c in STYLE_CANDIDATES if c in df_raw.columns]
        style_cols = st.multiselect("🧪 種別に使う列（値が入っている列名をcategoryに採用）",
                                    options=list(df_raw.columns),
                                    default=existing_styles)

        # 取り込み実行
        if st.button("✅ この対応で取り込む（data.xlsxに保存）"):
            mapping = {
                "id": m_id, "name": m_name, "category": m_category,
                "quantity": m_quantity, "updated_at": m_updated,
                "会員氏名": m_member, "蔵元": m_brew, "地域": m_area,
                "精米歩合": m_polish, "備考": m_note, "例会": m_mt, "例会日時": m_mt_dt,
            }
            df_norm = normalize_df(df_raw, mapping, style_cols)
            save_items(df_norm, DATA_FILE, SHEET_NAME)
            st.success("取り込み＆保存が完了しました。上のタブから確認できます。")
            st.cache_data.clear()

    except Exception as e:
        st.error(f"読み込みでエラー：{e}")

# メインタブ
items = load_items(DATA_FILE)
tab_list, tab_new, tab_edit = st.tabs(["📃 一覧", "➕ 新規追加", "✏️ 編集/削除"])

with tab_list:
    st.subheader("レコード一覧")

    # 表示する列（例会を追加／在庫数は非表示）
    show_cols = [c for c in ["name","例会","updated_at","蔵元","地域","category","精米歩合","会員氏名","備考"] if c in items.columns]
    if len(show_cols) == 0:
        show_cols = items.columns.tolist()

    # --- フィルタ適用 ---
    view = items.copy()

    # 「開催日」表示を日本語表記に（内部データは壊さない）
    if "updated_at" in view.columns:
        view["updated_at"] = pd.to_datetime(view["updated_at"], errors="coerce").dt.strftime("%Y年%m月%d日")

    # 表示名マッピング（画面上の列ヘッダーを日本語化）
    display_names = {
        "id": "ID",
        "name": "銘柄名",
        "category": "種別",
        "updated_at": "開催日",
        "蔵元": "蔵元",
        "地域": "地域",
        "精米歩合": "精米歩合",
        "会員氏名": "会員氏名",
        "備考": "備考",
        "例会": "例会",
    }

    # --- 検索UI（会員氏名プルダウン＋フリーワード） ---
    left, right = st.columns([1, 2])

    # プルダウンの候補（空欄は除外）
    member_candidates = []
    if "会員氏名" in items.columns:
        member_counts = (
        items["会員氏名"].dropna().astype(str).str.strip().value_counts()
        )
        member_candidates = list(member_counts.index)

    with left:
        sel_member = st.selectbox(
            "会員氏名で絞り込み",
            ["(すべて)"] + member_candidates,
            index=0
        )

    with right:
        q = st.text_input("フリーワード（銘柄名 / 種別 / 蔵元 / 地域 / 会員氏名）", value="")

    # 1) 会員氏名プルダウン（AND条件）
    if "会員氏名" in view.columns and sel_member != "(すべて)":
        view = view[view["会員氏名"].astype(str).str.strip() == sel_member]

    # 2) フリーワード（AND条件）
    if q:
        ql = q.lower()
        def contains(s):
            return s.fillna("").astype(str).str.lower().str.contains(ql, na=False)

        view = view[
            contains(view.get("name", pd.Series([""] * len(view)))) |
            contains(view.get("category", pd.Series([""] * len(view)))) |
            contains(view.get("蔵元", pd.Series([""] * len(view)))) |
            contains(view.get("地域", pd.Series([""] * len(view)))) |
            contains(view.get("会員氏名", pd.Series([""] * len(view))))
        ]

    # ---- 例会での絞り込み & グループ表示 ----
    # 絞り込みUI（例会列があるときだけ）
    # 例会の降順ソート（数値・日付に対応）
    if "例会" in view.columns:
        # --- 例会の昇順ソート：数値/日付 → 最後に特殊（例：第？回） ---
        # 全角→半角
        def z2h_digits(s: str) -> str:
            return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))

        s = view["例会"].astype(str).map(z2h_digits)

        # ① 数字キー（例：第10回 → 10）
        num_str = s.str.replace(r"\D", "", regex=True)  # 数字以外を削除
        key_num = pd.to_numeric(num_str, errors="coerce")  # 取れなければ NaN

        # ② 日付キー（例：2025/10 → int）
        key_dt = pd.to_datetime(s, errors="coerce").view("i8")  # 取れなければ NaT→NaN

        # 特殊行の判定（数字も日付も取れない → 末尾へ）
        special_mask = key_num.isna() & pd.isna(key_dt)
        view["__例会_flag__"] = special_mask.astype(int)   # 通常=0 / 特殊=1

        # 最終キー：数字 > 日付 の順に採用
        key_final = key_num.copy()
        need_dt = key_final.isna()
        key_final[need_dt] = key_dt[need_dt]

        # まだNaNなものは超大きい値に（昇順でも末尾へ）
        key_final = key_final.fillna(9.22e18)

        view["__例会_key__"] = key_final

        # ソート：①flag昇順（通常→特殊）②キー昇順（第1回→第2回→…）
        view = view.sort_values(
            by=["__例会_flag__", "__例会_key__"],
            ascending=[True, True],
            na_position="last"
        )

        # 表に出さない補助列は消しておく（任意）
        view = view.drop(columns=["__例会_flag__", "__例会_key__"], errors="ignore")

        # 数字部分を抽出してソート（例：第10回 → 10）
        def extract_num(s):
            import re
            s = str(s)
            # 「第10回」→10、「10」→10、それ以外は大きい値で末尾に
            m = re.search(r"\d+", s)
            return int(m.group()) if m else 999999

        # ユニーク値を取り、数字順に並び替え
        unique_vals = view["例会"].dropna().astype(str).unique()
        sorted_vals = sorted(unique_vals, key=extract_num)

        meetings = ["(すべて)"] + list(sorted_vals)

        sel = st.selectbox("🔎 例会で絞り込み", meetings, index=0)
        if sel != "(すべて)":
            view = view[view["例会"].astype(str) == sel]

        group_mode = st.toggle("📚 例会ごとにグループ表示", value=True)

    else:
        group_mode = False  # 例会列が無ければ通常表示

with tab_new:
    st.subheader("📝 新規追加フォーム")

    DATA_FILE = "data.xlsx"

    # ========= フォームの外：会員氏名モード切替＆候補取得 =========
    import pandas as pd

    try:
        df_existing = pd.read_excel(DATA_FILE)
        member_counts = (
            df_existing["会員氏名"]
            .dropna()
            .astype(str)
            .str.strip()
            .replace("", pd.NA)
            .dropna()
            .value_counts()
        )
        # 出現回数の多い順に並べたリスト
        member_candidates = member_counts.index.tolist()
    except Exception:
        member_candidates = []

    mode = st.radio(
        "会員氏名の入力方法",
        ["既存から選ぶ", "新規で入力"],
        horizontal=True,
        key="member_mode"
    )

    # ==================== フォーム本体 ====================
    with st.form("entry_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            date_str = st.date_input("開催日")

            # ▼ フォーム内で、選択モードに応じて片方だけ描画
            if mode == "既存から選ぶ":
                sel = st.selectbox(
                    "既存の会員氏名を選択",
                    ["(選択)"] + member_candidates,
                    index=0,
                    key="member_select"
                )
                kaiin = "" if sel == "(選択)" else sel
            else:
                kaiin = st.text_input("新しい会員氏名を入力", key="member_new_input")

            bikou = st.text_area("コメント", height=80)

        with col2:
            # reikai = st.text_input("例会（例：10）")
            meigara = st.text_input("持参日本酒銘柄名")
            kuramoto = st.text_input("蔵元（XX酒造）")
            chiiki = st.text_input("地域（XX県XX市）")
            category = st.text_input("種別（例：純米吟醸、本醸造　等）")
            
            # 精米歩合（半角数字のみ・空欄OK）
            import re

            # 半角数字（0〜9）と小数点のみ許可。空欄はOK。
            seimai = st.text_input("精米歩合（％・半角数字のみ　例：60）")

            # 入力バリデーション
            if seimai:  # 空欄でなければチェック
                if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", seimai):
                    st.error("⚠️ 精米歩合は半角数字（小数点可）のみで入力してください。")
                    st.stop()

        submitted = st.form_submit_button("📤 登録する")

        if submitted:
            # 入力チェック
            if not kaiin or str(kaiin).strip() == "":
                st.error("⚠️ 会員氏名を入力または選択してください。")
                st.stop()

            from datetime import date

            new_row = pd.DataFrame([{
                # "例会": reikai,  # 管理者が後で入力
                "会員氏名": str(kaiin).strip(),
                "name": meigara,
                "蔵元": kuramoto,
                "地域": chiiki,
                "category": category,
                "精米歩合": seimai,  # ※表示時に%整形しているのでここはそのまま保存
                "updated_at": date_str.strftime("%Y-%m-%d"),
                "備考": bikou,
            }])

            try:
                df = pd.read_excel(DATA_FILE)
                df = pd.concat([df, new_row], ignore_index=True)
                df.to_excel(DATA_FILE, index=False)
                st.success("✅ 登録しました！")
            except Exception as e:
                st.error(f"保存時にエラーが発生しました: {e}")

# ▼ 表示専用のコピーを作る（ロジック用の view は触らない）
display_view = view.copy()

# 例会を「第○回」へ（1.0 や "1.0" も 第1回 に）
if "例会" in display_view.columns:
    def fmt_meeting(v):
        s = str(v).strip()
        # 数字（小数含む）なら整数化して表示
        try:
            n = float(s)
            if pd.isna(n):
                return s
            return f"第{int(n)}回"
        except:
            # すでに「第◯回」などの文字列はそのまま
            return s
    display_view["例会"] = display_view["例会"].apply(fmt_meeting)

# 精米歩合を％表示に（0.5→50％、0.65→65％、60→60％、欠損は空欄）
if "精米歩合" in display_view.columns:
    def fmt_seimai(x):
        s = str(x).strip()
        if s == "" or s.lower() == "nan":
            return ""
        try:
            v = float(s)
            if v <= 1:           # 割合（0.5など）は×100
                v *= 100
            return f"{v:.0f}％"   # 小数点なしに丸め
        except:
            return ""
    display_view["精米歩合"] = display_view["精米歩合"].apply(fmt_seimai)

# NaN を空欄に（全体）
display_view = display_view.fillna("")

# ▼ 表示（グループ表示 or 通常表示）
if group_mode and "例会" in display_view.columns:
    total = 0
    for key, g in display_view.groupby("例会", sort=False):  # 並び替え済み順を維持
        st.markdown(f"**■ 例会: {key}（{len(g)}件）**")
        st.dataframe(
            g[show_cols].rename(columns=display_names),
            use_container_width=True,
            hide_index=True
        )
        total += len(g)
    st.caption(f"{total} / {len(items)} rows")
else:
    st.dataframe(
        display_view[show_cols].rename(columns=display_names),
        use_container_width=True,
        hide_index=True
    )
    st.caption(f"{len(display_view)} / {len(items)} rows")

with tab_edit:
    st.subheader("✏️ 編集 / 削除")

    if len(items) == 0:
        st.info("データがありません。")
    else:
        # ======== 検索UI（キーは一覧タブと衝突しないように別名）========
        c1, c2, c3 = st.columns([2, 1.2, 1.2])

        with c1:
            q_edit = st.text_input(
                "🔎 フリーワード（銘柄名 / 会員氏名 / 例会 / 地域 / 種別）",
                "",
                key="edit_query",
            )

        with c2:
            # 会員氏名プルダウン（頻出順）
            if "会員氏名" in items.columns:
                member_counts = (
                    items["会員氏名"]
                    .dropna()
                    .astype(str)
                    .str.strip()
                    .replace("", pd.NA)
                    .dropna()
                    .value_counts()
                )
                members_opt = ["(すべて)"] + member_counts.index.tolist()
            else:
                members_opt = ["(すべて)"]
            sel_member_e = st.selectbox(
                "会員氏名",
                members_opt,
                index=0,
                key="edit_member_sel",
            )

        with c3:
            import re

            def meeting_label(v):
                s = str(v).strip()
                try:
                    n = float(s)
                    if pd.isna(n):
                        return s
                    return f"第{int(n)}回"
                except Exception:
                    return s

            # 例会プルダウン（表示は第◯回、内部は生値）
            if "例会" in items.columns:
                uniq_raw = items["例会"].dropna().astype(str).unique().tolist()

                def exnum(s):
                    m = re.search(r"\d+", str(s))
                    return int(m.group()) if m else 10**9

                uniq_raw_sorted = sorted(uniq_raw, key=exnum)
                label_map = {raw: meeting_label(raw) for raw in uniq_raw_sorted}

                meetings_labels = ["(すべて)"] + [label_map[raw] for raw in uniq_raw_sorted]
                sel_label_meeting = st.selectbox(
                    "例会",
                    meetings_labels,
                    index=0,
                    key="edit_meeting_sel",
                )

                inv_map = {v: k for k, v in label_map.items()}
                sel_meeting_raw = (
                    None if sel_label_meeting == "(すべて)" else inv_map[sel_label_meeting]
                )
            else:
                sel_meeting_raw = None

        # ======== フィルタ適用（表示整形は最後）========
        view_e = items.copy()

        # 会員氏名フィルタ
        if "会員氏名" in view_e.columns and sel_member_e != "(すべて)":
            view_e = view_e[view_e["会員氏名"].astype(str).str.strip() == sel_member_e]

        # 例会フィルタ（生の値で比較）
        if "例会" in view_e.columns and sel_meeting_raw is not None:
            view_e = view_e[view_e["例会"].astype(str) == str(sel_meeting_raw)]

        # フリーワード（複数列OR）
        if q_edit:
            ql = q_edit.lower()

            def contains(s):
                return s.fillna("").astype(str).str.lower().str.contains(ql, na=False)

            view_e = view_e[
                contains(view_e.get("name", pd.Series([""] * len(view_e))))
                | contains(view_e.get("会員氏名", pd.Series([""] * len(view_e))))
                | contains(view_e.get("例会", pd.Series([""] * len(view_e))))
                | contains(view_e.get("地域", pd.Series([""] * len(view_e))))
                | contains(view_e.get("category", pd.Series([""] * len(view_e))))
            ]

        # 表示用に「第◯回」に整形（データ自体は変更しない）
        if "例会" in view_e.columns:
            view_e["例会"] = view_e["例会"].apply(meeting_label)

        # ======== 候補プレビュー ========
        with st.expander(f"候補プレビュー（{len(view_e)}件）", expanded=False):
            cols_preview = [
                c
                for c in ["id", "name", "会員氏名", "例会", "updated_at", "地域", "category"]
                if c in view_e.columns
            ]
            st.dataframe(view_e[cols_preview], use_container_width=True, hide_index=True)

        if len(view_e) == 0:
            st.warning("一致するレコードがありません。条件を緩めてください。")
            st.stop()

        # ======== 1件選択（ラベルは見やすく、内部はindex保持）========
        def safe_id(v):
            try:
                return int(pd.to_numeric(v, errors="coerce"))
            except Exception:
                return None

        options = []
        for _, r in view_e.reset_index().iterrows():
            rid = safe_id(r.get("id"))
            label = f"[id:{rid if rid is not None else '-'}] {str(r.get('name',''))} / {str(r.get('会員氏名',''))} / 例会:{meeting_label(r.get('例会',''))}"
            options.append((label, int(r["index"])))  # 元DataFrameのindexを保持

        labels = [o[0] for o in options]
        indices = {o[0]: o[1] for o in options}

        sel_label = st.selectbox("編集対象を選択", labels, index=0, key="edit_select_row")
        sel_index = indices[sel_label]

        # 対象行を取得
        row = items.loc[sel_index]

        # ======== 編集フォーム ========
        with st.form("edit_form"):
            name = st.text_input("name*", value=str(row.get("name", "") or ""))
            category = st.text_input("category", value=str(row.get("category", "") or ""))
            # quantityはNaN安全に
            q_raw = pd.to_numeric(row.get("quantity", None), errors="coerce")
            q_def = 0 if pd.isna(q_raw) else int(q_raw)
            quantity = st.number_input("quantity", min_value=0, value=q_def, step=1)

            brew = st.text_input("蔵元", value=str(row.get("蔵元", "") or ""))
            area = st.text_input("地域", value=str(row.get("地域", "") or ""))
            polish = st.text_input("精米歩合", value=str(row.get("精米歩合", "") or ""))
            member = st.text_input("会員氏名", value=str(row.get("会員氏名", "") or ""))
            meeting = st.text_input(
                "例会（数字推奨。表示は自動で『第◯回』に整形）",
                value=str(row.get("例会", "") or ""),
            )
            note = st.text_input("備考", value=str(row.get("備考", "") or ""))

            colA, colB = st.columns(2)
            update_btn = colA.form_submit_button("💾 更新")
            delete_btn = colB.form_submit_button("🗑️ 削除")

            if update_btn:
                if not name.strip():
                    st.error("name は必須です")
                    st.stop()
                # 更新（updated_at は現在時刻で更新）
                items.loc[
                    sel_index,
                    [
                        "name",
                        "category",
                        "quantity",
                        "updated_at",
                        "蔵元",
                        "地域",
                        "精米歩合",
                        "会員氏名",
                        "例会",
                        "備考",
                    ],
                ] = [
                    name.strip(),
                    category.strip(),
                    int(quantity),
                    datetime.now(),
                    brew.strip(),
                    area.strip(),
                    polish.strip(),
                    member.strip(),
                    meeting.strip(),
                    note.strip(),
                ]
                save_items(items, DATA_FILE, "items")  # ← save_items の仕様に合わせて必要なら統一
                st.success("更新しました")
                st.cache_data.clear()

            if delete_btn:
                df2 = items.drop(index=sel_index).copy()
                save_items(df2, DATA_FILE, "items")
                st.success("削除しました")
                st.cache_data.clear()

st.markdown("---")
st.caption("列マッピング＋“種別”自動抽出に対応。取り込み後は標準スキーマ＋追加列で保存されます。")
