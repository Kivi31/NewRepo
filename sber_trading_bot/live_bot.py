
import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime, time as clock_time
from zoneinfo import ZoneInfo

import requests
import pandas as pd
from dotenv import load_dotenv

from strategy import generate_signal


# ============================================================
# НАСТРОЙКИ
# ============================================================

load_dotenv(Path(__file__).with_name(".env"))

EMAIL = os.getenv("CASSANDRA_EMAIL")
PASSWORD = os.getenv("CASSANDRA_PASSWORD")

LOGIN_URL = "https://cassandra.lite-invest.com"
API_URL = "https://api-cassandra.lite-invest.com"

ACCOUNT = "00445"

# Все инструменты, которые отслеживает бот
SECURITIES = [
    "SBER@TQBR",
    "GAZP@TQBR",
    "LKOH@TQBR",
    "YDEX@TQBR",
    "T@TQBR",
    "VTBR@TQBR",
    "CHMF@TQBR",
    "NVTK@TQBR",
    "GMKN@TQBR",
    "ROSN@TQBR",
]

# Количество акций в одном лоте.
# Перед реальной торговлей проверь значения в карточке
# каждого инструмента у своего брокера.
SHARES_PER_LOT = {
    "SBER@TQBR": 1,
    "GAZP@TQBR": 10,
    "LKOH@TQBR": 1,
    "YDEX@TQBR": 1,
    "T@TQBR": 1,
    "VTBR@TQBR": 1,
    "CHMF@TQBR": 1,
    "NVTK@TQBR": 1,
    "GMKN@TQBR": 10,
    "ROSN@TQBR": 1,
}

# Количество лотов на одну сделку по каждому инструменту.
# Пока установлено по 1 лоту.
LOT_SIZE = {
    security: 1
    for security in SECURITIES
}

TIMEFRAME = 300
POLL_SECONDS = 10
CANDLE_REFRESH_SECONDS = 30

STOP_LOSS = 0.015
TAKE_PROFIT = 0.03

# Общие ограничения для всего портфеля
DAILY_LOSS_LIMIT = 100
MAX_TRADES_PER_DAY = 5

# Максимум одновременно открытых инструментов
MAX_OPEN_POSITIONS = 5

MAX_CANDLE_AGE = TIMEFRAME * 2 + 120

REQUEST_TIMEOUT = (15, 45)

RECONNECT_DELAYS = [5, 10, 20, 30, 60]

TZ = ZoneInfo("Europe/Moscow")

STATE_FILE = Path(__file__).with_name("bot_state.json")
LOG_FILE = Path(__file__).with_name("bot.log")


# ============================================================
# ЛОГИРОВАНИЕ
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger("MULTI-SBER-BOT")


# ============================================================
# ИСКЛЮЧЕНИЯ
# ============================================================

class OrderOutcomeUnknown(Exception):
    pass


class PositionSyncError(Exception):
    pass


# ============================================================
# CASSANDRA API
# ============================================================

class Cassandra:

    def __init__(self):

        self.session = requests.Session()

        self.access_token = None
        self.refresh_token = None

        # Отдельный кэш для каждого инструмента
        self.candles_cache = {}

        self.candles_loaded = set()
        self.last_candles_refresh = {}

    # --------------------------------------------------------
    # Авторизация
    # --------------------------------------------------------

    def login(self):

        if not EMAIL or not PASSWORD:
            raise RuntimeError(
                "В .env не заполнены CASSANDRA_EMAIL "
                "и CASSANDRA_PASSWORD"
            )

        response = self.session.post(
            LOGIN_URL + "/api/Authentication/Login",
            json={
                "email": EMAIL,
                "password": PASSWORD
            },
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("accessToken"):
            raise RuntimeError(
                "Cassandra не вернула accessToken"
            )

        self.access_token = data["accessToken"]
        self.refresh_token = data.get("refreshToken")

        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json"
        })

        log.info("Авторизация Cassandra успешна")

    # --------------------------------------------------------
    # Обновление токена
    # --------------------------------------------------------

    def refresh(self):

        if not self.refresh_token:
            raise RuntimeError(
                "Отсутствует refreshToken"
            )

        response = self.session.post(
            LOGIN_URL + "/api/Authentication/Refresh",
            json={
                "refreshToken": self.refresh_token,
                "accessToken": self.access_token
            },
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        if not data.get("accessToken"):
            raise RuntimeError(
                "Не удалось получить новый accessToken"
            )

        self.access_token = data["accessToken"]

        self.refresh_token = data.get(
            "refreshToken",
            self.refresh_token
        )

        self.session.headers["Authorization"] = (
            f"Bearer {self.access_token}"
        )

        log.info("Токен Cassandra обновлён")

    # --------------------------------------------------------
    # Универсальный запрос
    # --------------------------------------------------------

    def request(self, method, path, **kwargs):

        url = API_URL + path

        response = self.session.request(
            method,
            url,
            timeout=REQUEST_TIMEOUT,
            **kwargs
        )

        if response.status_code == 401:

            log.warning(
                "Токен истёк. Обновляю авторизацию."
            )

            self.refresh()

            response = self.session.request(
                method,
                url,
                timeout=REQUEST_TIMEOUT,
                **kwargs
            )

        if not response.ok:

            log.error(
                "Cassandra HTTP %s: %s",
                response.status_code,
                response.text[:1500]
            )

        response.raise_for_status()

        if not response.text.strip():
            return None

        return response.json()

    # --------------------------------------------------------
    # Получение свечей по инструменту
    # --------------------------------------------------------

    def candles(self, security):

        now = int(time.time())
        day = 86400

        if security not in self.candles_cache:
            self.candles_cache[security] = {}

        cache = self.candles_cache[security]

        # Первичная загрузка истории
        if security not in self.candles_loaded:

            log.info(
                "[%s] Первичная загрузка истории за 5 дней",
                security
            )

            for i in range(5):

                end_time = now - i * day
                start_time = end_time - day

                result = self.request(
                    "GET",
                    "/Clusters/Candles/periodUnix",
                    params={
                        "securityId": security,
                        "timeFrame": str(TIMEFRAME),
                        "from": start_time,
                        "to": end_time
                    }
                )

                history = result.get("history", [])

                for candle in history:

                    candle_time = int(candle["time"])
                    cache[candle_time] = candle

            self.candles_loaded.add(security)

            self.last_candles_refresh[security] = now

        # Периодическое обновление
        elif (
            now - self.last_candles_refresh.get(security, 0)
            >= CANDLE_REFRESH_SECONDS
        ):

            result = self.request(
                "GET",
                "/Clusters/Candles/periodUnix",
                params={
                    "securityId": security,
                    "timeFrame": str(TIMEFRAME),
                    "from": now - day,
                    "to": now
                }
            )

            history = result.get("history", [])

            for candle in history:

                candle_time = int(candle["time"])
                cache[candle_time] = candle

            self.last_candles_refresh[security] = now

        # Удаляем историю старше 7 дней
        cutoff = now - 7 * day

        self.candles_cache[security] = {
            timestamp: candle
            for timestamp, candle in cache.items()
            if timestamp >= cutoff
        }

        history = sorted(
            self.candles_cache[security].values(),
            key=lambda candle: int(candle["time"])
        )

        log.info(
            "[%s] Свечей загружено: %s",
            security,
            len(history)
        )

        return {"history": history}

    # --------------------------------------------------------
    # Рыночная заявка
    # --------------------------------------------------------

    def market_order(self, security, side, volume):

        side_code = 0 if side == "BUY" else 1

        result = self.request(
            "POST",
            "/Order/market",
            json={
                "tradeAccount": ACCOUNT,
                "securityId": security,
                "side": side_code,
                "volume": volume
            }
        )

        if isinstance(result, dict):

            if result.get("data") is False:

                raise RuntimeError(
                    f"Заявка отклонена: {result.get('message')}"
                )

        log.info(
            "[%s] Заявка %s отправлена: %s лот(ов). Ответ: %s",
            security,
            side,
            volume,
            result
        )

        return result

    # --------------------------------------------------------
    # Открытые позиции брокера
    # --------------------------------------------------------

    def open_positions(self):

        return self.request(
            "GET",
            f"/api/Positions/open/{EMAIL}"
        )


# ============================================================
# РАЗБОР ОТВЕТА С ПОЗИЦИЯМИ
# ============================================================

def extract_position_rows(response):

    if response is None:
        return []

    if isinstance(response, list):
        return response

    if isinstance(response, dict):

        for key in (
            "positions",
            "data",
            "result",
            "items"
        ):

            if key in response:

                value = response[key]

                if isinstance(value, list):
                    return value

                if isinstance(value, dict):

                    return extract_position_rows(value)

        # Возможно, API вернул одну позицию
        if any(
            key in response
            for key in (
                "securityId",
                "security",
                "ticker",
                "instrument"
            )
        ):
            return [response]

        if not response:
            return []

    raise PositionSyncError(
        "Неизвестный формат ответа Cassandra "
        "со списком открытых позиций. "
        "Торговля остановлена."
    )


def get_position_security(position):

    possible_keys = (
        "securityId",
        "security",
        "ticker",
        "instrument",
        "symbol",
        "securityCode"
    )

    for key in possible_keys:

        value = position.get(key)

        if isinstance(value, str) and value:

            value = value.upper()

            if "@" not in value:
                value += "@TQBR"

            return value

        if isinstance(value, dict):

            for nested_key in (
                "securityId",
                "ticker",
                "symbol",
                "code"
            ):

                nested_value = value.get(nested_key)

                if isinstance(nested_value, str):

                    nested_value = nested_value.upper()

                    if "@" not in nested_value:
                        nested_value += "@TQBR"

                    return nested_value

    return None


def get_broker_position_symbols(api):

    response = api.open_positions()

    rows = extract_position_rows(response)

    symbols = set()

    for position in rows:

        security = get_position_security(position)

        if security is None:

            raise PositionSyncError(
                "Не удалось определить инструмент "
                "в открытой позиции Cassandra. "
                "Проверь формат ответа API."
            )

        symbols.add(security)

    return symbols


# ============================================================
# СОСТОЯНИЕ БОТА
# ============================================================

def load_state():

    if STATE_FILE.exists():

        with STATE_FILE.open("r", encoding="utf-8") as file:
            state = json.load(file)

    else:

        state = {}

    today = str(datetime.now(TZ).date())

    # Поддержка старого формата bot_state.json
    old_position = state.pop("position", None)
    old_last_candle = state.pop("last_candle", None)

    positions = state.setdefault("positions", {})

    if old_position is not None:

        positions.setdefault(
            "SBER@TQBR",
            old_position
        )

    last_candles = state.setdefault("last_candles", {})

    if old_last_candle is not None:

        last_candles.setdefault(
            "SBER@TQBR",
            old_last_candle
        )

    state.setdefault("date", today)
    state.setdefault("daily_loss", 0.0)
    state.setdefault("trades", 0)
    state.setdefault("pending_orders", {})

    return state


def save_state(state):

    temp = STATE_FILE.with_suffix(".tmp")

    with temp.open("w", encoding="utf-8") as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
            indent=2
        )

    temp.replace(STATE_FILE)


def reset_daily_limits(state):

    today = str(datetime.now(TZ).date())

    if state["date"] != today:

        state["date"] = today
        state["daily_loss"] = 0.0
        state["trades"] = 0

        save_state(state)

        log.info("Дневные ограничения сброшены")


# ============================================================
# РЫНОЧНОЕ ВРЕМЯ
# ============================================================

def market_is_open():

    now = datetime.now(TZ)

    if now.weekday() >= 5:
        return False

    return (
        clock_time(9, 50)
        <= now.time()
        < clock_time(18, 45)
    )


# ============================================================
# АКТУАЛЬНОСТЬ ДАННЫХ
# ============================================================

def check_candle_freshness(history):

    if not history:
        return False

    latest = max(
        history,
        key=lambda candle: int(candle["time"])
    )

    candle_time = int(latest["time"])

    now_ts = int(time.time())

    candle_age = now_ts - (candle_time + TIMEFRAME)

    if not market_is_open():
        return True

    if candle_age > MAX_CANDLE_AGE:

        log.warning(
            "Рыночные данные устарели. "
            "Возраст последней свечи: %s секунд",
            candle_age
        )

        return False

    return True


# ============================================================
# СВЕРКА ПОЗИЦИЙ
# ============================================================

def synchronize_positions(api, state):

    if state["pending_orders"]:

        raise OrderOutcomeUnknown(
            "Есть незавершённые заявки в bot_state.json. "
            "Проверь их в Cassandra вручную."
        )

    broker_symbols = get_broker_position_symbols(api)

    local_symbols = set(state["positions"].keys())

    if broker_symbols != local_symbols:

        raise PositionSyncError(
            "Расхождение позиций!\n"
            f"В боте: {sorted(local_symbols)}\n"
            f"В Cassandra: {sorted(broker_symbols)}\n"
            "Проверь позиции вручную."
        )

    log.info(
        "Сверка завершена. Открытых инструментов: %s",
        len(broker_symbols)
    )


# ============================================================
# ОТПРАВКА ЗАЯВКИ
# ============================================================

def execute_order(api, state, security, side, volume, price):

    pending = {
        "side": side,
        "volume": volume,
        "estimated_price": price,
        "created_at": datetime.now(TZ).isoformat()
    }

    state["pending_orders"][security] = pending

    save_state(state)

    try:

        api.market_order(
            security,
            side,
            volume
        )

    except Exception as error:

        raise OrderOutcomeUnknown(
            f"[{security}] Неизвестен результат заявки {side}. "
            "Не отправляй повторную заявку до проверки в Cassandra."
        ) from error

    try:

        broker_symbols = get_broker_position_symbols(api)

    except Exception as error:

        raise OrderOutcomeUnknown(
            f"[{security}] Заявка отправлена, "
            "но не удалось проверить позиции."
        ) from error

    if side == "BUY" and security not in broker_symbols:

        raise OrderOutcomeUnknown(
            f"[{security}] BUY отправлен, "
            "но позиция не обнаружена."
        )

    if side == "SELL" and security in broker_symbols:

        raise OrderOutcomeUnknown(
            f"[{security}] SELL отправлен, "
            "но позиция всё ещё присутствует."
        )

    state["pending_orders"].pop(security, None)

    save_state(state)


# ============================================================
# КОНТРОЛЬ ОТКРЫТОЙ ПОЗИЦИИ
# ============================================================

def manage_position(api, state, security, candle, price):

    position = state["positions"].get(security)

    if not position:
        return

    entry = float(position["entry"])
    volume = int(position["volume"])

    stop_price = entry * (1 - STOP_LOSS)
    target_price = entry * (1 + TAKE_PROFIT)

    low = float(candle["low"])
    high = float(candle["high"])

    exit_reason = None
    exit_price = price

    if low <= stop_price:

        exit_reason = "STOP LOSS"
        exit_price = stop_price

    elif high >= target_price:

        exit_reason = "TAKE PROFIT"
        exit_price = target_price

    now = datetime.now(TZ)

    if (
        now.weekday() < 5
        and now.time() >= clock_time(18, 40)
    ):

        exit_reason = "END OF SESSION"
        exit_price = price

    if not exit_reason:
        return

    log.warning(
        "[%s] %s. Вход: %.2f. Расчётная цена выхода: %.2f",
        security,
        exit_reason,
        entry,
        exit_price
    )

    execute_order(
        api,
        state,
        security,
        "SELL",
        volume,
        exit_price
    )

    shares = SHARES_PER_LOT[security]

    pnl = (
        exit_price - entry
    ) * volume * shares

    if pnl < 0:

        state["daily_loss"] += abs(pnl)

    state["positions"].pop(security, None)

    save_state(state)

    log.info(
        "[%s] Позиция закрыта. "
        "Расчётный результат: %.2f ₽",
        security,
        pnl
    )


# ============================================================
# ОБРАБОТКА ОДНОГО ИНСТРУМЕНТА
# ============================================================


def process_security(api, state, security):
    try:
        data = api.candles(security)
        history = data.get("history", [])

        if not history:
            log.warning("[%s] ПРОПУСК: API вернул пустую историю", security)
            return

        df = pd.DataFrame(history)

        if "time" not in df.columns or "close" not in df.columns:
            log.error("[%s] ПРОПУСК: в свечах нет time или close. Колонки: %s",
                      security, list(df.columns))
            return

        df["time"] = pd.to_numeric(df["time"], errors="coerce")
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["time", "close"])
        df = df.sort_values("time").drop_duplicates(
            subset=["time"]
        ).reset_index(drop=True)

        if df.empty:
            log.warning("[%s] ПРОПУСК: после обработки свечей датафрейм пуст",
                        security)
            return

        now_ts = int(time.time())
        closed = df[df["time"] + TIMEFRAME <= now_ts]

        if closed.empty:
            log.warning(
                "[%s] ПРОПУСК: нет закрытых свечей. "
                "Последнее время=%s, now=%s",
                security, int(df.iloc[-1]["time"]), now_ts
            )
            return

        last = closed.iloc[-1]
        price = float(last["close"])
        candle_time = int(last["time"])

        if security in state["positions"]:
            if not check_candle_freshness(history):
                log.warning("[%s] ПРОПУСК: устаревшие данные для позиции",
                            security)
                return

            manage_position(api, state, security, last, price)
            return

        if not market_is_open():
            log.info("[%s] ПРОПУСК: сейчас вне торгового времени", security)
            return

        if candle_time == state["last_candles"].get(security):
            return

        if state["daily_loss"] >= DAILY_LOSS_LIMIT:
            log.warning("[%s] ПРОПУСК: достигнут дневной лимит убытка",
                        security)
            return

        if state["trades"] >= MAX_TRADES_PER_DAY:
            log.info("[%s] ПРОПУСК: достигнут лимит сделок", security)
            return

        if len(state["positions"]) >= MAX_OPEN_POSITIONS:
            log.info("[%s] ПРОПУСК: достигнут лимит открытых позиций",
                     security)
            return

        if not check_candle_freshness(history):
            log.warning("[%s] ПРОПУСК: последняя свеча устарела", security)
            return

        signal_df = closed[closed["time"] <= candle_time].copy()
        signal = generate_signal(signal_df)

        log.info(
            "[%s] НОВАЯ СВЕЧА: цена=%.2f, время=%s, свечей=%s, сигнал=%s",
            security, price, candle_time, len(signal_df), signal
        )

        if signal == "BUY":
            volume = int(LOT_SIZE[security])

            log.warning(
                "[%s] BUY: отправка заявки. Объём=%s",
                security, volume
            )

            execute_order(api, state, security, "BUY", volume, price)

            state["positions"][security] = {
                "entry": price,
                "volume": volume,
                "opened_at": datetime.now(TZ).isoformat()
            }
            state["trades"] += 1

            log.info(
                "[%s] Позиция зарегистрирована. Цена расчётная: %.2f",
                security, price
            )

        state["last_candles"][security] = candle_time
        save_state(state)

    except OrderOutcomeUnknown:
        raise
    except Exception:
        log.exception("[%s] ОШИБКА обработки инструмента", security)
        raise


# ============================================================
# ОСНОВНОЙ ЦИКЛ
# ============================================================

def run_bot():

    api = Cassandra()

    state = load_state()

    reset_daily_limits(state)

    # --------------------------------------------------------
    # Начальная авторизация
    # --------------------------------------------------------

    attempt = 0

    while True:

        try:

            api.login()
            break

        except requests.exceptions.RequestException:

            delay = RECONNECT_DELAYS[
                min(attempt, len(RECONNECT_DELAYS) - 1)
            ]

            log.exception(
                "Нет соединения. Повтор через %s секунд.",
                delay
            )

            time.sleep(delay)
            attempt += 1

    # --------------------------------------------------------
    # Проверка незавершённых заявок и позиций
    # --------------------------------------------------------

    synchronize_positions(api, state)

    log.info(
        "Мультиинструментальный бот запущен."
    )

    log.info(
        "Инструментов: %s",
        len(SECURITIES)
    )

    log.info(
        "Список инструментов: %s",
        ", ".join(SECURITIES)
    )

    log.info(
        "Счёт: %s",
        ACCOUNT
    )

    reconnect_attempt = 0

    # --------------------------------------------------------
    # Основной цикл
    # --------------------------------------------------------

    while True:

        try:

            reset_daily_limits(state)

            for security in SECURITIES:

                process_security(
                    api,
                    state,
                    security
                )

            reconnect_attempt = 0

            time.sleep(POLL_SECONDS)

        except OrderOutcomeUnknown:

            log.exception(
                "КРИТИЧЕСКАЯ ОШИБКА ЗАЯВКИ. "
                "Бот остановлен."
            )

            raise

        except PositionSyncError:

            log.exception(
                "ОШИБКА СИНХРОНИЗАЦИИ ПОЗИЦИЙ. "
                "Бот остановлен."
            )

            raise

        except KeyboardInterrupt:

            log.info(
                "Остановка по команде пользователя."
            )

            break

        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError
        ):

            delay = RECONNECT_DELAYS[
                min(
                    reconnect_attempt,
                    len(RECONNECT_DELAYS) - 1
                )
            ]

            log.exception(
                "Потеряно соединение. "
                "Повтор через %s секунд.",
                delay
            )

            time.sleep(delay)

            try:

                api.login()

                synchronize_positions(
                    api,
                    state
                )

                reconnect_attempt = 0

                log.info(
                    "Соединение восстановлено. "
                    "Позиции сверены."
                )

            except Exception:

                log.exception(
                    "Не удалось восстановить соединение."
                )

                reconnect_attempt += 1

        except requests.exceptions.RequestException:

            log.exception(
                "Ошибка HTTP. Повтор через 30 секунд."
            )

            time.sleep(30)

            try:

                api.login()

                synchronize_positions(
                    api,
                    state
                )

            except Exception:

                log.exception(
                    "Повторное подключение не удалось."
                )

        except Exception:

            log.exception(
                "Ошибка торгового цикла. "
                "Повтор через 30 секунд."
            )

            time.sleep(30)

            try:

                api.login()

                synchronize_positions(
                    api,
                    state
                )

            except Exception:

                log.exception(
                    "Не удалось восстановить работу бота."
                )


# ============================================================
# ЗАПУСК
# ============================================================

if __name__ == "__main__":

    run_bot()
