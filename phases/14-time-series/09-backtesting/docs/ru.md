# Rolling backtesting

> Forecast-модель можно сравнивать только на заранее объявленных rolling origins,
> а не по одному удачному последнему окну.

- **Тип:** Build
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/08-ets-and-arima`
- **Время:** ~90 минут
- **Результат:** вы проектируете expanding и rolling-origin backtests с
  несколькими cutoffs, fixed horizon, retraining policy и gap/embargo, затем
  публикуете `split_manifest.csv`, `backtest_forecasts.csv`,
  `backtest_errors.csv` и `backtest_report.json`.

## Цели обучения

- Зафиксировать `backtesting_spec.json` до запуска моделей: origins, train
  windows, gap/embargo, horizon, models и retraining policy.
- Различать expanding window и rolling window и понимать, какую бизнес-ошибку
  ловит каждый вариант.
- Строить forecast table на grain
  `split_id x segment_id x model_id x forecast_date`.
- Считать raw forecast errors без преждевременного leaderboard.
- Проверять, что backtest не использует random split, future actuals,
  переменный horizon или переиспользованный final fit.

## Проблема

В прошлом уроке ETS и ARIMA уже построили forecast rows на будущий 28-day horizon.
Очень хочется посмотреть на последнюю известную неделю и сказать:

```text
"ETS почти попадает в тренд, значит это новая production model".
```

Такой вывод опасен. Одно окно может быть легким для ETS, тяжелым для ARIMA или
случайно удобным для baseline. Если выбрать модель по одному cutoff, мы выбираем
не устойчивое качество, а удачную дату проверки.

Правильный handoff к метрикам выглядит так:

```text
declared split plan -> refit per origin -> forecast rows -> raw errors ->
metric aggregation in the next lesson
```

Этот урок еще не объявляет победителя. Он выпускает проверяемое сырье, на котором
следующий урок сможет честно считать MAE/RMSE/MASE по horizon и segment.

## Концепция

Rolling-origin backtesting имитирует несколько исторических моментов, в которых
мы как будто стояли в прошлом и не знали будущие actuals.

В tiny profile backtest устроен так:

| Split | Window | Train window | Embargo | Forecast horizon |
|---|---|---|---|---|
| `bt-expanding-2026-02-24` | expanding | `2026-02-02..2026-02-22` | `2026-02-23` | `2026-02-24..2026-02-26` |
| `bt-expanding-2026-03-03` | expanding | `2026-02-02..2026-03-01` | `2026-03-02` | `2026-03-03..2026-03-05` |
| `bt-rolling-2026-03-10` | rolling | `2026-02-16..2026-03-08` | `2026-03-09` | `2026-03-10..2026-03-12` |
| `bt-rolling-2026-03-14` | rolling | `2026-02-20..2026-03-12` | `2026-03-13` | `2026-03-14..2026-03-16` |

Expanding window отвечает на вопрос: "Что если мы всегда копим всю доступную
историю?". Rolling window отвечает на другой вопрос: "Что если старые недели уже
устарели и модель должна смотреть только на свежий режим?". Обе схемы полезны,
поэтому artifact требует, чтобы в backtest были оба типа окон.

Gap/embargo нужен для той же защиты, что и в предыдущих уроках: данные между
`training_end` и `first_forecast_date` существуют в календаре, но недоступны
модели на момент прогноза.

```text
training_end = 2026-02-22
embargo_date = 2026-02-23
first_forecast_date = 2026-02-24

raw_step=1 -> 2026-02-23  # skip
raw_step=2 -> 2026-02-24  # emit horizon_step=1
```

## Соберите это

Начните с manifest, а не с модели. Minimal split object должен быть достаточно
явным, чтобы его можно было проверить без чтения кода:

```python
split = {
    "split_id": "bt-expanding-2026-02-24",
    "window_type": "expanding",
    "forecast_origin": "2026-02-24T09:00:00+03:00",
    "training_start": "2026-02-02",
    "training_end": "2026-02-22",
    "embargo_dates": ["2026-02-23"],
    "first_forecast_date": "2026-02-24",
    "horizon_end": "2026-02-26",
}
```

Первые проверки механические:

```python
horizon_dates = ["2026-02-24", "2026-02-25", "2026-02-26"]
assert len(horizon_dates) == 3
assert split["window_type"] in {"expanding", "rolling"}
assert split["training_end"] < split["first_forecast_date"]
assert split["embargo_dates"] == ["2026-02-23"]
```

Дальше задайте output grain. Для каждого split, segment и model должно быть ровно
по одной строке на forecast date:

```text
split_id
metric_id
segment_id
model_id
forecast_date
horizon_step
forecast_value
training_start
training_end
raw_step
```

В tiny profile:

```python
splits = 4
segments = ["all", "android"]
models = ["seasonal_naive_7", "ets_additive_trend_seasonal_7", "arima_1_1_0"]
horizon_days = 3
assert splits * len(segments) * len(models) * horizon_days == 72
```

Raw errors считаются строка-в-строку:

```python
actual_value = 944
forecast_value = 881
error = actual_value - forecast_value
absolute_error = abs(error)
squared_error = error * error
```

Важно: raw errors еще не являются metric policy. Они только подготавливают
материал для следующего урока, где появятся aggregation, horizon weighting и
решение о том, какую модель можно сравнивать с baseline.

## Используйте это

Готовый artifact:

```text
outputs/rolling_backtester.py
```

Запуск из корня урока:

```bash
python outputs/rolling_backtester.py \
  --series ../data/tiny/backtest_observations.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --model-spec ../data/tiny/statsmodels_model_spec.json \
  --model-report ../08-ets-and-arima/outputs/model_report.json \
  --spec ../data/tiny/backtesting_spec.json \
  --output-dir outputs
```

Или из корня репозитория:

```bash
uv run --locked python phases/14-time-series/09-backtesting/code/main.py
```

CLI пишет четыре файла:

- `outputs/split_manifest.csv` - origins, train windows, embargo, horizon и
  retraining policy;
- `outputs/backtest_forecasts.csv` - baseline/ETS/ARIMA forecasts на каждом
  `split_id x segment_id x model_id x forecast_date`;
- `outputs/backtest_errors.csv` - actual, error, absolute error и squared error;
- `outputs/backtest_report.json` - quality gates, warnings и shape summary.

Tiny profile валиден, но оставляет две warnings:

```json
{
  "valid": true,
  "warnings": [
    "small_origin_count_blocks_model_selection_claim",
    "backtest_horizon_shorter_than_final_forecast_horizon"
  ],
  "split_rows": 4,
  "forecast_rows": 72,
  "error_rows": 72
}
```

Эти warnings не ломают artifact. Они запрещают слишком сильный вывод:

- 4 origins достаточно для учебного механизма, но мало для production model
  selection.
- 3-day backtest horizon короче final 28-day forecast horizon, поэтому нельзя
  утверждать, что качество проверено на всех рабочих шагах.

Первый baseline row показывает gap явно:

| Field | Value |
|---|---:|
| `split_id` | `bt-expanding-2026-02-24` |
| `segment_id` | `all` |
| `model_id` | `seasonal_naive_7` |
| `forecast_date` | `2026-02-24` |
| `forecast_value` | `881` |
| `actual_value` | `944` |
| `error` | `63` |
| `raw_step` | `2` |
| `anchor_dates` | `2026-02-17` |

ETS и ARIMA также refit-ятся на каждом origin. Например для того же split и
segment:

| Model | Forecast for `2026-02-24` |
|---|---:|
| `ets_additive_trend_seasonal_7` | `944.000002` |
| `arima_1_1_0` | `886.913429` |

Это все еще не winner table. Это проверяемые forecasts и errors.

## Сломайте это

Проверьте типичные поломки backtest-дизайна.

1. Поставьте `split_plan[0].window_type = "random"`. Report должен упасть с
   `no_random_splits`.
2. Сделайте `horizon_end = "2026-02-25"` при `backtest_horizon_days = 3`.
   Check `forecast_horizon_is_fixed` должен заблокировать report.
3. Удалите `embargo_dates` у первого split. Check
   `embargo_gap_is_respected` должен найти разрыв.
4. Удалите actual row для `all` на `2026-02-24`. Check
   `actuals_available_for_every_origin_horizon` должен остановить выпуск
   forecasts.
5. Продублируйте любую строку в `backtest_observations.csv`. Check
   `source_segment_date_unique` должен сработать.
6. Сделайте upstream `model_report.json` invalid. Check
   `scenario_model_and_backtest_spec_align` должен остановить backtest.
7. Поставьте `retraining_policy.refit_each_origin = false` и
   `reuse_final_forecast_fit = true`. Check `models_refit_each_origin` должен
   заблокировать отчет.

Строгий режим:

```bash
python outputs/rolling_backtester.py \
  --series ../data/tiny/backtest_observations.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --model-spec ../data/tiny/statsmodels_model_spec.json \
  --model-report ../08-ets-and-arima/outputs/model_report.json \
  --spec ../data/tiny/backtesting_spec.json \
  --fail-on-warning
```

На tiny profile он завершится non-zero, потому что warnings нельзя прятать в
автоматическом пайплайне.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/09-backtesting/tests -v
```

Они проверяют:

- воспроизводимость `backtesting_spec.json` и `backtest_observations.csv`;
- 4 split rows: два expanding и два rolling origins;
- фиксированный 3-day horizon и один embargo day перед каждым horizon;
- 72 forecast rows и 72 raw error rows;
- locked values для seasonal naive, ETS и ARIMA;
- raw error arithmetic: `error`, `absolute_error`, `squared_error`;
- блокировки random split, broken horizon, broken embargo, missing actual,
  duplicate grain, invalid upstream report и reuse final fit;
- CLI output files и `--fail-on-warning`.

## Поставьте результат

Переиспользуемый artifact:

```text
outputs/rolling_backtester.py
```

Минимальный production handoff:

```bash
python outputs/rolling_backtester.py \
  --series path/to/backtest_observations.csv \
  --scenario path/to/forecast_scenario.json \
  --model-spec path/to/statsmodels_model_spec.json \
  --model-report path/to/model_report.json \
  --spec path/to/backtesting_spec.json \
  --output-dir path/to/backtest_package
```

Перед передачей результата проверьте:

- `backtest_report.json.valid = true`;
- warnings явно обсуждены, а не проигнорированы;
- `split_manifest.csv` совпадает с согласованным protocol;
- `backtest_forecasts.csv` имеет уникальный grain;
- `backtest_errors.csv` содержит actuals для каждого published forecast.

## Упражнения

1. Добавьте пятый origin на `2026-03-16` и объясните, почему horizon actuals
   должны существовать до запуска backtest.
2. Сделайте rolling window длиной 28 дней вместо 21 и сравните ETS/ARIMA
   forecasts на последнем origin без объявления winner.
3. Добавьте третий segment в `backtest_observations.csv` и расширьте
   `target_segments`. Проверьте, как изменится expected row count.
4. Добавьте поле `origin_label` в `split_manifest.csv`, не меняя forecast grain.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Rolling-origin backtesting | То же самое, что random cross-validation | Последовательная проверка на нескольких исторических forecast origins |
| Expanding window | Всегда лучше rolling window | Train window растет от фиксированного старта; это одна из допустимых политик, а не универсальный winner |
| Rolling window | Просто меньше данных | Train window фиксированной длины, который проверяет устойчивость к устареванию старой истории |
| Embargo/gap | Можно удалить из manifest, если строка не прогнозируется | Запрещенный промежуток между training_end и first forecast date, который должен быть виден в contract |
| Raw error | Готовый leaderboard | Строковый `actual - forecast`, который еще нужно агрегировать по metric policy |
| Refit each origin | Лишняя медленная роскошь | Условие честной имитации прошлого: на каждом origin модель обучается только на доступной тогда истории |

## Дополнительное чтение

- [Forecasting: Principles and Practice, Time series cross-validation](https://otexts.com/fpp3/tscv.html) - базовая идея rolling forecasting origin и почему обычная cross-validation не подходит временным рядам.
- [Forecasting: Principles and Practice, Evaluating point forecast accuracy](https://otexts.com/fpp3/accuracy.html) - следующий шаг после этого урока: как агрегировать forecast errors и чем отличаются accuracy metrics.
- [scikit-learn `TimeSeriesSplit`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) - официальный API-пример split iterator с `gap`, `test_size` и растущими train sets; полезно сравнить с нашим явным manifest.
- [statsmodels Forecasting example](https://www.statsmodels.org/stable/examples/notebooks/generated/statespace_forecasting.html) - официальный пример pseudo-out-of-sample forecasting и продления результатов модели во времени.
