"""ecforce 初回データ投入スクリプト

過去90日分の受注をecforce APIから取得してSQLiteに投入し、GCSにアップロード。
1リクエストごとに3秒sleepでレート制限を回避。
1日で取りきれなければ中断→再実行で差分を取得。

使い方:
    python scripts/init_db.py                     # 過去90日
    python scripts/init_db.py --days 30            # 過去30日
    python scripts/init_db.py --from 2025-12-01    # 指定日から昨日まで
"""

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sync_ecforce import sync

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main():
    p = argparse.ArgumentParser(description="ecforce 初回データ投入")
    p.add_argument("--days", type=int, default=90, help="過去N日分 (default: 90)")
    p.add_argument("--from", dest="date_from", help="開始日 (YYYY-MM-DD)")
    p.add_argument("--to", dest="date_to", help="終了日 (default: 昨日)")
    args = p.parse_args()

    date_from = args.date_from or (date.today() - timedelta(days=args.days)).isoformat()
    date_to = args.date_to or (date.today() - timedelta(days=1)).isoformat()

    logger.info("初回投入: %s → %s", date_from, date_to)
    result = sync(date_from=date_from, date_to=date_to)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
