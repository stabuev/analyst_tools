# Drift, стабильность и interpretation package

> Финальный ML-пакет нужен не для красивого лидерборда, а для честного решения: что можно утверждать, что нельзя и какие evidence это доказывают.

**Тип:** Case  
**Треки:** ML, Delivery  
**Пререквизиты:** `16-tabular-ml/10-mlflow`  
**Время:** ~105 минут  
**Результат:** tabular ML interpretation package с upstream evidence matrix, drift/stability diagnostics, decision report и checksum manifest.

## Цели обучения

- Собрать CatBoost, interpretation, cost decision, Optuna и MLflow outputs в один проверяемый package.
- Разделить score drift, feature drift, importance stability и segment stability.
- Показать disagreement между built-in importance, permutation importance и SHAP без причинного overclaim.
- Принять финальный decision status из evidence, а не из одной метрики.
- Выпустить sha256 manifest для inputs и generated outputs.

## Проблема

К концу фазы 16 у нас есть сильная табличная цепочка:

```text
CatBoost candidate
categorical feature audit
early stopping trace
built-in importance
permutation importance
SHAP explanations
segment analysis
cost-sensitive decision gate
Optuna trial ledger
MLflow experiment ledger
```

Но цепочка еще не поставка. Если передать заказчику только "Optuna улучшила logloss",
получится опасно короткий вывод:

```text
best validation logloss: 0.696531
source validation logloss: 0.698394
```

В соседних evidence уже видно, почему такой вывод нельзя превращать в promotion:

```text
candidate top-k cost: 7
baseline top-k cost: 1
hidden failure slices: 13
unseen acquisition_channel categories after train: 3
importance methods disagree on direction
```

Финальный package собирает все это в один артефакт и говорит: держим baseline, CatBoost
остается diagnostic candidate, а drift/stability watch обязателен перед новым claim.

## Концепция

Финальный пакет похож на маленький model governance dossier. Он не обучает новую модель,
а проверяет, можно ли доверять уже собранной evidence chain.

| Слой | Что проверяет | Типичная ошибка |
|---|---|---|
| Upstream evidence | Все отчеты валидны и относятся к одному problem id | Потерять warning из раннего урока |
| Score drift | Похожи ли распределения score между train/validation/test | Объявить drift только по среднему score |
| Feature drift | Есть ли новые категории и high-cardinality risk | Считать native CatBoost categories магической защитой |
| Importance stability | Совпадают ли top feature, направление и смысл методов | Смешать SHAP, permutation и built-in importance в один "эффект" |
| Segment stability | Не ухудшился ли важный срез | Спрятать hidden failure за средним score |
| Decision report | Что можно делать с моделью | Сделать production или causal claim из offline evidence |
| Manifest | Какие inputs и outputs входят в поставку | Получить неревьюируемый набор файлов |

В этом уроке итоговый status:

```text
decision_status = keep_baseline
monitoring_status = drift_watch_required
```

Это не поражение модели. Это честная поставка: CatBoost evidence сохранена, но promotion
заблокирован cost, segment and stability gates.

## Соберите это

### Шаг 1. Объявите package spec

Spec находится в `phases/16-tabular-ml/data/tiny/tabular_ml_package_spec.json`. В нем
зафиксированы:

- `package_id`;
- upstream reports и evidence files;
- drift thresholds;
- stability policy;
- allowed decision statuses;
- список generated outputs.

Ключевой фрагмент:

```json
{
  "decision_policy": {
    "candidate_failed_gate_status": "keep_baseline",
    "monitoring_status_with_warnings": "drift_watch_required",
    "production_ready_allowed": false,
    "causal_claim_allowed": false,
    "serving_release_allowed": false
  }
}
```

Если поменять `candidate_failed_gate_status` на `promote_candidate_with_limits`, тесты
заблокируют package, потому что required promotion gates уже провалены.

### Шаг 2. Проверьте upstream reports

Packager читает 11 отчетов:

```text
baseline_package_report
catboost_report
categorical_report
early_stopping_report
built_in_importance_report
permutation_importance_report
shap_report
segment_report
cost_report
optuna_report
mlflow_report
```

Каждый report должен быть `valid=true`, без blocking errors и с тем же `problem_id`.
MLflow handoff обязан иметь:

```text
readiness_status = ready_for_drift_and_stability_lesson
```

### Шаг 3. Посчитайте score drift

Score drift считается по `optuna_tuned_predictions.csv`. Reference split - train.

В tiny fixture score распределение почти не меняется:

| split | mean_score | mean_delta_vs_train | status |
|---|---:|---:|---|
| train | 0.500000 | 0.000000 | stable |
| validation | 0.498333 | -0.001667 | stable |
| test | 0.499000 | -0.001000 | stable |

Это важно: score drift спокойный, но итоговый package все равно не обязан быть stable.
Модель может ломаться через feature mix, explanation disagreement или сегменты.

### Шаг 4. Посчитайте feature drift

Feature drift берется из `categorical_inventory.csv`.

`acquisition_channel` получает watch:

```text
after_train_row_count = 8
unseen_after_train_count = 3
unseen_after_train_rate = 0.375
high_cardinality_feature = true
stability_status = watch
```

CatBoost умеет принимать новые категории, но это не отменяет мониторинг. Native categorical
handling - не пропуск через drift gate.

### Шаг 5. Проверьте importance stability

В package попадают четыре explanation views:

```text
CatBoost PredictionValuesChange
CatBoost LossFunctionChange
Permutation importance
Tree SHAP mean_abs
```

Все называют `platform` top feature, но направления разные:

```text
loss_decrease_when_permuted,mixed,negative,positive
```

Значит interpretation остается diagnostic-only. Мы не прячем disagreement и не превращаем
top feature в причинное утверждение.

### Шаг 6. Перенесите segment failures

Segment stability читает `strong_model_segment_deltas.csv`.

В tiny fixture:

```text
segment rows = 19
hidden failure slices = 13
overall candidate worse than baseline = true
```

Это напрямую блокирует promotion. Даже если средняя метрика или objective улучшились,
нельзя выпускать candidate, который ухудшает важные срезы и добавляет новые false
positives/false negatives.

### Шаг 7. Выпустите manifest

Manifest хэширует:

- package spec;
- baseline package inputs;
- upstream reports;
- upstream evidence tables;
- generated package outputs.

Он не хэширует сам себя, чтобы не получить рекурсивный hash. В committed package:

```text
manifest inputs = 37
manifest outputs = 10
hash algorithm = sha256
```

## Используйте это

Запустите урок из корня репозитория:

```bash
uv run --locked python phases/16-tabular-ml/11-drift-and-stability/code/main.py
```

Ожидаемый summary:

```json
{
  "package_valid": true,
  "package_id": "trial-churn-tabular-ml-interpretation-package-v0",
  "decision_status": "keep_baseline",
  "monitoring_status": "drift_watch_required",
  "evidence_row_count": 16,
  "feature_drift_watch_count": 1,
  "importance_stability_watch_count": 4,
  "hidden_failure_slice_count": 13,
  "production_ready": false,
  "readiness_status": "phase_16_complete_tabular_ml_interpretation_package"
}
```

CLI artifact можно запускать отдельно:

```bash
uv run --locked python phases/16-tabular-ml/11-drift-and-stability/outputs/tabular_ml_interpretation_packager.py \
  --output-dir phases/16-tabular-ml/11-drift-and-stability/outputs
```

Для CI-gate, который должен падать на warnings:

```bash
uv run --locked python phases/16-tabular-ml/11-drift-and-stability/outputs/tabular_ml_interpretation_packager.py \
  --fail-on-warning
```

В этом уроке команда возвращает code `2`, потому что warnings намеренно видимы.

## Сломайте это

### Ошибка 1. Продвинуть candidate при проваленных gates

Измените spec:

```json
"candidate_failed_gate_status": "promote_candidate_with_limits"
```

Package станет invalid:

```text
candidate_cannot_be_promoted_when_required_decision_gates_fail
```

### Ошибка 2. Разрешить production claim

Измените:

```json
"production_ready_allowed": true
```

Package блокируется до сборки:

```text
decision_policy_blocks_production_causal_and_serving_claims
```

### Ошибка 3. Удалить MLflow run table

Если `mlflow_run_table.csv` отсутствует, package не может доказать experiment lineage:

```text
required_upstream_evidence_files_exist
```

### Ошибка 4. Сделать upstream report invalid

Если любой upstream report получает `valid=false`, итоговая сборка не должна прятать
проблему:

```text
upstream_reports_are_valid
```

## Проверьте это

Тесты запускаются так:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/11-drift-and-stability/tests
```

Они проверяют:

- итоговый `keep_baseline` и отсутствие production claim;
- score drift отдельно от feature drift;
- watch по unseen `acquisition_channel`;
- disagreement между built-in, permutation и SHAP;
- перенос 13 hidden failure slices;
- evidence matrix с MLflow handoff;
- sha256 manifest inputs and outputs;
- блокировки для invalid upstream, missing evidence и неверной decision policy.

## Поставьте результат

Урок поставляет CLI:

```text
outputs/tabular_ml_interpretation_packager.py
```

Он пишет:

```text
tabular_ml_package.json
tabular_ml_package_report.json
tabular_ml_evidence_matrix.csv
score_drift.csv
feature_drift.csv
importance_stability.csv
segment_stability.csv
stability_report.json
interpretation_report.md
decision_report.md
tabular_ml_package_manifest.json
```

Главный потребитель - следующий delivery layer. Он получает не "лучшую модель", а
ограниченный и проверяемый handoff:

```text
baseline stays selected
CatBoost remains diagnostic candidate
drift/stability watch is required
no causal or serving claim is made
```

## Упражнения

1. Измените threshold `feature_watch_unseen_after_train_rate` с `0.2` на `0.5` и объясните,
   почему это меняет feature drift warning, но не segment decision.
2. Добавьте в evidence matrix отдельную строку для `mlflow_artifact_inventory.csv` и
   проверьте, что manifest output hash изменился.
3. Сымитируйте stable interpretation: измените `explanation_disagreement.csv` в temp-copy
   так, чтобы все методы имели одно направление, и сравните warnings.
4. Добавьте новый allowed status `needs_more_data` и опишите, чем он отличается от
   `keep_baseline` в этом package.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Score drift | Любое изменение score означает плохую модель | Изменение распределения score, которое требует диагностики, но не заменяет quality gate |
| Feature drift | CatBoost решает drift за счет native categories | Новые категории и high-cardinality mix остаются monitoring risk |
| Importance stability | Один top feature делает объяснение стабильным | Нужно сравнивать вопрос метода, направление, split и uncertainty |
| Hidden segment failure | Small-n slice можно не показывать | Small-n slice diagnostic-only, но скрывать ухудшение нельзя |
| Decision status | Это просто лучший metric | Это ограниченный вывод из всей evidence chain |
| Checksum manifest | Формальность в конце | Воспроизводимый список inputs/outputs с sha256 |

## Дополнительное чтение

- [scikit-learn: Permutation feature importance](https://scikit-learn.org/stable/modules/permutation_importance.html) - перечитайте разделы про model reliance, held-out data и ограничения при коррелированных признаках.
- [CatBoost: Feature importance](https://catboost.ai/docs/en/concepts/fstr) - сравните смысл PredictionValuesChange и LossFunctionChange, чтобы не смешивать их в одно объяснение.
- [SHAP TreeExplainer](https://shap.readthedocs.io/en/stable/generated/shap.TreeExplainer.html) - проверьте параметры `model_output`, background data и additivity для tree models.
- [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/) - посмотрите, как runs, params, metrics, tags и artifacts образуют experiment ledger.
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) - используйте как общий контекст для ограничения claims, traceability и governance, не как замену локальным тестам.
