"""
Mock agent server。模擬外部 agent 的三種回應行為，供非同步任務測試用。

回應順序（每次收到 /dispatch 依序輪替）：
  第一次：等 5 秒後回調 success
  第二次：等 5 秒後回調 fail
  第三次：不回調（模擬 agent 掛掉）
"""

import threading
import time

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
lock = threading.Lock()
call_count = 0

BEHAVIORS = [
    {"delay": 5, "success": True,  "message": "agent completed successfully"},
    {"delay": 5, "success": False, "message": "agent encountered an error"},
    None,  # 第三次：不回調
]


@app.route("/dispatch", methods=["POST"])
def dispatch():
    global call_count

    with lock:
        idx = call_count % len(BEHAVIORS)
        call_count += 1

    data = request.get_json()
    record_id    = data["record_id"]
    callback_url = data["callback_url"]
    behavior     = BEHAVIORS[idx]

    if behavior:
        def do_callback():
            time.sleep(behavior["delay"])
            try:
                requests.post(callback_url, json={
                    "record_id": record_id,
                    "success":   behavior["success"],
                    "message":   behavior["message"],
                }, timeout=10)
            except Exception as e:
                print(f"[mock-agent] callback failed: {e}")

        threading.Thread(target=do_callback, daemon=True).start()

    print(f"[mock-agent] call #{idx + 1} — will_callback={behavior is not None}")
    return jsonify({"call_number": idx + 1, "will_callback": behavior is not None})


@app.route("/reset", methods=["POST"])
def reset():
    global call_count
    with lock:
        call_count = 0
    return jsonify({"status": "reset"})


@app.route("/status", methods=["GET"])
def status():
    return jsonify({"call_count": call_count})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
