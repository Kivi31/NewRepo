
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone

from logger import logger


class APIError(Exception):
    pass


class InsufficientBalance(APIError):
    pass


class MockBroker:
    """
    Имитация брокера.
    Позволяет запускать бота без Cassandra.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.balance = cfg.initial_capital
        self.position = None

    def get_balance(self):
        return self.balance

    def get_position(self):
        return self.position

    def get_candles(self, limit=200):
        """
        Генерируем искусственные свечи.
        Это только проверка работоспособности.
        Не является рыночной историей.
        """

        import numpy as np

        np.random.seed(42)

        periods = max(limit, 100)

        dates = pd.date_range(
            end=datetime.now(timezone.utc),
            periods=periods,
            freq="5min"
        )

        price = 312 + np.cumsum(
            np.random.normal(0, 0.25, periods)
        )

        df = pd.DataFrame({
            "timestamp": dates,
            "open": price,
            "high": price + np.random.uniform(0, 0.5, periods),
            "low": price - np.random.uniform(0, 0.5, periods),
            "close": price,
            "volume": np.random.randint(
                1000, 10000, periods
            )
        })

        return df

    def buy(self, lots, price):
        if self.position is not None:
            raise APIError("Позиция уже открыта")

        shares = lots * self.cfg.lot_size_shares
        cost = price * shares

        if cost > self.balance:
            raise InsufficientBalance("Недостаточный баланс")

        self.balance -= cost

        self.position = {
            "lots": lots,
            "entry_price": price,
            "entry_time": datetime.now().isoformat()
        }

        logger.info(
            "MOCK BUY | lots=%s price=%.2f",
            lots, price
        )

        return self.position

    def sell(self, price, reason="SIGNAL"):
        if self.position is None:
            return None

        position = self.position

        shares = (
            position["lots"]
            * self.cfg.lot_size_shares
        )

        proceeds = price * shares

        self.balance += proceeds

        pnl = (
            price - position["entry_price"]
        ) * shares

        result = {
            **position,
            "exit_price": price,
            "exit_time": datetime.now().isoformat(),
            "pnl": pnl,
            "reason": reason
        }

        self.position = None

        logger.info(
            "MOCK SELL | price=%.2f pnl=%.2f reason=%s",
            price, pnl, reason
        )

        return result

    def close_position(self, price, reason="FORCED_CLOSE"):
        return self.sell(price, reason)


class CassandraBroker:
    """
    Адаптер для реального Cassandra REST API.

    Эндпоинты ниже намеренно НЕ выдуманы.
    Их необходимо заполнить после получения документации.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.session = requests.Session()

        self.base_url = cfg.api_base_url.rstrip("/")

        if cfg.api_token:
            self.session.headers.update({
                "Authorization": f"Bearer {cfg.api_token}"
            })

    def _request(self, method, endpoint, **kwargs):
        url = self.base_url + endpoint

        try:
            response = self.session.request(
                method,
                url,
                timeout=self.cfg.api_timeout,
                **kwargs
            )

            if response.status_code in (401, 403):
                raise APIError(
                    "Ошибка авторизации Cassandra: "
                    f"HTTP {response.status_code}"
                )

            if response.status_code == 400:
                raise APIError(
                    f"Некорректный запрос: {response.text}"
                )

            if response.status_code >= 400:
                raise APIError(
                    f"API error {response.status_code}: "
                    f"{response.text}"
                )

            return response.json()

        except requests.Timeout as e:
            raise APIError("Таймаут Cassandra API") from e

        except requests.ConnectionError as e:
            raise APIError("Нет соединения с Cassandra") from e

    def authenticate(self):
        """
        TODO:
        Подставить реальный endpoint авторизации.
        Уточнить, возвращает ли Cassandra Bearer token,
        cookie или другую схему авторизации.
        """

        raise NotImplementedError(
            "Уточнить endpoint и формат авторизации у организаторов"
        )

    def get_balance(self):
        # TODO: GET реального endpoint баланса
        raise NotImplementedError

    def get_position(self):
        # TODO: GET реального endpoint позиции
        raise NotImplementedError

    def get_candles(self, limit=200):
        # TODO: GET исторических свечей
        raise NotImplementedError

    def buy(self, lots, price):
        # TODO: POST заявки на покупку
        raise NotImplementedError

    def sell(self, price, reason="SIGNAL"):
        # TODO: POST заявки на продажу
        raise NotImplementedError

    def close_position(self, price, reason="FORCED_CLOSE"):
        # TODO: Получить фактическую позицию и закрыть её
        raise NotImplementedError
