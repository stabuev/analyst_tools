# Временной индекс, частота и календарный grain

> Прогноз начинается не с модели, а с доказательства, что прошлые даты действительно
> образуют регулярный и доступный на момент прогноза ряд.

- **Тип:** Learn
- **Треки:** Decision
- **Пререквизиты:** `08-product-analytics/11-business-conclusion`, `09-applied-statistics/10-robust-methods`
- **Время:** ~75 минут
- **Результат:** вы задаете временной индекс, timezone, frequency, observation window и
  календарный grain для продуктовой метрики до построения прогноза.

## Цели обучения

- Зафиксировать forecast origin, horizon, business timezone и declared frequency.
- Отличить missing date, настоящий ноль, incomplete period и late revision.
- Проверить, что `(metric_id, segment_id, observed_date)` является grain ряда.
- Выпустить machine-readable audit, который блокирует forecast при нарушенном временном
  контракте.

## Проблема

Команда хочет спрогнозировать `active_subscriptions` на четыре недели вперед перед
весенней кампанией. В таблице есть даты, значения и сегменты, поэтому кажется, что можно
сразу вызвать модель. Но в реальной аналитике самый дорогой провал часто появляется
раньше модели:

- одна бизнес-дата пропала при загрузке;
- последнее значение еще не закрыто;
- UTC timestamp попал в другую локальную дату;
- историческое значение поменялось после forecast origin;
- сегментный ряд имеет дубликат на ту же дату.

Если это не поймать до forecasting, модель обучится на истории, которой аналитик на
самом деле не видел, или примет дырку в данных за резкое падение метрики.

## Концепция

Временной ряд для прогноза - это не просто две колонки `date, value`. Минимальный
контракт включает:

| Слой | Вопрос | Failure mode |
|---|---|---|
| Business time | В какой timezone определяется день? | UTC-полночь сдвигает события между датами. |
| Frequency | Как часто должен появляться ряд? | Пропущенная дата маскируется как отсутствие активности. |
| Grain | Что является уникальным наблюдением? | Дубликат размножает одну дату и ломает backtest. |
| Availability | Что было известно в forecast origin? | Late revision создает взгляд в будущее. |
| Completeness | Какие периоды закрыты? | Неполная последняя дата выглядит как падение. |

Для этой фазы `forecast_scenario.json` фиксирует:

```json
{
  "target_metric": "active_subscriptions",
  "target_segments": ["all", "android"],
  "timezone": "Europe/Moscow",
  "frequency": "D",
  "complete_through": "2026-03-16",
  "forecast_origin": "2026-03-18T09:00:00+03:00",
  "horizon_days": 28
}
```

Урок не доказывает, какая модель лучше. Он отвечает на более ранний вопрос: можно ли
доверять календарной оси, на которой эта модель будет учиться.

## Соберите это

Сначала сделайте ручной контрольный расчет для одного сегмента. Для daily frequency
полная история должна содержать все даты от `expected_start` до `complete_through`.

```python
from datetime import date, timedelta

def daterange(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]

expected = set(daterange(date(2026, 3, 2), date(2026, 3, 16)))
observed = {
    date(2026, 3, 2),
    date(2026, 3, 3),
    date(2026, 3, 4),
}
missing = sorted(expected - observed)
```

Такой расчет скучный, зато он показывает важное: missing date не равен нулю. Ноль должен
быть опубликованным значением, а missing date означает, что ряд нерегулярен или данные не
доехали.

Второй ручной контроль - timezone bucket. Если `period_start_at` хранится в UTC, его
нужно перевести в бизнес-таймзону и сравнить локальную дату с `observed_date`.

```python
from datetime import datetime
from zoneinfo import ZoneInfo

instant = datetime.fromisoformat("2026-03-01T21:00:00+00:00")
local_date = instant.astimezone(ZoneInfo("Europe/Moscow")).date()
assert local_date.isoformat() == "2026-03-02"
```

Если локальная дата не совпадает, вы можете получить ложный понедельник вместо
воскресенья, испортить weekly seasonality и потом долго лечить модель, хотя ошибка была в
календаре.

## Используйте это

В уроке готов reusable CLI `time-index-auditor`. Запустите его из корня урока:

```bash
python outputs/time_index_auditor.py \
  --metrics ../data/tiny/metric_observations.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --revisions ../data/tiny/data_revisions.csv \
  --output outputs/time_index_audit.json
```

Отчет содержит:

- `valid`: можно ли продолжать без blocking errors;
- `checks`: список проверок с `severity`, `observed`, `expected` и sample строками;
- `series`: сводку по каждому target segment;
- `summary.blocking_errors`: причины, которые запрещают forecast;
- `summary.warnings`: факты, которые не блокируют запуск, но должны попасть в
  limitations.

В baseline `tiny` отчет валиден, но содержит два предупреждения:

```json
{
  "valid": true,
  "warnings": [
    "incomplete_rows_after_complete_through",
    "revisions_after_forecast_origin"
  ]
}
```

Это правильное состояние для первого урока. Неполная последняя дата и late revision не
исчезают, но они не подменяются молчаливой очисткой.

## Сломайте это

Проверьте четыре поломки.

1. Удалите строку `android` за `2026-03-05`. Check
   `complete_history_has_no_missing_dates` должен стать blocking error.
2. Скопируйте строку `active_subscriptions/all/2026-03-02`. Check
   `metric_segment_date_unique` должен найти дубликат grain.
3. Поставьте `period_start_at = 2026-03-02T21:00:00Z` для даты `2026-03-02`. В
   `Europe/Moscow` это уже `2026-03-03`, поэтому check
   `timezone_bucket_matches_observed_date` должен упасть.
4. Удалите `2026-04-14` из календаря. История может выглядеть полной, но calendar уже не
   покрывает forecast horizon.

Отдельно запустите строгий режим:

```bash
python outputs/time_index_auditor.py \
  --metrics ../data/tiny/metric_observations.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --revisions ../data/tiny/data_revisions.csv \
  --fail-on-warning
```

Он вернет non-zero exit code даже при предупреждениях. Такой режим полезен, когда
pipeline не должен публиковать forecast package без ручного review.

## Проверьте это

Тесты урока покрывают поведение артефакта:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/01-time-index/tests -v
```

Они проверяют:

- воспроизводимость `tiny` профиля через `generate_data.py --check`;
- валидный baseline с двумя явными warnings;
- блокировку duplicate grain;
- блокировку missing complete date;
- блокировку timezone bucket mismatch;
- блокировку incomplete complete-date rows;
- покрытие календарем истории и horizon;
- CLI output и режим `--fail-on-warning`.

Критерий интерпретации простой: если `summary.blocking_errors` не пустой, forecast не
строится. Если есть `summary.warnings`, forecast можно продолжать только с limitations и
решением, как эти warnings будут учитываться в следующих уроках.

## Поставьте результат

Итоговый артефакт:

```text
outputs/time_index_auditor.py
```

Он принимает published metric series, calendar, scenario и optional revisions table и
возвращает JSON-аудит. Его можно использовать в следующих уроках перед resampling,
rolling features, backtesting и model comparison.

Пример запуска с сохранением отчета:

```bash
python outputs/time_index_auditor.py \
  --metrics ../data/tiny/metric_observations.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --revisions ../data/tiny/data_revisions.csv \
  --output outputs/time_index_audit.json
```

`code/main.py` запускает тот же аудит на committed `tiny` профиле и обновляет
`outputs/time_index_audit.json`.

## Упражнения

1. Добавьте третий сегмент `ios` только в `forecast_scenario.json` и объясните, какой
   check должен упасть.
2. Сдвиньте `complete_through` на `2026-03-17` и сравните результат с исходным отчетом.
3. Добавьте revision до forecast origin и объясните, почему это не то же самое, что
   revision after origin.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Time index | Достаточно иметь колонку с датой. | Упорядоченная временная ось с declared frequency, timezone и known completeness. |
| Frequency | Ее можно вывести из любых соседних дат. | Обещание, как часто ряд обязан иметь наблюдение. |
| Calendar grain | Это просто формат даты. | Единица наблюдения в бизнес-календаре: день, неделя, месяц или другой период. |
| Forecast origin | Последняя дата в таблице. | Момент времени, в который аналитик делает forecast и знает только опубликованные к этому моменту данные. |
| Late revision | Можно заменить старое значение и забыть. | Изменение истории после origin, которое должно попасть в audit и limitations. |
| Incomplete period | Это обычный ноль. | Еще не закрытый период, который нельзя молча смешивать с полной историей. |

## Дополнительное чтение

- [pandas: Time series / date functionality](https://pandas.pydata.org/docs/user_guide/timeseries.html) — прочитайте разделы про timestamps, date ranges, offsets, time zones и frequency conversion; они задают API, который будет использоваться дальше в фазе.
- [Python `zoneinfo`](https://docs.python.org/3/library/zoneinfo.html) — разберите, как стандартная библиотека работает с IANA time zones и почему timezone должен быть частью контракта данных.
- [Forecasting: Principles and Practice, Time series patterns](https://otexts.com/fpp3/tspatterns.html) — посмотрите, как тренд, сезонность и календарная структура зависят от корректной временной оси.
