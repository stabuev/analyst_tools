# Проект фазы 08: Продуктовая аналитика

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую продуктовую задачу, модель событийных данных, роли уже введенных инструментов и
контракт интеграционного исследования.

## Результат фазы

Студент превращает сырые события, платежи и обращения в согласованную систему продуктовых
метрик. Результат не сводится к одному числу: студент показывает дерево метрик, проверяет
событийную модель, считает активность, воронки, когорты, retention и монетизацию,
отделяет сегментный и композиционный эффект, проверяет guardrail-метрики и формулирует
ограниченную фактами рекомендацию.

Фаза состоит из четырех последовательных блоков:

1. `08/01`-`08/02`: дерево метрик, продуктовый вопрос и tracking plan.
2. `08/03`-`08/07`: активность, воронки, когорты, retention и монетизация.
3. `08/08`-`08/10`: сегментация, guardrails и диагностика аномалий.
4. `08/11`: интеграционное исследование продуктовой проблемы.

Суммарная длительность остается в рамке программы: 12-16 часов.

## Границы содержания

- **Метрика раньше графика и dashboard.** Фаза учит определять grain, популяцию,
  окно наблюдения, числитель, знаменатель и допустимые фильтры. Dashboard layout,
  интерактивная поставка и выбор формата для заказчика остаются фазе 17.
- **Продуктовая интерпретация, не статистический вывод.** Доли, средние и разрезы
  считаются воспроизводимо, но доверительные интервалы, свойства оценок и проверка
  предпосылок систематизируются в фазе 09.
- **Наблюдательные данные, не эксперимент.** Воронка, retention и сегменты помогают
  сформулировать гипотезу и решение под риск, но не доказывают эффект фичи. A/A,
  MDE, мощность, p-value, CUPED и протокол решения остаются фазе 10.
- **Связь, не причинность.** Сегментация и декомпозиция показывают, где меняется
  метрика, но причинные графы, backdoor paths и sensitivity analysis остаются фазе 13.
- **Tracking plan, не SDK-интеграция.** Студент проектирует события, свойства, версии,
  проверки и failure modes. Реальные SDK, consent management и production delivery
  находятся за границей фазы.
- **LTV как наблюдаемая когортная метрика.** Фаза считает realized revenue, ARPU,
  ARPPU и простую cohort LTV за фиксированное окно. Полная финансовая модель с CAC,
  discounting, payback и прогнозом остается вне обязательного ядра.
- **Аномалии продукта, не полный time-series курс.** `08/10` отделяет скачок
  числителя, знаменателя, состава, календаря релиза и качества данных. ETS, ARIMA,
  rolling backtesting и forecast intervals остаются фазе 14.

## Роли инструментов

Новых обязательных библиотек фаза не добавляет. Она использует стек, уже введенный в
ядре курса.

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| pandas | Event/user/session aggregations, cohort matrices, metric tables | Обзор API и оптимизация больших данных |
| DuckDB | Независимые SQL-проверки grain, связей и reconciliation метрик | dbt graph, warehouse orchestration и production BI |
| NumPy | Детерминированные rates, shares, weighted decompositions и sanity checks | Статистическое моделирование и распределения |
| Pandera/Pydantic | Контракты tracking plan, metric specs и конфигурации расчета | Полная data quality platform и web/API schemas |
| Matplotlib/Altair/Plotly | Повторное применение изученных графиков для трендов и разрезов | Новая gallery визуализаций и dashboard-приложения |

Проверенные внешние ориентиры не являются целевыми инструментами курса, но помогают
держать терминологию близкой к индустриальной практике:

- [Google Analytics: Set up events](https://developers.google.com/analytics/devguides/collection/ga4/events)
  - события описывают пользовательские взаимодействия, имеют имя и параметры, а
  recommended/custom events разделяются по назначению.
- [Mixpanel: Create A Tracking Plan](https://docs.mixpanel.com/docs/tracking-best-practices/tracking-plan)
  - tracking plan должен связывать бизнес-цели, KPI, события, свойства и команды.
- [Mixpanel: Metric Tree](https://docs.mixpanel.com/docs/metric_tree)
  - дерево метрик фиксирует связи между outcome-метриками, input-метриками и контекстом
  решения.
- [Mixpanel: Funnels](https://docs.mixpanel.com/docs/reports/funnels/funnels-overview)
  - funnel считается как переходы между событиями в заданном временном окне.
- [Mixpanel: Retention](https://docs.mixpanel.com/docs/reports/retention)
  - retention требует явно определить стартовое действие, return action, окно и способ
  измерения.

## Единая продуктовая задача и данные

Фаза использует вымышленный подписочный сервис с маркетплейсом дополнительных товаров.
Рабочий вопрос интеграционного проекта: «После изменения onboarding и paywall команда
видит рост ранней активации, но жалобы и отмены подписки растут. Продолжать rollout,
откатить изменение или поставить следующий проверяемый шаг?»

Входные таблицы:

| Таблица | Grain | Ключ |
|---|---|---|
| `users` | один зарегистрированный пользователь | `user_id` |
| `events` | одно клиентское или серверное событие | `event_id` |
| `sessions` | одна пользовательская сессия после identity stitching | `session_id` |
| `subscriptions` | один период подписки пользователя | `subscription_id` |
| `orders` | один платеж или заказ маркетплейса | `order_id` |
| `support_tickets` | одно обращение пользователя | `ticket_id` |
| `release_calendar` | один релиз продукта на платформе | `release_id` |

Минимальный словарь событий:

```text
app_open
signup_started
account_created
onboarding_started
onboarding_completed
feature_value_seen
paywall_viewed
trial_started
subscription_started
order_paid
subscription_cancelled
support_ticket_created
```

Базовые поля `events`:

| Поле | Смысл |
|---|---|
| `event_id` | идемпотентный ключ события |
| `user_id` | пользователь после login/identity merge, может отсутствовать до регистрации |
| `anonymous_id` | устройство или браузер до регистрации |
| `session_id` | сессия после нормализации таймзоны и inactivity gap |
| `event_name` | имя из tracking plan |
| `event_version` | версия контракта события |
| `occurred_at` | бизнес-время совершения события |
| `received_at` | время доставки в аналитическое хранилище |
| `platform` | `web`, `ios` или `android` |
| `app_version` | версия приложения, структурно отсутствует для `web` |
| `properties_json` | event-specific свойства из tracking plan |

Профили данных:

- `tiny`: маленький валидный baseline в Git для ручной сверки всех метрик;
- `sample`: детерминированная локальная генерация для недельных трендов, сегментов,
  когорт и аномалий;
- дефекты создаются как минимальные мутации baseline, чтобы failure mode был виден без
  чтения полного генератора.

Заложенные свойства и failure modes:

- повторная доставка одного события с тем же `event_id`;
- поздняя доставка события после закрытия дневного среза;
- разные часовые зоны и сессии, пересекающие локальную полночь;
- `anonymous_id` до регистрации и `user_id` после identity merge;
- переименование события и изменение обязательного свойства в новой версии;
- тестовые пользователи и bot-like активность;
- неполные observation windows для новых когорт retention и LTV;
- рост активации, вызванный изменением состава acquisition channels;
- Android-релиз с локальным ухудшением paywall и ростом support tickets;
- trial, refund и cancel events, которые ломают наивный ARPU;
- many-to-many join между событиями и платежами, размножающий выручку.

## Контракт метрики

Каждая метрика фазы описывается машинно читаемой спецификацией:

```text
metric_id
question
owner
grain
eligible_population
numerator
denominator
window
filters
dimensions
expected_direction
guardrails
known_failure_modes
source_tables
validation_checks
```

Спецификация нужна не для бюрократии, а чтобы студент мог объяснить, почему два похожих
расчета дают разные ответы. Например, `signup_to_trial_conversion_7d` и
`paywall_to_trial_conversion_session` имеют разные стартовые события, окна и
знаменатели, поэтому не должны сравниваться как одна метрика.

## Интеграционный мини-проект

`08/11` собирает поставку:

```text
product-problem-investigation/
├── brief.md
├── metric-tree.json
├── tracking-plan.json
├── metric-specs.json
├── audits/
│   ├── event-quality.json
│   └── metric-quality.json
├── metrics/
│   ├── activity.csv
│   ├── funnel.csv
│   ├── cohorts.csv
│   ├── retention.csv
│   ├── monetization.csv
│   ├── segments.csv
│   ├── guardrails.csv
│   └── anomalies.json
├── figures/
│   ├── metric-trend.png
│   └── segment-decomposition.png
├── report.md
├── recommendation.json
└── manifest.json
```

Исследование обязано:

- сформулировать продуктовый вопрос, варианты решения и цену ошибки;
- построить дерево метрик от outcome до input и guardrail-метрик;
- проверить tracking plan: обязательные события, свойства, версии, дубликаты, late
  arrivals и неизвестные события;
- рассчитать активность, funnel, cohorts, retention и монетизацию с явными окнами;
- исключить неполные observation windows перед retention и LTV;
- разделить изменение метрики на числитель, знаменатель, состав трафика и качество
  данных;
- проверять guardrails: support tickets, cancellations, refunds, data freshness и
  tracking completeness;
- классифицировать аномалии как `data_quality`, `composition`, `product_signal` или
  `calendar_effect`;
- выпустить рекомендацию из ограниченного набора: `continue`, `rollback`,
  `investigate`, `run_experiment`;
- связать каждый вывод с `metric_id`, расчетом, таблицей и ограничением.

## Проверяемость

- Tiny-profile содержит ручные ожидаемые ответы для ключевых метрик каждого урока.
- pandas-расчеты для финального проекта сверяются независимым DuckDB SQL по тем же
  metric specs.
- Deduplication, identity merge, timezone normalization и late arrivals проверяются
  отдельными fixtures.
- Funnel tests различают strict order, loose order, session window и day-window.
- Cohort, retention и LTV tests запрещают использовать неполные окна наблюдения.
- Segment analysis использует заранее объявленные dimensions и minimum cell size; новый
  post-hoc segment должен быть отмечен как exploratory.
- Guardrail tests проверяют не только значение, но и направление риска: рост support
  tickets, cancellations и refunds является плохим сигналом.
- Anomaly report не может называть продуктовый сигнал, пока не пройдены freshness,
  volume, duplicate и tracking completeness checks.
- Recommendation tests проверяют, что в `recommendation.json` нет причинного утверждения
  без эксперимента или явного causal design, а каждое claim ссылается на metric artifact.
- Manifest содержит SHA-256 всех переданных файлов и параметры генерации данных.
