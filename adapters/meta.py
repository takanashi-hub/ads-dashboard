"""Meta Marketing API アダプター（Graph API v23.0）"""

import logging
import os

import requests

from adapters.base import AdsAdapter

logger = logging.getLogger(__name__)

BASE_URL = "https://graph.facebook.com/v23.0"

METRIC_FIELDS = [
    "spend",
    "impressions",
    "clicks",
    "ctr",
    "cpc",
    "cpm",
    "actions",
    "action_values",
]


def _get_token() -> str:
    token = os.environ.get("META_ACCESS_TOKEN", "")
    if not token:
        raise RuntimeError("環境変数 META_ACCESS_TOKEN が設定されていません")
    return token


def _get_account_id() -> str:
    account_id = os.environ.get("META_AD_ACCOUNT_ID", "")
    if not account_id:
        raise RuntimeError("環境変数 META_AD_ACCOUNT_ID が設定されていません")
    return account_id


def _extract_action_value(actions: list[dict] | None, action_type: str) -> float:
    """actionsリストから指定タイプの値を取得"""
    if not actions:
        return 0.0
    for action in actions:
        if action.get("action_type") == action_type:
            return float(action.get("value", 0))
    return 0.0


def _calc_kpi(spend: float, conversions: int, revenue: float) -> dict:
    """CPA・ROASを計算"""
    cpa = spend / conversions if conversions > 0 else 0.0
    roas = revenue / spend if spend > 0 else 0.0
    return {"cpa": round(cpa, 2), "roas": round(roas, 2)}


def _api_get(endpoint: str, params: dict) -> dict:
    """Meta Graph APIへGETリクエスト"""
    token = _get_token()
    params["access_token"] = token
    url = f"{BASE_URL}/{endpoint}"

    resp = requests.get(url, params=params, timeout=60)
    data = resp.json()

    if "error" in data:
        error = data["error"]
        code = error.get("code", "")
        msg = error.get("message", "")

        if code == 190:
            raise RuntimeError(
                f"Metaアクセストークンが無効または期限切れです。トークンを更新してください。詳細: {msg}"
            )
        raise RuntimeError(f"Meta API エラー (code={code}): {msg}")

    return data


def _parse_insight(row: dict) -> dict:
    """insightsレスポンスの1行をパースして統一フォーマットに変換"""
    spend = float(row.get("spend", 0))
    impressions = int(row.get("impressions", 0))
    clicks = int(row.get("clicks", 0))
    ctr = float(row.get("ctr", 0))
    cpc = float(row.get("cpc", 0))
    cpm = float(row.get("cpm", 0))

    actions = row.get("actions", [])
    action_values = row.get("action_values", [])

    # purchase (コンバージョン) を取得。なければ offsite_conversion.fb_pixel_purchase も試行
    conversions = int(
        _extract_action_value(actions, "purchase")
        or _extract_action_value(actions, "offsite_conversion.fb_pixel_purchase")
    )
    revenue = (
        _extract_action_value(action_values, "purchase")
        or _extract_action_value(action_values, "offsite_conversion.fb_pixel_purchase")
    )

    kpi = _calc_kpi(spend, conversions, revenue)

    return {
        "spend": round(spend, 2),
        "impressions": impressions,
        "clicks": clicks,
        "conversions": conversions,
        "revenue": round(revenue, 2),
        "ctr": round(ctr, 2),
        "cpc": round(cpc, 2),
        "cpm": round(cpm, 2),
        "cpa": kpi["cpa"],
        "roas": kpi["roas"],
    }


def _fetch_all_pages(initial_data: dict) -> list[dict]:
    """ページネーションを処理して全データを取得"""
    results = initial_data.get("data", [])
    paging = initial_data.get("paging", {})

    while paging.get("next"):
        resp = requests.get(paging["next"], timeout=60)
        page_data = resp.json()
        results.extend(page_data.get("data", []))
        paging = page_data.get("paging", {})

    return results


def _format_genders(genders: list[int]) -> str:
    """gendersリスト (1=男性, 2=女性) を日本語に変換"""
    if not genders:
        return "すべて"
    m = {1: "男性", 2: "女性"}
    return "、".join(m.get(g, str(g)) for g in genders)


def _format_locations(geo: dict) -> str:
    """geo_locationsオブジェクトを文字列に変換"""
    parts = []
    for c in geo.get("countries", []):
        parts.append(c)
    for r in geo.get("regions", []):
        parts.append(r.get("name", str(r)))
    for c in geo.get("cities", []):
        parts.append(c.get("name", str(c)))
    return "、".join(parts) if parts else "指定なし"


class MetaAdsAdapter(AdsAdapter):
    """Meta Marketing API アダプター"""

    def platform_name(self) -> str:
        return "Meta広告"

    def fetch_campaigns(self, date_from: str, date_to: str) -> list[dict]:
        account_id = _get_account_id()
        fields = METRIC_FIELDS + ["campaign_id", "campaign_name"]

        data = _api_get(
            f"{account_id}/insights",
            {
                "level": "campaign",
                "fields": ",".join(fields),
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
                "limit": 500,
            },
        )

        results = []
        for row in _fetch_all_pages(data):
            parsed = _parse_insight(row)
            parsed["campaign_id"] = row.get("campaign_id", "")
            parsed["campaign_name"] = row.get("campaign_name", "")
            results.append(parsed)

        return results

    def fetch_daily_metrics(self, date_from: str, date_to: str) -> list[dict]:
        account_id = _get_account_id()

        data = _api_get(
            f"{account_id}/insights",
            {
                "fields": ",".join(METRIC_FIELDS),
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
                "time_increment": 1,
                "limit": 500,
            },
        )

        results = []
        for row in _fetch_all_pages(data):
            parsed = _parse_insight(row)
            parsed["date"] = row.get("date_start", "")
            results.append(parsed)

        return results

    def fetch_adsets(self, campaign_id: str, date_from: str, date_to: str) -> list[dict]:
        account_id = _get_account_id()
        fields = METRIC_FIELDS + ["adset_id", "adset_name"]

        data = _api_get(
            f"{account_id}/insights",
            {
                "level": "adset",
                "filtering": f'[{{"field":"campaign.id","operator":"EQUAL","value":"{campaign_id}"}}]',
                "fields": ",".join(fields),
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
                "limit": 500,
            },
        )

        results = []
        for row in _fetch_all_pages(data):
            parsed = _parse_insight(row)
            parsed["adset_id"] = row.get("adset_id", "")
            parsed["adset_name"] = row.get("adset_name", "")
            results.append(parsed)

        return results

    def fetch_ads(self, adset_id: str, date_from: str, date_to: str) -> list[dict]:
        account_id = _get_account_id()
        fields = METRIC_FIELDS + ["ad_id", "ad_name"]

        data = _api_get(
            f"{account_id}/insights",
            {
                "level": "ad",
                "filtering": f'[{{"field":"adset.id","operator":"EQUAL","value":"{adset_id}"}}]',
                "fields": ",".join(fields),
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
                "limit": 500,
            },
        )

        results = []
        for row in _fetch_all_pages(data):
            parsed = _parse_insight(row)
            parsed["ad_id"] = row.get("ad_id", "")
            parsed["ad_name"] = row.get("ad_name", "")
            results.append(parsed)

        return results

    def fetch_all_adsets(self, date_from: str, date_to: str) -> list[dict]:
        account_id = _get_account_id()
        fields = METRIC_FIELDS + ["adset_id", "adset_name", "campaign_name"]

        data = _api_get(
            f"{account_id}/insights",
            {
                "level": "adset",
                "fields": ",".join(fields),
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
                "limit": 500,
            },
        )

        results = []
        for row in _fetch_all_pages(data):
            parsed = _parse_insight(row)
            parsed["adset_id"] = row.get("adset_id", "")
            parsed["adset_name"] = row.get("adset_name", "")
            parsed["campaign_name"] = row.get("campaign_name", "")
            results.append(parsed)

        return results

    def fetch_all_ads(self, date_from: str, date_to: str) -> list[dict]:
        account_id = _get_account_id()
        fields = METRIC_FIELDS + ["ad_id", "ad_name", "campaign_name", "adset_name"]

        data = _api_get(
            f"{account_id}/insights",
            {
                "level": "ad",
                "fields": ",".join(fields),
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
                "limit": 500,
            },
        )

        results = []
        for row in _fetch_all_pages(data):
            parsed = _parse_insight(row)
            parsed["ad_id"] = row.get("ad_id", "")
            parsed["ad_name"] = row.get("ad_name", "")
            parsed["campaign_name"] = row.get("campaign_name", "")
            parsed["adset_name"] = row.get("adset_name", "")
            results.append(parsed)

        return results

    def fetch_age_gender_breakdown(self, date_from: str, date_to: str) -> list[dict]:
        account_id = _get_account_id()

        data = _api_get(
            f"{account_id}/insights",
            {
                "fields": ",".join(METRIC_FIELDS),
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
                "breakdowns": "age,gender",
                "limit": 500,
            },
        )

        results = []
        for row in _fetch_all_pages(data):
            parsed = _parse_insight(row)
            parsed["age"] = row.get("age", "")
            parsed["gender"] = row.get("gender", "")
            results.append(parsed)

        return results

    def fetch_region_breakdown(self, date_from: str, date_to: str) -> list[dict]:
        account_id = _get_account_id()

        data = _api_get(
            f"{account_id}/insights",
            {
                "fields": ",".join(METRIC_FIELDS),
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
                "breakdowns": "region",
                "limit": 500,
            },
        )

        results = []
        for row in _fetch_all_pages(data):
            parsed = _parse_insight(row)
            parsed["region"] = row.get("region", "")
            results.append(parsed)

        return results

    def fetch_frequency(self, date_from: str, date_to: str) -> dict:
        account_id = _get_account_id()

        data = _api_get(
            f"{account_id}/insights",
            {
                "fields": "frequency,reach,impressions",
                "time_range": f'{{"since":"{date_from}","until":"{date_to}"}}',
            },
        )

        rows = data.get("data", [])
        if rows:
            row = rows[0]
            return {
                "frequency": float(row.get("frequency", 0)),
                "reach": int(row.get("reach", 0)),
                "impressions": int(row.get("impressions", 0)),
            }
        return {"frequency": 0.0, "reach": 0, "impressions": 0}

    def fetch_adset_targeting(self, adset_id: str) -> dict:
        """広告セットのターゲティング情報を取得"""
        try:
            data = _api_get(adset_id, {"fields": "targeting"})
        except RuntimeError:
            logger.warning("ターゲティング情報の取得に失敗: adset_id=%s", adset_id)
            return {"age": "取得不可", "genders": "取得不可", "locations": "取得不可", "interests": "取得不可"}

        targeting = data.get("targeting", {})
        age_min = targeting.get("age_min", "")
        age_max = targeting.get("age_max", "")
        genders = targeting.get("genders", [])
        geo = targeting.get("geo_locations", {})

        interests = []
        for spec in targeting.get("flexible_spec", []):
            for item in spec.get("interests", []):
                interests.append(item.get("name", ""))

        return {
            "age": f"{age_min}〜{age_max}歳" if age_min or age_max else "指定なし",
            "genders": _format_genders(genders),
            "locations": _format_locations(geo),
            "interests": "、".join(interests) if interests else "指定なし",
        }

    def fetch_ad_creative(self, ad_id: str) -> dict:
        """広告のクリエイティブ情報を取得"""
        try:
            data = _api_get(ad_id, {"fields": "name,creative{title,body,thumbnail_url,image_url}"})
        except RuntimeError:
            logger.warning("クリエイティブ情報の取得に失敗: ad_id=%s", ad_id)
            return {"title": "", "body": "", "image_url": "", "thumbnail_url": ""}

        creative = data.get("creative", {})
        return {
            "title": creative.get("title", ""),
            "body": creative.get("body", ""),
            "image_url": creative.get("image_url", "") or creative.get("thumbnail_url", ""),
            "thumbnail_url": creative.get("thumbnail_url", ""),
        }
