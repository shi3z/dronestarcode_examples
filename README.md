# VISONSDK PC制御クライアント

iPhone上で動くiOSアプリ (test.app) を**制御サーバー(TCP 8080) + 映像サーバー(MJPEG 8081)** にして、PCから操縦＆映像確認するクライアント群。

## 構成

```
[PC: drone_app.py]
        ↓ TCP 8080 (制御)  ↓ HTTP 8081/stream (映像)
[iproxy 8080] [iproxy 8081]
        ↓ USB Lightning
[iPhone: test.app]
        ↓ Wi-Fi 172.16.10.1
[ドローン (54X / KF615)]
```

## クライアント一覧

| ファイル | 用途 | 依存 |
|---|---|---|
| `drone_app.py`     | **映像 + 制御 統合** (推奨) | `opencv-python` |
| `drone_follow.py`  | **顔追跡 自動追従** | `opencv-python`, `dlib` |
| `drone_control.py` | 制御のみ (キーボード対話 / デモ) | stdlib のみ |
| `drone_view.py`    | 映像のみ表示 | `opencv-python` |
| `drone-client.js`  | 制御のみ (Node.js版) | Node.js |

## セットアップ

### 1. libimobiledevice (USB↔iPhone転送)

macOS:
```bash
brew install libimobiledevice
```

Linux:
```bash
sudo apt install libimobiledevice-utils
```

### 2. Python依存 (映像を見るなら)

```bash
pip install opencv-python
```

### 3. iPhone側

- USBでPCに接続し「信頼」を許可
- ドローンSSIDのWi-Fiに接続
- Xcodeで `test` アプリをビルド → 実機起動 → フォアグラウンドのまま
- 起動ログに以下が出れば正常:
  ```
  🌐 制御サーバー起動: 0.0.0.0:8080
  📷 映像サーバー起動: 0.0.0.0:8081/stream
  ```

### 4. ポート転送 (PC側、別ターミナル2つ)

```bash
# ターミナルA
iproxy 8080 8080

# ターミナルB
iproxy 8081 8081
```

## 実行

### 統合版 (推奨)
```bash
python3 drone_app.py
```
OpenCVウィンドウに映像表示 + キー操作。ウィンドウにフォーカスを当てた状態でキー入力。

### 制御のみ
```bash
python3 drone_control.py            # 対話モード
python3 drone_control.py demo       # 自動デモ
```

### 映像のみ
```bash
python3 drone_view.py
```
※ブラウザで開くだけなら `http://localhost:8081/stream`

### 顔追跡 自動追従
```bash
pip install dlib  # 初回のみ。失敗する場合は `brew install cmake` 後に再度
python3 drone_follow.py
```
キー操作:
- `space` : 追跡 ON/OFF (デフォルトOFF)
- `t` : 離陸 / `l` : 着陸 / `x` : 緊急停止 / `ESC` : 終了

仕組み:
- dlibのHOG顔検出器で画面内の一番大きい顔を選択
- 顔の中心と目標枠（赤い四角）のずれから比例制御で stick を生成
  - 横ずれ → **yaw** (旋回)
  - 縦ずれ → **throttle** (上下)
  - 顔サイズ vs 目標サイズ → **pitch** (前後)
- 出力は±30に制限、平滑化＋不感帯あり
- 顔が0.5秒以上ロストすると自動的に中立(ホバー)

ゲイン調整は `drone_follow.py` の `FaceFollower` クラスの定数:
```python
GAIN_YAW = 60     # 横ずれの効き
GAIN_THROTTLE = 50
GAIN_PITCH = 40
LIMIT = 30        # 出力リミット
TARGET_SIZE_RATIO = 0.22  # 顔の目標サイズ (画面幅比)
```

## キー操作 (drone_app.py / drone_control.py 共通)

| キー | 動作 |
|---|---|
| `t` | 🛫 離陸 |
| `l` | 🛬 着陸 |
| `x` | ⏹ 緊急停止 |
| `b` | 🤸 フリップ |
| `w/s` (↑↓) | 前進/後退 |
| `a/d` (←→) | 左/右移動 |
| `q/e` | 左/右旋回 |
| `r/f` | 上昇/下降 |
| `n` / space | スティック中立 |
| `p` | 撮影 |
| `i` | ライト |
| `g` | ジャイロ校正 |
| `v` | ステータス取得 |
| `Ctrl+C` / `ESC` | 終了 |

スティックは押下時に値±50で送信、600ms後に自動中立化（ナッジ方式）。

## JSONプロトコル仕様

改行(`\n`)区切り。

### 制御コマンド (PC → iPhone:8080)

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

スティック値は `-100..+100` (内部で uint8 28..228 にマップ、128=中立)

### レスポンス
```json
{"ok": true, "cmd": "takeoff"}
{"ok": false, "error": "unknown cmd: foo"}
```

ステータス:
```json
{
  "ok": true, "connected": true,
  "model": "54X", "version": "V3.8.4",
  "sticks": {"roll": 0, "pitch": 0, "throttle": 0, "yaw": 0},
  "ctrl6": 0
}
```

### 映像 (iPhone:8081)

`GET /stream` → `multipart/x-mixed-replace; boundary=frame`
各フレーム:
```
--frame\r\n
Content-Type: image/jpeg\r\n
Content-Length: NNN\r\n
\r\n
<JPEG bytes>\r\n
```
約10fps / JPEG品質 50%。

## 他言語例

cURL:
```bash
echo '{"cmd":"status"}' | nc localhost 8080
curl http://localhost:8081/stream --output -  # MJPEG生バイト
```

Python (最小):
```python
import socket, json
s = socket.create_connection(("127.0.0.1", 8080))
s.sendall((json.dumps({"cmd":"takeoff"}) + "\n").encode())
print(s.recv(1024))
```

OpenCV (映像):
```python
import cv2
cap = cv2.VideoCapture("http://127.0.0.1:8081/stream")
while True:
    _, frame = cap.read()
    cv2.imshow("d", frame)
    if cv2.waitKey(1) & 0xFF == 27: break
```

## トラブルシュート

| 症状 | 対処 |
|---|---|
| `ECONNREFUSED` 8080 | `iproxy 8080 8080` 起動忘れ |
| 映像が出ない | `iproxy 8081 8081` 起動忘れ / iOSアプリでストリーミング受信が動いていない (Xcodeログ "描画開始" を確認) |
| 接続できるが応答なし | アプリがフォアグラウンドか確認 |
| 離陸しない | iOSアプリのXcodeログで `BlueLight送信完了` が出ているか / ドローンWi-Fi接続 |
| OpenCV起動が遅い | MJPEGの最初のフレームを待つため数秒かかる場合あり |
| 映像カクつく | iOS側でJPEG品質0.5/10fps制限。`ViewController.m` の `maybeBroadcastFrame...` で調整可 |

## 注意

- iOSは背景でTCPサーバーを維持できないので、アプリは**フォアグラウンドのまま**
- 緊急停止 (`x`) はモーター即停止 → 空中で叩くと墜落
- 広く障害物の無い場所でテスト
