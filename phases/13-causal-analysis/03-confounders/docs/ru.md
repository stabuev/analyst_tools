# Confounders и backdoor adjustment

> Хороший adjustment set не равен «все доступные колонки»; он закрывает нужные backdoor paths и честно оставляет то, что закрыть нельзя.

**Тип:** Build  
**Треки:** Decision, Product  
**Пререквизиты:** 13/02 — Причинные DAG и идентификация  
**Время:** ~75 минут  
**Результат:** находит открытые backdoor paths, выбирает pre-treatment adjustment set для
измеренного confounding и фиксирует, какие confounders измерены, проксированы или остаются
ненаблюдаемыми.

## Цели обучения

- Отличать confounder от mediator, collider, selection variable и assignment mechanism.
- Строить confounder inventory из DAG, а не из списка корреляций.
- Проверять, что measured confounders действительно наблюдаются до treatment и есть в data contract.
- Сравнивать candidate adjustment sets по active backdoor paths.
- Формулировать честный claim policy, когда observed adjustment не закрывает unmeasured confounding.

## Проблема

После `13/02` у нас есть DAG и неприятный, но честный вывод:

```text
active_backdoor_paths_without_adjustment = 48
```

Часть путей проходит через очевидные measured variables:

```text
assisted_within_24h <- friction_score -> activation_14d
assisted_within_24h <- specialist_capacity -> activation_14d
```

Если просто сравнить treated/control, мы сравним не только помощь, но и то, кому помощь
доставалась. Однако другая ошибка не лучше: взять все колонки, включая
`onboarding_completed_48h`, `opened_support_chat_after_offer` и
`telemetry_complete_30d`, и назвать это «контролем факторов».

Этот урок превращает DAG в рабочий audit:

```text
active paths -> confounder inventory -> candidate sets -> claim policy
```

Важный нюанс: recommended measured set закрывает observed/measured backdoor paths, но не
идентифицирует primary ATE полностью, потому что в графе остаётся:

```text
assisted_within_24h <- latent_motivation -> activation_14d
```

## Концепция

### Confounder — это роль в причинной истории

Confounder — pre-treatment причина или общий источник treatment assignment и outcome.
Он не обязан иметь самый большой коэффициент в regression. И наоборот, сильный predictor
после treatment может быть плохим control.

В нашем DAG measured confounders:

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

Unmeasured confounder:

```text
latent_motivation
```

`sessions_before_time_zero` и `onboarding_steps_before_time_zero` — полезные measured
proxies для мотивации, но proxy не становится магически полной заменой unobserved
construct. Для такого шага нужен отдельный substantive argument и sensitivity analysis.

### Backdoor adjustment закрывает пути, а не украшает модель

Backdoor path начинается стрелкой в treatment. Если путь активен, association между
treatment и outcome может возникать без causal effect.

Naive set:

```json
[]
```

оставляет открытыми measured и unmeasured paths. Узкий set:

```json
["friction_score", "specialist_capacity"]
```

закрывает очевидные assignment drivers, но всё ещё оставляет measured paths через
baseline UX, region, network quality и behavior. Поэтому аудитор отвергает его как
`insufficient_measured_backdoors_open`.

Recommended measured set:

```json
[
  "platform",
  "device_tier",
  "acquisition_channel",
  "region_id",
  "language",
  "network_quality",
  "app_crashes_before_time_zero",
  "onboarding_steps_before_time_zero",
  "sessions_before_time_zero",
  "friction_score",
  "specialist_capacity"
]
```

закрывает measured backdoor paths, но оставляет one open unmeasured path через
`latent_motivation`. Поэтому его статус длинный, зато честный:

```text
recommended_measured_adjustment_with_unmeasured_limitation
```

### Forbidden controls должны быть названы явно

Некоторые переменные доступны в данных, но не являются baseline confounders для primary
total effect:

| Переменная | Почему нельзя в primary adjustment |
|---|---|
| `offered_assistance` | assignment mechanism на treatment timing; меняет received-treatment question |
| `onboarding_completed_48h` | mediator; блокирует часть total effect |
| `opened_support_chat_after_offer` | post-treatment collider; может открыть некаузальный path |
| `telemetry_complete_30d` | post-treatment selection; complete-case filter меняет population |
| `activation_14d` | primary outcome |

Аудитор не просто запрещает эти variables: он показывает, что `telemetry_complete_30d`
может открыть больше путей, чем было в naive graph. Это полезное противоядие от фразы
«мы просто почистили данные».

### Identification status — часть артефакта

`adjustment_set_spec.json` содержит claim policy:

```json
{
  "identification_status": "not_identified_due_to_unmeasured_confounding",
  "allowed_effect_claim": false
}
```

Это не пессимизм, а нормальная дисциплина. Урок ещё не говорит «эффекта нет» и не говорит
«эффект найден». Он говорит: observed adjustment set готов для следующих estimators и
diagnostics, но primary causal claim пока нельзя выпускать.

## Соберите это

Артефакты урока:

```text
outputs/confounder_inventory.json
outputs/adjustment_set_spec.json
outputs/backdoor_adjustment_auditor.py
outputs/backdoor_adjustment_audit.json
```

### Шаг 1: перечислите confounders

Каждый measured confounder должен быть:

- узлом в DAG;
- observed;
- baseline;
- связан с source field из `data/contract.json`;
- включён в inventory, если появляется на active backdoor paths.

Фрагмент:

```json
{
  "variable": "friction_score",
  "measurement_status": "measured",
  "adjustment_role": "include"
}
```

Для unmeasured:

```json
{
  "variable": "latent_motivation",
  "measurement_status": "unmeasured",
  "adjustment_role": "cannot_adjust_directly",
  "proxy_variables": ["sessions_before_time_zero", "onboarding_steps_before_time_zero"]
}
```

### Шаг 2: зафиксируйте forbidden controls

Не надейтесь, что future regression сама поймет, что `onboarding_completed_48h` является
mediator. Запишите это машинно:

```json
{
  "variable": "onboarding_completed_48h",
  "forbidden_reason": "mediator on the total-effect path"
}
```

### Шаг 3: сравните candidate sets

`adjustment_set_spec.json` содержит несколько candidates:

- `none`;
- `friction_capacity_only`;
- `measured_baseline_backdoor_set`;
- `oracle_latent_adjustment`;
- bad-control sets с mediator, collider и selection.

Аудитор для каждого set считает:

```text
active_backdoor_paths
open_measured_backdoor_paths
open_unmeasured_backdoor_paths
forbidden_variables
unobserved_variables
calculated_status
```

### Шаг 4: проверьте primary recommendation

Primary set должен быть ровно один:

```json
"is_primary_recommendation": true
```

И он обязан:

- не содержать unknown variables;
- не содержать unobserved variables;
- не содержать forbidden controls;
- закрывать measured backdoor paths;
- не разрешать causal effect claim, если остается unmeasured path.

## Используйте это

Запуск учебного примера из корня репозитория:

```bash
python3 phases/13-causal-analysis/03-confounders/code/main.py
```

Ожидаемый смысл:

```json
{
  "audit_valid": true,
  "active_backdoor_paths_without_adjustment": 48,
  "recommended_set_id": "measured_baseline_backdoor_set",
  "recommended_open_measured_paths": 0,
  "recommended_open_unmeasured_paths": 1,
  "remaining_unmeasured_path": [
    "assisted_within_24h",
    "latent_motivation",
    "activation_14d"
  ],
  "identification_status": "not_identified_due_to_unmeasured_confounding"
}
```

Standalone CLI из корня урока:

```bash
cd phases/13-causal-analysis/03-confounders
python3 outputs/backdoor_adjustment_auditor.py \
  --dag ../02-causal-dags/outputs/causal_dag.json \
  --inventory outputs/confounder_inventory.json \
  --adjustment-spec outputs/adjustment_set_spec.json \
  --data-contract ../data/contract.json \
  --output outputs/backdoor_adjustment_audit.json
```

## Сломайте это

### Забыть confounder

Удалите `friction_score` из `confounder_inventory.json`. Аудитор должен упасть на:

```text
active_backdoor_confounders_are_in_inventory
```

### Назвать latent variable измеренной

Поменяйте:

```json
"latent_motivation": {"measurement_status": "measured"}
```

Это invalid: в DAG `observed=false`, и в data contract нет такой колонки.

### Разрешить effect claim

Поставьте:

```json
"allowed_effect_claim": true
```

Аудитор должен заблокировать spec, потому что recommended set оставляет open unmeasured
path.

### Добавить mediator

Добавьте `onboarding_completed_48h` в primary set. Это invalid для total effect: вы
оцените уже другой вопрос.

## Проверьте это

Запуск тестов урока:

```bash
uv run --locked python -m unittest phases/13-causal-analysis/03-confounders/tests/test_main.py
```

Проверяются:

- валидный measured/unmeasured inventory;
- участие `friction_score` и `latent_motivation` в active backdoor paths;
- наличие source fields в data contract;
- запрет unmeasured variable в observed adjustment;
- ровно один primary recommendation;
- статус candidate sets по графу;
- forbidden mediator/collider/selection controls;
- запрет causal effect claim при remaining unmeasured confounding;
- CLI non-zero для invalid adjustment spec.

## Поставьте результат

Итоговый артефакт:

```text
outputs/backdoor_adjustment_auditor.py
```

Он поставляет reusable contract для следующих уроков:

- `13/04` получит список forbidden controls и разберёт bad-control/selection bias глубже;
- `13/05` сможет использовать `measured_baseline_backdoor_set` для g-formula, но с
  ограниченным claim;
- `13/10` вернётся к `latent_motivation` через sensitivity analysis.

Главный итог: мы не спрятали проблему в сноску. Мы сделали её машинно проверяемой частью
исследовательского пакета.

## Упражнения

1. Добавьте candidate set только с `friction_score`, `region_id` и `specialist_capacity`.
   Сколько measured paths останется открытым?
2. Представьте, что команда добавила валидированный survey score мотивации до time zero.
   Какие поля в DAG, inventory и data contract пришлось бы изменить?
3. Сформулируйте claim для stakeholder memo, который честно использует measured
   adjustment set, но не обещает identified ATE.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Confounder | Любой хороший predictor outcome | Pre-treatment причина или общий источник treatment и outcome |
| Adjustment set | Все доступные control variables | Набор variables, выбранный по DAG для закрытия backdoor paths |
| Measured confounder | Любая колонка в таблице | Наблюдаемая baseline variable с известным источником и причинной ролью |
| Unmeasured confounder | То, что можно игнорировать, если есть proxies | Ненаблюдаемый фактор, который остается limitation или требует отдельного design/sensitivity шага |
| Proxy | Полная замена latent variable | Неполное измерение или индикатор, требующий substantive assumption |
| Bad control | Переменная с плохим качеством данных | Variable, conditioning on which changes estimand or opens bias path |

## Дополнительное чтение

- [Hernán и Robins — Causal Inference: What If](https://miguelhernan.org/whatifbook) — читать главы про exchangeability, positivity и standardization; они объясняют, почему adjustment set является assumption о сравнимости, а не механической regression recipe.
- [Pearl — Causal diagrams for empirical research](https://ftp.cs.ucla.edu/pub/stat_ser/r218-b.pdf) — первичный текст о backdoor criterion и causal diagrams; полезен, чтобы связать path blocking с идентификацией, а не только с визуальной схемой.
- [DAGitty manual](https://www.dagitty.net/manual-3.x.pdf) — практический reference по minimal sufficient adjustment sets, forbidden nodes и типичным ошибкам при ручном построении DAG.
- [DoWhy: Identifying causal effects](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/identifying_causal_effect/index.html) — официальный workflow identify-шага; читать как будущую автоматизированную проверку того, что в уроке сделано прозрачным валидатором.
