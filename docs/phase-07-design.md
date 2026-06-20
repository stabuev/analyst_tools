# Проект фазы 07: Надежная аналитика

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единый pipeline, матрицу дефектов, роли инструментов и контракт интеграционного проекта.

## Результат фазы

Студент превращает набор разрозненных проверок в систему защиты аналитического pipeline.
Система останавливает публикацию при нарушении входного контракта, логики
преобразований, SQL-reconciliation или regression baseline и оставляет диагностируемый
машинный отчет о запуске.

Фаза состоит из четырех последовательных блоков:

1. `07/01`-`07/03`: инварианты, границы тестирования и минимальные контрпримеры.
2. `07/04`-`07/06`: property-based testing, DataFrame-контракты и конфигурация.
3. `07/07`-`07/09`: SQL-проверки, regression baselines и наблюдаемость batch-запусков.
4. `07/10`: интеграционный quality gate с атомарной публикацией результата.

Суммарная длительность - 825 минут, или 13,75 часа.

## Границы содержания

- **Не повторяем введение в pytest.** Arrange-Act-Assert, `pytest.raises`, fixtures,
  parametrization и базовый CI уже пройдены в `01/08`-`01/09`. Здесь они применяются к
  многостадийным аналитическим pipeline и failure classes.
- **Контракт не заменяет бизнес-инвариант.** Pandera проверяет форму и допустимые
  значения DataFrame, но reconciliation выручки, сохранение grain и независимый
  контрольный расчет остаются отдельными правилами.
- **Property-based testing не означает случайный smoke test.** Hypothesis используется
  только после явной формулировки свойства, домена входов и oracle.
- **Golden dataset не является snapshot всего файла.** Сравниваются нормализованные
  значения и бизнес-семантика; нестабильные timestamps, порядок строк и служебные поля
  исключаются осознанно.
- **Monitoring не исправляет плохие данные.** Порог создает сигнал и блокирует
  публикацию, но политика исправления и backfill остается явным решением владельца.
- **CI не является новой темой.** Финальный урок расширяет знакомый quality workflow
  доменными gates и проверкой атомарной публикации, а не повторяет синтаксис GitHub
  Actions.
- **Оркестрация остается за границей.** Планировщики, retries на уровне workflow и
  production lineage систематизируются в фазах 11, 17 и инфраструктурных факультативах.

## Роли инструментов

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| pytest | Исполнение contract-focused, regression и integration tests | Повтор базового синтаксиса и полный обзор plugin ecosystem |
| Hypothesis | Генерация входов, edge cases и shrinking контрпримеров | Stateful testing и custom fuzzing infrastructure |
| Pandera | Runtime-контракты pandas DataFrame и lazy error reports | Контракты всех поддерживаемых DataFrame engines |
| Pydantic | Строгая конфигурация запуска и сериализация validation errors | Web/API models и settings management для production-сервисов |
| DuckDB | Независимые SQL-проверки grain, связей и reconciliation | dbt graph, warehouse-specific tests и production scheduling |
| logging + JSON reports | Диагностируемость запуска и разделение классов ошибок | Полноценный observability backend, tracing и alert routing |

На 13 июня 2026 года официальные stable-релизы: Hypothesis 6.155.2, Pandera 0.31.1 и
Pydantic 2.13.4. Зависимость добавляется в корневой locked environment только вместе с
первым уроком, который реально использует библиотеку. Для Pandera применяется
рекомендованный импорт `pandera.pandas`.

Проверенные официальные контракты:

- [Hypothesis documentation](https://hypothesis.readthedocs.io/en/latest/) - свойства
  проверяются на автоматически выбранных входах, включая неочевидные edge cases;
- [Pandera documentation](https://pandera.readthedocs.io/en/stable/) - DataFrame schema
  проверяет типы и свойства, а `lazy=True` агрегирует нарушения в error report;
- [Pydantic documentation](https://docs.pydantic.dev/latest/) - модели поддерживают
  strict и coercing validation и структурированные validation errors;
- [Python logging](https://docs.python.org/3/library/logging.html) - библиотечный код
  выпускает records через logger, а конфигурация handlers принадлежит приложению.

## Единый pipeline и данные

Фаза использует ежедневную поставку заказов подписочного сервиса:

```text
users.csv
orders.csv
order_items.csv
        |
        v
validated order mart
        |
        +--> daily metrics
        +--> quality report
        +--> run telemetry
        +--> checksum manifest
```

Таблицы:

| Таблица | Grain | Ключ |
|---|---|---|
| `users` | один пользователь | `user_id` |
| `orders` | один заказ | `order_id` |
| `order_items` | одна строка заказа | `order_id, line_number` |

Профили:

- `tiny`: небольшой валидный baseline в Git для ручной сверки, fixtures и golden tests;
- `sample`: детерминированная локальная генерация для volume checks и monitoring;
- дефекты создаются как минимальные мутации валидного baseline, а не как независимые
  несогласованные копии полного набора.

Контракт pipeline:

- `orders.order_id` уникален и не содержит пропусков;
- каждый `orders.user_id` существует в `users`;
- каждая строка `order_items` ссылается на существующий заказ;
- сумма `quantity * unit_price_rub` совпадает с `orders.amount_rub`;
- денежные значения конечны, неотрицательны и имеют не более двух десятичных знаков;
- timestamps содержат timezone offset и попадают в объявленное batch-window;
- paid revenue считается только по `status=paid`;
- публикация меняет указатель `current` только после прохождения всех gates.

## Матрица дефектов

| Класс | Минимальная мутация | Gate |
|---|---|---|
| Grain | повторить один `order_id` | invariant, Pandera, SQL |
| Null key | очистить `user_id` | invariant, Pandera |
| Orphan | заменить `user_id` на неизвестный | SQL relationship check |
| Schema drift | удалить или добавить столбец | Pandera strict schema |
| Type drift | записать текст в `amount_rub` | Pandera и parser |
| Domain | отрицательная сумма или неизвестный status | invariant, Pandera |
| Reconciliation | изменить order total без items | invariant и SQL control |
| Configuration | неизвестная timezone или лишнее поле | Pydantic |
| Regression | изменить правило paid revenue | golden semantic diff |
| Freshness | batch timestamp старше SLA | monitoring |
| Volume | число строк вне исторического диапазона | monitoring |
| Publication | gate падает после подготовки файлов | atomic publish test |

Каждый дефект получает стабильный идентификатор, минимальный fixture и ожидаемый класс
ошибки. Один тест не должен проверять сразу несколько несвязанных дефектов.

## Интеграционный мини-проект

`07/10` собирает поставку:

```text
reliable-order-pipeline/
├── config.json
├── mart/
│   ├── orders.parquet
│   └── daily_metrics.csv
├── quality/
│   ├── invariant-report.json
│   ├── schema-report.json
│   ├── sql-checks.json
│   ├── regression-report.json
│   └── monitoring-report.json
├── logs/
│   └── run.jsonl
├── run-report.json
├── manifest.json
└── current.json
```

Pipeline обязан:

- валидировать конфигурацию до чтения данных;
- проверить входные DataFrame, ключи, связи и межстолбцовые правила;
- выполнить преобразование и независимые SQL-reconciliation checks;
- сравнить tiny output с reviewed golden baseline;
- измерить freshness, volume, null и duplicate rates;
- разделить `data_failure`, `configuration_failure` и `system_failure`;
- записать версии контрактов, параметры запуска, row counts и checksums;
- публиковать новую immutable-версию и атомарно менять `current.json` только при success.

## Проверяемость

- Все генераторы и тестовые входы детерминированы.
- Property-based tests сохраняют минимальный falsifying example в обычный regression
  test, если он раскрывает новый класс дефекта.
- Machine reports используют стабильные идентификаторы checks и не зависят от текста
  исключения библиотеки.
- Golden comparison нормализует порядок строк и числовое представление до diff.
- Monitoring tests фиксируют clock, чтобы freshness не зависела от текущего времени.
- Integration tests проверяют как успешную публикацию, так и сохранение прежнего
  `current.json` после любого failed gate.
