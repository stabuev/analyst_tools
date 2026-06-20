# История изменений

Здесь фиксируются заметные изменения программы, готовых уроков, сайта и контрактов
репозитория. Новые записи добавляются сверху. Формат основан на
[Keep a Changelog](https://keepachangelog.com/), но курс не обещает строгую семантическую
версионизацию до первого стабильного выпуска.

## [Unreleased]

### Добавлено

- Полностью завершена фаза 09 «Прикладная статистика»: 10 уроков, 13,75 часа,
  112 behavioral tests и финальный `statistical-evidence-report/` package с sampling
  audit, distribution cards, point estimates, bias/variance simulation, formula и
  bootstrap intervals, correlation audit, OLS inference, regression diagnostics,
  robust/nonparametric sensitivity checks, figures, report и SHA-256 manifest.
- Уроки `09/04`–`09/10`: `bias-variance-simulator`, `confidence-interval-calculator`,
  `bootstrap-interval-builder`, `correlation-auditor`, `ols-inference-runner`,
  `regression-diagnostics-checker` и `robust-evidence-packager`; statsmodels 0.14.6
  и patsy 1.0.2 добавлены в locked runtime для regression inference.
- Урок `09/03` «Оценки и свойства оценок» с `estimator-runner`,
  machine-readable estimator spec, upstream sampling audit/distribution-card checks,
  naive и weighted point estimates для proportion/mean/quantile/rate, standard error
  diagnostics и 17 behavioral tests.
- Урок `09/02` «Распределения как модели» с SciPy-based
  `distribution-card-builder`, карточками Bernoulli/binomial activation,
  lognormal positive revenue/duration, Poisson count diagnostics, support checks,
  limitations и 13 behavioral tests; SciPy 1.17.1 добавлен в locked runtime.
- Урок `09/01` «Популяция, выборка и механизм отбора» с общим dataset фазы 09
  (`population_users`, `sampling_frame`, `sample_observations`, `segment_reference`),
  CLI-аудитором sampling frame, coverage/non-response/weight diagnostics и 10
  behavioral tests.
- Фаза 09 «Прикладная статистика» спроектирована целиком: 10 уроков на 13,75 часа,
  самостоятельная user-level статистическая задача для product и ML-маршрутов, sampling
  frame, estimator specs, intervals, bootstrap, correlation audit, OLS diagnostics,
  robust sensitivity checks и интеграционный `statistical-evidence-report`.
- Полностью завершена фаза 08 «Продуктовая аналитика»: 11 уроков, 12-16 часов,
  единая событийная модель продукта и интеграционный `product-problem-investigation`
  package с metric/tracking contracts, metric tables, anomalies, report,
  recommendation и checksum manifest.
- Урок `08/11` «Бизнес-вывод и рекомендация» с CLI-builder'ом
  `product-problem-investigation/`, evidence-map, machine-readable recommendation,
  запретом unsupported causal claims, проверкой artifact paths/metric IDs и SHA-256
  manifest.
- Урок `08/10` «Аномалии продуктовых метрик» с anomaly spec, CLI-детектором
  `data_quality`/`composition`/`calendar_effect`/`product_signal` candidates,
  freshness/duplicate/late-arrival/tracking completeness gates и запретом product-signal
  интерпретации до прохождения quality gates.
- Урок `08/09` «Guardrail-метрики» с guardrail spec,
  CLI-калькулятором support ticket, subscription cancel и refund rates,
  `risk_direction=up_is_bad`, thresholds, complete-window policy, decision status и
  overall-блокировкой rollout при breached guardrails.
- Урок `08/08` «Сегментация без самообмана» с segmentation spec,
  CLI-калькулятором segment activation rates, predeclared/exploratory dimensions,
  minimum cell size, platform decomposition на within-segment/composition effects и
  запретом causal claims без эксперимента.
- Урок `08/07` «Выручка, ARPU и LTV» с monetization spec,
  CLI-калькулятором realized revenue, ARPU, ARPPU и fixed-window cohort LTV,
  paid/refunded/pending order semantics, cancelled subscriptions, complete-window
  policy и защитой от many-to-many revenue joins.
- Урок `08/06` «Retention и возвращаемость» с retention spec, CLI-калькулятором
  `exact_day`/`on_or_after` retention, fixed denominator, age_day 1-7,
  complete-window policy, дедупликацией событий и quality report.
- Урок `08/05` «Когортный анализ» с cohort spec, CLI-калькулятором daily cohort
  matrix, фиксированным denominator, age_day 0-7, complete/incomplete observation
  windows, дедупликацией событий и quality report для late arrivals.
- Урок `08/04` «Воронки и неоднозначность конверсии» с funnel spec,
  CLI-калькулятором closed funnels, strict/loose ordering, units `user_id`,
  `session_id`, `user_day`, conversion window, дедупликацией событий и quality report
  для late arrivals.
- Урок `08/03` «Активность и активная аудитория» с activity spec, CLI-расчетом
  DAU/rolling active users, eligible denominator, business timezone, исключением test
  users, дедупликацией событий и флагами неполных окон.
- Урок `08/02` «Событийная модель продукта» с machine-readable tracking plan,
  CLI-валидатором event names, versions, required properties, identity policy,
  duplicates, late arrivals, mobile `app_version` и связей событий с metric specs.
- Урок `08/01` «Дерево метрик» с продуктовым metric tree, machine-readable
  metric specs, CLI-валидатором ролей outcome/input/guardrail, знаменателей,
  окон, source tables, validation checks и направления риска guardrail-метрик.
- Для фазы 08 добавлен детерминированный продуктовый tiny dataset: users, sessions,
  events, subscriptions, orders, support tickets, release calendar, contract и
  воспроизводимый генератор.
- Фаза 08 «Продуктовая аналитика» спроектирована целиком: 11 уроков на 12-16 часов,
  единая событийная модель подписочного продукта, tracking plan, metric specs,
  product metrics от активности до LTV, guardrails, диагностика аномалий и
  интеграционное исследование продуктовой проблемы.
- Полностью завершена фаза 07 «Надежная аналитика»: 10 уроков, 825 минут,
  60 behavioral tests и единый order-quality pipeline от инвариантов и минимальных
  дефектов до Hypothesis, Pandera, Pydantic, SQL, golden regression, monitoring и
  атомарной публикации immutable mart.
- Корневой locked dependency contract дополнен Hypothesis 6.155.2, Pandera 0.31.1 и
  Pydantic 2.13.4.
- Фаза 07 «Надежная аналитика» спроектирована целиком: 10 последовательных уроков на
  13,75 часа, единый order-quality pipeline, матрица дефектов, Hypothesis, Pandera,
  Pydantic, SQL-reconciliation, regression tests и интеграционный quality gate.
- Урок `07/01` «Инварианты аналитического расчета» с ручным контрольным путем,
  CLI-проверкой структурных и алгебраических правил и behavioral tests.
- Полностью завершена фаза 06 «EDA и визуальное мышление»: 11 уроков, 91 behavioral
  test и артефакты от visual question brief и data audit до статических, интерактивных
  и декларативных визуализаций и интеграционного EDA-report с checksum manifest.
- Корневой locked dependency contract дополнен Matplotlib 3.11.0, Seaborn 0.13.2,
  Plotly 6.8.0 и Altair 6.2.1.
- Урок `06/01` «Вопрос раньше графика» с контрактом visual question brief,
  rubric выбора представления, предупреждением о причинной формулировке и девятью
  behavioral tests.
- Фаза 06 «EDA и визуальное мышление» спроектирована целиком: 11 последовательных
  уроков на 15,5 часа, единый `user_journeys` dataset, явные границы Matplotlib,
  Seaborn, Plotly и Altair и интеграционный воспроизводимый EDA-report.
- Полностью завершена фаза 05 «Источники и форматы данных»: 11 уроков, 90 behavioral
  tests, 14 детерминированных fixtures и самостоятельные артефакты от CSV/Excel/JSON
  contracts до устойчивого загрузчика с raw cache, SHA-256 и partitioned Parquet.
- Корневой locked dependency contract дополнен openpyxl 3.1.5, Requests 2.34.2,
  Beautiful Soup 4.15.0, SQLAlchemy 2.0.50 и PyArrow 24.0.0.
- Урок `05/01` «CSV и неоднозначность типов» с явным encoding/dialect/schema-контрактом,
  CP1251 fixtures, аудитором повреждённых строк и девятью behavioral tests.
- Фаза 05 «Источники и форматы данных» спроектирована целиком: 11 последовательных
  уроков на 14 часов с контрактами файловых форматов, устойчивым получением внешних
  данных, Arrow/Parquet-поставкой и интеграционным загрузчиком с кешем и checksum.
- Полностью завершена фаза 04 «SQL и DuckDB»: 12 уроков, 98 behavioral tests,
  самостоятельные CLI и SQL-артефакты от grain-аудита до когорт, планов запросов и
  интеграционной поставки `order_mart`/`user_summary` с checksum-manifest.
- Урок `04/01` «Grain, ключи и связи» с ручной моделью проверки ключа,
  DuckDB-аудитором primary/foreign keys, девятью behavioral tests и JSON quality gate.
- Фаза 04 «SQL и DuckDB» спроектирована целиком: 12 последовательных уроков на
  17,5 часа с измеримыми результатами, артефактами и интеграционной SQL-витриной.
- DuckDB 1.5.3 добавлен в корневой locked dependency contract курса.
- Для фазы 04 добавлены детерминированный tiny-набор `users`, `orders`,
  `order_items`, `events` и локальный sample-профиль более чем на 500 тысяч строк.
- Полностью завершена фаза 03 «pandas и табличные данные»: 11 уроков от модели
  DataFrame и nullable dtype до безопасных join, временных зон, method chaining и
  интеграционной order mart с manifest.
- Для фазы 03 добавлен 91 behavioral test и 11 самостоятельных артефактов: инспекторы
  grain и dtype, безопасные фильтры, преобразования, агрегации, merge, reshape,
  нормализаторы времени и категорий, pipeline и mart builder.
- Фаза 03 «pandas и табличные данные» полностью спроектирована: для 11 уроков
  зафиксированы тип, время, зависимости, измеримый результат и артефакт; `03/11`
  назначен интеграционным мини-проектом.
- Детерминированный tiny-набор `users`, `orders` и `order_items` для фазы 03 с
  машинным контрактом, известными дефектами и SHA-256 манифестом.
- pandas 3.0.3 добавлен в корневой locked dependency contract курса.
- Полностью завершена фаза 02 «NumPy и численные данные»: девять уроков от модели
  `ndarray` и shape-контрактов до воспроизводимых симуляций, benchmark и численного
  quality gate.
- Уроки `02/02`–`02/04` с предиктором форм, аудитором dtype и функциями числовой
  фильтрации с явной семантикой view/copy.
- Уроки `02/05`–`02/07` с ручной проверкой broadcasting, агрегатами по осям и
  симулятором распределения выборочного среднего на `numpy.random.Generator`.
- Уроки `02/08`–`02/09` с воспроизводимым benchmark векторизации и интеграционным
  quality gate для tolerances, деления, overflow и точности суммирования.
- Урок `02/01` «ndarray и модель массива» с разбором `ndim`, `shape`, `size`,
  `dtype`, ручной проверкой прямоугольной формы и CLI-инспектором числовых массивов.
- Корневой `uv.lock` и единый dependency-контракт курса: NumPy 2.4.6,
  pytest 9.0.3, Ruff 0.15.17 и PyYAML 6.0.3; GitHub Pages CI теперь
  восстанавливает locked environment перед проверками.
- Урок `01/09` «Автоматическая проверка в CI» со standalone GitHub Actions
  project, locked uv sync, минимальными permissions и self-audit workflow.
- Урок `01/08` «Первые проверки с pytest» с behavioral suite для воронки,
  параметризацией, fixtures, boundaries и domain errors.
- Урок `01/07` «Единый стиль и Ruff» с явной rule policy, safe fixes,
  formatter gate и тестами на настоящем Ruff.
- Урок `01/06` «От ноутбука к модулям и скриптам» с importable package,
  проверяемым data contract и JSON CLI.
- Урок `01/05` «Воспроизводимые ноутбуки» с чистым notebook, реальным
  top-down execution и CLI-аудитом скрытого состояния.
- Урок `01/04` «Jupyter, kernels и состояние» с диагностическим notebook,
  разбором kernelspec и CLI-сверкой фактического Python-процесса.
- Урок `01/03` «pyproject.toml как контракт проекта» с разделением runtime/dev
  зависимостей, настройками инструментов и CLI-аудитом manifest.
- Урок `01/02` «Окружения и зависимости с uv» с настоящим lock/sync workflow,
  восстановлением `.venv` и CLI-проверкой locked-окружения.
- Урок `01/01` «Версии Python и совместимость» с контрактом `requires-python`,
  selector-файлом и CLI для проверки фактического интерпретатора и матрицы версий.
- Урок `00/06` «Секреты и безопасная работа с данными» с env-контрактом,
  классификацией данных и CLI для создания и проверки безопасного шаблона проекта.
- Урок `00/05` «Ветки, pull request и ревью» с локальным feature-branch сценарием,
  трёхточечным diff и CLI-пакетом для подготовки аналитического ревью.
- Урок `00/04` «Git: история аналитического проекта» с локальным Git-сценарием и CLI для
  проверки истории, `.gitignore` и сфокусированности commits.
- Урок `00/03` «Терминал и файловая система» с Bash CLI для воспроизводимого аудита
  файлов, тестами необычных имён и разбором безопасных pipelines.
- Полностью завершена фаза 01 «Воспроизводимый проект»: девять уроков от версии Python
  и lockfile до Ruff, pytest и CI.
- Публичный минимум репозитория: кодекс поведения, шаблоны issue и pull request, индекс
  проектной документации.
- Навигация для учащихся и контрибьюторов в корневом README.

## [0.1.0] — 2026-06-12

### Добавлено

- Единая программа из 19 фаз и 201 урока с пятью профессиональными маршрутами.
- Завершенные уроки `00/01` «Карта профессии аналитика» и `00/02` «Диагностика Python и
  SQL».
- Контракт урока с исполняемым кодом, тестами, квизом, артефактом и дополнительным
  чтением.
- Генераторы дорожной карты, страниц фаз, каталога артефактов и данных сайта.
- Standalone static-сайт с дорожной картой, каталогом, маршрутами, глоссарием и локальным
  прогрессом.
- GitHub Pages workflow и проверки структуры курса.
- Агентские навыки для определения стартового уровня и проверки понимания фазы.
- Handoff-контекст для продолжения разработки в новых чатах.

### Изменено

- Исходная tool-first программа преобразована в problem-first курс с общим ядром,
  специализациями и несколькими итоговыми маршрутами.
