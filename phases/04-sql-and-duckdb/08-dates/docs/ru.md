# Время и даты в SQL

> Сначала сохраните instant, затем выберите timezone и только потом режьте календарь.

**Тип:** Case
**Треки:** Core
**Пререквизиты:** 04/07
**Время:** ~90 минут
**Результат:** нормализует timestamps и строит периоды в явной бизнес-зоне.

## Цели обучения

- Различать строку времени, instant, local time и calendar date.
- Нормализовать разные UTC offsets без изменения момента.
- Строить день и месяц после выбора бизнес-timezone.
- Сохранять пропущенные timestamps как отдельный quality signal.

## Проблема

Заказы записаны с `Z`, `+03:00`, `-05:00` и другими offsets. Если удалить suffix и
сгруппировать строку по дню, события одного instant могут попасть в разные периоды, а
вечерняя активность пересечет границу бизнес-дня.

## Концепция

Разделяйте четыре сущности:

```text
source string -> TIMESTAMPTZ instant -> local time in timezone -> DATE/month
```

UTC нужен для сравнения моментов и длительностей. Бизнес-зона нужна для календарных
метрик: дня, недели, месяца.

## Соберите это

Ручной контроль:

```text
2026-01-05 10:00 +03:00
- 03:00
= 2026-01-05 07:00 UTC
```

В `Europe/Moscow` этот instant снова отображается как 10:00. В New York это 02:00.

```bash
uv run --locked python code/main.py
```

## Используйте это

```sql
ordered_at::TIMESTAMPTZ AS ordered_at_instant,
timezone('UTC', ordered_at_instant) AS ordered_at_utc,
timezone('Europe/Moscow', ordered_at_instant) AS business_local_time,
cast(timezone('Europe/Moscow', ordered_at_instant) AS DATE) AS business_date
```

Артефакт принимает timezone параметром и строит `business_month` после конвертации.

## Сломайте это

1. Приведите строку сразу к `TIMESTAMP` без timezone.
2. Вычислите `DATE` в UTC и назовите ее бизнес-днем.
3. Замените пустой timestamp текущим временем.
4. Передайте несуществующую timezone.

Каждая ошибка меняет смысл периода или скрывает качество источника.

## Проверьте это

- 12 заказов сохраняются;
- 11 timestamps парсятся, один остается missing;
- месяцы в Moscow: январь 2, февраль 4, март 3, апрель 2;
- `O1001` нормализуется в `07:00Z`.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

```bash
uv run --locked python outputs/time_model.py \
  --orders ../data/tiny/orders.csv \
  --business-timezone Europe/Moscow
```

CLI поставляет нормализованные строки и сводку по календарным месяцам.

## Упражнения

1. Постройте ISO week в бизнес-зоне.
2. Сравните даты в Moscow и New York для события около полуночи.
3. Добавьте явную политику для missing timestamp.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Instant | Отформатированная строка | Однозначная точка на временной шкале |
| Offset | Название timezone | Смещение от UTC в конкретной записи |
| Timezone | Постоянный offset | Набор исторических и календарных правил |
| Business date | UTC date | Дата instant в выбранной бизнес-зоне |
| DATE_TRUNC | Форматирование | Преобразование к календарной границе |

## Дополнительное чтение

- [DuckDB: Timestamp Types](https://duckdb.org/docs/current/sql/data_types/timestamp) — разберите `TIMESTAMP` и `TIMESTAMPTZ`.
- [DuckDB: Time Zones](https://duckdb.org/docs/current/sql/data_types/timezones) — изучите instants, binning и ICU.
- [DuckDB: TIMESTAMPTZ Functions](https://duckdb.org/docs/current/sql/functions/timestamptz) — найдите `timezone`, `date_part` и календарные функции.
- [IANA Time Zone Database](https://www.iana.org/time-zones) — поймите, почему timezone является набором изменяющихся правил, а не числом.
