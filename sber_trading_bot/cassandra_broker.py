
import os
import requests
import time
from dotenv import load_dotenv
from pathlib import Path

env_path = Path(__file__).with_name(".env")
load_dotenv(dotenv_path=env_path, override=True)


class CassandraBroker:
    def __init__(self):
        self.base_url = os.getenv(
            "CASSANDRA_BASE_URL",
            "https://api-cassandra.lite-invest.com"
        ).rstrip("/")

        self.email = os.getenv("CASSANDRA_EMAIL")
        self.password = os.getenv("CASSANDRA_PASSWORD")

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Content-Type": "application/json",
        })

        self.access_token = None
        self.refresh_token = None

    def _request(self, method, path, **kwargs):
        url = self.base_url + path

        response = self.session.request(
            method,
            url,
            timeout=20,
            **kwargs
        )

        if response.status_code == 429:
            raise RuntimeError(
                f"Лимит запросов Cassandra: {response.text}"
            )

        response.raise_for_status()

        if not response.text.strip():
            return None

        return response.json()

    def login(self):
        if not self.email or not self.password:
            raise RuntimeError(
                "Заполни CASSANDRA_EMAIL и CASSANDRA_PASSWORD в .env"
            )

        response = self.session.post(
            "https://cassandra.lite-invest.com/api/Authentication/Login",
            json={
                "email": self.email,
                "password": self.password
            },
            timeout=20
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Ошибка входа {response.status_code}: {response.text}"
            )

        data = response.json()

        self.access_token = data.get("accessToken")
        self.refresh_token = data.get("refreshToken")

        if not self.access_token:
            raise RuntimeError(f"Токен не получен: {data}")

        self.session.headers["Authorization"] = (
            f"Bearer {self.access_token}"
        )

        print("Авторизация Cassandra: OK")
        return True

    def get_trade_accounts(self):
        return self._request(
            "GET",
            "/api/Account/TradeAccountNumbers"
        )

    def find_sber(self):
        return self._request(
            "GET",
            "/Security/find/0/SBER"
        )

    def get_candles(
        self,
        security_id="SBER@TQBR",
        timeframe=300,
        count=200
    ):
        end_time = int(time.time())
        start_time = end_time - timeframe * count

        return self._request(
            "GET",
            "/Clusters/Candles/periodUnix",
            params={
                "securityId": security_id,
                "timeFrame": str(timeframe),
                "from": start_time,
                "to": end_time,
            }
        )
