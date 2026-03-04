"""設定・プラットフォーム切り替え"""

import os

# KADASONスカルプシャンプー関連の全商品ID（定期・セット・プロモーション含む）
KADASON_SHAMPOO_PRODUCT_IDS = [
    "72215", "60217", "60216", "60215", "44215", "40215",
    "32217", "32216", "32215", "28216", "8219",
    "182", "165", "164", "148", "147", "146", "144", "142", "141",
    "98", "97", "63", "62", "61", "53", "44", "40", "39", "38", "19",
]

from adapters.meta import MetaAdsAdapter
from adapters.google_ads import GoogleAdsAdapter


# Google広告 マルチアカウント設定
# {customer_id: 表示名} の辞書
# アカウントを追加/削除する場合はここを編集
GOOGLE_ADS_ACCOUNTS = {
    "4939499325": "Google広告（KADASON）",
    "9347491156": "Google広告（TURN）",
    "1667812509": "Google広告（TURN_2）",
    "7036229117": "Google広告（強心薬）",
    "6539036392": "Google広告（強心薬サブ）",
    "5627644401": "Google広告（おてて）",
    "6230156344": "Google広告（KADASONサテライト）",
}

ADAPTER_MAP = {
    "meta": MetaAdsAdapter,
    "google_ads": GoogleAdsAdapter,
}


def get_enabled_platforms() -> list[str]:
    """有効なプラットフォーム名のリストを返す"""
    raw = os.environ.get("ENABLED_PLATFORMS", "meta")
    return [p.strip() for p in raw.split(",") if p.strip()]


def get_adapters() -> list:
    """有効なアダプターのインスタンスをリストで返す"""
    platforms = get_enabled_platforms()
    adapters = []
    for name in platforms:
        cls = ADAPTER_MAP.get(name)
        if cls:
            if name == "google_ads":
                # Google広告は複数アカウント対応
                for cid, display_name in GOOGLE_ADS_ACCOUNTS.items():
                    adapters.append(cls(customer_id=cid, account_name=display_name))
            else:
                adapters.append(cls())
        else:
            raise ValueError(f"不明なプラットフォーム: {name}")
    return adapters


def get_ecforce_client():
    """ECFORCE_API_TOKEN設定時のみクライアント返却、未設定時None"""
    if not os.environ.get("ECFORCE_API_TOKEN"):
        return None
    from adapters.ecforce import EcforceClient
    return EcforceClient(product_ids=KADASON_SHAMPOO_PRODUCT_IDS)
