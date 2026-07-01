# Аномалии временных рядов и forecast package

> Хороший forecast handoff говорит не только число, но и почему этому числу можно доверять ровно в этих границах.

- **Тип:** Case
- **Треки:** Decision, Systems
- **Пререквизиты:** `14-time-series/11-prediction-intervals`
- **Время:** ~90 минут
- **Результат:** вы собираете `time-series forecast package`: upstream quality gates,
  leaderboard, prediction intervals, anomaly policy, decision report и checksum manifest.

## Цели обучения

- Собрать forecast package из evidence-файлов всей временной цепочки.
- Разделить anomaly labels: `data_quality`, `calendar_expected`,
  `model_misspecification`, `product_signal_candidate`, `inconclusive`.
- Не превращать partial rows, late revisions, holiday и release context в product signal.
- Пронести upstream warnings в decision report, не скрывая ограничения tiny profile.
- Выпустить checksum manifest, который фиксирует входы и outputs пакета.

## Проблема

После `14/11` у нас есть interval forecast. Но бизнесу нельзя отдавать только таблицу:

```text
2026-03-20, point=1160, interval=[1144, 1176]
```

Эта строка не отвечает на важные вопросы:

- ряд был свежим и закрытым на момент прогноза?
- были ли late revisions после forecast origin?
- model leaderboard выбран на корректных rolling origins?
- interval coverage проверен на backtest, а не только на формуле?
- всплеск пришелся на праздник, релиз, кампанию или ingestion gap?
- что именно считается product signal, а что только поводом для review?

Финальный урок собирает эти ответы в один package. Он не делает forecast "боевым"
магически. Он делает handoff воспроизводимым и честным.

## Концепция

Forecast package - это не папка с картинками. Это contract между аналитиком, системой и
пользователем решения:

```text
scenario -> data audits -> leakage checks -> baselines -> candidates
         -> rolling backtests -> metrics -> intervals -> anomaly policy
         -> decision report -> checksum manifest
```

Anomaly policy идет после quality gates. Порядок важен:

| Gate | Вопрос | Типичный label |
|---|---|---|
| `data_quality` | Значение закрыто, свежее, не backfilled после origin? | `data_quality` |
| `calendar_context` | Есть праздник, релиз, кампания, payday или другой known context? | `calendar_expected` |
| `interval_breach` | Actual вне primary prediction interval? | still review |
| `model_diagnostics` | Threshold не сломан самой моделью или interval method? | `model_misspecification` |
| `business_review` | Осталось ли событие без data/calendar/model объяснения? | `product_signal_candidate` или `inconclusive` |

`product_signal_candidate` - самый дорогой label. Его нельзя ставить, если строка partial,
если есть late revision, если known calendar context не разобран, или если сам interval
method undercovers на backtests.

Tiny profile специально заканчивается так:

```json
{
  "valid": true,
  "decision_status": "diagnostic_forecast_package_not_production_release",
  "warnings": ["upstream_warnings_propagated_to_decision"]
}
```

`valid=true` означает, что package собран корректно. Это не означает production SLA.

## Соберите это

Минимальная anomaly triage функция выглядит так:

```python
if source_status in {"partial", "late", "backfilled", "quality_hold"}:
    label = "data_quality"
elif is_holiday or campaign_active or release_active:
    label = "calendar_expected"
elif method_id == "model_based_normal" and coverage_status == "diagnostic_undercoverage":
    label = "model_misspecification"
elif future_context_without_actual:
    label = "inconclusive"
else:
    label = "product_signal_candidate"
```

В artifact эта логика не живет отдельно от evidence. Она проверяет:

- `forecast_package_spec.json` и `forecast_scenario.json`;
- десять upstream reports из `14/01`-`14/11`;
- `metric_leaderboard.csv`;
- `interval_forecasts.csv` и `interval_coverage.csv`;
- raw tiny tables `metric_observations.csv`, `calendar.csv`, `data_revisions.csv`.

Ключевой контракт:

```text
primary_model_id = metric_report.outputs.top_model_id
primary_interval_method = interval_report.outputs.primary_interval_method
primary interval rows = target_segments * horizon_days
```

Если один из этих пунктов не сходится, package invalid.

## Используйте это

Готовый artifact:

```text
outputs/time_series_forecast_packager.py
```

Запуск всего урока из корня репозитория:

```bash
uv run --locked python phases/14-time-series/12-time-series-anomalies/code/main.py
```

CLI пишет шесть файлов:

- `outputs/anomaly_flags.csv` - review cases с label, gate, evidence и recommended action;
- `outputs/quality_gate_summary.csv` - итог всех checks;
- `outputs/anomaly_policy.json` - machine-readable policy для labels и gates;
- `outputs/forecast_package_report.json` - валидность package, warnings, counts и decision status;
- `outputs/decision_report.md` - короткий handoff для решения;
- `outputs/forecast_package_manifest.json` - checksums входов и outputs.

Фрагмент `anomaly_flags.csv`:

| Case | Label | Gate | Evidence |
|---|---|---|---|
| `dq-source-all-2026-03-17` | `data_quality` | `data_quality` | `source_status=partial` |
| `calendar-all-2026-03-08` | `calendar_expected` | `calendar_context` | `holiday:spring_promo_day` |
| `model-misspec-seasonal_naive_7-overall-*-*` | `model_misspecification` | `model_diagnostics` | `model_based_normal` undercoverage |
| `future-context-all-2026-03-20` | `inconclusive` | `business_review` | future campaign context |

Tiny output summary:

```json
{
  "anomaly_rows": 41,
  "labels": {
    "data_quality": 3,
    "calendar_expected": 8,
    "model_misspecification": 14,
    "product_signal_candidate": 0,
    "inconclusive": 16
  }
}
```

Это хороший результат: package не выдумывает product signal там, где есть quality,
calendar или model evidence.

## Сломайте это

Проверьте failure modes.

1. Удалите `inconclusive` из `anomaly_policy.labels`. Check
   `anomaly_policy_contains_all_labels` должен заблокировать package.
2. Поставьте `primary_model_id = "seasonal_naive_7"`. Check
   `primary_model_matches_metric_leaderboard` должен упасть.
3. Поставьте `primary_interval_method = "residual_bootstrap"`. Check
   `primary_interval_method_matches_interval_report` должен упасть.
4. Удалите primary interval rows для ETS residual quantile. Check
   `primary_interval_forecasts_exist` должен остановить handoff.
5. Сделайте `metric_report.valid = false`. Check `upstream_reports_are_valid`
   должен заблокировать package.
6. Запустите CLI с `--fail-on-warning`. Tiny profile завершится non-zero, потому что
   upstream warnings запрещают production release.

Строгий режим:

```bash
python outputs/time_series_forecast_packager.py \
  --spec ../data/tiny/forecast_package_spec.json \
  --scenario ../data/tiny/forecast_scenario.json \
  --metric-observations ../data/tiny/metric_observations.csv \
  --calendar ../data/tiny/calendar.csv \
  --data-revisions ../data/tiny/data_revisions.csv \
  --metric-leaderboard ../10-forecast-metrics/outputs/metric_leaderboard.csv \
  --interval-forecasts ../11-prediction-intervals/outputs/interval_forecasts.csv \
  --interval-coverage ../11-prediction-intervals/outputs/interval_coverage.csv \
  --time-index-report ../01-time-index/outputs/time_index_audit.json \
  --resampling-report ../02-resampling/outputs/resampling_report.json \
  --window-feature-report ../03-rolling/outputs/window_feature_report.json \
  --seasonality-report ../04-trend-and-seasonality/outputs/seasonality_report.json \
  --temporal-leakage-report ../05-temporal-leakage/outputs/temporal_leakage_report.json \
  --baseline-report ../06-forecast-baselines/outputs/baseline_report.json \
  --model-report ../08-ets-and-arima/outputs/model_report.json \
  --backtest-report ../09-backtesting/outputs/backtest_report.json \
  --metric-report ../10-forecast-metrics/outputs/metric_report.json \
  --interval-report ../11-prediction-intervals/outputs/interval_report.json \
  --output-dir outputs \
  --fail-on-warning
```

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/12-time-series-anomalies/tests -v
```

Они проверяют:

- воспроизводимость `forecast_package_spec.json`;
- counts anomaly labels в tiny package;
- partial rows и late revisions классифицируются как `data_quality`;
- holiday, release и future campaign context не становятся product signal;
- model-based undercoverage становится `model_misspecification`;
- manifest хэширует входы и generated outputs;
- decision report сохраняет interpretation boundary;
- блокировки missing anomaly label, wrong primary model, wrong interval method,
  invalid upstream report и missing primary interval rows;
- CLI пишет package и падает в strict warning mode.

## Поставьте результат

Переиспользуемый artifact:

```text
outputs/time_series_forecast_packager.py
```

Минимальный handoff:

```bash
python outputs/time_series_forecast_packager.py \
  --spec path/to/forecast_package_spec.json \
  --scenario path/to/forecast_scenario.json \
  --metric-observations path/to/metric_observations.csv \
  --calendar path/to/calendar.csv \
  --data-revisions path/to/data_revisions.csv \
  --metric-leaderboard path/to/metric_leaderboard.csv \
  --interval-forecasts path/to/interval_forecasts.csv \
  --interval-coverage path/to/interval_coverage.csv \
  --time-index-report path/to/time_index_audit.json \
  --resampling-report path/to/resampling_report.json \
  --window-feature-report path/to/window_feature_report.json \
  --seasonality-report path/to/seasonality_report.json \
  --temporal-leakage-report path/to/temporal_leakage_report.json \
  --baseline-report path/to/baseline_report.json \
  --model-report path/to/model_report.json \
  --backtest-report path/to/backtest_report.json \
  --metric-report path/to/metric_report.json \
  --interval-report path/to/interval_report.json \
  --output-dir path/to/package
```

Перед передачей результата проверьте:

- `forecast_package_report.json.valid = true`;
- `summary.warnings` явно показаны пользователю;
- `anomaly_flags.csv` не содержит unreviewed `product_signal_candidate`;
- `decision_report.md` не делает causal claim;
- `forecast_package_manifest.json` покрывает inputs и outputs.

## Упражнения

1. Добавьте synthetic actual после `2026-03-20`, который вышел за primary interval. Какие
   условия должны выполниться, чтобы label стал `product_signal_candidate`?
2. Разделите `calendar_expected` на `holiday_expected`, `campaign_expected`,
   `release_expected`. Что станет проще в decision report и что сложнее в policy?
3. Сделайте model-based normal primary method. Какие checks должны стать строже?
4. Добавьте `owner_review_status` в anomaly flags. Где должен блокироваться package,
   если review не завершен?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Forecast package | Архив с прогнозной таблицей | Проверяемый handoff из scenario, checks, forecast evidence, anomaly policy, report и manifest |
| Anomaly flag | Автоматический product alert | Review case с label, gate, evidence и действием |
| Product signal candidate | Любой outlier | Событие после data/calendar/model gates и business review |
| Data-quality anomaly | Неприятная мелочь в источнике | Причина не интерпретировать residual как бизнес-сигнал |
| Calendar expected | Доказанная причина изменения | Known context, который требует annotation, но не causal claim |
| Checksum manifest | Формальность в конце | Способ зафиксировать точные versions входов и outputs |
| Valid package | Production SLA | Корректно собранный package; warnings могут блокировать production interpretation |

## Дополнительное чтение

- [Forecasting: Principles and Practice, Forecasting workflow](https://otexts.com/fpp3/) - практический контекст для сценариев, backtesting, intervals и ограничений интерпретации forecast handoff.
- [Forecasting: Principles and Practice, Prediction intervals](https://otexts.com/fpp3/prediction-intervals.html) - объясняет, почему forecast handoff должен включать uncertainty, а не только point forecast.
- [NIST/SEMATECH e-Handbook, Time Series Analysis](https://www.itl.nist.gov/div898/handbook/pmc/section4/pmc4.htm) - первичный справочник по time-series monitoring, diagnostics и special causes для контрольных карт и рядов.
- [Martin Fowler, Data Mesh Principles and Logical Architecture](https://martinfowler.com/articles/data-mesh-principles.html) - источник про data products и contract-style ownership; применимо к forecast package как data product.
- [OpenLineage specification](https://openlineage.io/docs/spec/) - пример machine-readable lineage и metadata подхода; checksum manifest в уроке решает похожую задачу на маленьком масштабе.
