"""
MCC配下の全Google広告アカウントを一覧取得するスクリプト
使い方: ~/projects/ads-dashboard/ にコピーして実行
  python list_accounts.py
"""

import os
from google.ads.googleads.client import GoogleAdsClient


def get_all_accounts():
    """MCC配下の全子アカウントを取得"""

    # 環境変数から設定を読み込み
    credentials = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
        "use_proto_plus": True,
    }

    client = GoogleAdsClient.load_from_dict(credentials)
    ga_service = client.get_service("GoogleAdsService")

    # MCC (login_customer_id) 配下の全アカウントを取得
    mcc_id = os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"]

    query = """
        SELECT
            customer_client.client_customer,
            customer_client.id,
            customer_client.descriptive_name,
            customer_client.status,
            customer_client.manager
        FROM customer_client
        WHERE customer_client.manager = FALSE
    """

    response = ga_service.search(customer_id=mcc_id, query=query)

    print("=" * 70)
    print(f"MCC ({mcc_id}) 配下のアカウント一覧")
    print("=" * 70)
    print(f"{'Customer ID':<15} {'ステータス':<12} {'アカウント名'}")
    print("-" * 70)

    accounts = []
    for row in response:
        cc = row.customer_client
        status_str = cc.status.name  # ENABLED, SUSPENDED, CLOSED, etc.
        accounts.append({
            "id": str(cc.id),
            "name": cc.descriptive_name,
            "status": status_str,
        })
        print(f"{cc.id:<15} {status_str:<12} {cc.descriptive_name}")

    print("-" * 70)
    print(f"合計: {len(accounts)} アカウント")
    print()

    # 有効なアカウントだけ抽出
    enabled = [a for a in accounts if a["status"] == "ENABLED"]
    print(f"✅ 有効 (ENABLED): {len(enabled)} アカウント")
    for a in enabled:
        print(f"   {a['id']} - {a['name']}")

    print()

    # .env用の設定出力
    ids = ",".join(a["id"] for a in enabled)
    print("📋 環境変数に設定する値（ENABLED のみ）:")
    print(f"   GOOGLE_ADS_CUSTOMER_IDS='{ids}'")

    return accounts


if __name__ == "__main__":
    get_all_accounts()
