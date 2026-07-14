# Встроенная важность признаков

## Проблема

После `16/03` у вас есть CatBoost model run с validation-only early stopping:
`best_iteration=0`, `tree_count=1`, test split не участвовал в выборе итерации. Теперь
хочется открыть `feature_importances_`, отсортировать признаки и сказать бизнесу:
"пользователи уходят из-за platform".

Это опасная фраза. Built-in importance отвечает не на вопрос "почему пользователь ушел",
а на вопрос "как этот обученный CatBoost использовал признаки внутри своей структуры или
validation diagnostic". На tiny-модели с одним деревом результат особенно хрупкий:
`PredictionValuesChange` дает `platform = 100`, а остальные признаки получают `0`.

В этом уроке вы построите reporter, который считает встроенную важность, но сразу
подписывает метод, проверяет feature names и добавляет interpretation warnings.

## Концепция

CatBoost умеет считать несколько типов важности. В этом уроке нужны два:

| Метод | Что показывает | Главная ловушка |
|---|---|---|
| `PredictionValuesChange` | насколько в среднем меняется prediction value при использовании признака в деревьях | model-internal diagnostic, чувствителен к структуре конкретной модели |
| `LossFunctionChange` | как меняется loss на заданных данных, если убрать признак | зависит от выбранного eval data и может быть отрицательным |

Оба метода полезны, но они не доказывают причинность. Если `platform` top-1, это значит:
в этой tiny-модели CatBoost построил split, где `platform` объясняет изменение model
score. Это не значит, что изменение платформы изменит churn.

Отдельно нужны три audit layer:

1. **Feature-name audit.** Importance vector должен совпадать с training pool order:
   сначала numeric features, затем categorical features.
2. **Method labels.** Каждая строка importance должна хранить `method`,
   `method_label`, `data_split` и `interpretation_scope`.
3. **Warning ledger.** High-cardinality categories, correlated features, tiny tree count
   и single-feature dominance должны быть видимы рядом с числами.

## Соберите это

Новый policy spec:

```text
phases/16-tabular-ml/data/tiny/built_in_importance_policy_spec.json
```

Он фиксирует:

- связь с early-stopping handoff из `16/03`;
- два метода: `PredictionValuesChange` и `LossFunctionChange`;
- точный порядок 10 признаков;
- non-causal interpretation policy;
- warning thresholds для high-cardinality, correlated features, tiny tree count и
  dominant importance.

Минимальный механизм:

```python
pvc = model.get_feature_importance(type="PredictionValuesChange")
loss = model.get_feature_importance(data=validation_pool, type="LossFunctionChange")
```

Но production-часть урока не останавливается на массиве чисел. Она соединяет значения с
feature names, добавляет method labels, маркирует top feature внутри каждого метода и
пишет warnings.

Основной артефакт:

```text
phases/16-tabular-ml/04-feature-importance/outputs/built_in_importance_reporter.py
```

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/16-tabular-ml/04-feature-importance/code/main.py
```

Ожидаемая сводка:

```json
{
  "audit_valid": true,
  "built_in_importance_audit_id": "trial-churn-built-in-importance-audit-v0",
  "early_stopping_model_id": "catboost_depth2_native_categories_es_logloss",
  "method_count": 2,
  "feature_count": 10,
  "importance_row_count": 20,
  "top_prediction_values_change_feature": "platform",
  "top_loss_function_change_feature": "platform",
  "warning_count": 4,
  "readiness_status": "ready_for_permutation_importance_lesson"
}
```

После запуска появляются пять файлов:

- `built_in_importance_report.json` - общий отчет, checks, summary и warnings;
- `built_in_importance.csv` - 20 строк: 2 метода на 10 признаков;
- `feature_name_audit.csv` - порядок признаков, роли numeric/categorical и risk flags;
- `importance_warning_ledger.csv` - high-cardinality, correlated-feature, tiny-tree и
  dominance warnings;
- `built_in_importance_serialized_spec.json` - handoff для `16/05`.

В текущем tiny fixture:

- `PredictionValuesChange` присваивает `platform` значение `100`;
- `LossFunctionChange` для `platform` равен `-0.005247` на validation;
- `acquisition_channel` отмечен как high-cardinality feature, хотя его importance сейчас
  `0`;
- пять пар numeric features имеют train correlation `>= 0.8`;
- модель содержит одно дерево, поэтому strong interpretation claim запрещен.

## Сломайте это

Удалите из `importance_methods` метод `LossFunctionChange`. Audit должен заблокировать
policy: один built-in метод не дает нужного контраста между model-structure и
validation-loss diagnostic.

Поменяйте порядок `expected_feature_order`, например поставьте `platform` первым. Audit
должен упасть до расчета интерпретации: importance без надежной привязки к feature names
опаснее, чем отсутствие importance.

Теперь измените interpretation claim на:

```json
"platform causes churn"
```

Policy должна быть заблокирована. Built-in importance может быть входом в расследование,
но не является causal claim.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/04-feature-importance/tests
```

Тесты проверяют:

- handoff от `16/03`;
- два labeled метода CatBoost importance;
- 20 строк importance для 10 признаков;
- `platform` как top feature в обоих built-in методах;
- отрицательный `LossFunctionChange` как допустимый diagnostic value;
- exact feature-name order;
- high-cardinality warning для `acquisition_channel`;
- correlated-feature warnings;
- tiny `tree_count=1` warning;
- блокировку positive causal claim;
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

Готовый результат урока - built-in importance report. Его можно передать в `16/05`, где
появится permutation importance:

- модель совпадает с early-stopping run из `16/03`;
- feature names совпадают с training pool;
- built-in methods явно подписаны;
- high-cardinality и correlated-feature risks не скрыты;
- report не содержит positive causal claim;
- `ready_for_permutation_importance_lesson` означает, что следующий урок может проверить,
  сохраняется ли importance на held-out scoring при перестановке признаков.

## Упражнения

1. Измените `dominant_prediction_values_change_threshold` на `99` и объясните, почему
   warning не меняет readiness, но меняет тон интерпретации.
2. Уберите `acquisition_channel` из categorical features и проверьте, какие строки
   feature-name audit и warning ledger исчезнут.
3. Повторите расчет без `use_best_model` в upstream early-stopping spec и объясните, почему
   importance уже относится к другой версии модели.
4. Сравните `PredictionValuesChange` и `LossFunctionChange`: почему один метод дает
   `100`, а второй отрицательное число?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Built-in importance | "Это причина поведения пользователя" | Diagnostic того, как конкретная модель использовала признаки |
| `PredictionValuesChange` | "Чем больше, тем важнее для бизнеса" | Model-internal оценка изменения prediction value в структуре деревьев |
| `LossFunctionChange` | "Всегда положительная польза признака" | Изменение loss на выбранном data split; значение может быть отрицательным |
| Feature-name audit | "Порядок признаков очевиден" | Проверка, что vector importance сопоставлен с правильными feature names |
| Correlated-feature warning | "Нулевая importance значит признак бесполезен" | Коррелированные признаки могут делить или маскировать importance друг друга |

## Дополнительное чтение

- [CatBoost feature importance](https://catboost.ai/docs/en/concepts/fstr) - типы `PredictionValuesChange` и `LossFunctionChange`, смысл формул и ограничения.
- [CatBoostClassifier.get_feature_importance](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier_get_feature_importance) - параметры `data`, `type`, `prettified` и формат результата.
- [CatBoostClassifier](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier) - модельный API, из которого берутся feature names, fitted model и diagnostic methods.
- [scikit-learn permutation importance](https://scikit-learn.org/stable/modules/permutation_importance.html) - следующий шаг: model-agnostic проверка importance на held-out scoring.
