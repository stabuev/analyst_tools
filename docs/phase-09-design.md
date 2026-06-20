# Проект фазы 09: Прикладная статистика

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единую статистическую задачу, модель данных, роли библиотек и контракт итогового
статистического отчета.

## Результат фазы

Студент превращает точечную продуктовую метрику в статистический вывод с явной
популяцией, механизмом отбора, оценкой неопределенности, проверкой предпосылок и
ограничениями. Фаза не учит искать «значимость» ради решения: она учит сначала назвать,
что именно оценивается, из какой выборки это взято, какие assumptions нужны для
интервала или модели и что нельзя утверждать по этим данным.

Фаза состоит из четырех последовательных блоков:

1. `09/01`-`09/02`: популяция, sampling frame, выборочный механизм и распределения как
   рабочие модели метрик.
2. `09/03`-`09/06`: оценки, bias/variance, доверительные интервалы и bootstrap.
3. `09/07`-`09/09`: корреляция, линейная регрессия для вывода и диагностика модели.
4. `09/10`: робастные проверки чувствительности и итоговый statistical evidence report.

Суммарная длительность - 825 минут, или 13,75 часа.

## Границы содержания

- **Не вводный учебник матстата.** Фаза отбирает только те понятия, которые меняют
  действие аналитика: популяция, выборочная единица, estimator, standard error,
  interval, resampling unit, regression assumption и diagnostic failure.
- **Не повтор фазы 06.** Bootstrap из `06/06` использовался для визуальной
  неопределенности. Здесь bootstrap становится статистическим инструментом с явной
  единицей ресемплирования, coverage, degenerate cases и reproducible RNG.
- **Не экспериментальная фаза.** Randomization unit, A/A, SRM, MDE, power, peeking,
  CUPED, multiple testing и заранее заданный decision protocol остаются фазе 10.
- **Не причинный анализ.** Корреляция, стратификация и регрессия показывают связь и
  условное среднее, но не доказывают эффект фичи. DAG, confounders, colliders,
  propensity methods, DiD и sensitivity analysis остаются фазе 13.
- **Не временные ряды.** Данные фазы имеют cross-sectional user-level grain с фиксированным
  observation window. Forecasting, rolling backtesting, сезонность и prediction intervals
  для рядов остаются фазе 14.
- **Не ML-моделирование.** Линейная регрессия используется для интерпретации оценок,
  standard errors и diagnostics. Train/validation/test, predictive metrics,
  regularization, pipelines и leakage в моделях остаются фазе 15.
- **Не финальная доставка заказчику.** `09/10` собирает проверяемый statistical evidence
  package, но polished stakeholder memo, PDF/HTML/DOCX и интерактивная поставка остаются
  фазе 17.

## Роли инструментов

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| NumPy | Симуляции, repeated sampling, RNG, ручные формулы оценок и интервалов | Полный курс random processes и numerical statistics |
| pandas | Подготовка user-level таблиц, группировки, веса, сегменты и контроль grain | Новый обзор DataFrame API |
| SciPy | Probability distributions, `scipy.stats`, confidence intervals, bootstrap и непараметрические тесты | Полный обзор всех статистических функций и Bayesian modeling |
| statsmodels | OLS, coefficient tables, standard errors, robust covariance и regression diagnostics | Time series, GLM, mixed models и автоматический causal inference |
| DuckDB | Независимые проверки sampling frame, grain, дубликатов и reconciliation | Analytics engineering graph и warehouse-specific execution |
| Pandera/Pydantic | Контракты analysis spec, sampling plan и machine-readable assumptions | Production data quality platform и API schemas |
| Matplotlib/Seaborn | Небольшие диагностические графики: coverage, bootstrap distribution, residuals | Новая gallery визуализаций и dashboard layout |

Runtime-зависимости добавляются в корневой locked environment только вместе с первым
уроком, который реально использует библиотеку. В `09/02` добавлен SciPy и зафиксирован
как locked baseline `scipy==1.17.1`; statsmodels остается не добавленным до первого
урока с regression inference. Проверенные на 19 июня 2026 года официальные ориентиры:
SciPy v1.17 для `scipy.stats` и `bootstrap`, statsmodels 0.14.6 для
regression/diagnostics, NumPy v2.4 для `numpy.random.Generator`.

Проверенные официальные контракты:

- [SciPy: Statistical functions](https://docs.scipy.org/doc/scipy/reference/stats.html) -
  `scipy.stats` покрывает распределения, summary/frequency statistics, correlation
  functions и statistical tests, а regression/time series явно вынесены в statsmodels.
- [SciPy: `scipy.stats.bootstrap`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.bootstrap.html) -
  bootstrap считает confidence interval для произвольной statistic, поддерживает
  percentile/basic/BCa methods и новый keyword `rng` для воспроизводимости.
- [statsmodels: Linear Regression](https://www.statsmodels.org/stable/regression.html) -
  OLS/GLS/WLS, results classes и related linear-model APIs являются целевым уровнем для
  регрессии как инструмента вывода.
- [statsmodels: Regression Diagnostics](https://www.statsmodels.org/stable/diagnostic.html) -
  diagnostics покрывают non-linearity, heteroscedasticity, structural change,
  multicollinearity, normality и outlier/influence checks.
- [NumPy: Random Generator](https://numpy.org/doc/stable/reference/random/generator.html) -
  `Generator` поставляет распределения и воспроизводимые permutation/resampling операции,
  что остается базой для ручных симуляций.

## Единая статистическая задача и данные

Фаза использует вымышленный подписочный сервис, но не зависит от артефактов фазы 08. Рабочий
вопрос интеграционного проекта: «Можно ли доверять оценке ранней активации и выручки по
выборке пользователей, и какие ограничения нужно явно передать продуктовой или ML-команде
перед следующим решением?»

Основной набор данных - user-level statistical extract с фиксированным семидневным окном.
В `tiny` хранится небольшая конечная популяция и несколько выборок для ручной проверки; в
`sample` локально генерируется более крупная популяция для симуляций coverage, bias/variance
и regression diagnostics.

Таблицы:

| Таблица | Grain | Ключ |
|---|---|---|
| `population_users` | один eligible user в синтетической конечной популяции | `user_id` |
| `sampling_frame` | один user в sampling frame с eligibility и inclusion metadata | `user_id` |
| `sample_observations` | одно наблюдение sampled user с outcome-метриками | `user_id` |
| `segment_reference` | один разрешенный сегмент и его expected population share | `segment_id` |

Базовые поля `sample_observations`:

| Поле | Смысл |
|---|---|
| `user_id` | единица анализа и ресемплирования |
| `registered_at` | старт фиксированного семидневного окна |
| `platform` | `web`, `ios` или `android` |
| `acquisition_channel` | канал привлечения |
| `country` | страна пользователя |
| `plan` | тариф или продуктовый план |
| `inclusion_probability` | вероятность попадания в sampling frame или выборку |
| `response_probability` | вероятность наблюдать outcome после отбора |
| `sample_weight` | вес для weighted estimate, если он объявлен в spec |
| `observed_days` | доступная длина observation window |
| `sessions_7d` | число сессий за семь дней |
| `activated_7d` | бинарная ранняя активация |
| `onboarding_seconds` | длительность onboarding flow |
| `first_order_amount_rub` | сумма первого заказа, отсутствует без заказа |
| `support_tickets_7d` | число обращений в поддержку за семь дней |

Заложенные свойства и failure modes:

- coverage bias: часть low-end Android пользователей отсутствует в sampling frame;
- non-response: пользователи с длинным onboarding чаще теряют outcome-наблюдение;
- unequal inclusion probabilities и веса, которые нельзя игнорировать в estimator spec;
- дубликат `user_id` и несовпадение sample grain с unit of analysis;
- неполные observation windows для последних cohort dates;
- Bernoulli activation, skewed/lognormal revenue, count support tickets и heavy tails;
- малые сегменты, где normal approximation дает обманчиво узкие интервалы;
- Simpson-like reversal между aggregate и stratified association;
- nonlinear relationship между onboarding duration и sessions/activation;
- heteroscedastic residuals, high-leverage observations и multicollinearity в regression;
- outliers, при которых mean и OLS coefficient меняются сильнее, чем robust alternatives.

## Контракт статистического анализа

Каждый урок работает через machine-readable spec, чтобы студент фиксировал методологию до
расчета:

```text
question_id
target_population
sampling_unit
sampling_frame
inclusion_mechanism
response_mechanism
parameter
estimator
metric_column
eligible_population
filters
weights
alpha
confidence_level
resampling_unit
resampling_method
model_formula
assumptions
diagnostic_checks
decision_boundary
known_limitations
```

Spec не должен превращать статистику в бюрократию. Его задача - запретить неявные скачки
между «среднее в файле», «оценка для популяции», «эффект фичи» и «прогноз модели».

## Интеграционный мини-проект

`09/10` собирает поставку:

```text
statistical-evidence-report/
├── question.json
├── sampling/
│   ├── population-and-frame.json
│   └── sampling-audit.json
├── distributions/
│   └── distribution-cards.json
├── estimates/
│   ├── point-estimates.csv
│   ├── bias-variance.csv
│   ├── confidence-intervals.csv
│   └── bootstrap-intervals.json
├── association/
│   └── correlation-audit.json
├── regression/
│   ├── model-spec.json
│   ├── coefficients.csv
│   └── diagnostics.json
├── robustness/
│   ├── robust-estimates.csv
│   └── sensitivity.json
├── figures/
│   ├── sampling-bias.png
│   ├── interval-coverage.png
│   └── regression-diagnostics.png
├── report.md
└── manifest.json
```

Отчет обязан:

- назвать target population, sampling unit, sampling frame и механизм отбора;
- различать parameter, statistic, estimator и estimate;
- показать naive, weighted и robust estimates там, где это методологически нужно;
- построить интервалы с указанным confidence level и assumptions;
- проверить coverage на симуляции там, где урок заявляет интервал как repeated-sampling
  процедуру;
- выбрать resampling unit до запуска bootstrap и запретить ресемплировать строки, если
  unit of analysis - пользователь;
- показать correlation/stratified correlation без причинной формулировки;
- построить OLS coefficient table и diagnostics, не использовать regression как
  автоматическое доказательство эффекта;
- явно перечислить ограничения: coverage, non-response, model misspecification,
  outliers, small cells и observational nature;
- связать каждый claim с артефактом, metric/parameter id и проверкой предпосылок;
- выпустить SHA-256 manifest всех переданных файлов.

## Проверяемость

- Tiny-profile содержит ручные ожидаемые ответы для sampling frame, proportions, means,
  weighted estimates, simple intervals и OLS на маленькой матрице.
- Симуляции используют фиксированный `numpy.random.Generator`; тесты проверяют не точное
  случайное значение, а стабильные tolerances для coverage, bias и variance.
- Bootstrap tests фиксируют `rng`, `n_resamples`, resampling unit и shape bootstrap
  distribution; degenerate input должен возвращать понятный failure или warning report.
- Confidence interval tests проверяют формулу, alpha/confidence-level mapping и запрет
  интервала при нарушенном domain assumption.
- Correlation tests различают aggregate, stratified и shuffled-control association.
- Regression tests сверяют OLS coefficient table с ручным closed-form расчетом на tiny и
  statsmodels result на sample.
- Diagnostic tests проверяют machine-readable check ids, thresholds и flags, а не текст
  исключений или формат summary библиотеки.
- Final package test проверяет существование всех файлов, ссылки claims на artifacts и
  checksum manifest.
