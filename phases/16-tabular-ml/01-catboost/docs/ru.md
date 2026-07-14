# CatBoost как сильный табличный baseline

## Проблема

В фазе 15 вы собрали baseline package для churn-risk задачи: есть problem spec, split
policy, метрики, calibration, leakage audit, error analysis и model card. Теперь хочется
сделать естественный следующий шаг: взять сильную табличную модель и проверить, улучшает
ли она решение.

Опасность в том, что "сильная библиотека" легко ломает дисциплину эксперимента. Можно
переобучиться на маленьком train, поменять split, выбрать модель по test, забыть передать
категориальные признаки как категории или потерять warnings из baseline package. Тогда
CatBoost score выглядит убедительно, но сравнение уже нечестное.

В этом уроке вы обучите CatBoost-кандидат как сильный табличный baseline, но не дадите ему
специальных правил:

- fit только на `train`;
- selection только на `validation`;
- `test` остается final holdout и не участвует в promotion decision;
- `cat_features` передаются явно и проверяются;
- результат сравнивается с phase 15 baseline package, а не заменяет его автоматически.

## Концепция

CatBoost удобен для табличных задач: он умеет работать с категориальными признаками через
native categorical handling и дает sklearn-like интерфейс `fit` / `predict_proba`. Но в
учебном production contract важнее не сам факт использования CatBoost, а границы сравнения.

Минимальный contract сильного кандидата:

1. **Та же ML-постановка.** `problem_id`, target, eligible population, decision budget и
   primary metric не меняются.
2. **Те же split roles.** Train нужен для fit, validation для выбора кандидата, test для
   финальной проверки.
3. **Явные признаки.** Numeric и categorical features перечислены в spec; target, label,
   split и prediction-time поля запрещены как model inputs.
4. **Честный promotion gate.** CatBoost может стать выбранным кандидатом только при
   validation gain по `precision_at_budget`.
5. **Сохранение ограничений.** Warnings из baseline package не исчезают только потому, что
   появилась новая модель.

В tiny-профиле этот урок специально показывает неприятный, но полезный результат:
CatBoost обучается корректно, однако по validation не превосходит baseline. Значит,
артефакт не продвигает его. Это не провал модели, а правильное поведение audit.

## Соберите это

Новый contract лежит в:

```text
phases/16-tabular-ml/data/tiny/catboost_model_spec.json
```

В нем зафиксированы:

- `catboost_baseline_id`;
- `baseline_package_id` и source baseline из фазы 15;
- `fit_split = train`;
- `selection_split = validation`;
- `final_holdout_split = test`;
- CatBoost params: `iterations`, `depth`, `learning_rate`, `random_seed`,
  `allow_writing_files = false`, `thread_count = 1`, `verbose = false`;
- numeric и categorical feature contract;
- output filenames.

Основной артефакт:

```text
phases/16-tabular-ml/01-catboost/outputs/catboost_baseline_trainer.py
```

Он делает пять вещей.

1. Читает phase 15 inputs: `problem_spec.json`, `ml_raw_features.csv`,
   `ml_labels.csv`, `ml_split_manifest.csv`.
2. Читает phase 15 evidence: `ml_baseline_package_report.json` и
   `imbalance_report.json`.
3. Проверяет, что CatBoost spec не меняет problem, split policy и promotion rule.
4. Строит `Pool` с явными `cat_features` и обучает `CatBoostClassifier` только на train.
5. Пишет report, comparison, predictions, training trace и serialized spec.

Ключевой фрагмент в trainer выглядит так:

```python
train_pool = Pool(
    matrix.loc[train_mask],
    frame.loc[train_mask, "target"],
    cat_features=categorical_features,
)
model.fit(train_pool)
all_pool = Pool(matrix, cat_features=categorical_features)
scores = model.predict_proba(all_pool)[:, 1]
```

Обратите внимание: validation и test используются только после fit. Validation участвует в
сравнении, test не участвует в выборе кандидата.

## Используйте это

Запустите пример урока:

```bash
uv run --locked python phases/16-tabular-ml/01-catboost/code/main.py
```

Ожидаемая сводка показывает, что audit валиден, CatBoost обучен, но выбранным остается
phase 15 baseline:

```json
{
  "audit_valid": true,
  "catboost_baseline_id": "trial-churn-catboost-baseline-v0",
  "model_id": "catboost_depth2_native_categories",
  "fit_row_count": 4,
  "selected_model_id": "random_forest_depth2_class_weight_balanced",
  "catboost_validation_precision_at_budget": 0.0,
  "baseline_validation_precision_at_budget": 0.5,
  "test_used_for_selection": false,
  "readiness_status": "ready_for_categorical_feature_lesson"
}
```

После запуска в `outputs/` появляются файлы:

- `catboost_report.json` — общий audit report;
- `catboost_comparison.csv` — сравнение CatBoost и phase 15 baseline;
- `catboost_predictions.csv` — score rows по train, validation и test;
- `catboost_training_trace.csv` — доказательство, какие split что делали;
- `catboost_serialized_spec.json` — переносимый spec без pickle/joblib модели.

CLI можно запустить напрямую:

```bash
uv run --locked python phases/16-tabular-ml/01-catboost/outputs/catboost_baseline_trainer.py \
  --output-dir phases/16-tabular-ml/01-catboost/outputs
```

Если нужно сделать warning строгим условием CI, добавьте:

```bash
uv run --locked python phases/16-tabular-ml/01-catboost/outputs/catboost_baseline_trainer.py \
  --fail-on-warning
```

На tiny-профиле команда завершится кодом `2`, потому что warnings ожидаемы:
маленький train, отсутствие validation gain у CatBoost и перенос предупреждений baseline
package.

## Сломайте это

Попробуйте сломать contract в копии `catboost_model_spec.json`.

Поменяйте selection data на test:

```json
{
  "comparison": {
    "selection_data": "test"
  }
}
```

Audit должен упасть на проверке
`catboost_spec_declares_reproducible_no_test_selection`: test не может выбирать модель.

Добавьте несуществующий categorical feature:

```json
{
  "feature_contract": {
    "categorical_features": ["plan_id", "platform", "country", "plan_name_from_future"]
  }
}
```

Audit должен остановиться до fit на `feature_contract_matches_table`: модель нельзя
обучать, если contract не совпадает с feature table.

Добавьте target column в `cat_features`:

```json
{
  "feature_contract": {
    "categorical_features": ["plan_id", "platform", "country", "churned_14d"]
  }
}
```

Audit снова блокирует fit. Target, label и split columns не могут быть model inputs.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/01-catboost/tests
```

Тесты проверяют:

- валидный CatBoost report и фиксированную версию `catboost==1.2.10`;
- `cat_features` как явные native categorical columns;
- стабильные prediction scores на tiny-профиле;
- `training_trace`: fit на train, selection на validation, test без fit;
- serialized spec без сохранения небезопасного бинарного model artifact;
- блокировку invalid baseline package;
- блокировку selection на test;
- блокировку сломанного feature contract;
- CLI `--fail-on-warning`.

Для полной проверки курса после изменения lesson status используйте общий набор команд:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/render_curriculum.py --check
uv run --locked python scripts/render_outputs.py --check
uv run --locked python scripts/render_site.py --check
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Готовый результат урока — не "CatBoost победил", а проверяемый handoff:

- CatBoost candidate обучен воспроизводимо;
- categorical features переданы явно;
- comparison показывает, что phase 15 baseline остается выбранным по validation;
- test не использован для selection;
- warnings сохранены;
- следующий урок может углубиться в categorical features без leakage.

Статус `ready_for_categorical_feature_lesson` означает: contract готов для 16/02, но
production claim по-прежнему запрещен. Tiny-data нужен для проверки поведения артефакта,
а не для реального вывода о качестве модели.

## Упражнения

1. Увеличьте `iterations` в копии spec и проверьте, меняется ли validation
   `precision_at_budget`. Объясните, почему одного улучшенного train score недостаточно.
2. Уберите `acquisition_channel` из `cat_features` и посмотрите, как меняется audit. Чем
   опасна неявная обработка категории как обычной строки или object column?
3. Добавьте в comparison еще один baseline row из phase 15 и продумайте tie-break rule:
   какая метрика должна идти после `precision_at_budget`?
4. Сформулируйте, какие дополнительные данные нужны, чтобы warning
   `tiny_catboost_training_sample_expected` перестал быть ожидаемым.

## Ключевые термины

- **CatBoostClassifier** — классификатор CatBoost с sklearn-like API.
- **Pool** — контейнер CatBoost для features, target и metadata, включая `cat_features`.
- **cat_features** — список категориальных колонок, которые CatBoost должен обрабатывать
  как категории.
- **promotion gate** — правило, по которому candidate model может заменить текущий
  baseline.
- **no-test-selection audit** — проверка, что test не использовался для выбора модели,
  threshold, hyperparameters или best iteration.
- **training trace** — машинно читаемая запись, какие split участвовали в fit, selection и
  final evaluation.

## Дополнительное чтение

- [CatBoostClassifier](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier) — официальный reference по параметрам, атрибутам и методам классификатора.
- [CatBoost Pool](https://catboost.ai/docs/en/concepts/python-reference_pool) — как CatBoost принимает features, label и `cat_features` в воспроизводимый training object.
- [CatBoost fit](https://catboost.ai/docs/en/concepts/python-reference_catboost_fit) — параметры `fit`, включая eval sets и границы будущего урока про early stopping.
- [scikit-learn classification metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#classification-metrics) — справочник по метрикам, которые используются в comparison table.
