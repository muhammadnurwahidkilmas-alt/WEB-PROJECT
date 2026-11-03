import math
import numpy as np
from .indicators import ema, rsi, atr
from .data_quality import validate_candles


def structure(high, low, close, window=8):
    h, l, c = np.asarray(high, float), np.asarray(low, float), np.asarray(close, float)
    if len(c) < window * 3:
        return {"label": "UNKNOWN", "bos": "NONE", "choch": "NONE",
                "support": float(np.min(l)), "resistance": float(np.max(h))}
    recent_high, recent_low = float(max(h[-window:])), float(min(l[-window:]))
    prior_high, prior_low = float(max(h[-2*window:-window])), float(min(l[-2*window:-window]))
    if recent_high > prior_high and recent_low > prior_low:
        label = "BULLISH HH/HL"
    elif recent_high < prior_high and recent_low < prior_low:
        label = "BEARISH LH/LL"
    elif recent_high > prior_high:
        label = "BULLISH MIXED"
    elif recent_low < prior_low:
        label = "BEARISH MIXED"
    else:
        label = "RANGE"
    price = float(c[-1])
    bos = "BULLISH BOS" if price > prior_high else "BEARISH BOS" if price < prior_low else "NONE"
    choch = "BEARISH CHoCH" if label.startswith("BULLISH") and price < prior_low else "BULLISH CHoCH" if label.startswith("BEARISH") and price > prior_high else "NONE"
    return {"label": label, "bos": bos, "choch": choch, "support": recent_low, "resistance": recent_high}


def analyze(candles):
    # The analysis engine only sees fully closed candles, never the live forming bar.
    closed = [x for x in candles if x.get("closed", True)]
    base = {"state":"WAIT", "score":0, "bias":"NEUTRAL", "price":float(closed[-1]["close"]) if closed else 0.0,
            "rsi":None, "atr":None, "entry":0.0, "sl":0.0, "tp1":0.0, "tp2":0.0,
            "rr":0.0, "reasons":[], "candles_used":len(closed), "structure":{}}
    quality = validate_candles(closed)
    if not quality["valid"]:
        base["reasons"] = ["Data OHLC tidak valid: " + quality["errors"][0]]
        base["data_valid"] = False
        return base
    base["data_valid"] = True
    if len(closed) < 80:
        base["reasons"] = [f"Menunggu minimal 80 candle tertutup; tersedia {len(closed)}."]
        return base

    h = np.array([x["high"] for x in closed], float)
    l = np.array([x["low"] for x in closed], float)
    c = np.array([x["close"] for x in closed], float)
    e9, e21, e50 = ema(c, 9), ema(c, 21), ema(c, 50)
    rv, av = float(rsi(c)[-1]), float(atr(h,l,c)[-1])
    if not math.isfinite(rv) or not math.isfinite(av) or av <= 0:
        base["reasons"] = ["Indikator belum dapat dihitung dengan stabil dari data ini."]
        return base
    s = structure(h,l,c)
    bullish, bearish = e9[-1] > e21[-1] > e50[-1], e9[-1] < e21[-1] < e50[-1]
    score = 50
    if bullish: score += 15
    elif bearish: score -= 15
    if rv >= 55: score += 10
    elif rv <= 45: score -= 10
    if s["label"].startswith("BULLISH"): score += 10
    elif s["label"].startswith("BEARISH"): score -= 10
    if s["bos"].startswith("BULLISH"): score += 8
    elif s["bos"].startswith("BEARISH"): score -= 8
    score = max(0, min(100, int(score)))
    bias = "BULLISH" if score >= 55 else "BEARISH" if score <= 45 else "NEUTRAL"
    state = "LONG" if score >= 70 and bias == "BULLISH" else "SHORT" if score <= 30 and bias == "BEARISH" else "WAIT"
    price = float(c[-1])
    if bias == "BULLISH":
        entry = max(price, s["support"] + .15 * av)
        sl = min(s["support"] - .25 * av, entry - av)
        risk = max(entry - sl, .5 * av)
        tp1, tp2 = entry + risk, entry + 2 * risk
    elif bias == "BEARISH":
        entry = min(price, s["resistance"] - .15 * av)
        sl = max(s["resistance"] + .25 * av, entry + av)
        risk = max(sl - entry, .5 * av)
        tp1, tp2 = entry - risk, entry - 2 * risk
    else:
        entry = sl = tp1 = tp2 = price
        risk = 0
    reasons = ["EMA 9/21/50 alignment: " + ("bullish" if bullish else "bearish" if bearish else "mixed"),
               f"RSI(14): {rv:.1f}", "Market structure: " + s["label"],
               "Break of structure: " + s["bos"],
               f"Perhitungan memakai {len(closed)} candle tertutup; candle berjalan dikecualikan."]
    return {"state":state,"score":score,"bias":bias,"rsi":rv,"atr":av,"structure":s,
            "entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,
            "rr":abs(tp2-entry)/risk if risk else 0,"price":price,"ema9":float(e9[-1]),
            "ema21":float(e21[-1]),"ema50":float(e50[-1]),"reasons":reasons,
            "candles_used":len(closed),"data_valid":True}


def validate(primary, mtfs):
    direction = primary.get("bias", "NEUTRAL")
    usable = [x for x in mtfs if x.get("bias") in ("BULLISH", "BEARISH", "NEUTRAL") and not x.get("error")]
    alignment = sum(x.get("bias") == direction for x in usable) / max(1, len(usable))
    mtf_ok = len(usable) == len(mtfs) and len(usable) > 0 and alignment >= .8 and direction != "NEUTRAL"
    structure_ok = primary.get("structure", {}).get("bos", "NONE") != "NONE"
    momentum_ok = (primary.get("rsi", 50) >= 55 if direction == "BULLISH" else
                   primary.get("rsi", 50) <= 45 if direction == "BEARISH" else False)
    rr_ok = primary.get("rr", 0) >= 1.5
    final = ("LONG" if direction == "BULLISH" else "SHORT") if mtf_ok and structure_ok and momentum_ok and rr_ok else "WAIT"
    return {"final":final,"mtf":mtf_ok,"structure":structure_ok,"momentum":momentum_ok,
            "rr":rr_ok,"alignment":alignment}
