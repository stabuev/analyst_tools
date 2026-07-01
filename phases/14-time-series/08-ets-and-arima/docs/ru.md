# ETS и ARIMA

> Библиотечная модель становится forecast artifact только после явного spec,
> diagnostics и честного сравнения с baseline.

- **Тип:** Build
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/07-decomposition`
- **Время:** ~90 минут
- **Результат:** вы обучаете заранее объявленные ETS и ARIMA-кандидаты в
  `statsmodels`, сохраняете model diagnostics и выпускаете comparison table к
  `seasonal_naive_7` без auto-modeling и без заявления о победителе до backtesting.

## Цели обучения

- Зафиксировать `statsmodels_model_spec.json` до fit: ETS components, ARIMA
  `order`, `seasonal_order`, initialization, cutoff и horizon.
- Обучить ETS и ARIMA на complete training rows, не используя embargo/future rows.
- Сохранить convergence status, library warnings и residual diagnostics по каждой
  паре `segment_id x model_id`.
- Понять разницу между shape comparison к baseline и forecast accuracy comparison.
- Выпустить `statsmodels-forecast-runner` как handoff к rolling-origin backtesting.

## Проблема

После декомпозиции видны trend и weekly seasonality. В этот момент легко сделать
слишком быстрый вывод:

```text
"ETS красиво продолжает тренд, значит можно заменить seasonal naive".
```

Это неверный forecast workflow. Сложная модель может идеально подстроиться под короткую
историю, но проиграть простому baseline на будущем окне. ARIMA может сойтись, но дать
плоский forecast. ETS может продолжить pattern, но не знать про будущую campaign. Поэтому
урок не выбирает winner. Он строит воспроизводимый model run:

```text
declared model spec -> cutoff-safe fit -> diagnostics -> horizon forecast ->
library-vs-baseline shape comparison -> backtesting handoff
```

## Концепция

ETS и ARIMA отвечают на разные вопросы.

| Family | Что моделирует | Что надо объявить заранее |
|---|---|---|
| `ETS` | error, trend и seasonal components через exponential smoothing | `trend`, `seasonal`, `seasonal_periods`, `initialization_method` |
| `ARIMA` | авторегрессию, differencing и moving-average динамику | `order=(p,d,q)`, `seasonal_order=(P,D,Q,m)`, `trend`, stationarity/invertibility policy |

В этом уроке tiny spec объявляет два кандидата:

```json
[
  {
    "model_id": "ets_additive_trend_seasonal_7",
    "family": "ETS",
    "statsmodels_class": "ExponentialSmoothing",
    "trend": "add",
    "seasonal": "add",
    "seasonal_periods": 7,
    "initialization_method": "estimated"
  },
  {
    "model_id": "arima_1_1_0",
    "family": "ARIMA",
    "statsmodels_class": "ARIMA",
    "order": [1, 1, 0],
    "seasonal_order": [0, 0, 0, 0],
    "trend": "n"
  }
]
```

Главное правило: параметры не подбираются автоматически после просмотра forecast. Если
нужен search, он должен стать отдельным reproducible experiment с backtesting protocol.
Здесь же кандидаты фиксируются как заранее заданные alternatives.

## Соберите это

Перед библиотекой соберите contract механически. У нас есть:

```python
training_end = "2026-03-16"
embargo_dates = ["2026-03-17"]
first_forecast_date = "2026-03-18"
horizon_days = 28
```

`statsmodels` forecast начинает шаги сразу после последней training date. Значит первый
raw step соответствует `2026-03-17`, но эта дата запрещена cutoff contract. Runner
запрашивает 29 raw steps до `2026-04-14`, а публикует только 28 horizon rows:

```python
raw_step_1 = "2026-03-17"  # skip: embargo
raw_step_2 = "2026-03-18"  # emit horizon_step=1
raw_step_29 = "2026-04-14" # emit horizon_step=28
```

Такой mapping важнее красивого plot: без него модель может тихо использовать или
публиковать не тот horizon.

Теперь задайте output grain:

```text
forecast_id
model_run_id
metric_id
segment_id
model_id
forecast_date
horizon_step
forecast_value
```

В tiny profile:

```python
segments = ["all", "android"]
candidate_models = ["ets_additive_trend_seasonal_7", "arima_1_1_0"]
horizon_days = 28
assert len(segments) * len(candidate_models) * horizon_days == 112
```

Diagnostics grain другой:

```text
segment_id x model_id
```

Для каждой пары сохраняются `training_points`, `training_cycles`,
`convergence_status`, `statsmodels_warnings`, `residual_mean`, `residual_std`,
`lag1_autocorrelation`, `aic`, `bic` и исходные model parameters.

## Используйте это

Готовый artifact:

```text
outputs/statsmodels_forecast_runner.py
```

Запуск из корня урока:

```bash
python outputs/statsmodels_forecast_runner.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --cutoff-contract ../05-temporal-leakage/outputs/cutoff_contract.json \
  --baseline-report ../06-forecast-baselines/outputs/baseline_report.json \
  --baseline-forecasts ../06-forecast-baselines/outputs/baseline_forecasts.csv \
  --decomposition-report ../07-decomposition/outputs/decomposition_report.json \
  --spec ../data/tiny/statsmodels_model_spec.json \
  --output-dir outputs
```

CLI пишет четыре файла:

- `outputs/candidate_forecasts.csv` - ETS/ARIMA forecast rows на 28-day horizon;
- `outputs/model_diagnostics.csv` - convergence, warnings, residual diagnostics и
  explicit model parameters;
- `outputs/library_vs_baseline.csv` - строковое сравнение каждого candidate forecast с
  primary baseline `seasonal_naive_7`;
- `outputs/model_report.json` - quality gates, warnings, output summary и selection policy.

Tiny profile валиден, но предупреждения остаются видимыми:

```json
{
  "valid": true,
  "warnings": [
    "short_history_blocks_model_selection_claim",
    "known_future_calendar_effects_not_modeled_by_candidates",
    "embargo_gap_skipped_before_forecast"
  ],
  "forecast_rows": 112,
  "diagnostics_rows": 4,
  "comparison_rows": 112
}
```

Первые horizon values показывают разницу behavior:

| Segment | Model | `2026-03-18` forecast | Что видно |
|---|---:|---:|---|
| `all` | `ets_additive_trend_seasonal_7` | `1141.999814` | продолжает trend + weekly pattern |
| `all` | `arima_1_1_0` | `1129.062333` | быстро выходит на почти плоский уровень |
| `android` | `ets_additive_trend_seasonal_7` | `381.999999` | продолжает синтетический weekly pattern |
| `android` | `arima_1_1_0` | `377.597805` | сглаживает последний скачок |

Это не leaderboard. Это controlled library run.

## Сломайте это

Проверьте восемь поломок.

1. Поставьте `selection_policy.no_auto_model_search = false`. Check
   `no_auto_model_search` должен заблокировать report.
2. Добавьте candidate model с `"auto_model_search": true`. Auto-search также должен
   блокироваться.
3. Удалите ARIMA candidate. Check `ets_and_arima_families_present` должен упасть.
4. Измените `order` на `[1, 1]`. Check `orders_and_initialization_are_explicit`
   должен найти неявный ARIMA spec.
5. Пометьте `2026-03-17` как `include_in_training=true`. Checks
   `training_rows_match_cutoff` и `model_uses_training_window_only` должны упасть.
6. Удалите одну строку `seasonal_naive_7` из `baseline_forecasts.csv`. Check
   `baseline_forecasts_have_primary_shape` должен заблокировать comparison.
7. Сделайте upstream `baseline_report.json` invalid. Check
   `baseline_and_decomposition_reports_are_valid` должен остановить model run.
8. Поставьте `minimum_training_points = 30` для ETS. Check
   `enough_history_for_declared_candidates` должен сработать.

Строгий режим:

```bash
python outputs/statsmodels_forecast_runner.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --calendar ../data/tiny/calendar.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --cutoff-contract ../05-temporal-leakage/outputs/cutoff_contract.json \
  --baseline-report ../06-forecast-baselines/outputs/baseline_report.json \
  --baseline-forecasts ../06-forecast-baselines/outputs/baseline_forecasts.csv \
  --decomposition-report ../07-decomposition/outputs/decomposition_report.json \
  --spec ../data/tiny/statsmodels_model_spec.json \
  --fail-on-warning
```

На tiny profile он завершится non-zero: warnings нельзя silently ignore.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/08-ets-and-arima/tests -v
```

Они проверяют:

- воспроизводимость `statsmodels_model_spec.json`;
- expected `statsmodels` forecast values в locked environment;
- пропуск `2026-03-17` и сохранение 28-day horizon;
- явные ETS/ARIMA parameters в diagnostics;
- convergence status, statsmodels warning count и residual diagnostics;
- shape-only comparison к `seasonal_naive_7`;
- блокировки auto-search, missing family, broken ARIMA order, post-cutoff training row,
  duplicate source grain, missing baseline forecast, invalid upstream report и
  overdemanding history policy;
- CLI output files и `--fail-on-warning`.

## Поставьте результат

Переиспользуемый artifact:

```text
outputs/statsmodels_forecast_runner.py
```

Минимальный handoff для `14/09`:

```text
candidate_forecasts.csv
model_diagnostics.csv
library_vs_baseline.csv
model_report.json
```

Передавайте дальше такой вывод:

```text
ETS and ARIMA candidates are predeclared and fit on cutoff-safe history. Forecast rows
match the primary baseline grain and horizon, but short history, known future calendar
effects, and embargo-gap handling remain visible warnings. Model choice is deferred to
rolling-origin backtesting and forecast metrics.
```

## Упражнения

1. Добавьте третий candidate `arima_0_1_1` и тест, что `candidate_forecasts.csv`
   вырос до 168 строк.
2. Поставьте `uses_exogenous_calendar_features = true` и объясните, почему warning про
   calendar effects исчезает, но сама модель еще не получила regressors.
3. Добавьте в diagnostics поле `forecast_last_value` и проверьте expected value для
   `android/arima_1_1_0` на `2026-04-14`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| `ETS` | "Всегда лучше seasonal naive, если есть сезонность" | Семейство exponential smoothing моделей; качество проверяется out-of-sample |
| `ARIMA order` | "Можно подобрать после просмотра графика" | Предзаданный `(p,d,q)` contract, который влияет на воспроизводимость fit |
| `Convergence warning` | "Шум библиотеки, можно удалить" | Сигнал нестабильности fit, который должен попасть в diagnostics |
| `Shape comparison` | "Это уже accuracy comparison" | Проверка одинакового grain, horizon и baseline alignment без actuals |
| `Auto-modeling` | "Бесплатный способ получить лучшую модель" | Поиск модели, который требует отдельного reproducible backtesting protocol |

## Дополнительное чтение

- [statsmodels ExponentialSmoothing](https://www.statsmodels.org/stable/generated/statsmodels.tsa.holtwinters.ExponentialSmoothing.html) — параметры `trend`, `seasonal`, `seasonal_periods` и `initialization_method`, которые должны быть явной частью ETS spec.
- [statsmodels ARIMA](https://www.statsmodels.org/stable/generated/statsmodels.tsa.arima.model.ARIMA.html) — API для `order`, `seasonal_order`, `trend`, stationarity и invertibility settings.
- [statsmodels forecasting examples](https://www.statsmodels.org/stable/examples/notebooks/generated/statespace_forecasting.html) — как библиотека различает in-sample prediction, out-of-sample forecast и forecast horizon mechanics.
- [Forecasting: Principles and Practice, Exponential smoothing](https://otexts.com/fpp3/expsmooth.html) — концептуальная база ETS, error/trend/seasonal components и ограничения smoothing.
- [Forecasting: Principles and Practice, ARIMA models](https://otexts.com/fpp3/arima.html) — что означают AR, differencing и MA components и почему выбор порядка должен быть проверяемым.
