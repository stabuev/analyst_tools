# Colliders, mediators и selection bias

> Плохой control часто выглядит как хороший predictor; causal adjustment выбирается по роли в DAG, а не по доступности колонки.

**Тип:** Case  
**Треки:** Decision, Product  
**Пререквизиты:** 13/03 — Confounders и backdoor adjustment  
**Время:** ~75 минут  
**Результат:** распознает collider, mediator, descendant of treatment и selection variable,
объясняет bias от bad controls и блокирует adjustment по post-treatment данным.

## Цели обучения

- Отличать baseline confounder от post-treatment descendant.
- Объяснять, почему mediator нельзя добавлять в adjustment set для primary total effect.
- Показывать, как conditioning on collider открывает некаузальный путь.
- Фиксировать selection bias от complete-case фильтра после treatment.
- Передавать в будущие estimators только разрешенный observed baseline set.

## Проблема

После `13/03` у нас есть рабочий observed baseline adjustment set:

```text
platform
device_tier
acquisition_channel
region_id
language
network_quality
app_crashes_before_time_zero
onboarding_steps_before_time_zero
sessions_before_time_zero
friction_score
specialist_capacity
```

Он закрывает measured backdoor paths, но оставляет limitation через unmeasured
`latent_motivation`. Теперь появляется знакомый соблазн:

```text
Давайте добавим еще полезные признаки:
- onboarding_completed_48h
- opened_support_chat_after_offer
- telemetry_complete_30d
- paid_subscription_30d
```

Для predictive модели такие признаки могут быть сильными. Для causal estimate primary
total effect они опасны:

- `onboarding_completed_48h` — mediator: treatment влияет на completion, completion
  влияет на activation;
- `opened_support_chat_after_offer` — collider: на support chat могут влиять и assistance,
  и высокий friction;
- `telemetry_complete_30d` — selection variable: complete-case фильтр после treatment
  меняет population;
- `activation_14d` и downstream outcomes — leakage, потому что outcome нельзя использовать
  как control для своего эффекта.

Урок строит аудитор, который превращает это в машинный gate:

```text
candidate action -> role/timing/descendant audit -> allowed or rejected handoff
```

## Концепция

### Mediator меняет estimand

В DAG есть directed total-effect path:

```text
assisted_within_24h -> onboarding_completed_48h -> activation_14d
```

Если мы контролируем `onboarding_completed_48h`, то спрашиваем уже не primary total
effect. Мы частично блокируем путь, по которому assistance могла сработать. Это может
быть осмысленным вопросом про direct effect, но это другой estimand, другой дизайн и
другие assumptions.

Правило урока:

```text
primary total effect -> не conditioning on mediator
```

### Collider открывает путь

Collider — переменная, в которую входят две стрелки. В нашем графе:

```text
assisted_within_24h -> opened_support_chat_after_offer <- friction_score -> activation_14d
```

Без conditioning path через support chat закрыт в collider. Если отфильтровать только
пользователей, открывших support chat, или добавить этот признак как control, path может
открыться. Тогда внутри selected subgroup treatment начинает некаузально ассоциироваться
с friction и outcome.

Это контринтуитивно: кажется, что мы «сравниваем похожих пользователей, которые обращались
в поддержку». На самом деле мы сравниваем внутри группы, попадание в которую само является
следствием treatment и проблем пользователя.

### Selection bias — это не просто missing data

`telemetry_complete_30d=true` выглядит как аккуратная аналитическая чистка: оставим только
полные наблюдения. Но в DAG:

```text
assisted_within_24h -> telemetry_complete_30d
activation_14d -> telemetry_complete_30d
opened_support_chat_after_offer -> telemetry_complete_30d
```

Если анализ молча оставляет только complete cases после treatment, target population уже
не та, что была в causal question. Selection может открыть paths и сделать estimate
свойством selected subgroup, а не eligible users.

### Outcome leakage — самый простой bad control

`activation_14d` нельзя использовать как feature, если мы оцениваем эффект на
`activation_14d`. Downstream outcome `paid_subscription_30d` тоже не является baseline
confounder для activation effect: он происходит позже и является descendant product
journey.

Для causal study полезно держать три корзины:

| Корзина | Пример | Можно в primary adjustment? |
|---|---|---|
| Observed baseline confounder | `friction_score`, `region_id` | Да, если нужен для backdoor |
| Post-treatment bad control | `onboarding_completed_48h`, `opened_support_chat_after_offer` | Нет |
| Outcome / descendant outcome | `activation_14d`, `paid_subscription_30d` | Нет |

## Соберите это

Артефакты урока:

```text
outputs/bad_control_policy.json
outputs/candidate_control_actions.json
outputs/bad_control_selection_auditor.py
outputs/bad_control_selection_audit.json
```

### Шаг 1: зафиксируйте bad-control policy

Policy перечисляет переменные, которые нельзя использовать в primary total-effect
adjustment:

```json
{
  "variable": "onboarding_completed_48h",
  "control_type": "mediator",
  "expected_status": "invalid_blocks_total_effect",
  "allowed_for_primary_total_effect": false
}
```

Важная часть — `expected_status`. Мы не просто пишем комментарий в текстовом отчете, а
делаем проверяемый contract: если DAG говорит, что переменная mediator, policy не может
назвать ее harmless baseline control.

### Шаг 2: опишите candidate control actions

Candidate action — это не только adjustment set. Это может быть filter или feature set:

```json
{
  "action_id": "telemetry_complete_case_filter",
  "action_type": "filter",
  "variables": [],
  "filter_variables": ["telemetry_complete_30d"],
  "declared_status": "invalid_selection_bias",
  "allowed_for_estimation": false,
  "population_change": "Restricts analysis to users with post-treatment complete telemetry."
}
```

Так мы ловим ошибку до estimator: future RA/matching/IPW уроки не должны случайно принять
post-treatment filtered cohort как исходную target population.

### Шаг 3: рассчитайте механизм ошибки

Аудитор использует DAG из `13/02` и d-separation helpers. Для каждого candidate action он
считает:

- role, timing и observed status каждой переменной;
- является ли переменная descendant of treatment;
- сколько active paths появляется после conditioning;
- какие directed total-effect paths блокирует mediator;
- остались ли measured/unmeasured backdoor paths.

Для mediator report содержит пример:

```text
assisted_within_24h -> onboarding_completed_48h -> activation_14d
```

Для collider report показывает opened path:

```text
assisted_within_24h -- opened_support_chat_after_offer -- friction_score -- activation_14d
```

Это и есть учебная ценность: аудитор объясняет, почему action отклонен.

## Используйте это

Из корня урока:

```bash
python outputs/bad_control_selection_auditor.py \
  --dag ../02-causal-dags/outputs/causal_dag.json \
  --policy outputs/bad_control_policy.json \
  --candidate-actions outputs/candidate_control_actions.json \
  --data-contract ../data/contract.json \
  --output outputs/bad_control_selection_audit.json
```

Компактный пример:

```bash
python code/main.py
```

Ожидаемая логика результата:

```json
{
  "primary_action": "recommended_pre_treatment_set",
  "allowed_actions": ["recommended_pre_treatment_set"],
  "mediator_blocks_directed_paths": 1,
  "collider_newly_opened_paths": 29,
  "selection_newly_opened_paths": 146
}
```

Точные counts могут измениться, если поменять DAG, но смысл должен сохраниться: only
observed baseline handoff разрешен, bad controls rejected.

## Сломайте это

Попробуйте внести типичные ошибки.

### Ошибка 1: назвать mediator разрешенным control

В `bad_control_policy.json` поменяйте:

```json
"expected_status": "allowed_pre_treatment_adjustment"
```

для `onboarding_completed_48h`. Аудитор должен провалить check:

```text
bad_control_policy_classifications_match_graph
```

### Ошибка 2: забыть selection variable в policy

Удалите `telemetry_complete_30d` из `bad_controls`. Это не косметика: policy больше не
покрывает DAG bad controls. Check:

```text
policy_covers_graph_bad_controls
```

### Ошибка 3: сделать filter без population-change описания

Очистите `population_change` у `telemetry_complete_case_filter`. Если filter меняет
cohort после treatment, он обязан явно сказать, какую population он оставляет.

### Ошибка 4: протащить bad control как primary recommendation

Добавьте `onboarding_completed_48h` в `recommended_pre_treatment_set`. Аудитор должен
заблокировать primary action, даже если остальные baseline covariates корректны.

## Проверьте это

Behavioral tests проверяют:

- valid policy покрывает mediator, collider, selection, assignment mechanism и outcomes;
- primary recommendation содержит только observed baseline controls;
- mediator блокирует directed total-effect path;
- collider и selection открывают новые active paths;
- outcome leakage отклоняется отдельно;
- filter action обязан описывать population change;
- unknown variables не принимаются даже как teaching counterexample;
- CLI возвращает non-zero при невалидной спецификации.

Запуск:

```bash
python -m unittest tests/test_main.py
```

## Поставьте результат

Именованный артефакт:

```text
bad-control-selection-auditor
```

Он нужен как gate между identification lessons и estimator lessons:

```text
13/03 backdoor set
  -> 13/04 bad-control audit
  -> 13/05 regression adjustment
  -> 13/06 matching
  -> 13/07 IPW/AIPW
```

Передавайте дальше только `recommended_pre_treatment_set`. Остальные candidate actions
остаются в package как объяснимые rejected alternatives — они полезны для ревью дизайна,
но не должны кормить estimator.

## Упражнения

1. Добавьте candidate action, который контролирует `paid_subscription_30d`, и объясните,
   почему это outcome leakage для activation estimand.
2. Перепишите `support_chat_restricted_cohort` как не filter, а feature в regression.
   Должен ли измениться causal verdict?
3. Найдите в DAG еще один path, который открывается после conditioning on
   `telemetry_complete_30d`, и объясните его словами.
4. Спроектируйте новый estimand для controlled direct effect через
   `onboarding_completed_48h`. Какие assumptions и policy должны измениться?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Mediator | «Хороший predictor outcome, значит надо контролировать» | Переменная на causal path от treatment к outcome; для total effect обычно не conditioning |
| Collider | «Общая переменная делает группы похожими» | Общий эффект двух причин; conditioning может открыть некаузальный path |
| Selection bias | «Мы просто убрали неполные данные» | Отбор после treatment может изменить target population и открыть paths |
| Descendant of treatment | «После treatment тоже можно, если колонка доступна» | Следствие treatment; control может изменить estimand или внести bias |
| Outcome leakage | «Модель станет точнее» | Использование outcome/downstream outcome как feature разрушает causal estimate |

## Дополнительное чтение

- [Hernán and Robins: Causal Inference: What If](https://miguelhernan.org/whatifbook) — главы про exchangeability, selection и target trial помогают отделять design от modeling.
- [Pearl: Causal Diagrams for Empirical Research](https://ftp.cs.ucla.edu/pub/stat_ser/r218-b.pdf) — первичный источник по DAG, d-separation, colliders и backdoor reasoning.
- [DAGitty manual](https://www.dagitty.net/manual-3.x.pdf) — практическая справка по adjustment sets, biasing paths и графической проверке assumptions.
- [DoWhy documentation: Identification](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/identifying_causal_effect/index.html) — как library workflow разделяет graph assumptions, identification и estimation.
