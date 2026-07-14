# Проект фазы 18: Капстоун-проекты

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует общую архитектуру
капстоуна, варианты маршрутов, контракты этапов, правила независимой проверки и критерии
защиты итогового `capstone-portfolio-package`.

## Результат фазы

Студент собирает не еще один учебный notebook, а законченный аналитический проект для
конкретного решения. Проект начинается с ограниченного brief, проходит через контракт и
аудит данных, простой baseline, маршрутную реализацию, независимую валидацию, peer review
и заканчивается защитой воспроизводимого портфельного пакета.

Фаза проверяет, что выпускник удерживает вместе семь частей работы:

1. **Decision framing:** понятны заказчик, решение, варианты действия, claim type и цена
   ошибки.
2. **Data contract:** названы grain, keys, lineage, временные границы, ограничения
   использования и известные дефекты данных.
3. **Baseline before complexity:** есть простой результат, ручная сверка и критерий,
   который оправдывает усложнение.
4. **Route-specific method:** метод соответствует выбранному маршруту и не расширяет
   допустимый тип вывода.
5. **Independent verification:** ключевой результат можно пересчитать отдельно, а
   намеренно испорченные входы приводят к ожидаемому отказу.
6. **Review closure:** замечания имеют severity, evidence, ответ автора и проверяемый
   статус закрытия.
7. **Defense and handoff:** студент объясняет решение, показывает живой rerun, честно
   отвечает на challenge questions и передает пакет другому человеку.

Семь уроков образуют один stage-gated workflow:

1. `18/01`: capstone brief, маршрут, scope, риски и milestones.
2. `18/02`: dataset manifest, data contract, lineage и pre-method audit.
3. `18/03`: decision-relevant baseline и complexity budget.
4. `18/04`: основная реализация выбранного маршрута.
5. `18/05`: clean-room rerun, shadow calculation и failure fixtures.
6. `18/06`: peer review, response ledger и re-review.
7. `18/07`: portfolio package, демонстрация и защита.

Суммарная длительность - 2640 минут, или 44 часа. Это середина заявленного диапазона
30-50 часов и включает самостоятельную реализацию, проверку и исправления после review.

## Границы содержания

- **Не восьмой тематический трек.** Фаза не вводит новый статистический, ML, BI или
  backend-метод. Студент применяет инструменты уже пройденного маршрута.
- **Не конкурс метрик.** Высокий uplift, accuracy, R2 или скорость запроса не заменяют
  корректную постановку, данные и проверку claim.
- **Не требование пройти все специализации.** Студент выбирает один маршрут. Проверяются
  только его обязательные пререквизиты и общие фазы.
- **Не production certification.** Учебный проект может показать readiness и handoff, но
  не заявляет production SLA, безопасность, юридическое соответствие или реальный
  бизнес-эффект без отдельного evidence.
- **Не обязательный публичный датасет.** Можно использовать локальные, открытые или
  синтетические данные, если зафиксированы license, privacy и правила публикации. Сырые
  чувствительные данные в портфельный пакет не входят.
- **Не notebook-only сдача.** Notebook допустим как исследовательская поверхность, но
  проверка и сборка запускаются явной командой из чистого окружения.
- **Не защита слайдов вместо результата.** Defense brief ссылается на артефакты и живые
  проверки; утверждение без evidence link считается неподтвержденным.
- **Не запрет AI-инструментов.** Помощь AI разрешена с disclosure, но автор отвечает за
  каждый claim, тест и источник. Непроверенный сгенерированный вывод не считается
  evidence.

## Маршруты капстоуна

Все варианты требуют завершенных общего ядра `00-07` и delivery-фазы 17. Дополнительные
пререквизиты зависят от выбранного маршрута и проверяются в `18/01`.

| Маршрут | Дополнительные фазы | Reference brief | Допустимый главный claim |
|---|---|---|---|
| Core analytics | нет | Диагностика активации и нагрузки поддержки | Descriptive или associational, без causal language |
| Product and experiments | `08-10` | Решение по onboarding/retention эксперименту | Product decision; causal только из корректного randomized design |
| Data and analytics engineering | `11-12` | Weekly customer health mart и SLA расчета | Correctness, lineage, freshness и performance, но не user impact |
| Decision science | `13` или `14` | Retention intervention study или support-load forecast | Causal estimand либо forecast claim в границах выбранного дизайна |
| Machine learning | `15`; `16` для strong-model варианта | Churn-risk prioritization при ограниченном бюджете | Predictive and decision-policy claim, но не эффект интервенции |
| Delivery product | любой verified evidence package + `17` | Регулярный stakeholder decision package | Usability, freshness и reproducibility без усиления upstream claim |

Reference briefs используют общую вымышленную вселенную подписочного сервиса из
[`data-universe.md`](data-universe.md). Студент может предложить собственную тему, если
она проходит тот же brief validator и не требует скрытых данных или непройденного метода.

## Общий stage contract

Каждый этап обновляет machine-readable `capstone_state.json`:

```text
project_id
project_title
route
route_prerequisites
decision_owner
decision
decision_options
claim_type
scope
non_goals
data_contract_id
baseline_id
implementation_id
verification_id
review_id
defense_id
current_stage
stage_status
open_blockers
warnings
artifact_inventory
evidence_links
input_checksums
output_checksums
assistance_disclosure
updated_at
```

Допустимые переходы:

```text
brief_draft
  -> data_ready
  -> baseline_ready
  -> implementation_ready
  -> verification_ready
  -> review_ready
  -> defense_ready
  -> passed | revision_required
```

Пропуск этапа запрещен. Исправление upstream contract инвалидирует downstream checksum и
возвращает проект на самый ранний затронутый gate.

## Контракт отдельных уроков

### Problem selection

- Brief начинается с решения и владельца, а не с названия библиотеки или найденного CSV.
- Фиксируются `claim_type`, unit of decision, population, time horizon и варианты
  действия, включая no-action.
- Scope обязан помещаться в 30-50 часов; non-goals и stop conditions записываются явно.
- Route readiness проверяет только реально нужные тематические фазы.
- Risk register покрывает data access, privacy, methodology, compute, delivery и review.
- Milestone plan содержит ожидаемый артефакт и acceptance gate каждого этапа.

### Data contract

- Для каждого источника фиксируются owner, origin, license, allowed use, freshness,
  checksum и способ воспроизведения.
- Для каждой таблицы названы grain, primary/candidate keys, допустимые дубликаты, временная
  зона, временной диапазон и missingness policy.
- Route adapter добавляет нужные проверки: randomization/SRM, temporal cutoff, split
  roles, post-treatment variables, schema/lineage или freshness SLA.
- Публичный пакет содержит только разрешенные данные; PII/secrets и лицензированные raw
  extracts исключаются manifest policy.
- Data audit выполняется до выбора финального метода и может заблокировать проект.

### Baseline

- Baseline является самым простым честным ответом на decision question, а не уменьшенной
  копией сложного решения.
- Ключевой показатель пересчитывается вручную на tiny slice или независимой формулой.
- До основной реализации объявляются acceptance metric, tolerance и practical threshold.
- Сложность имеет budget: новый метод обязан улучшить decision utility, надежность,
  скорость или поддержку, а не только добавить библиотеку.
- Если baseline уже достаточен, это допустимый вывод; проект не обязан искусственно
  усложняться.

### Implementation

- Реализация читает brief, data contract и baseline как immutable upstream inputs.
- Route-specific logic отделена от общего package/manifest слоя через явный adapter.
- Конфигурация, seeds, cutoffs, thresholds и candidate policy записаны до чтения финального
  evaluation result.
- Одна documented command строит все обязательные outputs из чистых разрешенных inputs.
- Evidence ledger связывает каждый публичный claim с таблицей, графиком, тестом или
  методологическим ограничением.
- Результат включает environment/lock metadata, run trace, warnings и checksums.

### Verification

- Clean-room rerun выполняется из нового output directory и locked environment.
- Shadow calculation независимо пересчитывает один главный показатель без вызова основной
  high-level функции проекта.
- Behavioral tests проверяют решение, а не только наличие файлов и столбцов.
- Negative fixtures должны ломать минимум три важных assumptions выбранного маршрута.
- Sensitivity checks меняют одно существенное решение: cutoff, metric, bandwidth, horizon,
  threshold, join policy или resource budget.
- Verification report разделяет `pass`, `warning`, `blocker` и не позволяет скрыть xfail,
  skipped checks или stale outputs.

### Peer review

- Автор сначала выполняет self-review, после чего package проверяет независимый reviewer.
- Reviewer type фиксируется как `learner_peer`, `mentor` или `independent_agent`; последний
  допустим для самостоятельного прохождения только с disclosure и clean review context.
- Automated precheck может найти проблему, но не закрывает собственное замечание автора.
- Findings имеют severity `blocker`, `major`, `minor` или `question`, точную evidence link,
  ожидаемое поведение и способ проверки исправления.
- Автор отвечает `accepted`, `partially_accepted` или `declined_with_evidence`; простое
  `resolved` без нового evidence запрещено.
- Любое изменение кода или данных после approval требует rerun затронутых checks и нового
  checksum manifest.

### Defense

- Defense brief укладывается в 10 минут: decision, data, baseline, method, result,
  limitations, recommendation и next step.
- Живая демонстрация показывает check mode и воспроизводимый rerun, а не только готовый
  HTML или screenshot.
- Challenge questions выбираются минимум из трех классов: data defect, method assumption,
  alternative explanation, failed deployment condition и changed business constraint.
- Ответ `не знаю` допустим, если автор корректно ограничивает claim и предлагает
  проверяемый следующий шаг.
- Финальный статус вычисляется по blockers и rubric; reviewer не может компенсировать
  критическую ошибку дополнительными баллами за оформление.

## Инструменты

Новые обязательные зависимости на этапе проектирования не добавляются. Капстоун использует
корневой locked environment и инструменты выбранного маршрута. Общий проверочный слой
строится на стандартной библиотеке, `pydantic`, `pandas` и `pytest`; delivery layer может
переиспользовать Quarto, Plotly, Streamlit, FastAPI и Docker только когда они нужны brief.

| Инструмент | Задача в фазе | Граница |
|---|---|---|
| JSON / CSV / pathlib / hashlib | Stage contracts, ledgers, inventories и checksums | Не заменяют содержательное review |
| Pydantic | Валидация brief, state, route adapter и rubric | Не доказывает корректность метода |
| pandas / DuckDB | Tiny shadow calculations и route data checks | Engine выбирается по маршруту и масштабу |
| pytest | Behavioral, negative, clean-room и contract tests | Passing tests не компенсируют неверный claim |
| uv | Locked environment и воспроизводимый run command | Lockfile не гарантирует доступность закрытых данных |
| Git / GitHub review | Diff, review threads, responses и approval history | GitHub не обязателен для локального курса |
| Quarto / delivery tools | Defense brief и stakeholder artifact | Формат выбирается по аудитории, не по эффектности |

Проверенные 11 июля 2026 года ориентиры:

- [uv locking and syncing](https://docs.astral.sh/uv/concepts/projects/sync/) - locked run,
  exact sync и проверка соответствия `pyproject.toml`/`uv.lock`.
- [pytest how-to guides](https://docs.pytest.org/en/stable/how-to/) и
  [fixtures](https://docs.pytest.org/en/latest/explanation/fixtures.html) - behavioral
  assertions, failure checks, temporary directories and isolated test contexts.
- [GitHub pull request reviews](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews) - review comments,
  approve/request-changes states and re-review after changes.
- [Quarto project basics](https://quarto.org/docs/projects/quarto-projects.html) - единая
  project configuration и воспроизводимый render нескольких outputs.
- [The Turing Way: reproducible research](https://book.the-turing-way.org/reproducible-research/reproducible-research/) - данные и код, достаточные для полного rerun анализа.
- [Datasheets for Datasets](https://arxiv.org/abs/1803.09010) - структурированная
  документация мотивации, состава, сбора, использования и ограничений dataset.

## Общая rubric

Каждое измерение оценивается от 0 до 4 и обязано иметь evidence links:

| Измерение | 0 | 2 | 4 |
|---|---|---|---|
| Problem framing | Решение и claim не определены | Scope понятен, но есть неоднозначности | Решение, claim, non-goals и цена ошибки согласованы |
| Data contract | Grain/lineage неизвестны | Основной contract есть, часть рисков не закрыта | Источники, grain, lineage, privacy и defects полностью проверяемы |
| Method and baseline | Нет честного baseline или метод не соответствует claim | Метод применим, но выборы обоснованы частично | Baseline, method choices и limitations связаны с decision utility |
| Verification | Результат нельзя независимо повторить | Основной rerun проходит, negative coverage ограничен | Clean-room, shadow, negative и sensitivity checks подтверждают границы |
| Delivery and handoff | Есть только рабочая директория автора | Основной consumer artifact и инструкция существуют | Пакет воспроизводим, понятен потребителю и имеет support/freshness policy |
| Review and defense | Замечания не закрыты, автор не объясняет решение | Review закрыт, но часть ответов поверхностна | Автор защищает assumptions, демонстрирует rerun и корректно ограничивает claim |

Итоговые правила:

- `passed`: нет blockers; все измерения не ниже 2; `Data contract`, `Method and baseline`
  и `Verification` не ниже 3; сумма не ниже 18 из 24.
- `passed_with_distinction`: нет blockers; все измерения не ниже 3; сумма не ниже 22.
- `revision_required`: любое другое состояние.

Rubric не является средним баллом за красоту проекта. Critical gates проверяются до
подсчета результата.

## Блокирующие проверки

Защита блокируется, если выполняется хотя бы одно условие:

- нет decision owner, claim type, scope или route readiness;
- grain, keys, source rights или privacy policy не определены;
- обязательный data quality gate не проходит;
- результат нельзя собрать documented command в locked environment;
- checksum входа или обязательного output не совпадает с manifest;
- основной claim не связан с evidence или шире допустимого route claim;
- обнаружены leakage, test peeking, post-treatment adjustment, SRM, temporal violation,
  many-to-many inflation или другой route-specific blocker;
- public package содержит secret, PII или запрещенный raw extract;
- independent verification не воспроизводит ключевой показатель в tolerance;
- blocker/major review finding остается открытым без принятого waiver evidence;
- defense показывает stale artifact или отличается от reviewed package.

## Reference profile и failure fixtures

Репозиторий поставляет deterministic `tiny` reference profile, чтобы инструменты каждого
урока имели executable example и behavioral tests. Он не является готовым ответом на
студенческий проект.

Reference project: еженедельное решение по удержанию пользователей подписочного сервиса.
В зависимости от route студент исследует activation, проектирует эксперимент, строит mart,
оценивает causal effect/forecast, ранжирует churn risk или доставляет verified package.

Обязательные дефектные fixtures:

- brief с неопределенным claim или scope шире 50 часов;
- источник без license/owner и таблица с неоднозначным grain;
- many-to-many join, размножающий revenue;
- baseline, посчитанный по test/future rows;
- implementation, которая проходит happy-path tests, но принимает stale input;
- shadow calculation с намеренно измененным denominator;
- review finding, помеченный resolved без rerun evidence;
- defense package с checksum, отличным от reviewed manifest;
- public artifact с fake secret/PII marker.

## Финальный portfolio package

`18/07` собирает:

```text
capstone-portfolio-package/
├── brief/
│   ├── capstone-brief.json
│   ├── risk-register.csv
│   └── milestone-plan.csv
├── data/
│   ├── data-contract.json
│   ├── dataset-manifest.json
│   ├── data-audit.json
│   └── public-data-sample/
├── baseline/
│   ├── baseline-report.json
│   ├── manual-cross-check.csv
│   └── complexity-budget.json
├── implementation/
│   ├── config/
│   ├── src/
│   ├── outputs/
│   ├── evidence-ledger.csv
│   └── run-manifest.json
├── verification/
│   ├── verification-report.json
│   ├── shadow-calculation.csv
│   ├── failure-fixtures/
│   └── test-results.json
├── review/
│   ├── review-rubric.json
│   ├── finding-ledger.csv
│   ├── author-responses.csv
│   └── re-review-report.json
├── defense/
│   ├── defense-brief.md
│   ├── demo-script.md
│   ├── challenge-questions.json
│   └── decision-report.md
├── handoff/
│   ├── README.md
│   ├── runbook.md
│   ├── limitations.md
│   └── assistance-disclosure.md
├── capstone-state.json
├── rubric-result.json
└── manifest.json
```

Пакет обязан:

- собираться одной командой из явно разрешенных inputs;
- проходить route-neutral и route-specific gates;
- содержать минимум один независимый shadow calculation;
- иметь минимум три negative fixtures и один sensitivity check;
- связывать каждый defense claim с evidence ledger;
- сохранять review history и повторную проверку после исправлений;
- отделять публикуемый sample от закрытых/чувствительных источников;
- фиксировать assistance disclosure без переноса ответственности с автора;
- включать SHA-256 manifest всех обязательных входов и outputs.

## Проверяемость уроков

- `18/01` проверяет route readiness, decision/claim consistency, scope budget, non-goals,
  risks and milestones.
- `18/02` проверяет grain/keys, lineage, source rights, privacy, freshness, checksums and
  route-specific data gates.
- `18/03` проверяет baseline isolation, manual reconciliation, acceptance metric,
  practical threshold and no test/future peeking.
- `18/04` проверяет immutable upstream contracts, route adapter, config/seeds, one-command
  build, evidence ledger and output manifest.
- `18/05` проверяет clean-room rerun, shadow tolerance, negative fixtures, sensitivity,
  skipped/xfail disclosure and claim traceability.
- `18/06` проверяет reviewer independence disclosure, finding severity, author responses,
  changed-file reruns and re-review status.
- `18/07` проверяет package tree, blocker gates, rubric thresholds, live-rerun contract,
  review closure, public-data policy and final checksums.

## Защита от утечки готового ответа

- Reference profile достаточно мал для ручной проверки и намеренно содержит warnings.
- Примеры показывают форму contract и validator behavior, но не полный route solution.
- Итоговые вопросы квиза используют другие параметры и failure modes.
- Tests проверяют invariants и состояния отказа, а не одно ожидаемое число из документа.
- Starter kit не содержит заполненный defense narrative и финальные reviewer responses.
- Собственная тема студента проходит те же gates, поэтому подмена файлов reference package
  не дает завершить capstone.
