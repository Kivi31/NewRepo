import logging
import pandas as pd

logger = logging.getLogger(__name__)

# ============================================================
# СТРАТЕГИЯ №5: ORB + MA200 + RSI
# ============================================================

ORB_START = "10:00"
ORB_END = "10:30"
ORB_BUFFER = 0.001

MA_PERIOD = 200
RSI_PERIOD = 14
RSI_MIN = 50
RSI_MAX = 70

TIMEZONE = "Europe/Moscow"


# ============================================================
# ИНДИКАТОРЫ
# ============================================================

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:

    required = {"open", "high", "low", "close", "volume"}

    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise ValueError(f"Не хватает столбцов: {missing}")

    data = df.copy()

    for column in ("open", "high", "low", "close", "volume"):
        data[column] = pd.to_numeric(
            data[column],
            errors="coerce"
        )

    data["ma200"] = data["close"].rolling(
        window=MA_PERIOD,
        min_periods=MA_PERIOD
    ).mean()

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

    data.loc[
        (avg_loss == 0) & (avg_gain > 0),
        "rsi"
    ] = 100

    data.loc[
        (avg_loss == 0) & (avg_gain == 0),
        "rsi"
    ] = 50

    return data


# ============================================================
# ПРЕОБРАЗОВАНИЕ ВРЕМЕНИ В МОСКОВСКОЕ
# ============================================================

def _get_moscow_times(df: pd.DataFrame):

    time_column = None

    for column in ("datetime", "timestamp", "time", "date"):
        if column in df.columns:
            time_column = column
            break

    if time_column is not None:

        raw = df[time_column]

        if pd.api.types.is_numeric_dtype(raw):

            valid = raw.dropna()

            if valid.empty:
                return None

            median = valid.abs().median()

            # ВАЖНО:
            # Unix timestamp всегда отсчитывается от UTC.
            # Сначала определяем UTC, затем переводим в Москву.

            if median > 1e14:

                times = pd.to_datetime(
                    raw,
                    unit="ns",
                    errors="coerce",
                    utc=True
                )

            elif median > 1e11:

                times = pd.to_datetime(
                    raw,
                    unit="ms",
                    errors="coerce",
                    utc=True
                )

            else:

                times = pd.to_datetime(
                    raw,
                    unit="s",
                    errors="coerce",
                    utc=True
                )

        else:

            times = pd.to_datetime(
                raw,
                errors="coerce"
            )

    elif isinstance(df.index, pd.DatetimeIndex):

        times = pd.DatetimeIndex(df.index)

    else:

        return None

    times = pd.DatetimeIndex(times)

    if times.tz is None:

        # Для строковых дат без часового пояса
        # предполагаем, что они уже московские.

        times = times.tz_localize(
            TIMEZONE,
            ambiguous="NaT",
            nonexistent="NaT"
        )

    else:

        times = times.tz_convert(TIMEZONE)

    return times


# ============================================================
# ГЕНЕРАЦИЯ СИГНАЛА
# ============================================================

def generate_signal(df: pd.DataFrame) -> str:

    if df is None or df.empty:

        logger.warning("HOLD | Нет данных для анализа")
        return "HOLD"

    if len(df) < MA_PERIOD + 1:

        logger.info(
            "HOLD | Недостаточно свечей: %s. Требуется минимум %s",
            len(df),
            MA_PERIOD + 1
        )

        return "HOLD"

    try:

        data = calculate_indicators(df)

        times = _get_moscow_times(data)

        if times is None:

            logger.warning(
                "HOLD | Не удалось определить время свечей"
            )

            return "HOLD"

        data = data.copy()
        data["_time"] = times

        data = data.dropna(subset=["_time"])

        if len(data) < MA_PERIOD + 1:

            logger.info(
                "HOLD | Недостаточно корректных свечей"
            )

            return "HOLD"

        current = data.iloc[-1]
        previous = data.iloc[-2]

        if (
            pd.isna(current["ma200"])
            or pd.isna(current["rsi"])
        ):

            logger.info(
                "HOLD | MA200 или RSI ещё не рассчитаны"
            )

            return "HOLD"

        current_time = current["_time"]

        # ORB ещё не сформирован
        if current_time.strftime("%H:%M") < ORB_END:

            logger.info(
                "HOLD | ORB ещё формируется. Время свечи: %s",
                current_time.strftime("%H:%M")
            )

            return "HOLD"

        today = current_time.date()

        # Свечи только за текущий московский день
        day_mask = data["_time"].apply(
            lambda t: t.date() == today
        )

        day_data = data.loc[day_mask]

        # ORB: с 10:00 включительно до 10:30
        orb_data = day_data[
            (
                day_data["_time"].dt.strftime("%H:%M")
                >= ORB_START
            )
            &
            (
                day_data["_time"].dt.strftime("%H:%M")
                < ORB_END
            )
        ]

        if len(orb_data) < 6:

            logger.info(
                "HOLD | Недостаточно свечей ORB: %s из 6. "
                "Дата: %s",
                len(orb_data),
                today
            )

            return "HOLD"

        orb_high = float(orb_data["high"].max())

        breakout_level = orb_high * (1 + ORB_BUFFER)

        current_close = float(current["close"])
        previous_close = float(previous["close"])

        ma200 = float(current["ma200"])
        rsi = float(current["rsi"])

        # Условие пробоя:
        # предыдущая свеча закрылась не выше уровня,
        # текущая закрылась выше уровня.

        breakout = (
            previous_close <= breakout_level
            and current_close > breakout_level
        )

        trend_confirmed = current_close > ma200

        rsi_confirmed = RSI_MIN <= rsi <= RSI_MAX

        logger.info(
            "Проверка стратегии | "
            "Дата: %s | Время: %s | "
            "Цена: %.2f | ORB High: %.2f | "
            "Уровень пробоя: %.2f | "
            "MA200: %.2f | RSI: %.2f | "
            "Пробой: %s | Тренд: %s | RSI-фильтр: %s",
            today,
            current_time.strftime("%H:%M"),
            current_close,
            orb_high,
            breakout_level,
            ma200,
            rsi,
            breakout,
            trend_confirmed,
            rsi_confirmed
        )

        if breakout and trend_confirmed and rsi_confirmed:

            logger.info(
                "BUY | Все условия стратегии выполнены"
            )

            return "BUY"

        reasons = []

        if not breakout:
            reasons.append("нет нового пробоя ORB")

        if not trend_confirmed:
            reasons.append("цена ниже MA200")

        if not rsi_confirmed:
            reasons.append(
                f"RSI вне диапазона {RSI_MIN}-{RSI_MAX}"
            )

        logger.info(
            "HOLD | Причины: %s",
            "; ".join(reasons)
        )

        return "HOLD"

    except Exception:

        logger.exception(
            "Ошибка при расчёте торгового сигнала"
        )

        return "HOLD"