"""
複数Google広告アカウント対応セットアップスクリプト
使い方: ~/projects/ads-dashboard/ にコピーして実行
  python3 setup_multi_accounts.py

このスクリプトは以下を自動修正します:
1. adapters/google_ads.py - 複数アカウント対応
2. config.py - アカウントリスト追加
3. ~/.zshrc - 環境変数追加
"""

import os
import re

ADS_DASHBOARD_DIR = os.path.expanduser("~/projects/ads-dashboard")

# ============================================================
# 1. adapters/google_ads.py の修正
# ============================================================
def patch_google_ads():
    filepath = os.path.join(ADS_DASHBOARD_DIR, "adapters", "google_ads.py")
    with open(filepath, "r") as f:
        content = f.read()

    # --- 修正1: __init__ に customer_id と account_name を追加 ---
    old_init = '''    def __init__(self):
        self._client: Optional[GoogleAdsClient] = None'''

    new_init = '''    def __init__(self, customer_id: str = None, account_name: str = None):
        self._client: Optional[GoogleAdsClient] = None
        self._customer_id_override = customer_id
        self._account_name = account_name or "Google広告"'''

    if old_init in content:
        content = content.replace(old_init, new_init)
        print("  ✅ __init__ を複数アカウント対応に修正")
    else:
        print("  ⚠️ __init__ のパターンが一致しません（既に修正済み？）")

    # --- 修正2: customer_id プロパティを変更 ---
    old_cid = '''    @property
    def customer_id(self) -> str:
        return _get_customer_id()'''

    new_cid = '''    @property
    def customer_id(self) -> str:
        if self._customer_id_override:
            return self._customer_id_override
        return _get_customer_id()'''

    if old_cid in content:
        content = content.replace(old_cid, new_cid)
        print("  ✅ customer_id プロパティを修正")
    else:
        print("  ⚠️ customer_id のパターンが一致しません（既に修正済み？）")

    # --- 修正3: platform_name にアカウント名を追加 ---
    old_name = '''    def platform_name(self) -> str:
        return "Google広告"'''

    new_name = '''    def platform_name(self) -> str:
        return self._account_name or "Google広告"'''

    if old_name in content:
        content = content.replace(old_name, new_name)
        print("  ✅ platform_name にアカウント名対応を追加")
    else:
        print("  ⚠️ platform_name のパターンが一致しません（既に修正済み？）")

    with open(filepath, "w") as f:
        f.write(content)
    print(f"  💾 {filepath} を保存しました")


# ============================================================
# 2. config.py の修正
# ============================================================
def patch_config():
    filepath = os.path.join(ADS_DASHBOARD_DIR, "config.py")
    with open(filepath, "r") as f:
        content = f.read()

    # --- 修正1: アカウント定義を追加 ---
    # import の後に GOOGLE_ADS_ACCOUNTS を追加
    account_config = '''
# Google広告 マルチアカウント設定
# {customer_id: 表示名} の辞書
# アカウントを追加/削除する場合はここを編集
GOOGLE_ADS_ACCOUNTS = {
    "4939499325": "Google広告（KADASON）",
    "6230156344": "Google広告（KADASONサテライト）",
    "9347491156": "Google広告（TURN）",
    "5627644401": "Google広告（おてて）",
    "7036229117": "Google広告（強心薬）",
}
'''

    if "GOOGLE_ADS_ACCOUNTS" not in content:
        # ADAPTER_MAP の前に挿入
        content = content.replace(
            "ADAPTER_MAP = {",
            account_config + "\nADAPTER_MAP = {"
        )
        print("  ✅ GOOGLE_ADS_ACCOUNTS を追加")
    else:
        print("  ⚠️ GOOGLE_ADS_ACCOUNTS は既に存在します")

    # --- 修正2: get_adapters を複数アカウント対応に変更 ---
    old_get_adapters = '''def get_adapters() -> list:
    """有効なアダプターのインスタンスをリストで返す"""
    platforms = get_enabled_platforms()
    adapters = []
    for name in platforms:
        cls = ADAPTER_MAP.get(name)
        if cls:
            adapters.append(cls())
        else:
            raise ValueError(f"不明なプラットフォーム: {name}")
    return adapters'''

    new_get_adapters = '''def get_adapters() -> list:
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
    return adapters'''

    if old_get_adapters in content:
        content = content.replace(old_get_adapters, new_get_adapters)
        print("  ✅ get_adapters を複数アカウント対応に修正")
    else:
        print("  ⚠️ get_adapters のパターンが一致しません（既に修正済み？）")

    with open(filepath, "w") as f:
        f.write(content)
    print(f"  💾 {filepath} を保存しました")


# ============================================================
# 3. notify.py の修正
# ============================================================
def patch_notify():
    filepath = os.path.join(ADS_DASHBOARD_DIR, "notify.py")
    with open(filepath, "r") as f:
        content = f.read()

    # キャンペーン別内訳の条件を修正
    # "Google広告" 完全一致 → "Google広告" を含むかどうかに変更
    old_check = 'if adapter.platform_name() == "Google広告":'
    new_check = 'if "Google広告" in adapter.platform_name():'

    if old_check in content:
        content = content.replace(old_check, new_check)
        print("  ✅ キャンペーン内訳の条件を修正（部分一致に変更）")
    else:
        print("  ⚠️ platform_name チェックのパターンが一致しません（既に修正済み？）")

    with open(filepath, "w") as f:
        f.write(content)
    print(f"  💾 {filepath} を保存しました")


# ============================================================
# 4. ~/.zshrc に環境変数追加（GOOGLE_ADS_CUSTOMER_ID は残す ← 互換性のため）
# ============================================================
def patch_zshrc():
    zshrc_path = os.path.expanduser("~/.zshrc")
    with open(zshrc_path, "r") as f:
        content = f.read()

    if "GOOGLE_ADS_CUSTOMER_IDS" not in content:
        ids = "4939499325,6230156344,9347491156,5627644401,7036229117"
        addition = f"\n# Google Ads 複数アカウント（カンマ区切り）\nexport GOOGLE_ADS_CUSTOMER_IDS='{ids}'\n"
        with open(zshrc_path, "a") as f:
            f.write(addition)
        print("  ✅ ~/.zshrc に GOOGLE_ADS_CUSTOMER_IDS を追加")
    else:
        print("  ⚠️ GOOGLE_ADS_CUSTOMER_IDS は既に存在します")


# ============================================================
# メイン
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🔧 複数Google広告アカウント対応セットアップ")
    print("=" * 60)

    # バックアップ作成
    import shutil
    for fname in ["adapters/google_ads.py", "config.py", "notify.py"]:
        src = os.path.join(ADS_DASHBOARD_DIR, fname)
        bak = src + ".bak_multi"
        if os.path.exists(src) and not os.path.exists(bak):
            shutil.copy2(src, bak)
            print(f"📁 バックアップ: {bak}")

    print("\n--- adapters/google_ads.py ---")
    patch_google_ads()

    print("\n--- config.py ---")
    patch_config()

    print("\n--- notify.py ---")
    patch_notify()

    print("\n--- ~/.zshrc ---")
    patch_zshrc()

    print("\n" + "=" * 60)
    print("✅ セットアップ完了！")
    print()
    print("次のステップ:")
    print("  1. source ~/.zshrc")
    print("  2. python3 notify_test.py  （テスト実行）")
    print("=" * 60)
