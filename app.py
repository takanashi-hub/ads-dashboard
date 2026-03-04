"""広告ダッシュボード（Streamlit）— Meta / Google Ads"""

import json
import os
import locale

try:
    locale.setlocale(locale.LC_TIME, "ja_JP.UTF-8")
except locale.Error:
    pass

from datetime import date, timedelta
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import get_adapters

# ─── ページ設定 ───────────────────────────────────────────
st.set_page_config(
    page_title="広告ダッシュボード",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown('<meta name="google" content="notranslate">', unsafe_allow_html=True)

# ─── パスワード認証 ───────────────────────────────────────
import hashlib
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if st.session_state.authenticated:
        return True
    pw = st.text_input("パスワードを入力してください", type="password")
    if pw:
        if hashlib.sha256(pw.encode()).hexdigest() == hashlib.sha256("ys2026".encode()).hexdigest():
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("パスワードが正しくありません")
    st.stop()

check_password()

# ─── カスタムCSS ──────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1rem; }
    [data-testid="stMetricValue"] { font-size: 1.3rem; }
    [data-testid="stMetricDelta"] { font-size: 0.85rem; }
    div[data-testid="stMetricLabel"] > div { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)


# ─── ユーティリティ ───────────────────────────────────────
def fmt_currency(val):
    if val is None or pd.isna(val):
        return "—"
    return f"¥{val:,.0f}"


def fmt_number(val, decimals=0):
    if val is None or pd.isna(val):
        return "—"
    if decimals == 0:
        return f"{val:,.0f}"
    return f"{val:,.{decimals}f}"


def fmt_pct(val):
    if val is None or pd.isna(val):
        return "—"
    return f"{val:.2f}%"


def calc_delta(current, previous):
    if previous is None or previous == 0 or pd.isna(previous):
        return None
    return ((current - previous) / abs(previous)) * 100


def delta_str(delta_val):
    if delta_val is None:
        return None
    return f"{delta_val:+.1f}%"


# ─── サイドバー ───────────────────────────────────────────
st.sidebar.title("📊 広告ダッシュボード")
st.sidebar.markdown("---")

# 日付選択
today = date.today()
default_from = today - timedelta(days=7)

date_from = st.sidebar.date_input("開始日", value=default_from)
date_to = st.sidebar.date_input("終了日", value=today - timedelta(days=1))

if date_from > date_to:
    st.sidebar.error("開始日は終了日より前にしてください")
    st.stop()

# 比較期間
selected_compare = st.sidebar.selectbox(
    "比較対象",
    ["前月比", "前年比"],
    index=0,
)

span = (date_to - date_from).days + 1

if selected_compare == "前月比":
    try:
        if date_from.month == 1:
            prev_from = date_from.replace(year=date_from.year - 1, month=12)
        else:
            prev_from = date_from.replace(month=date_from.month - 1)
    except ValueError:
        import calendar
        prev_m = date_from.month - 1
        prev_y = date_from.year
        if prev_m == 0:
            prev_m = 12
            prev_y -= 1
        last_day = calendar.monthrange(prev_y, prev_m)[1]
        prev_from = date_from.replace(year=prev_y, month=prev_m, day=min(date_from.day, last_day))
    prev_to = prev_from + timedelta(days=span - 1)
elif selected_compare == "前年比":
    try:
        prev_from = date_from.replace(year=date_from.year - 1)
    except ValueError:
        prev_from = date_from.replace(year=date_from.year - 1, day=28)
    prev_to = prev_from + timedelta(days=span - 1)

st.sidebar.markdown("---")

# ─── データ取得 ───────────────────────────────────────────
@st.cache_data(ttl=600)
def fetch_all_data(from_str, to_str, prev_from_str, prev_to_str):
    adapters = get_adapters()
    results = {}
    for adapter in adapters:
        name = getattr(adapter, "_account_name", adapter.__class__.__name__)
        try:
            current = adapter.fetch_campaigns(from_str, to_str)
            previous = adapter.fetch_campaigns(prev_from_str, prev_to_str)
            results[name] = {
                "current": current,
                "previous": previous,
                "adapter": adapter,
            }
        except Exception as e:
            results[name] = {
                "current": [],
                "previous": [],
                "error": str(e),
            }
    return results


def aggregate_kpis(campaigns):
    if not campaigns:
        return {"spend": 0, "impressions": 0, "clicks": 0, "conversions": 0, "revenue": 0,
                "ctr": 0, "cpc": 0, "cpm": 0, "cpa": 0, "roas": 0}
    
    total = {
        "spend": sum(c.get("spend", 0) or 0 for c in campaigns),
        "impressions": sum(c.get("impressions", 0) or 0 for c in campaigns),
        "clicks": sum(c.get("clicks", 0) or 0 for c in campaigns),
        "conversions": sum(c.get("conversions", 0) or 0 for c in campaigns),
        "revenue": sum(c.get("revenue", 0) or 0 for c in campaigns),
    }
    
    total["ctr"] = (total["clicks"] / total["impressions"] * 100) if total["impressions"] > 0 else 0
    total["cpc"] = (total["spend"] / total["clicks"]) if total["clicks"] > 0 else 0
    total["cpm"] = (total["spend"] / total["impressions"] * 1000) if total["impressions"] > 0 else 0
    total["cpa"] = (total["spend"] / total["conversions"]) if total["conversions"] > 0 else 0
    total["roas"] = (total["revenue"] / total["spend"]) if total["spend"] > 0 else 0
    
    return total


from_str = date_from.strftime("%Y-%m-%d")
to_str = date_to.strftime("%Y-%m-%d")
prev_from_str = prev_from.strftime("%Y-%m-%d")
prev_to_str = prev_to.strftime("%Y-%m-%d")

with st.spinner("データを取得中..."):
    all_data = fetch_all_data(from_str, to_str, prev_from_str, prev_to_str)

# ─── プラットフォーム選択（サイドバー） ───────────────────
platform_names = ["📊 全体"] + list(all_data.keys())
selected_platform = st.sidebar.radio("プラットフォーム", platform_names, index=0)

st.sidebar.markdown("---")
st.sidebar.markdown(
    f"**選択期間**: {date_from.strftime('%Y/%m/%d')} ~ {date_to.strftime('%Y/%m/%d')}  \n"
    f"**比較期間**: {prev_from.strftime('%Y/%m/%d')} ~ {prev_to.strftime('%Y/%m/%d')}"
)


# ─── KPIメトリクス表示 ────────────────────────────────────
def show_kpi_metrics(cur, prev):
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        d = delta_str(calc_delta(cur["spend"], prev["spend"]))
        st.metric("費用", fmt_currency(cur["spend"]), delta=d, delta_color="inverse")
    with c2:
        d = delta_str(calc_delta(cur["conversions"], prev["conversions"]))
        st.metric("CV数", f"{cur['conversions']:.1f}件", delta=d)
    with c3:
        d = delta_str(calc_delta(cur["cpa"], prev["cpa"]))
        st.metric("CPA", fmt_currency(cur["cpa"]), delta=d, delta_color="inverse")
    with c4:
        d = delta_str(calc_delta(cur["roas"], prev["roas"]))
        st.metric("ROAS", f"{cur['roas']:.2f}", delta=d)
    
    c5, c6, c7, c8 = st.columns(4)
    with c5:
        d = delta_str(calc_delta(cur["impressions"], prev["impressions"]))
        st.metric("表示回数", fmt_number(cur["impressions"]), delta=d)
    with c6:
        d = delta_str(calc_delta(cur["clicks"], prev["clicks"]))
        st.metric("クリック数", fmt_number(cur["clicks"]), delta=d)
    with c7:
        d = delta_str(calc_delta(cur["ctr"], prev["ctr"]))
        st.metric("CTR", fmt_pct(cur["ctr"]), delta=d)
    with c8:
        d = delta_str(calc_delta(cur["cpc"], prev["cpc"]))
        st.metric("CPC", fmt_currency(cur["cpc"]), delta=d, delta_color="inverse")


# ─── キャンペーンテーブル表示 ─────────────────────────────
def show_campaign_table(campaigns, platform_name):
    if not campaigns:
        st.info("選択期間にデータがありません")
        return
    
    # ベストキャンペーン
    valid = [c for c in campaigns if c.get("conversions", 0) > 0]
    if valid:
        best = min(valid, key=lambda c: c.get("cpa", float("inf")))
        st.success(
            f"🏆 ベストキャンペーン: **{best.get('campaign_name', '不明')}**　"
            f"CPA {fmt_currency(best.get('cpa', 0))} / CV {best.get('conversions', 0):.1f}件"
        )
    
    st.markdown("---")
    
    df = pd.DataFrame(campaigns)
    
    display_cols = {
        "campaign_name": "キャンペーン名",
        "spend": "費用",
        "impressions": "表示回数",
        "clicks": "クリック数",
        "conversions": "CV数",
        "revenue": "売上",
        "ctr": "CTR(%)",
        "cpc": "CPC",
        "cpa": "CPA",
        "roas": "ROAS",
    }
    
    available_cols = [c for c in display_cols.keys() if c in df.columns]
    df_display = df[available_cols].copy()
    df_display.columns = [display_cols[c] for c in available_cols]
    
    sort_col = st.selectbox("並び替え", ["費用", "CV数", "CPA", "ROAS"], index=0)
    ascending = sort_col in ["CPA"]
    
    if sort_col in df_display.columns:
        df_display = df_display.sort_values(sort_col, ascending=ascending, na_position="last")
    
    format_dict = {}
    if "費用" in df_display.columns:
        format_dict["費用"] = "¥{:,.0f}"
    if "表示回数" in df_display.columns:
        format_dict["表示回数"] = "{:,.0f}"
    if "クリック数" in df_display.columns:
        format_dict["クリック数"] = "{:,.0f}"
    if "CV数" in df_display.columns:
        format_dict["CV数"] = "{:.1f}"
    if "売上" in df_display.columns:
        format_dict["売上"] = "¥{:,.0f}"
    if "CTR(%)" in df_display.columns:
        format_dict["CTR(%)"] = "{:.2f}%"
    if "CPC" in df_display.columns:
        format_dict["CPC"] = "¥{:,.0f}"
    if "CPA" in df_display.columns:
        format_dict["CPA"] = "¥{:,.0f}"
    if "ROAS" in df_display.columns:
        format_dict["ROAS"] = "{:.2f}"
    
    st.dataframe(
        df_display.style.format(format_dict, na_rep="—"),
        use_container_width=True,
        hide_index=True,
    )
    
    # 費用構成グラフ
    if "費用" in df_display.columns and "キャンペーン名" in df_display.columns:
        df_chart = df_display[df_display["費用"] > 0].head(10)
        if not df_chart.empty:
            fig = go.Figure(data=[
                go.Bar(
                    x=df_chart["キャンペーン名"],
                    y=df_chart["費用"],
                    marker_color="#4A90D9",
                )
            ])
            fig.update_layout(
                title=f"{platform_name} — キャンペーン別費用（Top 10）",
                xaxis_title="",
                yaxis_title="費用（円）",
                height=400,
                margin=dict(t=40, b=80),
            )
            fig.update_xaxes(tickangle=-45)
            st.plotly_chart(fig, use_container_width=True)


# ─── メインコンテンツ ─────────────────────────────────────
st.title("📊 広告ダッシュボード")
st.caption(f"{date_from.strftime('%Y年%m月%d日')} ~ {date_to.strftime('%Y年%m月%d日')}　|　比較: {selected_compare}")

if selected_platform == "📊 全体":
    # ── 全体表示 ──
    all_current = []
    all_previous = []
    for name, data in all_data.items():
        if "error" not in data:
            all_current.extend(data["current"])
            all_previous.extend(data["previous"])
    
    t_cur = aggregate_kpis(all_current)
    t_prev = aggregate_kpis(all_previous)
    
    show_kpi_metrics(t_cur, t_prev)
    
    st.markdown("---")
    st.subheader("キャンペーン別詳細")
    
    all_campaigns = []
    for name, data in all_data.items():
        if "error" in data:
            st.error(f"❌ {name}: {data['error']}")
            continue
        for c in data["current"]:
            c_copy = c.copy()
            c_copy["platform"] = name
            all_campaigns.append(c_copy)
    
    if all_campaigns:
        show_campaign_table(all_campaigns, "全体")

else:
    # ── 個別プラットフォーム表示 ──
    pdata = all_data.get(selected_platform, {})
    
    if "error" in pdata:
        st.error(f"❌ {pdata['error']}")
    else:
        cur = aggregate_kpis(pdata.get("current", []))
        prev = aggregate_kpis(pdata.get("previous", []))
        
        show_kpi_metrics(cur, prev)
        
        st.markdown("---")
        st.subheader("キャンペーン別詳細")
        show_campaign_table(pdata.get("current", []), selected_platform)


# ─── AI分析（フッター） ──────────────────────────────────
st.markdown("---")
api_key = os.environ.get("ANTHROPIC_API_KEY", "")

with st.expander("🤖 AI分析", expanded=False):
    if not api_key:
        st.warning("⚠️ ANTHROPIC_API_KEY が設定されていません。`~/.zshrc` に追加してください。")
    else:
        st.caption("広告データをAIが分析し、改善提案を行います")
        
        if st.button("分析を実行", type="primary"):
            summary_parts = []
            for name, data in all_data.items():
                if "error" in data:
                    continue
                cur = aggregate_kpis(data["current"])
                prev = aggregate_kpis(data["previous"])
                
                part = (
                    f"【{name}】\n"
                    f"  費用: {fmt_currency(cur['spend'])}（{selected_compare}: {fmt_currency(prev['spend'])}）\n"
                    f"  CV数: {cur['conversions']:.1f}件（{selected_compare}: {prev['conversions']:.1f}件）\n"
                    f"  CPA: {fmt_currency(cur['cpa'])}（{selected_compare}: {fmt_currency(prev['cpa'])}）\n"
                    f"  ROAS: {cur['roas']:.2f}（{selected_compare}: {prev['roas']:.2f}）\n"
                    f"  CTR: {cur['ctr']:.2f}%（{selected_compare}: {prev['ctr']:.2f}%）\n"
                )
                
                if data["current"]:
                    part += "  キャンペーン別:\n"
                    sorted_camps = sorted(data["current"], key=lambda c: c.get("spend", 0), reverse=True)
                    for c in sorted_camps[:5]:
                        if c.get("spend", 0) > 0:
                            part += (
                                f"    - {c.get('campaign_name', '不明')}: "
                                f"費用{fmt_currency(c.get('spend', 0))} / "
                                f"CV{c.get('conversions', 0):.1f}件 / "
                                f"CPA{fmt_currency(c.get('cpa', 0))} / "
                                f"ROAS{c.get('roas', 0):.2f}\n"
                            )
                
                summary_parts.append(part)
            
            data_summary = "\n".join(summary_parts)
            
            prompt = f"""あなたはD2C製薬会社（ワイズ製薬）の広告分析エキスパートです。
以下の広告データを分析し、日本語で改善提案をしてください。

期間: {date_from} ~ {date_to}
比較: {selected_compare}

{data_summary}

以下の観点で分析してください:
1. 全体パフォーマンスの要約（良い点・悪い点）
2. プラットフォーム別の比較と傾向
3. キャンペーン別の改善ポイント（CPAが高いもの、ROASが低いもの）
4. 具体的なアクション提案（3〜5つ）

簡潔かつ実用的にお願いします。"""

            with st.spinner("AI分析中..."):
                try:
                    import requests
                    resp = requests.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": api_key,
                            "anthropic-version": "2023-06-01",
                            "content-type": "application/json",
                        },
                        json={
                            "model": "claude-sonnet-4-20250514",
                            "max_tokens": 2000,
                            "messages": [{"role": "user", "content": prompt}],
                        },
                        timeout=60,
                    )
                    
                    if resp.status_code == 200:
                        result = resp.json()
                        text = result["content"][0]["text"]
                        st.markdown(text)
                    else:
                        st.error(f"API エラー: {resp.status_code} - {resp.text}")
                except Exception as e:
                    st.error(f"分析エラー: {e}")
