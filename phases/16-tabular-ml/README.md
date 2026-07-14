<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 16: Табличный ML и интерпретация

> Улучшайте табличные модели без потери интерпретируемости и контроля.

- **Треки:** ml
- **Пререквизиты:** Фаза 15
- **Время:** ~12-16 часов
- **Итоговый артефакт:** Tabular ML interpretation package

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [CatBoost как сильный табличный baseline](01-catboost) | 90 мин | Обучает CatBoost-кандидат на той же ML-постановке, split roles и metric policy, сравнивая его с baseline package без test-driven selection. | CatBoost baseline trainer с model comparison, training trace и no-test-selection audit | complete |
| 02 | [Категориальные признаки без leakage](02-categorical-features) | 75 мин | Передает categorical features в CatBoost через явный contract, проверяя high-cardinality levels, unknown categories, missing semantics и availability до prediction time. | Categorical feature auditor с category inventory, leakage checks и unknown-category policy | complete |
| 03 | [Early stopping и iteration budget](03-early-stopping) | 75 мин | Использует validation-only eval_set, overfitting detector, best iteration и learning trace как воспроизводимый training-control protocol. | Early stopping auditor с eval_set lineage, best-iteration trace и tree-count report | complete |
| 04 | [Встроенная важность признаков](04-feature-importance) | 75 мин | Считает CatBoost built-in feature importance, различает model-internal diagnostic и причинный вывод, отмечая high-cardinality и correlated-feature warnings. | Built-in importance reporter с method labels, feature-name audit и interpretation warnings | complete |
| 05 | [Permutation importance](05-permutation-importance) | 75 мин | Считает model-agnostic permutation importance на held-out data с declared scoring, repeats, uncertainty bands и предупреждениями про плохую модель и коррелированные признаки. | Permutation importance evaluator с held-out scoring, repeat variance и correlated-feature audit | complete |
| 06 | [SHAP и ограничения объяснений](06-shap) | 90 мин | Строит Tree SHAP explanations для CatBoost, фиксируя background sample, output space, additivity check, local examples и границы интерпретации. | SHAP explanation reporter с local/global summaries, additivity audit и explanation-limitations section | complete |
| 07 | [Сегментный анализ сильной модели](07-segment-analysis) | 75 мин | Сравнивает baseline и CatBoost по segment, score band и business cohort, показывая где сильная модель улучшает, ухудшает или скрывает ошибки. | Strong-model segment analyzer с baseline deltas, small-n warnings и hidden-failure slices | complete |
| 08 | [Порог и стоимость решения для сильной модели](08-cost-sensitive-decisions) | 75 мин | Проверяет, меняет ли CatBoost бизнес-решение: threshold, top-k budget, FP/FN cost, calibration handoff и no-causal-effect boundary. | Cost-sensitive decision evaluator с threshold comparison, budget impact и decision-status gate | complete |
| 09 | [Optuna и честный подбор параметров](09-optuna) | 90 мин | Запускает fixed-budget Optuna study с заранее объявленным search space, validation-only objective, seed policy и полным trial ledger. | Optuna tuning auditor с search-space spec, trial ledger, best-trial trace и no-test-objective check | complete |
| 10 | [MLflow для истории экспериментов](10-mlflow) | 75 мин | Логирует локальные MLflow runs с params, metrics, artifacts, model metadata и upstream package id, превращая эксперименты в проверяемый ledger. | MLflow experiment ledger exporter с run table, artifact inventory и reproducibility checks | complete |
| 11 | [Drift, стабильность и interpretation package](11-drift-and-stability) | 105 мин | Собирает tabular ML interpretation package: CatBoost candidate, comparison, explanations, experiment ledger, drift/stability diagnostics, decision report и checksum manifest. | Tabular ML interpretation package с drift/stability audit, interpretation report и manifest | complete |

## Как проходить фазу

1. Ответьте на входные вопросы до чтения reference implementation.
2. Для каждого урока воспроизведите ручной механизм в локальной папке `work/`.
3. Запустите пример, один failure mode и тесты урока.
4. Выполните хотя бы одно упражнение, которое меняет данные или правило.
5. После фазы пройдите перемешанную самопроверку:

```bash
uv run --locked python scripts/run_quiz.py --phase 16 --stage post --limit 8
```

Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. Критерий освоения — объяснить решение, воспроизвести расчёт и диагностировать хотя бы одну поломку.

## Критерий завершения

Студент улучшает baseline сильной табличной моделью, объясняет локальные и глобальные факторы, ведет журнал экспериментов и проверяет стабильность на сегментах.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
