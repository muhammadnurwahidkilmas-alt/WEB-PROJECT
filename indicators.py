import numpy as np

def ema(values, period):
    x = np.asarray(values, dtype=float)
    if len(x) == 0:
        return x
    out = np.empty_like(x)
    out[0] = x[0]
    alpha = 2.0 / (period + 1)
    for i in range(1, len(x)):
        out[i] = alpha * x[i] + (1 - alpha) * out[i - 1]
    return out

def rsi(close, period=14):
    c = np.asarray(close, dtype=float)
    out = np.full(len(c), np.nan)
    if len(c) <= period:
        return out
    delta = np.diff(c)
    gains, losses = np.maximum(delta, 0), np.maximum(-delta, 0)
    avg_gain, avg_loss = gains[:period].mean(), losses[:period].mean()
    out[period] = 50.0 if avg_loss == 0 and avg_gain == 0 else 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    for i in range(period + 1, len(c)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        out[i] = 50.0 if avg_loss == 0 and avg_gain == 0 else 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out

def atr(high, low, close, period=14):
    h, l, c = map(lambda x: np.asarray(x, dtype=float), (high, low, close))
    if not len(c):
        return np.array([], dtype=float)
    tr = np.empty(len(c))
    tr[0] = h[0] - l[0]
    if len(c) > 1:
        tr[1:] = np.maximum.reduce([h[1:] - l[1:], np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])])
    out = np.full(len(c), np.nan)
    if len(c) >= period:
        out[period - 1] = tr[:period].mean()
        for i in range(period, len(c)):
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out
