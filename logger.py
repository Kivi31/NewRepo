
import logging
import csv
import os
from datetime import datetime


os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("SBER_BOT")


def log_trade(entry_time, exit_time, entry_price,
              exit_price, lots, pnl, reason):

    file_exists = os.path.exists("logs/trades.csv")

    with open(
        "logs/trades.csv",
        "a",
        newline="",
        encoding="utf-8"
    ) as f:

        writer = csv.writer(f)

        if not file_exists:
            writer.writerow([
                "entry_time",
                "exit_time",
                "entry_price",
                "exit_price",
                "lots",
                "pnl",
                "reason"
            ])

        writer.writerow([
            entry_time,
            exit_time,
            entry_price,
            exit_price,
            lots,
            round(pnl, 2),
            reason
        ])

    logger.info(
        "TRADE CLOSED | entry=%s exit=%s "
        "lots=%s pnl=%.2f reason=%s",
        entry_price, exit_price, lots, pnl, reason
    )
