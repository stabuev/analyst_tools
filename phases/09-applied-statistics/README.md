<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 09: Прикладная статистика

> Оценивайте неопределенность и границы статистических выводов.

**Треки:** product, ml  
**Пререквизиты:** Фаза 07  
**Время:** ~12-16 часов  
**Итоговый артефакт:** Статистический отчет с ограничениями

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Популяция, выборка и механизм отбора](01-population-and-sample) | 75 мин | Задает target population, sampling unit, sampling frame и inclusion/response mechanisms для user-level метрики, проверяет coverage bias, non-response, веса, дубликаты и неполные observation windows до расчета estimate. | CLI-аудитор sampling frame и sample mechanism report | complete |
| 02 | [Распределения как модели](02-distributions) | 75 мин | Сопоставляет activation, revenue, support tickets и onboarding duration с Bernoulli/binomial, lognormal, count и heavy-tailed моделями, проверяя support, параметры, empirical summaries и failure modes распределения. | Distribution cards для продуктовых метрик с проверкой предпосылок | complete |
| 03 | [Оценки и свойства оценок](03-estimators) | 75 мин | Различает parameter, statistic, estimator и estimate, считает naive и weighted estimators для mean, proportion, quantile и rate и фиксирует estimator spec с population, filters, weights и standard error. | CLI-калькулятор estimator specs и point estimates | complete |
| 04 | [Смещение и дисперсия](04-bias-and-variance) | 75 мин | Проводит repeated-sampling simulation для нескольких механизмов отбора, оценивает bias, variance и MSE estimator'ов и объясняет, почему стабильное число может быть систематически неверным. | Bias-variance simulator с CSV-отчетом по estimator'ам | complete |
| 05 | [Доверительные интервалы](05-confidence-intervals) | 90 мин | Строит confidence intervals для средних и долей через formula-based standard errors, проверяет confidence level, coverage simulation, малые выборки, skew/outliers и явно запрещает интервал при нарушенных assumptions. | CLI-калькулятор confidence intervals с coverage report | complete |
| 06 | [Bootstrap](06-bootstrap) | 90 мин | Строит bootstrap distribution и intervals для произвольной statistic с явной resampling unit, фиксированным RNG, paired mode, degenerate-data handling и сравнением percentile/basic/BCa подходов. | Bootstrap interval builder с resampling manifest и diagnostics | complete |
| 07 | [Корреляция и ложные связи](07-correlation) | 75 мин | Считает Pearson/Spearman correlations, stratified association и shuffled controls, распознает Simpson-like reversal, common-cause segment effects и запрещает причинные claims по наблюдательной связи. | Correlation audit report с aggregate/stratified comparisons | complete |
| 08 | [Линейная регрессия для вывода](08-linear-regression) | 90 мин | Строит design matrix, оценивает OLS coefficients, standard errors и confidence intervals для user-level outcome, интерпретирует коэффициенты при контролях и отделяет inference от prediction и causality. | OLS inference runner с model spec и coefficient table | complete |
| 09 | [Диагностика регрессии](09-regression-diagnostics) | 75 мин | Проверяет residual patterns, heteroscedasticity, leverage, influence, multicollinearity, non-linearity и specification risks, превращая diagnostics в machine-readable flags и ограничения отчета. | Regression diagnostics checker с JSON-report и diagnostic figures | complete |
| 10 | [Робастные и непараметрические методы](10-robust-methods) | 105 мин | Собирает statistical evidence package: sampling audit, distribution cards, estimates, intervals, bootstrap, correlation audit, OLS diagnostics, robust/nonparametric sensitivity checks, report и checksum manifest. | Воспроизводимый statistical-evidence-report package с assumptions, limitations и manifest | complete |

## Критерий завершения

Студент выбирает оценку под процесс генерации данных, строит интервал и проверяет предпосылки модели.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
