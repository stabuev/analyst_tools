# Инструменты аналитика

> От сырых данных к проверенному решению и воспроизводимому артефакту.

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-1f2937?style=flat-square" alt="Лицензия MIT"></a>
  <a href="ROADMAP.md"><img src="https://img.shields.io/badge/phases-19-2563eb?style=flat-square" alt="19 фаз"></a>
  <a href="ROADMAP.md"><img src="https://img.shields.io/badge/lessons-201-2563eb?style=flat-square" alt="201 урок"></a>
  <a href="https://github.com/stabuev/analyst_tools/actions/workflows/pages.yml"><img src="https://github.com/stabuev/analyst_tools/actions/workflows/pages.yml/badge.svg" alt="Проверка и публикация сайта"></a>
</p>

Открытый практический курс под лицензией MIT для аналитиков, которые уже знают основы
Python и SQL и хотят освоить современный рабочий процесс: получение и моделирование
данных, анализ, статистику, эксперименты, analytics engineering, машинное обучение и
доставку результата заказчику.

Курс организован по модели `ai-engineering-from-scratch`: материал разбит на фазы, каждая
фаза состоит из небольших самостоятельных уроков, а каждый урок заканчивается полезным
артефактом. При этом программа не заставляет проходить все темы линейно: после общего ядра
можно выбрать профессиональный маршрут.

## Как устроен курс

Каждый урок проходит единый цикл:

```text
Problem -> Concept -> Build It -> Use It -> Break It -> Verify It -> Ship It
```

- **Problem**: реальная аналитическая проблема и цена ошибки.
- **Concept**: модель данных, предпосылки и способ рассуждения.
- **Build It**: минимальная реализация без скрытой магии.
- **Use It**: решение средствами рабочей библиотеки или платформы.
- **Break It**: намеренно испорченные данные, неверный grain, leakage или edge cases.
- **Verify It**: тесты, контрольные расчеты и проверка интерпретации.
- **Ship It**: переиспользуемый аналитический артефакт.

Урок считается завершенным, когда код запускается в чистом окружении, проверки проходят,
а результат можно объяснить и передать другому человеку.

## С чего начать

**Вариант A — читать.** Откройте завершенный урок через [дорожную карту](ROADMAP.md).
Текст, код, упражнения и артефакт находятся в одной папке.

**Вариант B — открыть сайт.** Папка [`site/`](site/) содержит standalone static-сайт
с дорожной картой, маршрутами, каталогом и GitHub-ссылками на готовые уроки.

**Вариант C — клонировать и запускать.**

```bash
git clone https://github.com/stabuev/analyst_tools.git
cd analyst_tools
uv sync --locked --dev
uv run --locked python scripts/validate_course.py
```

**Вариант D — определить уровень.** В агенте, который поддерживает project skills:

```text
/find-your-level
```

После фазы:

```text
/check-understanding 3
```

Диагностика рекомендует стартовую фазу и маршрут, но не заменяет проверку практических
работ.

### Предварительные требования

- Базовый Python: функции, коллекции, условия и циклы.
- Базовый SQL: `SELECT`, `JOIN`, `GROUP BY`.
- Понимание среднего, дисперсии и идеи статистической гипотезы.
- Готовность запускать код и разбирать ошибки, а не только читать материалы.

Если база неуверенная, начните с диагностики фазы 00: она укажет конкретные пробелы и не
требует заранее выбирать специализацию.

## Маршруты

Все маршруты начинаются с фаз `0-7`.

| Маршрут | Рекомендуемые фазы | Часы | Результат |
|---|---|---:|---|
| Базовый аналитик | `0-10`, `17`, `18` | 160-224 | Исследование, эксперимент и готовый отчет |
| Продуктовый аналитик | `0-10`, `13`, `17`, `18` | 172-240 | Метрики, эксперименты и причинные выводы |
| Analytics Engineer | `0-7`, `11-12`, `17`, `18` | 148-208 | Проверенные витрины и производительные пайплайны |
| ML-аналитик | `0-7`, `9`, `12`, `15-18` | 174-242 | Честный baseline, интерпретация и доставка модели |
| Полный | `0-18` | 238-326 | Все специализации курса |

Полная программа и зависимости находятся в [ROADMAP.md](ROADMAP.md).

## Каждый урок поставляет инструмент

Урок заканчивается не только выполненным упражнением, но и именованным артефактом:
функцией, SQL-моделью, data contract, тестовым набором, шаблоном отчета, CLI, приложением,
prompt или agent skill. Завершенные артефакты публикуются в
[`outputs/index.json`](outputs/index.json).

Студент сначала строит минимальную прозрачную версию механизма, затем использует
production-библиотеку и сравнивает поведение. Для аналитики этот принцип означает не
«переписать pandas», а вручную вывести grain, формулу, реляционную операцию, симуляцию или
контрольный расчет.

## Структура репозитория

```text
.
├── curriculum.json       # источник правды о фазах и уроках
├── phases/               # страницы фаз и будущие материалы уроков
├── site/                 # standalone static-сайт курса
├── docs/                 # принципы курса и учебная предметная область
├── glossary/             # общие термины и заблуждения
├── outputs/              # каталог переиспользуемых артефактов
├── schemas/              # контракты lesson, quiz и artifact
├── .agents/skills/       # диагностика уровня и проверка понимания
├── scripts/              # генерация, scaffolding и валидация
├── tests/                # проверки структуры курса
├── LESSON_TEMPLATE.md    # обязательный формат урока
└── ROADMAP.md            # сгенерированная дорожная карта
```

Проектные решения и текущий статус собраны в [индексе документации](docs/README.md).

## Контекст для нового чата

Новый агент начинает с [`AGENTS.md`](AGENTS.md) и
[`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md). Критика исходного research-плана и
принятые изменения сохранены в
[`docs/research-baseline.md`](docs/research-baseline.md).

## Быстрая проверка

```bash
uv sync --locked --dev
uv run --locked python scripts/validate_course.py
uv run --locked python -m unittest discover -s tests
uv run --locked python scripts/run_lesson_tests.py
```

После изменения `curriculum.json` обновите документы:

```bash
uv run --locked python scripts/render_curriculum.py
uv run --locked python scripts/render_outputs.py
uv run --locked python scripts/render_site.py
```

Локальный запуск сайта:

```bash
python3 -m http.server 8000 --directory site
```

## Текущий статус

Архитектура курса, полная дорожная карта и standalone-сайт зафиксированы. Полностью
завершены фазы `0-14` и уроки `15/01`–`15/11`: 167 уроков от входной диагностики до
продуктовых экспериментов, analytics engineering, воспроизводимого multi-engine benchmark
package и причинного анализа. Фаза `13` «Причинный анализ» завершена как 11 уроков на 15,5 часа: causal
question/estimand, DAG/identification, backdoor adjustment, bad controls, g-formula,
matching, IPW/AIPW, DiD, RDD/IV, sensitivity/falsification и интеграционный `13/11`
causal-study-package с DoWhy-compatible workflow trace, EconML scope audit, checksum
manifest и финальной claim policy, которая блокирует single strong causal claim при
невыполненных assumptions. Фаза `14` «Временные ряды» спроектирована как 12 уроков на
15,75 часа: временной индекс, resampling, leakage-free rolling features, temporal leakage
audit, seasonal baseline, decomposition, ETS/ARIMA, rolling backtesting, forecast metrics,
prediction intervals и итоговый time-series forecast package; уроки `14/01`–`14/12`
завершены как time-index auditor, resampling pipeline, leakage-safe window feature
builder, seasonality profiler, temporal leakage auditor, baseline forecaster,
STL decomposition reporter, statsmodels forecast runner, rolling-origin backtester
и forecast metric evaluator с metric slices, suitability audit, MASE denominators
и weighted-MASE leaderboard policy, prediction interval calibrator с empirical coverage
report, calibration audit и uncertainty statements, а также финальный time-series
forecast packager с anomaly flags, decision report и checksum manifest.
Фаза `15` «Прикладное машинное обучение» спроектирована как 15 уроков на 19,5 часа:
ML problem framing, split protocol, metrics/cost policy, preprocessing, scikit-learn
Pipeline и ColumnTransformer, baselines, trees/ensembles, cross-validation, imbalance,
calibration, leakage audit, segment error analysis и итоговый model card package.
Урок `15/01` завершен как ML problem spec validator с deterministic tiny churn-risk
profile, readiness report и no-causal-claim boundary; `15/02` завершен как ML split
auditor с group/time split manifest, label-horizon checks и validation/test role
boundary; `15/03` завершен как classification metric evaluator с candidate score table,
validation-only threshold sweep, cost table, PR-oriented metrics и no-test-peeking gate;
`15/04` завершен как preprocessing contract checker с raw feature table,
train-fitted imputation/encoding/scaling state, transformed feature matrix,
unknown-category bucket audit и no-fit-before-split gate.
`15/05` завершен как scikit-learn Pipeline runner с единым fit/transform/predict
объектом, `pipeline_spec.json`, validation/test prediction report, serialized spec,
fit trace, unknown-category bucket audit и no-external-preprocessed-matrix gate.
`15/06` завершен как ColumnTransformer auditor с `column_transformer_spec.json`,
numeric/categorical/binary routes, routing table, transformed feature schema,
validation/test predictions, serialized route state и no-silent-dropped-columns gate.
`15/07` завершен как linear baseline trainer с `linear_baseline_spec.json`,
dummy/logistic sklearn `Pipeline` comparison, validation-only selection, coefficient
table, intercept/regularization report и warning, когда logistic baseline не бьет
dummy на tiny validation.
`15/08` завершен как tree diagnostic trainer с `tree_diagnostic_spec.json`,
depth-limited `DecisionTreeClassifier`, upstream linear-baseline handoff,
train-validation overfit report, readable rule export, node report и warning, когда
дерево хуже выбранного `dummy_prior` на validation.
`15/09` завершен как tree ensemble comparator с `tree_ensemble_spec.json`,
`RandomForestClassifier` внутри `Pipeline(ColumnTransformer, estimator)`, comparison
dummy/logistic/tree/ensemble, validation-only selection, seed stability report,
MDI/permutation feature-importance warnings, validation slice metrics и small-n warnings.
`15/10` завершен как cross-validation planner с `cv_plan_spec.json`,
`ml_cv_fold_manifest.csv`, predeclared group/time-aware folds, no-test-peeking audit,
scoring alignment, fold-level score report, validation-only predictions,
serialized fit trace и warnings для tiny CV sample.
`15/11` завершен как imbalance policy evaluator с `imbalance_policy_spec.json`,
class distribution report, always-negative accuracy trap, `class_weight="balanced"`
candidate, validation-only selection, threshold/budget report, predictions,
serialized fit trace и warnings для tiny imbalance sample.
Следующий шаг — разработка урока `15/12` «Калибровка вероятностей».
Точная готовность указана в
[`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md), заметные изменения — в
[`CHANGELOG.md`](CHANGELOG.md).

## Участие в проекте

Исправления, улучшения объяснений, новые упражнения и предложения уроков приветствуются.
Перед изменением программы прочитайте [`CONTRIBUTING.md`](CONTRIBUTING.md), а новый урок
сначала предложите через
[шаблон issue](.github/ISSUE_TEMPLATE/new_lesson_proposal.md).

Участие регулируется [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md). Код и материалы
распространяются по [лицензии MIT](LICENSE).
