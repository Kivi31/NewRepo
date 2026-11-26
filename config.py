
from dataclasses import dataclass


@dataclass
class Config:
    # Режим: BACKTEST / PAPER / LIVE
    mode: str = "PAPER"

    # Инструмент
    symbol: str = "SBER"
    timeframe: str = "5m"

    # Индикаторы
    fast_ma: int = 20
    slow_ma: int = 50
    volume_period: int = 20
    volume_multiplier: float = 1.5

    # Торговые параметры
    stop_loss_pct: float = 0.015
    take_profit_pct: float = 0.03

    # Капитал и риски
    initial_capital: float = 1000.0
    daily_loss_limit: float = 100.0
    attempts_per_day: int = 5

    # Лотность. Уточнить у организаторов.
    lot_size_shares: int = 1

    # Комиссия брокера: доля от оборота.
    commission_pct: float = 0.0005

    # Проскальзывание: доля от цены.
    slippage_pct: float = 0.0005

    # Торговая сессия, московское время.
    timezone: str = "Europe/Moscow"
    market_open: str = "09:50"
    market_close: str = "18:50"

    # Не открывать сделки за N минут до закрытия.
    entry_close_buffer_min: int = 15

    # Закрыть позиции за N минут до закрытия.
    exit_close_buffer_min: int = 5

    # Данные
    polling_seconds: int = 10
    history_bars: int = 200

    # API Cassandra — заполнить после получения документации.
    api_base_url: str = "https://ai.iieasy.ru"
    api_token: str = ""
    api_username: str = ""
    api_password: str = ""
    api_timeout: int = 10

    # Локальные файлы
    log_file: str = "logs/bot.log"
    trades_file: str = "logs/trades.csv"
    risk_state_file: str = "data/risk_state.json"


CONFIG = Config()
