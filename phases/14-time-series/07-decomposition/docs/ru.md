# Декомпозиция ряда

> Декомпозиция объясняет историю, но не доказывает точность будущего прогноза.

- **Тип:** Build
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/06-forecast-baselines`
- **Время:** ~75 минут
- **Результат:** вы разлагаете ряд на trend, seasonal и residual components,
  проверяете reconstruction и residual diagnostics, а затем явно ограничиваете вывод:
  это diagnostic artifact, не forecast leaderboard.

## Цели обучения

- Разложить daily series на additive components: `observed = trend + seasonal + residual`.
- Выполнить STL только на complete training rows до cutoff.
- Проверить reconstruction tolerance, residual mean, residual spread и lag-1 autocorrelation.
- Объяснить выбор additive interpretation и условия, при которых нужен multiplicative review.
- Выпустить `stl-decomposition-reporter` как diagnostic gate перед ETS/ARIMA.

## Проблема

После `14/06` есть честный seasonal-naive baseline. Команда видит weekly pattern и рост
активных подписок, поэтому хочет сразу сказать:

```text
"Тренд растет, сезонность понятна, значит forecast будет надежным".
```

Это опасный скачок. Декомпозиция действительно помогает увидеть структуру истории, но:

- trend и seasonal components могут быть оценены с temporal leakage, если взять строки
  после forecast origin;
- красивый residual plot не является out-of-sample проверкой;
- короткая история может идеально реконструироваться и все равно плохо прогнозировать;
- decomposition не отменяет baseline policy: ETS/ARIMA-кандидаты все еще должны победить
  `seasonal_naive_7` на тех же cutoffs, segments и horizon.

Урок строит `stl-decomposition-reporter`: CLI, который читает cutoff-safe daily series,
forecast scenario, cutoff contract, baseline report и `decomposition_spec.json`, а затем
пишет component table, residual diagnostics и JSON-report.

## Концепция

В additive decomposition наблюдение представляется как сумма:

```text
observed_t = trend_t + seasonal_t + residual_t
```

Компоненты читаются так:

| Component | Что означает | Типичная ошибка |
|---|---|---|
| `trend` | медленное изменение уровня ряда | принять тренд за гарантию будущего роста |
| `seasonal` | повторяющийся календарный pattern | подобрать period после просмотра ошибки |
| `residual` | оставшаяся часть после trend и seasonal | считать маленькие residuals доказательством forecast accuracy |

Additive interpretation подходит, когда seasonal amplitude примерно стабильна в абсолютных
единицах. Multiplicative interpretation стоит рассматривать, если сезонность растет вместе
с уровнем ряда и относительная амплитуда важнее абсолютной. В этом уроке tiny-ряд
`active_subscriptions` положительный, но сезонный эффект выглядит как абсолютный weekday
offset, поэтому spec фиксирует `component_model = additive`.

STL извлекает trend и seasonality через LOESS smoothing. В production это удобно, но в
forecast workflow есть жесткое правило:

```text
component source date <= training_end
component source date not in embargo_dates
```

Если decomposition построена на полном ряду, включая будущий horizon, это такая же утечка,
как centered rolling window.

## Соберите это

Сначала проверьте механику на одной строке. Для сегмента `all` первая complete training
date равна `2026-03-02`, observed value равен `998`. STL в locked environment дает:

```python
observed = 998
trend = 984.060186
seasonal = 14.836851
residual = -0.897037

reconstructed = trend + seasonal + residual
assert round(reconstructed, 6) == observed
```

Для weekend-даты сезонная компонента отрицательная:

```python
observed = 1003
trend = 1034.856823
seasonal = -32.358018
residual = 0.501195

assert round(trend + seasonal + residual, 6) == observed
```

Теперь зафиксируйте grain component table:

```text
forecast_id
decomposition_id
metric_id
segment_id
method_id
component_model
observed_date
observed_value
trend
seasonal
residual
reconstructed
reconstruction_error
```

В tiny-профиле 2 сегмента и 15 complete training dates:

```python
segments = ["all", "android"]
training_dates = 15
assert len(segments) * training_dates == 30
```

Дата `2026-03-17` есть в source series, но это embargo/partial row. Она не должна попасть
в component table.

## Используйте это

Готовый артефакт:

```text
outputs/decomposition_reporter.py
```

Запуск из корня урока:

```bash
python outputs/decomposition_reporter.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --cutoff-contract ../05-temporal-leakage/outputs/cutoff_contract.json \
  --baseline-report ../06-forecast-baselines/outputs/baseline_report.json \
  --spec ../data/tiny/decomposition_spec.json \
  --output-dir outputs
```

CLI пишет три файла:

- `outputs/decomposition_components.csv` - trend, seasonal, residual и reconstruction
  по каждой training date и segment;
- `outputs/residual_diagnostics.csv` - residual mean/std/max, lag-1 autocorrelation,
  seasonal amplitude и diagnostic decision status;
- `outputs/decomposition_report.json` - checks, warnings, policy и output summary.

Tiny-профиль валиден, но не молчит про ограничение:

```json
{
  "valid": true,
  "warnings": ["short_history_blocks_accuracy_claim"],
  "component_rows": 30,
  "diagnostics_rows": 2,
  "method_id": "stl_additive"
}
```

Warning означает: чуть больше двух weekly cycles достаточно для учебной проверки
components и reconstruction, но недостаточно для уверенного заявления о будущей точности.
Такой отчет можно передать в `14/08` как diagnostic evidence, но не как model selection
result.

## Сломайте это

Проверьте семь поломок.

1. Поставьте `seasonal_period_days = 14` в `decomposition_spec.json`. Check
   `seasonal_period_is_precommitted` должен заблокировать отчет.
2. Поставьте `component_model = multiplicative`. Check `decomposition_method_supported`
   должен упасть, потому что урок реализует только additive STL.
3. Уберите policy
   `decomposition_is_diagnostic_not_forecast_evidence`. Check
   `interpretation_policy_blocks_forecast_claim` должен заблокировать handoff.
4. Сделайте `baseline_report.json` invalid. Check `baseline_report_is_valid` должен
   остановить decomposition handoff.
5. Пометьте `2026-03-17` как `include_in_training=true`. Check
   `decomposition_uses_training_window_only` должен найти leakage.
6. Удалите training date `2026-03-09` для сегмента `all`. Check
   `training_rows_match_cutoff` должен упасть.
7. Скопируйте любую source row. Check `source_segment_date_unique` должен найти
   дубликат.

Строгий режим:

```bash
python outputs/decomposition_reporter.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --cutoff-contract ../05-temporal-leakage/outputs/cutoff_contract.json \
  --baseline-report ../06-forecast-baselines/outputs/baseline_report.json \
  --spec ../data/tiny/decomposition_spec.json \
  --fail-on-warning
```

Он вернет non-zero exit code на tiny-профиле: warning надо рассмотреть перед переходом к
model candidates.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/07-decomposition/tests -v
```

Они проверяют:

- воспроизводимость `decomposition_spec.json`;
- STL component values для `all` и `android`;
- reconstruction invariant для каждой строки;
- отсутствие `2026-03-17` в component table;
- residual diagnostics и diagnostic-only status;
- блокировку invalid baseline report, wrong seasonal period, unsupported component model,
  forecast-claim policy, post-cutoff training row, duplicate grain, missing training date
  и overdemanding history policy;
- CLI output files и `--fail-on-warning`.

## Поставьте результат

Переиспользуемый artifact:

```text
outputs/decomposition_reporter.py
```

Минимальный handoff для следующего урока:

```text
decomposition_components.csv
residual_diagnostics.csv
decomposition_report.json
```

Передавайте дальше не фразу "модель будет точной", а ограниченный вывод:

```text
STL additive decomposition реконструирует complete training history, показывает weekly
seasonality и рост уровня, но short history блокирует accuracy claim. Candidate ETS/ARIMA
models still must beat seasonal_naive_7 on rolling-origin backtests.
```

## Упражнения

1. Добавьте в diagnostics поле `residual_median_abs` и тест на ожидаемое значение для
   сегмента `all`.
2. Измените threshold `minimum_cycles_for_decision` на `2` и объясните, почему warning
   исчезает, но это не заменяет rolling backtesting.
3. Добавьте дефектный fixture с полным рядом до `2026-03-17` и проверьте, что artifact
   не включает embargo date в components.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Decomposition | "Это уже forecast model." | Диагностическое разложение истории на components. |
| Trend component | "Если trend растет, будущее тоже вырастет." | Сглаженный уровень в observed training history. |
| Seasonal component | "Period можно выбрать по лучшей ошибке." | Повторяющийся pattern с заранее выбранным period. |
| Residual component | "Маленький residual доказывает точность." | Остаток после trend и seasonality внутри training history. |
| Additive interpretation | "Всегда подходит положительным рядам." | Подходит, когда сезонность стабильна в абсолютных единицах. |

## Дополнительное чтение

- [statsmodels: Seasonal-Trend decomposition using LOESS](https://www.statsmodels.org/stable/examples/notebooks/generated/stl_decomposition.html) — официальный пример STL, robust fitting и связи decomposition с forecasting.
- [statsmodels.tsa.seasonal.STL API](https://www.statsmodels.org/stable/generated/statsmodels.tsa.seasonal.STL.html) — параметры `period`, `seasonal`, `trend`, `robust` и ограничения метода.
- [Forecasting: Principles and Practice, STL decomposition](https://otexts.com/fpp3/stl.html) — концептуальная рамка STL и правила чтения trend/seasonal/remainder.
- [Forecasting: Principles and Practice, Time series components](https://otexts.com/fpp3/components.html) — additive/multiplicative decomposition и смысл components.
- [pandas.Series.asfreq](https://pandas.pydata.org/docs/reference/api/pandas.Series.asfreq.html) — как явно зафиксировать regular frequency перед передачей ряда в time-series методы.
