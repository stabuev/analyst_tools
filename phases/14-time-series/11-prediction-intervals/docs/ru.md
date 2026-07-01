# Интервалы прогноза

> Точечный прогноз без uncertainty statement выглядит увереннее, чем имеет право.

- **Тип:** Build
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/10-forecast-metrics`
- **Время:** ~75 минут
- **Результат:** вы строите residual, bootstrap и model-based prediction intervals,
  проверяете empirical coverage на rolling-origin backtests и выпускаете forecast table,
  где каждый point forecast сопровожден границами и ограничением интерпретации.

## Цели обучения

- Отличать prediction interval для будущего наблюдения от confidence interval для
  среднего или параметра.
- Калибровать residual interval по out-of-sample backtest errors.
- Строить bootstrap interval из signed residual distribution.
- Сравнивать model-based normal interval с empirical coverage.
- Блокировать поставку точечного прогноза без uncertainty statement.

## Проблема

После `14/10` у нас есть leaderboard: ETS выглядит лучшей моделью по weighted MASE. Но
для решения о capacity этого все еще мало. Если сказать:

```text
2026-03-20: active_subscriptions = 1160
```

то заказчик почти неизбежно прочитает число как обещание. Для операционного решения
важнее другой handoff:

```text
point forecast = 1160
90% prediction interval = [1144, 1176]
status = diagnostic_intervals_not_production_sla
```

Интервал не делает forecast магически правильным. Он показывает, насколько ошибалась
такая связка model + segment + horizon на исторических cutoffs, и честно помечает, где
истории слишком мало.

## Концепция

Prediction interval отвечает на вопрос:

```text
where can the future actual observation land?
```

Confidence interval отвечает на другой вопрос:

```text
where can the unknown mean or parameter be?
```

В forecasting workflow это разные объекты. Для capacity planning нас интересует будущий
actual, поэтому урок строит prediction intervals.

У нас уже есть rolling-origin error table:

```text
error = actual - forecast
absolute_error = abs(error)
```

Три метода урока:

| Method | Идея | Роль |
|---|---|---|
| `residual_quantile` | Взять консервативный квантиль absolute backtest errors и построить симметричный interval вокруг point forecast | primary |
| `residual_bootstrap` | Взять нижний и верхний квантиль signed residuals и сдвинуть point forecast | comparison |
| `model_based_normal` | Построить `forecast +/- z * residual_stddev` | diagnostic_only |

Почему model-based method diagnostic-only? Если модель систематически занижает forecast,
маленький residual standard deviation не спасает coverage. Tiny profile специально
показывает это на seasonal baseline: normal interval имеет zero или tiny width и
эмпирически не покрывает actuals.

Coverage:

```text
empirical_coverage = covered_count / n_observations
covered = lower_bound <= actual <= upper_bound
```

Заявленное `90%` имеет смысл только после проверки на backtest rows. Если backtest
короткий, coverage остается диагностикой, а не production SLA.

## Соберите это

Начните с одной backtest-группы:

```python
errors = [63, 63, 75, 63]
absolute_errors = [abs(value) for value in errors]
coverage_target = 0.90

residual_quantile = max(absolute_errors)
lower_residual = -residual_quantile
upper_residual = residual_quantile

point_forecast = 1124
lower = point_forecast + lower_residual
upper = point_forecast + upper_residual

assert lower == 1049
assert upper == 1199
```

Для bootstrap-interval используйте signed residuals:

```python
signed_residuals = sorted(errors)
bootstrap_lower = signed_residuals[0]
bootstrap_upper = signed_residuals[-1]

lower = point_forecast + bootstrap_lower
upper = point_forecast + bootstrap_upper
```

Такой interval может не содержать point forecast. Это нормально: signed residuals
сохраняют bias. Если модель всегда занижала actual на похожем horizon, bootstrap interval
сдвинется вверх.

Для model-based diagnostic:

```python
from statistics import NormalDist, stdev

alpha = 0.10
z = NormalDist().inv_cdf(1 - alpha / 2)
margin = z * stdev(errors)
```

Этот расчет полезен как contrast: он похож на привычную формулу, но coverage все равно
надо проверять на backtest.

Калибровочный grain урока:

```text
model_id x segment_id x horizon_step
```

В tiny profile:

```python
calibration_groups = 3 * 2 * 3
methods = 3
assert calibration_groups * methods == 54
```

## Используйте это

Готовый artifact:

```text
outputs/prediction_interval_calibrator.py
```

Запуск из корня урока:

```bash
python outputs/prediction_interval_calibrator.py \
  --errors ../09-backtesting/outputs/backtest_errors.csv \
  --final-baseline-forecasts ../06-forecast-baselines/outputs/baseline_forecasts.csv \
  --final-candidate-forecasts ../08-ets-and-arima/outputs/candidate_forecasts.csv \
  --backtest-report ../09-backtesting/outputs/backtest_report.json \
  --metric-report ../10-forecast-metrics/outputs/metric_report.json \
  --spec ../data/tiny/prediction_interval_spec.json \
  --output-dir outputs
```

Или из корня репозитория:

```bash
uv run --locked python phases/14-time-series/11-prediction-intervals/code/main.py
```

CLI пишет пять файлов:

- `outputs/interval_calibration_audit.csv` - параметры residual, bootstrap и
  model-based calibration по model/segment/horizon;
- `outputs/interval_backtest_predictions.csv` - интервалы на historical backtest rows
  и флаг `covered`;
- `outputs/interval_coverage.csv` - empirical coverage по overall, segment и horizon
  slices;
- `outputs/interval_forecasts.csv` - final forecast table с point/lower/upper bounds и
  uncertainty statement;
- `outputs/interval_report.json` - quality gates, warnings и output summary.

Tiny profile валиден, но предупреждает об ограничениях:

```json
{
  "valid": true,
  "warnings": [
    "small_origin_count_blocks_interval_sla_claim",
    "interval_horizon_shorter_than_final_forecast",
    "upstream_warnings_limit_interval_claim",
    "diagnostic_model_based_undercoverage_is_warned"
  ],
  "interval_forecast_rows": 504,
  "coverage_rows": 54,
  "primary_interval_method": "residual_quantile",
  "primary_interval_min_coverage": "1"
}
```

Почему `valid=true`, но warning-и остаются:

- backtest содержит только 4 origins, а production coverage claim требует больше;
- backtest horizon равен 3 дням, а final forecast horizon равен 28 дням;
- upstream metric report уже предупредил, что tiny leaderboard не является production
  model selection;
- model-based normal interval на части срезов undercovers и остается diagnostic-only.

Пример final interval для ETS:

| Date | Horizon | Method | Point | Lower | Upper | Status |
|---|---:|---|---:|---:|---:|---|
| `2026-03-20` | 3 | `residual_quantile` | `1160.000044` | `1143.999739` | `1176.000349` | `exact` |
| `2026-03-21` | 4 | `residual_quantile` | `1123.000063` | `1106.999758` | `1139.000368` | `extrapolated_from_step_3` |

`horizon_step=4` уже не имеет собственного backtest calibration step в tiny profile.
Artifact не молчит: он пишет `extrapolated_from_step_3`.

## Сломайте это

Проверьте failure modes.

1. Сделайте `prediction_interval_not_confidence_interval = false`. Report должен
   заблокироваться: confidence interval нельзя подменять prediction interval.
2. Уберите метод `model_based_normal` из spec. Check `interval_methods_declared`
   должен упасть, потому что lesson contract требует все три метода.
3. Установите `absolute_error_quantile = 0.25` для primary residual method. Coverage
   станет ниже target, и `primary_interval_coverage_meets_target` заблокирует package.
4. Продублируйте строку `backtest_errors.csv`. Check `backtest_error_grain_unique`
   должен найти broken historical forecast grain.
5. Удалите последнюю строку `candidate_forecasts.csv`. Check
   `final_forecast_table_has_full_horizon` должен остановить final intervals.
6. Сделайте `metric_report.valid = false`. Interval package не должен скрывать
   upstream metric failure.
7. Поставьте `minimum_backtest_rows_per_group = 5`. Tiny profile имеет только 4 rows
   на model/segment/horizon, поэтому calibration должна стать invalid.

Строгий режим:

```bash
python outputs/prediction_interval_calibrator.py \
  --errors ../09-backtesting/outputs/backtest_errors.csv \
  --final-baseline-forecasts ../06-forecast-baselines/outputs/baseline_forecasts.csv \
  --final-candidate-forecasts ../08-ets-and-arima/outputs/candidate_forecasts.csv \
  --backtest-report ../09-backtesting/outputs/backtest_report.json \
  --metric-report ../10-forecast-metrics/outputs/metric_report.json \
  --spec ../data/tiny/prediction_interval_spec.json \
  --output-dir outputs \
  --fail-on-warning
```

На tiny profile он завершится non-zero, потому что warnings запрещают тихую production
SLA-интерпретацию.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/11-prediction-intervals/tests -v
```

Они проверяют:

- воспроизводимость `prediction_interval_spec.json`;
- locked residual, bootstrap и model-based calibration values;
- empirical coverage slices для primary и diagnostic methods;
- final interval table, uncertainty statement и horizon extrapolation status;
- covered flags на backtest intervals;
- блокировки low primary quantile, missing method, confidence-interval подмены,
  invalid metric report, duplicate backtest grain, incomplete/duplicate final forecasts
  и insufficient calibration rows;
- CLI output files и `--fail-on-warning`.

## Поставьте результат

Переиспользуемый artifact:

```text
outputs/prediction_interval_calibrator.py
```

Минимальный handoff:

```bash
python outputs/prediction_interval_calibrator.py \
  --errors path/to/backtest_errors.csv \
  --final-baseline-forecasts path/to/baseline_forecasts.csv \
  --final-candidate-forecasts path/to/candidate_forecasts.csv \
  --backtest-report path/to/backtest_report.json \
  --metric-report path/to/metric_report.json \
  --spec path/to/prediction_interval_spec.json \
  --output-dir path/to/interval_package
```

Перед передачей результата проверьте:

- `interval_report.json.valid = true`;
- `interval_forecasts.csv` содержит point/lower/upper bounds для каждого final forecast;
- `uncertainty_statement` не пустой;
- `interval_coverage.csv` показывает empirical coverage primary method;
- warnings не скрыты в UI или отчете;
- интервалы за пределами calibrated horizon явно помечены как extrapolated.

## Упражнения

1. Измените `coverage_target` на `0.8`. Какие строки coverage report изменятся, а какие
   calibration bounds останутся теми же?
2. Сделайте bootstrap interval only for `all` segment и объясните, почему отсутствие
   `android` интервалов ломает decision handoff.
3. Добавьте asymmetric business statement: under-forecast support load дороже
   over-forecast. Почему symmetric residual interval не выражает это сам по себе?
4. Попробуйте pool residuals по horizon вместо `model x segment x horizon`. Что вы
   выигрываете в sample size и что теряете в интерпретации?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Prediction interval | То же самое, что confidence interval | Диапазон для будущего actual observation |
| Confidence interval | Интервал прогноза будущего значения | Диапазон неопределенности среднего, параметра или estimate |
| Empirical coverage | Свойство, гарантированное названием метода | Доля backtest actuals, которые попали в построенные интервалы |
| Residual quantile interval | Красивый графический band | Консервативный interval из out-of-sample absolute errors |
| Residual bootstrap interval | Всегда симметричный interval вокруг point forecast | Percentile interval из signed residuals, который может отражать bias |
| Model-based interval | Истина модели | Formula-based interval, который нужно проверять на coverage |
| Uncertainty statement | Текстовая приписка | Contract, который не дает передать point forecast без границ и limitations |

## Дополнительное чтение

- [Forecasting: Principles and Practice, Prediction intervals](https://otexts.com/fpp3/prediction-intervals.html) - основной источник по prediction intervals, residual bootstrap и ограничениям нормальных предположений.
- [Forecasting: Principles and Practice, Time series cross-validation](https://otexts.com/fpp3/tscv.html) - как проверять forecast behavior на rolling origins, а не на одном последнем окне.
- [statsmodels: Forecasting in statsmodels](https://www.statsmodels.org/stable/examples/notebooks/generated/statespace_forecasting.html) - официальный пример forecast objects, `get_forecast` и interval-style outputs в statsmodels.
- [SciPy `bootstrap`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) - официальный API для bootstrap confidence intervals; полезен как contrast, почему в этом уроке bootstrap применяется к forecast residuals и проверяется через coverage.
