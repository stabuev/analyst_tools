<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 15: Прикладное машинное обучение

> Постройте честный baseline и защитите оценку от leakage.

- **Треки:** ml
- **Пререквизиты:** Фаза 07, Фаза 09
- **Время:** ~16-20 часов
- **Итоговый артефакт:** Воспроизводимый ML baseline и model card

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Постановка ML-задачи](01-problem-framing) | 75 мин | Формулирует supervised ML-задачу через business decision, prediction unit, target horizon, prediction time, positive/negative class, allowed feature sources и no-causal-claim boundary. | ML problem spec validator с target timing, prediction-unit и feature-availability checks | complete |
| 02 | [Train, validation и test](02-data-splitting) | 75 мин | Строит train/validation/test split manifest, который уважает prediction time, user grouping, label horizon и роли validation/test. | ML split auditor с group/time split manifest и leakage checks | complete |
| 03 | [Метрики и стоимость ошибки](03-metrics) | 75 мин | Связывает confusion matrix, precision/recall/FPR/FNR, PR-oriented metrics, threshold и business cost ошибки в metric policy. | Classification metric evaluator с threshold sweep, cost table и metric suitability audit | complete |
| 04 | [Предобработка как часть модели](04-preprocessing) | 75 мин | Разделяет raw features, train-fitted preprocessing и transformed feature matrix, блокируя fit-before-split, silent missing-value policy и unknown categories. | Preprocessing contract checker с train-fitted imputing/encoding/scaling audit | complete |
| 05 | [scikit-learn Pipeline](05-pipeline) | 90 мин | Собирает scikit-learn Pipeline, где preprocessing и estimator обучаются одним объектом, а predictions воспроизводимо строятся для validation/test. | Pipeline runner с fit/transform order audit, serialized spec и prediction report | complete |
| 06 | [ColumnTransformer](06-column-transformer) | 75 мин | Маршрутизирует numeric, categorical и binary columns через ColumnTransformer, проверяя dropped columns, transformed feature names и unknown-category policy. | ColumnTransformer auditor с feature routing table и transformed schema report | complete |
| 07 | [Линейные baseline](07-linear-models) | 75 мин | Строит dummy и logistic/linear baseline, сравнивает их на validation, фиксирует regularization, intercept и coefficient interpretation limits. | Linear baseline trainer с dummy comparison, coefficients и baseline report | complete |
| 08 | [Деревья решений](08-trees) | 75 мин | Обучает decision tree как диагностическую non-linear модель, контролируя depth/min samples, train-validation gap и rule export. | Tree diagnostic trainer с overfit report и readable rules | complete |
| 09 | [Ансамбли деревьев](09-ensembles) | 75 мин | Сравнивает tree ensemble с baselines, фиксируя random seed, stability across seeds, feature-importance warnings и slice metrics. | Tree ensemble comparator с stability report и feature-importance audit | complete |
| 10 | [Cross-validation](10-cross-validation) | 75 мин | Проектирует cross-validation folds, которые уважают group/time constraints, scoring policy и запрет test peeking. | Cross-validation planner с fold manifest, scoring alignment и no-peeking audit | complete |
| 11 | [Несбалансированные классы](11-imbalanced-data) | 75 мин | Диагностирует imbalance, ловушку accuracy, class weights/resampling role и threshold selection для ограниченного offer budget. | Imbalance policy evaluator с class distribution, baseline trap и budget-threshold report | complete |
| 12 | [Калибровка вероятностей](12-calibration) | 75 мин | Проверяет probability calibration через bins, Brier/log loss и сравнивает calibrated vs uncalibrated threshold decisions. | Probability calibration auditor с calibration bins, Brier score и threshold impact report | complete |
| 13 | [Data leakage](13-leakage) | 90 мин | Аудирует forbidden features, post-outcome information, full-sample preprocessing, feature selection outside CV и validation-score cherry-picking. | ML leakage auditor с feature availability report, forbidden-source table и model-selection checks | complete |
| 14 | [Анализ ошибок по сегментам](14-error-analysis) | 75 мин | Публикует error analysis по segment, score band и business cohort, показывая small-n warnings и hidden aggregate failures. | Segment error analyzer с slice metrics, confusion rows и small-n warnings | complete |
| 15 | [Model card и ограничения](15-model-card) | 90 мин | Собирает ML baseline package: problem spec, data/split/leakage evidence, pipeline summary, metrics, calibration, segment errors, model card, decision и checksum manifest. | ML baseline package с model card, decision report и manifest | complete |

## Как проходить фазу

1. Ответьте на входные вопросы до чтения reference implementation.
2. Для каждого урока воспроизведите ручной механизм в локальной папке `work/`.
3. Запустите пример, один failure mode и тесты урока.
4. Выполните хотя бы одно упражнение, которое меняет данные или правило.
5. После фазы пройдите перемешанную самопроверку:

```bash
uv run --locked python scripts/run_quiz.py --phase 15 --stage post --limit 8
```

Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. Критерий освоения — объяснить решение, воспроизвести расчёт и диагностировать хотя бы одну поломку.

## Критерий завершения

Полный Pipeline оценивается на корректном split, сравнивается с простым baseline и сопровождается анализом ошибок.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
