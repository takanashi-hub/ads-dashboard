"""ecforce API クライアント（JSON:API v2）

API特性:
- 1リクエストあたり約10秒（per=100の場合）
- per=1でメタデータのみ取得すると約0.6秒
- 全件取得は非現実的なため、サンプリング＋メタデータ活用で高速化
"""

import logging
import os
import time
from collections import defaultdict
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://ysmd-online.jp/api/v2/admin"


class EcforceClient:
    """ecforce EC基幹システムの APIクライアント"""

    def __init__(self, product_ids: list[str] | None = None):
        self.token = os.environ.get("ECFORCE_API_TOKEN", "")
        self.password = os.environ.get("ECFORCE_API_PASSWORD", "")
        self.product_ids = product_ids  # 商品IDフィルタ（受注系APIに適用）
        if not self.token:
            raise RuntimeError("環境変数 ECFORCE_API_TOKEN が設定されていません")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        })
        if self.password:
            self.session.headers["X-Ecforce-Api-Password"] = self.password
        if self.product_ids:
            logger.info("ecforce: 商品フィルタ有効 (%d商品)", len(self.product_ids))

    # ------------------------------------------------------------------
    # 低レベル API
    # ------------------------------------------------------------------

    def _add_product_filter(self, params: dict) -> dict:
        """商品IDフィルタをparamsに追加"""
        if self.product_ids:
            params["q[order_items_product_id_in][]"] = self.product_ids
        return params

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        """単一APIリクエスト（429リトライ付き、30秒タイムアウト）"""
        url = f"{BASE_URL}/{endpoint}"
        max_retries = 5
        for attempt in range(max_retries):
            resp = self.session.get(url, params=params or {}, timeout=30)
            if resp.status_code == 429:
                wait = min(2 ** attempt * 3 + 5, 60)
                logger.warning("ecforce API rate limit (429). %d秒待機... (attempt %d/%d)", wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"ecforce API rate limit: {endpoint} ({max_retries}回リトライ後も失敗)")

    def _get_meta(self, endpoint: str, params: dict | None = None) -> dict:
        """メタデータのみ高速取得（per=1で0.6秒）"""
        params = dict(params or {})
        params["per"] = 1
        params["page"] = 1
        body = self._get(endpoint, params)
        return body.get("meta", {})

    def _get_page(
        self,
        endpoint: str,
        params: dict | None = None,
        per: int = 100,
        page: int = 1,
    ) -> dict:
        """指定ページを1ページ分取得"""
        params = dict(params or {})
        params["per"] = per
        params["page"] = page
        return self._get(endpoint, params)

    def _get_all_pages(
        self,
        endpoint: str,
        params: dict | None = None,
        max_pages: int = 5,
        per_page: int = 100,
    ) -> list[dict]:
        """ページネーション取得（max_pagesで上限制御）"""
        params = dict(params or {})
        params["per"] = per_page

        all_records = []
        for page in range(1, max_pages + 1):
            params["page"] = page
            body = self._get(endpoint, params)
            data = body.get("data", [])
            if not data:
                break
            for item in data:
                record = {"id": item.get("id")}
                record.update(item.get("attributes", {}))
                all_records.append(record)
            meta = body.get("meta", {})
            total_pages = meta.get("total_pages")
            if total_pages and page >= total_pages:
                break
            if len(data) < per_page:
                break
        return all_records

    def _get_all_pages_with_included(
        self,
        endpoint: str,
        params: dict | None = None,
        max_pages: int = 5,
        per_page: int = 100,
    ) -> tuple[list[dict], list[dict]]:
        """ページネーション取得 + included"""
        params = dict(params or {})
        params["per"] = per_page

        all_records = []
        all_included = []
        for page in range(1, max_pages + 1):
            params["page"] = page
            body = self._get(endpoint, params)
            data = body.get("data", [])
            if not data:
                break
            for item in data:
                record = {"id": item.get("id")}
                record.update(item.get("attributes", {}))
                all_records.append(record)
            for inc in body.get("included", []):
                inc_record = {"id": inc.get("id"), "type": inc.get("type")}
                inc_record.update(inc.get("attributes", {}))
                all_included.append(inc_record)
            meta = body.get("meta", {})
            total_pages = meta.get("total_pages")
            if total_pages and page >= total_pages:
                break
            if len(data) < per_page:
                break
        return all_records, all_included

    # ------------------------------------------------------------------
    # 受注データ（高速版）
    # ------------------------------------------------------------------

    def _fetch_day_meta(self, day_str: str) -> dict:
        """1日分の受注件数のみ高速取得（per=1、約0.6秒）"""
        params = {
            "q[created_at_gteq]": day_str,
            "q[created_at_lteq]": f"{day_str} 23:59:59",
        }
        self._add_product_filter(params)
        meta = self._get_meta("orders", params)
        return {
            "date": day_str,
            "order_count": meta.get("total_count", 0),
        }

    def _fetch_day_sample_amount(self, day_str: str) -> tuple[float, int]:
        """1日分のサンプル金額取得（per=100 × 1ページ、約10秒）"""
        params = {
            "q[created_at_gteq]": day_str,
            "q[created_at_lteq]": f"{day_str} 23:59:59",
        }
        self._add_product_filter(params)
        body = self._get_page("orders", params, per=100, page=1)
        data = body.get("data", [])
        amount = sum(
            float(d.get("attributes", {}).get("total", 0) or 0)
            for d in data
        )
        return amount, len(data)

    def fetch_orders_daily(self, date_from: str, date_to: str) -> list[dict]:
        """日別売上集計（2段階取得で高速化）

        Step1: 全日分をper=1でメタデータのみ取得（0.6秒×日数、逐次）
        Step2: 最大3日分をper=100でサンプル取得し、平均単価を算出
        Step3: 全日分の金額を平均単価×件数で推定

        7日 → ~8リクエスト ≈ 7-8秒、30日 → ~33リクエスト ≈ 25秒
        """
        d_from = date.fromisoformat(date_from)
        d_to = date.fromisoformat(date_to)
        days = [(d_from + timedelta(days=i)).isoformat()
                for i in range((d_to - d_from).days + 1)]

        # Step1: 全日分の件数を高速取得（逐次、per=1で各0.6秒）
        day_counts = {}
        for d in days:
            try:
                info = self._fetch_day_meta(d)
                day_counts[d] = info["order_count"]
            except Exception as e:
                logger.warning("日別件数取得エラー %s: %s", d, e)
                day_counts[d] = 0

        # Step2: 件数が多い上位3日からサンプル取得して平均単価算出
        sorted_days = sorted(day_counts.items(), key=lambda x: -x[1])
        sample_days = [d for d, c in sorted_days if c > 0][:3]

        total_sample_amount = 0.0
        total_sample_count = 0
        for d in sample_days:
            try:
                amount, count = self._fetch_day_sample_amount(d)
                total_sample_amount += amount
                total_sample_count += count
            except Exception as e:
                logger.warning("日別金額サンプル取得エラー %s: %s", d, e)

        avg_unit_price = (
            total_sample_amount / total_sample_count
            if total_sample_count > 0 else 0
        )

        # Step3: 件数×平均単価で全日の推定金額を算出
        results = []
        for d in days:
            count = day_counts.get(d, 0)
            results.append({
                "date": d,
                "order_count": count,
                "total_amount": round(avg_unit_price * count, 0),
            })

        return results

    def fetch_orders_by_product(self, date_from: str, date_to: str) -> list[dict]:
        """商品別売上（サンプル300件から構成比を算出）"""
        params = {
            "q[created_at_gteq]": date_from,
            "q[created_at_lteq]": f"{date_to} 23:59:59",
            "include": "order_items",
        }
        self._add_product_filter(params)
        _orders, included = self._get_all_pages_with_included(
            "orders", params, max_pages=3
        )

        product_sales = defaultdict(lambda: {"product_name": "", "quantity": 0, "amount": 0.0})
        for item in included:
            if item.get("type") not in ("order_item", "order_items"):
                continue
            name = item.get("product_name") or item.get("name") or "不明"
            qty = int(item.get("quantity", 1) or 1)
            price = float(item.get("price", 0) or item.get("subtotal", 0) or 0)
            product_sales[name]["product_name"] = name
            product_sales[name]["quantity"] += qty
            product_sales[name]["amount"] += price * qty if price < 100000 else price

        result = sorted(product_sales.values(), key=lambda x: -x["amount"])
        for r in result:
            r["amount"] = round(r["amount"], 0)
        return result

    def fetch_orders_raw(self, date_from: str, date_to: str, max_pages: int = 1) -> list[dict]:
        """受注一覧（最新100件、表示用）"""
        params = {
            "q[created_at_gteq]": date_from,
            "q[created_at_lteq]": f"{date_to} 23:59:59",
            "q[s]": "created_at desc",
        }
        self._add_product_filter(params)
        orders = self._get_all_pages("orders", params, max_pages=max_pages)

        return [
            {
                "受注ID": o.get("id", ""),
                "受注日": (o.get("created_at") or "")[:10],
                "合計金額": float(o.get("total", 0) or o.get("total_price", 0) or 0),
                "ステータス": o.get("status") or o.get("state") or "",
                "顧客名": o.get("customer_name") or o.get("name") or "",
            }
            for o in orders
        ]

    # ------------------------------------------------------------------
    # 顧客・LTVデータ（サンプリング）
    # ------------------------------------------------------------------

    def fetch_ltv_distribution(self, sample_pages: int = 5) -> list[dict]:
        """LTV分布（サンプル500件）"""
        customers = self._get_all_pages("customers", max_pages=sample_pages)

        bucket_ranges = [
            (0, 5000, "0-5,000"),
            (5000, 10000, "5,000-10,000"),
            (10000, 20000, "10,000-20,000"),
            (20000, 30000, "20,000-30,000"),
            (30000, 50000, "30,000-50,000"),
            (50000, 100000, "50,000-100,000"),
            (100000, float("inf"), "100,000+"),
        ]
        buckets = {label: 0 for _, _, label in bucket_ranges}

        for c in customers:
            ltv = float(
                c.get("total_order_amount", 0)
                or c.get("lifetime_value", 0)
                or c.get("total_spend", 0)
                or 0
            )
            for low, high, label in bucket_ranges:
                if low <= ltv < high:
                    buckets[label] += 1
                    break

        return [{"bucket": k, "count": v} for k, v in buckets.items()]

    def fetch_purchase_frequency(self, sample_pages: int = 5) -> list[dict]:
        """購入回数分布（サンプル500件）"""
        customers = self._get_all_pages("customers", max_pages=sample_pages)

        freq = defaultdict(int)
        for c in customers:
            count = int(
                c.get("order_count", 0)
                or c.get("orders_count", 0)
                or c.get("total_orders", 0)
                or 0
            )
            if count >= 10:
                freq["10回以上"] += 1
            else:
                freq[f"{count}回"] += 1

        order = ["0回", "1回", "2回", "3回", "4回", "5回", "6回", "7回", "8回", "9回", "10回以上"]
        return [{"frequency": k, "count": freq.get(k, 0)} for k in order if freq.get(k, 0) > 0]

    # ------------------------------------------------------------------
    # 定期購入データ（サンプリング）
    # ------------------------------------------------------------------

    def fetch_subscription_summary(self, sample_pages: int = 5) -> dict:
        """定期サマリー（サンプル500件）"""
        subs = self._get_all_pages("subs_orders", max_pages=sample_pages)

        summary = {"active": 0, "cancelled": 0, "paused": 0, "other": 0, "total": len(subs)}
        for s in subs:
            status = (s.get("status") or s.get("state") or "").lower()
            if status in ("active", "継続中", "enabled"):
                summary["active"] += 1
            elif status in ("cancelled", "canceled", "解約", "stopped"):
                summary["cancelled"] += 1
            elif status in ("paused", "休止", "suspended"):
                summary["paused"] += 1
            else:
                summary["other"] += 1

        if summary["total"] > 0:
            summary["retention_rate"] = round(
                summary["active"] / summary["total"] * 100, 1
            )
        else:
            summary["retention_rate"] = 0.0
        return summary

    def fetch_subscription_retention(self, sample_pages: int = 5) -> list[dict]:
        """回数別継続率カーブ（サンプル500件）"""
        subs = self._get_all_pages("subs_orders", max_pages=sample_pages)

        delivery_counts = defaultdict(int)
        max_delivery = 0
        for s in subs:
            count = int(
                s.get("delivery_count", 0)
                or s.get("deliveries_count", 0)
                or s.get("order_count", 0)
                or 0
            )
            delivery_counts[count] += 1
            max_delivery = max(max_delivery, count)

        if not delivery_counts:
            return []

        total = sum(delivery_counts.values())
        result = []
        for n in range(1, min(max_delivery + 1, 13)):
            reached = sum(c for d, c in delivery_counts.items() if d >= n)
            rate = round(reached / total * 100, 1) if total > 0 else 0
            result.append({"delivery_number": n, "retention_rate": rate, "count": reached})
        return result
