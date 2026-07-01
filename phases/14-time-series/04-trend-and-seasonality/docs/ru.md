# Тренд, сезонность и календарные эффекты

> Сезонный профиль описывает структуру истории, но не превращает календарный всплеск в
> причинный вывод и не заменяет forecast baseline.

- **Тип:** Learn
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/03-rolling`
- **Время:** ~75 минут
- **Результат:** вы строите trend summary, weekly/monthly seasonality profile и inventory
  известных календарных эффектов, не используя неполные периоды и неизвестные на момент
  прогноза будущие признаки.

## Цели обучения

- Отделить тренд, недельную сезонность и календарные события от data-quality дефектов.
- Построить day-of-week profile по complete history и явно пометить недостаточную
  monthly history.
- Проверить, что holiday, campaign и release context были известны до forecast origin.
- Выпустить календарный inventory, где будущие эффекты без исторических примеров не
  становятся автоматическим forecast uplift.

## Проблема

После `14/03` у нас есть регулярный ряд и leakage-safe rolling features. Следующий соблазн
аналитика - посмотреть на график active subscriptions и сказать:

```text
В понедельник рост, в выходные просадка, а перед кампанией будет еще выше.
```

Это опасно сразу по трем причинам.

1. Тренд может смешаться с недельным циклом. Если последние понедельники выше первых,
   это может быть общий рост ряда, а не особая сила понедельника.
2. Календарный эффект можно использовать в будущем только если он был известен до
   forecast origin. Иначе это такая же временная утечка, как `lag=0`.
3. Единичный holiday, release или campaign day не доказывает устойчивый эффект. Он
   попадает в inventory и review, но не становится причинным claim.

Урок строит `seasonality-profiler`: CLI, который выпускает trend summary, профиль по дням
недели, monthly row с предупреждением о недостаточной истории и календарный inventory для
holiday, campaign и release.

## Концепция

В этом уроке есть три разных объекта.

| Объект | Что описывает | Главный риск |
|---|---|---|
| Trend | Долгосрочное направление уровня ряда. | Принять тренд за сезонность. |
| Seasonality | Повторяемый календарный паттерн внутри периода, например недели. | Подогнать период по одному удачному окну. |
| Calendar effect | Конкретное событие: праздник, кампания, релиз. | Использовать событие, которое не было известно на forecast origin, или объявить причинность. |

Для forecast hygiene важны две даты.

```text
observed_date <= complete_through       -> можно использовать в историческом профиле
known_before_date <= forecast_origin    -> можно использовать как известный календарный контекст
```

`calendar.csv` покрывает history и horizon, но этого мало. Нужно еще доказать, что
объявленная кампания в `campaign_calendar.csv` совпадает с `campaign_active=true` в
daily calendar, а релиз из `release_calendar.csv` совпадает с `release_active=true`.
Иначе разные части pipeline будут видеть разные будущие признаки.

Monthly seasonality в tiny-профиле специально не считается устойчивой. История содержит
только март 2026 года, поэтому profiler выпускает строку `seasonality_type=month`, но
ставит `enough_history=false` и warning `monthly_profile_has_single_cycle`.

## Соберите это

Сначала посчитайте weekly profile вручную. Берем только complete training rows.

```python
from collections import defaultdict

rows = [
    {"date": "2026-03-02", "day_of_week": "Monday", "value": 998, "complete": True},
    {"date": "2026-03-09", "day_of_week": "Monday", "value": 1073, "complete": True},
    {"date": "2026-03-16", "day_of_week": "Monday", "value": 1124, "complete": True},
    {"date": "2026-03-17", "day_of_week": "Tuesday", "value": 1133, "complete": False},
]

groups = defaultdict(list)
for row in rows:
    if row["complete"]:
        groups[row["day_of_week"]].append(row["value"])

monday_mean = sum(groups["Monday"]) / len(groups["Monday"])
assert monday_mean == 1065
```

Теперь добавьте seasonal index: разницу между средним дня недели и средним значением
сегмента.

```python
all_complete_values = [998, 1007, 1016, 1025, 1034, 1003, 1012,
                       1073, 1082, 1091, 1100, 1109, 1066, 1075, 1124]
segment_mean = sum(all_complete_values) / len(all_complete_values)
seasonal_index_monday = monday_mean - segment_mean

assert round(segment_mean, 6) == 1054.333333
assert round(seasonal_index_monday, 6) == 10.666667
```

Важно: это не прогноз на следующий понедельник. Это диагностический профиль, который
позже поможет построить seasonal naive baseline и проверить остатки.

Календарный effect inventory строится отдельно. Для holiday `2026-03-08` profiler
сравнивает значение с обычным Sunday baseline без holiday date:

```text
holiday all observed = 1012
normal Sunday baseline = 1075
lift vs seasonal profile = -63
```

Для будущей кампании `2026-03-20`-`2026-03-27` в истории нет campaign days. Поэтому
правильный статус:

```text
known_future_effect_without_training_examples
```

Это не ошибка. Ошибкой было бы молча превратить такой статус в ожидаемый uplift.

## Используйте это

Готовый артефакт:

```text
outputs/seasonality_profiler.py
```

Запуск из корня урока:

```bash
python outputs/seasonality_profiler.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --calendar ../data/tiny/calendar.csv \
  --campaign-calendar ../data/tiny/campaign_calendar.csv \
  --release-calendar ../data/tiny/release_calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --spec ../data/tiny/seasonality_profile_spec.json \
  --output-dir outputs
```

CLI пишет четыре файла:

- `outputs/trend_summary.csv` - направление и скорость изменения по complete history;
- `outputs/seasonality_profile.csv` - day-of-week и month profile;
- `outputs/calendar_effect_inventory.csv` - holiday, campaign и release context;
- `outputs/seasonality_report.json` - checks, warnings и summary.

В tiny-профиле отчет валиден, но содержит три предупреждения:

```json
{
  "valid": true,
  "warnings": [
    "partial_rows_excluded_from_profiles",
    "future_calendar_effect_has_no_training_examples",
    "monthly_profile_has_single_cycle"
  ]
}
```

Эти warnings не блокируют урок: они фиксируют ограничения интерпретации.

В pandas тот же профиль можно получить через join с календарем и `groupby`.

```python
import pandas as pd

series = pd.read_csv("../02-resampling/outputs/daily_resampled.csv")
calendar = pd.read_csv("../data/tiny/calendar.csv")

frame = series.merge(calendar, left_on="observed_date", right_on="date", validate="many_to_one")
training = frame[frame["include_in_training"]]
profile = (
    training
    .groupby(["segment_id", "day_of_week"], as_index=False)
    .agg(observations=("value", "size"), mean_value=("value", "mean"))
)
```

Но pandas не проверит сам, что campaign calendar и daily calendar согласованы, а
`known_before_date` не позже forecast origin. Поэтому production-артефакт держит рядом
spec, checks и inventory.

## Сломайте это

Проверьте пять поломок.

1. Удалите `2026-04-14` из `calendar.csv`. Check `calendar_covers_history_and_horizon`
   должен стать blocking error.
2. Скопируйте строку `all/2026-03-02` в `daily_resampled.csv`. Check
   `source_segment_date_unique` должен найти дубликат.
3. Поставьте `campaign_active=false` на `2026-03-20` в `calendar.csv`, но оставьте
   `campaign_calendar.csv` без изменений. Check `calendar_flags_cover_declared_events`
   должен заблокировать профиль.
4. Поставьте `known_before_date=2026-03-19` для `campaign_active=true` на `2026-03-20`.
   Check `calendar_effects_known_before_origin` должен упасть, потому что forecast origin
   был `2026-03-18T09:00:00+03:00`.
5. Удалите колонку `value` из source series. Check `source_columns_present` должен
   остановить расчет до построения красивых, но бессмысленных таблиц.

Строгий режим:

```bash
python outputs/seasonality_profiler.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --calendar ../data/tiny/calendar.csv \
  --campaign-calendar ../data/tiny/campaign_calendar.csv \
  --release-calendar ../data/tiny/release_calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --spec ../data/tiny/seasonality_profile_spec.json \
  --fail-on-warning
```

Он вернет non-zero exit code, потому что tiny history честно предупреждает о partial row,
будущей кампании без historical examples и недостаточной месячной истории.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/04-trend-and-seasonality/tests -v
```

Они проверяют:

- воспроизводимость `seasonality_profile_spec.json`;
- ручной Monday mean, Saturday mean и seasonal index;
- trend summary только на complete history;
- future campaign status без исторических примеров;
- segment-specific release lift для Android;
- блокировку missing calendar date, duplicate source grain, рассинхрона campaign flags,
  неизвестного до origin calendar effect, scenario/spec mismatch и missing source column;
- CLI output и режим `--fail-on-warning`.

Критерий интерпретации: если `summary.blocking_errors` не пустой, profile нельзя
использовать дальше. Если есть warnings, profile можно использовать только вместе с
ограничениями из отчета.

## Поставьте результат

Итоговый артефакт:

```text
outputs/seasonality_profiler.py
```

`code/main.py` пересобирает committed outputs:

```bash
uv run --locked python phases/14-time-series/04-trend-and-seasonality/code/main.py
```

Следующий урок использует этот профиль как вход для temporal leakage audit: какие
календарные признаки действительно known future features, какие исторические эффекты
только diagnostics, а какие rows нельзя использовать из-за partial или insufficient
history.

Ограничение: этот урок не строит forecast и не выбирает модель. Он описывает структуру
ряда и календарный контекст, чтобы baseline и decomposition в следующих уроках не
начинались с неверной истории.

## Упражнения

1. Добавьте `payday_week` в `calendar_effect_columns` и объясните, какие будущие даты
   можно считать известными на forecast origin.
2. Добавьте отдельный `weekend` profile и сравните его с day-of-week profile.
3. Сделайте campaign calendar с historical campaign period и проверьте, как изменится
   `calendar_effect_inventory.csv`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Trend | Любой рост последней точки. | Устойчивое направление уровня ряда на выбранном историческом окне. |
| Seasonality | Любое повторяющееся среднее в groupby. | Повторяемая структура с заранее заданным календарным периодом. |
| Seasonal index | Прогноз следующей даты. | Отклонение сезонной группы от среднего уровня сегмента. |
| Calendar effect | Доказанный эффект события. | Известный календарный контекст, который требует review и не доказывает причинность. |
| Known future feature | Любая будущая колонка календаря. | Будущий признак, значение которого известно до forecast origin. |
| Monthly profile | Среднее за один месяц. | Сезонный месячный паттерн только при наличии повторных месячных циклов. |
| Effect inventory | Список причин. | Машинная таблица календарных событий, их дат, known-before статуса и ограничений. |

## Дополнительное чтение

- [pandas: Time series / date functionality](https://pandas.pydata.org/docs/user_guide/timeseries.html) — повторите работу с датами, offsets и calendar joins; это база для корректного профиля по business date.
- [pandas: Group by: split-apply-combine](https://pandas.pydata.org/docs/user_guide/groupby.html) — разберите именованные агрегации и `as_index=False`, чтобы строить сезонные профили без потери grain.
- [Forecasting: Principles and Practice, Time plots](https://otexts.com/fpp3/graphics.html) — посмотрите, как отличать trend, seasonality и calendar variation визуально, не делая причинных выводов.
- [Forecasting: Principles and Practice, Time series decomposition](https://otexts.com/fpp3/decomposition.html) — подготовка к следующему блоку: decomposition полезна как диагностика структуры, но не является forecast сама по себе.
