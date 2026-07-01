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
| 01 | Постановка ML-задачи | 75 мин | Формулирует supervised ML-задачу через business decision, prediction unit, target horizon, prediction time, positive/negative class, allowed feature sources и no-causal-claim boundary. | ML problem spec validator с target timing, prediction-unit и feature-availability checks | designed |
| 02 | Train, validation и test | 75 мин | Строит train/validation/test split manifest, который уважает prediction time, user grouping, label horizon и роли validation/test. | ML split auditor с group/time split manifest и leakage checks | designed |
| 03 | Метрики и стоимость ошибки | 75 мин | Связывает confusion matrix, precision/recall/FPR/FNR, PR-oriented metrics, threshold и business cost ошибки в metric policy. | Classification metric evaluator с threshold sweep, cost table и metric suitability audit | designed |
| 04 | Предобработка как часть модели | 75 мин | Разделяет raw features, train-fitted preprocessing и transformed feature matrix, блокируя fit-before-split, silent missing-value policy и unknown categories. | Preprocessing contract checker с train-fitted imputing/encoding/scaling audit | designed |
| 05 | scikit-learn Pipeline | 90 мин | Собирает scikit-learn Pipeline, где preprocessing и estimator обучаются одним объектом, а predictions воспроизводимо строятся для validation/test. | Pipeline runner с fit/transform order audit, serialized spec и prediction report | designed |
| 06 | ColumnTransformer | 75 мин | Маршрутизирует numeric, categorical и binary columns через ColumnTransformer, проверяя dropped columns, transformed feature names и unknown-category policy. | ColumnTransformer auditor с feature routing table и transformed schema report | designed |
| 07 | Линейные baseline | 75 мин | Строит dummy и logistic/linear baseline, сравнивает их на validation, фиксирует regularization, intercept и coefficient interpretation limits. | Linear baseline trainer с dummy comparison, coefficients и baseline report | designed |
| 08 | Деревья решений | 75 мин | Обучает decision tree как диагностическую non-linear модель, контролируя depth/min samples, train-validation gap и rule export. | Tree diagnostic trainer с overfit report и readable rules | designed |
| 09 | Ансамбли деревьев | 75 мин | Сравнивает tree ensemble с baselines, фиксируя random seed, stability across seeds, feature-importance warnings и slice metrics. | Tree ensemble comparator с stability report и feature-importance audit | designed |
| 10 | Cross-validation | 75 мин | Проектирует cross-validation folds, которые уважают group/time constraints, scoring policy и запрет test peeking. | Cross-validation planner с fold manifest, scoring alignment и no-peeking audit | designed |
| 11 | Несбалансированные классы | 75 мин | Диагностирует imbalance, ловушку accuracy, class weights/resampling role и threshold selection для ограниченного offer budget. | Imbalance policy evaluator с class distribution, baseline trap и budget-threshold report | designed |
| 12 | Калибровка вероятностей | 75 мин | Проверяет probability calibration через bins, Brier/log loss и сравнивает calibrated vs uncalibrated threshold decisions. | Probability calibration auditor с calibration bins, Brier score и threshold impact report | designed |
| 13 | Data leakage | 90 мин | Аудирует forbidden features, post-outcome information, full-sample preprocessing, feature selection outside CV и validation-score cherry-picking. | ML leakage auditor с feature availability report, forbidden-source table и model-selection checks | designed |
| 14 | Анализ ошибок по сегментам | 75 мин | Публикует error analysis по segment, score band и business cohort, показывая small-n warnings и hidden aggregate failures. | Segment error analyzer с slice metrics, confusion rows и small-n warnings | designed |
| 15 | Model card и ограничения | 90 мин | Собирает ML baseline package: problem spec, data/split/leakage evidence, pipeline summary, metrics, calibration, segment errors, model card, decision и checksum manifest. | ML baseline package с model card, decision report и manifest | designed |

## Критерий завершения

Полный Pipeline оценивается на корректном split, сравнивается с простым baseline и сопровождается анализом ошибок.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
