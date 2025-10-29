import streamlit as st
import pandas as pd
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Tuple

st.set_page_config(page_title="Excel DB App (Style-aware + RBAC)", page_icon="🍶", layout="wide")

DATA_FILE = Path("data.xlsx")
SHEET_NAME = "items"  # ← 明示的に定義（元コードではコメントアウトで呼び出し時に未定義だった）

# 監査ログ（別ファイルに追記式で管理）
AUDIT_FILE = Path("audit_log.xlsx")
AUDIT_SHEET = "logs"

def _read_audit() -> pd.DataFrame:
    if AUDIT_FILE.exists():
        try:
            return pd.read_excel(AUDIT_FILE, sheet_name=AUDIT_SHEET, engine="openpyxl")
        except Exception:
            pass
    return pd.DataFrame(columns=[
        "ts", "user", "action", "record_id", "name",
        "changed_fields", "before_json", "after_json"
    ])

def _write_audit(df: pd.DataFrame):
    with pd.ExcelWriter(AUDIT_FILE, engine="openpyxl") as w:
        df.to_excel(w, sheet_name=AUDIT_SHEET, index=False)

def _to_jsonish(d: dict) -> str:
    # Excelに入れやすい素朴なJSON風文字列
    import json
    try:
        return json.dumps(d, ensure_ascii=False)
    except Exception:
        return str(d)

def append_audit(action: str, user: str, before: dict|None, after: dict|None):
    """追記型の監査ログ。action=add/update/delete"""
    import datetime as _dt
    rec_id = None
    name = None
    if after and "id" in after: rec_id = after.get("id")
    if before and "id" in before: rec_id = rec_id or before.get("id")
    if after and "name" in after: name = after.get("name")
    if before and "name" in before: name = name or before.get("name")

    # 変更フィールドの簡易抽出
    changed = []
    if before is not None and after is not None:
        keys = set(before.keys()) | set(after.keys())
        for k in keys:
            if str(before.get(k)) != str(after.get(k)):
                changed.append(k)
    elif before is None and after is not None:
        changed = list(after.keys())
    elif before is not None and after is None:
        changed = list(before.keys())

    row = {
        "ts": _dt.datetime.now(),
        "user": user or "-",
        "action": action,
        "record_id": rec_id,
        "name": name,
        "changed_fields": ", ".join(changed),
        "before_json": _to_jsonish(before or {}),
        "after_json": _to_jsonish(after or {}),
    }
    logdf = _read_audit()
    logdf = pd.concat([logdf, pd.DataFrame([row])], ignore_index=True)
    _write_audit(logdf)

# =============================
# 権限管理（RBAC：最小追加）
# =============================
# 実運用では .streamlit/secrets.toml に以下のように定義して使うのを推奨：
# [users.admin]
# password = "********"
# role = "admin"
# display = "管理者A"
# [users.alice]
# password = "********"
# role = "user"
# display = "一般ユーザーA"
from pathlib import Path

DEFAULT_USERS = {
    "admin": {"password": "admin123", "role": "admin", "display": "管理者"},
    "guest": {"password": "guest", "role": "user", "display": "一般"},
}

def _load_users():
    """secrets.toml が存在する時だけ st.secrets を読む（無ければデフォルト）"""
    users = {}
    possible = [
        Path.home() / ".streamlit" / "secrets.toml",
        Path.cwd() / ".streamlit" / "secrets.toml",
    ]
    has_secrets = any(p.exists() for p in possible)
    if has_secrets:
        try:
            # secrets.toml に [users] があれば使う
            users_src = st.secrets.get("users", {})
            for k, v in users_src.items():
                users[k] = {
                    "password": v.get("password", ""),
                    "role": v.get("role", "user"),
                    "display": v.get("display", k),
                }
        except Exception:
            pass
    return users or DEFAULT_USERS

USERS = _load_users()

def do_login(username: str, password: str) -> Tuple[bool, str, str]:
    info = USERS.get(username)
    if not info:
        return False, "", ""
    if info.get("password") != password:
        return False, "", ""
    return True, info.get("role", "user"), info.get("display", username)

if "auth" not in st.session_state:
    st.session_state.auth = {"ok": False, "user": None, "role": "user", "display": None}

# === サイドバー（ログイン + 管理者だけ取り込みUI） ===
with st.sidebar:
    st.header("🔐 ログイン")

    if not st.session_state.auth["ok"]:
        with st.form("login_form", clear_on_submit=False):
            u = st.text_input("ユーザー名")
            p = st.text_input("パスワード", type="password")
            s = st.form_submit_button("ログイン")
        if s:
            ok, role, disp = do_login(u, p)
            if ok:
                st.session_state.auth = {"ok": True, "user": u, "role": role, "display": disp}
                st.success(f"ログインしました：{disp}（{role}）")
                st.rerun()
            else:
                st.error("ユーザー名またはパスワードが違います。")
    else:
        st.markdown(
            f"**{st.session_state.auth['display']}** としてログイン中（役割：`{st.session_state.auth['role']}`）"
        )
        if st.button("ログアウト"):
            st.session_state.auth = {"ok": False, "user": None, "role": "user", "display": None}
            st.rerun()

        # ---- ここから管理者専用の「設定（取り込み）」 ----
        IS_ADMIN = st.session_state.auth.get("role") == "admin"
        if IS_ADMIN:
            st.header("⚙️ 設定（取り込み）")
            uploaded = st.file_uploader("既存Excelをアップロード", type=["xlsx"], accept_multiple_files=False)

            if uploaded:
                try:
                    xls = pd.ExcelFile(uploaded, engine="openpyxl")
                    sheet = st.selectbox("読み込むシート", options=xls.sheet_names, index=0)
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
                    style_cols = st.multiselect(
                        "🧪 種別に使う列（値が入っている列名をcategoryに採用）",
                        options=list(df_raw.columns),
                        default=existing_styles
                    )

                    # 取り込み実行
                    if st.button("✅ この対応で取り込む（data.xlsxに保存）"):
                        mapping = {
                            "id": m_id, "name": m_name, "category": m_category,
                            "quantity": m_quantity, "updated_at": m_updated,
                            "会員氏名": m_member, "蔵元": m_brew, "地域": m_area,
                            "精米歩合": m_polish, "備考": m_note, "例会": m_mt, "例会日時": m_mt_dt,
                        }
                        df_norm = normalize_df(df_raw, mapping, style_cols)
                        save_items(df_norm, DATA_FILE, "items")
                        st.success("取り込み＆保存が完了しました。上のタブから確認できます。")
                        st.cache_data.clear()
                except Exception as e:
                    st.error(f"読み込みでエラー：{e}")

ROLE = st.session_state.auth["role"]
IS_ADMIN = ROLE == "admin"

# =============================
# あなたの現行ロジック（軽微バグ修正込み）
# =============================

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
        df = pd.DataFrame(columns=TARGET_FIELDS)
    else:
        try:
            df = pd.read_excel(path, engine="openpyxl")
        except Exception as e:
            st.warning(f"既存ファイルを読み込めませんでした（{e}）")
            df = pd.DataFrame(columns=TARGET_FIELDS)

    # 欠けている列は追加（※元コードはここに到達する前にreturnしていたため不達→修正）
    for col in TARGET_FIELDS:
        if col not in df.columns:
            df[col] = None

    # 型のざっくり整形
    if "id" in df.columns:
        df["id"] = pd.to_numeric(df["id"], errors="coerce").astype("Int64")
    if "quantity" in df.columns:
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
    if "updated_at" in df.columns:
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

st.title("🍶 診断士迷酒会 DB（RBAC対応・最新版ベース）")

# メインタブ
items = load_items(DATA_FILE)

if IS_ADMIN:
    tab_list, tab_new, tab_edit, tab_logs = st.tabs(
        ["📃 一覧", "➕ 新規追加", "✏️ 編集/削除", "🪵 変更履歴"]
    )
else:
    # 一般ユーザーは編集/履歴タブなし
    tab_list, tab_new = st.tabs(["📃 一覧", "➕ 新規追加"])
    tab_edit = None
    tab_logs = None

st.subheader("レコード一覧")

# --- ここで自足的に初期化（前段で定義がなくても動くように） ---
view = items.copy()

# ===== フィルタUI（会員氏名／フリーワード／例会グループ表示） =====
# 会員氏名の候補
try:
    member_candidates = (
        items["会員氏名"]
        .dropna()
        .astype(str).str.strip()
        .replace("", pd.NA).dropna()
        .unique().tolist()
    )
    member_candidates.sort()
except Exception:
    member_candidates = []

# 例会の候補（「第◯回」表記をラベルに、内部は生値で保持）
import re
def meeting_label(v: str) -> str:
    s = str(v).strip()
    try:
        n = float(s)
        if pd.isna(n):
            return s
        return f"第{int(n)}回"
    except Exception:
        # すでに「第◯回」等はそのまま
        return s

if "例会" in items.columns:
    uniq_raw = (
        items["例会"]
        .dropna()
        .astype(str).str.strip()
        .replace("", pd.NA).dropna()
        .unique().tolist()
    )

    def exnum(s):
        m = re.search(r"\d+", str(s))
        return int(m.group()) if m else 10**9

    uniq_raw_sorted = sorted(uniq_raw, key=exnum)
    label_map = {raw: meeting_label(raw) for raw in uniq_raw_sorted}
    inv_map = {v: k for k, v in label_map.items()}
    meeting_options = ["(すべて)"] + [label_map[r] for r in uniq_raw_sorted]
else:
    meeting_options = ["(すべて)"]
    inv_map = {}

# UI
left, right = st.columns([1, 2])
with left:
    sel_member = st.selectbox("会員氏名で絞り込み", ["(すべて)"] + member_candidates, index=0)
with right:
    q = st.text_input("フリーワード（銘柄名 / 種別 / 蔵元 / 地域 / 会員氏名）", value="")

row = st.columns([1, 1, 1])
with row[0]:
    sel_meeting_label = st.selectbox("例会で絞り込み", meeting_options, index=0)
with row[1]:
    group_mode = st.toggle("📚 例会ごとにグループ表示", value=True,
                           help="閲覧モード時のみ有効。インライン編集モードでは通常表示になります。")
with row[2]:
    pass  # 予備スペース

# フィルタ適用
# 1) 会員氏名
if "会員氏名" in view.columns and sel_member != "(すべて)":
    view = view[view["会員氏名"].astype(str).str.strip() == sel_member]

# 2) 例会（内部の生値で一致）
if "例会" in view.columns and sel_meeting_label != "(すべて)":
    raw_val = inv_map.get(sel_meeting_label, None)
    if raw_val is not None:
        view = view[view["例会"].astype(str) == str(raw_val)]

# 3) フリーワード（OR検索）
if q:
    ql = q.lower()
    def contains(s):
        return s.fillna("").astype(str).str.lower().str.contains(ql, na=False)
    view = view[
        contains(view.get("name", pd.Series([""] * len(view))))
        | contains(view.get("category", pd.Series([""] * len(view))))
        | contains(view.get("蔵元", pd.Series([""] * len(view))))
        | contains(view.get("地域", pd.Series([""] * len(view))))
        | contains(view.get("会員氏名", pd.Series([""] * len(view))))
    ]

st.session_state["group_mode"] = group_mode   # ← ここでセッションに保存

# ===== 一覧描画ここから =====
group_mode = st.session_state.get("group_mode", False)

# 表示列と見出し
show_cols = [c for c in ["id","name","例会","updated_at","蔵元","地域","category","精米歩合","会員氏名","備考","quantity"] if c in view.columns]
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
    "quantity": "数量",
}

# ▼ 表示用コピーを作って整形
display_view = view.copy()

# 例会 → 「第◯回」表記
if "例会" in display_view.columns:
    def fmt_meeting(v):
        s = str(v).strip()
        try:
            n = float(s)
            if pd.isna(n):
                return s
            return f"第{int(n)}回"
        except:
            return s
    display_view["例会"] = display_view["例会"].apply(fmt_meeting)

# 精米歩合 → ％表記
if "精米歩合" in display_view.columns:
    def fmt_seimai(x):
        s = str(x).strip()
        if s == "" or s.lower() == "nan":
            return ""
        try:
            v = float(s)
            if v <= 1:
                v *= 100
            return f"{v:.0f}％"
        except:
            return ""
    display_view["精米歩合"] = display_view["精米歩合"].apply(fmt_seimai)

# 開催日 見た目
if "updated_at" in display_view.columns:
    display_view["updated_at"] = pd.to_datetime(display_view["updated_at"], errors="coerce").dt.strftime("%Y-%m-%d")

display_view = display_view.fillna("")

# ===== 列幅などの column_config =====
col_cfg = {}
if "id" in show_cols:
    col_cfg["id"] = st.column_config.NumberColumn("ID", width="small", disabled=True)
if "name" in show_cols:
    col_cfg["name"] = st.column_config.TextColumn("銘柄名", width="large")
if "例会" in show_cols:
    col_cfg["例会"] = st.column_config.TextColumn("例会", width="small")
if "updated_at" in show_cols:
    col_cfg["updated_at"] = st.column_config.DatetimeColumn("開催日", format="YYYY-MM-DD", width="small")
if "蔵元" in show_cols:
    col_cfg["蔵元"] = st.column_config.TextColumn("蔵元", width="medium")
if "地域" in show_cols:
    col_cfg["地域"] = st.column_config.TextColumn("地域", width="medium")
if "category" in show_cols:
    col_cfg["category"] = st.column_config.TextColumn("種別", width="small")
if "精米歩合" in show_cols:
    col_cfg["精米歩合"] = st.column_config.TextColumn("精米歩合", width="small")
if "会員氏名" in show_cols:
    col_cfg["会員氏名"] = st.column_config.TextColumn("会員氏名", width="medium")
if "備考" in show_cols:
    col_cfg["備考"] = st.column_config.TextColumn("備考", width="large")
if "quantity" in show_cols:
    col_cfg["quantity"] = st.column_config.NumberColumn("数量", min_value=0, step=1, width="small")

# ===== 編集モード（管理者のみ） =====
edit_mode = IS_ADMIN and st.toggle("✏️ インライン編集（管理者）", value=False, help="管理者はこの表で直接編集できます。")

if (not edit_mode) and group_mode and "例会" in display_view.columns:
    # 閲覧モードのグループ表示（今回は group_mode=False なので通常は通らない）
    total = 0
    for key, g in display_view.groupby("例会", sort=False):
        st.markdown(f"**■ 例会: {key}（{len(g)}件）**")
        st.dataframe(
            g[[c for c in show_cols if c in g.columns]].rename(columns=display_names),
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg
        )
        total += len(g)
    st.caption(f"{total} / {len(items)} rows")
else:
    # 編集モード：st.data_editor、閲覧モード：st.dataframe
    table_df = display_view[[c for c in show_cols if c in display_view.columns]].rename(columns=display_names)

    if edit_mode:
        # 表示名→内部名の逆マップ
        inv_name = {v: k for k, v in display_names.items() if k in show_cols}

        edited = st.data_editor(
            table_df,
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            column_config=col_cfg,
            key="editable_table"
        )

        if st.button("💾 この内容で保存（インライン編集）", type="primary", use_container_width=True):
            edited_internal = edited.rename(columns=inv_name)

            if "id" in edited_internal.columns:
                base = items.copy()
                base["id"] = pd.to_numeric(base["id"], errors="coerce").astype("Int64")
                edited_internal["id"] = pd.to_numeric(edited_internal["id"], errors="coerce").astype("Int64")

                base_idx = base.set_index("id")
                incoming_idx = edited_internal.set_index("id")

                # 変更・追加検出
                changed_ids = sorted(list(set(base_idx.index).intersection(incoming_idx.index)))
                common_cols = [c for c in incoming_idx.columns if c in base_idx.columns and c != "updated_at"]

                # 既存更新
                if changed_ids:
                    base_idx.loc[changed_ids, common_cols] = incoming_idx.loc[changed_ids, common_cols].values

                # 追加行（id欠損のもの）
                add_df = incoming_idx[incoming_idx.index.isna()]
                if not add_df.empty:
                    next_id = int(pd.to_numeric(base["id"], errors="coerce").fillna(0).max()) + 1
                    add_rows = add_df.reset_index(drop=True)
                    add_rows["id"] = range(next_id, next_id + len(add_rows))
                    add_rows = add_rows.set_index("id")
                    base_idx = pd.concat([base_idx, add_rows], axis=0)

                # updated_at 更新
                if "updated_at" in base_idx.columns:
                    base_idx.loc[:, "updated_at"] = pd.Timestamp.now()

                updated_df = base_idx.reset_index()

                # 保存＆監査ログ
                save_items(updated_df, DATA_FILE, SHEET_NAME)
                append_audit(
                    action="bulk_edit",
                    user=st.session_state.auth.get("user"),
                    before=None,
                    after=f"rows={len(changed_ids)}+added={0 if 'add_rows' not in locals() else len(add_rows)}"
                )
                st.success("保存しました")
                st.cache_data.clear()
            else:
                st.error("ID 列が見つかりません。列の表示設定を確認してください。")
    else:
        st.dataframe(
            table_df,
            use_container_width=True,
            hide_index=True,
            column_config=col_cfg
        )
        st.caption(f"{len(display_view)} / {len(items)} rows")

with tab_new:
    st.subheader("📝 新規追加フォーム（全ユーザー可）")

    # ========= フォームの外：会員氏名モード切替＆候補取得 =========
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
            meigara = st.text_input("持参日本酒銘柄名")
            kuramoto = st.text_input("蔵元（XX酒造）")
            chiiki = st.text_input("地域（XX県XX市）")
            category = st.text_input("種別（例：純米吟醸、本醸造 等）")

            # 精米歩合（半角数字のみ・空欄OK）
            import re
            seimai = st.text_input("精米歩合（％・半角数字のみ　例：60）")
            if seimai and not re.fullmatch(r"[0-9]+(\.[0-9]+)?", seimai):
                st.error("⚠️ 精米歩合は半角数字（小数点可）のみで入力してください。")
                st.stop()

        submitted = st.form_submit_button("📤 登録する")

        if submitted:
            if not kaiin or str(kaiin).strip() == "":
                st.error("⚠️ 会員氏名を入力または選択してください。")
                st.stop()

            # 既存データを読み込み（存在しない場合は空）
            try:
                df = pd.read_excel(DATA_FILE)
            except Exception:
                df = pd.DataFrame(columns=TARGET_FIELDS)

            # 🔢 自動採番を追加（既存idの最大値+1）
            next_id = int(pd.to_numeric(df.get("id", pd.Series(dtype=float)), errors="coerce").fillna(0).max()) + 1

            # 新規行を定義
            new_row = pd.DataFrame([{
                "id": next_id,   # ← 自動採番
                "会員氏名": str(kaiin).strip(),
                "name": meigara,
                "蔵元": kuramoto,
                "地域": chiiki,
                "category": category,
                "精米歩合": seimai,
                "updated_at": date_str.strftime("%Y-%m-%d"),
                "備考": bikou,
            }])

            # 保存処理
            df = pd.concat([df, new_row], ignore_index=True)
            save_items(df, DATA_FILE if isinstance(DATA_FILE, Path) else Path(DATA_FILE), "items")

            # 監査ログ
            append_audit(
                action="add",
                user=st.session_state.auth.get("user"),
                before=None,
                after=new_row.iloc[0].to_dict()
            )

            st.success("✅ 登録しました！")
            st.cache_data.clear()


# =========================
# ✏️ 編集 / 削除（管理者のみ）
# =========================
if IS_ADMIN and tab_edit is not None:
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

                    # 1) 更新【前】スナップショットを先に取得
                    before_dict = items.loc[sel_index].to_dict()

                    # 2) 更新内容をまとめて定義（可読性＆差分検出しやすく）
                    update_values = {
                        "name": name.strip(),
                        "category": category.strip(),
                        "quantity": int(quantity),
                        "updated_at": datetime.now(),
                        "蔵元": brew.strip(),
                        "地域": area.strip(),
                        "精米歩合": polish.strip(),
                        "会員氏名": member.strip(),
                        "例会": meeting.strip(),
                        "備考": note.strip(),
                    }

                    # すでに同一内容なら更新・ログをスキップ（任意だが事故防止に有効）
                    no_change = all(str(items.at[sel_index, k]) == str(v) for k, v in update_values.items())
                    if no_change:
                        st.info("変更点がありません。")
                        st.stop()

                    # 3) 実データを更新
                    items.loc[sel_index, list(update_values.keys())] = list(update_values.values())

                    # 4) 保存
                    save_items(items, DATA_FILE, SHEET_NAME)

                    # 5) 更新【後】スナップショット
                    after_dict = items.loc[sel_index].to_dict()

                    # 6) 監査ログ
                    append_audit(
                        action="update",
                        user=st.session_state.auth.get("user"),
                        before=before_dict,
                        after=after_dict
                    )

                    st.success("更新しました")
                    st.cache_data.clear()

                if delete_btn:
                    df2 = items.drop(index=sel_index).copy()

                    before_del = items.loc[sel_index].to_dict()
                    append_audit(
                        action="delete",
                        user=st.session_state.auth.get("user"),
                        before=before_del,
                        after=None
                    )

                    save_items(df2, DATA_FILE, SHEET_NAME)
                    st.success("削除しました")
                    st.cache_data.clear()

if IS_ADMIN and tab_logs is not None:
    with tab_logs:
        st.subheader("🪵 変更履歴（最新100件）")
        logs = _read_audit()
        if logs.empty:
            st.info("履歴はまだありません。")
        else:
            logs = logs.sort_values("ts", ascending=False).head(100)
            show = logs[["ts", "user", "action", "record_id", "name", "changed_fields", "before_json", "after_json"]]
            st.dataframe(show, use_container_width=True, hide_index=True)


st.markdown("---")
st.caption("列マッピング＋“種別”自動抽出に対応。RBACでアップロード/新規は一般可、編集/削除は管理者限定、閲覧・検索は全ユーザー可。")
