<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 10: Эксперименты

> Проектируйте и анализируйте эксперименты до принятия продуктового решения.

- **Треки:** product
- **Пререквизиты:** Фаза 08, Фаза 09
- **Время:** ~14-18 часов
- **Итоговый артефакт:** Полный протокол A/B-эксперимента

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Гипотеза и целевая метрика](01-hypothesis-and-metric) | 75 мин | Переводит продуктовую гипотезу в pre-registered experiment protocol: variants, eligible population, primary metric, guardrails, metric windows, alpha/power assumptions и decision rule до просмотра результата. | CLI-валидатор experiment protocol, metric roles и pre-registration contract | complete |
| 02 | [Единица рандомизации](02-randomization-unit) | 90 мин | Выбирает randomization unit и analysis unit, строит стабильное назначение вариантов по hash bucket, проверяет one-unit-one-variant, eligibility, exposure timing, balance и риск interference. | Детерминированный assignment engine и exposure audit report | complete |
| 03 | [A/A-тест и Sample Ratio Mismatch](03-aa-and-srm) | 90 мин | Проводит A/A-test, SRM check и randomization validation: сверяет expected allocation, variant counts, covariate balance, telemetry loss и metric null distribution до анализа A/B. | CLI-диагностик A/A, SRM и randomization health checks | complete |
| 04 | [MDE, мощность и размер выборки](04-mde-and-power) | 90 мин | Рассчитывает baseline, MDE, power, alpha, allocation ratio, expected traffic и runtime для долей и средних, сравнивая formula-based calculation с симуляцией мощности. | Power planner с experiment sizing spec, mde-grid.csv и power curve | complete |
| 05 | [Сравнение средних и долей](05-means-and-proportions) | 90 мин | Оценивает treatment effect для user-level means, proportions и простых ratio metrics: absolute/relative lift, confidence interval, p-value, assumption checks и guardrail status без significance-only решения. | Experiment effect calculator с primary, secondary и guardrail results | complete |
| 06 | [Bootstrap в экспериментах](06-bootstrap) | 90 мин | Строит bootstrap и permutation-based uncertainty для skewed, zero-inflated и ratio metrics с resampling по randomization unit, fixed RNG, paired denominator handling и diagnostics. | Experiment bootstrap analyzer с interval report и resampling manifest | complete |
| 07 | [Снижение дисперсии и CUPED](07-cuped) | 90 мин | Применяет CUPED/pre-experiment covariate adjustment, проверяет pre-treatment статус ковариаты, missingness, correlation with outcome, variance reduction и отсутствие post-treatment leakage. | CUPED adjusted-effect calculator с variance-reduction report | complete |
| 08 | [Множественные проверки](08-multiple-testing) | 75 мин | Объявляет families of hypotheses для primary, guardrail, secondary и exploratory metrics, применяет gatekeeping, Holm/Bonferroni или FDR policy и блокирует cherry-picking по сегментам. | Multiple-testing policy checker с adjusted results и metric-family audit | complete |
| 09 | [Подглядывание и последовательный анализ](09-peeking) | 75 мин | Показывает рост false positive rate от незапланированных interim looks, задает monitoring schedule, alpha-spending или stop/go правила и отличает quality monitoring от decision peeking. | Peeking audit и sequential monitoring report | complete |
| 10 | [Сегменты и неоднородные эффекты](10-heterogeneous-effects) | 75 мин | Анализирует predeclared segment effects, interaction checks, minimum cell sizes и guardrail differences, помечает exploratory findings и не выдает post-hoc subgroup lift за подтвержденный общий эффект. | Segment effect auditor с heterogeneity report и exploratory flags | complete |
| 11 | [Протокол решения и коммуникация](11-decision-protocol) | 105 мин | Собирает experiment-decision package: protocol, assignment audit, A/A/SRM, power, primary effect, bootstrap/CUPED checks, multiple-testing policy, peeking audit, segment report, guardrails, decision и checksum manifest. | Воспроизводимый experiment-decision-package с launch/hold/rollback/iterate decision | complete |

## Критерий завершения

Студент проверяет назначение, рассчитывает эффект и неопределенность и принимает решение по заранее заданному правилу.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
