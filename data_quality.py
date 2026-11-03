"""Data-quality checks for candle series used by KILMAS PRO."""
from __future__ import annotations

import math


def validate_candles(candles, timeframe_ms=None):
    """Return a transparent quality report; never silently repair bad OHLC rows.

    Missing intervals are reported as warnings rather than hard errors because
    market sessions, exchange outages, and provider coverage can create gaps.
    """
    errors = []
    warnings = []
    if not isinstance(candles, (list, tuple)) or not candles:
        return {"valid": False, "count": 0, "closed_count": 0,
                "errors": ["Tidak ada candle untuk diperiksa."], "warnings": []}

    timestamps = []
    closed_count = 0
    for index, candle in enumerate(candles):
        try:
            ts = int(candle["ts"])
            o, h, l, c = (float(candle[k]) for k in ("open", "high", "low", "close"))
            v = float(candle.get("volume", 0) or 0)
        except (KeyError, TypeError, ValueError, OverflowError):
            errors.append(f"Candle #{index + 1}: format atau nilai OHLC tidak lengkap.")
            continue
        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
            errors.append(f"Candle #{index + 1}: terdapat angka non-finite.")
        elif min(o, h, l, c) <= 0 or v < 0:
            errors.append(f"Candle #{index + 1}: harga harus positif dan volume tidak boleh negatif.")
        elif h < max(o, c, l) or l > min(o, c, h):
            errors.append(f"Candle #{index + 1}: relasi OHLC tidak valid.")
        timestamps.append(ts)
        if candle.get("closed", True):
            closed_count += 1

    if len(timestamps) == len(candles):
        if timestamps != sorted(timestamps):
            errors.append("Timestamp candle tidak berurutan secara kronologis.")
        if len(set(timestamps)) != len(timestamps):
            errors.append("Terdapat timestamp candle duplikat.")
        if timeframe_ms and len(timestamps) > 1 and timestamps == sorted(set(timestamps)):
            gaps = sum(1 for a, b in zip(timestamps, timestamps[1:]) if b - a > timeframe_ms * 1.5)
            if gaps:
                warnings.append(f"Terdapat {gaps} jeda interval candle; periksa cakupan provider/sesi pasar.")

    if len(candles) < 80:
        warnings.append("Kurang dari 80 candle historis; sinyal tidak akan dibuat.")
    if closed_count < 80:
        warnings.append("Kurang dari 80 candle yang sudah ditutup; analisis akan menunggu data." )

    return {"valid": not errors, "count": len(candles), "closed_count": closed_count,
            "errors": errors, "warnings": warnings}
