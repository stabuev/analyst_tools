# SHAP и ограничения объяснений

## Проблема

В `16/04` built-in importance сказал: `platform` доминирует внутри CatBoost. В
`16/05` permutation importance на validation сказал осторожнее: тот же `platform` дает
самый большой абсолютный delta, но mean delta отрицательный, а strong positive claim
не поддержан.

Теперь хочется открыть модель локально: почему конкретная строка получила такой score?
Tree SHAP отвечает на этот вопрос через decomposition prediction:

```text
raw_prediction = expected_value + sum(shap_value_i)
```

Но SHAP легко переинтерпретировать. Он объясняет поведение обученной модели в выбранном
output space, а не причину churn, не справедливость решения и не стабильность в
production. В этом уроке вы построите reporter, который считает global/local Tree SHAP
для CatBoost и рядом сохраняет ограничения: background mode, raw output space,
additivity check, local examples, disagreement с built-in/permutation и warning ledger.

## Концепция

SHAP values раскладывают prediction на вклады признаков. В tree models это удобно:
`TreeExplainer` использует структуру деревьев и возвращает вклад каждого feature в
выбранном output space.

В этом уроке output space - `raw_margin`, то есть `RawFormulaVal` CatBoost. Это важно:

| Решение | Что значит | Почему так |
|---|---|---|
| `model_output="raw"` | SHAP values складываются в raw margin | additivity можно проверить напрямую |
| `feature_perturbation="tree_path_dependent"` | background берется из path counts дерева | CatBoost categorical splits не поддерживают external background data в `TreeExplainer` |
| `external_background_data_passed=false` | мы не передаем train dataframe как masker | это осознанный constraint, а не забытый параметр |
| `background_split="train"` | train rows записаны как reference | в отчете видно, какая обучающая база соответствует path-dependent baseline |

Почему не probability? Для Tree SHAP probability output требует другой режим
зависимости признаков. С CatBoost native categorical splits в этом tiny уроке честнее
объяснять raw margin, а probability показывать рядом только как prediction context.

Защитные слои reporter:

| Слой | Что проверяет | Что блокирует |
|---|---|---|
| Handoff | `16/05` готов к SHAP, модель и feature order совпадают | объяснение не той модели |
| Background audit | path-dependent mode зафиксирован, train reference не смешан с test | неявный baseline |
| Output contract | `raw_margin`, `RawFormulaVal`, tolerance `1e-9` | некорректная additivity |
| Local rows | только `S005`, `S006`, `S007` из validation | подглядывание в final test |
| Disagreement table | built-in, permutation и SHAP сравниваются явно | красивая, но однобокая история |
| Limitation warnings | tiny sample, one tree, weak score, high-cardinality, correlation | сильные бизнес-выводы |

## Соберите это

Новый policy spec:

```text
phases/16-tabular-ml/data/tiny/shap_explanation_policy_spec.json
```

Он фиксирует:

- handoff от `16/05` permutation importance;
- `explain_split=validation` и `final_holdout_split=test`;
- `TreeExplainer`, `model_output=raw`, `output_space=raw_margin`;
- `feature_perturbation=tree_path_dependent`;
- path-dependent background mode и train-row reference;
- additivity tolerance `1e-9`;
- local rows `S005`, `S006`, `S007`;
- global aggregation `mean_abs_shap`;
- non-causal, non-fairness, non-production-stability interpretation policy;
- warning thresholds для tiny background, tiny explanation sample, one-tree model,
  weak validation score, high-cardinality и correlated features.

Минимальный механизм:

```python
import shap
from catboost import Pool


explainer = shap.TreeExplainer(
    model,
    feature_perturbation="tree_path_dependent",
    model_output="raw",
)
values = explainer.shap_values(Pool(X_validation, cat_features=cat_features))
expected_value = explainer.expected_value
raw_prediction = model.predict(
    Pool(X_validation, cat_features=cat_features),
    prediction_type="RawFormulaVal",
)
```

Reporter делает из этого production-shaped artifact:

- `shap_global_summary.csv` - feature-level `mean_abs_shap`, signs и rank;
- `shap_local_explanations.csv` - top local contributions для declared rows;
- `shap_additivity_audit.csv` - row-level reconstruction raw margin;
- `explanation_disagreement.csv` - comparison с built-in и permutation;
- `shap_warning_ledger.csv` - limitations рядом с числами;
- `shap_explanation_serialized_spec.json` - handoff для `16/07`.

Основной артефакт:

```text
phases/16-tabular-ml/06-shap/outputs/shap_explanation_reporter.py
```

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/16-tabular-ml/06-shap/code/main.py
```

Ожидаемая сводка:

```json
{
  "audit_valid": true,
  "shap_explanation_audit_id": "trial-churn-shap-explanation-audit-v0",
  "early_stopping_model_id": "catboost_depth2_native_categories_es_logloss",
  "explain_split": "validation",
  "background_row_count": 4,
  "explain_row_count": 3,
  "output_space": "raw_margin",
  "expected_value": 0.0,
  "additivity_max_abs_error": 0.0,
  "top_mean_abs_shap_feature": "platform",
  "disagreement_status": "same_top_feature_conflicting_direction_or_scope",
  "warning_count": 8,
  "readiness_status": "ready_for_segment_analysis_lesson"
}
```

В tiny fixture:

- background reference содержит train rows `S001`-`S004`;
- объяснение строится только для validation rows `S005`, `S006`, `S007`;
- `expected_value = 0.0`;
- raw predictions: `[-0.030769, -0.030769, 0.030769]`;
- `platform` единственный ненулевой SHAP feature;
- `mean_abs_shap(platform) = 0.030769`;
- local signs смешанные: `ios` и `web` дают отрицательный вклад, `android` -
  положительный;
- additivity error равен `0.0` для всех трех rows.

Disagreement table важнее, чем top feature:

| Method | Top feature | Direction / meaning |
|---|---|---|
| CatBoost `PredictionValuesChange` | `platform` | positive internal prediction-change signal |
| CatBoost `LossFunctionChange` | `platform` | negative validation loss-function change |
| Permutation importance | `platform` | loss decreased when permuted on tiny validation |
| Tree SHAP `mean_abs` | `platform` | mixed local signs in raw-margin space |

Все методы указывают на `platform`, но смысл сигнала разный. Поэтому корректный вывод:
модель действительно использует split по `platform`, но этот факт не доказывает
положительную бизнес-важность платформы и не объясняет причинность churn.

## Сломайте это

Поменяйте output space:

```json
"model_output": "probability",
"output_space": "probability"
```

Policy должна упасть. В этом уроке additivity contract задан для raw margin, а
probability values нельзя смешивать с raw `RawFormulaVal`.

Теперь добавьте test-row в local explanations:

```json
"snapshot_ids": ["S005", "S009"]
```

Audit должен заблокировать расчет. Final test не используется для выбора и упаковки
интерпретационной истории.

Измените claim:

```json
"claim": "platform causes churn and fairness certified production stable"
```

Reporter должен заблокировать policy. SHAP объясняет модельный score, а не causal
effect, fairness guarantee или production-stability guarantee.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/06-shap/tests
```

Тесты проверяют:

- handoff от `16/05`;
- path-dependent background reference на train rows;
- validation-only explanation без final test;
- raw-margin output contract;
- feature order из CatBoost training pool;
- 10 global SHAP rows;
- local explanations для `S005`, `S006`, `S007`;
- additivity reconstruction для raw margin;
- disagreement table для built-in, permutation и SHAP;
- warnings про high-cardinality, correlation, tiny sample, one tree, weak score,
  raw margin и CatBoost background constraint;
- блокировку probability output;
- блокировку local row из test;
- блокировку causal/fairness/production-stability claim;
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

Готовый результат урока - SHAP explanation reporter. Его можно передать в `16/07`,
потому что:

- модель совпадает с early-stopping run из `16/03`;
- permutation handoff из `16/05` валиден;
- background mode записан явно;
- output space не смешивает raw margin и probability;
- additivity check проходит;
- local examples сохранены рядом с feature values;
- global summary показывает, где есть ненулевой вклад;
- disagreement с built-in и permutation не скрыт;
- limitations сохранены как machine-readable warning ledger;
- `ready_for_segment_analysis_lesson` означает, что следующий урок может смотреть
  segment-level behavior сильной модели, не превращая SHAP в causal proof.

## Упражнения

1. Включите `include_zero_contributions=true` в копии policy и сравните читаемость
   local explanations.
2. Добавьте local row из test split и объясните, почему auditor блокирует такой отчет.
3. Увеличьте модель в копии early-stopping spec и проверьте, исчезает ли one-tree
   warning.
4. Сравните `mean_abs_shap` с permutation `mean_importance` и сформулируйте, почему
   эти числа не обязаны иметь одинаковый знак.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| SHAP value | "Причина решения" | Вклад признака в prediction обученной модели в выбранном output space |
| Expected value | "Средняя вероятность churn" | Baseline в том output space, где считается SHAP; здесь raw margin |
| Additivity | "Красивое свойство графика" | Проверка, что `expected_value + sum(SHAP)` восстанавливает model raw prediction |
| Background | "Любой train dataframe" | Для CatBoost categorical splits здесь используется tree-path-dependent baseline |
| Global SHAP | "Общая бизнес-важность" | Aggregation local contributions на выбранном split, не causal effect |
| Disagreement table | "Лишний отчет" | Защита от скрытия конфликтующих смыслов разных explanation methods |

## Дополнительное чтение

- [SHAP TreeExplainer API](https://shap.readthedocs.io/en/stable/generated/shap.TreeExplainer.html) - параметры `model_output`, `feature_perturbation`, background behavior и additivity contract.
- [SHAP CatBoost tutorial](https://shap.readthedocs.io/en/stable/example_notebooks/tabular_examples/tree_based_models/Catboost%20tutorial.html) - пример применения SHAP к CatBoost-модели.
- [CatBoost: feature importance and SHAP values](https://catboost.ai/docs/en/concepts/fstr) - документация CatBoost по feature importance и SHAP value формату.
- [Lundberg and Lee, 2017: A Unified Approach to Interpreting Model Predictions](https://arxiv.org/abs/1705.07874) - первичная статья про SHAP как additive feature attribution.
