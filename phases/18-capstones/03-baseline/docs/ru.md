# Baseline результата

> Baseline нужен не для того, чтобы сложной реализации было легко победить. Он нужен,
> чтобы сложность пришлось оправдать измеримым практическим улучшением.

**Тип:** Case  
**Треки:** core, product, data, decision, ml, delivery  
**Пререквизиты:** `18-capstones/02-data-contract`  
**Время:** ~300 минут

## Цели обучения

После урока вы сможете:

- продолжить checksum-verified data package со статусом `data_ready`;
- выбрать простейший честный baseline для своего capstone-маршрута;
- превратить baseline из таблицы метрик в воспроизводимое decision rule;
- независимо пересчитать ключевой результат на tiny slice;
- до реализации кандидата зафиксировать acceptance metric, tolerance и practical delta;
- учесть capacity constraint вместе с качеством решения;
- ограничить dependencies, runtime, config и часы через complexity budget;
- сохранить baseline как допустимый итог, если сложность не дает практической пользы;
- выпустить `baseline_ready` package без raw data и результатов будущего кандидата.

## Проблема

После data contract появляется соблазн перейти прямо к «настоящей» части проекта:
обучить модель, построить adjusted estimator, оптимизировать pipeline или сделать
интерактивное приложение. Baseline в таком процессе часто добавляют задним числом. Он
получается заведомо слабым и выполняет декоративную роль.

Это ломает сразу несколько решений:

- нельзя понять, улучшил ли сложный метод полезность или только изменил метрику;
- acceptance threshold подстраивается под уже увиденный candidate result;
- ошибка denominator одинаково повторяется в baseline и реализации;
- ресурсы тратятся на библиотеку, хотя простое правило уже достаточно для решения;
- сильный predictive score ошибочно интерпретируют как эффект будущей интервенции;
- reviewer видит красивый результат, но не имеет простого числа для независимой сверки.

В reference case владелец решает, сохранить ли общий weekly review или направить
ограниченную ручную проверку на один заранее определенный сегмент. Разрешенный input из
`18/02` содержит две агрегированные строки:

| Сегмент | Пользователи | Churned | Churn rate | Support tickets per user |
|---|---:|---:|---:|---:|
| `high_touch` | 4 | 2 | 0.50 | 1.50 |
| `self_serve` | 4 | 1 | 0.25 | 0.50 |

Самый простой decision-relevant baseline выбирает один сегмент по максимальному observed
churn rate, затем по support load и стабильному `segment_id`. Он выбирает `high_touch`,
просматривает четыре пользователя и ретроспективно охватывает двух из трех churned users:

```text
captured_churn_recall = 2 / 3 = 0.666667
```

Это comparator для приоритизации. Он не доказывает, что ручной outreach снизит churn.

## Концепция

### Baseline отвечает на decision question

Baseline не обязан использовать ту же архитектуру, что будущая реализация. Его форма
следует решению:

| Слабая постановка | Decision-relevant baseline |
|---|---|
| Посчитать средний churn | Выбрать допустимый сегмент в пределах review capacity |
| Обучить маленькую модель | Сравнить candidate policy с dummy/rate rule |
| Запустить один SQL | Сверить correctness, freshness и runtime прямого запроса |
| Нарисовать статичный экран | Проверить, выполняет ли consumer задачу с verified package |

Полезный baseline имеет четыре свойства:

1. использует только разрешенные на этом stage данные;
2. выдает воспроизводимое действие или comparator;
3. остается внутри claim boundary маршрута;
4. достаточно прост для независимой проверки.

### Маршруты требуют разных comparators

Общий принцип один, но baseline не универсален.

| Route | Минимальный baseline | Граница claim |
|---|---|---|
| Core analytics | segment rate/rule | observed priority, не intervention effect |
| Product experiments | unadjusted assignment means | causal только после design/SRM gates |
| Data/analytics engineering | direct query quality benchmark | correctness/freshness/performance, не user impact |
| Decision science causal | unadjusted outcome difference | comparator, не causal effect |
| Decision science forecast | seasonal naive forecast | accuracy только в заявленном horizon |
| ML baseline/strong | dummy или rate rule | prediction/priority, не treatment effect |
| Delivery product | static verified package | usability/freshness без усиления upstream claim |

Strong-model route все равно начинает с dummy/rate baseline. Слово `strong` описывает
будущий candidate budget, а не право пропустить простой comparator.

### Baseline раньше candidate

Stage contract запрещает поля `candidate_value`, `candidate_pass`, `test_score` и
`implementation_score` в `baseline_spec.json`. Они появляются только после того, как
зафиксированы:

- metric id и direction;
- baseline value;
- practical improvement;
- tolerance;
- resource/capacity constraint;
- fallback, если кандидат gate не прошел.

Для reference case:

```text
metric: captured_churn_recall
direction: maximize
baseline: 0.666667
practical improvement: 0.10
candidate threshold: 0.766667
capacity: reviewed_users <= 4
```

Порог не равен «любому положительному приросту». Улучшение с `0.666667` до `0.67` может
быть численно настоящим, но недостаточным, чтобы оплачивать более сложную систему.

### Tolerance не является скидкой на practical value

Tolerance отвечает за численную эквивалентность, например различие из-за округления:

```python
candidate_value + tolerance >= candidate_threshold
```

Practical improvement отвечает за смысл решения:

```python
candidate_threshold = baseline_value + practical_improvement
```

Нельзя заменить practical delta большой tolerance. В reference contract tolerance равна
`0.000001`, а improvement равен `0.10`: это разные масштабы и разные обязанности.

### Manual reconciliation использует второй путь

Если baseline и «ручная проверка» вызывают одну функцию, это одна и та же ошибка дважды.
Reference artifact выбирает одну строку `high_touch` и напрямую читает четыре counts:

```text
users = 4
activated_users = 2
support_ticket_count = 6
churned_users = 2
```

Затем независимо выполняет три деления:

```text
activation_rate = 2 / 4 = 0.5
support_tickets_per_user = 6 / 4 = 1.5
churn_rate = 2 / 4 = 0.5
```

Каждая формула, expected, observed, delta и tolerance попадает в
`manual_reconciliation.csv`. Ошибка `2 / 8` сразу становится видимой как неверный
denominator.

### Capacity является частью метрики

Без capacity candidate может «улучшить» recall, выбрав всех пользователей. Это не решение
при ограниченном ресурсе. Поэтому acceptance gate одновременно требует:

```text
captured_churn_recall >= 0.766667
reviewed_users <= 4
no new blocking quality gates
```

Метрика без операционного ограничения оценивает другую задачу.

### Complexity budget делает простоту проверяемой

Фраза «не переусложнять» слишком расплывчата. Reference budget ограничивает:

| Ресурс | Максимум |
|---|---:|
| Новые runtime dependencies | 1 |
| Runtime | 30 секунд |
| Config parameters | 8 |
| Implementation work | 12 часов |

Сложность допускается только ради одного из объявленных gains:

- `decision_utility`;
- `reliability`;
- `runtime`;
- `maintainability`.

Наличие новой библиотеки не является gain. Более подробный dashboard не является gain,
если он не улучшает consumer task или надежность. Stop rule сохраняет baseline, когда
кандидат не достигает practical threshold.

### Достаточный baseline не провал проекта

Если простое правило:

- соответствует decision contract;
- проходит data quality gates;
- укладывается в capacity;
- воспроизводимо;
- а сложный candidate не дает практического улучшения,

то корректное решение состоит в сохранении baseline. Capstone оценивает качество решения,
а не количество примененных технологий.

## Соберите это

Standalone artifact находится в
[`../outputs/capstone_baseline_gate.py`](../outputs/capstone_baseline_gate.py).

### 1. Проверьте upstream package

Baseline принимает package из `18/02` и требует:

- `data_audit.json` со статусом `data_ready`;
- `capstone_state.json` на stage `data_contract`;
- совпадающие `project_id` и `contract_id`;
- SHA-256 для state, contract, audit и public sample;
- `raw_sources_copied: false`.

Изменение одной строки после data audit блокирует baseline до выпуска согласованной новой
версии data package.

### 2. Объявите baseline policy

Reference policy фиксирует порядок до вычислений:

```json
{
  "baseline_kind": "segment_rate_rule",
  "ranking_metric": "churn_rate",
  "ranking_direction": "maximize",
  "tie_breakers": ["support_tickets_per_user", "segment_id"],
  "max_selected_segments": 1,
  "action_on_selection": "targeted_manual_review",
  "fallback_action": "no_action",
  "no_causal_claim": true
}
```

Tie-breakers нужны даже в tiny case. Без них одинаковые rates могут дать разный результат
при другом порядке CSV.

### 3. Пересчитайте aggregate input

Artifact не доверяет опубликованному `activation_rate`. Он читает counts, проверяет их
границы и заново считает rates:

```python
activation_rate = activated_users / users
churn_rate = churned_users / users
support_tickets_per_user = support_ticket_count / users
```

Grain `as_of_week, segment_id` обязан быть уникальным. Columns с row-level identifiers
в таком input запрещены.

### 4. Получите действие

Строки сортируются по predeclared policy. В package сохраняются полный ranking и решение:

```json
{
  "selected_action": "targeted_manual_review",
  "selected_segments": ["high_touch"],
  "causal_effect_claimed": false,
  "observed_evidence": {
    "captured_churn_recall": 0.666667,
    "reviewed_users": 4
  }
}
```

`selected_action` не означает автоматическое выполнение. Это baseline для сравнения
decision policies.

### 5. Заморозьте acceptance gate

В `acceptance_gate.json` candidate fields остаются пустыми:

```json
{
  "baseline_value": 0.666667,
  "candidate_threshold": 0.766667,
  "candidate_value": null,
  "candidate_pass": null,
  "status": "predeclared_for_implementation"
}
```

Так manifest доказывает, что threshold существовал до следующего stage.

## Используйте это

Создайте reference data package, baseline spec и passing baseline package:

```bash
uv run --locked python \
  phases/18-capstones/03-baseline/outputs/capstone_baseline_gate.py \
  --write-example /tmp/capstone-baseline-input \
  --output-dir /tmp/capstone-baseline-package \
  --fail-on-invalid
```

CLI вернет:

```json
{
  "status": "baseline_ready",
  "valid": true,
  "selected_segments": ["high_touch"],
  "baseline_value": 0.666667,
  "candidate_threshold": 0.766667,
  "blocking_errors": []
}
```

Для собственного проекта передайте входы явно:

```bash
uv run --locked python \
  phases/18-capstones/03-baseline/outputs/capstone_baseline_gate.py \
  --upstream-data-package path/to/data-package \
  --baseline-spec path/to/baseline_spec.json \
  --output-dir path/to/baseline-package \
  --fail-on-invalid
```

Готовый package:

```text
baseline-package/
├── baseline_spec.json
├── baseline_report.json
├── baseline_metrics.csv
├── baseline_decision.json
├── manual_reconciliation.csv
├── acceptance_gate.json
├── complexity_budget.json
├── capstone_state.json
└── baseline_manifest.json
```

Exit code `0` означает `baseline_ready`, `1` - содержательный `baseline_block`, `2` -
missing/invalid input или другую системную ошибку.

## Сломайте это

### Подмените data package

Измените `public_data_sample.csv` после data audit. Upstream SHA-256 перестанет совпадать,
и вычисленный заново «улучшенный» baseline не будет принят как evidence.

### Повторите week-segment row

Скопируйте строку `high_touch`. Даже если rates не изменятся, grain перестанет быть
уникальным, а totals и captured recall удвоят часть population.

### Нарушьте count bounds

Укажите `churned_users = 5` при `users = 4`. Artifact блокирует строку до ranking.
Отрицательные ticket counts и activated users выше population обрабатываются так же.

### Подмените denominator

Поставьте expected `churn_rate = 0.25` для manual slice. Основной ranking может остаться
прежним, но независимая формула `2 / 4` вернет `0.5` и заблокирует stage.

### Передвиньте threshold после просмотра кандидата

Добавьте в spec:

```json
{
  "candidate_value": 0.70,
  "candidate_pass": true
}
```

Gate `baseline_is_isolated_from_implementation_and_future_results` найдет оба поля. На
baseline stage значение кандидата еще не существует.

### Уберите practical improvement

Установите delta в `0`. Тогда любая численная флуктуация сможет оправдать сложность.
Acceptance gate требует положительный practical threshold отдельно от tolerance.

### Превысьте budget

Запросите 20 dependencies и 30 часов реализации. Даже потенциально полезный candidate не
соответствует утвержденному 44-часовому capstone scope и блокируется до изменения brief.

## Проверьте это

Запустите behavioral tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/18-capstones/03-baseline/tests -v
```

Тесты проверяют:

- passing reference baseline и frozen threshold;
- upstream state/sample checksum tampering;
- project, contract и decision mismatch;
- aggregate-only input boundary;
- duplicate grain, count bounds и rate reconciliation;
- восемь route/variant baseline profiles;
- deterministic tie-breakers;
- manual denominator и missing slice failures;
- practical delta, tolerance, capacity и complexity budget;
- запрет candidate values и later-stage identifiers;
- state handoff, manifest hashes и CLI exit codes;
- отсутствие mutation входных файлов.

Курс-уровневые проверки:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Baseline stage готов, когда reviewer получает:

- checksum-verified upstream data package;
- route-specific `baseline_spec.json`;
- полный ranking в `baseline_metrics.csv`;
- decision action и честную claim boundary в `baseline_decision.json`;
- независимую сверку counts и rates в `manual_reconciliation.csv`;
- frozen metric, tolerance, practical threshold и capacity в `acceptance_gate.json`;
- ограниченный `complexity_budget.json` с retain-baseline stop rule;
- `capstone_state.json` со статусом `baseline_ready` и пустым `implementation_id`;
- SHA-256 manifest с `candidate_results_observed: false`.

Не публикуйте raw sources и не добавляйте результат кандидата задним числом. Следующий
урок реализует route-specific workflow как immutable consumer brief, data contract и
baseline package.

## Упражнения

1. **Измените capacity.** Разрешите выбрать не больше шести пользователей и объясните,
   почему baseline rule теперь должно работать на другом grain, а не просто выбрать оба
   четырехпользовательских сегмента.
2. **Смените tie-breaker.** Используйте меньший support load при одинаковом churn rate.
   Зафиксируйте бизнес-смысл изменения и behavioral test на стабильный порядок.
3. **Выбранный маршрут.** Спроектируйте baseline kind, metric, direction и claim boundary
   для своего route. Не переносите core `captured_churn_recall` механически в forecast или
   data engineering.
4. **Minimize metric.** Создайте acceptance gate для MAE или expected cost, где practical
   delta вычитается из baseline, и проверьте направление inequality.
5. **Достаточный baseline.** Напишите короткое решение, при каких наблюдаемых результатах
   вы откажетесь от сложной реализации и передадите baseline как основной метод.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Baseline | Намеренно слабая модель | Простейший честный decision-relevant comparator |
| Decision rule | Таблица метрик | Детерминированное преобразование evidence в допустимое действие |
| Manual reconciliation | Повторный вызов функции | Независимый расчет tiny slice по явной формуле |
| Acceptance metric | Любая знакомая метрика | Заранее выбранная мера практической полезности кандидата относительно baseline |
| Practical threshold | Статистическая значимость | Минимальный полезный gain, оправдывающий изменение решения или системы |
| Tolerance | Допустимое ухудшение | Численная погрешность сравнения, существенно меньше practical delta |
| Capacity constraint | Необязательный фильтр | Ограничение ресурса, без которого метрика описывает другую задачу |
| Complexity budget | Оценка красоты кода | Верхние границы dependencies, runtime, config и часов кандидата |
| Stop rule | Признание поражения | Заранее объявленное условие сохранить baseline и не покупать лишнюю сложность |

## Дополнительное чтение

- [Rules of Machine Learning](https://developers.google.com/machine-learning/guides/rules-of-ml) - прочитайте правила о простом первом pipeline и измеряемой цели; примените принцип за пределами ML.
- [Dummy estimators в scikit-learn](https://scikit-learn.org/stable/modules/model_evaluation.html#dummy-estimators) - сравните `DummyClassifier`/`DummyRegressor` с task-specific decision baseline и не путайте технический dummy с полным бизнес-comparator.
- [Forecasting: simple methods](https://otexts.com/fpp3/simple-methods.html) - разберите mean, naive, seasonal naive и drift как обязательные comparators перед сложным прогнозом.
- [The Aqua Book](https://www.gov.uk/government/publications/the-aqua-book-guidance-on-producing-quality-analysis-for-government) - используйте рекомендации по proportionate quality assurance, независимой проверке и audit trail для manual reconciliation.
