"""Run the JPX400 EMA9/21 rank-1 BUY screener and build static data files."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf


JST = ZoneInfo("Asia/Tokyo")
REQUIRED_OHLC = ("Open", "High", "Low", "Close")
RULE_NAME = "1位戦略：週足買いフィルターなし / 日足C / 週足EMA9・21デッドクロス出口"
PRICE_SOURCE = "Yahoo Finance（株式分割・配当調整済み）"


def clean_code(value: Any) -> str:
    token = str(value or "").strip()
    return token[:-2] if token.endswith(".0") else token


def prepare_ohlc(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=REQUIRED_OHLC, dtype=float)
    data = frame.copy()
    data.columns = [str(column) for column in data.columns]
    if set(REQUIRED_OHLC).difference(data.columns):
        return pd.DataFrame(columns=REQUIRED_OHLC, dtype=float)
    data = data.loc[:, list(REQUIRED_OHLC)].apply(pd.to_numeric, errors="coerce")
    data.index = pd.to_datetime(data.index, errors="coerce")
    data = data.loc[~data.index.isna()]
    if isinstance(data.index, pd.DatetimeIndex) and data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    return (
        data.dropna(subset=list(REQUIRED_OHLC))
        .sort_index()
        .loc[lambda value: ~value.index.duplicated(keep="last")]
    )


def add_rank1_signals(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the same objective Entry C and confirmed-week rules as the backtest."""
    data = prepare_ohlc(frame)
    if data.empty:
        return data

    data["ema9"] = data["Close"].ewm(span=9, adjust=False, min_periods=9).mean()
    data["ema21"] = data["Close"].ewm(span=21, adjust=False, min_periods=21).mean()
    data["momentum63"] = data["Close"].pct_change(63)

    weekly = data.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    ).dropna()
    weekly["weekly_ema9"] = weekly["Close"].ewm(span=9, adjust=False, min_periods=9).mean()
    weekly["weekly_ema21"] = weekly["Close"].ewm(span=21, adjust=False, min_periods=21).mean()
    weekly["weekly_filter_ok"] = (
        (weekly["weekly_ema9"] > weekly["weekly_ema21"])
        & (weekly["weekly_ema21"] > weekly["weekly_ema21"].shift(1))
    )
    weekly["weekly_dead_cross"] = weekly["weekly_ema9"] < weekly["weekly_ema21"]
    for column in ("weekly_ema9", "weekly_ema21", "weekly_filter_ok", "weekly_dead_cross"):
        data[column] = weekly[column].reindex(data.index, method="ffill")
    data["weekly_filter_ok"] = data["weekly_filter_ok"].eq(True)
    data["weekly_dead_cross"] = data["weekly_dead_cross"].eq(True)

    bounce = (data["Close"] > data["Open"]) & (data["Close"] > data["High"].shift(1))
    data["buy_signal"] = (
        (data["Close"].shift(1) > data["ema9"].shift(1))
        & (data["Low"] <= data["ema9"])
        & (data["High"] >= data["ema21"])
        & (data["Close"] > data["ema21"])
        & bounce
    ).fillna(False)
    return data


def extract_frames(raw: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    if raw is None or raw.empty:
        return {}
    if not isinstance(raw.columns, pd.MultiIndex):
        return {tickers[0]: prepare_ohlc(raw)} if len(tickers) == 1 else {}

    level0 = {str(value) for value in raw.columns.get_level_values(0)}
    level1 = {str(value) for value in raw.columns.get_level_values(1)}
    fields = set(REQUIRED_OHLC)
    ticker_level = 1 if fields.intersection(level0) else 0 if fields.intersection(level1) else -1
    if ticker_level < 0:
        return {}

    frames: dict[str, pd.DataFrame] = {}
    for ticker in tickers:
        try:
            prepared = prepare_ohlc(raw.xs(ticker, axis=1, level=ticker_level))
        except KeyError:
            continue
        if not prepared.empty:
            frames[ticker] = prepared
    return frames


def _download_once(tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    raw = yf.download(
        tickers,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=True,
        group_by="column",
        progress=False,
        threads=True,
        timeout=30,
    )
    return extract_frames(raw, tickers)


def download_histories(tickers: list[str], start: date, end: date) -> dict[str, pd.DataFrame]:
    cache = Path(".cache/yfinance")
    cache.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache))

    histories: dict[str, pd.DataFrame] = {}
    for offset in range(0, len(tickers), 40):
        batch = tickers[offset : offset + 40]
        batch_result: dict[str, pd.DataFrame] = {}
        for attempt in range(3):
            try:
                batch_result = _download_once(batch, start, end)
                if batch_result:
                    break
            except Exception as exc:  # network errors are retried and logged
                print(f"batch {offset // 40 + 1}, attempt {attempt + 1}: {exc}")
            time.sleep(3 * (attempt + 1))
        histories.update(batch_result)

    missing = [ticker for ticker in tickers if ticker not in histories]
    for ticker in missing:
        try:
            histories.update(_download_once([ticker], start, end))
        except Exception as exc:
            print(f"individual retry failed: {ticker}: {exc}")
    return histories


def rank_latest_candidates(
    components: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    enriched_by_ticker: dict[str, pd.DataFrame] = {}
    latest_dates: list[pd.Timestamp] = []
    for ticker, history in histories.items():
        enriched = add_rank1_signals(history)
        if enriched.empty:
            continue
        enriched_by_ticker[ticker] = enriched
        latest_dates.append(pd.Timestamp(enriched.index[-1]).normalize())
    if not latest_dates:
        raise RuntimeError("株価データを取得できませんでした。時間を置いて再実行してください。")

    as_of = max(latest_dates)
    company_by_code = {
        clean_code(row.code): str(row.company_name)
        for row in components[["code", "company_name"]].itertuples(index=False)
    }
    rows: list[dict[str, Any]] = []
    fresh_count = 0
    for ticker, enriched in enriched_by_ticker.items():
        if pd.Timestamp(enriched.index[-1]).normalize() != as_of:
            continue
        fresh_count += 1
        latest = enriched.iloc[-1]
        if not bool(latest.get("buy_signal", False)) or pd.isna(latest.get("momentum63")):
            continue
        code = ticker.removesuffix(".T")
        weekly_ok = bool(latest["weekly_filter_ok"])
        weekly_dc = bool(latest["weekly_dead_cross"])
        rows.append(
            {
                "code": code,
                "company_name": company_by_code.get(code, code),
                "signal_date": as_of.date().isoformat(),
                "close": round(float(latest["Close"]), 2),
                "momentum63_pct": round(float(latest["momentum63"]) * 100, 2),
                "weekly_filter_ok": weekly_ok,
                "weekly_status": "OK" if weekly_ok else "NG",
                "weekly_dead_cross": weekly_dc,
                "exit_status": "WEEKLY DC" if weekly_dc else "HOLD",
                "daily_ema9": round(float(latest["ema9"]), 2),
                "daily_ema21": round(float(latest["ema21"]), 2),
                "weekly_ema9": round(float(latest["weekly_ema9"]), 2) if pd.notna(latest["weekly_ema9"]) else None,
                "weekly_ema21": round(float(latest["weekly_ema21"]), 2) if pd.notna(latest["weekly_ema21"]) else None,
                "action": "翌営業日始値で買い候補",
                "chart_url": f"https://www.tradingview.com/chart/?symbol=TSE%3A{code}",
            }
        )

    ranked = pd.DataFrame(rows)
    columns = [
        "rank", "code", "company_name", "signal_date", "close", "momentum63_pct",
        "weekly_filter_ok", "weekly_status", "weekly_dead_cross", "exit_status",
        "daily_ema9", "daily_ema21", "weekly_ema9", "weekly_ema21", "action", "chart_url",
    ]
    if ranked.empty:
        ranked = pd.DataFrame(columns=columns)
    else:
        ranked = ranked.sort_values(["momentum63_pct", "code"], ascending=[False, True], kind="stable")
        ranked = ranked.reset_index(drop=True)
        ranked.insert(0, "rank", range(1, len(ranked) + 1))

    status = {
        "as_of_date": as_of.date().isoformat(),
        "downloaded_count": len(enriched_by_ticker),
        "fresh_count": fresh_count,
        "stale_count": len(enriched_by_ticker) - fresh_count,
        "candidate_count": len(ranked),
        "weekly_ok_count": int(ranked["weekly_filter_ok"].sum()) if not ranked.empty else 0,
    }
    return ranked, status


def load_components(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"code": "string"})
    if not {"code", "company_name"}.issubset(frame.columns):
        raise ValueError("components.csvにはcodeとcompany_nameが必要です。")
    result = frame[["code", "company_name"]].copy()
    result["code"] = result["code"].map(clean_code)
    return result.loc[result["code"] != ""].drop_duplicates("code").reset_index(drop=True)


def save_results(output: Path, metadata: dict[str, Any], candidates: pd.DataFrame) -> None:
    output.mkdir(parents=True, exist_ok=True)
    candidates.to_csv(output / "latest.csv", index=False, encoding="utf-8-sig")
    (output / "latest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    records = json.loads(candidates.to_json(orient="records", force_ascii=False))
    (output / "data.json").write_text(
        json.dumps({"metadata": metadata, "candidates": records}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(components_path: Path, output: Path, as_of: date | None = None) -> tuple[dict[str, Any], pd.DataFrame]:
    current_date = as_of or datetime.now(JST).date()
    components = load_components(components_path)
    tickers = [f"{code}.T" for code in components["code"]]
    print(f"scan started: {len(tickers)} components")
    histories = download_histories(tickers, current_date - timedelta(days=1_100), current_date)
    candidates, status = rank_latest_candidates(components, histories)
    metadata = {
        **status,
        "fetched_at": datetime.now(JST).replace(microsecond=0).isoformat(),
        "component_count": len(components),
        "price_source": PRICE_SOURCE,
        "rule": RULE_NAME,
    }
    save_results(output, metadata, candidates)
    print(
        f"scan completed: as_of={metadata['as_of_date']} fresh={metadata['fresh_count']} "
        f"candidates={metadata['candidate_count']}"
    )
    return metadata, candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JPX400 EMA9/21 BUY screener")
    parser.add_argument("--components", type=Path, default=Path("data/components.csv"))
    parser.add_argument("--output", type=Path, default=Path("_site"))
    parser.add_argument("--as-of", type=date.fromisoformat)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.components, args.output, args.as_of)

