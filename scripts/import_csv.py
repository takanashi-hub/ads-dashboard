"""ecforce CSVインポートスクリプト

ecforce管理画面からエクスポートした受注CSVをSQLiteに一括投入する。
初回データ投入用。以降の差分はsync_ecforce.pyが処理する。

使い方:
    python scripts/import_csv.py data/orders.csv
    python scripts/import_csv.py data/orders.csv --upload-gcs
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# プロジェクトルートをパスに追加
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB_PATH = PROJECT_ROOT / "db" / "orders.db"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _read_csv(filepath: Path) -> pd.DataFrame:
    """CSVを読み込む（cp932 → utf-8 フォールバック）"""
    for enc in ("cp932", "utf-8", "utf-8-sig"):
        try:
            df = pd.read_csv(filepath, encoding=enc, dtype=str)
            logger.info("CSV読み込み成功: %s (%s, %d行)", filepath.name, enc, len(df))
            return df
        except UnicodeDecodeError:
            continue
    raise ValueError(f"CSVのエンコーディングを判定できません: {filepath}")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """カラム名をDBスキーマに合わせて正規化"""
    col_map = {}
    for col in df.columns:
        cl = col.strip()
        # 受注ID
        if cl in ("受注ID", "受注番号", "注文番号", "id", "order_id", "order_number"):
            col_map[col] = "order_id"
        # 受注日
        elif cl in ("受注日", "注文日", "created_at", "order_date"):
            col_map[col] = "order_date"
        # 商品ID
        elif cl in ("商品ID", "product_id"):
            col_map[col] = "product_id"
        # 商品名
        elif cl in ("商品名", "product_name", "item_name"):
            col_map[col] = "product_name"
        # 数量
        elif cl in ("数量", "quantity"):
            col_map[col] = "quantity"
        # 単価
        elif cl in ("単価", "price", "unit_price"):
            col_map[col] = "price"
        # 合計金額
        elif cl in ("合計金額", "合計", "total", "total_price", "小計", "subtotal"):
            col_map[col] = "total"
        # 顧客ID
        elif cl in ("顧客ID", "customer_id"):
            col_map[col] = "customer_id"
        # ステータス
        elif cl in ("ステータス", "status", "state"):
            col_map[col] = "status"

    df = df.rename(columns=col_map)
    return df


def _ensure_table(conn: sqlite3.Connection) -> None:
    """ordersテーブルがなければ作成"""
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        order_id TEXT PRIMARY KEY,
        order_date TEXT NOT NULL,
        product_id TEXT,
        product_name TEXT,
        quantity INTEGER DEFAULT 1,
        price REAL DEFAULT 0,
        total REAL DEFAULT 0,
        customer_id TEXT,
        status TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_date ON orders(order_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_product ON orders(product_name)")
    conn.commit()


def import_csv(csv_path: Path, db_path: Path = DB_PATH) -> int:
    """CSVをSQLiteにインポート。戻り値は投入件数。"""
    df = _read_csv(csv_path)
    df = _normalize_columns(df)

    # 必須カラムチェック
    if "order_id" not in df.columns:
        # order_idがない場合は行番号で代替
        logger.warning("order_idカラムが見つかりません。行番号をIDとして使用します。")
        df["order_id"] = [f"csv_{i}" for i in range(len(df))]

    if "order_date" not in df.columns:
        raise ValueError("受注日カラムが見つかりません。CSVに「受注日」「注文日」「created_at」列が必要です。")

    # 日付正規化 (YYYY-MM-DD形式に)
    df["order_date"] = pd.to_datetime(df["order_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    df = df.dropna(subset=["order_date"])

    # 数値カラムの変換
    for col in ("quantity", "price", "total"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce").fillna(0)

    # DBスキーマのカラムのみ抽出
    db_columns = ["order_id", "order_date", "product_id", "product_name",
                   "quantity", "price", "total", "customer_id", "status"]
    existing_cols = [c for c in db_columns if c in df.columns]
    df = df[existing_cols]

    # SQLiteに投入
    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    _ensure_table(conn)

    inserted = 0
    skipped = 0
    for _, row in df.iterrows():
        try:
            placeholders = ", ".join(["?"] * len(existing_cols))
            col_names = ", ".join(existing_cols)
            conn.execute(
                f"INSERT OR REPLACE INTO orders ({col_names}) VALUES ({placeholders})",
                tuple(row[c] for c in existing_cols),
            )
            inserted += 1
        except Exception as e:
            skipped += 1
            if skipped <= 5:
                logger.warning("投入スキップ: %s", e)

    conn.commit()
    conn.close()

    logger.info("インポート完了: %d件投入, %d件スキップ (DB: %s)", inserted, skipped, db_path)
    return inserted


def main():
    parser = argparse.ArgumentParser(description="ecforce CSVをSQLiteにインポート")
    parser.add_argument("csv_path", help="CSVファイルパス")
    parser.add_argument("--db", default=str(DB_PATH), help=f"SQLiteパス (default: {DB_PATH})")
    parser.add_argument("--upload-gcs", action="store_true", help="インポート後にGCSにアップロード")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        logger.error("CSVファイルが見つかりません: %s", csv_path)
        sys.exit(1)

    db_path = Path(args.db)
    count = import_csv(csv_path, db_path)
    logger.info("合計 %d 件をインポートしました", count)

    if args.upload_gcs:
        from adapters.ecforce_db import upload_to_gcs
        upload_to_gcs(db_path)
        logger.info("GCSアップロード完了")


if __name__ == "__main__":
    main()
