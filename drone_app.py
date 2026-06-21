#!/usr/bin/env python3
"""
VISONSDK ドローン統合クライアント (映像 + 制御 / OpenCV)

事前:
    brew install libimobiledevice
    pip install opencv-python
    iproxy 8080 8080
    iproxy 8081 8081

使い方:
    python3 drone_app.py
    python3 drone_app.py --host 127.0.0.1
"""
import argparse
import json
import socket
import threading
import time

import cv2


class DroneControl:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(None)
        threading.Thread(target=self._recv_loop, daemon=True).start()
        self.last_status = {}

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
                line, buf = buf.split(b"\n", 1)
                try:
                    resp = json.loads(line.decode("utf-8"))
                    if resp.get("connected") is not None:
                        self.last_status = resp
                except Exception:
                    pass

    def send(self, cmd):
        try:
            self.sock.sendall((json.dumps(cmd) + "\n").encode("utf-8"))
        except OSError:
            pass


def run(host, ctrl_port, video_port):
    # 制御チャネル接続
    try:
        ctl = DroneControl(host, ctrl_port)
        print(f"✅ 制御接続: {host}:{ctrl_port}")
    except OSError as e:
        print(f"⚠️  制御接続失敗 ({e}) — 映像のみで継続")
        ctl = None

    # 映像チャネル接続
    url = f"http://{host}:{video_port}/stream"
    print(f"映像受信: {url}")
    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print(f"⚠️  映像接続失敗。iproxy {video_port} {video_port} を確認")

    # スティック自動中立
    NUDGE = 0.6
    STICK = 50
    pending = [None]

    def stick_hold(axis, value):
        if not ctl:
            return
        cmd = {"cmd": "stick", "roll": 0, "pitch": 0, "throttle": 0, "yaw": 0}
        cmd[axis] = value
        ctl.send(cmd)
        if pending[0]:
            pending[0].cancel()
        t = threading.Timer(NUDGE, lambda: ctl.send({"cmd": "neutral"}))
        t.daemon = True
        t.start()
        pending[0] = t

    def send(cmd):
        if ctl:
            ctl.send(cmd)

    print("""
==== キー操作 ====
  t 🛫離陸  l 🛬着陸  x ⏹緊急  b フリップ
  w/s 前/後  a/d 左/右  q/e 左/右旋回  r/f 上/下
  n / space  中立    p 撮影  i ライト  g 校正  v 状態
  ESC で終了
""")

    win = "Drone Live"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 1280, 720)

    while True:
        if cap.isOpened():
            ret, frame = cap.read()
        else:
            ret, frame = False, None

        if ret and frame is not None:
            # ステータスをオーバーレイ
            if ctl and ctl.last_status:
                st = ctl.last_status
                txt = f"model:{st.get('model','?')} ver:{st.get('version','?')} conn:{st.get('connected')}"
                cv2.putText(frame, txt, (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            cv2.imshow(win, frame)
        else:
            time.sleep(0.05)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            break
        elif key == 255:  # no key
            continue
        elif key == ord("t"):  send({"cmd": "takeoff"})
        elif key == ord("l"):  send({"cmd": "land"})
        elif key == ord("x"):  send({"cmd": "emergency"})
        elif key == ord("p"):  send({"cmd": "photo"})
        elif key == ord("i"):  send({"cmd": "light"})
        elif key == ord("g"):  send({"cmd": "gyro_cal"})
        elif key == ord("v"):  send({"cmd": "status"})
        elif key == ord("b"):  send({"cmd": "flip"})
        elif key in (ord("n"), ord(" ")): send({"cmd": "neutral"})
        elif key == ord("w"):  stick_hold("pitch",     STICK)
        elif key == ord("s"):  stick_hold("pitch",    -STICK)
        elif key == ord("a"):  stick_hold("roll",     -STICK)
        elif key == ord("d"):  stick_hold("roll",      STICK)
        elif key == ord("q"):  stick_hold("yaw",      -STICK)
        elif key == ord("e"):  stick_hold("yaw",       STICK)
        elif key == ord("r"):  stick_hold("throttle",  STICK)
        elif key == ord("f"):  stick_hold("throttle", -STICK)

    if cap.isOpened():
        cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--ctrl-port", type=int, default=8080)
    ap.add_argument("--video-port", type=int, default=8081)
    args = ap.parse_args()
    run(args.host, args.ctrl_port, args.video_port)
