# SQL или DataFrame: выбор инструмента

> Выбирайте границу по grain, объему и сопровождению, а не по личной привычке.

**Тип:** Case
**Треки:** Core
**Пререквизиты:** 04/11
**Время:** ~90 минут
**Результат:** собирает проверенные SQL marts и обосновывает границу инструментов.

## Цели обучения

- Назначать реляционные преобразования SQL/DuckDB.
- Использовать Python для orchestration и delivery.
- Передавать в pandas только результат нужного grain.
- Поставлять несколько marts с checksums и manifest.
- Проверять grain, связи и аддитивные метрики end-to-end.

## Проблема

Один вариант загружает все CSV в pandas и выполняет JOIN в памяти. Другой прячет весь
pipeline в огромной SQL-строке внутри Python. Оба могут работать, но плохо сопровождаются:
неясны границы ответственности, сложно переиспользовать SQL и невозможно доказать, какие
файлы были поставлены.

## Концепция

В этом проекте граница такая:

| Задача | Инструмент |
|---|---|
| Cast, normalize, JOIN, GROUP BY | DuckDB SQL |
| Параметры, запуск, export, checksum | Python |
| Небольшой ad hoc анализ готовой mart | pandas, опционально |

Результаты: `order_mart` с grain `order_id` и `user_summary` с grain `user_id`.

## Соберите это

До кода зафиксируйте инварианты:

```text
order_mart rows = orders rows = 12
order_id unique
paid_revenue = 5005
amount_item_mismatches = 0
unknown_user_orders = 1
```

Затем примените SQL pipeline из предыдущих уроков.

```bash
uv run --locked python code/main.py
```

## Используйте это

`order_mart.sql` типизирует заказы, нормализует пользователей, предварительно агрегирует
позиции и сохраняет unmatched user. `user_summary.sql` агрегирует уже проверенный grain.

Python builder:

1. передает пути и timezone параметрами;
2. выполняет оба SQL assets;
3. проверяет контрольные метрики;
4. записывает CSV;
5. считает SHA-256 источников, SQL и результатов;
6. выпускает `manifest.json`.

## Сломайте это

1. Соедините items до агрегации и наблюдайте fanout.
2. Замените LEFT JOIN users на INNER JOIN.
3. Удалите timezone из business date.
4. Измените SQL после поставки и сравните checksum.
5. Передайте сырые 500 тысяч событий в pandas без необходимости.

## Проверьте это

Integration suite подтверждает:

- 12 уникальных заказов;
- две позиции и total 1200 для `O1001`;
- сохраненный `U999`;
- два заказа с непроверяемой суммой и ноль расхождений;
- 8 пользователей с заказами в summary;
- выручку U001 `2700`;
- checksum каждого delivery file.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

```bash
uv run --locked python outputs/sql_mart_builder.py \
  --users ../data/tiny/users.csv \
  --orders ../data/tiny/orders.csv \
  --items ../data/tiny/order_items.csv \
  --output-dir delivery
```

Каталог `delivery/` содержит `order_mart.csv`, `user_summary.csv` и `manifest.json`.

## Упражнения

1. Добавьте monthly revenue mart.
2. Экспортируйте marts в Parquet и сравните размер и plan.
3. Подключите sample-профиль и измерьте момент, когда pandas-transfer становится дорогим.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Tool boundary | Выбор любимой библиотеки | Явное место смены engine, format и ownership |
| Mart | Любой export | Таблица с заявленным grain и назначением |
| Orchestration | Бизнес-расчет в Python | Управление параметрами, шагами и delivery |
| Manifest | README | Машинный контракт артефактов, checks и checksums |
| Checksum | Тест логики | Доказательство идентичности байтов |

## Дополнительное чтение

- [DuckDB: Python Overview](https://duckdb.org/docs/current/clients/python/overview) — изучите connections, relations и способы получения результата.
- [DuckDB: CSV Export](https://duckdb.org/docs/current/data/csv/overview#writing-csv-files) — сравните SQL `COPY` и Python export.
- [DuckDB: SQL on Pandas](https://duckdb.org/docs/current/guides/python/sql_on_pandas) — разберите явные и replacement-scan границы.
- [DuckDB: Performance Overview](https://duckdb.org/docs/current/guides/performance/overview) — свяжите выбор engine с объемом, форматами и workload.
