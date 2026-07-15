<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 14: Временные ряды

> Превращайте продуктовые метрики в проверяемые прогнозы с временной валидацией, интервалами и честным сезонным baseline.

- **Треки:** decision
- **Пререквизиты:** Фаза 08, Фаза 09
- **Время:** ~12-16 часов
- **Итоговый артефакт:** Time-series forecast package с backtesting, интервалами и anomaly policy

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Временной индекс, частота и календарный grain](01-time-index) | 75 мин | Задает временной индекс, timezone, frequency, observation window и календарный grain для продуктовой метрики, находя пропущенные даты, дубликаты, неполные периоды, late revisions и несовместимые timestamps до построения прогноза. | CLI-аудитор временного индекса и частоты с calendar coverage report | complete |
| 02 | [Resampling и агрегация](02-resampling) | 75 мин | Переводит event-level и daily extracts в регулярный daily/weekly ряд с явными правилами label/closed, complete-period policy, timezone normalization и reconciliation между исходными событиями и агрегированной метрикой. | Resampling pipeline с aggregation spec, reconciliation table и partial-period audit | complete |
| 03 | [Rolling и expanding windows](03-rolling) | 75 мин | Строит rolling и expanding summaries только из доступного на момент прогноза прошлого, фиксирует alignment, min_periods, lag policy и проверяет leakage от centered windows или будущих наблюдений. | Window feature builder с leakage checks и rolling-summary report | complete |
| 04 | [Тренд, сезонность и календарные эффекты](04-trend-and-seasonality) | 75 мин | Описывает тренд, weekly/monthly seasonality, holiday, campaign и release effects через сезонные профили и календарные срезы, отделяя устойчивую структуру ряда от единичных всплесков и дефектов данных. | Seasonality profile report с calendar effect inventory | complete |
| 05 | [Временная утечка](05-temporal-leakage) | 75 мин | Фиксирует forecast origin, horizon, data availability и revision policy, блокируя random splits, target leakage, future-known-only признаки, backfilled значения и вычисления, которые используют данные после cutoff. | Temporal leakage auditor с cutoff contract и forbidden-feature report | complete |
| 06 | [Наивные и сезонные baseline](06-forecast-baselines) | 75 мин | Строит naive, seasonal naive, drift и moving-average baselines для заданного horizon, сверяет ручные tiny-расчеты и фиксирует baseline policy, ниже которой сложная модель не считается улучшением. | Baseline forecaster с seasonal-naive policy и forecast trace | complete |
| 07 | [Декомпозиция ряда](07-decomposition) | 75 мин | Разлагает ряд на trend, seasonal и residual components, выбирает additive или multiplicative interpretation, проверяет остатки и показывает, почему decomposition является диагностикой, а не доказательством будущей точности. | STL decomposition report с component tables и residual diagnostics | complete |
| 08 | [ETS и ARIMA](08-ets-and-arima) | 90 мин | Обучает ETS и ARIMA/SARIMAX candidate models в statsmodels, фиксирует order/seasonal_order, initialization, convergence warnings, residual diagnostics и сравнивает model forecast с прозрачным baseline без auto-modeling магии. | Statsmodels forecast runner с model spec, diagnostics и library-vs-baseline comparison | complete |
| 09 | [Rolling backtesting](09-backtesting) | 90 мин | Проектирует expanding и rolling-origin backtests с несколькими cutoffs, fixed horizon, retraining policy и gap/embargo, публикуя split manifest, forecast table и raw error table без вывода победителя по одному последнему окну. | Rolling-origin backtester с split manifest, forecast table и raw error table | complete |
| 10 | [Метрики прогноза](10-forecast-metrics) | 75 мин | Считает MAE, RMSE, MAPE/sMAPE, WAPE и MASE с overall, horizon-level и segment-level разрезами, объясняя failure modes нулевых значений, разных масштабов, выбросов и несопоставимых business costs. | Forecast metric evaluator с metric slices, metric suitability audit, MASE denominators и leaderboard policy | complete |
| 11 | [Интервалы прогноза](11-prediction-intervals) | 75 мин | Строит residual, bootstrap и model-based prediction intervals, проверяет empirical coverage по backtests, различает confidence и prediction intervals и блокирует точечный forecast без uncertainty statement. | Prediction interval calibrator с residual/bootstrap/model-based intervals, coverage report, calibration audit и interval forecast table | complete |
| 12 | [Аномалии временных рядов и forecast package](12-time-series-anomalies) | 90 мин | Собирает интегрированный time-series forecast package: upstream quality gates, metric leaderboard, prediction intervals, anomaly policy, decision report и checksum manifest. | Time-series forecast packager с anomaly flags, quality gate summary, decision report и checksum manifest | complete |

## Как проходить фазу

1. Ответьте на входные вопросы до чтения reference implementation.
2. Для каждого урока выполните прозрачную практику в локальной папке `work/`.
3. Запустите пример и тесты либо заполните артефакт и проверьте его по рубрике.
4. Выполните хотя бы одно упражнение, которое меняет данные или правило.
5. После фазы пройдите перемешанную самопроверку:

```bash
uv run --locked python scripts/run_quiz.py --phase 14 --stage post --limit 8
```

Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. Критерий освоения — объяснить решение, воспроизвести расчет или рассуждение и диагностировать хотя бы одну поломку.

## Критерий завершения

Студент фиксирует частоту и forecast horizon, сравнивает модели с сезонным baseline, использует rolling-origin backtesting, показывает интервалы прогноза и отделяет прогнозную аномалию от дефекта данных или календарного эффекта.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
