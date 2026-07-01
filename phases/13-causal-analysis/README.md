<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 13: Причинный анализ

> Проектируйте наблюдательное причинное исследование: сначала estimand и идентификация, затем оценка и проверка чувствительности.

- **Треки:** decision, product
- **Пререквизиты:** Фаза 09, Фаза 10
- **Время:** ~12-16 часов
- **Итоговый артефакт:** Воспроизводимый causal-study-package с DAG, идентификацией, оценками и sensitivity checks

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Причинный вопрос и estimand](01-causal-question-and-estimand) | 75 мин | Переводит продуктовый вопрос в target trial-style causal spec: treatment, contrast, outcome, time zero, population и ATE/ATT/LATE estimand, явно фиксируя consistency, exchangeability, positivity и interference risks. | CLI-валидатор causal question, target trial и estimand spec | complete |
| 02 | [Причинные DAG и идентификация](02-causal-dags) | 75 мин | Строит направленный ациклический граф из предметных assumptions, различает association и intervention, проверяет temporal order и d-separation и отделяет идентификацию эффекта от выбора estimator. | Causal DAG validator с identification map и d-separation checks | complete |
| 03 | [Confounders и backdoor adjustment](03-confounders) | 75 мин | Находит открытые backdoor paths, выбирает достаточный pre-treatment adjustment set и фиксирует, какие confounders измерены, проксированы или остаются ненаблюдаемыми. | Backdoor adjustment-set auditor с measured/unmeasured confounder report | complete |
| 04 | [Colliders, mediators и selection bias](04-colliders) | 75 мин | Распознает collider, mediator, descendant of treatment и selection variable, объясняет bias от bad controls и блокирует adjustment по post-treatment данным. | Bad-control и selection-bias auditor для candidate adjustment sets | complete |
| 05 | [Regression adjustment и g-formula](05-regression-adjustment) | 90 мин | Оценивает standardized potential outcomes и ATE/ATT через outcome regression, сверяет ручную g-computation со statsmodels и диагностирует misspecification, extrapolation и неверный adjustment set. | G-computation estimator с standardized outcomes и model diagnostics | complete |
| 06 | [Matching и баланс ковариат](06-matching) | 90 мин | Строит matching по pre-treatment covariates или propensity score, задает caliper и replacement policy, проверяет common support, standardized mean differences и изменение target population после отбора. | Matching pipeline с balance table, love plot data и common-support audit | complete |
| 07 | [Propensity weighting и doubly robust оценка](07-weighting-and-doubly-robust) | 90 мин | Оценивает propensity scores, строит stabilized IPW и AIPW estimates, проверяет overlap, extreme weights, effective sample size и trimming sensitivity и сравнивает методы при misspecified treatment или outcome model. | IPW/AIPW estimator с overlap, weight и effective-sample-size diagnostics | complete |
| 08 | [Difference-in-Differences](08-difference-in-differences) | 105 мин | Рассчитывает 2x2 и multi-period DiD для регионального rollout, формулирует parallel-trends assumption, проверяет pre-trends и placebo periods и распознает риск наивного TWFE при staggered adoption. | DiD analyzer с manual reconciliation, event-study table и placebo/pre-trend checks | complete |
| 09 | [RDD и instrumental variables: дизайн до оценки](09-quasi-experiments) | 75 мин | Проверяет применимость RDD и IV, формулирует локальный estimand, continuity/relevance/exclusion/monotonicity assumptions и обнаруживает manipulation at cutoff, weak instrument и неверное обобщение LATE на ATE. | Quasi-experiment design auditor для RDD и IV с local-estimand contract | complete |
| 10 | [Sensitivity analysis и falsification checks](10-sensitivity) | 75 мин | Проводит placebo treatment/outcome, negative-control и omitted-confounding sensitivity checks, сравнивает estimates между designs и формулирует, какая сила нарушения assumptions изменит вывод. | Sensitivity и refutation suite с placebo, negative-control и omitted-variable report | complete |
| 11 | [Causal workflow и границы автоматизации](11-causal-workflow) | 105 мин | Собирает causal-study-package, воспроизводит model-identify-estimate-refute workflow в DoWhy, сверяет его с прозрачными RA/IPW/AIPW/DiD расчетами и объясняет, почему EconML не заменяет identification и нужен только для отдельно поставленной heterogeneity-задачи. | Causal-study-package с DAG, estimates, balance, falsification, sensitivity, automation audit и checksum manifest | complete |

## Критерий завершения

Студент формулирует estimand, обосновывает adjustment или quasi-experimental design, проверяет overlap, falsification и sensitivity и ограничивает causal claim выполненными assumptions.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
