# Проверки SQL-витрин

> Независимый SQL-контроль особенно ценен, когда production-преобразование написано не на SQL.

**Тип:** Case  
**Треки:** core  
**Пререквизиты:** 07/06  
**Время:** ~90 минут

## Цели обучения

- писать отдельные запросы для grain, domain, relationships и reconciliation;
- возвращать violation count и диагностический sample;
- не смешивать проверку с production query.

## Проблема

Если витрина и ее контроль используют один и тот же join и формулу, общий дефект
останется незамеченным. Один гигантский SQL с boolean-флагами также плохо показывает
причину.

## Концепция

Каждый SQL check возвращает только нарушающие строки. Пустой результат означает pass.
DuckDB регистрирует исходные таблицы и независимо проверяет ключи, foreign keys,
status/amount domain и сумму `quantity * unit_price_rub`.

## Соберите это

Откройте список `CHECKS` в `outputs/sql_quality_checks.py`.

```bash
uv run --locked python phases/07-reliable-analytics/07-sql-checks/outputs/sql_quality_checks.py \
  --data-dir phases/07-reliable-analytics/data/tiny \
  --output /tmp/sql-checks.json
```

Каждый результат содержит stable ID, `violation_count` и не более пяти примеров.

## Используйте это

Запускайте SQL suite после schema checks, но до публикации. `try_cast` позволяет
представить плохой amount как нарушение домена, а не аварийно оборвать весь отчет.

## Сломайте это

Повторите order, создайте orphan user и увеличьте цену одной строки на копейку.
Убедитесь, что каждый запрос возвращает конкретную нарушающую строку.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/07-reliable-analytics/07-sql-checks/tests
```

## Поставьте результат

Результат: `outputs/sql_quality_checks.py`, самостоятельный DuckDB quality suite с
единым машинным отчетом.

## Упражнения

1. Добавьте check «каждый order имеет хотя бы один item».
2. Проверьте, что paid revenue в mart совпадает с независимой суммой source orders.
3. Добавьте sample policy, скрывающую чувствительные поля.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Violation query | Возвращает все валидные строки | Возвращает только контрпримеры контракту |
| Reconciliation | Повтор production query | Независимая сверка двух представлений одного факта |
| Relationship check | Проверка типа ключа | Проверка существования ссылки в родительском grain |

## Дополнительное чтение

- [DuckDB Python API](https://duckdb.org/docs/stable/clients/python/overview) — соединение, выполнение SQL и интеграция с pandas.
- [DuckDB casting](https://duckdb.org/docs/stable/sql/expressions/cast.html) — `CAST` и `TRY_CAST` для диагностируемой проверки типов.
- [DuckDB aggregate functions](https://duckdb.org/docs/stable/sql/functions/aggregates.html) — группировки для grain и reconciliation checks.
