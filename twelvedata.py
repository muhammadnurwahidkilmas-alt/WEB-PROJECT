
import json
import threading
import time
from datetime import datetime, timezone
from urllib.parse import quote
import requests
import websocket

BASE = "https://api.twelvedata.com"
WS_BASE = "wss://ws.twelvedata.com/v1/quotes/price"
INTERVALS = {"1m":"1min", "5m":"5min", "15m":"15min", "30m":"30min",
             "1h":"1h", "2h":"2h", "4h":"4h", "1d":"1day"}
DURATION_MS = {"1m":60_000,"5m":300_000,"15m":900_000,"30m":1_800_000,
               "1h":3_600_000,"2h":7_200_000,"4h":14_400_000,"1d":86_400_000}

def _check_key(api_key):
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Masukkan API key Twelve Data di sidebar. API key tidak disertakan dalam ZIP.")
    return key

def _parse_time(value):
    # Twelve Data returns UTC when timezone=UTC.
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)

def fetch_candles(symbol, timeframe, api_key, outputsize=500):
    key = _check_key(api_key)
    if timeframe not in INTERVALS:
        raise ValueError(f"Timeframe {timeframe} belum didukung oleh adapter Twelve Data.")
    symbol = (symbol or "").strip().upper()
    if not symbol or len(symbol) > 24:
        raise ValueError("Simbol tidak valid. Contoh forex: EUR/USD; emas spot: XAU/USD.")
    response = requests.get(f"{BASE}/time_series", params={
        "symbol": symbol, "interval": INTERVALS[timeframe], "outputsize": min(max(int(outputsize), 80), 500),
        "timezone": "UTC", "order": "ASC", "apikey": key
    }, timeout=20, headers={"User-Agent":"KILMAS-PRO/3.0"})
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        # Never echo request URLs here: the API key is a query parameter.
        raise RuntimeError(f"Twelve Data HTTP error ({response.status_code}). Periksa jaringan dan kuota API.") from None
    data = response.json()
    if isinstance(data, dict) and data.get("status") == "error":
        raise ValueError(data.get("message", "Twelve Data menolak permintaan. Periksa simbol, API key, kuota, dan hak akses paket."))
    values = data.get("values") if isinstance(data, dict) else None
    if not values:
        raise ValueError("Twelve Data tidak mengembalikan candle. Pastikan simbol dan timeframe tersedia pada paket API key.")
    candles=[]
    for row in values:
        candle_ts = _parse_time(row["datetime"])
        duration = DURATION_MS[timeframe]
        # Twelve Data timestamps the candle at its opening time. The latest
        # interval is still forming until its scheduled close time has passed.
        is_closed = candle_ts + duration <= int(time.time() * 1000)
        candles.append({"ts":candle_ts, "open":float(row["open"]),
            "high":float(row["high"]), "low":float(row["low"]), "close":float(row["close"]),
            "volume":float(row.get("volume") or 0), "closed":is_closed})
    candles.sort(key=lambda x:x["ts"])
    return candles

class TwelveDataLive:
    """Streams quote ticks and folds them into a clearly identified synthetic current candle."""
    def __init__(self, symbol, interval, api_key):
        self.key = _check_key(api_key)
        if interval not in DURATION_MS:
            raise ValueError(f"Timeframe {interval} tidak didukung untuk streaming.")
        self.symbol = (symbol or "").strip().upper()
        self.interval = interval
        self.duration = DURATION_MS[interval]
        self.latest = None
        self.last_message = 0.0
        self.reconnects = 0
        self.attempts = 0
        self.error = ""
        self.stop_flag = False
        self.thread = None
        self.ws = None
        self.lock = threading.Lock()

    def on_open(self, ws):
        ws.send(json.dumps({"action":"subscribe", "params":{"symbols":self.symbol}}))

    def on_message(self, ws, message):
        try:
            data=json.loads(message)
            if data.get("event") == "error":
                self.error=str(data.get("message") or data)
                return
            if data.get("event") in ("subscribe-status", "heartbeat"):
                return
            price=data.get("price")
            if price is None:
                return
            price=float(price)
            stamp=int(float(data.get("timestamp") or time.time())*1000)
            bucket=(stamp//self.duration)*self.duration
            with self.lock:
                prev=self.latest
                if prev and prev["ts"] == bucket:
                    candle={**prev,"high":max(prev["high"],price),"low":min(prev["low"],price),"close":price,"closed":False,"volume":0.0}
                else:
                    candle={"ts":bucket,"open":price,"high":price,"low":price,"close":price,"volume":0.0,"closed":False}
                self.latest=candle
                self.last_message=time.time()
                self.error=""
        except Exception as exc:
            self.error=self._safe_error(exc)

    def _safe_error(self, error):
        message = str(error)
        if self.key:
            message = message.replace(self.key, "[API_KEY_REDACTED]")
        return message[:300]

    def run(self):
        while not self.stop_flag:
            self.attempts += 1
            try:
                url=f"{WS_BASE}?apikey={quote(self.key, safe='')}"
                self.ws=websocket.WebSocketApp(url, on_open=self.on_open, on_message=self.on_message,
                    on_error=lambda ws, err: setattr(self,"error",self._safe_error(err)))
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as exc:
                self.error=self._safe_error(exc)
            if not self.stop_flag:
                self.reconnects += 1
                time.sleep(3)

    def start(self):
        if not self.thread or not self.thread.is_alive():
            self.stop_flag=False
            self.thread=threading.Thread(target=self.run, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_flag=True
        try:
            if self.ws: self.ws.close()
        except Exception: pass

    def health(self):
        with self.lock:
            age=time.time()-self.last_message if self.last_message else None
            latest=self.latest
        state="CONNECTING" if age is None else "LIVE" if age <= 15 else "DELAYED" if age <= 45 else "STALE"
        return {"state":state,"age":age,"reconnects":self.reconnects,"attempts":self.attempts,
                "error":self.error,"latest":latest}
