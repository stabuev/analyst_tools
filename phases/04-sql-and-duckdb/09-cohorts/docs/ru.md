# Когорты на SQL

> Когортная метрика корректна только при фиксированных входе, периоде и знаменателе.

**Тип:** Case
**Треки:** Core
**Пререквизиты:** 04/08
**Время:** ~105 минут
**Результат:** строит cohort-period матрицу с явным знаменателем.

## Цели обучения

- Определять cohort month и activity month в одной timezone.
- Дедуплицировать технические повторы событий.
- Строить `period_index` как календарное расстояние.
- Создавать полную grid, включая нулевую активность.
- Делить active users на фиксированный cohort size.

## Проблема

Для декабрьской когорты активны два пользователя в январе и один в феврале. Если каждый
месяц менять знаменатель на число наблюдаемых пользователей, retention всегда будет
выглядеть высоким. Повторная доставка `E0005` дополнительно завысит event count.

## Концепция

Контракт витрины:

```text
grain = cohort_month, period_index
cohort_month = месяц регистрации
activity_month = месяц уникальной активности
period_index = month_diff(cohort_month, activity_month)
retention = distinct active users / cohort_size
```

`cohort_size` вычисляется один раз из users и повторяется по периодам.

## Соберите это

Декабрьская когорта: U001 и U002, размер 2.

```text
period 0: 0 / 2 = 0.0
period 1: 2 / 2 = 1.0
period 2: 1 / 2 = 0.5
```

Нулевая ячейка должна существовать как строка матрицы.

```bash
uv run --locked python code/main.py
```

## Используйте это

Pipeline состоит из:

1. `users` с cohort month;
2. `cohort_sizes`;
3. `deduplicated_events`;
4. user-month `activity`;
5. полной `grid` через `range`;
6. `active_users`;
7. LEFT JOIN активности к grid.

Так отсутствие события превращается в `active_users = 0`, а не в отсутствие строки.

## Сломайте это

1. Считайте строки events вместо distinct users.
2. Оставьте повтор `E0005`.
3. Используйте число активных как знаменатель.
4. Стройте cohort month в UTC, activity month в Moscow.
5. Не создавайте grid и потеряйте нулевые периоды.

## Проверьте это

- cohort sizes: 2, 3, 3;
- 16 доставленных строк событий и 15 уникальных event_id;
- 12 ячеек полной матрицы;
- декабрь period 1 = 1.0, period 2 = 0.5;
- retention всегда между 0 и 1.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

```bash
uv run --locked python outputs/cohort_mart.py \
  --users ../data/tiny/users.csv \
  --events ../data/tiny/events.csv
```

CLI поставляет cohort mart и checks дедупликации.

## Упражнения

1. Замените регистрацию на первый оплаченный заказ как вход в когорту.
2. Постройте weekly cohort matrix.
3. Добавьте сегмент plan в grain и проверьте знаменатели.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Cohort | Любая группа | Пользователи с общим моментом или условием входа |
| Activity period | Номер события | Календарный период наблюдаемой активности |
| Denominator | Активные текущего месяца | Фиксированный размер исходной когорты |
| Retention | Число событий | Доля участников когорты с активностью |
| Cohort grid | Только наблюдаемые строки | Полное пространство допустимых cohort-period |

## Дополнительное чтение

- [DuckDB: Date Functions](https://duckdb.org/docs/current/sql/functions/date) — изучите `date_diff`, `date_trunc` и интервалы.
- [DuckDB: DISTINCT](https://duckdb.org/docs/current/sql/query_syntax/select#distinct-clause) — разберите дедупликацию событий и пользователей.
- [DuckDB: range](https://duckdb.org/docs/current/sql/functions/list#range-functions) — используйте генерацию полных периодов.
- [PostgreSQL: Date/Time Functions](https://www.postgresql.org/docs/current/functions-datetime.html) — сопоставьте календарные операции и interval arithmetic.
