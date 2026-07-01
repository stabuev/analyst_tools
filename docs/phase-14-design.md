# Проект фазы 14: Временные ряды

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую forecasting-задачу, модель данных, роли инструментов и контракт итогового
`time-series forecast package`.

## Результат фазы

Студент превращает историческую продуктовую метрику в проверяемый прогноз для решения.
Он сначала фиксирует календарный grain, частоту, timezone, доступность данных,
forecast origin и horizon, затем строит прозрачные naive и seasonal-naive baselines,
сравнивает с ETS/ARIMA-кандидатами через rolling-origin backtesting, проверяет метрики и
интервалы и только после этого формулирует, можно ли использовать forecast для решения.

Фаза учит держать раздельно пять слоев:

1. **Временной контракт:** что является наблюдением, с какой частотой ряд обновляется,
   какие даты полные, а какие еще могут измениться.
2. **Forecast setup:** в какой момент времени делается прогноз, на какой horizon и какие
   признаки действительно известны на этот момент.
3. **Baseline:** какой простой forecast обязан победить любой более сложный метод.
4. **Backtesting:** как много исторических cutoffs проверяют стабильность качества.
5. **Decision statement:** какие point forecast, intervals, anomaly flags и limitations
   можно передать дальше.

Фаза состоит из четырех последовательных блоков:

1. `14/01`-`14/03`: временной индекс, resampling, rolling/expanding windows и запрет
   неявной работы с нерегулярными или неполными периодами.
2. `14/04`-`14/07`: trend, seasonality, temporal leakage, seasonal baseline и
   decomposition как диагностика структуры ряда.
3. `14/08`-`14/11`: ETS/ARIMA, rolling-origin backtesting, forecast metrics и prediction
   intervals.
4. `14/12`: anomaly policy и итоговый `time-series forecast package`.

Суммарная длительность - 945 минут, или 15,75 часа.

## Границы содержания

- **Не повтор продуктовой аналитики.** Фаза переиспользует metric specs, guardrails,
  calendar/release context и аномалии продуктовых метрик из фазы 08. Здесь главный
  вопрос - как прогнозировать уже определенную метрику с честной временной валидацией.
- **Не повтор прикладной статистики.** Bias/variance, bootstrap, intervals и regression
  diagnostics уже систематизированы в фазе 09. Здесь они применяются к forecast errors,
  coverage и residual diagnostics по временным cutoffs.
- **Не причинный анализ и не causal impact.** Forecast может показать, что наблюдение
  необычно относительно истории, но не доказывает эффект релиза, кампании или
  вмешательства. Counterfactual causal claims, DiD и sensitivity остаются фазе 13.
- **Не ML-фаза.** Лаги, rolling features и time-based splits показываются как
  forecasting hygiene, но scikit-learn pipelines, feature engineering для supervised ML,
  model selection и leakage в табличном ML остаются фазе 15.
- **Не каталог всех forecasting-моделей.** Фаза покрывает naive, seasonal naive, drift,
  moving average, decomposition diagnostics, ETS и ARIMA/SARIMAX. Prophet, sktime,
  neural forecasting, hierarchical reconciliation, intermittent demand, dynamic
  regression и probabilistic forecasting libraries остаются факультативными
  продолжениями.
- **Не автоматический model search.** Auto-ARIMA, перебор сотен параметров и выбор модели
  по одному leaderboard считаются failure mode. Студент должен объяснить baseline,
  assumptions, horizon, backtest plan и business cost ошибки.
- **Не monitoring platform.** `14/12` выпускает anomaly policy и воспроизводимый package,
  но production alerting, on-call, SLA, feature store и scheduled delivery остаются
  фазе 17 или за пределами обязательного курса.
- **Не финансовое планирование.** Ряд может быть revenue/support/subscription metric, но
  discounting, CAC, inventory optimization, capacity optimization и P&L-модель не входят
  в обязательную фазу.

## Роли инструментов

Новые зависимости на этапе проектирования не добавляются. В locked environment уже есть
pandas, NumPy, SciPy, statsmodels, Matplotlib/Seaborn/Altair/Plotly, DuckDB,
Pandera/Pydantic и pytest. Prophet, sktime или специализированные forecasting libraries
не становятся обязательными зависимостями без отдельной задачи, где они меняют решение
лучше уже доступного стека.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| pandas | `DatetimeIndex`, timezone, frequency inference, `resample`, offsets, rolling/expanding windows, lagged features и calendar joins | Новый обзор pandas API и distributed time-series processing |
| NumPy | Ручные naive/seasonal forecasts, deterministic simulations, residual bootstrap и tiny expected values | Полный stochastic processes курс |
| SciPy | Residual summaries, distribution checks, robust thresholds и interval calibration helpers | Байесовские time-series models и полный каталог statistical tests |
| statsmodels | STL, ETS/ExponentialSmoothing, ARIMA/SARIMAX, forecasting results и residual diagnostics | Автоматический model discovery, все state-space extensions и econometric panel time series |
| DuckDB | Независимые проверки grain, duplicates, calendar coverage, late revisions и reconciliation агрегатов | Warehouse orchestration и production scheduler |
| Pandera / Pydantic | Контракты forecast scenario, time index, backtest plan, metric policy, interval policy и anomaly policy | Production governance platform |
| Matplotlib / Seaborn / Altair / Plotly | Forecast/backtest figures, seasonal profiles, residual plots, interval coverage и anomaly review | Новая gallery визуализаций и dashboard layout |
| pytest | Behavioral tests для calendar contract, leakage, baselines, backtesting, metrics, intervals и final package | Повтор основ pytest/CI |

Проверенные на 29 июня 2026 года официальные и первичные ориентиры:

- [pandas: Time series / date functionality](https://pandas.pydata.org/docs/user_guide/timeseries.html) -
  официальный пользовательский раздел по timestamps, date ranges, offsets,
  time zone handling, frequency conversion и resampling.
- [pandas: Windowing operations](https://pandas.pydata.org/docs/user_guide/window.html) -
  rolling, expanding и exponentially weighted windows; это базовый API для ручных
  feature и baseline calculations.
- [statsmodels: Time Series Analysis](https://www.statsmodels.org/stable/tsa.html) -
  официальный индекс tsa-модулей: ARIMA/SARIMAX, exponential smoothing, state space,
  decomposition, filters и diagnostics.
- [statsmodels: Forecasting in statsmodels](https://www.statsmodels.org/stable/examples/notebooks/generated/statespace_forecasting.html) -
  пример forecasting workflow, forecast objects, prediction intervals и evaluation
  через исторические origins.
- [statsmodels: STL decomposition](https://www.statsmodels.org/stable/examples/notebooks/generated/stl_decomposition.html) -
  пример decomposition на trend, seasonal и residual components.
- [statsmodels: Exponential smoothing](https://www.statsmodels.org/stable/examples/notebooks/generated/exponential_smoothing.html) -
  пример Simple/Holt/Holt-Winters exponential smoothing и forecast results.
- [Forecasting: Principles and Practice, Time series cross-validation](https://otexts.com/fpp3/tscv.html) -
  первичный учебный ориентир по rolling/expanding forecast origins и оценке out-of-sample
  forecast accuracy.
- [Forecasting: Principles and Practice, Forecast accuracy](https://otexts.com/fpp3/accuracy.html) -
  первичный ориентир по MAE, RMSE, MAPE, scaled errors и корректному сравнению forecast
  methods.
- [Hyndman and Koehler, Another look at measures of forecast accuracy](https://doi.org/10.1016/j.ijforecast.2006.03.001) -
  primary source по проблемам популярных accuracy measures и scaled errors.

При разработке конкретного урока API и версии необходимо сверять с фактически
зафиксированным `uv.lock`, а не только с online-документацией.

## Единая forecasting-задача и данные

Фаза использует вымышленный подписочный сервис с маркетплейсом дополнительных товаров.
Рабочий вопрос интеграционного проекта: «На ближайшие четыре недели нужно спрогнозировать
активные подписки, net revenue и нагрузку на поддержку, чтобы решить, выдержит ли команда
предстоящую кампанию и где нужен capacity или rollout guardrail».

Команда не может использовать простую линию тренда:

- продажи и support tickets имеют недельную сезонность и календарные праздники;
- часть событий приезжает поздно, а revenue может пересчитываться после refund;
- кампания и релизы создают известные будущие calendar features, но реальные outcomes
  после forecast origin неизвестны;
- Android-релиз меняет уровень support tickets и ломает stationarity;
- новые сегменты имеют мало истории, а aggregate forecast скрывает segment-level риск;
- нулевые или маленькие знаменатели делают percentage errors обманчивыми;
- anomaly может быть дефектом ingestion, календарным эффектом или реальным product signal.

Таблицы:

| Таблица | Grain | Ключ |
|---|---|---|
| `metric_observations` | одна метрика, сегмент и календарный день | `metric_id, segment_id, observed_date` |
| `calendar` | один календарный день с business attributes | `date` |
| `release_calendar` | один релиз или rollout event | `release_id` |
| `campaign_calendar` | одна маркетинговая кампания и период активности | `campaign_id` |
| `data_revisions` | одна ревизия значения метрики после первичной публикации | `metric_id, segment_id, observed_date, revision_number` |
| `forecast_scenarios` | один machine-readable forecast setup | `forecast_id` |

Ключевые поля `metric_observations`:

| Поле | Смысл |
|---|---|
| `metric_id` | `active_subscriptions`, `net_revenue_rub`, `support_tickets` или другой прогнозируемый ряд |
| `segment_id` | `all`, platform, region или план; aggregate и segment forecasts не смешиваются молча |
| `observed_date` | бизнес-дата наблюдения после timezone normalization |
| `published_at` | когда значение стало доступно аналитику |
| `value` | опубликованное значение метрики |
| `denominator` | база ratio metric, если применимо |
| `is_complete_period` | закрыт ли период для анализа |
| `revision_number` | версия опубликованного значения |
| `source_status` | `ok`, `late`, `backfilled`, `partial`, `quality_hold` |

Календарные поля:

```text
date
week_start
day_of_week
is_weekend
is_holiday
holiday_name
campaign_active
release_active
payday_week
support_capacity
known_before_date
```

Профили данных:

- `tiny`: несколько недель daily data с ручными expected values для resampling,
  seasonal naive, rolling windows, forecast errors, coverage и anomaly flags.
- `sample`: детерминированная локальная генерация нескольких лет daily/weekly rows для
  trend, seasonality, rolling backtests, model comparison и interval calibration.
- Дефектные fixtures: минимальные мутации valid baseline для одного failure mode.

Заложенные свойства и failure modes:

- нерегулярный индекс, пропущенные даты и дубликаты `(metric_id, segment_id, date)`;
- локальная дата и UTC timestamp дают разные daily buckets;
- daily ряд агрегируется в weekly с неверным `label`/`closed`;
- неполная последняя неделя включается в training как полноценная;
- late revisions меняют историю после forecast origin;
- centered rolling window и decomposition используют будущее;
- случайный train/test split завышает качество;
- forecast horizon смешивает `t+1` и `t+28`;
- baseline и candidate model сравниваются на разных cutoffs;
- один последний cutoff выбирает модель, которая нестабильна на истории;
- MAPE взрывается на нулевых или маленьких значениях;
- aggregate forecast выглядит хорошо, но Android/support segment систематически ошибается;
- ETS/ARIMA converges with warnings или дает остатки с явной автокорреляцией;
- intervals имеют заявленные 90%, но покрывают только 65% backtest observations;
- anomaly flag срабатывает на data-quality gap или holiday, а не на product signal;
- anomaly detection threshold подобран после просмотра test window.

## Контракт forecast scenario

Каждый урок работает через machine-readable forecast scenario:

```text
forecast_id
business_decision
target_metric
target_segments
time_column
timezone
frequency
aggregation_policy
complete_period_policy
revision_policy
forecast_origin
horizon
cutoff_policy
training_window
validation_window
gap_or_embargo
known_future_features
forbidden_future_columns
baseline_models
candidate_models
model_specs
backtest_origins
retraining_policy
metrics
metric_weights
interval_method
coverage_target
anomaly_policy
quality_gates
decision_rule
known_limitations
rerun_instructions
```

Scenario запрещает прогнозировать «ряд вообще». Если forecast origin, horizon,
frequency, data availability, baseline и backtest plan не зафиксированы до оценки, такой
forecast нельзя использовать для решения.

## Контракт отдельных методов

### Time index и resampling

- каждый ряд имеет единственный `time_column`, timezone и declared frequency;
- missing dates отличаются от настоящих нулей;
- last incomplete period не входит в training без явной policy;
- aggregation сохраняет смысл метрики: sums, means, ratios и counts не resample'ятся
  одной функцией;
- reconciliation сверяет event-level source и published series.

### Rolling и leakage

- rolling/expanding features используют только наблюдения строго до forecast origin;
- centered windows, global scaling, full-sample decomposition и backfilled revisions
  считаются leakage;
- known future features допустимы только если они действительно известны до origin;
- каждый feature имеет `available_at` и `lookback_window`.

### Baselines

- naive, seasonal naive и drift считаются вручную на `tiny`;
- seasonal period фиксируется из календарного контракта, а не подгоняется по test error;
- сложная модель должна улучшить baseline на заранее выбранной метрике и horizon;
- baseline failure не является разрешением пропустить data-quality audit.

### ETS / ARIMA

- model spec содержит order, seasonal_order, trend/seasonal components и initialization;
- warnings, failed convergence и residual autocorrelation попадают в diagnostics;
- library forecast сверяется с shape/horizon/cutoff contract;
- model не выбирается по in-sample fit или красивому графику.

### Backtesting и метрики

- rolling-origin backtest публикует все origins, train windows, horizon и predictions;
- aggregate score дополняется horizon-level, segment-level и raw error table;
- MAPE/sMAPE запрещаются или помечаются, если zeros/small denominators делают их
  misleading;
- MASE или seasonal-naive-relative score нужен для сравнения разных масштабов.

### Интервалы и аномалии

- prediction interval относится к будущему наблюдению, а не к mean estimate;
- coverage проверяется по historical backtests, а не заявляется из модели;
- anomaly flag требует quality gates: freshness, duplicate, late revision, missing date,
  holiday/campaign/release context;
- anomaly policy должна выпускать `data_quality`, `calendar_expected`,
  `model_misspecification`, `product_signal_candidate` или `inconclusive`, а не один
  универсальный alarm.

## Интеграционный мини-проект

`14/12` собирает поставку:

```text
time-series-forecast-package/
├── scenario/
│   ├── forecast-scenario.json
│   ├── calendar-contract.json
│   └── data-availability-policy.json
├── data/
│   ├── source-contract.json
│   ├── time-index-audit.json
│   ├── resampled-series.csv
│   ├── revision-audit.json
│   └── quality-gates.json
├── features/
│   ├── rolling-features.csv
│   ├── known-future-features.csv
│   └── leakage-audit.json
├── baselines/
│   ├── baseline-spec.json
│   ├── seasonal-naive-forecast.csv
│   └── baseline-diagnostics.json
├── models/
│   ├── decomposition-report.json
│   ├── ets-model-spec.json
│   ├── arima-model-spec.json
│   ├── model-diagnostics.json
│   └── candidate-forecasts.csv
├── backtesting/
│   ├── split-manifest.json
│   ├── backtest-forecasts.csv
│   ├── metric-leaderboard.csv
│   └── raw-errors.csv
├── uncertainty/
│   ├── prediction-intervals.csv
│   ├── coverage-report.json
│   └── interval-diagnostics.json
├── anomalies/
│   ├── anomaly-policy.json
│   ├── anomaly-flags.csv
│   └── anomaly-review.json
├── figures/
│   ├── observed-vs-forecast.png
│   ├── seasonal-profile.png
│   ├── backtest-errors.png
│   ├── interval-coverage.png
│   └── anomaly-review.png
├── report.md
├── decision.json
└── manifest.json
```

Пакет обязан:

- фиксировать forecast origin, horizon, frequency, target metric и target segments;
- публиковать time-index audit до resampling и modeling;
- отличать missing, zero, partial period и late revision;
- хранить правила aggregation для count, sum, mean и ratio metrics;
- строить rolling/expanding features без доступа к будущему;
- включать naive и seasonal-naive baseline;
- сравнивать ETS/ARIMA candidates с baseline на одних и тех же origins;
- использовать rolling-origin backtesting с несколькими cutoffs;
- показывать raw errors, horizon-level metrics и segment-level metrics;
- объяснять, почему выбранная forecast metric соответствует business cost;
- публиковать prediction intervals и empirical coverage;
- выпускать anomaly flags только после quality/calendar gates;
- ограничивать decision statement одним из статусов:
  `usable_with_limits`, `baseline_only`, `needs_more_history`, `data_quality_blocked`,
  `model_unstable`, `inconclusive`;
- связывать каждый статус с forecast id, cutoff ids, metrics, coverage и limitations;
- выпускать SHA-256 manifest всех переданных файлов и generation parameters.

## Проверяемость

- Tiny-profile содержит ручные expected values для daily/weekly resampling,
  timezone bucket, missing-date detection, rolling mean, expanding mean, seasonal naive,
  drift forecast, one-step forecast errors, MASE denominator и interval coverage.
- Time-index tests проверяют unique `(metric_id, segment_id, date)`, declared frequency,
  timezone normalization, complete-period policy и late revisions.
- Resampling tests ловят неверные `label`/`closed`, смешивание sums/ratios и включение
  неполной последней недели.
- Window tests блокируют centered rolling, full-sample scaling, future revisions и
  features без `available_at`.
- Baseline tests сверяют naive/seasonal/drift forecasts с ручными tiny tables и
  проверяют horizon alignment.
- Decomposition tests проверяют component shapes, reconstruction tolerance и residual
  diagnostics without future leakage.
- ETS/ARIMA tests проверяют model spec, warning propagation, forecast horizon, residual
  diagnostics и сравнение с baseline.
- Backtesting tests проверяют origins, rolling/expanding windows, gap/embargo,
  reproducibility и запрет random splits.
- Metrics tests проверяют MAE/RMSE/WAPE/MASE, zero-value handling, segment weights и
  стабильность leaderboard policy.
- Interval tests проверяют coverage by origin/horizon, monotonic interval bounds и
  distinction между confidence и prediction wording.
- Anomaly tests проверяют quality gates, holiday/campaign/release suppression,
  threshold precommitment и allowed anomaly statuses.
- Final package test проверяет структуру, manifest, checksums, decision-to-evidence
  links, отсутствие unsupported causal wording и consistency между scenario, data audit,
  backtests, metrics, intervals, anomalies и limitations.
