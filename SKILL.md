---
name: drone-control
description: >-
  VISONSDK ドローン (54X / KF615 系) を PC から操縦・映像確認・顔追従するクライアント群。
  iPhone 上の iOS アプリ (test.app) が制御サーバー (TCP 8080) と MJPEG 映像サーバー (HTTP 8081/stream)
  を提供し、USB 越しに iproxy で PC に転送する。「ドローンを飛ばす」「ドローン映像を見る」
  「ドローンに顔を追わせる」「離陸/着陸/スティック操作」などで使う。
---

# drone-control スキル

VISONSDK ドローンを PC から制御するためのスキル。iPhone 上の iOS アプリ (`test.app`) を
**制御サーバー (TCP 8080)** + **映像サーバー (MJPEG 8081)** として使い、PC のクライアントから
JSON コマンドで操縦し、MJPEG で映像を受け取る。

このリポジトリの実体は <https://github.com/shi3z/dronestarcode_examples> にある。
クライアント本体 (`drone_app.py` ほか) を同じディレクトリに置いて使うこと。

## アーキテクチャ

```
[PC: クライアント (このスキル)]
        ↓ TCP 8080 (制御)   ↓ HTTP 8081/stream (映像)
[iproxy 8080]  [iproxy 8081]      ← libimobiledevice で USB 転送
        ↓ USB Lightning
[iPhone: test.app]
        ↓ Wi-Fi 172.16.10.1
[ドローン (54X / KF615)]
```

ポイント:
- iOS は背景で TCP サーバーを維持できない → アプリは **フォアグラウンドのまま**にする。
- 制御と映像は独立した 2 本のチャネル。映像が無くても制御だけは動く。

## 前提セットアップ (これが無いと動かない)

1. **libimobiledevice** (USB ↔ iPhone 転送):
   - macOS: `brew install libimobiledevice`
   - Linux: `sudo apt install libimobiledevice-utils`
2. **Python 依存** (映像を見るなら): `pip install opencv-python`、顔追従なら追加で `pip install dlib`
   (dlib のビルドに失敗したら `brew install cmake` 後に再試行)
3. **iPhone 側**: USB 接続して「信頼」を許可 → ドローン SSID の Wi-Fi に接続 →
   Xcode で `test` アプリを実機ビルド・起動 → フォアグラウンド維持。
   起動ログに `🌐 制御サーバー起動: 0.0.0.0:8080` と `📷 映像サーバー起動: 0.0.0.0:8081/stream` が出れば正常。
4. **ポート転送** (PC 側、別ターミナル 2 つ):
   ```bash
   iproxy 8080 8080   # ターミナル A: 制御
   iproxy 8081 8081   # ターミナル B: 映像
   ```

## クライアント一覧

| ファイル | 用途 | 依存 | 起動 |
|---|---|---|---|
| `drone_app.py`     | 映像 + 制御 統合 (**推奨**) | `opencv-python` | `python3 drone_app.py` |
| `drone_follow.py`  | 顔追跡 自動追従 | `opencv-python`, `dlib` | `python3 drone_follow.py` |
| `drone_control.py` | 制御のみ (キーボード / デモ) | stdlib のみ | `python3 drone_control.py [demo]` |
| `drone_view.py`    | 映像のみ表示 | `opencv-python` | `python3 drone_view.py` |
| `drone-client.js`  | 制御のみ (Node.js 版) | Node.js | `node drone-client.js [demo]` |

全クライアント共通の引数: `--host` (既定 `127.0.0.1`)、`--ctrl-port` (8080)、`--video-port` (8081)。

## キー操作 (drone_app.py / drone_control.py / drone-client.js 共通)

| キー | 動作 | キー | 動作 |
|---|---|---|---|
| `t` | 🛫 離陸 | `w/s` (↑↓) | 前進/後退 |
| `l` | 🛬 着陸 | `a/d` (←→) | 左/右移動 |
| `x` | ⏹ 緊急停止 (空中で押すと墜落) | `q/e` | 左/右旋回 |
| `b` | 🤸 フリップ | `r/f` | 上昇/下降 |
| `p` | 撮影 | `n` / space | スティック中立 |
| `i` | ライト | `v` | ステータス取得 |
| `g` | ジャイロ校正 | `ESC` / `Ctrl+C` | 終了 |

スティックは押下時に値 ±50 で送信し、約 600ms 後に自動で中立化する（ナッジ方式）。
`drone_app.py` は OpenCV ウィンドウにフォーカスを当てた状態でキー入力する。

## JSON プロトコル (これさえ分かれば任意言語で実装できる)

改行 (`\n`) 区切りの JSON。**制御コマンド (PC → iPhone:8080)**:

```json
{"cmd": "takeoff"}
{"cmd": "land"}
{"cmd": "emergency"}
{"cmd": "neutral"}
{"cmd": "stick", "roll": 0, "pitch": 50, "throttle": 0, "yaw": 0}
{"cmd": "flip"}
{"cmd": "photo"}
{"cmd": "light"}
{"cmd": "gyro_cal"}
{"cmd": "status"}
```

- スティック値は `-100..+100`（内部で uint8 28..228 にマップ、128=中立）。
- `roll`=左右移動, `pitch`=前後, `throttle`=上下, `yaw`=旋回。

**レスポンス**: `{"ok": true, "cmd": "takeoff"}` / `{"ok": false, "error": "..."}`
**ステータス**: `{"ok": true, "connected": true, "model": "54X", "version": "V3.8.4", "sticks": {...}, "ctrl6": 0}`

**映像 (iPhone:8081)**: `GET /stream` → `multipart/x-mixed-replace; boundary=frame`、約 10fps / JPEG 品質 50%。

最小実装例 (Python):
```python
import socket, json
s = socket.create_connection(("127.0.0.1", 8080))
s.sendall((json.dumps({"cmd": "takeoff"}) + "\n").encode())
print(s.recv(1024))
```
```bash
echo '{"cmd":"status"}' | nc localhost 8080   # cURL/nc でも叩ける
```

## 顔追従 (drone_follow.py) の仕組み

dlib の HOG 顔検出器で画面内の最大の顔を選び、目標枠とのずれから P 制御で stick を生成する:
- 横ずれ → **yaw**、縦ずれ → **throttle**、顔サイズ vs 目標サイズ → **pitch**
- 出力は ±30 に制限、平滑化＋不感帯あり。顔を 0.5 秒以上ロストすると自動中立 (ホバー)。
- ゲインは `FaceFollower` クラスの `GAIN_YAW` / `GAIN_THROTTLE` / `GAIN_PITCH` / `LIMIT` / `TARGET_SIZE_RATIO` で調整。
- キー: `space` 追跡 ON/OFF、`t` 離陸、`l` 着陸、`x` 緊急停止、`ESC` 終了。

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `ECONNREFUSED` 8080 | `iproxy 8080 8080` 起動忘れ |
| 映像が出ない | `iproxy 8081 8081` 起動忘れ / iOS 側でストリーミングが動いていない |
| 接続できるが無応答 | アプリがフォアグラウンドか確認 |
| 離陸しない | iOS の Xcode ログで `BlueLight送信完了` が出ているか / ドローン Wi-Fi 接続を確認 |
| OpenCV 起動が遅い | MJPEG の最初のフレーム待ちで数秒かかる場合あり |

## 安全上の注意 (必ず守る)

- 緊急停止 (`x`) はモーター即停止 → **空中で押すと墜落する**。地上でのみ使う。
- 広く障害物の無い場所でテストする。
- 操縦中は常にスティックの自動中立を信頼しきらず、`n` / space で明示的に止められるようにしておく。

## このドキュメントをスキル化する手順 (他の Claude Code 向け)

1. リポジトリを clone: `git clone https://github.com/shi3z/dronestarcode_examples`
2. clone したディレクトリをそのまま `~/.claude/skills/drone-control/` に置く
   (この `SKILL.md` がスキル定義になる。クライアント `.py` / `.js` も同梱されている)。
3. 上記「前提セットアップ」を実施してから、`drone_app.py` などを起動する。
