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


# Meta広告 マルチアカウント設定
# {account_id: 表示名} の辞書
# account_id が空文字の場合は環境変数 META_AD_ACCOUNT_ID を使用
META_AD_ACCOUNTS = {
    "": "Meta広告",
    "act_1969418190300504": "Meta広告（おてて）",
}

# Google広告 認証情報セット
# "default" = MCC経由、"satellite" = 別OAuth（サテライト/サブアカウント用）
GOOGLE_ADS_CREDENTIAL_SETS = {
    "default": {
        "client_id_env": "GOOGLE_ADS_CLIENT_ID",
        "client_secret_env": "GOOGLE_ADS_CLIENT_SECRET",
        "refresh_token_env": "GOOGLE_ADS_REFRESH_TOKEN",
        "login_customer_id_env": "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    },
    "satellite": {
        "client_id_env": "GOOGLE_ADS_CLIENT_ID_SAT",
        "client_secret_env": "GOOGLE_ADS_CLIENT_SECRET_SAT",
        "refresh_token_env": "GOOGLE_ADS_REFRESH_TOKEN_SAT",
        "login_customer_id_env": "GOOGLE_ADS_LOGIN_CUSTOMER_ID_SAT",
    },
}

# Google広告 マルチアカウント設定
# credentials: "default"=MCC経由, "satellite"=別OAuth
GOOGLE_ADS_ACCOUNTS = {
    "4939499325": {"name": "Google広告（KADASON）", "credentials": "default"},
    "9347491156": {"name": "Google広告（TURN）", "credentials": "default"},
    "1667812509": {"name": "Google広告（TURN_2）", "credentials": "satellite", "login_customer_id": "1667812509"},
    "7036229117": {"name": "Google広告（強心薬）", "credentials": "default"},
    "6539036392": {"name": "Google広告（強心薬サブ）", "credentials": "satellite", "login_customer_id": "6539036392"},
    "5627644401": {"name": "Google広告（おてて）", "credentials": "default"},
    "6230156344": {"name": "Google広告（KADASONサテライト）", "credentials": "satellite", "login_customer_id": "6230156344"},
    "3104136786": {"name": "Google広告（おててサブ（サテライト））", "credentials": "satellite", "login_customer_id": "3104136786"},
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
                # Google広告は複数アカウント対応（認証情報セット別）
                for cid, acct_info in GOOGLE_ADS_ACCOUNTS.items():
                    cred_set = dict(GOOGLE_ADS_CREDENTIAL_SETS[acct_info["credentials"]])
                    # アカウント固有のlogin_customer_idがあれば上書き
                    if "login_customer_id" in acct_info:
                        cred_set["login_customer_id_override"] = acct_info["login_customer_id"]
                    adapters.append(cls(
                        customer_id=cid,
                        account_name=acct_info["name"],
                        credential_set=cred_set,
                    ))
            elif name == "meta":
                # Meta広告は複数アカウント対応
                for aid, display_name in META_AD_ACCOUNTS.items():
                    adapters.append(cls(account_id=aid, account_name=display_name))
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
