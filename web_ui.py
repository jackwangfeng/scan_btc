from flask import Flask, render_template, jsonify, Response
import threading
import time

app = Flask(__name__)

shared_state = {
    "prices": {},
    "indicators": {},
    "sentiment": {},
    "recent_signals": [],
    "last_update": None
}
state_lock = threading.Lock()


def update_shared_state(prices=None, indicators=None, sentiment=None, signal=None):
    with state_lock:
        if prices:
            shared_state["prices"].update(prices)
        if indicators:
            shared_state["indicators"].update(indicators)
        if sentiment:
            shared_state["sentiment"].update(sentiment)
        if signal:
            shared_state["recent_signals"].insert(0, signal)
            shared_state["recent_signals"] = shared_state["recent_signals"][:50]
        shared_state["last_update"] = time.time()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def get_status():
    with state_lock:
        return jsonify(shared_state.copy())


@app.route("/api/stream")
def stream():
    def event_stream():
        last_update = 0
        while True:
            with state_lock:
                current_update = shared_state["last_update"]
                if current_update != last_update:
                    last_update = current_update
                    data = jsonify(shared_state.copy()).get_data(as_text=True)
                    yield f"data: {data}\n\n"
            time.sleep(1)

    return Response(event_stream(), mimetype="text/event-stream")


def run_server(host="0.0.0.0", port=5000):
    app.run(host=host, port=port, debug=False, threaded=True)
