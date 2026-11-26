
import logging
import pandas as pd

from config import config


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    required = {"open", "high", "low", "close", "volume"}

    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise ValueError(f"Не хватает столбцов: {missing}")

    data = df.copy()

    data["ma_fast"] = data["close"].rolling(
        window=config.FAST_MA
    ).mean()

    data["ma_slow"] = data["close"].rolling(
        window=config.SLOW_MA
    ).mean()

    data["avg_volume"] = (
        data["volume"]
        .shift(1)
        .rolling(window=config.VOLUME_PERIOD)
        .mean()
    )

    return data


def generate_signal(df: pd.DataFrame) -> str:
    if len(df) < config.SLOW_MA + 1:
        logging.info("DIAGNOSTICS | Недостаточно свечей: %s", len(df))
        return "HOLD"

    data = calculate_indicators(df)

    previous = data.iloc[-2]
    current = data.iloc[-1]

    values = [
        previous["ma_fast"],
        previous["ma_slow"],
        current["ma_fast"],
        current["ma_slow"],
        current["avg_volume"],
    ]

    if any(pd.isna(value) for value in values):
        logging.info("DIAGNOSTICS | Индикаторы ещё рассчитываются")
        return "HOLD"

    crossover = (
        previous["ma_fast"] <= previous["ma_slow"]
        and current["ma_fast"] > current["ma_slow"]
    )

    volume_confirmed = (
        current["volume"]
        > current["avg_volume"] * config.VOLUME_MULTIPLIER
    )

    logging.info(
        "DIAGNOSTICS | MA20=%.2f | MA50=%.2f | "
        "Объём=%.0f | Средний=%.0f | "
        "Пересечение=%s | Объём подтверждён=%s",
        current["ma_fast"],
        current["ma_slow"],
        current["volume"],
        current["avg_volume"],
        crossover,
        volume_confirmed,
    )

    if crossover and volume_confirmed:
        logging.info("DIAGNOSTICS | СИГНАЛ BUY")
        return "BUY"

    return "HOLD"
