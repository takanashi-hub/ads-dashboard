"""ecforce 日次同期バッチ

Cloud Schedulerから毎晩3時JSTに起動。
GCSからDB取得 → ecforce APIで差分取得 → DB追記 → GCSアップロード → Slack通知。

使い方:
    python scripts/sync_ecforce.py                    # 差分同期（前回の翌日〜昨日）
    python scripts/sync_ecforce.py --from 2026-02-01  # 指定日から昨日まで
"""

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from adapters.ecforce_db import (
    GCS_BUCKET, GCS_DB_BLOB, CREATE_TABLE_SQL, CREATE_INDEX_SQL,
    download_from_gcs, upload_to_gcs,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

BASE_URL = "https://ysmd-online.jp/api/v2/admin"
REQUEST_SLEEP = 2  # リクエスト間のsleep（秒）
DB_PATH = Path("/tmp/orders.db")


# ------------------------------------------------------------------
# ecforce API
# ------------------------------------------------------------------

def _headers() -> dict:
    token = os.environ.get("ECFORCE_API_TOKEN", "")
    password = os.environ.get("ECFORCE_API_PASSWORD", "")
    if not token:
        raise RuntimeError("ECFORCE_API_TOKEN が未設定")
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if password:
        h["X-Ecforce-Api-Password"] = password
    return h


def _api_get(headers: dict, endpoint: str, params: dict) -> dict:
    """APIリクエスト（429リトライ付き）"""
    url = f"{BASE_URL}/{endpoint}"
    for attempt in range(3):
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        if resp.status_code == 429:
            wait = 30 * (attempt + 1)
            logger.warning("429 rate limit → %d秒待機 (attempt %d/3)", wait, attempt + 1)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"429 rate limit 解消せず: {endpoint}")


def fetch_orders_for_date(headers: dict, day_str: str) -> list[dict]:
    """1日分の受注を全ページ取得 → フラットなdict list"""
    params = {
        "q[created_at_gteq]": day_str,
        "q[created_at_lteq]": f"{day_str} 23:59:59",
        "include": "order_items",
        "per": 100,
    }
    all_rows = []
    page = 1

    while True:
        params["page"] = page
        body = _api_get(headers, "orders", params)
        data = body.get("data", [])
        included = body.get("included", [])

        # included → order_id ごとの order_items マッピング
        items_map: dict[str, list[dict]] = {}
        for inc in included:
            if inc.get("type") not in ("order_item", "order_items"):
                continue
            attrs = inc.get("attributes", {})
            rels = inc.get("relationships", {})
            oid = rels.get("order", {}).get("data", {}).get("id", "")
            if oid:
                items_map.setdefault(oid, []).append(attrs)

        for order in data:
            oid = order["id"]
            oa = order.get("attributes", {})
            order_date = (oa.get("created_at") or "")[:10]
            customer_id = (
                order.get("relationships", {})
                .get("customer", {}).get("data", {}).get("id", "")
            )

            items = items_map.get(oid, [])
            if items:
                for it in items:
                    all_rows.append({
                        "order_id": f"{oid}_{it.get('product_id', '')}",
                        "order_date": order_date,
                        "product_name": it.get("product_name") or it.get("name") or "",
                        "quantity": int(it.get("quantity", 1) or 1),
                        "price": int(float(it.get("price", 0) or 0)),
                        "total": int(float(it.get("subtotal", 0) or it.get("price", 0) or 0)),
                        "customer_id": customer_id,
                    })
            else:
                all_rows.append({
                    "order_id": oid,
                    "order_date": order_date,
                    "product_name": "",
                    "quantity": 1,
                    "price": int(float(oa.get("total", 0) or 0)),
                    "total": int(float(oa.get("total", 0) or 0)),
                    "customer_id": customer_id,
                })

        meta = body.get("meta", {})
        total_pages = meta.get("total_pages", 1)
        if page >= total_pages or len(data) < 100:
            break
        page += 1
        time.sleep(REQUEST_SLEEP)

    return all_rows


# ------------------------------------------------------------------
# DB操作
# ------------------------------------------------------------------

def _open_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute(CREATE_TABLE_SQL)
    for sql in CREATE_INDEX_SQL:
        conn.execute(sql)
    conn.commit()
    return conn


def _last_sync_date(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT MAX(order_date) FROM orders").fetchone()
    return row[0] if row and row[0] else None


def _insert(conn: sqlite3.Connection, rows: list[dict]) -> int:
    n = 0
    for r in rows:
        conn.execute(
            "INSERT OR REPLACE INTO orders "
            "(order_id, order_date, product_name, quantity, price, total, customer_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (r["order_id"], r["order_date"], r["product_name"],
             r["quantity"], r["price"], r["total"], r["customer_id"]),
        )
        n += 1
    conn.commit()
    return n


# ------------------------------------------------------------------
# Slack通知
# ------------------------------------------------------------------

def _notify_slack(msg: str) -> None:
    url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not url:
        return
    try:
        requests.post(url, json={"text": msg}, timeout=10)
    except Exception as e:
        logger.warning("Slack通知失敗: %s", e)


# ------------------------------------------------------------------
# メイン
# ------------------------------------------------------------------

def sync(date_from: str | None = None, date_to: str | None = None) -> dict:
    # 1. GCSからDB取得
    try:
        download_from_gcs(DB_PATH)
        logger.info("GCSからDB取得済み")
    except FileNotFoundError:
        logger.info("GCSにDBなし → 新規作成")
    except Exception as e:
        logger.warning("GCSダウンロード失敗（新規作成）: %s", e)

    conn = _open_db(DB_PATH)

    # 2. 同期範囲決定
    if not date_from:
        last = _last_sync_date(conn)
        date_from = (date.fromisoformat(last) + timedelta(days=1)).isoformat() if last else (date.today() - timedelta(days=7)).isoformat()
    if not date_to:
        date_to = (date.today() - timedelta(days=1)).isoformat()

    if date_from > date_to:
        logger.info("同期不要: %s > %s (最新)", date_from, date_to)
        conn.close()
        return {"status": "skip", "reason": "already up to date"}

    days = []
    d = date.fromisoformat(date_from)
    d_end = date.fromisoformat(date_to)
    while d <= d_end:
        days.append(d.isoformat())
        d += timedelta(days=1)

    logger.info("同期: %s → %s (%d日)", date_from, date_to, len(days))

    # 3. 日ごとにAPI取得→DB投入
    headers = _headers()
    total_inserted = 0
    for day_str in days:
        try:
            rows = fetch_orders_for_date(headers, day_str)
            n = _insert(conn, rows)
            total_inserted += n
            logger.info("  %s: %d件", day_str, n)
        except Exception as e:
            logger.error("  %s: エラー %s", day_str, e)
        time.sleep(REQUEST_SLEEP)

    conn.close()

    # 4. GCSにアップロード
    try:
        upload_to_gcs(DB_PATH)
    except Exception as e:
        logger.error("GCSアップロード失敗: %s", e)

    # 5. Slack通知
    _notify_slack(f"🔄 ecforce同期完了\n{date_from} → {date_to}\n{total_inserted}件追加")

    result = {
        "status": "ok",
        "date_from": date_from,
        "date_to": date_to,
        "inserted": total_inserted,
    }
    logger.info("完了: %s", json.dumps(result, ensure_ascii=False))
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="date_from")
    p.add_argument("--to", dest="date_to")
    args = p.parse_args()
    result = sync(args.date_from, args.date_to)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
