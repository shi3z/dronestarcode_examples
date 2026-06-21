#!/usr/bin/env python3
"""
VISONSDK ドローン顔追跡サンプル (dlib + OpenCV)

映像中の顔を検出して、ドローンが自動で追従するように
yaw / throttle / pitch のスティック指令を生成する。

事前:
    brew install libimobiledevice
    pip install opencv-python dlib
    # dlibのコンパイルに失敗する場合: brew install cmake && pip install dlib
    iproxy 8080 8080
    iproxy 8081 8081

使い方:
    python3 drone_follow.py
    キー:
        space : 追跡 ON/OFF
        t     : 離陸
        l     : 着陸
        x     : 緊急停止 (墜落します。注意)
        ESC   : 終了
"""
import argparse
import json
import socket
import threading
import time

import cv2
import dlib


# ====== 制御クライアント ===================================================

class DroneControl:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(None)
        threading.Thread(target=self._recv_loop, daemon=True).start()

    def _recv_loop(self):
        buf = b""
        while True:
            try:
                data = self.sock.recv(4096)
            except OSError:
                return
            if not data:
                return
            buf += data
            while b"\n" in buf:
                _, buf = buf.split(b"\n", 1)

    def send(self, cmd):
        try:
            self.sock.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
        except OSError:
            pass


# ====== 追跡ロジック =======================================================

def clip(v, lo, hi):
    return max(lo, min(hi, v))


class FaceFollower:
    """
    顔の位置からスティック指令を作る簡易Pコントローラ
      dx (顔X - 画面中央X) → yaw      (左右に旋回)
      dy (顔Y - 画面中央Y) → throttle (上下に高度)
      face_size vs target  → pitch    (前後に移動)
    """
    # ゲイン (環境に合わせて調整)
    GAIN_YAW      = 60     # 横ずれ→旋回
    GAIN_THROTTLE = 50     # 縦ずれ→上下
    GAIN_PITCH    = 40     # サイズ差→前後

    # 不感帯 (この範囲内では動かない)
    DEAD_X    = 0.10
    DEAD_Y    = 0.10
    DEAD_SIZE = 0.15

    # 出力リミット (安全のため小さめ)
    LIMIT = 30

    # 顔の目標サイズ (画面幅に対する比率)
    TARGET_SIZE_RATIO = 0.22

    # 平滑化係数 (0=直接 / 1=変えない)
    SMOOTH = 0.6

    def __init__(self):
        self._prev = {"yaw": 0, "throttle": 0, "pitch": 0}

    def compute(self, face, frame_w, frame_h):
        cx = (face.left() + face.right()) / 2.0
        cy = (face.top()  + face.bottom()) / 2.0
        face_w = face.right() - face.left()

        # -1..+1 に正規化
        dx = (cx - frame_w / 2.0) / (frame_w / 2.0)
        dy = (cy - frame_h / 2.0) / (frame_h / 2.0)

        target = frame_w * self.TARGET_SIZE_RATIO
        ds = (target - face_w) / target   # +: 顔が遠い→前進

        # 不感帯
        if abs(dx) < self.DEAD_X: dx = 0
        if abs(dy) < self.DEAD_Y: dy = 0
        if abs(ds) < self.DEAD_SIZE: ds = 0

        yaw      = clip(int(self.GAIN_YAW      * dx), -self.LIMIT, self.LIMIT)
        # 画像Y軸は下向きが正、ドローンは上に行きたい時thr正なので反転
        throttle = clip(int(self.GAIN_THROTTLE * -dy), -self.LIMIT, self.LIMIT)
        pitch    = clip(int(self.GAIN_PITCH    * ds), -self.LIMIT, self.LIMIT)

        # ローパス平滑化
        a = self.SMOOTH
        yaw      = int(a * self._prev["yaw"]      + (1 - a) * yaw)
        throttle = int(a * self._prev["throttle"] + (1 - a) * throttle)
        pitch    = int(a * self._prev["pitch"]    + (1 - a) * pitch)
        self._prev = {"yaw": yaw, "throttle": throttle, "pitch": pitch}

        return {"roll": 0, "pitch": pitch, "throttle": throttle, "yaw": yaw}

    def reset(self):
        self._prev = {"yaw": 0, "throttle": 0, "pitch": 0}


# ====== メインループ =======================================================

def run(host, ctrl_port, video_port, detect_scale):
    # 制御
    try:
        ctl = DroneControl(host, ctrl_port)
        print(f"✅ 制御接続: {host}:{ctrl_port}")
    except OSError as e:
        print(f"❌ 制御接続失敗: {e} (iproxy 8080 8080 を確認)")
        return

    # 映像
    url = f"http://{host}:{video_port}/stream"
    print(f"映像受信: {url}")
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print(f"❌ 映像接続失敗 (iproxy {video_port} {video_port} を確認)")
        return

    # 顔検出
    print("dlib HOG顔検出器を初期化...")
    detector = dlib.get_frontal_face_detector()

    follower = FaceFollower()
    tracking = False
    last_face_t = 0
    last_send_t = 0
    SEND_INTERVAL = 0.1   # 10Hz でスティックを送る

    print("""
==== 顔追跡モード ====
  space : 追跡 ON/OFF
  t     : 🛫 離陸
  l     : 🛬 着陸
  x     : ⏹  緊急停止 (墜落します。地上でのみ)
  ESC   : 終了
""")

    win = "Face Follow"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    while True:
        ret, frame = cap.read()
        if not ret:
            time.sleep(0.05)
            cv2.waitKey(1)
            continue

        h, w = frame.shape[:2]

        # 検出は縮小して高速化
        small = cv2.resize(frame, (int(w * detect_scale), int(h * detect_scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        rects = detector(gray, 0)

        face = None
        if rects:
            # 一番大きい顔を選ぶ
            big = max(rects, key=lambda r: r.width() * r.height())
            # 元解像度に戻す
            face = dlib.rectangle(
                int(big.left()   / detect_scale),
                int(big.top()    / detect_scale),
                int(big.right()  / detect_scale),
                int(big.bottom() / detect_scale),
            )
            last_face_t = time.time()

        # 描画
        cv2.line(frame, (w//2, 0), (w//2, h), (80, 80, 80), 1)
        cv2.line(frame, (0, h//2), (w, h//2), (80, 80, 80), 1)
        # 目標サイズの枠
        tgt = int(w * follower.TARGET_SIZE_RATIO)
        cv2.rectangle(frame, (w//2 - tgt//2, h//2 - tgt//2),
                             (w//2 + tgt//2, h//2 + tgt//2),
                             (60, 60, 200), 1)

        if face is not None:
            cv2.rectangle(frame, (face.left(), face.top()),
                                 (face.right(), face.bottom()),
                                 (0, 255, 0), 2)
            cx = (face.left() + face.right()) // 2
            cy = (face.top()  + face.bottom()) // 2
            cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)

        # 制御コマンド送信
        now = time.time()
        if tracking and now - last_send_t >= SEND_INTERVAL:
            last_send_t = now
            if face is not None and (now - last_face_t) < 0.5:
                stick = follower.compute(face, w, h)
                ctl.send({"cmd": "stick", **stick})
                info = f"YAW:{stick['yaw']:+3d} THR:{stick['throttle']:+3d} PIT:{stick['pitch']:+3d}"
                cv2.putText(frame, info, (10, h - 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            else:
                # 顔ロスト → 中立 (ホバリング)
                ctl.send({"cmd": "neutral"})
                follower.reset()

        # ステータス表示
        status = "TRACKING" if tracking else "tracking OFF (space)"
        color = (0, 255, 0) if tracking else (0, 0, 255)
        cv2.putText(frame, status, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

        cv2.imshow(win, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:                                # ESC
            ctl.send({"cmd": "neutral"})
            break
        elif key == ord(" "):
            tracking = not tracking
            follower.reset()
            if not tracking:
                ctl.send({"cmd": "neutral"})
            print(f"追跡: {'ON' if tracking else 'OFF'}")
        elif key == ord("t"):
            ctl.send({"cmd": "takeoff"})
        elif key == ord("l"):
            tracking = False
            ctl.send({"cmd": "neutral"})
            time.sleep(0.1)
            ctl.send({"cmd": "land"})
        elif key == ord("x"):
            tracking = False
            ctl.send({"cmd": "emergency"})

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ctrl-port", type=int, default=8080)
    ap.add_argument("--video-port", type=int, default=8081)
    ap.add_argument("--detect-scale", type=float, default=0.5,
                    help="検出時の縮小率 (0.5=半分にして高速化)")
    args = ap.parse_args()
    run(args.host, args.ctrl_port, args.video_port, args.detect_scale)
