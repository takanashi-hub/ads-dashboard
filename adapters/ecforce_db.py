"""ecforce SQLite読み取りアダプター

ダッシュボード表示用。APIは叩かず、SQLiteからSELECTするだけ。
バッチ(scripts/sync_ecforce.py)が毎晩データを更新する。

Cloud Run: 起動時にGCSからorders.dbを/tmpにダウンロード
ローカル: db/orders.db を直接参照
"""

import logging
import os
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

GCS_BUCKET = os.environ.get("GCS_BUCKET", "ysmd-ads-dashboard-data")
GCS_DB_BLOB = "orders.db"

_LOCAL_DB = Path(__file__).resolve().parent.parent / "db" / "orders.db"
_TMP_DB = Path("/tmp/orders.db")

# テーブル定義（sync/init_dbでも使う）
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    order_date TEXT NOT NULL,
    product_name TEXT,
    quantity INTEGER DEFAULT 1,
    price INTEGER DEFAULT 0,
    total INTEGER DEFAULT 0,
    customer_id TEXT,
    synced_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""
CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date)",
    "CREATE INDEX IF NOT EXISTS idx_orders_product ON orders(product_name)",
]


# ------------------------------------------------------------------
# DB パス解決 & GCS
# ------------------------------------------------------------------

def _resolve_db_path() -> Path:
    """ローカル優先 → /tmp → GCSダウンロード"""
    if _LOCAL_DB.exists():
        return _LOCAL_DB
    if _TMP_DB.exists():
        return _TMP_DB
    try:
        download_from_gcs()
        return _TMP_DB
    except Exception as e:
        logger.warning("GCSからDBダウンロード失敗: %s", e)
    return _LOCAL_DB


def download_from_gcs(dest: Path = _TMP_DB) -> None:
    """GCSからorders.dbをダウンロード"""
    from google.cloud import storage
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(GCS_DB_BLOB)
    if not blob.exists():
        raise FileNotFoundError(f"gs://{GCS_BUCKET}/{GCS_DB_BLOB} が存在しません")
    blob.download_to_filename(str(dest))
    logger.info("GCS → %s (%d bytes)", dest, dest.stat().st_size)


def upload_to_gcs(db_path: str | Path | None = None) -> None:
    """DBファイルをGCSにアップロード"""
    from google.cloud import storage
    db_path = Path(db_path) if db_path else _resolve_db_path()
    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blob = bucket.blob(GCS_DB_BLOB)
    blob.upload_from_filename(str(db_path))
    logger.info("GCS ← %s", db_path)


def ensure_table(conn: sqlite3.Connection) -> None:
    """ordersテーブルを作成（存在しなければ）"""
    conn.execute(CREATE_TABLE_SQL)
    for sql in CREATE_INDEX_SQL:
        conn.execute(sql)
    conn.commit()


# ------------------------------------------------------------------
# 接続
# ------------------------------------------------------------------

def _conn() -> sqlite3.Connection:
    db_path = _resolve_db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


# ------------------------------------------------------------------
# 読み取りクエリ（ダッシュボード用）
# ------------------------------------------------------------------

def has_data() -> bool:
    """DBにデータがあるか"""
    db_path = _resolve_db_path()
    if not db_path.exists():
        return False
    try:
        with _conn() as c:
            row = c.execute("SELECT COUNT(*) FROM orders").fetchone()
            return row[0] > 0
    except Exception:
        return False


def get_date_range() -> tuple[str, str] | None:
    """DB内の最小・最大日付"""
    with _conn() as c:
        row = c.execute("SELECT MIN(order_date), MAX(order_date) FROM orders").fetchone()
        if row[0]:
            return row[0], row[1]
    return None


def get_orders_summary(date_from: str, date_to: str) -> dict:
    """受注サマリー → {order_count, total_amount, avg_price}"""
    with _conn() as c:
        row = c.execute("""
            SELECT COUNT(DISTINCT order_id) AS order_count,
                   COALESCE(SUM(total), 0) AS total_amount
            FROM orders
            WHERE order_date BETWEEN ? AND ?
        """, (date_from, date_to)).fetchone()
    count = row["order_count"]
    total = row["total_amount"]
    return {
        "order_count": count,
        "total_amount": total,
        "avg_price": round(total / count) if count > 0 else 0,
    }


def get_orders_daily(date_from: str, date_to: str) -> list[dict]:
    """日別集計 → [{date, order_count, total_amount}]"""
    with _conn() as c:
        rows = c.execute("""
            SELECT order_date AS date,
                   COUNT(DISTINCT order_id) AS order_count,
                   COALESCE(SUM(total), 0) AS total_amount
            FROM orders
            WHERE order_date BETWEEN ? AND ?
            GROUP BY order_date
            ORDER BY order_date
        """, (date_from, date_to)).fetchall()
    return [dict(r) for r in rows]


def get_orders_by_product(date_from: str, date_to: str, limit: int = 20) -> list[dict]:
    """商品別集計 → [{product_name, quantity, amount}]"""
    with _conn() as c:
        rows = c.execute("""
            SELECT product_name,
                   SUM(quantity) AS quantity,
                   COALESCE(SUM(total), 0) AS amount
            FROM orders
            WHERE order_date BETWEEN ? AND ?
            GROUP BY product_name
            ORDER BY amount DESC
            LIMIT ?
        """, (date_from, date_to, limit)).fetchall()
    return [dict(r) for r in rows]


def get_orders_raw(date_from: str, date_to: str, limit: int = 100) -> list[dict]:
    """受注一覧（最新N件）"""
    with _conn() as c:
        rows = c.execute("""
            SELECT order_id AS "受注ID",
                   order_date AS "受注日",
                   total AS "合計金額",
                   product_name AS "商品名"
            FROM orders
            WHERE order_date BETWEEN ? AND ?
            ORDER BY order_date DESC, order_id DESC
            LIMIT ?
        """, (date_from, date_to, limit)).fetchall()
    return [dict(r) for r in rows]
