
import pandas as pd
import logging

logger = logging.getLogger(__name__)


# Параметры стратегии №5
ORB_START = "10:00"
ORB_END = "10:30"
ORB_BUFFER = 0.001       # 0.1%
MA_PERIOD = 200
RSI_PERIOD = 14
RSI_MIN = 50
RSI_MAX = 70
TIMEZONE = "Europe/Moscow"


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    ORB + MA200 + RSI(14).

    Ожидаемые столбцы:
    open, high, low, close, volume

    Время свечи должно находиться в DatetimeIndex
    или в одном из столбцов:
    datetime, timestamp, time, date.
    """

    required = {"open", "high", "low", "close", "volume"}

    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise ValueError(f"Не хватает столбцов: {missing}")

    data = df.copy()

    # MA200 — направление глобального тренда
    data["ma200"] = data["close"].rolling(
        window=MA_PERIOD
    ).mean()

    # RSI(14)
    delta = data["close"].diff()

    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(
        alpha=1 / RSI_PERIOD,
        min_periods=RSI_PERIOD,
        adjust=False
    ).mean()

    avg_loss = loss.ewm(
        alpha=1 / RSI_PERIOD,
        min_periods=RSI_PERIOD,
        adjust=False
    ).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    data["rsi"] = 100 - (100 / (1 + rs))

    # Если цена росла без снижения — RSI = 100
    data.loc[
        (avg_loss == 0) & (avg_gain > 0), "rsi"
    ] = 100

    # Если цена не менялась — RSI = 50
    data.loc[
        (avg_loss == 0) & (avg_gain == 0), "rsi"
    ] = 50

    return data


def _get_moscow_times(df: pd.DataFrame):
    """Получает время свечей и приводит его к московскому часовому поясу."""

    time_column = None

    for column in ("datetime", "timestamp", "time", "date"):
        if column in df.columns:
            time_column = column
            break

    if time_column is not None:
        raw = df[time_column]

        if pd.api.types.is_numeric_dtype(raw):
            median = raw.dropna().abs().median()

            if median > 1e14:
                times = pd.to_datetime(raw, unit="ns", errors="coerce")
            elif median > 1e11:
                times = pd.to_datetime(raw, unit="ms", errors="coerce")
            else:
                times = pd.to_datetime(raw, unit="s", errors="coerce")
        else:
            times = pd.to_datetime(raw, errors="coerce")

    elif isinstance(df.index, pd.DatetimeIndex):
        times = pd.Series(df.index, index=df.index)

    else:
        return None

    times = pd.DatetimeIndex(times)

    if times.tz is None:
        times = times.tz_localize(TIMEZONE)
    else:
        times = times.tz_convert(TIMEZONE)

    return times


def generate_signal(df: pd.DataFrame) -> str:
    """ORB + MA200 + RSI с диагностикой."""

    if len(df) < MA_PERIOD:
        logger.info(
            "HOLD | Недостаточно свечей: %s из %s",
            len(df), MA_PERIOD
        )
        return "HOLD"

    data = calculate_indicators(df)
    times = _get_moscow_times(data)

    if times is None:
        logger.warning("HOLD | Не удалось определить время свечей")
        return "HOLD"

    data = data.copy()
    data["_time"] = times

    current = data.iloc[-1]
    previous = data.iloc[-2]

    if pd.isna(current["ma200"]) or pd.isna(current["rsi"]):
        logger.info("HOLD | MA200 или RSI ещё не рассчитаны")
        return "HOLD"

    current_time = current["_time"]

    if current_time.strftime("%H:%M") < ORB_END:
        logger.info("HOLD | ORB ещё формируется")
        return "HOLD"

    today = current_time.date()

    day_mask = data["_time"].apply(
        lambda t: t.date() == today
    )

    day_data = data.loc[day_mask]

    orb_data = day_data[
        (day_data["_time"].dt.strftime("%H:%M") >= ORB_START)
        & (day_data["_time"].dt.strftime("%H:%M") < ORB_END)
    ]

    if len(orb_data) < 6:
        logger.info(
            "HOLD | Недостаточно свечей ORB: %s из 6",
            len(orb_data)
        )
        return "HOLD"

    orb_high = orb_data["high"].max()
    breakout_level = orb_high * (1 + ORB_BUFFER)

    breakout = (
        previous["close"] <= breakout_level
        and current["close"] > breakout_level
    )

    trend_confirmed = current["close"] > current["ma200"]

    rsi_confirmed = (
        RSI_MIN <= current["rsi"] <= RSI_MAX
    )

    logger.info(
        "Проверка стратегии | "
        "Цена: %.2f | ORB High: %.2f | Уровень пробоя: %.2f | "
        "MA200: %.2f | RSI: %.2f | "
        "Пробой: %s | Тренд: %s | RSI-фильтр: %s",
        current["close"],
        orb_high,
        breakout_level,
        current["ma200"],
        current["rsi"],
        breakout,
        trend_confirmed,
        rsi_confirmed
    )

    if breakout and trend_confirmed and rsi_confirmed:
        logger.info("BUY | Все условия стратегии выполнены")
        return "BUY"

    return "HOLD"
