# Early stopping и iteration budget

## Проблема

В `16/01` CatBoost обучился с фиксированными `iterations=20`, а `16/02` подтвердил, что
категориальные признаки можно передавать в модель без явной leakage. Следующая типичная
ошибка появляется в training control: команда увеличивает `iterations`, включает early
stopping и начинает считать, что библиотека сама защитила модель от переобучения.

Early stopping не является магией. Это часть evaluation protocol:

- `eval_set` должен состоять только из validation rows;
- `best_iteration` выбирается по заранее объявленной метрике;
- test split не участвует в overfitting detector;
- `tree_count` после `use_best_model=True` должен быть зафиксирован;
- validation curve нужна как evidence, а не только итоговый score.

В этом уроке вы превращаете early stopping в проверяемый артефакт: `eval_set` lineage,
validation curve, best iteration и tree-count report.

## Концепция

Iteration budget отвечает на вопрос: "сколько деревьев модели разрешено построить".
Early stopping отвечает на другой вопрос: "на какой итерации validation metric перестала
улучшаться по объявленному правилу".

Важно не смешивать роли split:

| Split | Роль в уроке | Что запрещено |
|---|---|---|
| `train` | fit pool, обновление деревьев | выбирать best iteration по train score |
| `validation` | `eval_set` и overfitting detector | использовать как final holdout |
| `test` | final once-only evaluation | попадать в `eval_set`, tuning или patience window |

Если test попал в `eval_set`, это такая же test-driven selection, как ручной выбор модели
по test score. Даже если CatBoost делает это внутри `fit`, методологическая ошибка остается.

В tiny-профиле planned budget равен `80`, overfitting detector `Iter` с `od_wait=3`.
Validation Logloss ухудшается сразу после первой итерации:

```text
iteration 0: validation_logloss = 0.698394
iteration 1: validation_logloss = 0.703791
iteration 2: validation_logloss = 0.709329
iteration 3: validation_logloss = 0.715000
```

Поэтому `best_iteration=0`, а `tree_count=1`. Это учебный warning: на трех validation
rows нельзя делать сильный вывод о реальном оптимальном числе деревьев, но сам протокол
виден и проверяем.

## Соберите это

Новый policy spec:

```text
phases/16-tabular-ml/data/tiny/early_stopping_policy_spec.json
```

Он фиксирует:

- связь с `catboost_baseline_id` и categorical audit из `16/02`;
- `fit_split=train`, `eval_split=validation`, `final_holdout_split=test`;
- planned budget `iterations=80`;
- `od_type=Iter`, `od_wait=3`;
- `use_best_model=true`;
- `eval_metric=Logloss`;
- запрет test split в `eval_set`.

Минимальный механизм проверки выглядит так:

```python
train_pool = Pool(X_train, y_train, cat_features=cat_features)
validation_pool = Pool(X_valid, y_valid, cat_features=cat_features)

model.fit(train_pool, eval_set=validation_pool)
best_iteration = model.get_best_iteration()
tree_count = model.tree_count_
```

Но production-часть урока делает больше: она записывает lineage split, проверяет, что
test не участвовал в best-iteration selection, сохраняет validation curve и сравнивает
planned iterations с фактическим `tree_count`.

Основной артефакт:

```text
phases/16-tabular-ml/03-early-stopping/outputs/early_stopping_auditor.py
```

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/16-tabular-ml/03-early-stopping/code/main.py
```

Ожидаемая сводка:

```json
{
  "audit_valid": true,
  "early_stopping_audit_id": "trial-churn-early-stopping-audit-v0",
  "early_stopping_model_id": "catboost_depth2_native_categories_es_logloss",
  "planned_iterations": 80,
  "trained_iteration_count": 4,
  "best_iteration": 0,
  "tree_count": 1,
  "stopped_before_budget": true,
  "warning_count": 3,
  "readiness_status": "ready_for_feature_importance_lesson"
}
```

После запуска появляются пять файлов:

- `early_stopping_report.json` — общий отчет, checks, warnings и summary;
- `eval_set_lineage.csv` — роли train/validation/test в fit и early stopping;
- `validation_curve.csv` — learn/validation Logloss по итерациям и best marker;
- `tree_count_report.csv` — planned iterations, trained iterations, best iteration и
  финальный `tree_count`;
- `early_stopping_serialized_spec.json` — handoff для урока `16/04`.

В текущем fixture auditor валиден, но предупреждает:

- train pool содержит только 4 rows;
- eval set содержит только 3 rows;
- best iteration равен `0`, что нормально для tiny-примера, но слишком хрупко для
  production claim.

## Сломайте это

Поменяйте в `early_stopping_policy_spec.json`:

```json
"eval_split": "test"
```

Audit должен заблокировать policy: test split нельзя использовать как `eval_set`.

Теперь выставьте:

```json
"use_best_model": false
```

Даже если CatBoost сможет обучиться, контракт урока нарушен: `tree_count` больше не
связан с best iteration так, как ожидает downstream interpretation package.

Наконец удалите `od_type`. Без overfitting detector planned budget превращается в обычное
число деревьев, а урок не сможет доказать, что остановка была частью protocol.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/03-early-stopping/tests
```

Тесты проверяют:

- handoff от `16/01` и `16/02`;
- validation-only `eval_set`;
- запрет test split в best-iteration selection;
- запись `best_iteration=0` и `tree_count=1`;
- validation curve с patience window `od_wait=3`;
- tree-count reduction относительно budget `80` и baseline `20`;
- блокировку policy без `use_best_model`;
- блокировку policy без overfitting detector;
- структурированный failure при отсутствующем policy file;
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

Готовый результат урока — early stopping audit package. Его можно передать в `16/04`,
где начнется built-in feature importance:

- модель и категории совпадают с предыдущими уроками;
- CatBoost обучен с фиксированным random seed и validation-only `eval_set`;
- test split остается невидимым для best iteration;
- validation curve показывает, почему выбран `best_iteration`;
- `tree_count_report.csv` фиксирует, сколько деревьев реально осталось в модели;
- `ready_for_feature_importance_lesson` означает, что следующий урок может считать
  важность признаков на известной training-control версии модели.

## Упражнения

1. Увеличьте `od_wait` до `5` и объясните, почему `trained_iteration_count` изменится, а
   `tree_count` при `use_best_model=true` может остаться прежним.
2. Поменяйте `eval_metric` на другую метрику, поддерживаемую CatBoost, и запишите, какие
   поля spec и curve должны измениться вместе.
3. Измените validation rows так, чтобы validation split содержал один класс, и объясните,
   почему такой `eval_set` опасен для early stopping.
4. Сравните `tree_count_report.csv` с `catboost_training_trace.csv` из `16/01`: чем
   фиксированный budget отличается от validation-driven tree count?

## Ключевые термины

- **Iteration budget** — заранее объявленный максимум деревьев или boosting iterations.
- **Early stopping** — остановка обучения по validation metric после patience window без
  улучшения.
- **Eval set** — данные, которые не обучают деревья, но участвуют в выборе best iteration.
- **Best iteration** — итерация с лучшим значением объявленной validation metric.
- **Tree count** — фактическое число деревьев в модели после `use_best_model`.
- **Patience window** — количество итераций без улучшения, после которого detector
  останавливает обучение.

## Дополнительное чтение

- [CatBoost fit](https://catboost.ai/docs/en/concepts/python-reference_catboost_fit) — параметры `eval_set`, `use_best_model` и поведение `fit` для validation-driven обучения.
- [CatBoost overfitting detector](https://catboost.ai/docs/en/features/overfitting-detector-desc) — официальный раздел про `od_type`, `od_wait` и правила остановки.
- [CatBoostClassifier](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier) — атрибуты и методы модели, включая `best_iteration_`, `tree_count_` и `get_evals_result`.
- [scikit-learn common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html) — напоминание, почему любые решения по test split создают leakage даже вне sklearn.
