# Временная утечка

> В прогнозировании честный split определяется не строкой в таблице, а тем, что было
> известно на forecast origin.

- **Тип:** Case
- **Треки:** Decision
- **Пререквизиты:** `14-time-series/04-trend-and-seasonality`
- **Время:** ~75 минут
- **Результат:** вы строите cutoff contract и audit report, которые блокируют random split,
  target leakage, future-known-only признаки, centered windows, full-sample statistics и
  backfilled revisions after origin.

## Цели обучения

- Зафиксировать `forecast_origin`, `complete_through`, `training_end`, `embargo_dates` и
  forecast horizon как единый контракт.
- Отличить безопасные lag/window/calendar features от признаков, которые используют
  информацию после cutoff.
- Проверить, что known future calendar features были известны до forecast origin.
- Заблокировать ревизии истории, опубликованные после forecast origin.
- Выпустить `temporal-leakage-auditor` как переиспользуемый CLI перед baseline-уроками.

## Проблема

После `14/04` у нас есть аккуратный daily series, rolling features, сезонный профиль и
календарный контекст. Теперь легко сделать красивый, но нечестный эксперимент:

```text
random train/test split -> модель видит будущие даты
current target as feature -> модель получает ответ
centered rolling mean -> окно смотрит вперед
full-sample scaling -> статистики посчитаны по train и test вместе
latest revised values -> история исправлена после момента прогноза
```

Метрики такого эксперимента будут выглядеть лучше, чем реальный forecast. Бизнес увидит
заниженный риск, команда поддержки заложит неправильную емкость, а rollout guardrails
будут основаны на данных, которых в день решения еще не было.

Урок строит `temporal-leakage-auditor`: CLI, который принимает source series, window
features, leakage audit из `14/03`, calendar, data revisions, forecast scenario и
temporal leakage spec. На выходе он пишет cutoff contract, feature decision report и
общий JSON-отчет.

## Концепция

Временная утечка возникает, когда расчет имитирует прогноз из прошлого, но использует
информацию, доступную только в будущем.

| Объект | Что фиксирует | Зачем нужен |
|---|---|---|
| `forecast_origin` | Момент выпуска прогноза. | Отделяет известное от будущего. |
| `complete_through` | Последняя закрытая дата метрики. | Не дает обучаться на partial period. |
| `training_end` | Последняя дата train в split plan. | Должна совпадать с `complete_through`. |
| `embargo_dates` | Даты рядом с cutoff, которые есть в данных, но не идут в train. | Защищают от partial/post-cutoff rows. |
| `horizon` | Даты, на которые делается прогноз. | Проверяет, что calendar features покрывают будущее. |
| `revision_policy` | Snapshot-правило для исправленных исторических значений. | Запрещает использовать ревизии, опубликованные после origin. |

Главная проверка звучит так:

```text
Для каждой строки, признака и ревизии спросить:
"Было ли это известно на forecast_origin?"
```

Для target history ответ проще: training rows не могут быть позже `training_end`.

Для window features нужно доказательство из `leakage_audit.csv`: например,
`rolling_7_mean_lag1` допустим только если `latest_source_date_used < feature_date`.

Для calendar features есть два класса:

- deterministic calendar вроде `day_of_week` можно вычислить заранее;
- business calendar вроде `campaign_active` можно использовать только если активная
  кампания была известна до forecast origin.

Запрещенные availability types в tiny spec:

| Тип | Почему опасен |
|---|---|
| `target_at_feature_date` | Признак равен ответу на ту же дату. |
| `future_target` | Использует target после feature date. |
| `centered_window` | Окно заглядывает вправо от текущей даты. |
| `full_sample_statistic` | Статистика посчитана по train и будущему test вместе. |
| `random_split` | Нарушает временной порядок оценки. |
| `backfilled_revision_after_origin` | История исправлена значением, которого еще не было на forecast origin. |
| `post_cutoff_observation` | Обучение видит строку после cutoff. |

## Соберите это

Сначала соберите минимальный контракт вручную. Он не требует модели: только даты и правило
доступности.

```python
from datetime import date, timedelta

forecast_origin = "2026-03-18T09:00:00+03:00"
complete_through = date(2026, 3, 16)
training_end = date(2026, 3, 16)
first_forecast_date = date(2026, 3, 18)
horizon_days = 28
horizon_end = first_forecast_date + timedelta(days=horizon_days - 1)
embargo_dates = [date(2026, 3, 17)]

assert training_end == complete_through
assert first_forecast_date > training_end
assert horizon_end.isoformat() == "2026-04-14"
assert complete_through not in embargo_dates
```

Теперь добавьте проверку training rows:

```python
rows = [
    {"observed_date": "2026-03-16", "include_in_training": True},
    {"observed_date": "2026-03-17", "include_in_training": False},
]

bad_rows = [
    row for row in rows
    if row["include_in_training"] and row["observed_date"] > training_end.isoformat()
]
assert bad_rows == []
```

Дальше проверьте признаки. У каждого candidate feature есть `availability_type` и флаг
`selected`.

```python
forbidden = {
    "target_at_feature_date",
    "future_target",
    "centered_window",
    "full_sample_statistic",
    "random_split",
    "backfilled_revision_after_origin",
    "post_cutoff_observation",
}

features = [
    {"name": "value_lag_1", "availability_type": "past_observation", "selected": True},
    {"name": "current_value", "availability_type": "target_at_feature_date", "selected": False},
]

selected_forbidden = [
    feature["name"]
    for feature in features
    if feature["selected"] and feature["availability_type"] in forbidden
]
assert selected_forbidden == []
```

Самая частая ошибка здесь - поверить названию признака. `rolling_7_mean_lag1` выглядит
безопасно, но production-проверка должна смотреть не на имя, а на audit evidence:

```python
audit_row = {
    "feature_name": "rolling_7_mean_lag1",
    "feature_date": "2026-03-12",
    "latest_source_date_used": "2026-03-11",
    "valid": True,
}

assert audit_row["valid"]
assert audit_row["latest_source_date_used"] < audit_row["feature_date"]
```

Для known future business calendar проверка другая:

```python
calendar_row = {
    "date": "2026-03-20",
    "campaign_active": True,
    "known_before_date": "2026-03-01",
}

forecast_origin_date = "2026-03-18"
assert calendar_row["known_before_date"] <= forecast_origin_date
```

Если поставить `known_before_date = "2026-03-19"`, кампания станет future-known-only:
она находится в forecast horizon, но не была известна на момент прогноза.

## Используйте это

Готовый артефакт:

```text
outputs/temporal_leakage_auditor.py
```

Запуск из корня урока:

```bash
python outputs/temporal_leakage_auditor.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --features ../03-rolling/outputs/window_features.csv \
  --feature-audit ../03-rolling/outputs/leakage_audit.csv \
  --calendar ../data/tiny/calendar.csv \
  --revisions ../data/tiny/data_revisions.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --spec ../data/tiny/temporal_leakage_spec.json \
  --output-dir outputs
```

CLI пишет три файла:

- `outputs/cutoff_contract.json` - origin, train window, embargo, horizon, revision policy
  и список разрешенных selected features;
- `outputs/forbidden_feature_report.csv` - решение `allow` или `reject` по каждому
  candidate feature;
- `outputs/temporal_leakage_report.json` - checks, warnings, blocking errors и summary.

В tiny-профиле отчет валиден:

```json
{
  "valid": true,
  "warnings": [
    "forbidden_feature_candidates_rejected",
    "revisions_after_origin_are_excluded"
  ],
  "selected_features": 4,
  "rejected_feature_candidates": 6
}
```

Эти warnings не ломают pipeline. Они фиксируют, что:

- запрещенные feature candidates видимы в отчете и отклонены;
- ревизия исторического значения после forecast origin существует, но политика исключает
  ее из training snapshot.

Разрешенные selected features:

```text
value_lag_1
rolling_7_mean_lag1
day_of_week
campaign_active
```

Первые два требуют `leakage_audit.csv`; последние два требуют calendar evidence и
`known_before_date <= forecast_origin_date` для активных business events.

## Сломайте это

Проверьте семь поломок.

1. Поставьте `split_type=random` в `temporal_leakage_spec.json`. Check
   `split_plan_is_time_ordered` должен стать blocking error.
2. Пометьте `current_value` как `selected=true`. Check
   `selected_features_do_not_use_forbidden_availability` должен упасть.
3. Измените `training_end` на `2026-03-17`. Check
   `training_end_matches_complete_through` должен остановить audit.
4. Поставьте `include_in_training=true` на `2026-03-17` в `daily_resampled.csv`. Должны
   упасть `training_rows_end_at_complete_through` и `embargo_dates_are_not_training_rows`.
5. В `leakage_audit.csv` для `rolling_7_mean_lag1` сделайте
   `latest_source_date_used=feature_date`. Check `window_features_have_past_only_audit`
   должен заблокировать feature set.
6. Для `campaign_active=true` на `2026-03-20` поставьте
   `known_before_date=2026-03-19`. Check `known_future_features_known_before_origin`
   должен упасть, потому что forecast origin date - `2026-03-18`.
7. Поставьте `revision_policy=use_latest_revision`. Check
   `revision_policy_excludes_after_origin` должен заблокировать audit.

Строгий режим:

```bash
python outputs/temporal_leakage_auditor.py \
  --series ../02-resampling/outputs/daily_resampled.csv \
  --features ../03-rolling/outputs/window_features.csv \
  --feature-audit ../03-rolling/outputs/leakage_audit.csv \
  --calendar ../data/tiny/calendar.csv \
  --revisions ../data/tiny/data_revisions.csv \
  --scenario ../data/tiny/forecast_scenario.json \
  --spec ../data/tiny/temporal_leakage_spec.json \
  --fail-on-warning
```

Он вернет non-zero exit code даже на валидном tiny-профиле, потому что warnings требуют
review перед production forecast.

## Проверьте это

Тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/14-time-series/05-temporal-leakage/tests -v
```

Они проверяют:

- воспроизводимость `temporal_leakage_spec.json`;
- baseline contract: `training_end=2026-03-16`, `first_forecast_date=2026-03-18`,
  `embargo_dates=["2026-03-17"]`, `horizon_end=2026-04-14`;
- разрешение только cutoff-safe selected features;
- блокировку target leakage, random split, training after cutoff, embargo row,
  broken window audit, future-known-only calendar feature и неправильной revision policy;
- CLI outputs и `--fail-on-warning`.

Минимальная ручная проверка отчета:

```python
import json
from pathlib import Path

report = json.loads(Path("outputs/temporal_leakage_report.json").read_text())
assert report["valid"]
assert report["summary"]["blocking_errors"] == []
assert report["summary"]["warnings"] == [
    "forbidden_feature_candidates_rejected",
    "revisions_after_origin_are_excluded",
]
```

## Поставьте результат

Именованный артефакт урока:

```text
outputs/temporal_leakage_auditor.py
```

Он нужен как quality gate перед следующими baseline-уроками. Перед тем как сравнивать
naive, seasonal naive или ML-модель, запустите audit и приложите:

- `cutoff_contract.json` как явный snapshot forecast setup;
- `forbidden_feature_report.csv` как review feature catalog;
- `temporal_leakage_report.json` как машинно-проверяемый итог.

Команда воспроизводимого запуска всего урока:

```bash
uv run --locked python phases/14-time-series/05-temporal-leakage/code/main.py
```

## Упражнения

1. Добавьте candidate feature `release_active` как `known_future_calendar` и проверьте,
   что он разрешается только при корректном `known_before_date`.
2. Добавьте forbidden candidate `rolling_7_mean_centered` и объясните, почему centered
   window ломает forecast experiment даже если в коде нет явного `future_value`.
3. Расширьте audit так, чтобы он проверял `published_at <= forecast_origin` для всех
   training rows, если source series содержит publication timestamps.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Forecast origin | Просто дата начала test. | Момент, в который прогноз реально выпускается и фиксируется доступность данных. |
| Cutoff contract | Необязательная документация. | Машинно-проверяемый договор о train window, horizon, embargo и revision snapshot. |
| Temporal leakage | Только использование future target. | Любая информация после origin/cutoff, попавшая в train, features или оценку. |
| Known future feature | Любой будущий календарный признак. | Только признак, чье значение было известно до forecast origin. |
| Embargo date | Потерянная строка данных. | Дата рядом с cutoff, которая существует в источнике, но исключается из training для честности. |
| Backfilled revision | Обычное улучшение качества истории. | Исправление прошлого, которое нельзя использовать в backtest, если оно опубликовано после origin. |

## Дополнительное чтение

- [pandas: Time series / date functionality](https://pandas.pydata.org/docs/user_guide/timeseries.html) - разделы про timestamps, timezones и resampling помогают не смешивать business date, timestamp и frequency.
- [scikit-learn: Common pitfalls and data leakage](https://scikit-learn.org/stable/common_pitfalls.html#data-leakage) - официальный разбор data leakage; полезен для переноса идеи cutoff из time series в общие ML-pipelines.
- [scikit-learn: TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) - API для time-ordered split; читайте параметры `gap`, `max_train_size` и `test_size` как готовые аналоги cutoff/embargo/backtest design.
- [Forecasting: Principles and Practice, 3rd ed., Time series cross-validation](https://otexts.com/fpp3/tscv.html) - первичный учебный источник о forecast evaluation, где test observations идут после training observations.
