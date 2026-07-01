# Resampling и агрегация

> Resampling меняет не только частоту ряда, но и смысл наблюдения, поэтому каждая новая
> точка должна пройти timezone bucket, aggregation policy и reconciliation.

- **Тип:** Build
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/01-time-index`
- **Время:** ~75 минут
- **Результат:** вы переводите event-level и daily extracts в регулярный daily/weekly
  ряд с явными правилами label/closed, complete-period policy, timezone normalization и
  reconciliation.

## Цели обучения

- Превратить timezone-aware события в business-date buckets без UTC-сдвига.
- Собрать daily stock series из opening balance и signed deltas.
- Построить weekly ряд с явной политикой `label=left`, `closed=left` и Monday week start.
- Сверить resampled series с опубликованной метрикой и не обучать forecast на partial
  periods.

## Проблема

После `14/01` команда знает, что published daily ряд `active_subscriptions` имеет
регулярный time index. Следующий шаг кажется простым: взять события подписок, вызвать
`resample`, получить недели и отдать их в baseline.

В этом месте часто появляются тихие ошибки:

- событие `2026-03-01T21:30:00Z` в `Europe/Moscow` относится к `2026-03-02`, а не к
  `2026-03-01`;
- `active_subscriptions` является stock metric, поэтому недельная сумма daily values
  бессмысленна;
- последняя неделя начинается `2026-03-16`, но содержит только один полный день и один
  partial day;
- event-level расчет может не сойтись с published daily extract, а модель потом будет
  сравнивать разные версии реальности.

Урок строит resampling pipeline, который не доверяет ни одному из этих шагов молча.

## Концепция

Resampling отвечает на вопрос: какое новое наблюдение получается после смены частоты или
grain. Для forecast этого недостаточно описать одной строкой `resample("W")`.

| Слой | Что фиксируем | Что ломается без фиксации |
|---|---|---|
| Timestamp bucket | Business timezone и business date | UTC-дата сдвигает событие в соседний день. |
| Metric type | Stock, flow, ratio или count | Stock metric суммируют как flow и меняют смысл. |
| Opening balance | Состояние до первой даты | Cumulative deltas не восстанавливают published value. |
| Weekly policy | Week start, `label`, `closed`, value rule | Неделя получает неверную границу или неполный хвост. |
| Reconciliation | Сверка computed и published values | Pipeline строит ряд, который не равен официальной метрике. |
| Completeness | Что можно брать в training | Partial period выглядит как реальное падение или рост. |

В `tiny` профиле события лежат в `subscription_events.csv`. Первая строка выглядит так:

```csv
event_id,segment_id,occurred_at,available_at,event_type,delta_active
sub-delta-all-2026-03-02,all,2026-03-01T21:30:00Z,2026-03-02T09:10:00+03:00,active_subscription_delta,18
```

UTC-дата здесь `2026-03-01`, но business date в `Europe/Moscow` равна `2026-03-02`.
Если взять `.dt.date` до timezone conversion, daily ряд начнется на день раньше и уже не
сойдется с `metric_observations.csv`.

## Соберите это

Сначала соберите прозрачную версию daily resampling. Для stock metric нужен opening
balance: значение до первой даты. После этого каждое событие добавляет signed delta к
текущему состоянию.

```python
from collections import defaultdict
from datetime import datetime
from zoneinfo import ZoneInfo

tz = ZoneInfo("Europe/Moscow")
opening_balance = 980
events = [
    {"occurred_at": "2026-03-01T21:30:00Z", "delta_active": 18},
    {"occurred_at": "2026-03-02T21:30:00Z", "delta_active": 9},
]

deltas_by_date = defaultdict(int)
for event in events:
    occurred_at = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
    business_date = occurred_at.astimezone(tz).date()
    deltas_by_date[business_date] += event["delta_active"]

balance = opening_balance
daily_rows = []
for business_date in sorted(deltas_by_date):
    balance += deltas_by_date[business_date]
    daily_rows.append({"observed_date": business_date.isoformat(), "value": balance})
```

Этот код показывает механизм, который обычно скрывает pandas: сначала timestamp
превращается в business date, потом deltas агрегируются внутри bucket, и только потом
восстанавливается stock value.

Weekly слой нельзя строить универсальной суммой. Для `active_subscriptions` weekly value
в этом уроке означает `last_complete_observation` внутри недели с Monday start. Неделя
`2026-03-16` видима в output, но `include_in_training=false`, потому что она еще
неполная.

## Используйте это

Готовый артефакт урока:

```text
outputs/resampling_pipeline.py
```

Запуск из корня урока:

```bash
python outputs/resampling_pipeline.py \
  --events ../data/tiny/subscription_events.csv \
  --metrics ../data/tiny/metric_observations.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --spec ../data/tiny/resampling_spec.json \
  --output-dir outputs
```

CLI пишет четыре файла:

- `outputs/daily_resampled.csv` - daily stock series после timezone normalization;
- `outputs/weekly_resampled.csv` - weekly rows с `weekly_label=left`,
  `weekly_closed=left` и флагом complete week;
- `outputs/reconciliation.csv` - сверка computed values с published
  `metric_observations.csv`;
- `outputs/resampling_report.json` - machine-readable audit с blocking errors и warnings.

В baseline `tiny` отчет валиден, но содержит два предупреждения:

```json
{
  "valid": true,
  "warnings": [
    "partial_daily_rows_excluded_from_training",
    "incomplete_weeks_excluded_from_training"
  ]
}
```

Это хороший результат. Pipeline не прячет partial day `2026-03-17` и неполную неделю
`2026-03-16`, но явно исключает их из training.

Если вы используете pandas в рабочем проекте, держите тот же контракт. Один безопасный
вариант - сначала получить business date, затем join к calendar table и группировать по
явному `week_start`, а не надеяться, что строка frequency сама совпала с бизнес-смыслом:

```python
import pandas as pd

events = pd.read_csv("subscription_events.csv")
events["occurred_at"] = pd.to_datetime(events["occurred_at"], utc=True)
events["observed_date"] = events["occurred_at"].dt.tz_convert("Europe/Moscow").dt.date

daily_delta = (
    events.groupby(["segment_id", "observed_date"], as_index=False)["delta_active"]
    .sum()
)
```

После pandas-агрегации все равно нужен reconciliation report. Библиотека помогает
переложить строки по bucket, но не знает, является ли метрика stock, flow или ratio.

## Сломайте это

Проверьте пять поломок.

1. Скопируйте `event_id` из первой строки во вторую. Check `event_id_unique` должен
   стать blocking error.
2. Поменяйте в `resampling_spec.json` `weekly_label` на `right`. Check
   `resampling_policies_supported` должен заблокировать weekly output.
3. Измените published value для `all/2026-03-12` на `1105`. Check
   `published_series_reconciles` должен показать difference `-5`.
4. Поставьте `available_at = 2026-03-19T10:00:00+03:00` для события внутри complete
   history. Check `complete_events_available_by_origin` должен заблокировать training.
5. Удалите `2026-03-10` из календаря. Check `calendar_dates_cover_resampling_window`
   должен упасть до weekly aggregation.

Отдельно запустите строгий режим:

```bash
python outputs/resampling_pipeline.py \
  --events ../data/tiny/subscription_events.csv \
  --metrics ../data/tiny/metric_observations.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --spec ../data/tiny/resampling_spec.json \
  --fail-on-warning
```

Он вернет non-zero exit code из-за partial periods. Это удобно для production gate, если
forecast package нельзя публиковать без ручного review.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/02-resampling/tests -v
```

Они проверяют:

- воспроизводимость `tiny` профиля, включая `subscription_events.csv` и
  `resampling_spec.json`;
- корректный UTC-to-business-date bucket;
- восстановление daily stock series через opening balance и cumulative deltas;
- weekly rows с Monday start и left/left policy;
- reconciliation computed values с published metric extract;
- явное исключение partial daily и weekly periods из training;
- CLI output и строгий режим `--fail-on-warning`.

Критерий интерпретации: `error_count > 0` запрещает forecast. `warning_count > 0` не
запрещает расчет, но требует limitation и решения, что делать с partial periods.

## Поставьте результат

Итоговый артефакт:

```text
outputs/resampling_pipeline.py
```

Он принимает event-level deltas, published metrics, calendar, forecast scenario и
resampling spec, а затем выпускает daily/weekly series, reconciliation table и audit
report. `code/main.py` пересобирает committed outputs урока:

```bash
uv run --locked python phases/14-time-series/02-resampling/code/main.py
```

Пакет можно использовать в следующих уроках как вход для rolling features, seasonal
profiles, leakage checks и baselines. Важное ограничение: этот pipeline покрывает
stock-from-deltas metric. Flow, ratio и count metrics требуют своей aggregation policy и
своих reconciliation checks.

## Упражнения

1. Добавьте в `subscription_events.csv` день без события и объясните, почему для stock
   metric это может быть нулевой delta, а не missing date.
2. Измените `opening_balances.android` на `309` и найдите первую строку reconciliation,
   где появляется расхождение.
3. Добавьте flow metric `support_tickets` и опишите, почему weekly aggregation для нее
   будет суммой, а не `last_complete_observation`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Resampling | Это просто смена частоты через одну функцию. | Перевод наблюдений в новый time grain с явной политикой bucket, aggregation и completeness. |
| Business date bucket | Достаточно взять UTC date из timestamp. | Дата наблюдения после conversion в бизнес-таймзону. |
| Stock metric | Ее можно складывать по периодам как события. | Состояние на дату; при недельной агрегации нужен отдельный смысл значения. |
| Flow metric | Это то же самое, что stock. | Накопление за период; для weekly часто используется сумма daily flows. |
| Opening balance | Необязательная константа. | Стартовое состояние до первой даты, без которого deltas не восстанавливают stock series. |
| Reconciliation | Косметическая сверка после графика. | Blocking check, который доказывает, что resampled series совпадает с опубликованной метрикой. |
| Partial period | Его можно удалить без следа. | Неполный период должен быть видим в output и явно исключен из training. |

## Дополнительное чтение

- [pandas: Time series / date functionality](https://pandas.pydata.org/docs/user_guide/timeseries.html) — прочитайте разделы про resampling, offsets и time zone handling; они объясняют API, но не заменяют business contract.
- [pandas: Group by: split-apply-combine](https://pandas.pydata.org/docs/user_guide/groupby.html) — полезно для варианта с явным calendar join и группировкой по `week_start`.
- [pandas: Time zone handling](https://pandas.pydata.org/docs/user_guide/timeseries.html#time-zone-handling) — сфокусируйтесь на разнице между timezone-aware timestamps и локальной business date.
- [Forecasting: Principles and Practice, Temporal aggregation](https://otexts.com/fpp3/aggregates.html) — посмотрите, как смена временного уровня влияет на смысл ряда и последующую forecast accuracy.
