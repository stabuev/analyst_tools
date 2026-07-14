# Permutation importance

## Проблема

В `16/04` CatBoost built-in importance показал яркую, но опасную картинку:
`PredictionValuesChange` дал `platform = 100`, остальные признаки получили `0`, а
`LossFunctionChange` для той же `platform` оказался отрицательным. Если остановиться на
этом месте, легко рассказать бизнесу слишком сильную историю: "platform главный драйвер
churn".

Permutation importance задает другой вопрос: что случится с заранее объявленным score,
если на heldout data перемешать один столбец признака и оставить остальные как есть. Это
model-agnostic diagnostic: он не зависит от внутренней формулы CatBoost importance, но
зависит от качества модели, выбранного split, scoring и случайных перестановок.

В этом уроке вы построите evaluator, который считает permutation importance через
`sklearn.inspection.permutation_importance`, сохраняет repeat-level deltas и сразу
показывает warnings для плохой модели, маленькой validation, high-cardinality и
коррелированных признаков.

## Концепция

Permutation importance работает так:

1. Посчитать baseline score модели на heldout split.
2. Для каждого признака несколько раз перемешать только этот столбец.
3. После каждого shuffle снова посчитать score.
4. Записать разницу `baseline_score - permuted_score`.

В уроке scoring объявлен как `neg_log_loss`, поэтому importance удобно читать как
`log_loss increase when feature is permuted`:

```text
importance_delta = permuted_log_loss - baseline_log_loss
```

Положительная delta значит, что shuffle ухудшил log loss. Нулевая delta значит, что
модель не изменила score на этом split. Отрицательная delta значит, что после shuffle
log loss стал лучше. Это не делает признак "анти-причиной"; это говорит, что на данном
heldout split strong positive importance claim не поддержан.

Нужны четыре защитных слоя:

| Слой | Что проверяет | Почему важно |
|---|---|---|
| Split boundary | `heldout_split=validation`, `final_holdout_split=test` не используется | иначе interpretation подглядывает в финальную проверку |
| Scoring contract | `neg_log_loss`, `predict_proba`, labels `[0, 1]` | ranking признаков зависит от metric |
| Repeat ledger | 7 shuffle repeats на каждый признак | mean без разброса выглядит слишком уверенно |
| Warning ledger | high-cardinality, correlated features, tiny heldout, weak score | permutation importance легко переинтерпретировать |

Коррелированные признаки особенно важны. Если два столбца несут похожий сигнал, модель
может сохранить score через proxy, когда один столбец перемешан. Тогда individual
importance будет ниже, чем importance группы признаков.

## Соберите это

Новый policy spec:

```text
phases/16-tabular-ml/data/tiny/permutation_importance_policy_spec.json
```

Он фиксирует:

- handoff от `16/04` built-in importance;
- `heldout_split=validation` и `final_holdout_split=test`;
- scoring `neg_log_loss` через `predict_proba`;
- `n_repeats=7`, `random_state=1605`, `max_samples=1.0`;
- точный порядок 10 признаков;
- non-causal interpretation policy;
- warning thresholds для tiny heldout, poor baseline log loss, high-cardinality и
  correlated features.

Минимальный механизм:

```python
from sklearn.inspection import permutation_importance
from sklearn.metrics import log_loss


def neg_log_loss_scorer(estimator, X, y):
    probabilities = estimator.predict_proba(X)[:, 1]
    return -log_loss(y, probabilities, labels=[0, 1])


result = permutation_importance(
    model,
    X_validation,
    y_validation,
    scoring=neg_log_loss_scorer,
    n_repeats=7,
    random_state=1605,
)
```

Production-артефакт не ограничивается `result.importances_mean`. Он пишет:

- mean/std и `mean +/- 2*std` для каждого признака;
- все 70 repeat deltas;
- baseline score и permuted score по каждому repeat;
- warnings, которые не блокируют readiness, но блокируют сильный interpretation claim.

Основной артефакт:

```text
phases/16-tabular-ml/05-permutation-importance/outputs/permutation_importance_evaluator.py
```

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/16-tabular-ml/05-permutation-importance/code/main.py
```

Ожидаемая сводка:

```json
{
  "audit_valid": true,
  "permutation_importance_audit_id": "trial-churn-permutation-importance-audit-v0",
  "early_stopping_model_id": "catboost_depth2_native_categories_es_logloss",
  "heldout_split": "validation",
  "baseline_log_loss": 0.698394,
  "repeat_count": 7,
  "feature_count": 10,
  "importance_row_count": 10,
  "repeat_row_count": 70,
  "largest_absolute_mean_delta_feature": "platform",
  "warning_count": 5,
  "readiness_status": "ready_for_shap_lesson"
}
```

После запуска появляются пять файлов:

- `permutation_importance_report.json` - общий отчет, checks, summary и warnings;
- `permutation_importance.csv` - 10 строк feature-level mean/std/uncertainty;
- `permutation_importance_repeats.csv` - 70 строк: 10 признаков на 7 повторов;
- `permutation_warning_ledger.csv` - high-cardinality, correlation, tiny sample, weak
  score и no-positive-signal warnings;
- `permutation_importance_serialized_spec.json` - handoff для `16/06`.

В текущем tiny fixture:

- validation содержит только `S005`, `S006`, `S007`;
- test rows `S009`-`S013` не используются;
- baseline validation log loss равен `0.698394`;
- `platform` имеет mean delta `-0.011722`;
- 4 из 7 shuffle repeats для `platform` улучшают log loss на `0.020513`;
- ни один признак не имеет `mean - 2*std > 0`.

Это отличный учебный результат: built-in importance подсветил `platform`, а permutation
importance на heldout scoring не поддержал сильный положительный claim. Следующий шаг -
сравнить это с SHAP и не скрывать disagreement.

## Сломайте это

Поставьте в policy:

```json
"heldout_split": "test"
```

Audit должен заблокировать расчет. Test split остается final once-only evaluation, а не
местом для выбора интерпретационной истории.

Теперь уменьшите repeats:

```json
"n_repeats": 1
```

Policy должна упасть: один shuffle не дает repeat variance и не позволяет построить
uncertainty band.

Измените claim на:

```json
"platform causes churn and proves retention effect"
```

Evaluator должен заблокировать policy. Permutation importance объясняет поведение
модели на выбранном score, а не причинный эффект платформы или удерживающего оффера.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/05-permutation-importance/tests
```

Тесты проверяют:

- handoff от `16/04`;
- validation-only heldout scoring без test rows;
- declared `neg_log_loss` scoring;
- 10 feature-level rows и 70 repeat rows;
- отрицательную mean delta для `platform`;
- uncertainty band `mean +/- 2*std`;
- high-cardinality warning для `acquisition_channel`;
- correlated-feature warnings;
- tiny heldout и weak-score warnings;
- блокировку `heldout_split=test`;
- блокировку `n_repeats < 2`;
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

Готовый результат урока - permutation importance evaluator. Его можно передать в
`16/06`, потому что:

- модель совпадает с early-stopping run из `16/03`;
- built-in importance handoff из `16/04` валиден;
- validation heldout split явно отделен от final test;
- scoring, repeats и random seed зафиксированы;
- repeat variance сохранена отдельным CSV;
- warnings видны рядом с числами;
- report не содержит positive causal claim;
- `ready_for_shap_lesson` означает, что следующий урок может сравнить global/local SHAP
  с built-in и permutation signals.

## Упражнения

1. Увеличьте `n_repeats` до `21` и сравните `std_importance` для `platform`.
2. Поменяйте scoring на accuracy в копии policy и объясните, почему feature ranking уже
   отвечает на другой вопрос.
3. Исключите `platform` из feature order в копии spec и проверьте, где сломается handoff.
4. Сгруппируйте коррелированные numeric features и подумайте, какой group permutation
   check нужен для более честной интерпретации.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Permutation importance | "Это универсальная важность признака" | Изменение выбранного score после shuffle одного признака на конкретном data split |
| Heldout scoring | "Можно считать где угодно" | Score должен считаться на заранее объявленном split, который не подгонял модель под вывод |
| Repeat variance | "Mean достаточно" | Разброс shuffle deltas показывает стабильность или хрупкость importance |
| Negative delta | "Признак вреден для бизнеса" | На этом split shuffle улучшил metric; это diagnostic warning, не бизнес-причина |
| Correlated-feature masking | "Нулевая importance значит нет сигнала" | Коррелированный proxy может сохранить score после shuffle одного признака |

## Дополнительное чтение

- [scikit-learn: Permutation feature importance](https://scikit-learn.org/stable/modules/permutation_importance.html) - user guide с предупреждениями про плохие модели, correlated features и отличие от impurity-based importance.
- [sklearn.inspection.permutation_importance](https://scikit-learn.org/stable/modules/generated/sklearn.inspection.permutation_importance.html) - параметры `scoring`, `n_repeats`, `random_state`, `max_samples` и формат `importances_mean/std`.
- [scikit-learn: Model evaluation scoring](https://scikit-learn.org/stable/modules/model_evaluation.html#scoring-parameter) - как устроены scoring strings и callable scorers, от которых зависит смысл importance.
- [CatBoostClassifier.predict_proba](https://catboost.ai/docs/en/concepts/python-reference_catboostclassifier_predict_proba) - официальный API вероятностей, которые используются в `neg_log_loss`.
