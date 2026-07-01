# Наивные и сезонные baseline

> Сложная модель сначала должна победить честный простой forecast на том же cutoff и
> horizon.

- **Тип:** Build
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/05-temporal-leakage`
- **Время:** ~75 минут
- **Результат:** вы строите naive, seasonal naive, drift и moving-average baselines,
  выпускаете forecast trace и фиксируете baseline policy для будущего сравнения моделей.

## Цели обучения

- Построить четыре прозрачных baseline-прогноза без доступа к будущим наблюдениям.
- Зафиксировать seasonal period до оценки качества, а не подобрать его по test error.
- Проверить, что anchors baseline лежат внутри training window и не используют embargo
  date.
- Объяснить, почему known future campaign context остается warning, а не скрытым uplift.
- Выпустить `baseline-forecaster` как quality gate перед ETS/ARIMA и backtesting.

## Проблема

После `14/05` у нас есть cutoff contract:

```text
training_end = 2026-03-16
embargo_dates = 2026-03-17
first_forecast_date = 2026-03-18
horizon_end = 2026-04-14
```

Теперь можно построить первую прогнозную планку. Опасность в том, что команда часто
прыгает сразу к сложной модели:

```text
"Давайте ETS/ARIMA/ML - там график красивее".
```

Но без baseline непонятно, действительно ли модель умеет прогнозировать, или просто
выглядит сложнее. Для product decision baseline нужен как минимальный оппонент:

- если модель не лучше seasonal naive на том же horizon, ее нельзя продавать как
  улучшение;
- если baseline строится с temporal leakage, все последующие сравнения заражены;
- если baseline не публикует trace, невозможно понять, какие даты реально стали
  источником прогноза.

Урок строит `baseline-forecaster`: CLI, который читает `daily_resampled.csv`, calendar,
forecast scenario, cutoff contract и `baseline_forecast_spec.json`, а затем выпускает
таблицу forecasts, trace и report.

## Концепция

Baseline - это не "плохая модель". Это честная простая модель, которую сложно победить,
если в ряду есть устойчивый уровень, тренд или сезонность.

| Baseline | Формула | Что проверяет |
|---|---|---|
| Naive | Повторить последнее complete training value. | Может ли сложная модель победить "завтра как вчера". |
| Seasonal naive | Взять последнее training value с тем же weekday. | Есть ли недельная сезонность, которую уже достаточно повторить. |
| Drift | Продолжить линию от первого к последнему training value. | Достаточен ли линейный рост без сезонной структуры. |
| Moving average 7 | Повторить среднее последних 7 complete values. | Лучше ли сгладить шум, чем повторять одну дату. |

В этом уроке primary baseline - `seasonal_naive_7`. Будущие ETS/ARIMA-кандидаты должны
сравниваться именно с ним на тех же сегментах, cutoff, horizon и метрике качества.

Ключевое правило:

```text
baseline anchor date <= training_end
baseline anchor date not in embargo_dates
```

Для `2026-03-24` это особенно заметно. Это вторник. Ближайший предыдущий вторник -
`2026-03-17`, но это embargo date. Поэтому seasonal naive берет `2026-03-10`, последнее
полное training-наблюдение с тем же weekday.

## Соберите это

Сначала посчитайте baseline вручную для сегмента `all`.

Training history:

```python
values = {
    "2026-03-02": 998,
    "2026-03-03": 1007,
    "2026-03-04": 1016,
    "2026-03-05": 1025,
    "2026-03-06": 1034,
    "2026-03-07": 1003,
    "2026-03-08": 1012,
    "2026-03-09": 1073,
    "2026-03-10": 1082,
    "2026-03-11": 1091,
    "2026-03-12": 1100,
    "2026-03-13": 1109,
    "2026-03-14": 1066,
    "2026-03-15": 1075,
    "2026-03-16": 1124,
}
```

Naive для `2026-03-18`:

```python
naive = values["2026-03-16"]
assert naive == 1124
```

Seasonal naive для среды `2026-03-18`:

```python
seasonal_naive = values["2026-03-11"]
assert seasonal_naive == 1091
```

Drift продолжает first-to-last slope. От `2026-03-02` до `2026-03-16` прошло 14
календарных интервалов, значение выросло на `126`, значит slope равен `9` в день.
Первый forecast date находится через 2 дня после `training_end`.

```python
first = values["2026-03-02"]
last = values["2026-03-16"]
slope_per_day = (last - first) / 14
drift = last + 2 * slope_per_day

assert slope_per_day == 9
assert drift == 1142
```

Moving average 7:

```python
last_7 = [1082, 1091, 1100, 1109, 1066, 1075, 1124]
moving_average_7 = sum(last_7) / len(last_7)

assert round(moving_average_7, 6) == 1092.428571
```

Теперь проверьте embargo для seasonal naive. `2026-03-24` - вторник, но `2026-03-17`
запрещен.

```python
embargo_dates = {"2026-03-17"}
candidate_anchor = "2026-03-17"
fallback_anchor = "2026-03-10"

anchor = fallback_anchor if candidate_anchor in embargo_dates else candidate_anchor
assert anchor == "2026-03-10"
assert values[anchor] == 1082
```

Эта ручная логика и есть ядро production-артефакта: никаких подгонок, никаких будущих
дат, никаких "почти training" строк.

## Используйте это

Готовый артефакт:

```text
outputs/baseline_forecaster.py
```

Запуск из корня урока:

```bash
python outputs/baseline_forecaster.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --cutoff-contract ../05-temporal-leakage/outputs/cutoff_contract.json \
  --spec ../data/tiny/baseline_forecast_spec.json \
  --output-dir outputs
```

CLI пишет три файла:

- `outputs/baseline_forecasts.csv` - по одной строке на segment, model и forecast date;
- `outputs/baseline_trace.csv` - anchors, slope/window policy и primary baseline flag;
- `outputs/baseline_report.json` - checks, warnings, baseline policy и output summary.

В tiny-профиле отчет валиден:

```json
{
  "valid": true,
  "warnings": [
    "known_future_calendar_effects_not_modeled",
    "embargo_gap_skipped_before_forecast"
  ],
  "forecast_rows": 224,
  "primary_baseline_model": "seasonal_naive_7"
}
```

Два warning важны для интерпретации.

`known_future_calendar_effects_not_modeled` говорит, что в horizon есть известная
кампания `2026-03-20`-`2026-03-27`, но простые baseline не добавляют campaign uplift.
Это не ошибка: baseline остается нейтральной планкой качества.

`embargo_gap_skipped_before_forecast` говорит, что `2026-03-17` существует в source
series, но не входит в training. Forecast начинается с `2026-03-18`.

В pandas похожие baselines можно собрать через сортировку, `groupby`, `shift` и rolling
mean. Но pandas сам не проверит, что anchor не попал в embargo date и что seasonal period
не был выбран после просмотра ошибки. Поэтому production-CLI держит spec, cutoff contract
и trace рядом с forecast table.

## Сломайте это

Проверьте семь поломок.

1. Удалите `seasonal_naive_7` из `baseline_forecast_spec.json`. Check
   `baseline_models_declared` должен стать blocking error.
2. Поставьте `seasonal_period_days=14`. Check `seasonal_period_is_precommitted` должен
   заблокировать отчет.
3. Поставьте `primary_baseline_model=naive`. Check `primary_baseline_declared` должен
   упасть, потому что policy требует `seasonal_naive_7`.
4. Пометьте `2026-03-17` как `include_in_training=true` в `daily_resampled.csv`. Должны
   упасть `no_training_rows_after_cutoff` и `embargo_dates_are_not_training_rows`.
5. Скопируйте любую source row. Check `source_segment_date_unique` должен найти дубликат.
6. Удалите `2026-04-14` из `calendar.csv`. Check `calendar_covers_forecast_horizon`
   должен остановить прогноз.
7. Измените `training_end` в cutoff contract. Check
   `scenario_cutoff_and_baseline_spec_align` должен заблокировать сравнение.

Строгий режим:

```bash
python outputs/baseline_forecaster.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --cutoff-contract ../05-temporal-leakage/outputs/cutoff_contract.json \
  --spec ../data/tiny/baseline_forecast_spec.json \
  --fail-on-warning
```

Он вернет non-zero exit code на tiny-профиле, потому что warnings требуют review перед
сравнением с кандидатными моделями.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/06-forecast-baselines/tests -v
```

Они проверяют:

- воспроизводимость `baseline_forecast_spec.json`;
- ручные значения для naive, seasonal naive, drift и moving average;
- что seasonal naive для `2026-03-24` берет `2026-03-10`, а не embargo date;
- trace rows, primary baseline и drift slope;
- блокировку missing baseline model, wrong seasonal period, wrong primary baseline,
  training after cutoff, duplicate source grain, missing calendar horizon date,
  cutoff mismatch и over-demanding minimum history;
- CLI outputs и `--fail-on-warning`.

Минимальная ручная проверка:

```python
import csv
import json
from pathlib import Path

report = json.loads(Path("outputs/baseline_report.json").read_text())
assert report["valid"]
assert report["outputs"]["forecast_rows"] == 224
assert report["outputs"]["primary_baseline_model"] == "seasonal_naive_7"

with Path("outputs/baseline_forecasts.csv").open(newline="") as source:
    rows = list(csv.DictReader(source))

first_seasonal = next(
    row for row in rows
    if row["segment_id"] == "all"
    and row["model_id"] == "seasonal_naive_7"
    and row["forecast_date"] == "2026-03-18"
)
assert first_seasonal["forecast_value"] == "1091"
```

## Поставьте результат

Именованный артефакт урока:

```text
outputs/baseline_forecaster.py
```

Он нужен как вход для `14/08`-`14/10`: ETS/ARIMA, rolling backtesting и metric
leaderboard не должны сравниваться с пустотой. Перед любой сложной моделью приложите:

- `baseline_forecasts.csv` как таблицу прогнозов;
- `baseline_trace.csv` как доказательство anchor policy;
- `baseline_report.json` как machine-readable baseline policy.

Команда воспроизводимого запуска всего урока:

```bash
uv run --locked python phases/14-time-series/06-forecast-baselines/code/main.py
```

## Упражнения

1. Добавьте baseline `last_week_delta_repeat`: переносите не уровень, а дневное изменение
   с той же weekday, и объясните, почему это уже другой policy.
2. Измените primary baseline на `naive` и напишите короткое decision note, почему это
   ослабляет планку для ряда с недельной сезонностью.
3. Добавьте отдельный warning, если `campaign_active=true` покрывает больше четверти
   forecast horizon.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Baseline | Примитивная модель, которую можно пропустить. | Честная минимальная планка качества для будущих моделей. |
| Naive forecast | Всегда плохой прогноз. | Повтор последнего наблюдения, часто сильный benchmark для рядов уровня. |
| Seasonal naive | То же самое, что moving average. | Повтор последнего training-наблюдения с тем же сезонным ключом. |
| Drift | Линейная регрессия со множеством признаков. | Экстраполяция first-to-last slope training history. |
| Forecast trace | Лог для отладки. | Доказательство, какие training anchors и policy породили каждую baseline-строку. |
| Primary baseline | Любимая простая модель. | Заранее выбранная планка, которую кандидат должен улучшить на том же evaluation setup. |

## Дополнительное чтение

- [Forecasting: Principles and Practice, Simple forecasting methods](https://otexts.com/fpp3/simple-methods.html) - первичный учебный источник по average, naive, seasonal naive и drift baselines; полезен для формул и интуиции.
- [Forecasting: Principles and Practice, Evaluating point forecast accuracy](https://otexts.com/fpp3/accuracy.html) - раздел про training/test split, forecast errors и scaled errors; пригодится перед уроками `14/09`-`14/10`.
- [pandas.Series.shift](https://pandas.pydata.org/docs/reference/api/pandas.Series.shift.html) - официальный API для lag/shift операций; читайте как строительный блок baseline и leakage-safe features.
- [statsmodels: Exponential smoothing](https://www.statsmodels.org/stable/examples/notebooks/generated/exponential_smoothing.html) - официальный пример следующего уровня моделей, который в курсе будет сравниваться с baseline, а не заменять его без проверки.
