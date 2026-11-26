from dataclasses import dataclass


@dataclass
class Config:
    # Режим работы
    MODE: str = "MOCK"

    # Инструмент
    SYMBOL: str = "SBER"
    TIMEFRAME: str = "5m"
    LOT_SIZE: int = 1

    # Стратегия
    FAST_MA: int = 20
    SLOW_MA: int = 50
    VOLUME_PERIOD: int = 20
    VOLUME_MULTIPLIER: float = 1.5

    # Риск-менеджмент
    INITIAL_CAPITAL: float = 1000.0
    DAILY_LOSS_LIMIT: float = 100.0
    STOP_LOSS_PCT: float = 0.015
    TAKE_PROFIT_PCT: float = 0.03
    MAX_TRADES_PER_DAY: int = 5

    # Издержки
    COMMISSION_PCT: float = 0.0005
    SLIPPAGE_PCT: float = 0.0005

    # Торговое время (Москва)
    TIMEZONE: str = "Europe/Moscow"
    MARKET_OPEN: str = "09:50"
    MARKET_CLOSE: str = "18:50"

    # Интервал проверки
    POLL_INTERVAL: int = 10
    HISTORY_BARS: int = 250


config = Config()
