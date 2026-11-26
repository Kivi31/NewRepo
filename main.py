
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import CONFIG
from strategy import calculate_indicators, generate_signal
from risk import RiskManager
from broker import MockBroker, CassandraBroker, APIError
from logger import logger, log_trade


cfg = CONFIG


def is_friday(dt):
    return dt.weekday() == 4


def minutes_to_close(dt):
    close_time = datetime.strptime(
        cfg.market_close, "%H:%M"
    ).time()

    close_dt = dt.replace(
        hour=close_time.hour,
        minute=close_time.minute,
        second=0,
        microsecond=0
    )

    return (close_dt - dt).total_seconds() / 60


def trading_allowed(dt):
    """
    Не торгуем вне основной сессии
    и за 15 минут до её окончания.
    """

    current = dt.strftime("%H:%M")

    return (
        dt.weekday() < 5
        and current >= cfg.market_open
        and minutes_to_close(dt) > cfg.entry_close_buffer_min
    )


def net_pnl(entry, exit_price, shares):
    gross = (exit_price - entry) * shares

    costs = (
        (entry + exit_price)
        * shares
        * cfg.commission_pct
    )

    slippage_cost = (
        (entry + exit_price)
        * shares
        * cfg.slippage_pct
    )

    return gross - costs - slippage_cost


def close_trade(broker, risk, price, reason, position):
    result = broker.close_position(price, reason)

    if result is None:
        return

    shares = (
        position["lots"] * cfg.lot_size_shares
    )

    pnl = net_pnl(
        position["entry_price"],
        result["exit_price"],
        shares
    )

    risk.record_trade(pnl)

    log_trade(
        position["entry_time"],
        result["exit_time"],
        position["entry_price"],
        result["exit_price"],
        position["lots"],
        pnl,
        reason
    )


def run_bot():
    logger.info("Starting SBER bot | mode=%s", cfg.mode)

    if cfg.mode == "MOCK" or cfg.mode == "PAPER":
        broker = MockBroker(cfg)

        # В PAPER вместо MockBroker следует подключить
        # рыночный источник котировок Cassandra.
        logger.warning(
            "Используется MOCK broker. "
            "Это не реальная рыночная торговля."
        )

    elif cfg.mode == "LIVE":
        broker = CassandraBroker(cfg)
        broker.authenticate()

    else:
        raise ValueError("Неизвестный режим")

    risk = RiskManager(cfg)
    tz = ZoneInfo(cfg.timezone)

    # Локальное состояние текущей позиции.
    position = broker.get_position()

    while True:
        try:
            now = datetime.now(tz)

            # Получаем свечи.
            df = broker.get_candles(
                limit=cfg.history_bars
            )

            if df is None or df.empty:
                logger.warning("Нет рыночных данных")
                time.sleep(cfg.polling_seconds)
                continue

            df = calculate_indicators(df, cfg)

            candle = df.iloc[-1]
            price = float(candle["close"])

            # Проверяем открытие и закрытие сессии.
            is_closing_time = (
                now.weekday() >= 5
                or minutes_to_close(now)
                <= cfg.exit_close_buffer_min
            )

            # 1. Управление открытой позицией.
            if position is not None:

                stop_price = (
                    position["entry_price"]
                    * (1 - cfg.stop_loss_pct)
                )

                take_price = (
                    position["entry_price"]
                    * (1 + cfg.take_profit_pct)
                )

                # Если свеча коснулась обоих уровней,
                # приоритет у SL.
                if float(candle["low"]) <= stop_price:
                    close_trade(
                        broker, risk, stop_price,
                        "STOP_LOSS", position
                    )
                    position = None

                elif float(candle["high"]) >= take_price:
                    close_trade(
                        broker, risk, take_price,
                        "TAKE_PROFIT", position
                    )
                    position = None

                elif is_closing_time:
                    close_trade(
                        broker, risk, price,
                        "END_OF_SESSION", position
                    )
                    position = None

                elif risk.is_stopped():
                    close_trade(
                        broker, risk, price,
                        "DAILY_LIMIT", position
                    )
                    position = None

            # 2. Если дневной лимит достигнут —
            # никаких новых сделок.
            if risk.is_stopped():
                logger.warning(
                    "Trading stopped until next trading day"
                )

                time.sleep(cfg.polling_seconds)
                continue

            # 3. Проверяем возможность входа.
            if position is None and trading_allowed(now):

                signal = generate_signal(df, cfg)

                if signal == "BUY":

                    balance = broker.get_balance()

                    lots = risk.calculate_position(
                        balance, price
                    )

                    if lots > 0 and risk.check_entry(
                        price, lots
                    ):

                        position = broker.buy(
                            lots=lots,
                            price=price
                        )

                        logger.info(
                            "BUY SIGNAL | price=%.2f lots=%d",
                            price, lots
                        )

            logger.info(
                "PRICE=%.2f | BALANCE=%.2f | "
                "DAILY_LOSS=%.2f",
                price,
                broker.get_balance(),
                risk.daily_loss
            )

        except APIError:
            logger.exception("Broker API error")

            # После ошибки API не отправляем новые заявки.
            # При потере связи с LIVE-брокером нужна сверка
            # фактической позиции после восстановления связи.

        except Exception:
            logger.exception("Unexpected trading error")

        time.sleep(cfg.polling_seconds)


if __name__ == "__main__":
    run_bot()
