
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
from config import config

from strategy import generate_signal


# ---------- НАСТРОЙКИ ----------
load_dotenv(Path(__file__).with_name(".env"))

EMAIL = os.getenv("CASSANDRA_EMAIL")
PASSWORD = os.getenv("CASSANDRA_PASSWORD")

LOGIN_URL = "https://cassandra.lite-invest.com"
API_URL = "https://api-cassandra.lite-invest.com"

ACCOUNT = "00445"
SECURITY = "SBER@TQBR"
LOT_SIZE = 1

TIMEFRAME = 300
POLL_SECONDS = 10

STOP_LOSS = 0.015
TAKE_PROFIT = 0.03
DAILY_LOSS_LIMIT = 100
MAX_TRADES_PER_DAY = 5

TZ = ZoneInfo("Europe/Moscow")
STATE_FILE = Path(__file__).with_name("bot_state.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger("SBER-BOT")


# ---------- CASSANDRA API ----------
class Cassandra:

    def __init__(self):
        self.session = requests.Session()
        self.access_token = None
        self.refresh_token = None

        # Кэш исторических свечей
        self._candles_cache = {}
        self._candles_loaded = False
        self._last_candles_refresh = 0

    def login(self):
        if not EMAIL or not PASSWORD:
            raise RuntimeError(
                "В .env не заполнены CASSANDRA_EMAIL и CASSANDRA_PASSWORD"
            )

        r = self.session.post(
            LOGIN_URL + "/api/Authentication/Login",
            json={
                "email": EMAIL,
                "password": PASSWORD
            },
            timeout=60
        )

        if not r.ok:
            log.error(
                "Cassandra HTTP %s: %s",
                r.status_code,
                r.text[:1500]
            )

        r.raise_for_status()

        data = r.json()

        self.access_token = data["accessToken"]
        self.refresh_token = data.get("refreshToken")

        self.session.headers.update({
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json"
        })

        log.info("Авторизация Cassandra успешна")

    def refresh(self):
        if not self.refresh_token:
            self.login()
            return

        r = self.session.post(
            LOGIN_URL + "/api/Authentication/Refresh",
            json={
                "refreshToken": self.refresh_token,
                "accessToken": self.access_token
            },
            timeout=60
        )

        if r.status_code != 200:
            self.login()
            return

        data = r.json()

        self.access_token = data["accessToken"]
        self.refresh_token = data.get(
            "refreshToken",
            self.refresh_token
        )

        self.session.headers["Authorization"] = (
            f"Bearer {self.access_token}"
        )

        log.info("Токен обновлён")

    def request(self, method, path, **kwargs):
        url = API_URL + path

        for attempt in range(2):
            r = self.session.request(
                method,
                url,
                timeout=60,
                **kwargs
            )

            if r.status_code == 401 and attempt == 0:
                self.refresh()
                continue

            if not r.ok:
                log.error(
                    "Cassandra HTTP %s: %s",
                    r.status_code,
                    r.text[:1500]
                )

            r.raise_for_status()

            return r.json() if r.text.strip() else None

        raise RuntimeError(
            "Не удалось выполнить запрос Cassandra"
        )

    def candles(self):
        now = int(time.time())
        day = 86400

        # При первом запуске загружаем историю за 5 дней.
        if not self._candles_loaded:

            log.info("Первичная загрузка истории за 5 дней")

            for i in range(5):
                end_time = now - i * day
                start_time = end_time - day

                result = self.request(
                    "GET",
                    "/Clusters/Candles/periodUnix",
                    params={
                        "securityId": SECURITY,
                        "timeFrame": str(TIMEFRAME),
                        "from": start_time,
                        "to": end_time
                    }
                )

                history = result.get("history", [])

                for candle in history:
                    candle_time = int(candle["time"])
                    self._candles_cache[candle_time] = candle

            self._candles_loaded = True
            self._last_candles_refresh = now

        # Обновляем историю раз в 30 секунд.
        elif now - self._last_candles_refresh >= 30:

            result = self.request(
                "GET",
                "/Clusters/Candles/periodUnix",
                params={
                    "securityId": SECURITY,
                    "timeFrame": str(TIMEFRAME),
                    "from": now - day,
                    "to": now
                }
            )

            history = result.get("history", [])

            for candle in history:
                candle_time = int(candle["time"])
                self._candles_cache[candle_time] = candle

            self._last_candles_refresh = now

        # Удаляем слишком старые свечи.
        cutoff = now - 7 * day

        self._candles_cache = {
            timestamp: candle
            for timestamp, candle in self._candles_cache.items()
            if timestamp >= cutoff
        }

        history = sorted(
            self._candles_cache.values(),
            key=lambda candle: int(candle["time"])
        )

        log.info(
            "Загружено исторических свечей: %s",
            len(history)
        )

        return {"history": history}

    def market_order(self, side, volume):
        # side 0 = BUY, side 1 = SELL
        side_code = 0 if side == "BUY" else 1

        result = self.request(
            "POST",
            "/Order/market",
            json={
                "tradeAccount": ACCOUNT,
                "securityId": SECURITY,
                "side": side_code,
                "volume": volume
            }
        )

        if isinstance(result, dict) and result.get("data") is False:
            raise RuntimeError(
                f"Заявка отклонена Cassandra: {result.get('message')}"
            )

        log.info(
            "Заявка %s отправлена: %s лот(ов). Ответ: %s",
            side,
            volume,
            result
        )

        return result

    def open_positions(self):
        return self.request(
            "GET",
            f"/api/Positions/open/{EMAIL}"
        )


# ---------- СОСТОЯНИЕ БОТА ----------
def load_state():
    if STATE_FILE.exists():
        with STATE_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)

    return {
        "date": str(datetime.now(TZ).date()),
        "position": None,
        "last_candle": None,
        "daily_loss": 0.0,
        "trades": 0
    }


def save_state(state):
    temp = STATE_FILE.with_suffix(".tmp")

    with temp.open("w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
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

        log.info("Дневные счётчики сброшены")


# ---------- РЫНОЧНОЕ ВРЕМЯ ----------
def market_is_open():
    now = datetime.now(TZ)

    if now.weekday() >= 5:
        return False

    current = now.time()

    return (
        clock_time(9, 50)
        <= current
        < clock_time(18, 45)
    )


# ---------- ТОРГОВЫЙ ЦИКЛ ----------
def run_bot():
    api = Cassandra()
    api.login()

    state = load_state()
    reset_daily_limits(state)

    # Проверяем, нет ли уже открытой позиции.
    if state["position"] is None:
        positions = api.open_positions()

        if positions:
            raise RuntimeError(
                "Cassandra сообщает об открытых позициях. "
                "Проверь их перед первым запуском; "
                "бот остановлен ради защиты от повторной покупки."
            )

    # Не используем старый сигнал из истории при старте.
    if state["last_candle"] is None:
        data = api.candles()
        history = data.get("history", [])

        if history:
            state["last_candle"] = int(history[-1]["time"])
            save_state(state)

    log.info(
        "Бот запущен. Инструмент: %s. Счёт: %s",
        SECURITY,
        ACCOUNT
    )

    while True:
        try:
            reset_daily_limits(state)

            data = api.candles()
            history = data.get("history", [])

            if len(history) < 55:
                log.warning(
                    "Недостаточно свечей: %s",
                    len(history)
                )
                time.sleep(POLL_SECONDS)
                continue

            df = (
                pd.DataFrame(history)
                .sort_values("time")
                .reset_index(drop=True)
            )

            df["time"] = pd.to_numeric(df["time"])

            now_ts = int(time.time())

            # Последняя полностью закрытая 5-минутная свеча.
            closed = df[
                df["time"] + TIMEFRAME <= now_ts
            ]

            if closed.empty:
                time.sleep(POLL_SECONDS)
                continue

            last = closed.iloc[-1]

            price = float(last["close"])
            candle_time = int(last["time"])

            # ---------- КОНТРОЛЬ ПОЗИЦИИ ----------
            position = state["position"]

            if position:
                entry = float(position["entry"])

                stop_price = entry * (1 - STOP_LOSS)
                target_price = entry * (1 + TAKE_PROFIT)

                current_candle = df.iloc[-1]

                low = float(current_candle["low"])
                high = float(current_candle["high"])

                exit_reason = None

                if low <= stop_price:
                    exit_reason = "STOP LOSS"

                elif high >= target_price:
                    exit_reason = "TAKE PROFIT"

                # Не переносим позицию на ночь и выходные.
                now = datetime.now(TZ)

                if (
                    now.weekday() < 5
                    and now.time() >= clock_time(18, 40)
                ):
                    exit_reason = "END OF SESSION"

                if exit_reason:
                    log.info(
                        "%s: цена %.2f, вход %.2f. Отправляю SELL",
                        exit_reason,
                        price,
                        entry
                    )

                    api.market_order(
                        "SELL",
                        int(position["volume"])
                    )

                    pnl = (
                        price - entry
                    ) * int(position["volume"])

                    if pnl < 0:
                        state["daily_loss"] += abs(pnl)

                    state["position"] = None
                    save_state(state)

                    log.info(
                        "Позиция закрыта. Расчётный результат: %.2f ₽",
                        pnl
                    )

            # ---------- ПОКУПКА ----------
            if (
                state["position"] is None
                and candle_time != state["last_candle"]
                and market_is_open()
                and state["daily_loss"] < DAILY_LOSS_LIMIT
                and state["trades"] < MAX_TRADES_PER_DAY
            ):
                signal_df = df[
                    df["time"] <= candle_time
                ].copy()

                signal = generate_signal(signal_df)

                log.info(
                    "Новая свеча. Цена %.2f. Сигнал: %s",
                    price,
                    signal
                )

                if signal == "BUY":
                    api.market_order("BUY", LOT_SIZE)

                    state["position"] = {
                        "entry": price,
                        "volume": LOT_SIZE,
                        "opened_at": datetime.now(TZ).isoformat()
                    }

                    state["trades"] += 1
                    save_state(state)

                    log.info(
                        "BUY принят. Расчётная цена входа: %.2f",
                        price
                    )

                state["last_candle"] = candle_time
                save_state(state)

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:
            log.info("Остановка по команде пользователя")
            break

        except Exception:
            log.exception(
                "Ошибка цикла. Повтор подключения через 30 секунд"
            )

            time.sleep(30)

            try:
                api.login()
            except Exception:
                log.exception(
                    "Повторная авторизация не удалась"
                )


if __name__ == "__main__":
    run_bot()
