# Optuna и честный подбор параметров

> Подбор параметров честен только тогда, когда search space, бюджет trial'ов, seed и objective split объявлены до запуска, а test не участвует в выборе лучшего trial.

**Тип:** Case  
**Треки:** ML, Delivery, Decision  
**Пререквизиты:** `16-tabular-ml/08-cost-sensitive-decisions`  
**Время:** ~90 минут  
**Результат:** Optuna tuning auditor, который запускает fixed-budget study, сохраняет полный trial ledger, проверяет no-test-objective boundary и передает tuned CatBoost candidate в MLflow-урок.

## Цели обучения

- Зафиксировать search space, direction, objective metric, trial budget и seed до запуска study.
- Запустить Optuna `GridSampler` так, чтобы все trial'ы были воспроизводимы.
- Считать objective только на validation split и не использовать final holdout для выбора лучшего trial.
- Сохранить полный trial ledger, а не только best params.
- Сравнить лучший trial с source CatBoost и cost-sensitive baseline без подмены бизнес-вывода.

## Проблема

В прошлом уроке CatBoost-кандидат не прошел decision gate. Его top-k cost на validation равен `7`, baseline top-k cost равен `1`, а true positive `S006` выпадает из action set. Но это еще не конец исследования: возможно, у CatBoost были неудачные параметры.

Опасный путь выглядит так:

```text
1. Перебирать параметры до тех пор, пока test станет красивым.
2. Записать только best params.
3. Забыть, сколько было попыток и какие варианты не сработали.
4. Назвать результат production-ready, хотя бизнес-cost все еще хуже baseline.
```

Этот урок строит другой путь: маленький, но честный Optuna-аудит. Мы заранее объявляем grid из шести trial'ов, оптимизируем `validation_logloss`, сохраняем каждую попытку и отдельно показываем, что улучшение logloss не спасает cost-sensitive gate.

## Концепция

Hyperparameter tuning - это эксперимент с собственным риском утечки. Даже если модель не видит `target` test напрямую, test становится частью обучения решений, если вы смотрите на него после каждой попытки и выбираете параметры по лучшему test-результату.

Поэтому tuning policy фиксирует четыре границы:

| Граница | В этом уроке | Зачем нужна |
|---|---|---|
| Fit data | `train` | Только эти строки используются для fit модели |
| Objective data | `validation` | Только здесь Optuna сравнивает trial'ы |
| Final holdout | `test` | Можно скорить после выбора best trial, нельзя использовать для selection |
| Trial budget | `6` | Нельзя “еще чуть-чуть поискать”, когда результат не нравится |

Search space специально маленький:

```json
{
  "depth": [1, 2],
  "learning_rate": [0.05, 0.2, 0.4]
}
```

Это не production tuning. Это учебный audit pattern: на маленьком fixture видно, где проходят границы, какие файлы нужно сохранить и почему “best trial” не равен “готовая бизнес-модель”.

### Что оптимизирует Optuna

Objective возвращает `validation_logloss`:

```text
direction = minimize
objective_metric = validation_logloss
```

Cost-sensitive метрики считаются рядом, но не становятся objective. Это важное разделение:

- `validation_logloss` отвечает на вопрос “улучшилась ли вероятностная модель на validation?”;
- `validation_top_k_total_error_cost` отвечает на вопрос “улучшилось ли действие при бюджете двух offers?”;
- `test` отвечает только на вопрос “как выглядит уже выбранный кандидат на финальном holdout?”.

В результате лучший trial слегка улучшает logloss:

```text
source CatBoost validation_logloss = 0.698394
best Optuna trial validation_logloss = 0.696531
```

Но business gate остается плохим:

```text
best Optuna trial top-k cost = 7
calibrated baseline top-k cost = 1
```

## Соберите это

### Шаг 1. Объявите tuning policy

Policy должна жить рядом с данными, а не в голове исследователя:

```json
{
  "study": {
    "study_name": "trial_churn_catboost_fixed_budget_v0",
    "direction": "minimize",
    "objective_metric": "validation_logloss",
    "n_trials": 6,
    "sampler": {"name": "GridSampler", "seed": 1609}
  },
  "objective_policy": {
    "fit_data": "train",
    "selection_data": "validation",
    "forbid_objective_on_test": true
  }
}
```

Evaluator проверяет, что:

- `selection_data` совпадает с validation split;
- `final_holdout_split` не совпадает с objective split;
- размер grid равен `n_trials`;
- seed CatBoost совпадает с seed sampler;
- feature contract совпадает с предыдущим CatBoost spec.

### Шаг 2. Соберите ledger без Optuna

До библиотеки полезно представить ledger как обычную таблицу:

| trial | depth | learning_rate | objective_value | selected_ids | is_best |
|---:|---:|---:|---:|---|---|
| 0 | 1 | 0.05 | 0.698842 | `S007,S005` | false |
| 1 | 1 | 0.2 | 0.717590 | `S007,S005` | false |
| 2 | 2 | 0.2 | 0.707280 | `S007,S005` | false |
| 3 | 1 | 0.4 | 0.746454 | `S007,S005` | false |
| 4 | 2 | 0.05 | 0.696531 | `S007,S005` | true |
| 5 | 2 | 0.4 | 0.723010 | `S007,S005` | false |

Это главный артефакт tuning-аудита. Если у вас есть только `best_params`, вы не знаете:

- сколько попыток было сделано;
- какие параметры проиграли;
- был ли search space объявлен заранее;
- мог ли кто-то руками остановить поиск на удобном результате.

### Шаг 3. Проверьте no-test boundary

Для каждого split auditor пишет роль:

| split | role |
|---|---|
| train | fit |
| validation | objective и best trial selection |
| test | final holdout after selection |

Test-прогнозы в этом уроке создаются, но у них стоят флаги:

```text
used_for_objective = False
test_used_for_best_trial_selection = False
used_for_final_holdout_reporting = True
```

Такой отчет можно читать после выбора best trial. По нему нельзя возвращаться назад и менять search space.

### Шаг 4. Сформулируйте честный outcome

Лучший trial:

```text
trial_number = 4
depth = 2
learning_rate = 0.05
validation_logloss = 0.696531
```

Но selected top-k rows не изменились:

```text
S007,S005
```

А false negative все еще:

```text
S006
```

Поэтому корректный статус:

```text
decision_status = tuned_candidate_ready_for_mlflow_tracking
readiness_status = ready_for_mlflow_lesson
```

Не “promote model”, а “можно переходить к tracking и packaging, сохранив ограничения”.

## Используйте это

Запустите урок из корня репозитория:

```bash
uv run --locked python phases/16-tabular-ml/09-optuna/code/main.py
```

Ожидаемый summary:

```json
{
  "audit_valid": true,
  "optuna_tuning_audit_id": "trial-churn-optuna-tuning-audit-v0",
  "study_name": "trial_churn_catboost_fixed_budget_v0",
  "n_trials": 6,
  "objective_split": "validation",
  "test_used_for_objective": false,
  "source_validation_logloss": 0.698394,
  "best_trial_number": 4,
  "best_validation_logloss": 0.696531,
  "best_depth": 2,
  "best_learning_rate": 0.05,
  "best_trial_validation_top_k_cost": 7.0,
  "cost_gate_still_fails_vs_baseline": true,
  "decision_status": "tuned_candidate_ready_for_mlflow_tracking",
  "readiness_status": "ready_for_mlflow_lesson"
}
```

Основные файлы:

- `outputs/optuna_tuning_report.json` - полный audit report с checks, warnings и summary.
- `outputs/optuna_trial_ledger.csv` - все trial'ы, параметры, objective value и validation cost.
- `outputs/optuna_best_trial_trace.csv` - сравнение source CatBoost, best Optuna trial и calibrated baseline gate.
- `outputs/optuna_tuned_predictions.csv` - train, validation и test scores с флагами использования.
- `outputs/optuna_search_space_audit.csv` - объявленный search space и размер grid.
- `outputs/optuna_objective_audit.csv` - роли train/validation/test.
- `outputs/optuna_tuning_serialized_spec.json` - handoff в следующий MLflow-урок.

## Сломайте это

### Ошибка 1. Перенести objective на test

Измените policy:

```json
"objective_policy": {
  "selection_data": "test"
}
```

Evaluator вернет:

```text
valid = false
blocking_errors = objective_uses_validation_and_excludes_test
readiness_status = blocked_before_optuna_tuning
```

Важно: auditor блокирует запуск study до обучения trial'ов. Так дешевле и чище, чем потом объяснять, почему test уже испорчен.

### Ошибка 2. Сохранить только best params

Если удалить `optuna_trial_ledger.csv`, следующий ревьюер не увидит полный эксперимент. Best params без ledger не отвечают на вопрос, был ли tuning fixed-budget и reproducible.

### Ошибка 3. Объявить business win по logloss

Лучший trial улучшил validation logloss, но не улучшил top-k action set. В lesson fixture это ожидаемый warning:

```text
best_trial_logloss_improves_but_cost_gate_still_fails
```

Нельзя превращать метрику модели в claim про бизнес-решение без decision layer.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/09-optuna/tests
```

Что проверяют тесты:

- summary фиксирует Optuna `4.9.0`, `GridSampler`, seed `1609` и `6` complete trials;
- objective split равен validation, test не используется для objective;
- trial ledger содержит все шесть попыток и ровно один best trial;
- search space audit показывает grid `2 x 3 = 6`;
- objective audit показывает train/validation/test роли;
- prediction rows для test помечены только как final holdout reporting;
- best trial trace сравнивает source, tuned candidate и baseline;
- policy с `selection_data=test` становится blocking error.

## Поставьте результат

Именованный артефакт:

```text
outputs/optuna_tuning_auditor.py
```

Standalone запуск:

```bash
uv run --locked python phases/16-tabular-ml/09-optuna/outputs/optuna_tuning_auditor.py \
  --output-root phases/16-tabular-ml/09-optuna/outputs
```

Артефакт можно переиспользовать как pre-MLflow audit step:

1. Подайте policy с fixed search space, metric direction, sampler seed и budget.
2. Подайте upstream CatBoost spec и decision report.
3. Запустите auditor и сохраните все CSV/JSON outputs.
4. Передавайте в MLflow только serialized spec с полным trial ledger рядом.

## Упражнения

1. Уменьшите search space до одного `learning_rate` и объясните, почему check `study_declares_fixed_budget_seed_and_grid` должен измениться.
2. Поменяйте objective metric в policy на `validation_auc` и перечислите, какие части evaluator нужно переписать.
3. Добавьте в search space `l2_leaf_reg` и расширьте тесты так, чтобы grid size проверялся автоматически.
4. Сформулируйте MLflow tags, которые должны попасть в следующий урок из `optuna_tuning_serialized_spec.json`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Search space | Можно менять во время tuning | Набор параметров и значений, объявленный до study |
| Trial budget | Просто технический лимит | Часть методологии, защищающая от бесконечного перебора до удобного результата |
| Objective split | Любой split, где есть labels | Split, по которому выбирают лучший trial; в этом уроке только validation |
| Final holdout | Еще один validation | Закрытая выборка для reporting после выбора модели |
| Trial ledger | Лог для отладки | Основной audit artifact tuning-эксперимента |
| Best trial | Готовая production-модель | Лучшая попытка по objective, которую еще нужно проверить по decision, tracking и packaging |

## Дополнительное чтение

- [Optuna documentation: Key Features](https://optuna.readthedocs.io/en/stable/) - посмотрите базовую модель `study`, `trial`, sampler и pruning, чтобы связать API с ledger из урока.
- [Optuna API: `create_study`](https://optuna.readthedocs.io/en/stable/reference/generated/optuna.create_study.html) - проверьте параметры `direction`, `sampler`, `pruner` и `study_name`.
- [Optuna API: `GridSampler`](https://optuna.readthedocs.io/en/stable/reference/samplers/generated/optuna.samplers.GridSampler.html) - разберите, почему маленький declared grid удобен для воспроизводимого учебного аудита.
- [CatBoost documentation: parameter tuning](https://catboost.ai/docs/en/concepts/parameter-tuning) - используйте как справочник по тому, какие параметры CatBoost имеет смысл выносить в search space.
