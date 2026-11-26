
from cassandra_broker import CassandraBroker
import json


def show(title, data):
    print(f"\n--- {title} ---")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:5000])


def main():
    broker = CassandraBroker()

    print("Подключаемся к Cassandra...")
    broker.login()

    accounts = broker.get_trade_accounts()
    show("ТОРГОВЫЕ СЧЕТА", accounts)

    securities = broker.find_sber()
    show("ПОИСК SBER", securities)

    candles = broker.get_candles()
    show("СВЕЧИ SBER", candles)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nОШИБКА:", error)
