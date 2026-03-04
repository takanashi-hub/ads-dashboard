# 📊 広告ダッシュボード + Slack日次通知

Meta広告のKPIをWebダッシュボードで確認し、毎朝Slackに日次レポートを自動通知するシステム。

## 機能

- **ダッシュボード（Streamlit）**: KPIサマリー、キャンペーン別パフォーマンス、日別推移グラフ、広告セット/広告ドリルダウン
- **Slack通知（Flask）**: 毎朝9時に日次レポートを自動投稿、オンデマンド投稿も可能
- **プラグイン設計**: Meta広告に加え、将来Google Adsも追加可能

## リポジトリ構成

```
ads-dashboard/
├── app.py                  # Streamlit ダッシュボード
├── notify.py               # Flask: Slack通知エンドポイント
├── adapters/
│   ├── __init__.py
│   ├── base.py             # アダプター基底クラス
│   ├── meta.py             # Meta Marketing API アダプター
│   └── google_ads.py       # Google Ads アダプター（スタブ）
├── config.py               # 設定・プラットフォーム切り替え
├── formatter.py            # Slack投稿の整形
├── requirements.txt
├── Dockerfile              # ダッシュボード用
└── Dockerfile.notify       # Slack通知用
```

## 環境変数

| 変数名 | 説明 | 例 |
|--------|------|-----|
| `META_ACCESS_TOKEN` | Meta長期アクセストークン（60日有効） | `EAAG...` |
| `META_AD_ACCOUNT_ID` | Meta広告アカウントID | `act_374762540327537` |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL | `https://hooks.slack.com/services/...` |
| `ENABLED_PLATFORMS` | 有効プラットフォーム（カンマ区切り） | `meta` |
| `TZ` | タイムゾーン | `Asia/Tokyo` |

## ローカル起動

### 前提条件

```bash
pip install -r requirements.txt
```

### 環境変数の設定

```bash
export META_ACCESS_TOKEN="your_meta_token"
export META_AD_ACCOUNT_ID="act_374762540327537"
export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/xxx/yyy/zzz"
export ENABLED_PLATFORMS="meta"
export TZ="Asia/Tokyo"
```

### ダッシュボード起動

```bash
streamlit run app.py
```

ブラウザで http://localhost:8501 にアクセス。

### Slack通知サーバ起動

```bash
python notify.py
```

手動通知テスト:

```bash
# 昨日分のレポートを投稿
curl -X POST http://localhost:8080/notify

# 日付指定で投稿
curl -X POST http://localhost:8080/notify \
  -H "Content-Type: application/json" \
  -d '{"date": "2026-02-17"}'

# ヘルスチェック
curl http://localhost:8080/health
```

## Cloud Run デプロイ

### 1. ダッシュボード

```bash
gcloud run deploy ads-dashboard \
  --source . \
  --dockerfile Dockerfile \
  --region asia-northeast1 \
  --set-env-vars "META_ACCESS_TOKEN=xxx,META_AD_ACCOUNT_ID=act_374762540327537,ENABLED_PLATFORMS=meta,TZ=Asia/Tokyo"
```

### 2. Slack通知

```bash
gcloud run deploy ads-notifier \
  --source . \
  --dockerfile Dockerfile.notify \
  --region asia-northeast1 \
  --set-env-vars "META_ACCESS_TOKEN=xxx,META_AD_ACCOUNT_ID=act_374762540327537,SLACK_WEBHOOK_URL=xxx,ENABLED_PLATFORMS=meta,TZ=Asia/Tokyo"
```

### 3. Cloud Scheduler（毎朝9時 JST）

```bash
# Cloud Runサービスの URL を取得
NOTIFIER_URL=$(gcloud run services describe ads-notifier --region asia-northeast1 --format='value(status.url)')

# OIDCトークン用のサービスアカウントを作成
gcloud iam service-accounts create ads-scheduler-sa \
  --display-name="Ads Scheduler Service Account"

# Cloud Run の起動権限を付与
gcloud run services add-iam-policy-binding ads-notifier \
  --region asia-northeast1 \
  --member="serviceAccount:ads-scheduler-sa@YOUR_PROJECT.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Scheduler ジョブを作成
gcloud scheduler jobs create http ads-daily-report \
  --schedule="0 9 * * *" \
  --time-zone="Asia/Tokyo" \
  --uri="${NOTIFIER_URL}/notify" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --oidc-service-account-email="ads-scheduler-sa@YOUR_PROJECT.iam.gserviceaccount.com"
```

## Metaトークン更新手順（60日ごと）

Metaの長期トークンは60日で期限切れになります。以下の手順で更新してください。

### 1. 新しい長期トークンを取得

[Facebook Graph API Explorer](https://developers.facebook.com/tools/explorer/) で:
1. アプリを選択
2. 必要な権限を追加: `ads_read`, `ads_management`
3. 「Generate Access Token」をクリック
4. 短期トークンを長期トークンに交換:

```bash
curl "https://graph.facebook.com/v23.0/oauth/access_token?\
grant_type=fb_exchange_token&\
client_id=YOUR_APP_ID&\
client_secret=YOUR_APP_SECRET&\
fb_exchange_token=SHORT_LIVED_TOKEN"
```

### 2. Cloud Run の環境変数を更新

```bash
# ダッシュボード
gcloud run services update ads-dashboard \
  --region asia-northeast1 \
  --set-env-vars "META_ACCESS_TOKEN=NEW_TOKEN"

# 通知サービス
gcloud run services update ads-notifier \
  --region asia-northeast1 \
  --set-env-vars "META_ACCESS_TOKEN=NEW_TOKEN"
```

## Google Ads 追加手順（将来）

1. `google-ads` パッケージをインストール:
   ```bash
   pip install google-ads
   ```
   `requirements.txt` にも追加。

2. `adapters/google_ads.py` のスタブを実装に差し替え。

3. 環境変数を追加:
   ```
   GOOGLE_ADS_DEVELOPER_TOKEN=xxx
   GOOGLE_ADS_CLIENT_ID=xxx
   GOOGLE_ADS_CLIENT_SECRET=xxx
   GOOGLE_ADS_REFRESH_TOKEN=xxx
   GOOGLE_ADS_CUSTOMER_ID=xxx
   ```

4. `ENABLED_PLATFORMS` を更新:
   ```
   ENABLED_PLATFORMS=meta,google_ads
   ```

5. 再デプロイすると、ダッシュボードにプラットフォーム選択が自動追加されます。
