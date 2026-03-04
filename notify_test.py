"""
複数Google広告アカウント テストスクリプト
全アカウントからデータを取得してSlackに送信せず表示するだけ
"""

from config import get_adapters

def test():
    adapters = get_adapters()
    print(f"アダプター数: {len(adapters)}")
    print("-" * 50)

    for adapter in adapters:
        name = adapter.platform_name()
        print(f"\n📊 {name}")
        try:
            from datetime import datetime, timedelta
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            campaigns = adapter.fetch_campaigns(yesterday, yesterday)
            if campaigns:
                total_spend = sum(c.get("spend", 0) for c in campaigns)
                total_cv = sum(c.get("conversions", 0) for c in campaigns)
                print(f"   キャンペーン数: {len(campaigns)}")
                print(f"   合計費用: ¥{total_spend:,.0f}")
                print(f"   合計CV: {total_cv:.1f}件")
            else:
                print("   データなし（費用0円の可能性）")
        except Exception as e:
            print(f"   ❌ エラー: {e}")

    print("\n" + "=" * 50)
    print("✅ テスト完了")

if __name__ == "__main__":
    test()
