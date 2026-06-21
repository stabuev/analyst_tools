# Статус проекта

> Этот файл — handoff для нового чата. Сначала проверьте `git status`: рабочее дерево
> может содержать более свежие изменения.

**Обновлено:** 21 июня 2026
**Ветка:** `main`
**Базовый коммит перед текущим этапом:** `7fac9fd` — завершение фаз 07–09

Локальная `main` была синхронизирована с `origin/main` перед проектированием фазы 10.
Рабочее дерево после текущего этапа содержит незакоммиченные изменения завершенной фазы
10 и проектирования фазы 11. Push и commit выполняются только по явной команде
пользователя. Перед продолжением проверьте актуальное состояние через `git status`.

## Цель

Собрать единый открытый курс по современным инструментам аналитика. Курс должен:

- сохранять структурную идеологию `ai-engineering-from-scratch`;
- поддерживать несколько профессиональных маршрутов внутри одной дорожной карты;
- завершать каждый урок проверяемым переиспользуемым артефактом;
- поставляться вместе со standalone static-сайтом в `site/`;
- работать после публикации на GitHub Pages или другом static hosting.

## Текущий снимок

- 19 фаз.
- 201 урок в программе.
- 111 завершенных уроков.
- 11 уроков в статусе `designed`.
- Фазы 00–10 полностью завершены.
- Фаза 10 «Эксперименты и A/B-тесты» завершена: готовы уроки `10/01`–`10/11`.
- Фаза 11 «Analytics Engineering» спроектирована: 11 уроков на 900 минут.
- Следующий содержательный этап — разработка урока `11/01`
  «Слои и контракты аналитических данных».
- Полный маршрут: 238–326 часов.
- Сайт содержит главную дорожную карту, каталог, маршруты, глоссарий и локальный прогресс.

Готовность по фазам: `00` — 6/6, `01` — 9/9, `02` — 9/9, `03` — 11/11,
`04` — 12/12, `05` — 11/11, `06` — 11/11, `07` — 10/10, `08` — 11/11,
`09` — 10/10, `10` — 11/11, `11` — 11/11 designed.

## Текущая работа

После коммита `83ee574` разработаны уроки `01/02`–`01/09`.

- `01/02`: declaration, locking, syncing, восстановление `.venv` и CLI
  `uv_project_check.py`;
- `01/03`: metadata, runtime/dev dependencies, `[tool.*]`, console scripts и CLI
  `pyproject_audit.py`;
- `01/04`: Jupyter architecture, kernelspec, runtime evidence и CLI
  `kernel_diagnostic.py`;
- `01/05`: clean notebook policy, top-down execution и CLI `notebook_audit.py`;
- `01/06`: importable package, data contract, `Decimal` и JSON CLI;
- `01/07`: явная Ruff policy, safe fixes и lint/format quality gate;
- `01/08`: behavioral pytest suite, boundaries, fixtures и parametrization;
- `01/09`: standalone GitHub Actions project, locked sync и workflow self-audit;
- все уроки содержат поведенческие тесты и развивающие ссылки на официальную
  документацию.

Фазы 00 и 01 завершены; в фазе 01 готовы девять из девяти уроков.

Перед фазой 02 добавлен корневой reproducible environment:

- runtime: NumPy 2.4.6;
- development: pytest 9.0.3, Ruff 0.15.17 и PyYAML 6.0.3;
- точные версии зафиксированы в `uv.lock`;
- GitHub Pages CI использует setup-uv 8.2.0, uv 0.11.21 и
  `uv sync --locked --dev`;
- валидатор требует `pyproject.toml` и `uv.lock`, repository test сверяет dependency
  contract и locked CI.

Фаза 02 полностью разработана:

- `02/01`–`02/03`: модель `ndarray`, предсказание форм и аудит `dtype`, диапазонов,
  пропусков и памяти;
- `02/04`–`02/06`: индексация и copy/view, broadcasting, нормализация и агрегаты по
  явным осям;
- `02/07`: воспроизводимые симуляции на локальном `numpy.random.Generator`;
- `02/08`: benchmark циклической и векторной реализации с проверкой эквивалентности,
  warm-up, повторами и медианой;
- `02/09`: интеграционный numerical quality gate для shapes, tolerances, деления,
  integer overflow и точности аккумулятора;
- каждый урок содержит самостоятельный артефакт, квиз и восемь behavioral tests.

Фаза 03 полностью разработана:

- все 11 уроков переведены в статус `complete`;
- суммарная длительность уроков — 990 минут, или 16,5 часа;
- каждый урок содержит документацию, executable example, behavioral tests, квиз и
  самостоятельный артефакт;
- суммарно фаза содержит 91 behavioral test;
- `03/11` реализует интеграционный проект по сборке и передаче order mart;
- runtime дополнен pandas 3.0.3 с учетом Copy-on-Write и нового string dtype;
- добавлены детерминированные `users`, `orders` и `order_items` с контрактом,
  известными дефектами и checksum-манифестом.

Фаза 04 полностью разработана:

- все 12 уроков получили тип, время, последовательные зависимости, измеримый результат и
  артефакт;
- суммарная длительность фазы — 1050 минут, или 17,5 часа;
- `04/12` назначен интеграционным проектом по сборке проверенных SQL-витрин;
- DuckDB 1.5.3 добавлен в runtime и зафиксирован в `uv.lock`;
- добавлены совместимые `users`, `orders`, `order_items` и `events`;
- committed `tiny` содержит 50 строк, локальный `sample` — 525 005 строк для анализа
  планов запросов;
- все 12 уроков переведены в статус `complete`;
- суммарно фаза содержит 98 behavioral tests;
- `04/01`–`04/05` покрывают grain, SELECT, NULL, агрегаты и безопасные JOIN;
- `04/06`–`04/09` покрывают CTE, окна, временные зоны и cohort matrix;
- `04/10`–`04/11` поставляют Python runner и сравнение `EXPLAIN ANALYZE`;
- `04/12` реализует интеграционную поставку `order_mart.csv`, `user_summary.csv` и
  checksum-manifest с явной границей SQL/Python/pandas.

Фаза 05 полностью разработана:

- все 11 уроков переведены в статус `complete`;
- суммарная длительность фазы — 840 минут, или 14 часов;
- каждый урок содержит документацию полного учебного цикла, executable example,
  behavioral tests, квиз и самостоятельный артефакт;
- суммарно фаза содержит 90 behavioral tests;
- `05/01`–`05/03` покрывают CSV, Excel и вложенный JSON через явные контракты;
- `05/04`–`05/07` реализуют безопасный HTTP download, pagination/retries, HTML parsing и
  параметризованный SQLAlchemy Core reader;
- `05/08`–`05/10` поставляют typed Parquet converter, Arrow compatibility report и
  partitioned dataset builder с анализом fragment pruning и small files;
- `05/11` собирает интеграционный resilient loader с raw cache, SHA-256, immutable
  versioned datasets и атомарным указателем `current.json`;
- добавлены 14 детерминированных fixtures и шесть машинных контрактов для CSV, Excel,
  JSON, HTML, SQL и Parquet;
- runtime дополнен openpyxl 3.1.5, Requests 2.34.2, Beautiful Soup 4.15.0,
  SQLAlchemy 2.0.50 и PyArrow 24.0.0;
- ограничение pandas roundtrip, который не сохраняет Arrow field-level
  `nullable=False`, явно зафиксировано в compatibility report;
- глубокая Arrow memory model оставлена фазе 12, а оформление Excel-выдачи — фазе 17.

Фаза 06 полностью разработана:

- все 11 уроков переведены в статус `complete`;
- суммарная длительность — 930 минут, или 15,5 часа;
- уроки образуют последовательность от visual question brief и аудита данных до
  воспроизводимого EDA-report;
- Matplotlib отвечает за явные Figure/Axes и статический экспорт, Seaborn — за
  статистические сравнения и facets, Plotly — за exploratory drill-down, Altair — за
  проверяемую декларативную спецификацию;
- общий датасет `user_journeys` имеет grain «один пользователь и одно семидневное окно»
  и profiles `tiny` и `sample`;
- в данные заложены неполные окна наблюдения, дубликат, структурные пропуски,
  heavy tails, composition effect, Android regression и группы разного размера;
- `06/11` назначен интеграционным проектом: report.md, static figures, interactive
  appendix, Vega-Lite specs и checksum-manifest;
- границы со статистикой, надежностью, причинным анализом и доставкой закреплены в
  `docs/phase-06-design.md`;
- runtime дополнен Matplotlib 3.11.0, Seaborn 0.13.2, Plotly 6.8.0 и Altair 6.2.1;
- `06/01`–`06/02` поставляют visual question brief и машинный аудит grain, типов,
  missingness, диапазонов, дубликатов и observation windows;
- `06/03`–`06/06` покрывают явные Figure/Axes, histogram и ECDF, стратифицированные
  связи и percentile bootstrap с provenance;
- `06/07`–`06/10` поставляют faceted Seaborn panel, standalone Plotly explorer,
  валидированную Vega-Lite specification и accessibility review checklist;
- `06/11` собирает question, audit, report.md, PNG/SVG, standalone HTML, linked spec,
  visual review и checksum manifest;
- суммарно фаза содержит 91 behavioral test;
- детерминированный `tiny` profile содержит 25 строк и 24 уникальных пользователя,
  локальный `sample` генерирует 20 001 строку с одним дубликатом.

Фаза 07 полностью разработана:

- десять последовательных уроков рассчитаны на 825 минут, или 13,75 часа;
- базовый pytest и GitHub Actions из фазы 01 не повторяются: они применяются к
  многостадийным pipeline и доменным failure classes;
- общий order-quality pipeline использует `users`, `orders` и `order_items`;
- матрица дефектов покрывает grain, null/orphan keys, schema/type drift,
  reconciliation, configuration, regression, freshness, volume и atomic publication;
- runtime дополнен Pandera 0.31.1 и Pydantic 2.13.4, development environment —
  Hypothesis 6.155.2;
- `07/01` реализует CLI `order-invariant-gate`: проверяет ключи, status, currency,
  денежный домен и timezone и сверяет pandas-агрегаты независимым `Decimal`-контролем;
- committed `tiny` содержит 6 users, 10 orders и 12 order items; локальный `sample`
  генерирует 1 000 users и 5 000 orders;
- границы фазы и интеграционный reliable order pipeline зафиксированы в
  `docs/phase-07-design.md`.
- `07/02`–`07/04` поставляют contract-focused stages, фабрику 12 классов дефектов и
  Hypothesis suite для денежных агрегатов и дедупликации;
- `07/05`–`07/07` реализуют версионированный Pandera-контракт, strict Pydantic config и
  восемь независимых DuckDB violation queries;
- `07/08`–`07/09` добавляют reviewed semantic golden, точный JSON-path diff и монитор
  freshness, volume, null и duplicate rates;
- `07/10` собирает immutable version с Parquet/CSV mart, пятью quality reports,
  JSONL telemetry, checksum manifest и атомарным `current.json`;
- суммарно фаза содержит 60 behavioral tests.

Фаза 08 спроектирована:

- 11 последовательных уроков на 12-16 часов ведут от дерева метрик и tracking plan к
  активности, воронкам, когортам, retention, монетизации, сегментации, guardrails,
  аномалиям и финальной рекомендации;
- границы закреплены в `docs/phase-08-design.md`: фаза не подменяет статистический
  вывод, A/B-эксперименты, причинный анализ, production SDK-интеграцию, финансовую LTV
  модель и time-series forecasting;
- единая продуктовая задача использует события, сессии, подписки, заказы, поддержку и
  календарь релизов вымышленного подписочного сервиса;
- финальный артефакт `08/11` — `product-problem-investigation/` с `metric-tree.json`,
  `tracking-plan.json`, `metric-specs.json`, metric tables, anomalies, report,
  recommendation и checksum manifest;
- новых обязательных библиотек не требуется: фаза переиспользует pandas, DuckDB, NumPy,
  Pandera/Pydantic и визуальный стек из фаз 03-07.

Урок `08/01` «Дерево метрик» разработан:

- добавлен общий продуктовый dataset фазы 08 с `users`, `sessions`, `events`,
  `subscriptions`, `orders`, `support_tickets`, `release_calendar`, контрактом и
  воспроизводимым генератором tiny/sample;
- урок строит дерево `activation_rate_7d` с input-метриками
  `onboarding_completion_rate`, `paywall_to_trial_conversion_7d` и guardrails
  `support_ticket_rate_7d`, `subscription_cancel_rate_14d`;
- артефакт `metric-tree-validator` проверяет роли outcome/input/guardrail, связи,
  совпадение tree/specs, denominator, source tables, validation checks и направление
  риска guardrail-метрик;
- lesson suite содержит 9 behavioral tests.

Урок `08/02` «Событийная модель продукта» разработан:

- добавлен machine-readable `tracking_plan.json` для 12 продуктовых событий фазы 08:
  `app_open`, signup, onboarding, activation, paywall, trial, subscription, order и
  support events;
- артефакт `event-model-validator` проверяет обязательные колонки, уникальность
  `event_id`, известные event names и versions, required properties, identity policy,
  timezone-aware timestamps, `received_at >= occurred_at`, late arrivals, mobile
  `app_version` и ссылки `used_by_metrics` на metric specs из `08/01`;
- lesson suite содержит 12 behavioral tests, включая неизвестные события, version drift,
  невалидный `properties_json`, пустой `user_id`, duplicate delivery и late arrival.

Урок `08/03` «Активность и активная аудитория» разработан:

- добавлен `activity_spec.json` с grain `user_id`, meaningful active events, окнами
  1/7 дней, business timezone `Europe/Moscow`, eligible population и исключением test
  users;
- артефакт `active-audience-calculator` строит `activity.csv` с `eligible_users`,
  `active_users`, `activity_rate`, `active_event_count` и флагом `is_complete_window`;
- quality report проверяет activity spec, связь active events с tracking plan,
  обязательные колонки, уникальность `event_id`/`user_id`, identity active events,
  timezone-aware timestamps и наличие activity rows;
- lesson suite содержит 12 behavioral tests: zero-activity days, incomplete rolling
  windows, test-user exclusion, duplicate delivery, missing `user_id`, timezone
  conversion и CLI failure для invalid spec.

Урок `08/04` «Воронки и неоднозначность конверсии» разработан:

- добавлен `funnel_spec.json` с closed funnels для activation и paywall-to-trial,
  unit `user_id`, strict ordering, conversion window 7 дней, business timezone
  `Europe/Moscow` и исключением test users;
- артефакт `funnel-calculator` строит `funnel.csv` с `units`,
  `conversion_from_start`, `conversion_from_previous` и `dropoff_from_previous`;
- калькулятор поддерживает units `user_id`, `session_id`, `user_day`, strict/loose
  ordering, дедупликацию `event_id`, проверку step events через tracking plan и
  late-arrival policy;
- lesson suite содержит 12 behavioral tests: эталонные funnel counts, duplicate
  delivery, unknown step event, unsupported unit, missing `user_id`, strict versus
  loose order, cross-session, cross-day, late arrivals и CLI failure для invalid spec.

Урок `08/05` «Когортный анализ» разработан:

- добавлен `cohort_spec.json` для daily cohort matrix: cohort date из `registered_at`,
  unit `user_id`, age_day 0-7, business timezone `Europe/Moscow`, исключение test users
  и политика `blank_rate` для incomplete windows;
- артефакт `cohort-matrix-calculator` строит `cohorts.csv` с `cohort_size`,
  `active_users`, `activity_rate`, `is_complete_window` и `active_event_count`;
- расчет использует active events из `08/03` `activity_spec.json`, проверяет их связь с
  tracking plan, дедуплицирует `event_id`, фиксирует complete/incomplete windows против
  `observation_end_date` и не маскирует incomplete windows нулями;
- lesson suite содержит 13 behavioral tests: эталонные cohort counts, full grid, zero
  activity cells, blank incomplete rates, test-user exclusion, duplicate delivery,
  missing `user_id`, unknown active event, age-day continuity, timezone conversion,
  observation end override, late arrivals и CLI failure для invalid spec.

Урок `08/06` «Retention и возвращаемость» разработан:

- добавлен `retention_spec.json` для `active_retention`: start source `registered_at`,
  unit `user_id`, return events из `activity_spec`, age_day 1-7, business timezone
  `Europe/Moscow`, исключение test users и политика `blank_rate` для incomplete windows;
- артефакт `retention-calculator` строит `retention.csv` с режимами `exact_day` и
  `on_or_after`, фиксированным `cohort_size`, `retained_users`, `retention_rate`,
  границами return window, `is_complete_window` и `return_event_count`;
- расчет дедуплицирует `event_id`, не считает day 0 activity возвращением, проверяет
  return events против `activity_spec` и tracking plan, фиксирует complete/incomplete
  windows против `observation_end_date` и не маскирует incomplete windows нулями;
- lesson suite содержит 14 behavioral tests: full retention grid, sample CSV parity,
  day-0 exclusion, exact-day versus on-or-after semantics, incomplete on-or-after
  horizon, duplicate delivery, missing `user_id`, unknown return event, age-day
  continuity, unsupported modes, observation end override, timezone conversion, late
  arrivals и CLI failure для invalid spec.

Урок `08/07` «Выручка, ARPU и LTV» разработан:

- добавлен `monetization_spec.json` для `cohort_monetization`: cohort date из
  `registered_at`, unit `user_id`, revenue windows D0/D7, business timezone
  `Europe/Moscow`, исключение test users, явные paid/refunded/pending order statuses,
  subscription lifecycle statuses и политика `blank_metrics` для incomplete windows;
- артефакт `monetization-calculator` строит `monetization.csv` с `gross_revenue_rub`,
  `refund_amount_rub`, `realized_revenue_rub`, `arpu_rub`, `arppu_rub`, `ltv_rub`,
  paid/refunded/pending order counts, subscription starts, cancellations и
  `is_complete_window`;
- расчет считает деньги на grain `order_id`, дедуплицирует `order_id` и
  `subscription_id`, не считает pending orders выручкой, показывает refunded orders как
  gross/refund с нулевой realized revenue, считает subscriptions только как lifecycle
  signals и защищает результат от many-to-many revenue join multiplication;
- lesson suite содержит 15 behavioral tests: эталонные D0 ARPU/LTV, sample CSV parity,
  refund и pending semantics, blank incomplete LTV windows, cancellations only in
  complete windows, duplicate orders/subscriptions, unknown users, currency mismatch,
  negative amount, revenue-window contract, timezone conversion, no join multiplication
  и CLI failure для invalid spec.

Урок `08/08` «Сегментация без самообмана» разработан:

- добавлен `segmentation_spec.json` для `activation_rate_d0_by_segment`: cohort periods
  baseline/comparison, unit `user_id`, activation event `feature_value_seen`, business
  timezone `Europe/Moscow`, исключение test users, predeclared dimensions
  `platform`/`acquisition_channel`, exploratory dimension `country` и
  `minimum_cell_size`;
- артефакт `segmentation-calculator` строит `segments.csv` с overall,
  `segment_metric` и `decomposition` rows, `traffic_share`, `is_reportable`,
  `is_exploratory`, within-segment effect, composition effect и overall delta;
- расчет проверяет dimensions против `users.csv`, activation event против tracking plan,
  primary decomposition dimension против predeclared status, дедуплицирует `event_id`,
  отлавливает missing/unknown `user_id`, late arrivals и запрещает causal claims без
  эксперимента;
- lesson suite содержит 15 behavioral tests: эталонные segment rates, sample CSV parity,
  exploratory flags, minimum cell size, predeclared primary dimension, unknown activation
  event, duplicate delivery, missing/unknown `user_id`, late arrivals, timezone
  conversion, observation end override, causal-claim guard, decomposition sum и CLI
  failure для invalid spec.

Урок `08/09` «Guardrail-метрики» разработан:

- добавлен `guardrail_spec.json` для трех рисков: `support_ticket_rate_7d`,
  `subscription_cancel_rate_14d` и `refund_rate_7d`, с periods baseline/comparison,
  business timezone `Europe/Moscow`, observation end, `risk_direction=up_is_bad`,
  `max_rate`, `max_delta`, complete-window policy и overall decision rules;
- артефакт `guardrail-calculator` строит `guardrails.csv` с metric и assessment rows,
  baseline/comparison values, absolute delta, threshold breach, decision status
  `breached`/`watch`/`ok`/`incomplete` и итоговым `overall_decision`;
- расчет проверяет guardrails против metric specs для уже объявленных guardrail-метрик,
  дедуплицирует tickets/subscriptions/orders, проверяет known users, timezone-aware
  timestamps, lifecycle cancelled subscriptions и refund domain по валюте, статусу и
  неотрицательной сумме;
- lesson suite содержит 15 behavioral tests: threshold breaches, sample CSV parity,
  duplicate tickets/subscriptions/orders, unknown support users, subscription lifecycle,
  refund domain, metric spec role/direction, incomplete windows, watch status,
  timezone conversion, test-user exclusion и CLI failure для invalid spec.

Урок `08/10` «Аномалии продуктовых метрик» разработан:

- добавлен `anomaly_spec.json` с periods baseline/comparison, quality gates для
  freshness, duplicate IDs, late arrivals, required events, event volume и tracking
  completeness, thresholds для guardrail delta, composition effect и release window;
- артефакт `anomaly-detector` строит `anomalies.json` с `quality_gates`,
  `summary.by_classification` и candidates классов `data_quality`, `composition`,
  `calendar_effect`, `product_signal`;
- расчет блокирует `product_signal`, если quality gates не прошли, связывает breached
  guardrails с segment decomposition и release calendar и не формулирует causal claim по
  календарному совпадению;
- lesson suite содержит 13 behavioral tests: эталонные classifications, sample JSON
  parity, duplicate event IDs, unknown event names, missing required events, late
  arrivals, freshness, received-before-occurred, volume gate, thresholds и CLI failure
  для failed gates.

Урок `08/11` «Бизнес-вывод и рекомендация» разработан:

- добавлен `product_problem_builder.py`, который собирает
  `product-problem-investigation/` из артефактов `08/01`–`08/10`: brief, metric tree,
  metric specs, tracking plan, metric tables, anomalies, audits, figures, report,
  recommendation и checksum manifest;
- recommendation выбирает `investigate`, отклоняет автоматический `continue` из-за
  breached guardrails, не выбирает немедленный rollback без causal evidence и фиксирует
  next steps по Android paywall release, support/cancel/refund разбору и будущему
  experiment/holdout;
- builder проверяет decision boundary, cited claims, существование artifact paths,
  разрешение `metric_id`, запрет unsupported causal wording и SHA-256 manifest;
- lesson suite содержит 14 behavioral tests: delivery files, manifest verification,
  sample package parity, machine-readable recommendation, evidence-map checks,
  causal-claim guard, uncited/unknown/invalid decision failures, event/metric audits,
  byte-identical metric copies, PNG figures, CLI и missing source failure.

Фаза 09 полностью разработана:

- 10 последовательных уроков рассчитаны на 825 минут, или 13,75 часа;
- границы закреплены в `docs/phase-09-design.md`: фаза систематизирует sampling
  assumptions, uncertainty, confidence intervals, bootstrap, correlation, regression
  inference, diagnostics и robust sensitivity checks;
- фаза самостоятельна для product и ML-маршрутов и не зависит от артефактов фазы 08;
- единая статистическая задача использует user-level extract подписочного сервиса:
  `population_users`, `sampling_frame`, `sample_observations`, `segment_reference`;
- итоговый артефакт `09/10` — `statistical-evidence-report/` с sampling audit,
  distribution cards, point estimates, bias/variance, intervals, bootstrap, correlation
  audit, OLS diagnostics, robust checks, report и checksum manifest;
- SciPy добавлен в `09/02` и зафиксирован в locked runtime как 1.17.1; statsmodels
  добавлен в `09/08` и зафиксирован как 0.14.6 вместе с `patsy`.

Урок `09/01` «Популяция, выборка и механизм отбора» разработан:

- добавлен общий dataset фазы 09 с таблицами `population_users`, `sampling_frame`,
  `sample_observations`, `segment_reference`, контрактом и детерминированным генератором
  tiny/sample;
- tiny profile содержит 8 eligible non-test users и одного test user; sampling frame
  пропускает `U006`, создавая undercoverage для low-end Android, а sample содержит
  segment-level non-response без структурной поломки;
- артефакт `sampling-frame-auditor` проверяет required spec fields, sampling unit,
  ключи, связи population/frame/sample, probability domain, inverse-probability weights,
  complete observation windows, segment coverage, segment response и unequal inclusion
  probabilities;
- report разделяет blocking errors и warning-level estimation risks: warning-и не ломают
  CLI, но должны идти в limitations будущих estimators и intervals;
- lesson suite содержит 10 behavioral tests: structural-valid/warning baseline,
  segment response warning, manual missing frame user, duplicate sample grain, unknown
  sample user, incomplete window, invalid probability/weight, unsupported sampling unit,
  CLI output и blocking-error exit code.

Урок `09/02` «Распределения как модели» разработан:

- добавлен SciPy в locked runtime (`scipy==1.17.1`) и repository dependency contract;
- артефакт `distribution-card-builder` строит карточки распределений для
  `activation_7d`, `first_order_amount_rub_positive`, `support_tickets_7d` и
  `onboarding_seconds`;
- карточки фиксируют family, SciPy API, support, observed `n`, параметры, empirical
  summaries, checks, assumptions, failure modes и limitations;
- revenue нули сохраняются как отдельная mass перед lognormal positive fit, а
  `onboarding_seconds=0` блокируется как нарушение support `x > 0`;
- Poisson count card проверяет non-negative integer support и mean/variance dispersion;
- lesson suite содержит 13 behavioral tests: model coverage, ручной Bernoulli parameter,
  positive-revenue lognormal fit, Poisson diagnostics, onboarding right-tail warning,
  committed cards parity, invalid boolean, negative revenue, fractional count, zero
  duration, unknown metric column, CLI success/failure и example output.

Урок `09/03` «Оценки и свойства оценок» разработан:

- добавлен артефакт `estimator-runner`, который читает `sample_observations.csv`,
  `estimator_spec.json`, upstream sampling audit из `09/01` и distribution cards из
  `09/02`;
- runner выпускает `point_estimates.csv` и `estimator_report.json` для пяти оценок:
  naive activation proportion, weighted activation proportion, weighted first-order
  revenue mean, onboarding median и weighted support-ticket rate;
- estimator spec явно разделяет parameter, statistic, estimator и estimate, задает
  weight column, distribution-card reference, standard-error method и limitations;
- sampling audit warning ids (`frame_segment_coverage`, `sample_segment_response`,
  `unequal_inclusion_probabilities_declared`) переносятся в limitations каждого estimate;
- quantile standard error сознательно отложен до bootstrap, а weighted estimates показывают
  `sum_weights` и approximate effective sample size;
- lesson suite содержит 17 behavioral tests: baseline estimates, parameter/statistic/
  estimator contract, ручные activation controls, weighted revenue/rate, quantile SE
  deferral, committed CSV/JSON parity, missing card/column, zero weight, unknown
  estimator, invalid sampling audit, CLI success/failure и example output.

Уроки `09/04`–`09/10` разработаны:

- `09/04` добавляет `bias-variance-simulator`: repeated-sampling simulation для полной
  eligible population, coverage-biased frame и unequal frame с non-response; report
  фиксирует bias, variance, MSE и показывает, что маленькая variance может быть
  стабильно неверной.
- `09/05` добавляет `confidence-interval-calculator`: normal proportion и Student t
  intervals, coverage simulation, warning/blocking assumption checks и явный отказ
  выпускать lower/upper при нарушенном `minimum_n`.
- `09/06` добавляет `bootstrap-interval-builder`: percentile/basic/BCa intervals,
  `resampling_unit=user_id`, paired mode, fixed RNG, degenerate distribution diagnostics
  и bootstrap manifest.
- `09/07` добавляет `correlation-auditor`: Pearson/Spearman, shuffled controls,
  stratified sign reversal, constant-stratum warnings и машинный запрет causal wording.
- `09/08` добавляет `ols-inference-runner`: design matrix из model spec, ручной
  `np.linalg.lstsq`, `statsmodels.OLS`, coefficient table, standard errors, confidence
  intervals и claim type `conditional_association_not_causality`.
- `09/09` добавляет `regression-diagnostics-checker`: residuals, condition number, VIF,
  leverage, Cook distance, skipped formal tests for tiny n, warning flags и PNG diagnostics.
- `09/10` добавляет `robust-evidence-packager`: финальный
  `statistical-evidence-report/` с upstream artifacts, robust estimates,
  Mann-Whitney sensitivity, figures, `report.md` и SHA-256 manifest.
- Новые lesson suites: `09/04` — 12 tests, `09/05` — 11, `09/06` — 11, `09/07` — 9,
  `09/08` — 10, `09/09` — 10, `09/10` — 9.

Фаза 10 полностью разработана:

- 11 последовательных уроков рассчитаны на 945 минут, или 15,75 часа;
- границы закреплены в `docs/phase-10-design.md`: фаза покрывает experiment protocol,
  randomization unit, A/A, SRM, MDE/power, effect estimation, bootstrap, CUPED,
  multiple testing, peeking, heterogeneity и decision protocol;
- фаза переиспользует продуктовые постановки фазы 08 и статистические инструменты фазы
  09, но не уходит в production experimentation platform, Bayesian/bandit designs,
  causal DAG/quasi-experiments или polished delivery;
- единая задача — A/B-тест нового paywall/onboarding hint для Android в вымышленном
  подписочном сервисе с guardrails по support tickets, cancellations и refunds;
- итоговый артефакт `10/11` — `experiment-decision-package/` с protocol, assignment
  audit, A/A/SRM, power plan, primary/guardrail effects, bootstrap/CUPED checks,
  multiple-testing policy, peeking audit, segment report, decision и checksum manifest;
- новых обязательных библиотек не добавлено: фаза использует pandas, DuckDB, NumPy,
  SciPy, statsmodels, Pandera/Pydantic и визуальный стек, уже введенные ранее.

Урок `10/01` «Гипотеза и целевая метрика» разработан:

- добавлен первый experiment extract фазы 10 с таблицами `experiments`,
  `experiment_variants`, `users`, `events`, `orders`, `subscriptions`,
  `support_tickets`, `metric_baselines`, `pre_experiment_metrics`, контрактом и
  tiny-manifest;
- урок фиксирует pre-registered protocol для A/B-теста Android paywall/onboarding hint:
  variants, eligible population, primary metric `activation_rate_7d`, guardrails
  `support_ticket_rate_7d`, `subscription_cancel_rate_14d`, `refund_rate_7d`,
  secondary metrics, metric windows, alpha/power/MDE, policies и decision rule;
- артефакт `experiment-protocol-validator` проверяет required fields, variants и traffic
  allocation, timeline, design parameters, eligible population, metric roles, metric
  windows, source tables, guardrail risk directions, CUPED covariates и связь decision
  rule с primary/guardrails;
- lesson suite содержит 13 behavioral tests.

Урок `10/02` «Единица рандомизации» разработан:

- добавлены `randomization_spec.json`, deterministic `assignment_engine.py`,
  assignment/exposure fixtures и расширенный tiny experiment extract с `device_id` и
  `household_id` для interference checks;
- engine строит stable hash buckets по `salt:experiment_id:assignment_unit_id`,
  назначает eligible Android non-test users в control/treatment и формирует exposure
  records из первого `paywall_viewed`;
- audit проверяет randomization spec против protocol, one-unit-one-variant, exact
  eligibility match, stable bucket/variant, balance tolerance, unique exposure IDs,
  exposure timing, assignment/exposure variant consistency и shared interference units;
- lesson suite содержит 14 behavioral tests.

Урок `10/03` «A/A-тест и Sample Ratio Mismatch» разработан:

- добавлены `randomization_health_spec.json`, `randomization_health.py` и committed
  `randomization_health_report.json`;
- diagnostic читает assignments/exposures из `10/02`, pre-treatment metrics и protocol,
  проверяет assignment SRM, exposure SRM, telemetry loss, completeness pre-period metrics,
  standardized covariate balance и exact permutation A/A pseudo-outcomes;
- blocking failures отделены от warning diagnostics: baseline tiny готов к A/B-анализу
  по SRM/telemetry, но честно показывает warning по covariate balance на пяти users;
- lesson suite содержит 12 behavioral tests.

Урок `10/04` «MDE, мощность и размер выборки» разработан:

- добавлены `power_spec.json`, `power_planner.py`, committed `power_plan.json`,
  `mde_grid.csv` и `power_curve.png`;
- planner проверяет upstream `randomization_health_report.json`, затем считает sample
  size для primary proportion `activation_rate_7d` через `NormalIndPower` и для mean
  metric `realized_revenue_per_user_7d` через `TTestIndPower`;
- baseline `0.30`, MDE `+0.03`, alpha `0.05`, power `0.8` дают `2964` users per
  variant для primary metric; planned `12000` per variant дает power `0.999609`;
- MDE grid показывает trade-off для `+1`–`+5` п.п., а simulation sanity check сверяет
  required sample с target power;
- lesson suite содержит 9 behavioral tests.

Урок `10/05` «Сравнение средних и долей» разработан:

- добавлены `effect_spec.json`, `experiment_effect_calculator.py`, committed
  `metric_observations.csv`, `effect_results.csv` и `assumption_checks.json`;
- calculator использует protocol, metric specs, randomization health report и power plan
  из `10/01`–`10/04`, строит user-level observations для primary, guardrails и
  secondary metrics от exposure window;
- effects считаются как absolute/relative lift, confidence interval и p-value:
  proportions через two-sample z-test и Newcombe CI, mean revenue через Welch t-test,
  `refund_rate_7d` как ratio-of-sums;
- primary `activation_rate_7d` в tiny имеет lift `-0.666667` и статус
  `missed_primary_direction`, secondary trial signal остается `diagnostic_only`, а
  guardrails получают `watch`, если harmful delta не исключен interval-ом;
- assumption report сохраняет warnings по tiny sample против power plan,
  normal approximation cell counts и mean variance, поэтому artifact valid, но
  `ready_for_decision = false`;
- lesson suite содержит 9 behavioral tests.

Урок `10/06` «Bootstrap в экспериментах» разработан:

- добавлены `bootstrap_spec.json`, `experiment_bootstrap_analyzer.py`, committed
  `bootstrap_intervals.json`, `bootstrap_distribution.csv` и
  `resampling_manifest.json`;
- analyzer переиспользует `metric_observations.csv`, `effect_results.csv` и
  `assumption_checks.json` из `10/05`, не пересчитывая raw experiment metrics;
- bootstrap resampling идет по `user_id` внутри variants с fixed RNG, а permutation
  sensitivity перемешивает labels при фиксированных group sizes;
- для `refund_rate_7d` сохраняется paired numerator/denominator handling:
  tiny дает `148` invalid bootstrap resamples из `500`, `352` valid resamples и warning
  `paired_denominator_contains_zero_units`;
- primary `activation_rate_7d` получает bootstrap CI `[-1.0, 0.0]` и permutation
  p-value `0.401198`; secondary trial/revenue signals остаются sensitivity layer, а не
  decision;
- manifest фиксирует SciPy `1.17.1`, seeds, resampling unit, число resamples и ratio
  metrics с paired denominator;
- lesson suite содержит 9 behavioral tests.

Урок `10/07` «Снижение дисперсии и CUPED» разработан:

- добавлены `cuped_spec.json`, `experiment_cuped_adjuster.py`, committed
  `cuped_effects.csv`, `adjusted_observations.csv`, `variance_reduction_report.json` и
  `cuped_manifest.json`;
- adjuster переиспользует `metric_observations.csv`, `effect_results.csv` и
  `assumption_checks.json` из `10/05`, а pre-treatment ковариаты берет из
  `pre_experiment_metrics.csv` и сверяет с protocol `cuped_policy`;
- CUPED применяется к user-level primary, support guardrail, secondary trial conversion
  и revenue metrics через `Y - theta * (X - mean(X))`;
- primary `activation_rate_7d` использует `sessions_7d_pre`: raw lift `-0.666667`,
  adjusted lift `-0.416667`, `theta = -0.1`, `correlation = -0.288675`,
  `variance_reduction = 0.083333`;
- `refund_rate_7d` и `subscription_cancel_rate_14d` explicitly skipped: ratio metric
  требует paired numerator/denominator augmentation, а subscription denominator в tiny
  sparse;
- diagnostics блокируют post-treatment covariate, не объявленную в protocol ковариату,
  missing pre-metrics и invalid upstream effect analysis; tiny sample оставляет все
  analyzed metrics в warning status;
- lesson suite содержит 10 behavioral tests.

Урок `10/08` «Множественные проверки» разработан:

- добавлены `multiple_testing_policy.json`, `multiple_testing_policy_checker.py`,
  committed `multiple_testing_report.json`, `adjusted_results.csv` и
  `multiple_testing_manifest.json`;
- checker переиспользует protocol, `effect_results.csv`, bootstrap report,
  CUPED variance report, CUPED effects и assumption checks из уроков `10/01`–`10/07`,
  не пересчитывая experiment metrics в multiple-testing layer;
- policy объявляет primary, guardrail, secondary и exploratory families: primary
  проверяется без поправки, guardrails используют Holm/FWER, secondary и exploratory
  используют FDR/BH;
- ручные Bonferroni, Holm и FDR/BH поправки сверяются со `statsmodels.multipletests` и
  `scipy.stats.false_discovery_control`;
- primary `activation_rate_7d` остается failed: raw p-value `0.931981`, CUPED
  sensitivity p-value `0.804109`, practical status `missed_primary_direction`;
- secondary `paywall_to_trial_conversion_7d` получает adjusted p-value `0.025348`, но
  gate status `blocked_by_primary`, поэтому не может открыть launch decision;
- exploratory сегменты `activation_rate_7d_by_acquisition_channel_paid_search` и
  `activation_rate_7d_by_country_ru` получают adjusted p-values `0.021` и `0.008`, но
  остаются `not_pre_registered_launch_gate`, а country segment помечен как post-hoc;
- итоговый report valid, но `ready_for_decision = false`,
  `launch_allowed_by_multiple_testing = false`;
- lesson suite содержит 12 behavioral tests.

Урок `10/09` «Подглядывание и последовательный анализ» разработан:

- добавлены `peeking_policy.json`, `peeking_audit.py`, committed
  `sequential_monitoring_report.json`, `monitoring_schedule.csv`,
  `peeking_simulation.csv` и `peeking_manifest.json`;
- audit переиспользует protocol из `10/01`, power plan из `10/04` и
  multiple-testing report из `10/08`, не пересчитывая experiment metrics;
- peeking policy разделяет daily quality monitoring (`daily_sample_size`, `daily_srm`,
  `telemetry_loss`) и planned decision looks `interim_50`/`final`;
- O'Brien-Fleming-style Lan-DeMets alpha spending дает boundary `0.005575` на
  information fraction `0.5` и `0.05` на final look;
- observed `interim_50` имеет p-value `0.031`: он пересекает naive `0.05`, но не
  sequential boundary, поэтому status `continue_collecting`;
- два observed looks (`day_05_slack_peek`, `day_10_dashboard_refresh`) помечены как
  `unplanned_decision_peek` и блокируют decision-readiness;
- null simulation показывает false positive inflation: при пяти naive looks
  `naive_false_positive_rate = 0.14155`, O'Brien-Fleming spending дает `0.05955`;
- итоговый report valid, но `ready_for_decision = false` из-за unplanned decision looks
  и upstream multiple-testing launch block;
- lesson suite содержит 11 behavioral tests.

Урок `10/10` «Сегменты и неоднородные эффекты» разработан:

- добавлены `segment_policy.json`, `segment_effect_auditor.py`, committed
  `heterogeneity_report.json`, `segment_effects.csv`, `interaction_checks.csv` и
  `segment_manifest.json`;
- auditor переиспользует protocol, `metric_observations.csv`, users, multiple-testing
  report и peeking report, не пересчитывая upstream experiment metrics;
- predeclared dimensions `platform` и `acquisition_channel` сверяются с protocol
  `segment_policy`, а post-hoc `country` остается `exploratory_only`;
- `platform=android` имеет обе ветки и lift `-0.666667`, но не проходит
  протокольный minimum cell size `500`, поэтому остается diagnostic layer;
- `acquisition_channel` показывает типичный failure mode segment analysis на tiny:
  большинство строк получает `missing_variant`, потому что внутри сегмента нет одной из
  веток;
- все interaction checks получают `insufficient_overlap`, segment findings явно не
  становятся launch gates;
- lesson suite содержит 10 behavioral tests.

Урок `10/11` «Протокол решения и коммуникация» разработан:

- добавлены `decision_policy.json`, `experiment_decision_packager.py` и committed
  `experiment-decision-package/` с evidence, assignment audit, decision summary,
  markdown report, checksums и manifest;
- package собирает protocol, assignment/exposure evidence, A/A/SRM, power, raw effects,
  assumption checks, bootstrap intervals, CUPED report, multiple-testing policy/report,
  peeking audit и segment report;
- generated `assignment_audit.json` подтверждает one-unit-one-variant и соответствие
  exposure назначенному варианту: `5` assigned units, `5` exposed units,
  `control=3`, `treatment=2`;
- итоговое решение `hold`: launch запрещен из-за `missed_primary_direction`,
  `observed_sample_below_power_plan`, `multiple_testing_does_not_allow_launch`,
  unplanned decision looks и segment diagnostics; rollback не нужен, потому что
  guardrails имеют статус `watch`, а не breach;
- checksum manifest фиксирует SHA-256 digest для `23` package files и digest самого
  `checksums.json` в `manifest.json`;
- lesson suite содержит 10 behavioral tests.

## Следующий содержательный шаг

Фаза 11 спроектирована в `docs/phase-11-design.md`: зафиксированы границы analytics
engineering, роли dbt Core/local CLI, dbt-duckdb, DuckDB, SQLFluff, PyYAML/Pydantic и
pytest, общий customer revenue health mart, source/model/snapshot failure modes,
machine-readable mart contract и структура финального `analytics-mart-dbt/` package.

Разработать урок `11/01` «Слои и контракты аналитических данных»: начать фазу Analytics
Engineering, создать общий data mart context фазы 11 и первый проверяемый layer contract
artifact.

Фазы 00–10 завершены, фаза 11 спроектирована. Перед коммитом обязательно
прогнать полный набор проверок.

## Уже принятые решения

- Один курс с маршрутами, а не несколько независимых курсов.
- Общее ядро — фазы 00–07.
- Задача и модель данных появляются раньше библиотеки.
- Надежность, тесты и воспроизводимость вводятся с первых фаз.
- `uv` выбран основным менеджером окружений вместо Conda.
- Библиотеки курса фиксируются на актуальных стабильных версиях в `uv.lock`;
  обновление делается отдельным осознанным diff, без pre-release по умолчанию.
- SQL, продуктовая аналитика, эксперименты, analytics engineering и доставка результата
  являются самостоятельными фазами, а не приложениями к pandas или ML.
- FastAPI и Docker остаются факультативными способами доставки, а не обязательным финалом
  для каждого аналитика.
- `curriculum.json` — источник правды; дорожная карта, страницы фаз и данные сайта
  генерируются.
- Сайт не рендерит уроки самостоятельно: он показывает программу и ведет на готовые
  материалы в GitHub.

## Неопределенности

- GitHub Pages workflow добавлен, но фактическая публикация зависит от push и настройки
  Pages в репозитории.
- Пользовательский домен и аналитика посещений не выбраны.
- Состав факультативов может уточняться при разработке соответствующих фаз, но изменение
  не должно ломать пререквизиты основных маршрутов.

## Полная проверка

```bash
uv sync --locked --dev
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/render_curriculum.py --check
uv run --locked python scripts/render_outputs.py --check
uv run --locked python scripts/render_site.py --check
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/run_lesson_tests.py
```
