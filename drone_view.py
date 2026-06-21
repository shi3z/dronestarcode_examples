#!/usr/bin/env python3
"""
ドローン映像ビューア (OpenCV / MJPEG over HTTP)

事前:
    pip install opencv-python
    iproxy 8081 8081

使い方:
    python3 drone_view.py
    python3 drone_view.py --host 127.0.0.1 --port 8081

ブラウザで見るだけなら:
    http://127.0.0.1:8081/stream
"""
import argparse
import sys

import cv2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8081)
    args = ap.parse_args()

    url = f"http://{args.host}:{args.port}/stream"
    print(f"映像受信: {url}")

    cap = cv2.VideoCapture(url)
    if not cap.isOpened():
        print(f"❌ 開けません: {url}")
        print("  iproxy 8081 8081 が起動しているか確認")
        sys.exit(1)

    while True:
        ret, frame = cap.read()
        if not ret:
            print("⚠️  フレーム取得失敗")
            break
        cv2.imshow("Drone", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q") or key == 27:
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
