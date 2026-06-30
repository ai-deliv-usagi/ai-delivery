# ai-delivery

Minecraft 配信向けの AI 実況システムです。

Cloud Run 側で Gemini による実況生成と VOICEVOX 音声合成を行い、ローカル PC 側の `local_agent` が Minecraft 画面キャプチャ、TikTok Live イベント受信、音声再生を担当します。

## 構成

Cloud 側は Cloud Run で動かします。

- `ai-delivery-app`: Flask ダッシュボード、Gemini 実況生成、イベント API、フレーム API
- `ai-delivery-voicevox`: VOICEVOX Engine
- Cloud Storage bucket: セッション状態などの保存先
- Vertex AI Gemini: Cloud Run のサービスアカウント認証で利用

TikTok Live の接続、Minecraft 画面キャプチャ、音声再生は Cloud Run ではなくローカル PC で実行します。Cloud Run は長時間 WebSocket 接続やローカル音声再生を持たない前提です。

## GCP デプロイ

Terraform は `infra/terraform` にあります。通常は repo ルートで次を実行します。

```powershell
.\scripts\deploy-gcp.ps1 `
  -ProjectId "gen-lang-client-0496284195" `
  -Region "asia-northeast1"
```

このスクリプトは、必要な GCP API を有効化し、Terraform を適用してから、ローカルソースを Cloud Build 経由で Cloud Run にデプロイします。

Gemini は Vertex AI のサービスアカウント認証を使うため、Gemini API key や Secret Manager の値は不要です。

主な調整パラメータ:

```powershell
.\scripts\deploy-gcp.ps1 `
  -ProjectId "gen-lang-client-0496284195" `
  -Region "asia-northeast1" `
  -VoicevoxMaxTextChars 200 `
  -SessionIdleTimeoutSeconds 180 `
  -JackDurationSeconds 120
```

`VOICEVOX_MAX_TEXT_CHARS` は VOICEVOX に送る最大文字数です。デフォルトは 200 文字です。

`SESSION_IDLE_TIMEOUT_SECONDS` は、フレームや TikTok イベントが来なくなったあと Cloud 側セッションを自動停止するまでの秒数です。デフォルトは 180 秒です。

`JACK_DURATION_SECONDS` は人格ジャックが継続する秒数です。デフォルトは 120 秒です。

## ローカル agent の起動

初回はローカル環境を作ります。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-local.txt
```

Cloud Run の URL と TikTok ID を設定して起動します。

```powershell
$env:CLOUD_APP_URL = "https://your-ai-delivery-app-url"
$env:TIKTOK_UNIQUE_ID = "@your_tiktok_id"
python -m local_agent.main
```

`local_agent` は起動時に Cloud 側セッションを開始し、終了時に停止します。

実行中は次を行います。

- Minecraft の画面をキャプチャして `/api/frames` に送信
- TikTok Live のコメント、ギフト、フォロー、入室イベントを `/api/events` に送信
- Cloud 側から返ってきた VOICEVOX 音声をローカル PC で再生

音声再生は非同期です。再生中でもフレーム送信と TikTok イベント送信は続きます。再生中のフレームには `playback_busy=1` が付き、Cloud 側はコメント生成を一時的に抑えつつ、最新の視聴者イベントだけを次の生成へ混ぜます。

## セッションと監視

Cloud Run app はリクエスト駆動です。コンテナ起動時に自動で配信ループを開始しません。

配信セッション中だけ軽いバックグラウンドループを動かし、ギフトキュー、人格ジャックの残り時間、ダッシュボード状態を更新します。

セッション状態は Cloud Storage の `state/stream-session.json` に保存されます。Cloud Run インスタンスが再起動しても、次のリクエストでセッション中フラグ、人格ジャック状態、残り時間、ギフトキュー、未処理コンテキストを復元できます。

状態確認:

```powershell
$env:CLOUD_APP_URL = "https://your-ai-delivery-app-url"

curl "$env:CLOUD_APP_URL/api/status"
curl -X POST "$env:CLOUD_APP_URL/api/session/start"
curl -X POST "$env:CLOUD_APP_URL/api/session/stop"
```

`/api/status` には `is_online`、`idle_seconds`、`session_idle_timeout_seconds` が含まれます。

iPhone ショートカットなどから監視する場合も、`GET /api/status` は idle timer をリセットしません。

```text
GET  https://your-ai-delivery-app-url/api/status
POST https://your-ai-delivery-app-url/api/session/stop
```

## Cloud Run の起動コスト方針

`min_instance_count=1` にすると、使っていない時間も Cloud Run インスタンスを常に温めます。

このプロジェクトの利用頻度が「4〜5日に1回、1時間程度」なら、VOICEVOX を常時起動する費用対効果は低いです。基本方針は `min_instance_count=0` のままにして、配信開始直後の初回だけコールドスタートを許容します。

初回遅延が気になる場合は、配信直前に短いテスト発話を流して VOICEVOX を起こす運用が現実的です。

## VOICEVOX 音声

VOICEVOX は Cloud Run の別サービスとして動きます。

app サービスは `VOICEVOX_URL/audio_query` と `VOICEVOX_URL/synthesis` を呼び、生成された WAV を `/api/frames` のレスポンスで base64 として返します。

音声再生はローカル PC の `local_agent` が担当します。

## TikTok 設定

`TIKTOK_UNIQUE_ID` は Secret Manager や Cloud Run には置きません。ローカル環境変数またはローカル `.env` に設定します。

```powershell
$env:TIKTOK_UNIQUE_ID = "@your_tiktok_id"
python -m local_agent.main
```

## トラブルシュート

### Terraform が `invalid_grant` で失敗する

`gcloud auth login` と Terraform の Application Default Credentials は別です。

次のような OAuth エラーが出た場合:

```text
oauth2: "invalid_grant" "Token has been expired or revoked."
```

ADC を更新します。

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project gen-lang-client-0496284195
gcloud auth application-default print-access-token
```

その後、再実行します。

```powershell
.\.tools\terraform\terraform.exe -chdir=infra\terraform plan
.\scripts\deploy-gcp.ps1 -ProjectId "gen-lang-client-0496284195"
```

### GCP API 有効化で失敗する

デプロイスクリプトは Terraform 実行前に次の API を有効化します。

```text
artifactregistry.googleapis.com
aiplatform.googleapis.com
cloudbuild.googleapis.com
run.googleapis.com
storage.googleapis.com
```

`PERMISSION_DENIED` が出る場合、現在の GCP アカウントに Service Usage 権限が足りない可能性があります。コンソールで手動有効化するか、`Service Usage Admin` 相当の権限を付与してください。

### PowerShell と Terraform の `-chdir`

PowerShell では Terraform の `-chdir` 引数の渡し方に注意してください。

デプロイスクリプトは Terraform ディレクトリを解決してから `-chdir` に渡します。手動実行する場合は次の形が安全です。

```powershell
.\.tools\terraform\terraform.exe -chdir=infra\terraform plan
```

次のようなエラーは、パスが展開されずに文字列のまま渡された時に起きます。

```text
Error handling -chdir option: chdir $terraformDir: The system cannot find the file specified.
```
