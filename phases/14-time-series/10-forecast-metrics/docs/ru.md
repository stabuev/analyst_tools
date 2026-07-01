# Метрики прогноза

> Leaderboard полезен только тогда, когда metric policy заранее говорит, какую
> ошибку считать дорогой, а какую - просто диагностической.

- **Тип:** Case
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/09-backtesting`
- **Время:** ~75 минут
- **Результат:** вы считаете MAE, RMSE, MAPE/sMAPE, WAPE и MASE по rolling-origin
  errors, публикуете overall, segment-level и horizon-level slices, проверяете
  пригодность метрик и выпускаете leaderboard без production overclaim.

## Цели обучения

- Отличать raw forecast errors от metric policy.
- Считать MAE, RMSE, MAPE, sMAPE, WAPE и MASE из одной backtest error table.
- Объяснять, почему MAE/RMSE scale-dependent, а MASE удобнее для сравнения сегментов.
- Блокировать или помечать MAPE/sMAPE при нулевых и маленьких denominator.
- Строить leaderboard по primary metric и не объявлять production winner при
  warning-ах backtest-дизайна.

## Проблема

После `14/09` у нас есть `backtest_errors.csv`: каждая строка знает model, segment,
origin, horizon step, forecast, actual и raw error. Этого еще недостаточно для решения.
Можно взять первую строку, где ETS почти идеально попала в actual, и сказать:

```text
"ETS выиграла, выкатываем".
```

Это снова слишком сильный вывод. Разные метрики отвечают на разные вопросы:

- MAE легко объяснить в единицах продукта, но она зависит от масштаба segment.
- RMSE сильнее наказывает крупные промахи, но менее прозрачен бизнесу.
- MAPE кажется удобной процентной метрикой, но ломается на нулях и маленьких actuals.
- WAPE нормирует absolute error общим объемом и часто понятен в бизнес-отчетах.
- MASE сравнивает ошибку модели с in-sample seasonal-naive scale и подходит для разных
  масштабов.

Задача урока - не найти красивое число, а сделать metric handoff:

```text
raw errors -> suitability audit -> metric slices -> weighted leaderboard ->
limited decision status
```

## Концепция

Forecast error:

```text
error = actual - forecast
absolute_error = abs(error)
squared_error = error ** 2
```

Scale-dependent metrics:

```text
MAE  = mean(abs(error))
RMSE = sqrt(mean(error ** 2))
```

Percentage metrics:

```text
MAPE  = mean(abs(error) / abs(actual)) * 100
sMAPE = mean(2 * abs(error) / (abs(actual) + abs(forecast))) * 100
WAPE  = sum(abs(error)) / sum(abs(actual)) * 100
```

MAPE и sMAPE не становятся primary metric только потому, что они в процентах. Если
`actual = 0`, MAPE не определена. Если `actual` и `forecast` оба около нуля, sMAPE
тоже нестабильна. Поэтому spec держит их в роли `diagnostic_only`.

Scaled metric:

```text
MASE = mean(abs(error) / seasonal_naive_training_mae)
```

Для weekly seasonal daily series denominator считается внутри каждого split и segment:

```text
seasonal_naive_training_mae =
  mean(abs(y_t - y_{t-7})) over training window
```

В tiny profile:

| Split | Segment | MASE denominator |
|---|---|---:|
| `bt-expanding-2026-02-24` | `all` | `63` |
| `bt-expanding-2026-02-24` | `android` | `28` |
| `bt-rolling-2026-03-14` | `all` | `66.428571` |

Эта таблица важна: без denominator MASE выглядит как магическое число.

## Соберите это

Начните с одной backtest row:

```python
actual = 944
forecast = 881
error = actual - forecast
absolute_error = abs(error)
squared_error = error * error

assert error == 63
assert absolute_error == 63
assert squared_error == 3969
```

Для MAE/RMSE достаточно raw errors:

```python
absolute_errors = [63, 63, 63]
squared_errors = [3969, 3969, 3969]

mae = sum(absolute_errors) / len(absolute_errors)
rmse = (sum(squared_errors) / len(squared_errors)) ** 0.5
```

Для MAPE добавьте safety gate:

```python
if any(abs(actual) < 1 for actual in actual_values):
    mape_status = "blocked"
else:
    mape = mean(abs(error) / abs(actual) * 100)
```

Для MASE нужен training window:

```python
seasonal_period = 7
denominator = mean(
    abs(y[day] - y[day - seasonal_period])
    for day in training_dates
    if day - seasonal_period in training_dates
)
mase = mean(abs(error) / denominator for error in forecast_errors)
```

После этого задайте slices. В уроке их три:

```text
overall: model_id
segment: model_id x segment_id
horizon: model_id x horizon_step
```

Для трех моделей, двух сегментов и трех horizon steps получается:

```python
metric_rows = 3 * (1 + 2 + 3)
assert metric_rows == 18
```

## Используйте это

Готовый artifact:

```text
outputs/forecast_metric_evaluator.py
```

Запуск из корня урока:

```bash
python outputs/forecast_metric_evaluator.py \
  --errors ../09-backtesting/outputs/backtest_errors.csv \
  --split-manifest ../09-backtesting/outputs/split_manifest.csv \
  --series ../data/tiny/backtest_observations.csv \
  --backtest-report ../09-backtesting/outputs/backtest_report.json \
  --spec ../data/tiny/forecast_metric_spec.json \
  --output-dir outputs
```

Или из корня репозитория:

```bash
uv run --locked python phases/14-time-series/10-forecast-metrics/code/main.py
```

CLI пишет пять файлов:

- `outputs/forecast_metrics.csv` - MAE/RMSE/MAPE/sMAPE/WAPE/MASE по overall,
  segment и horizon slices;
- `outputs/metric_suitability_audit.csv` - роль каждой метрики, zero/scale risks и
  decision eligibility;
- `outputs/mase_denominators.csv` - training seasonal-naive denominator по split и
  segment;
- `outputs/metric_leaderboard.csv` - weighted-MASE leaderboard;
- `outputs/metric_report.json` - quality gates, warnings и output summary.

Tiny profile валиден, но warning остается:

```json
{
  "valid": true,
  "warnings": ["backtest_warnings_limit_model_selection"],
  "metric_rows": 18,
  "leaderboard_rows": 3,
  "primary_metric": "weighted_mase",
  "top_model_id": "ets_additive_trend_seasonal_7"
}
```

Overall metrics:

| Model | MAE | RMSE | WAPE | MASE |
|---|---:|---:|---:|---:|
| `seasonal_naive_7` | `46.5` | `50.264301` | `6.782133` | `1.009831` |
| `ets_additive_trend_seasonal_7` | `3.166694` | `6.377098` | `0.46187` | `0.0489` |
| `arima_1_1_0` | `41.765465` | `47.942236` | `6.09159` | `0.897672` |

Weighted-MASE leaderboard:

| Rank | Model | Weighted MASE | Relative improvement | Status |
|---:|---|---:|---:|---|
| 1 | `ets_additive_trend_seasonal_7` | `0.068459` | `0.93247` | `diagnostic_leaderboard_not_production_selection` |
| 2 | `arima_1_1_0` | `0.914565` | `0.097852` | `diagnostic_leaderboard_not_production_selection` |
| 3 | `seasonal_naive_7` | `1.013763` | `0` | `primary_baseline` |

Почему status не `selected_for_production`? Потому что backtest из tiny profile сам
предупредил: origins меньше production threshold, а 3-day backtest horizon короче
финального 28-day forecast horizon.

## Сломайте это

Проверьте failure modes.

1. Сделайте `primary_metric = "mape"`. Check
   `percentage_metrics_not_primary_decision_metric` должен заблокировать report.
2. Удалите weight для `android`. Check
   `segment_weights_cover_targets_and_sum_to_one` должен упасть.
3. Удалите одну строку из `backtest_errors.csv`. Check
   `backtest_error_rows_match_report` должен остановить metrics.
4. Продублируйте любую строку error table. Check `backtest_error_grain_unique`
   должен найти broken grain.
5. Поставьте `actual_value = 0` в одной error row. Package остается valid, но
   `percentage_denominators_are_safe_or_blocked` становится warning, а MAPE status
   становится `blocked`.
6. Сделайте history series постоянным для `android`. MASE denominator станет нулевым,
   и check `mase_denominator_positive` заблокирует scaled metrics.
7. Сделайте upstream `backtest_report.json.valid = false`. Check
   `backtest_report_is_valid` должен остановить evaluator.

Строгий режим:

```bash
python outputs/forecast_metric_evaluator.py \
  --errors ../09-backtesting/outputs/backtest_errors.csv \
  --split-manifest ../09-backtesting/outputs/split_manifest.csv \
  --series ../data/tiny/backtest_observations.csv \
  --backtest-report ../09-backtesting/outputs/backtest_report.json \
  --spec ../data/tiny/forecast_metric_spec.json \
  --fail-on-warning
```

На tiny profile он завершится non-zero, потому что warning upstream backtest не
позволяет тихо использовать leaderboard как production selection.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/10-forecast-metrics/tests -v
```

Они проверяют:

- воспроизводимость `forecast_metric_spec.json`;
- MASE denominators по split и segment;
- locked overall, segment и horizon metrics;
- suitability audit для MAPE/sMAPE и MASE;
- weighted-MASE leaderboard values и blocked model selection status;
- zero-actual handling без подмены primary MASE;
- блокировки percentage primary metric, bad segment weights, missing/duplicate error row,
  invalid upstream report и нулевого MASE denominator;
- CLI output files и `--fail-on-warning`.

## Поставьте результат

Переиспользуемый artifact:

```text
outputs/forecast_metric_evaluator.py
```

Минимальный handoff:

```bash
python outputs/forecast_metric_evaluator.py \
  --errors path/to/backtest_errors.csv \
  --split-manifest path/to/split_manifest.csv \
  --series path/to/backtest_observations.csv \
  --backtest-report path/to/backtest_report.json \
  --spec path/to/forecast_metric_spec.json \
  --output-dir path/to/metric_package
```

Перед передачей результата проверьте:

- `metric_report.json.valid = true`;
- `metric_suitability_audit.csv` не разрешает MAPE/sMAPE как primary decision metric;
- `mase_denominators.csv` имеет положительный denominator для каждого split и segment;
- `forecast_metrics.csv` содержит overall, segment и horizon slices;
- `metric_leaderboard.csv` не объявляет production selection при backtest warning-ах.

## Упражнения

1. Измените segment weights на `all=0.5`, `android=0.5` и объясните, почему
   weighted MASE меняется, а segment-level MASE - нет.
2. Добавьте horizon weights, где `horizon_step=3` в два раза важнее первого шага.
   Какие строки output должны измениться?
3. Создайте synthetic zero-actual row для support-like metric и убедитесь, что MAPE
   заблокирована, а WAPE/MASE остаются интерпретируемыми при положительном масштабе.
4. Добавьте business-cost metric, где over-forecast и under-forecast имеют разную цену.
   Почему MAE/RMSE этого не выражают?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Forecast error | Ошибка модели в training residuals | Разница `actual - forecast` на out-of-sample horizon |
| MAE | Универсальный winner metric | Средняя absolute error в единицах target, не scale-free |
| RMSE | Просто MAE с корнем | Метрика, которая сильнее наказывает крупные промахи |
| MAPE | Удобная процентная метрика без условий | Делит на actual и ломается на нулях или маленьких значениях |
| WAPE | То же самое, что MAPE | Volume-normalized absolute error: `sum(abs(error)) / sum(abs(actual))` |
| MASE | Сложная версия MAE | Absolute error, нормированная in-sample naive или seasonal-naive scale |
| Leaderboard policy | Таблица rank сама выбирает модель | Правила, которые связывают metric, baseline threshold, segments и ограничения backtest |

## Дополнительное чтение

- [Forecasting: Principles and Practice, Evaluating point forecast accuracy](https://otexts.com/fpp3/accuracy.html) - основной источник по forecast errors, MAE/RMSE, MAPE/sMAPE failure modes и seasonal MASE denominator.
- [Forecasting: Principles and Practice, Time series cross-validation](https://otexts.com/fpp3/tscv.html) - как связать metric evaluation с rolling-origin backtests, а не с fit на train.
- [scikit-learn Regression metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#regression-metrics) - официальный обзор regression metrics API; полезно сравнить generic ML metrics с time-series-specific MASE policy.
- [scikit-learn `mean_absolute_error`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.mean_absolute_error.html) - пример production API для MAE и sample weights, который помогает думать о segment/horizon weighting.
