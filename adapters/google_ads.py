"""Google Ads API アダプター"""

import logging
import os
from typing import Optional

from google.ads.googleads.client import GoogleAdsClient
from google.ads.googleads.errors import GoogleAdsException

from adapters.base import AdsAdapter

logger = logging.getLogger(__name__)


def _get_client() -> GoogleAdsClient:
    """環境変数からGoogle Ads APIクライアントを生成"""
    required = [
        "GOOGLE_ADS_DEVELOPER_TOKEN",
        "GOOGLE_ADS_CLIENT_ID",
        "GOOGLE_ADS_CLIENT_SECRET",
        "GOOGLE_ADS_REFRESH_TOKEN",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    ]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"環境変数が未設定: {', '.join(missing)}")

    return GoogleAdsClient.load_from_dict({
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
        "use_proto_plus": True,
    })


def _get_customer_id() -> str:
    cid = os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "")
    if not cid:
        raise RuntimeError("環境変数 GOOGLE_ADS_CUSTOMER_ID が設定されていません")
    return cid


def _query(client: GoogleAdsClient, customer_id: str, gaql: str) -> list:
    """GAQLクエリを実行して結果行のリストを返す"""
    service = client.get_service("GoogleAdsService")
    try:
        response = service.search(customer_id=customer_id, query=gaql)
        return list(response)
    except GoogleAdsException as ex:
        for error in ex.failure.errors:
            logger.error("Google Ads API エラー: %s", error.message)
        raise RuntimeError(f"Google Ads API エラー: {ex.failure.errors[0].message}") from ex


def _micros_to_yen(micros: int) -> float:
    """マイクロ単位を円に変換"""
    return micros / 1_000_000


def _calc_kpi(spend: float, conversions: float, revenue: float) -> dict:
    cpa = spend / conversions if conversions > 0 else 0.0
    roas = revenue / spend if spend > 0 else 0.0
    return {"cpa": round(cpa, 2), "roas": round(roas, 2)}


def _safe_div(a: float, b: float) -> float:
    return round(a / b, 2) if b > 0 else 0.0


class GoogleAdsAdapter(AdsAdapter):
    """Google Ads API アダプター"""

    def __init__(self, customer_id: str = None, account_name: str = None):
        self._client: Optional[GoogleAdsClient] = None
        self._customer_id_override = customer_id
        self._account_name = account_name or "Google広告"

    @property
    def client(self) -> GoogleAdsClient:
        if self._client is None:
            self._client = _get_client()
        return self._client

    @property
    def customer_id(self) -> str:
        if self._customer_id_override:
            return self._customer_id_override
        return _get_customer_id()

    def platform_name(self) -> str:
        return self._account_name or "Google広告"

    def fetch_campaigns(self, date_from: str, date_to: str) -> list[dict]:
        gaql = f"""
            SELECT
                campaign.id,
                campaign.name,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.average_cpm,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
              AND campaign.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
        """
        rows = _query(self.client, self.customer_id, gaql)
        results = []
        for row in rows:
            spend = _micros_to_yen(row.metrics.cost_micros)
            conversions = round(row.metrics.conversions, 2)
            revenue = round(row.metrics.conversions_value, 2)
            kpi = _calc_kpi(spend, conversions, revenue)
            results.append({
                "campaign_id": str(row.campaign.id),
                "campaign_name": row.campaign.name,
                "spend": round(spend, 2),
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": conversions,
                "revenue": revenue,
                "ctr": round(row.metrics.ctr * 100, 2),  # Google returns 0-1
                "cpc": _micros_to_yen(row.metrics.average_cpc),
                "cpm": _micros_to_yen(row.metrics.average_cpm),
                "cpa": kpi["cpa"],
                "roas": kpi["roas"],
            })
        return results

    def fetch_daily_metrics(self, date_from: str, date_to: str) -> list[dict]:
        gaql = f"""
            SELECT
                segments.date,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.conversions_value
            FROM campaign
            WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
              AND campaign.status != 'REMOVED'
            ORDER BY segments.date ASC
        """
        rows = _query(self.client, self.customer_id, gaql)

        # 日別に集約（複数キャンペーンが同日に存在するため）
        daily: dict[str, dict] = {}
        for row in rows:
            d = row.segments.date
            if d not in daily:
                daily[d] = {
                    "date": d,
                    "spend": 0.0,
                    "impressions": 0,
                    "clicks": 0,
                    "conversions": 0,
                    "revenue": 0.0,
                }
            daily[d]["spend"] += _micros_to_yen(row.metrics.cost_micros)
            daily[d]["impressions"] += row.metrics.impressions
            daily[d]["clicks"] += row.metrics.clicks
            daily[d]["conversions"] += row.metrics.conversions
            daily[d]["revenue"] += row.metrics.conversions_value

        results = []
        for d in sorted(daily.keys()):
            rec = daily[d]
            rec["spend"] = round(rec["spend"], 2)
            rec["revenue"] = round(rec["revenue"], 2)
            kpi = _calc_kpi(rec["spend"], rec["conversions"], rec["revenue"])
            rec["cpa"] = kpi["cpa"]
            rec["roas"] = kpi["roas"]
            results.append(rec)
        return results

    def fetch_adsets(self, campaign_id: str, date_from: str, date_to: str) -> list[dict]:
        """Google Adsでは広告グループ = 広告セット相当"""
        gaql = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.conversions,
                metrics.conversions_value
            FROM ad_group
            WHERE campaign.id = {campaign_id}
              AND segments.date BETWEEN '{date_from}' AND '{date_to}'
              AND ad_group.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
        """
        rows = _query(self.client, self.customer_id, gaql)
        results = []
        for row in rows:
            spend = _micros_to_yen(row.metrics.cost_micros)
            conversions = round(row.metrics.conversions, 2)
            revenue = round(row.metrics.conversions_value, 2)
            kpi = _calc_kpi(spend, conversions, revenue)
            results.append({
                "adset_id": str(row.ad_group.id),
                "adset_name": row.ad_group.name,
                "spend": round(spend, 2),
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": conversions,
                "revenue": revenue,
                "ctr": round(row.metrics.ctr * 100, 2),
                "cpc": _micros_to_yen(row.metrics.average_cpc),
                "cpa": kpi["cpa"],
                "roas": kpi["roas"],
            })
        return results

    def fetch_ads(self, adset_id: str, date_from: str, date_to: str) -> list[dict]:
        """広告グループ内の広告一覧"""
        gaql = f"""
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad.name,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.conversions,
                metrics.conversions_value
            FROM ad_group_ad
            WHERE ad_group.id = {adset_id}
              AND segments.date BETWEEN '{date_from}' AND '{date_to}'
              AND ad_group_ad.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
        """
        rows = _query(self.client, self.customer_id, gaql)
        results = []
        for row in rows:
            spend = _micros_to_yen(row.metrics.cost_micros)
            conversions = round(row.metrics.conversions, 2)
            revenue = round(row.metrics.conversions_value, 2)
            kpi = _calc_kpi(spend, conversions, revenue)
            results.append({
                "ad_id": str(row.ad_group_ad.ad.id),
                "ad_name": row.ad_group_ad.ad.name or f"Ad {row.ad_group_ad.ad.id}",
                "spend": round(spend, 2),
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": conversions,
                "revenue": revenue,
                "ctr": round(row.metrics.ctr * 100, 2),
                "cpc": _micros_to_yen(row.metrics.average_cpc),
                "cpa": kpi["cpa"],
                "roas": kpi["roas"],
            })
        return results

    def fetch_all_adsets(self, date_from: str, date_to: str) -> list[dict]:
        gaql = f"""
            SELECT
                ad_group.id,
                ad_group.name,
                campaign.name,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.conversions,
                metrics.conversions_value
            FROM ad_group
            WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
              AND ad_group.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
        """
        rows = _query(self.client, self.customer_id, gaql)
        results = []
        for row in rows:
            spend = _micros_to_yen(row.metrics.cost_micros)
            conversions = round(row.metrics.conversions, 2)
            revenue = round(row.metrics.conversions_value, 2)
            kpi = _calc_kpi(spend, conversions, revenue)
            results.append({
                "adset_id": str(row.ad_group.id),
                "adset_name": row.ad_group.name,
                "campaign_name": row.campaign.name,
                "spend": round(spend, 2),
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": conversions,
                "revenue": revenue,
                "ctr": round(row.metrics.ctr * 100, 2),
                "cpc": _micros_to_yen(row.metrics.average_cpc),
                "cpa": kpi["cpa"],
                "roas": kpi["roas"],
            })
        return results

    def fetch_all_ads(self, date_from: str, date_to: str) -> list[dict]:
        gaql = f"""
            SELECT
                ad_group_ad.ad.id,
                ad_group_ad.ad.name,
                campaign.name,
                ad_group.name,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.ctr,
                metrics.average_cpc,
                metrics.conversions,
                metrics.conversions_value
            FROM ad_group_ad
            WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
              AND ad_group_ad.status != 'REMOVED'
            ORDER BY metrics.cost_micros DESC
        """
        rows = _query(self.client, self.customer_id, gaql)
        results = []
        for row in rows:
            spend = _micros_to_yen(row.metrics.cost_micros)
            conversions = round(row.metrics.conversions, 2)
            revenue = round(row.metrics.conversions_value, 2)
            kpi = _calc_kpi(spend, conversions, revenue)
            results.append({
                "ad_id": str(row.ad_group_ad.ad.id),
                "ad_name": row.ad_group_ad.ad.name or f"Ad {row.ad_group_ad.ad.id}",
                "campaign_name": row.campaign.name,
                "adset_name": row.ad_group.name,
                "spend": round(spend, 2),
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": conversions,
                "revenue": revenue,
                "ctr": round(row.metrics.ctr * 100, 2),
                "cpc": _micros_to_yen(row.metrics.average_cpc),
                "cpa": kpi["cpa"],
                "roas": kpi["roas"],
            })
        return results

    def fetch_age_gender_breakdown(self, date_from: str, date_to: str) -> list[dict]:
        gaql = f"""
            SELECT
                ad_group_criterion.age_range_type,
                ad_group_criterion.gender.type,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.conversions_value
            FROM gender_view
            WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
        """
        rows = _query(self.client, self.customer_id, gaql)
        results = []
        gender_map = {"MALE": "male", "FEMALE": "female", "UNDETERMINED": "unknown"}
        for row in rows:
            spend = _micros_to_yen(row.metrics.cost_micros)
            conversions = round(row.metrics.conversions, 2)
            revenue = round(row.metrics.conversions_value, 2)
            kpi = _calc_kpi(spend, conversions, revenue)
            results.append({
                "age": "",
                "gender": gender_map.get(
                    str(row.ad_group_criterion.gender.type).split(".")[-1], "unknown"
                ),
                "spend": round(spend, 2),
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": conversions,
                "revenue": revenue,
                "cpa": kpi["cpa"],
                "roas": kpi["roas"],
            })
        return results

    def fetch_region_breakdown(self, date_from: str, date_to: str) -> list[dict]:
        gaql = f"""
            SELECT
                geographic_view.country_criterion_id,
                geographic_view.location_type,
                metrics.cost_micros,
                metrics.impressions,
                metrics.clicks,
                metrics.conversions,
                metrics.conversions_value
            FROM geographic_view
            WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
        """
        rows = _query(self.client, self.customer_id, gaql)
        results = []
        for row in rows:
            spend = _micros_to_yen(row.metrics.cost_micros)
            conversions = round(row.metrics.conversions, 2)
            revenue = round(row.metrics.conversions_value, 2)
            kpi = _calc_kpi(spend, conversions, revenue)
            results.append({
                "region": str(row.geographic_view.country_criterion_id),
                "spend": round(spend, 2),
                "impressions": row.metrics.impressions,
                "clicks": row.metrics.clicks,
                "conversions": conversions,
                "revenue": revenue,
                "cpa": kpi["cpa"],
                "roas": kpi["roas"],
            })
        return results

    def fetch_frequency(self, date_from: str, date_to: str) -> dict:
        """Google Adsではフリークエンシーはキャンペーンタイプにより制限あり"""
        try:
            gaql = f"""
                SELECT
                    metrics.average_frequency,
                    metrics.impressions
                FROM campaign
                WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
                  AND campaign.status != 'REMOVED'
            """
            rows = _query(self.client, self.customer_id, gaql)
            total_imp = sum(r.metrics.impressions for r in rows)
            # average_frequency はディスプレイ/動画キャンペーンのみ
            freqs = [r.metrics.average_frequency for r in rows if r.metrics.average_frequency > 0]
            avg_freq = sum(freqs) / len(freqs) if freqs else 0.0
            return {
                "frequency": round(avg_freq, 2),
                "reach": 0,  # Google Adsでは直接取得不可（Reach API別途必要）
                "impressions": total_imp,
            }
        except Exception:
            logger.warning("フリークエンシー取得に失敗")
            return {"frequency": 0.0, "reach": 0, "impressions": 0}

    def fetch_adset_targeting(self, adset_id: str) -> dict:
        """広告グループのターゲティング情報"""
        try:
            gaql = f"""
                SELECT
                    ad_group.id,
                    ad_group.name,
                    ad_group_criterion.keyword.text,
                    ad_group_criterion.keyword.match_type
                FROM ad_group_criterion
                WHERE ad_group.id = {adset_id}
                  AND ad_group_criterion.type = 'KEYWORD'
                  AND ad_group_criterion.status != 'REMOVED'
                LIMIT 20
            """
            rows = _query(self.client, self.customer_id, gaql)
            keywords = []
            for row in rows:
                kw = row.ad_group_criterion.keyword
                keywords.append(f"{kw.text} ({kw.match_type})")

            return {
                "age": "指定なし",
                "genders": "すべて",
                "locations": "日本",
                "interests": "、".join(keywords) if keywords else "キーワード情報なし",
            }
        except Exception:
            logger.warning("ターゲティング取得に失敗: adset_id=%s", adset_id)
            return {
                "age": "取得不可",
                "genders": "取得不可",
                "locations": "取得不可",
                "interests": "取得不可",
            }

    def fetch_ad_creative(self, ad_id: str) -> dict:
        """広告クリエイティブ情報（Google Adsでは制限あり）"""
        try:
            gaql = f"""
                SELECT
                    ad_group_ad.ad.id,
                    ad_group_ad.ad.final_urls,
                    ad_group_ad.ad.responsive_search_ad.headlines,
                    ad_group_ad.ad.responsive_search_ad.descriptions
                FROM ad_group_ad
                WHERE ad_group_ad.ad.id = {ad_id}
                LIMIT 1
            """
            rows = _query(self.client, self.customer_id, gaql)
            if not rows:
                return {"title": "", "body": "", "image_url": "", "thumbnail_url": ""}

            ad = rows[0].ad_group_ad.ad
            headlines = []
            descriptions = []

            if ad.responsive_search_ad:
                headlines = [h.text for h in (ad.responsive_search_ad.headlines or [])]
                descriptions = [d.text for d in (ad.responsive_search_ad.descriptions or [])]

            return {
                "title": " | ".join(headlines[:3]) if headlines else "",
                "body": " ".join(descriptions[:2]) if descriptions else "",
                "image_url": "",
                "thumbnail_url": "",
            }
        except Exception:
            logger.warning("クリエイティブ取得に失敗: ad_id=%s", ad_id)
            return {"title": "", "body": "", "image_url": "", "thumbnail_url": ""}
