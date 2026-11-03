import json
import threading
import time
import requests
import websocket

REST = "https://data-api.binance.vision/api/v3/klines"
WS = "wss://data-stream.binance.vision/ws"
SUPPORTED = {"1m","3m","5m","15m","30m","1h","2h","4h","6h","8h","12h","1d"}

def fetch_klines(symbol, interval, limit=500):
    symbol = symbol.upper().strip()
    if not symbol or not symbol.isalnum():
        raise ValueError("Symbol tidak valid. Contoh: BTCUSDT.")
    if interval not in SUPPORTED:
        raise ValueError(f"Timeframe {interval} tidak didukung provider ini.")
    response = requests.get(REST, params={"symbol":symbol,"interval":interval,"limit":limit},
                            timeout=15, headers={"User-Agent":"KILMAS-PRO/2.8"})
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list) or not rows:
        raise ValueError("Provider tidak mengembalikan candle. Periksa simbol.")
    now_ms = int(time.time() * 1000)
    return [{"ts":int(x[0]),"open":float(x[1]),"high":float(x[2]),"low":float(x[3]),
             "close":float(x[4]),"volume":float(x[5]),"closed":bool(int(x[6]) < now_ms)}
            for x in rows]

class BinanceLive:
    def __init__(self, symbol, interval):
        if interval not in SUPPORTED:
            raise ValueError(f"Timeframe {interval} tidak didukung.")
        self.url = f"{WS}/{symbol.lower()}@kline_{interval}"
        self.latest = None
        self.last_message = 0.0
        self.reconnects = 0
        self.attempts = 0
        self.error = ""
        self.stop_flag = False
        self.thread = None
        self.ws = None
        self.lock = threading.Lock()

    def on_message(self, ws, message):
        try:
            k = json.loads(message)["k"]
            candle = {"ts":int(k["t"]),"open":float(k["o"]),"high":float(k["h"]),
                      "low":float(k["l"]),"close":float(k["c"]),"volume":float(k["v"]),
                      "closed":bool(k["x"])}
            with self.lock:
                self.latest = candle
                self.last_message = time.time()
                self.error = ""
        except Exception as exc:
            self.error = str(exc)

    def run(self):
        while not self.stop_flag:
            self.attempts += 1
            try:
                self.ws = websocket.WebSocketApp(
                    self.url, on_message=self.on_message,
                    on_error=lambda ws, err: setattr(self, "error", str(err)))
                self.ws.run_forever(ping_interval=15, ping_timeout=10)
            except Exception as exc:
                self.error = str(exc)
            if not self.stop_flag:
                self.reconnects += 1
                time.sleep(2)

    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.stop_flag = False
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_flag = True
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass

    def health(self):
        with self.lock:
            age = time.time() - self.last_message if self.last_message else None
            latest = self.latest
        state = "CONNECTING" if age is None else "LIVE" if age <= 8 else "DELAYED" if age <= 25 else "STALE"
        return {"state":state,"age":age,"reconnects":self.reconnects,
                "attempts":self.attempts,"error":self.error,"latest":latest}
