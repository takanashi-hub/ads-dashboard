"""Slack投稿の整形"""


def _fmt_yen(value: float) -> str:
    """金額を¥付き3桁カンマ区切りにフォーマット"""
    return f"¥{value:,.0f}"


def _fmt_pct(value: float) -> str:
    """パーセント表示（小数1桁）"""
    return f"{value:.1f}%"


def _fmt_delta(current: float, previous: float) -> str:
    """前日比を計算してフォーマット"""
    if previous == 0:
        if current == 0:
            return "±0%"
        return "+∞%"
    change = (current - previous) / previous * 100
    sign = "+" if change >= 0 else ""
    return f"{sign}{change:.0f}%"


def format_daily_report(
    platform_name: str,
    today_data: dict,
    yesterday_data: dict | None = None,
    best_campaign: dict | None = None,
    report_date: str = "",
) -> str:
    """Slack投稿文を生成

    Args:
        platform_name: プラットフォーム名（例: "Meta広告"）
        today_data: 当日の集計データ
            - spend: float
            - conversions: int
            - cpa: float
            - roas: float
        yesterday_data: 前日の集計データ（前日比計算用、Noneの場合は前日比なし）
        best_campaign: ベストキャンペーン情報（Noneの場合は表示なし）
            - campaign_name: str
            - cpa: float
            - conversions: int
        report_date: レポート日付文字列（例: "2026-02-18"）
    """
    spend = today_data.get("spend", 0)
    conversions = today_data.get("conversions", 0)
    cpa = today_data.get("cpa", 0)
    roas = today_data.get("roas", 0)

    lines = []
    lines.append(f"📊 広告日次レポート（{report_date}）")
    lines.append("")
    lines.append(f"【{platform_name}】")

    if yesterday_data:
        y_spend = yesterday_data.get("spend", 0)
        y_cv = yesterday_data.get("conversions", 0)
        y_cpa = yesterday_data.get("cpa", 0)
        y_roas = yesterday_data.get("roas", 0)

        lines.append(f"├ 費用: {_fmt_yen(spend)}（前日比 {_fmt_delta(spend, y_spend)}）")
        lines.append(f"├ CV数: {conversions:.1f}件（前日比 {_fmt_delta(conversions, y_cv)}）")
        lines.append(f"├ CPA: {_fmt_yen(cpa)}（前日比 {_fmt_delta(cpa, y_cpa)}）")
        lines.append(f"└ ROAS: {roas:.2f}（前日比 {_fmt_delta(roas, y_roas)}）")
    else:
        lines.append(f"├ 費用: {_fmt_yen(spend)}")
        lines.append(f"├ CV数: {conversions:.1f}件")
        lines.append(f"├ CPA: {_fmt_yen(cpa)}")
        lines.append(f"└ ROAS: {roas:.2f}")

    if best_campaign:
        lines.append("")
        bc_name = best_campaign.get("campaign_name", "N/A")
        bc_cpa = best_campaign.get("cpa", 0)
        bc_cv = best_campaign.get("conversions", 0)
        lines.append(f"🏆 ベストキャンペーン: {bc_name}")
        lines.append(f"   CPA {_fmt_yen(bc_cpa)} / CV {bc_cv:.1f}件")

    return "\n".join(lines)


def format_campaign_breakdown(campaigns: list[dict], report_date: str = "") -> str:
    """キャンペーン別の内訳をSlack投稿用テキストで生成"""
    if not campaigns:
        return ""

    # cost > 0 のキャンペーンのみ、費用降順
    active = [c for c in campaigns if c.get("spend", 0) > 0]
    active.sort(key=lambda c: c.get("spend", 0), reverse=True)

    if not active:
        return ""

    def _fmt_yen(v):
        return f"¥{int(v):,}"

    lines = []
    lines.append("")
    lines.append("📊 Google広告 キャンペーン別内訳")
    lines.append("")

    for c in active:
        name = c.get("campaign_name", "N/A")
        spend = c.get("spend", 0)
        cv = c.get("conversions", 0)
        cpa = spend / cv if cv > 0 else 0
        roas = c.get("roas", 0)

        cpa_str = _fmt_yen(cpa) if cv > 0 else "-"
        lines.append(f"▸ *{name}*")
        lines.append(f"　費用: {_fmt_yen(spend)} / CV: {cv:.1f}件 / CPA: {cpa_str}")

    return "\n".join(lines)
