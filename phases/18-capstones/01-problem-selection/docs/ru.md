# Выбор и ограничение задачи

> Хороший capstone начинается не с датасета и не с библиотеки. Он начинается с решения,
> которое можно принять или отклонить, и с границы того, что проект вправе утверждать.

**Тип:** Learn  
**Треки:** core, product, data, decision, ml, delivery  
**Пререквизиты:** `17-delivery/12-handoff`  
**Время:** ~240 минут

## Цели обучения

После урока вы сможете:

- выбрать один маршрут капстоуна и проверить только его обязательные пререквизиты;
- сформулировать decision owner, unit, population, horizon, варианты действия и claim type;
- ограничить работу диапазоном 30-50 часов через in-scope, non-goals и stop conditions;
- превратить критерии успеха в будущие acceptance tests;
- составить risk register для всего жизненного цикла проекта;
- разложить 44 часа на семь последовательных stage gates;
- выпустить machine-readable brief package перед переходом к data contract.

## Проблема

Самый опасный capstone выглядит занятым. В нем много данных, несколько библиотек, красивый
dashboard и длинный notebook, но невозможно ответить на три простых вопроса:

1. Кто принимает решение?
2. Какие действия реально доступны?
3. Что изменится, если результат проекта окажется одним, другим или неопределенным?

Без этих ответов scope расширяется вслед за каждой интересной находкой. Product-проект
незаметно обещает causal effect по наблюдаемым данным. ML-проект выбирает алгоритм раньше
prediction unit. Data-проект заявляет бизнес-эффект, хотя доказал только корректность mart.
Delivery-проект делает интерфейс единственным результатом и теряет границы upstream claim.

Цена ошибки особенно высока в капстоуне: неверно выбранную задачу нельзя исправить
полировкой последних двух дней. Поэтому первый артефакт фазы является gate, а не эссе.
Пока brief не готов, работа с основным датасетом и методом преждевременна.

## Концепция

### От темы к решению

Тема отвечает на вопрос «о чем проект?». Decision contract отвечает на вопрос «что будет
делать конкретный владелец после результата?».

Слабая формулировка:

```text
Исследовать churn с pandas и CatBoost.
```

Проверяемая формулировка:

```text
Head of support operations решает, оставить ли текущий weekly review или направлять
ограниченный ресурс на заранее определенный at-risk segment. No-action остается
допустимым вариантом.
```

Во второй формулировке появляются owner, cadence, decision options и цена ошибки. Метод
еще не выбран, и это правильно.

### Шесть маршрутов, не одна лестница

Капстоун не требует пройти все специализации. Валидатор вычисляет минимальный набор фаз:

| Route | Variant | Дополнительная подготовка | Допустимые claim types |
|---|---|---|---|
| `core_analytics` | `standard` | нет | `descriptive`, `associational` |
| `product_experiments` | `standard` | `08-10` | `product_decision`, `experimental_causal` |
| `data_analytics_engineering` | `standard` | `11-12` | data quality, lineage, freshness, performance |
| `decision_science` | `causal` | `13` | `causal` |
| `decision_science` | `forecast` | `14` | `forecast` |
| `machine_learning` | `baseline` | `15` | `predictive`, `decision_policy` |
| `machine_learning` | `strong_model` | `15-16` | `predictive`, `decision_policy` |
| `delivery_product` | `standard` | verified upstream package | delivery quality без усиления claim |

Во всех строках подразумеваются общее ядро `00-07` и фаза 17. Список
`declared_prerequisites` должен совпадать с route profile: пропущенная фаза опасна, но и
лишнее требование делает маршрут искусственно недоступным.

### Claim type раньше метода

`claim_type` - короткое обещание читателю о природе вывода. Оно не описывает красивую
формулировку, а ограничивает доказательство:

- `descriptive`: что наблюдалось в объявленной population и horizon;
- `associational`: какие признаки менялись вместе, без утверждения причины;
- `experimental_causal`: эффект из корректного randomized design;
- `causal`: estimand и эффект в границах causal identification;
- `forecast`: будущая величина и uncertainty в объявленном horizon;
- `predictive`: способность ранжировать или предсказывать outcome;
- `data_quality`, `lineage`, `freshness`, `performance`: свойства аналитического слоя;
- `delivery_quality`: воспроизводимость и пригодность upstream evidence для потребителя.

Например, predictive score не доказывает эффект retention offer. Быстрый mart не
доказывает рост retention. Интерактивное приложение не усиливает causal claim отчета.

### Scope как бюджет доказательства

Фаза отводит на проект 30-50 часов. Reference plan использует 44:

| Stage | Часы | Gate |
|---|---:|---|
| Problem selection | 4 | Brief готов к data contract |
| Data contract | 6 | Grain, keys, lineage и source policy проверены |
| Baseline | 5 | Есть manual cross-check и complexity budget |
| Implementation | 12 | Route workflow собирается одной командой |
| Verification | 7 | Clean-room, shadow и failure checks проходят |
| Peer review | 5 | Blockers закрыты новым evidence |
| Defense | 5 | Reviewed package готов к защите |

Число часов само по себе не ограничивает проект. Нужны четыре списка:

- `in_scope`: что обязано быть сделано;
- `non_goals`: что сознательно не доказывается и не строится;
- `stop_conditions`: при каких условиях проект останавливается или меняет тему;
- `deliverables`: какие проверяемые файлы остаются после работы.

### Risk register до того, как риск реализовался

Risk register покрывает шесть категорий:

| Категория | Типичный вопрос |
|---|---|
| `data_access` | Сможет ли reviewer получить разрешенный input или synthetic fallback? |
| `privacy` | Какие поля нельзя публиковать в portfolio package? |
| `methodology` | Какой overclaim или assumption способен обесценить вывод? |
| `compute` | Помещается ли rerun в доступный laptop/time budget? |
| `delivery` | Можно ли пересобрать и проверить свежесть consumer artifact? |
| `review` | Когда и кем будет выполнена независимая проверка? |

Каждая строка имеет owner, trigger и mitigation. Запись «данные могут быть плохими» не
является управляемым риском: непонятно, что считать наступлением и что делать дальше.

### Gate, warning и системная ошибка

Валидатор различает три состояния:

- `ready_for_data_contract`: блокеров нет;
- `brief_revision_required`: нарушен содержательный contract;
- `system_error`: файл нельзя прочитать или CLI вызван без входа.

Reference tiny brief получает warning `reference_profile_is_not_portfolio_evidence`. Это
не ошибка урока. Его задача - доказать поведение инструмента, а не заменить собственную
тему студента.

## Соберите это

Прозрачная версия механизма состоит из четырех шагов.

### 1. Вычислите минимальные пререквизиты

```python
CORE = list(range(8))

def causal_capstone_prerequisites() -> list[int]:
    return CORE + [13, 17]

assert causal_capstone_prerequisites() == [0, 1, 2, 3, 4, 5, 6, 7, 13, 17]
```

Здесь нет фаз 11, 12, 15 и 16: они полезны другим маршрутам, но не являются скрытым
условием causal capstone.

### 2. Проверьте action space

```python
option_ids = {"no_action", "targeted_manual_review"}
assert len(option_ids) >= 2
assert "no_action" in option_ids
```

Этот маленький invariant не дает brief заранее принудить положительную рекомендацию.

### 3. Сверьте часы milestone plan

```python
stage_hours = [4, 6, 5, 12, 7, 5, 5]
assert sum(stage_hours) == 44
assert 30 <= sum(stage_hours) <= 50
```

Если milestones обещают 61 час при scope в 44, план уже внутренне противоречив.

### 4. Отделите blocker от warning

```python
blocking_errors = []
warnings = ["reference_profile_is_not_portfolio_evidence"]
status = "ready_for_data_contract" if not blocking_errors else "brief_revision_required"
```

Warning остается видимым, но не превращает корректный учебный fixture в failed build.

## Используйте это

Standalone artifact находится в
[`../outputs/capstone_brief_validator.py`](../outputs/capstone_brief_validator.py).

Создайте reference input и пакет:

```bash
uv run --locked python \
  phases/18-capstones/01-problem-selection/outputs/capstone_brief_validator.py \
  --write-example /tmp/capstone-brief-input \
  --output-dir /tmp/capstone-brief-package \
  --fail-on-invalid
```

Появятся:

```text
/tmp/capstone-brief-package/
├── capstone_brief_audit.json
├── risk_register.csv
├── milestone_plan.csv
├── capstone_state.json
└── brief_manifest.json
```

`capstone_brief_audit.json` содержит checks, blockers, warnings и следующий stage.
`capstone_state.json` является handoff для урока `18/02`: будущие contract IDs пока
равны `null`, текущий stage остается `problem_selection`, а status показывает готовность
к data contract. Manifest фиксирует SHA-256 входа и четырех сгенерированных evidence
files; сам manifest не хеширует себя.

Запустите короткий пример урока:

```bash
uv run --locked python phases/18-capstones/01-problem-selection/code/main.py
```

Reference brief проходит с одним ожидаемым warning. Для собственного проекта поменяйте
`profile_kind` на `student_project` только после того, как действительно заменили тему,
decision, scope, risks и milestones.

## Сломайте это

### Уберите no-action

Оставьте только `targeted_manual_review`. Check `decision_precedes_analysis` должен
заблокировать brief: анализ больше не способен рекомендовать сохранение текущей политики.

### Расширьте scope до 90 часов

Измените `scope.estimated_hours`, но не milestones. Валидатор покажет сразу две проблемы:
scope вышел за диапазон и сумма этапов не совпадает с заявленным бюджетом.

### Назовите descriptive project причинным

Для `core_analytics` поставьте `claim_type = "causal"`. Check
`claim_matches_route_boundary` не позволит получить causal claim без causal или
experimental route.

### Добавьте лишний пререквизит

В `declared_prerequisites` core route добавьте фазу 16. Проект мог быть пройден автором,
но требовать его от следующего студента нельзя. Audit покажет поле `unnecessary`.

### Удалите review risk

Проект не должен сначала закончиться, а потом искать reviewer. Отсутствие категории
`review` блокирует lifecycle risk coverage.

### Перепутайте порядок milestones

Поставьте `defense` раньше `verification`. Artifact проверяет и полный порядок stages, и
линейные `depends_on`, поэтому формальное наличие семи строк не обманет gate.

## Проверьте это

Запустите behavioral suite урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/18-capstones/01-problem-selection/tests
```

Suite проверяет:

- valid reference brief, warning и переход к `data_contract`;
- исполнение `code/main.py` и standalone CLI;
- все шесть route profiles и variant-specific prerequisites;
- no-action, owner, unit/population/horizon и claim boundaries;
- scope budget, success criteria, risk coverage и milestone dependencies;
- assistance disclosure;
- содержимое `capstone_state.json`;
- SHA-256 каждого обязательного output;
- structured exit codes для invalid brief и system error.

Passing test suite не доказывает качество выбранной темы. Он доказывает, что brief
содержит минимальные условия, при которых следующий этап вообще можно проверять.

## Поставьте результат

Именованный артефакт урока - `capstone-brief-validator`. Передайте следующему этапу:

- исходный `capstone_brief.json`;
- `capstone_brief_audit.json` без blockers;
- нормализованный `risk_register.csv`;
- последовательный `milestone_plan.csv`;
- `capstone_state.json` со статусом `ready_for_data_contract`;
- `brief_manifest.json` с совпадающими SHA-256.

Не передавайте reference brief как собственный проект. Его warning специально остается в
audit и state, чтобы provenance не потерялся.

## Упражнения

1. Создайте student brief для `data_analytics_engineering`: ограничьте главный claim
   корректностью, lineage или performance и объясните, почему user impact остается
   non-goal.
2. Создайте две версии `decision_science`: causal и forecast. Сравните только различия в
   prerequisites, claim type, methodology risk и future acceptance gate.
3. Уменьшите implementation с 12 до 8 часов и распределите освободившийся бюджет между
   verification и review, не меняя общий scope. Обоснуйте изменение риска.
4. Добавьте seventh risk категории `stakeholder_availability`. Проверьте, что обязательные
   шесть категорий остаются покрыты, а дополнительная не блокируется.
5. Напишите stop condition, который действительно меняет план, а не повторяет «если будет
   сложно». Укажите trigger и fallback route.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Capstone brief | Красивое описание темы | Machine-readable contract решения, scope, route, рисков и приемки |
| Decision owner | Автор анализа | Роль, которая отвечает за выбор действия на основании результата |
| Claim type | Стиль формулировки вывода | Тип доказательства, который ограничивает допустимое утверждение |
| No-action | Отказ от проекта | Полноценный вариант решения, который сохраняет честность рекомендации |
| Non-goal | То, что не успели | Сознательно исключенная работа или недопустимый claim |
| Stop condition | Любая трудность | Наблюдаемый trigger, после которого проект останавливается или меняет план |
| Route readiness | Все пройденные фазы | Минимальные завершенные фазы, нужные выбранному route и variant |
| Risk register | Список страхов | Реестр trigger, likelihood, impact, mitigation, owner и статуса |
| Stage gate | Дата в календаре | Проверяемое условие перехода с конкретным артефактом |

## Дополнительное чтение

- [The AQuA Book](https://www.gov.uk/guidance/the-aqua-book) - прочитайте главы про
  engagement/scoping, specification и proportionate assurance: они связывают границы
  анализа с решением, ресурсами и уровнем риска.
- [The Turing Way: Getting Started Checklist](https://book.the-turing-way.org/project-design/pd-overview/pd-checklist) - используйте checklist, чтобы проверить research question,
  users, data, workflow, communication, review и sharing до начала реализации.
- [The Turing Way: Getting Started with Project Design](https://book.the-turing-way.org/project-design/pd-overview/pd-overview-planning/) - сопоставьте purpose, audience, resources и
  skills с полями capstone brief этого урока.
- [GitHub: Planning and tracking work](https://docs.github.com/en/issues/tracking-your-work-with-issues/learning-about-issues/planning-and-tracking-work-for-your-team-or-project) - перенесите stage plan в issues, dependencies и milestones, не создавая второй источник правды для scope.
