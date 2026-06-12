"""
Mock agent server。模擬外部 agent 的三種回應行為，供非同步任務測試用。

行為由測試端透過 POST /set-behavior {"mode": "success" | "fail" | "none"} 顯式設定，
之後所有 /dispatch 都照該模式行為，直到下次變更：
  success：等 5 秒後回調 success
  fail   ：等 5 秒後回調 fail
  none   ：不回調（模擬 agent 掛掉）
"""

import threading
import time

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)
lock = threading.Lock()
call_count = 0
current_mode = "success"

BEHAVIORS = {
    "success": {"delay": 5, "success": True,  "message": "agent completed successfully"},
    "fail":    {"delay": 5, "success": False, "message": "agent encountered an error"},
    "none":    None,
}


@app.route("/dispatch", methods=["POST"])
def dispatch():
    global call_count

    with lock:
        call_count += 1
        call_number = call_count
        mode = current_mode

    data = request.get_json()
    record_id    = data["record_id"]
    callback_url = data["callback_url"]
    behavior     = BEHAVIORS[mode]

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

    print(f"[mock-agent] call #{call_number} — mode={mode}")
    return jsonify({"call_number": call_number, "mode": mode})


@app.route("/set-behavior", methods=["POST"])
def set_behavior():
    global current_mode

    data = request.get_json() or {}
    mode = data.get("mode")
    if mode not in BEHAVIORS:
        return jsonify({"error": f"mode must be one of {sorted(BEHAVIORS)}"}), 400

    with lock:
        current_mode = mode
    print(f"[mock-agent] behavior set to {mode}")
    return jsonify({"mode": mode})


@app.route("/reset", methods=["POST"])
def reset():
    global call_count, current_mode
    with lock:
        call_count = 0
        current_mode = "success"
    return jsonify({"status": "reset"})


@app.route("/status", methods=["GET"])
def status():
    return jsonify({"call_count": call_count, "mode": current_mode})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8001)
