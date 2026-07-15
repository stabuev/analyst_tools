<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 08: Продуктовая аналитика

> Свяжите поведение пользователей с измеримыми продуктовыми решениями.

- **Треки:** product
- **Пререквизиты:** Фаза 07
- **Время:** ~12-16 часов
- **Итоговый артефакт:** Исследование продуктовой проблемы

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Дерево метрик](01-metric-tree) | 75 мин | Строит дерево продуктовых метрик из вопроса, задает outcome, input и guardrail-метрики с grain, population, numerator, denominator и window и валидирует metric specs. | CLI-валидатор дерева метрик и спецификаций продуктовых метрик | complete |
| 02 | [Событийная модель продукта](02-event-model) | 75 мин | Проектирует tracking plan для продуктовых событий, связывает события с metric specs и проверяет event names, versions, required properties, identity fields, дубликаты и late arrivals. | CLI-валидатор tracking plan и событийного лога | complete |
| 03 | [Активность и активная аудитория](03-activity) | 75 мин | Считает DAU/rolling active users по явному набору активных событий, grain `user_id`, eligible population, business timezone и окнам 1/7 дней, исключая test users и помечая неполные окна. | CLI-калькулятор active audience с activity.csv и quality report | complete |
| 04 | [Воронки и неоднозначность конверсии](04-funnels) | 75 мин | Считает closed funnels по tracking plan с явным unit `user_id`/`session_id`/`user_day`, strict/loose ordering, conversion window, стартовой популяцией, дедупликацией событий и проверкой late arrivals. | CLI-калькулятор продуктовых воронок с funnel.csv и quality report | complete |
| 05 | [Когортный анализ](05-cohorts) | 75 мин | Строит daily cohort matrix по registered_at и active events с фиксированным cohort denominator, age_day 0-7, complete/incomplete observation windows, дедупликацией событий и проверкой test users, unknown users и late arrivals. | CLI-калькулятор когортной матрицы с cohorts.csv и quality report | complete |
| 06 | [Retention и возвращаемость](06-retention) | 75 мин | Считает daily retention по registered cohorts и return events с режимами `exact_day` и `on_or_after`, фиксированным denominator, age_day 1-7, complete-window policy, дедупликацией событий и quality report. | CLI-калькулятор retention с retention.csv и quality report | complete |
| 07 | [Выручка, ARPU и LTV](07-monetization) | 75 мин | Считает realized revenue, ARPU, ARPPU и cohort LTV по registered cohorts и фиксированным revenue windows, учитывая paid/refunded/pending orders, cancelled subscriptions, complete-window policy и защиту от many-to-many revenue joins. | CLI-калькулятор монетизации с monetization.csv и quality report | complete |
| 08 | [Сегментация без самообмана](08-segmentation) | 75 мин | Считает сегментные activation rates по заранее объявленным dimensions, minimum cell size и cohort periods, помечает exploratory segments, строит platform decomposition на within-segment и composition effect и запрещает причинные claims без эксперимента. | CLI-калькулятор сегментации с segments.csv и quality report | complete |
| 09 | [Guardrail-метрики](09-guardrails) | 75 мин | Считает support_ticket_rate, subscription_cancel_rate и refund_rate как guardrail-метрики с risk direction `up_is_bad`, thresholds, complete-window policy и итоговым decision status, запрещая оптимизировать outcome ценой ухудшения guardrails. | CLI-калькулятор guardrail-метрик с guardrails.csv и quality report | complete |
| 10 | [Аномалии продуктовых метрик](10-anomalies) | 75 мин | Классифицирует скачки продуктовых метрик как data_quality, composition, calendar_effect или product_signal, пропуская product_signal только после freshness, duplicate, late-arrival и tracking completeness gates. | CLI-детектор аномалий с anomaly spec, quality gates и anomalies.json | complete |
| 11 | [Бизнес-вывод и рекомендация](11-business-conclusion) | 105 мин | Собирает артефакты продуктовой фазы в проверяемое исследование проблемы: brief, metric/tracking contracts, metric tables, audits, figures, report, recommendation и checksum manifest. | Воспроизводимый product-problem-investigation package с recommendation и manifest | complete |

## Как проходить фазу

1. Ответьте на входные вопросы до чтения reference implementation.
2. Для каждого урока выполните прозрачную практику в локальной папке `work/`.
3. Запустите пример и тесты либо заполните артефакт и проверьте его по рубрике.
4. Выполните хотя бы одно упражнение, которое меняет данные или правило.
5. После фазы пройдите перемешанную самопроверку:

```bash
uv run --locked python scripts/run_quiz.py --phase 8 --stage post --limit 8
```

Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. Критерий освоения — объяснить решение, воспроизвести расчет или рассуждение и диагностировать хотя бы одну поломку.

## Критерий завершения

Студент строит согласованную систему метрик и формулирует решение с guardrail-метриками и ограничениями.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
