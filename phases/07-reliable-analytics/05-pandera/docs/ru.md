# Контракты DataFrame с Pandera

> DataFrame-контракт проверяет форму и домены данных, но не отменяет межтабличные бизнес-инварианты.

**Тип:** Build  
**Треки:** core  
**Пререквизиты:** 07/04  
**Время:** ~90 минут

## Цели обучения

- описывать strict schema, nullable policy, uniqueness и checks;
- собирать несколько нарушений через `lazy=True`;
- отделять DataFrame schema от foreign key и reconciliation.

## Проблема

Проверки вида `assert "order_id" in df` не ловят лишние столбцы, duplicate grain,
неизвестный status и несколько дефектов одновременно. Первый exception заставляет
чинить выгрузку итерациями.

## Концепция

Pandera превращает ожидания к DataFrame в версионированную схему. `strict=True`
запрещает drift столбцов, Column checks задают домены, а lazy validation возвращает
полную таблицу failure cases. Foreign keys и сверка сумм остаются явными отдельными
checks, потому что охватывают несколько таблиц.

## Соберите это

`outputs/dataframe_contract.py` определяет схемы `users`, `orders`, `order_items` и
контракт версии `1.0.0`. Для Pandera используется рекомендованный импорт
`pandera.pandas`.

```bash
uv run --locked python phases/07-reliable-analytics/05-pandera/outputs/dataframe_contract.py \
  --data-dir phases/07-reliable-analytics/data/tiny \
  --output /tmp/schema-report.json
```

## Используйте это

Сначала анализируйте `schema.*`, затем relationship checks. Stable IDs принадлежат
вашему контракту; сырые сообщения библиотеки сохраняются только как диагностические
failure cases.

## Сломайте это

Удалите `currency`, добавьте `extra`, установите status `complete` и amount `-1.001`.
Lazy report должен показать несколько нарушений за один запуск. Затем создайте orphan
user: individual schemas пройдут, но `orders.user_fk` упадет.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/07-reliable-analytics/05-pandera/tests
```

## Поставьте результат

Результат: `outputs/dataframe_contract.py` с версией контракта, тремя schemas,
межтабличными checks и единым JSON report.

## Упражнения

1. Добавьте допустимый домен country и обсудите цену его поддержки.
2. Запретите заказ без хотя бы одной строки.
3. Подготовьте migration note для schema version `1.1.0`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Strict schema | Только строгие типы | Точное множество разрешенных столбцов |
| Lazy validation | Ленивое вычисление pandas | Сбор всех доступных ошибок вместо остановки на первой |
| Data contract | Полная бизнес-логика pipeline | Версионированные ожидания к данным и их изменению |

## Дополнительное чтение

- [Pandera DataFrame schemas](https://pandera.readthedocs.io/en/stable/dataframe_schemas.html) — основные Column и DataFrame checks.
- [Pandera data validation](https://pandera.readthedocs.io/en/stable/data_validation.html) — validation workflow и поддерживаемые типы.
- [Pandera error reports](https://pandera.readthedocs.io/en/stable/error_report.html) — структура lazy validation errors.
