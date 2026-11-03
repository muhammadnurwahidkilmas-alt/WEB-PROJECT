"""Conservative, candle-close-only historical simulation for KILMAS PRO."""
from __future__ import annotations

import math
from .analysis import analyze
from .data_quality import validate_candles


def run_backtest(candles, fee_bps=5.0, slippage_bps=5.0, min_bars=100):
    """Test signals generated at a closed candle and entered at the next open.

    If SL and TP are both inside the same candle, the stop is assumed first.
    A single position is simulated at a time. Costs are a simple price-notional
    approximation in basis points and must be adapted to the instrument/provider.
    """
    series = [c for c in candles if c.get("closed", True)]
    if len(series) < min_bars:
        return {"ready": False, "message": f"Minimal {min_bars} candle tertutup diperlukan.", "trades": []}
    quality = validate_candles(series)
    if not quality["valid"]:
        return {"ready": False, "message": "Data tidak lolos pemeriksaan: " + quality["errors"][0], "trades": []}
    if fee_bps < 0 or slippage_bps < 0:
        return {"ready": False, "message": "Biaya tidak boleh negatif.", "trades": []}

    trades = []
    i = 79
    while i < len(series) - 1:
        signal = analyze(series[:i + 1])
        direction = signal.get("state")
        if direction not in ("LONG", "SHORT"):
            i += 1
            continue

        entry_bar_index = i + 1
        entry_bar = series[entry_bar_index]
        entry = float(entry_bar["open"])
        stop = float(signal.get("sl", 0))
        target = float(signal.get("tp2", 0))
        if direction == "LONG":
            risk = entry - stop
            target_distance = target - entry
        else:
            risk = stop - entry
            target_distance = entry - target
        if not math.isfinite(risk) or risk <= 0 or target_distance <= 0:
            i += 1
            continue

        exit_price = float(series[-1]["close"])
        exit_index = len(series) - 1
        exit_reason = "END_OF_DATA"
        gross_r = 0.0
        for j in range(entry_bar_index, len(series)):
            bar = series[j]
            bar_open = float(bar["open"])
            # Handle price gaps at the next open. A stop gap is filled at the
            # worse open price, not optimistically at the requested stop level.
            if direction == "LONG" and bar_open <= stop:
                exit_price, exit_index, exit_reason = bar_open, j, "STOP_GAP"
                gross_r = (exit_price - entry) / risk
                break
            if direction == "SHORT" and bar_open >= stop:
                exit_price, exit_index, exit_reason = bar_open, j, "STOP_GAP"
                gross_r = (entry - exit_price) / risk
                break
            if direction == "LONG" and bar_open >= target:
                exit_price, exit_index, exit_reason = target, j, "TAKE_PROFIT_GAP"
                gross_r = target_distance / risk
                break
            if direction == "SHORT" and bar_open <= target:
                exit_price, exit_index, exit_reason = target, j, "TAKE_PROFIT_GAP"
                gross_r = target_distance / risk
                break
            if direction == "LONG":
                stop_hit = float(bar["low"]) <= stop
                target_hit = float(bar["high"]) >= target
            else:
                stop_hit = float(bar["high"]) >= stop
                target_hit = float(bar["low"]) <= target

            # Conservative intrabar assumption: stop is filled first if both hit.
            if stop_hit:
                exit_price, exit_index, exit_reason = stop, j, "STOP_LOSS"
                gross_r = -1.0
                break
            if target_hit:
                exit_price, exit_index, exit_reason = target, j, "TAKE_PROFIT_2"
                gross_r = target_distance / risk
                break

        if exit_reason == "END_OF_DATA":
            gross_r = ((exit_price - entry) / risk) if direction == "LONG" else ((entry - exit_price) / risk)

        # Two-sided fee/slippage approximation; actual costs vary by provider/account.
        cost_fraction = (2.0 * (float(fee_bps) + float(slippage_bps))) / 10000.0
        cost_r = (entry * cost_fraction) / risk
        net_r = gross_r - cost_r
        trades.append({"direction": direction, "signal_time": series[i]["ts"],
                       "entry_time": entry_bar["ts"], "exit_time": series[exit_index]["ts"],
                       "entry": entry, "exit": exit_price, "stop": stop, "target": target,
                       "exit_reason": exit_reason, "gross_R": gross_r,
                       "estimated_cost_R": cost_r, "net_R": net_r})
        i = max(i + 1, exit_index + 1)

    if not trades:
        return {"ready": True, "message": "Tidak ada setup LONG/SHORT yang memenuhi aturan dalam data ini.",
                "trades": [], "trade_count": 0, "win_rate": 0.0, "avg_net_r": 0.0,
                "net_r": 0.0, "profit_factor": 0.0, "max_drawdown_r": 0.0}

    net_values = [t["net_R"] for t in trades]
    wins = [x for x in net_values if x > 0]
    losses = [x for x in net_values if x < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    equity = peak = drawdown = 0.0
    for value in net_values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)

    return {"ready": True, "message": "Simulasi selesai.", "trades": trades,
            "trade_count": len(trades), "win_rate": len(wins) / len(trades) * 100.0,
            "avg_net_r": sum(net_values) / len(net_values), "net_r": sum(net_values),
            "profit_factor": gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0),
            "max_drawdown_r": drawdown}
