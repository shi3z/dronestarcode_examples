#!/usr/bin/env python3
"""
VISONSDK ドローン制御クライアント (Python stdlib only)

事前:
    brew install libimobiledevice
    iproxy 8080 8080

使い方:
    python3 drone_control.py                # 対話モード
    python3 drone_control.py demo           # デモシーケンス
    python3 drone_control.py --host HOST --port 8080
"""
import argparse
import json
import select
import socket
import sys
import threading
import time


class DroneControl:
    def __init__(self, host="127.0.0.1", port=8080):
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(None)
        self._stop = False
        self._t = threading.Thread(target=self._recv_loop, daemon=True)
        self._t.start()

    def _recv_loop(self):
        buf = b""
        while not self._stop:
            try:
                data = self.sock.recv(4096)
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if not line:
                    continue
                try:
                    resp = json.loads(line.decode("utf-8"))
                    if resp.get("ok") is True and "cmd" in resp:
                        sys.stdout.write(f"  ✓ {resp['cmd']}\n")
                    else:
                        sys.stdout.write(f"← {resp}\n")
                    sys.stdout.flush()
                except Exception:
                    sys.stdout.write(f"← {line!r}\n")

    def send(self, cmd):
        line = (json.dumps(cmd) + "\n").encode("utf-8")
        try:
            self.sock.sendall(line)
            sys.stdout.write(f"→ {cmd}\n")
            sys.stdout.flush()
        except OSError as e:
            sys.stderr.write(f"送信失敗: {e}\n")

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass


def run_demo(c):
    print("\n=== デモシーケンス ===")
    print("3秒後に離陸します。Ctrl+Cで中断\n")
    time.sleep(3)
    c.send({"cmd": "status"});      time.sleep(0.5)
    c.send({"cmd": "gyro_cal"});    time.sleep(2)
    print("🛫 離陸");                 c.send({"cmd": "takeoff"});  time.sleep(5)
    print("⬆️  上昇 2秒");            c.send({"cmd": "stick", "roll": 0, "pitch": 0, "throttle": 40, "yaw": 0}); time.sleep(2)
    print("🔼 前進 2秒");             c.send({"cmd": "stick", "roll": 0, "pitch": 40, "throttle": 0, "yaw": 0}); time.sleep(2)
    print("↪️  右旋回 2秒");           c.send({"cmd": "stick", "roll": 0, "pitch": 0, "throttle": 0, "yaw": 50}); time.sleep(2)
    print("🟢 中立");                 c.send({"cmd": "neutral"});  time.sleep(1)
    print("🛬 着陸");                 c.send({"cmd": "land"});     time.sleep(3)
    print("=== デモ終了 ===")


def run_interactive(c):
    import termios
    import tty

    print("""
==== 対話モード ====
  t : 🛫 離陸          l : 🛬 着陸           x : ⏹  緊急停止
  w/s : 前進/後退      a/d : 左/右移動
  q/e : 左/右旋回      r/f : 上昇/下降
  n / space : 中立     b : フリップ
  p : 撮影             i : ライト           g : ジャイロ校正
  v : ステータス       Ctrl+C : 終了
""")
    NUDGE = 0.6
    STICK = 50
    pending_timer = [None]  # mutable holder for closure

    def neutral_after(delay):
        if pending_timer[0]:
            pending_timer[0].cancel()
        t = threading.Timer(delay, lambda: c.send({"cmd": "neutral"}))
        t.daemon = True
        t.start()
        pending_timer[0] = t

    def stick_hold(axis, value):
        cmd = {"cmd": "stick", "roll": 0, "pitch": 0, "throttle": 0, "yaw": 0}
        cmd[axis] = value
        c.send(cmd)
        neutral_after(NUDGE)

    mapping = {
        "t": lambda: c.send({"cmd": "takeoff"}),
        "l": lambda: c.send({"cmd": "land"}),
        "x": lambda: c.send({"cmd": "emergency"}),
        "p": lambda: c.send({"cmd": "photo"}),
        "i": lambda: c.send({"cmd": "light"}),
        "g": lambda: c.send({"cmd": "gyro_cal"}),
        "v": lambda: c.send({"cmd": "status"}),
        "b": lambda: c.send({"cmd": "flip"}),
        "n": lambda: c.send({"cmd": "neutral"}),
        " ": lambda: c.send({"cmd": "neutral"}),
        "w": lambda: stick_hold("pitch", STICK),
        "s": lambda: stick_hold("pitch", -STICK),
        "a": lambda: stick_hold("roll", -STICK),
        "d": lambda: stick_hold("roll", STICK),
        "q": lambda: stick_hold("yaw", -STICK),
        "e": lambda: stick_hold("yaw", STICK),
        "r": lambda: stick_hold("throttle", STICK),
        "f": lambda: stick_hold("throttle", -STICK),
        "UP": lambda: stick_hold("pitch", STICK),
        "DOWN": lambda: stick_hold("pitch", -STICK),
        "LEFT": lambda: stick_hold("roll", -STICK),
        "RIGHT": lambda: stick_hold("roll", STICK),
    }

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not r:
                continue
            ch = sys.stdin.read(1)
            if ch == "\x03":  # Ctrl+C
                break
            if ch == "\x1b":  # ESC sequence (矢印キー)
                seq = sys.stdin.read(2)
                ch = {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT"}.get(seq, "")
            fn = mapping.get(ch)
            if fn:
                fn()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="interactive",
                    choices=["interactive", "demo"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    try:
        c = DroneControl(args.host, args.port)
        print(f"✅ 接続: {args.host}:{args.port}")
    except OSError as e:
        print(f"❌ 接続エラー: {e}")
        print("   iproxyが起動しているか確認: iproxy 8080 8080")
        sys.exit(1)

    try:
        if args.mode == "demo":
            run_demo(c)
        else:
            run_interactive(c)
    finally:
        c.close()


if __name__ == "__main__":
    main()
