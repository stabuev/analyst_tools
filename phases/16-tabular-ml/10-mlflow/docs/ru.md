# MLflow для истории экспериментов

> Experiment tracking полезен только тогда, когда из run history можно восстановить, что было запущено, почему это допустимо и какие ограничения нельзя забыть.

**Тип:** Build  
**Треки:** ML, Delivery  
**Пререквизиты:** `16-tabular-ml/09-optuna`  
**Время:** ~75 минут  
**Результат:** MLflow experiment ledger exporter, который логирует локальные runs с params, metrics, tags, artifacts и model metadata, а затем экспортирует проверяемый ledger без случайных raw run ids.

## Цели обучения

- Разделить MLflow tracking, model registry и serving scope.
- Залогировать локальные MLflow runs для source CatBoost, best Optuna trial и baseline gate.
- Сохранить params, metrics, tags, artifacts и model metadata рядом с upstream package id.
- Экспортировать стабильный run table, artifact inventory, metric history и reproducibility checks.
- Заблокировать handoff, если отсутствует обязательный artifact или tracking scope выходит за рамки урока.

## Проблема

После Optuna у нас появился tuned candidate:

```text
best trial = 4
depth = 2
learning_rate = 0.05
validation_logloss = 0.696531
```

Но вместе с ним появились и ограничения:

```text
best trial top-k cost = 7
baseline top-k cost = 1
cost gate still fails
```

Если передать следующему человеку только `best_params`, он увидит “параметры победителя” и легко пропустит методологический контекст. Нам нужен журнал эксперимента:

- от какого package и problem spec идет run;
- какие params и metrics были залогированы;
- какие upstream artifacts приложены;
- почему кандидат не становится production claim;
- где заканчивается локальный tracking и начинается настоящая MLOps-инфраструктура.

MLflow в этом уроке используется ровно для этого: как локальный experiment ledger.

## Концепция

MLflow Tracking хранит runs внутри experiment. У каждого run есть:

| Часть run | Что хранит | Что легко забыть |
|---|---|---|
| Params | Конфигурацию запуска | Params должны быть связаны с policy, а не с ручным перебором |
| Metrics | Числовые результаты | Метрика модели не заменяет business gate |
| Tags | Контекст и lineage | Без source package id run становится сиротой |
| Artifacts | Файлы evidence | Best params без trial ledger неревьюируемы |
| Metadata | Описание модели и ограничений | Нужны warnings и decision status |

В этом lesson fixture логируются три tracking units:

```text
source_early_stopped_catboost
best_optuna_trial
phase15_baseline_cost_gate
```

Это не model registry. Мы не регистрируем модель, не поднимаем remote tracking server и не готовим serving. Фаза 16 пока собирает evidence для финального interpretation package.

### Почему `mlflow-skinny`

Проект использует `pandas>=3`. Актуальный полный пакет `mlflow 3.14.0` на момент урока требует `pandas<3`, поэтому для tracking API используется `mlflow-skinny 3.14.0`. Он дает импорт `mlflow`, `MlflowClient`, local tracking, params, metrics, tags и artifacts - достаточно для этого урока. Model flavors и registry сознательно остаются вне scope.

### Почему не экспортируем raw `run_id`

MLflow `run_id` генерируется при каждом запуске. Если положить его в committed CSV, артефакт будет менять diff при каждом rerun. Поэтому exporter проверяет:

```text
run_id_present = True
run_id_length = 32
raw_run_id_exported = False
```

Внутри временного MLflow store run id есть. В стабильный ledger попадает `run_alias`, который задается policy.

## Соберите это

### Шаг 1. Объявите tracking policy

Policy фиксирует experiment, scope и обязательные поля:

```json
{
  "experiment": {
    "name": "trial_churn_tabular_ml_local_tracking_v0",
    "tracking_backend": "local_file_store",
    "tracking_package": "mlflow-skinny",
    "omit_raw_run_ids_from_exports": true
  },
  "tracking_scope": {
    "registry": false,
    "remote_tracking_server": false,
    "serving": false
  }
}
```

Если включить `registry=true`, auditor блокирует handoff:

```text
blocking_errors = tracking_scope_excludes_registry_and_serving
```

### Шаг 2. Сформируйте run plan

Каждый run получает стабильный alias:

| run_alias | role | model_id |
|---|---|---|
| `source_early_stopped_catboost` | source candidate | `catboost_depth2_native_categories_es_logloss` |
| `best_optuna_trial` | tuned candidate | `catboost_optuna_fixed_budget_logloss` |
| `phase15_baseline_cost_gate` | baseline gate | `trial-churn-ml-baseline-package-v0` |

Для каждого run логируются common tags:

```text
mlflow_tracking_audit_id
problem_id
source_package_id
optuna_tuning_audit_id
decision_status
readiness_status
```

Так run не отрывается от фазы 15 и Optuna-аудита.

### Шаг 3. Залогируйте metrics и artifacts

Лучший Optuna run получает:

```text
params:
  depth = 2
  learning_rate = 0.05
  random_seed = 1609
  optuna_trial_number = 4

metrics:
  validation_logloss = 0.696531
  validation_top_k_total_error_cost = 7
  baseline_validation_top_k_cost = 1
  objective_improved_vs_source = 1
  cost_gate_still_fails_vs_baseline = 1

artifacts:
  optuna_tuning_serialized_spec.json
  optuna_trial_ledger.csv
  optuna_tuned_predictions.csv
  best_optuna_trial_model_metadata.json
```

Здесь есть намеренная асимметрия: run улучшил objective, но несет warning по cost gate.

### Шаг 4. Экспортируйте стабильный ledger

Exporter читает MLflow store через `MlflowClient` и пишет:

- `mlflow_run_table.csv` - стабильные aliases, params, metrics, tags и artifact count.
- `mlflow_artifact_inventory.csv` - пути artifact'ов, source file, размер и sha256.
- `mlflow_metric_history.csv` - MLflow metric history по каждому run.
- `mlflow_reproducibility_checks.csv` - checks и warnings.
- `mlflow_model_metadata.json` - model metadata по каждому run.
- `mlflow_tracking_serialized_spec.json` - handoff в финальный stability/package урок.

## Используйте это

Запустите урок из корня репозитория:

```bash
uv run --locked python phases/16-tabular-ml/10-mlflow/code/main.py
```

Ожидаемый summary:

```json
{
  "audit_valid": true,
  "mlflow_tracking_audit_id": "trial-churn-mlflow-tracking-audit-v0",
  "mlflow_version": "3.14.0",
  "tracking_package": "mlflow-skinny",
  "experiment_name": "trial_churn_tabular_ml_local_tracking_v0",
  "run_count": 3,
  "raw_run_ids_exported": false,
  "best_run_alias": "best_optuna_trial",
  "best_validation_logloss": 0.696531,
  "best_trial_validation_top_k_cost": 7.0,
  "baseline_validation_top_k_cost": 1.0,
  "decision_status": "mlflow_ledger_ready_for_stability_package",
  "readiness_status": "ready_for_drift_and_stability_lesson"
}
```

MLflow 3.14 требует явный opt-in для filesystem backend:

```text
MLFLOW_ALLOW_FILE_STORE=true
```

Exporter ставит этот opt-in внутри локального урока. Это не production-рекомендация, а граница учебного local tracking store.

## Сломайте это

### Ошибка 1. Включить registry в tracking scope

Измените policy:

```json
"tracking_scope": {
  "registry": true
}
```

Auditor вернет:

```text
valid = false
blocking_errors = tracking_scope_excludes_registry_and_serving
```

Registry, remote tracking server и serving не входят в фазу 16.

### Ошибка 2. Не приложить trial ledger

Если `best_optuna_trial` не логирует `upstream/optuna_trial_ledger.csv`, run table все еще существует, но handoff невалиден:

```text
blocking_errors = required_artifacts_logged
```

Best trial без ledger нельзя ревьюить.

### Ошибка 3. Сделать raw run id частью committed outputs

Raw MLflow ids нужны внутри tracking store, но не должны попадать в стабильный artifact:

```text
run_id_present = True
raw_run_id_exported = False
```

Иначе каждый rerun меняет diff без изменения учебного смысла.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/10-mlflow/tests
```

Что проверяют тесты:

- summary фиксирует `mlflow 3.14.0`, `mlflow-skinny`, local file store и 3 runs;
- run table содержит стабильные aliases и не экспортирует raw run ids;
- best Optuna run хранит params trial `4`, logloss `0.696531` и cost warning metric;
- artifact inventory содержит upstream Optuna ledger, predictions и model metadata;
- metric history показывает, что нужные метрики залогированы в MLflow;
- model metadata сохраняет source package id, warnings и Optuna handoff;
- policy с registry scope блокируется;
- отсутствие обязательного artifact становится reproducibility blocker.

## Поставьте результат

Именованный артефакт:

```text
outputs/mlflow_experiment_ledger_exporter.py
```

Standalone запуск:

```bash
uv run --locked python phases/16-tabular-ml/10-mlflow/outputs/mlflow_experiment_ledger_exporter.py \
  --output-root phases/16-tabular-ml/10-mlflow/outputs
```

Если хотите сохранить временный MLflow store для ручного просмотра, передайте отдельный tracking root:

```bash
uv run --locked python phases/16-tabular-ml/10-mlflow/outputs/mlflow_experiment_ledger_exporter.py \
  --tracking-root /tmp/trial-churn-mlruns \
  --output-root phases/16-tabular-ml/10-mlflow/outputs
```

Коммитить сам `mlruns` не нужно. В репозитории остается стабильный exported ledger.

## Упражнения

1. Добавьте required tag `feature_contract_id` и проверьте, что auditor блокирует runs без этого тега.
2. Добавьте artifact `optuna_search_space_audit.csv` к `best_optuna_trial` и расширьте inventory test.
3. Добавьте metric `test_used_for_selection=0` в required metrics для всех runs и объясните, почему это tracking evidence.
4. Сформулируйте, какие поля из `mlflow_tracking_serialized_spec.json` должен использовать финальный stability/package урок.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Experiment | Папка с файлами | Группа MLflow runs с общей задачей и контекстом |
| Run | Только модель-победитель | Один tracked запуск с params, metrics, tags и artifacts |
| Tag | Необязательная подпись | Lineage и governance context, без которого run трудно ревьюить |
| Artifact | Любой красивый файл | Evidence file, который подтверждает метрику, policy или handoff |
| Run id | Удобный ключ для CSV | Случайный MLflow identifier; в committed ledger лучше использовать stable alias |
| Model registry | То же, что tracking | Отдельный lifecycle слой, который не входит в этот урок |

## Дополнительное чтение

- [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/) - прочитайте про experiments, runs, params, metrics, artifacts и local tracking, чтобы связать API с ledger из урока.
- [MLflow Python API](https://mlflow.org/docs/latest/python_api/mlflow.html) - используйте как справочник по `start_run`, `log_params`, `log_metrics`, `set_tags` и `log_artifact`.
- [MLflow Tracking Client](https://mlflow.org/docs/latest/python_api/mlflow.client.html) - посмотрите, как читать runs, artifacts и metric history через `MlflowClient`.
- [MLflow file store migration note](https://mlflow.org/docs/latest/self-hosting/migrate-from-file-store/) - разберите, почему local file store в MLflow 3.x требует явного opt-in и не равен production tracking backend.
