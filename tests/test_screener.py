from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from src.screener import add_rank1_signals, rank_latest_candidates


def history_with_latest_signal(momentum_scale: float = 1.0) -> pd.DataFrame:
    index = pd.bdate_range("2023-01-02", periods=260)
    close = pd.Series(np.linspace(100.0, 180.0 * momentum_scale, len(index)), index=index)
    frame = pd.DataFrame({"Open": close - 0.5, "High": close + 1, "Low": close - 1, "Close": close})
    enriched = add_rank1_signals(frame)
    previous = frame.iloc[-2]
    ema9 = float(enriched["ema9"].iloc[-1])
    ema21 = float(enriched["ema21"].iloc[-1])
    frame.iloc[-1, frame.columns.get_loc("Open")] = max(ema21 + .1, float(previous["High"]) - .5)
    frame.iloc[-1, frame.columns.get_loc("Low")] = min(ema9, ema21) - .2
    frame.iloc[-1, frame.columns.get_loc("High")] = max(ema9, float(previous["High"]) + 2)
    frame.iloc[-1, frame.columns.get_loc("Close")] = float(previous["High"]) + 1
    return frame


class ScreenerTests(unittest.TestCase):
    def test_latest_bar_is_buy_signal(self):
        self.assertTrue(bool(add_rank1_signals(history_with_latest_signal())["buy_signal"].iloc[-1]))

    def test_candidates_are_ranked_by_momentum(self):
        components = pd.DataFrame({"code": ["1001", "1002"], "company_name": ["A社", "B社"]})
        candidates, metadata = rank_latest_candidates(
            components,
            {"1001.T": history_with_latest_signal(1.0), "1002.T": history_with_latest_signal(1.3)},
        )
        self.assertEqual(metadata["candidate_count"], 2)
        self.assertEqual(candidates.iloc[0]["code"], "1002")

    def test_weekly_ng_is_not_filtered_out(self):
        components = pd.DataFrame({"code": ["1001"], "company_name": ["A社"]})
        candidates, _ = rank_latest_candidates(components, {"1001.T": history_with_latest_signal()})
        self.assertEqual(len(candidates), 1)
        self.assertIn("weekly_status", candidates.columns)


if __name__ == "__main__":
    unittest.main()

