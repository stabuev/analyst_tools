# Категориальные признаки без leakage

## Проблема

В `16/01` CatBoost получил список `cat_features` и обучился без test-driven selection.
Но это еще не значит, что категориальные признаки безопасны. Табличная модель часто
ломается не из-за параметров бустинга, а из-за того, что категории попали в модель
нечестным или неуправляемым способом.

Типичные ошибки:

- категория рассчитана из target или событий после `prediction_time`;
- missing value молча смешали с реальным уровнем;
- validation/test содержат новые уровни, которых не было в train;
- high-cardinality поле стало почти идентификатором;
- rare levels дают нестабильный score и нестабильную feature importance;
- CatBoost умеет обработать unseen category, но команда не мониторит ее появление.

В этом уроке вы добавите отдельный categorical feature contract. Он не переобучает модель,
а проверяет, можно ли доверять тем категориям, которые уже переданы CatBoost.

## Концепция

Категориальный признак безопасен не потому, что он строковый и CatBoost принимает его в
`Pool`. Он безопасен, если одновременно выполнены четыре условия.

1. **Источник разрешен problem spec.** Например, `user_profile` можно использовать, а
   `churn_label` нельзя.
2. **Значение известно до prediction time.** Категория из будущего события является
   leakage даже при нативной обработке CatBoost.
3. **Missing semantics объявлены.** Пропуск может быть ошибкой данных или отдельным
   состоянием источника; это должно быть видно.
4. **Unknown categories не скрыты.** Новые уровни в validation/test допустимы только при
   явной policy и мониторинге.

Отдельно нужна проверка high-cardinality. Много уровней не всегда блокирует признак, но
создает риск: rare levels, почти-идентификаторы, нестабильные target statistics и
завышенная важность. В tiny-профиле `acquisition_channel` специально маленький, но уже
показывает поведение high-cardinality-like поля: есть rare train levels и unseen уровни в
validation/test.

## Соберите это

Новый contract лежит здесь:

```text
phases/16-tabular-ml/data/tiny/categorical_feature_contract.json
```

Он фиксирует:

- `categorical_audit_id`;
- связь с `catboost_baseline_id` и `catboost_model_id` из `16/01`;
- список категориальных признаков;
- `missing_policy` для каждого признака;
- `unknown_category_policy`;
- threshold для high-cardinality warning на tiny-профиле;
- known-bad categorical candidates: target, post-intervention outcome и full-sample
  target encoding.

Основной артефакт:

```text
phases/16-tabular-ml/02-categorical-features/outputs/categorical_feature_auditor.py
```

Он читает:

- `catboost_model_spec.json`;
- `catboost_report.json` из `16/01`;
- `ml_raw_features.csv`;
- `ml_split_manifest.csv`;
- `feature_availability_report.csv` из leakage-урока `15/13`.

Минимальный механизм audit выглядит так:

```python
train_values = values_by_feature_and_split[feature]["train"]
for row in validation_and_test_rows:
    value = normalize_missing(row[feature], "__MISSING__")
    if value not in train_values:
        record_unknown_category(row["snapshot_id"], feature, value)
```

Production-часть урока делает это же системно: строит inventory по всем split, соединяет
его с leakage policy, пишет warnings и blocking checks.

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/16-tabular-ml/02-categorical-features/code/main.py
```

Ожидаемая сводка:

```json
{
  "audit_valid": true,
  "categorical_audit_id": "trial-churn-categorical-feature-audit-v0",
  "catboost_model_id": "catboost_depth2_native_categories",
  "feature_count": 4,
  "unknown_category_row_count": 3,
  "high_cardinality_feature_count": 1,
  "selected_leaky_feature_count": 0,
  "readiness_status": "ready_for_early_stopping_lesson"
}
```

После запуска появляются пять файлов:

- `categorical_feature_report.json` — общий отчет и checks;
- `categorical_inventory.csv` — уровни категорий, counts по train/validation/test,
  `unseen_in_train`, `rare_in_train`, `missing_value`;
- `categorical_unknowns.csv` — конкретные validation/test rows с неизвестными train
  уровнями;
- `categorical_leakage_audit.csv` — выбранные безопасные признаки и known-bad rejected
  candidates;
- `categorical_serialized_contract.json` — handoff для `16/03`.

В tiny-профиле audit валиден, но содержит warnings:

- `S006` имеет unseen `acquisition_channel = influencer`;
- `S007` имеет missing `acquisition_channel`, записанный как `__MISSING__`;
- `S010` имеет unseen `acquisition_channel = partnership`;
- `acquisition_channel` превышает tiny threshold по числу уровней;
- несколько train levels имеют count `1`.

Это не production claim и не запрет CatBoost. Это честный список рисков, который нельзя
спрятать за хорошим API.

## Сломайте это

Попробуйте добавить в `categorical_feature_contract.json` known-bad candidate:

```json
{
  "feature_name": "segment_churn_rate_full_dataset",
  "semantic_type": "forbidden_full_sample_target_encoding",
  "missing_policy": "map_missing_to_explicit_category",
  "unknown_category_policy": "allow_native_catboost_unseen_value_and_monitor"
}
```

Audit должен заблокировать contract: full-sample target encoding видит labels из
validation/test и не может быть входом модели.

Теперь измените availability report так, будто `platform` стал доступен только после
prediction time. Проверка `selected_categorical_features_pass_leakage_policy` должна
упасть: timing важнее того, что поле выглядит обычной категорией.

Наконец удалите `unknown_category_policy` у любого признака. Даже если данные сейчас не
ломаются, contract неполный: команда не договорилась, что делать с новым уровнем на
scoring.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/02-categorical-features/tests
```

Тесты проверяют:

- handoff с `16/01`: тот же CatBoost model id и тот же список `cat_features`;
- inventory по train/validation/test;
- unknown rows для `acquisition_channel`;
- missing `__MISSING__` как отдельную категорию;
- high-cardinality warning;
- rare train levels;
- rejected known-bad candidates: target, post-intervention outcome и target encoding;
- блокировку feature availability после prediction time;
- CLI `--fail-on-warning`.

Для полного курса после изменения статуса:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/render_curriculum.py --check
uv run --locked python scripts/render_outputs.py --check
uv run --locked python scripts/render_site.py --check
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Готовый результат урока — categorical feature audit package. Его можно передать дальше в
`16/03`, где появятся validation curves и early stopping:

- CatBoost model spec остается прежним;
- categorical contract подтверждает, что выбранные категории доступны до prediction time;
- known-bad categorical candidates явно отклонены;
- unseen/missing/high-cardinality/rare levels не блокируют tiny run, но сохраняются как
  warnings;
- `ready_for_early_stopping_lesson` означает, что следующий урок может управлять training
  iterations, не возвращаясь к вопросу "а категории вообще безопасны?".

## Упражнения

1. Уменьшите `max_distinct_values_tiny` для `platform` до `2` и объясните, почему warning
   станет видимым, но не должен автоматически блокировать модель.
2. Добавьте новый validation row с неизвестным `country` и проверьте, как изменится
   `categorical_unknowns.csv`.
3. Измените `missing_policy` у `acquisition_channel` на `missing_not_expected_block_if_seen`
   и предложите, какой check должен стать blocking в production-профиле.
4. Сравните `categorical_leakage_audit.csv` с `feature_availability_report.csv`: какие поля
   достаточно безопасны для score, а какие нужны только как rejected examples?

## Ключевые термины

- **Categorical feature contract** — машинно читаемый договор о списке категорий,
  missing/unknown policies и доступности признаков.
- **Unknown category** — уровень, который появился в validation/test или scoring, но не
  встречался в train.
- **Missing semantics** — смысл пропуска: ошибка данных, неизвестное значение или
  отдельное состояние источника.
- **High-cardinality feature** — категориальный признак с большим числом уровней, где
  высок риск редких категорий и нестабильной интерпретации.
- **Target encoding leakage** — кодирование категории через target с использованием
  validation/test labels или full sample до split.
- **Feature availability** — доказательство, что значение признака известно до
  `prediction_time`.

## Дополнительное чтение

- [CatBoost categorical features](https://catboost.ai/docs/en/features/categorical-features) — как CatBoost обрабатывает категориальные признаки и где начинаются ограничения метода.
- [CatBoost Pool](https://catboost.ai/docs/en/concepts/python-reference_pool) — официальный контракт передачи `cat_features` по именам или индексам.
- [CatBoostClassifier](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier) — параметры и sklearn-like API, которые использует предыдущий CatBoost lesson.
- [scikit-learn common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html) — раздел про leakage и неправильную подготовку данных до split.
