# Причинные DAG и идентификация

> DAG — это не картинка для отчета, а проверяемый договор о том, какие пути нужно закрыть, а какие нельзя трогать.

**Тип:** Learn  
**Треки:** Decision, Product  
**Пререквизиты:** 13/01 — Причинный вопрос и estimand  
**Время:** ~75 минут  
**Результат:** строит направленный ациклический граф из предметных assumptions,
различает association и intervention, проверяет temporal order и d-separation и отделяет
идентификацию эффекта от выбора estimator.

## Цели обучения

- Записать causal DAG как machine-readable assumptions: узлы, роли, timing и стрелки.
- Проверить, что граф ацикличен и не содержит стрелок из будущего в прошлое.
- Отличить наблюдаемую ассоциацию `P(Y | T)` от интервенции `P(Y | do(T))`.
- Найти активные backdoor paths и понять, что делает conditioning.
- Распознать mediator, collider и selection variable как bad controls для total effect.
- Зафиксировать честный identification status до выбора regression, matching или IPW.

## Проблема

В прошлом уроке мы сформулировали estimand:

```text
ATE = E[Y(assisted) - Y(no_assistance) | eligible_high_friction_users]
```

Теперь хочется «просто добавить controls» и посчитать regression. В данных есть много
полей: `friction_score`, `platform`, `support_minutes_14d`,
`onboarding_completed_48h`, `telemetry_complete_30d`. Если взять всё, модель станет
выглядеть серьезнее.

Но causal-ошибка здесь тонкая и дорогая:

- `friction_score` — причина treatment и outcome, его нужно рассмотреть как confounder;
- `onboarding_completed_48h` — mediator после treatment, для total effect его нельзя
  контролировать;
- `opened_support_chat_after_offer` — post-treatment collider, conditioning on it может
  открыть новый некаузальный путь;
- `telemetry_complete_30d` — selection variable, complete-case filter меняет population;
- `latent_motivation` не наблюдается, поэтому даже хороший measured adjustment set не
  обязан идентифицировать ATE.

DAG нужен, чтобы не спорить словами «кажется, контролировать полезно», а явно проверить:
какие пути открыты, какие закрываются и какие ограничения остаются.

## Концепция

### DAG хранит assumptions, а не найденные корреляции

Причинный DAG — направленный ациклический граф. Узлы — переменные или конструкты, ребра —
утверждения вида «A может причинно влиять на B». Стрелка не появляется потому, что
корреляция значима, и не исчезает потому, что коэффициент regression мал.

В уроке primary treatment:

```text
assisted_within_24h
```

primary outcome:

```text
activation_14d
```

Часть backdoor paths очевидна:

```text
assisted_within_24h <- friction_score -> activation_14d
assisted_within_24h <- specialist_capacity -> activation_14d
assisted_within_24h <- latent_motivation -> activation_14d
```

Если такой путь открыт, наблюдаемое сравнение treated/control смешивает эффект помощи и
различия в том, кому помощь досталась.

### Association и intervention — разные запросы к миру

Наблюдаемая ассоциация:

```text
P(activation_14d | assisted_within_24h = true)
```

оставляет механизм назначения treatment как есть. В нашем мире в treatment чаще попадают
пользователи с высоким friction и с доступной capacity.

Интервенция:

```text
P(activation_14d | do(assisted_within_24h = true))
```

мысленно фиксирует treatment. В графе это означает: входящие стрелки в treatment
разрываются, а исходящие causal paths из treatment остаются.

```text
friction_score ─┐
capacity ───────┼──> assisted_within_24h ──> activation_14d
motivation ─────┘

do(assisted_within_24h): удалить входящие стрелки в treatment
```

Это не estimator. Это объект идентификации.

### D-separation говорит, какие пути активны

Путь между treatment и outcome активен, если conditioning не заблокировал его. Правила:

1. Non-collider на пути блокирует путь, если мы на него condition.
2. Collider блокирует путь сам по себе.
3. Conditioning on collider или его descendant открывает путь.

Пример confounder path:

```text
assisted_within_24h <- friction_score -> activation_14d
```

Если condition on `friction_score`, этот путь закрывается.

Пример collider path:

```text
assisted_within_24h -> opened_support_chat_after_offer <- friction_score -> activation_14d
```

Без conditioning путь закрыт на collider. Если отфильтровать только пользователей с
`opened_support_chat_after_offer = true`, путь открывается.

### Identification не равен estimator

Regression, matching, IPW и AIPW — это способы оценки выражения, которое уже
идентифицировано при stated assumptions. Они не могут сами доказать, что нужный estimand
выражается через наблюдаемые данные.

В этом уроке валидный статус:

```text
not_identified_from_observed_variables
```

Почему так строго? В DAG есть:

```text
assisted_within_24h <- latent_motivation -> activation_14d
```

Measured baseline controls могут закрыть наблюдаемые пути, но не закрывают прямой путь
через ненаблюдаемую мотивацию. Следующий урок будет аккуратно разбирать, можно ли
сузить claim, добавить proxy-обоснование, выбрать другой дизайн или честно оставить
ограничение.

## Соберите это

Файлы урока:

```text
outputs/causal_dag.json
outputs/identification_map.json
outputs/causal_dag_validator.py
```

### Шаг 1: задайте узлы с ролями и timing

Фрагмент `causal_dag.json`:

```json
{
  "id": "onboarding_completed_48h",
  "role": "mediator",
  "timing": "mediator",
  "observed": true
}
```

Роль нужна не для красоты. Валидатор запрещает использовать mediator, collider,
selection и outcome как обычные baseline controls для total effect.

### Шаг 2: запишите стрелки как assumptions

Примеры ребер:

```json
{"source": "friction_score", "target": "assisted_within_24h"}
{"source": "friction_score", "target": "activation_14d"}
{"source": "assisted_within_24h", "target": "onboarding_completed_48h"}
```

Первая пара создает backdoor path. Последняя стрелка показывает mediator: для total
effect этот путь должен оставаться открытым.

### Шаг 3: проверьте ацикличность и temporal order

`causal_dag_validator.py` делает две базовые проверки:

```text
graph_is_acyclic
temporal_order_respected
```

Если добавить стрелку:

```text
activation_14d -> friction_score
```

валидатор отвергнет граф: outcome не может причинять baseline score в этом target-trial
дизайне.

### Шаг 4: реализуйте d-separation на простых путях

Валидатор перечисляет простые undirected paths и проверяет каждый промежуточный узел:

```python
if collider:
    path_is_active_only_if_collider_or_descendant_is_conditioned
else:
    path_is_blocked_if_node_is_conditioned
```

Это маленькая ручная версия механизма, который позже можно заменить библиотечным API.
Она нужна, чтобы студент видел, почему collider ведет себя противоположно confounder.

### Шаг 5: составьте identification map

`identification_map.json` связывает граф с estimand:

```json
{
  "treatment": "assisted_within_24h",
  "outcome": "activation_14d",
  "effect": "total_effect",
  "identification_status": "not_identified_from_observed_variables",
  "estimator": "not_selected"
}
```

Заметьте: `estimator` намеренно не выбран. Пока нет идентификации, regression будет
не ответом, а красивой машинкой для associational number.

## Используйте это

Запустите пример из корня репозитория:

```bash
python3 phases/13-causal-analysis/02-causal-dags/code/main.py
```

Ожидаемый смысл вывода:

```json
{
  "audit_valid": true,
  "identification_status": "not_identified_from_observed_variables",
  "active_backdoor_paths_without_adjustment": 48,
  "active_backdoor_paths_after_measured_adjustment": 1,
  "remaining_backdoor_example": [
    "assisted_within_24h",
    "latent_motivation",
    "activation_14d"
  ],
  "collider_path_active_without_conditioning": false,
  "collider_path_active_after_conditioning": true
}
```

Standalone CLI:

```bash
cd phases/13-causal-analysis/02-causal-dags
python3 outputs/causal_dag_validator.py \
  --dag outputs/causal_dag.json \
  --identification-map outputs/identification_map.json \
  --question ../01-causal-question-and-estimand/outputs/causal_question.json \
  --estimand ../01-causal-question-and-estimand/outputs/estimand.json \
  --output outputs/dag_audit.json
```

`dag_audit.json` можно передать следующему уроку как machine-readable evidence: граф
валиден, но primary ATE не идентифицирован из одних observed variables.

## Сломайте это

Попробуйте три мутации.

### 1. Стрелка из будущего в прошлое

Добавьте:

```json
{"source": "activation_14d", "target": "friction_score"}
```

Проверки `graph_is_acyclic` и/или `temporal_order_respected` должны упасть.

### 2. Collider как фильтр

Поменяйте adjustment set на:

```json
["friction_score", "opened_support_chat_after_offer"]
```

Такой set invalid: conditioning on support chat открывает collider path.

### 3. Estimator до identification

Поставьте:

```json
"estimator": "logistic_regression"
```

Валидатор вернет `estimator_selected_before_identification`. Это намеренно: урок про
идентификацию, а не про оценку.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest phases/13-causal-analysis/02-causal-dags/tests/test_main.py
```

Покрываются failure modes:

- цикл в графе;
- неизвестный узел в ребре;
- нарушение temporal order;
- несовпадение `question_id`, `estimand_id` и `graph_id`;
- открытый backdoor path через unmeasured confounder;
- collider, который открывается conditioning;
- mediator, ошибочно помеченный как достаточный control;
- преждевременный выбор estimator;
- CLI, который пишет audit и возвращает non-zero для invalid graph.

## Поставьте результат

Итоговый артефакт:

```text
outputs/causal_dag_validator.py
```

Он принимает causal DAG и identification map, проверяет их и возвращает машинный audit.
Переиспользуемый сценарий:

1. команда формулирует causal question и estimand;
2. аналитик записывает DAG как JSON;
3. валидатор проверяет структуру, d-separation и bad controls;
4. следующий урок получает `dag_audit.json` и решает, какой adjustment claim можно
   честно защищать.

## Упражнения

1. Добавьте в DAG узел `pricing_localization_quality` как baseline confounder между
   `region_id` и `paid_subscription_30d`. Объясните, меняет ли он primary outcome
   `activation_14d`.
2. Создайте новый d-separation check для пути
   `assisted_within_24h <- specialist_capacity -> activation_14d` и покажите, какой
   control его блокирует.
3. Сформулируйте версию graph assumptions, где `latent_motivation` считается достаточно
   хорошо проксированной `sessions_before_time_zero` и `onboarding_steps_before_time_zero`.
   Почему это уже не чистая проверка графа, а дополнительное substantive assumption?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| DAG | Диаграмма корреляций | Направленный ациклический граф causal assumptions |
| Backdoor path | Любой путь между treatment и outcome | Путь, который начинается стрелкой в treatment и может создавать confounding |
| D-separation | Автоматическое доказательство причинности | Графическое правило условной независимости при заданном DAG |
| Collider | Переменная, которую полезно контролировать, потому что она связана с двумя факторами | Узел вида `A -> C <- B`; conditioning on it может открыть путь |
| Mediator | Хороший control, потому что объясняет механизм | Переменная на causal path; для total effect ее нельзя контролировать |
| Identification | Выбор regression или matching | Доказательство, что estimand выражается через наблюдаемые распределения при assumptions |

## Дополнительное чтение

- [Hernán и Robins — Causal Inference: What If](https://miguelhernan.org/whatifbook) — главы про target trial, exchangeability и positivity; это основной мост между вопросом из 13/01 и DAG/adjustment reasoning.
- [Pearl — Causal diagrams for empirical research](https://ftp.cs.ucla.edu/pub/stat_ser/r218-b.pdf) — первичный текст о causal diagrams, intervention и графических критериях; читать для математической интуиции за d-separation.
- [DAGitty manual](https://www.dagitty.net/manual-3.x.pdf) — практический reference по
  построению DAG, adjustment sets и типичным графическим ошибкам.
- [NetworkX: D-Separation](https://networkx.org/documentation/stable/reference/algorithms/d_separation.html) — официальный API, к которому можно перейти после ручной реализации, когда нужен проверенный graph algorithm вместо учебного валидатора.
