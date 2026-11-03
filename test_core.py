import math
import unittest

from core.analysis import analyze
from core.backtest import run_backtest
from core.data_quality import validate_candles
from core.indicators import rsi


def make_candles(count=180):
    rows = []
    price = 100.0
    for i in range(count):
        # Gentle directional sequence with small pullbacks to make a plausible series.
        price += 0.45 if i % 7 not in (0, 1) else -0.08
        rows.append({"ts": 1_700_000_000_000 + i * 60_000,
                     "open": price - 0.1, "high": price + 0.25,
                     "low": price - 0.3, "close": price,
                     "volume": 10.0, "closed": True})
    return rows


class CoreTests(unittest.TestCase):
    def test_flat_market_rsi_is_neutral(self):
        value = rsi([100.0] * 40)[-1]
        self.assertAlmostEqual(float(value), 50.0, places=6)

    def test_quality_flags_duplicate_timestamp(self):
        rows = make_candles(3)
        rows[2]["ts"] = rows[1]["ts"]
        report = validate_candles(rows)
        self.assertFalse(report["valid"])
        self.assertTrue(any("duplikat" in e.lower() for e in report["errors"]))

    def test_quality_flags_bad_ohlc(self):
        rows = make_candles(3)
        rows[1]["high"] = rows[1]["low"] - 1
        report = validate_candles(rows)
        self.assertFalse(report["valid"])

    def test_analysis_excludes_forming_candle(self):
        rows = make_candles(120)
        base = analyze(rows)
        forming = dict(rows[-1])
        forming.update({"ts": forming["ts"] + 60_000, "open": 300, "high": 301,
                        "low": 299, "close": 300, "closed": False})
        with_forming = analyze(rows + [forming])
        self.assertEqual(base["price"], with_forming["price"])
        self.assertEqual(base["candles_used"], with_forming["candles_used"])

    def test_analysis_waits_below_minimum(self):
        result = analyze(make_candles(50))
        self.assertEqual(result["state"], "WAIT")
        self.assertEqual(result["candles_used"], 50)

    def test_backtest_uses_next_open_and_returns_metrics(self):
        rows = make_candles(220)
        result = run_backtest(rows, fee_bps=0, slippage_bps=0)
        self.assertTrue(result["ready"])
        self.assertGreaterEqual(result["trade_count"], 0)
        self.assertTrue(math.isfinite(result["net_r"]))

    def test_backtest_does_not_accept_forming_candle_as_history(self):
        rows = make_candles(120)
        rows[-1]["closed"] = False
        result = run_backtest(rows, min_bars=120)
        self.assertFalse(result["ready"])


if __name__ == "__main__":
    unittest.main()
