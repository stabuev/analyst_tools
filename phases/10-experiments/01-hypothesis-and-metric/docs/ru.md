# Гипотеза и целевая метрика

> Эксперимент начинается не с p-value, а с заранее подписанного вопроса и правила решения.

**Тип:** Learn  
**Треки:** Product  
**Пререквизиты:** 08/11 - Бизнес-вывод и рекомендация; 09/10 - Робастные и непараметрические методы  
**Время:** ~75 минут  
**Результат:** переводит продуктовую гипотезу в pre-registered experiment protocol:
variants, eligible population, primary metric, guardrails, metric windows, alpha/power
assumptions и decision rule до просмотра результата.

## Цели обучения

- Разделять продуктовую гипотезу, статистическую гипотезу и decision rule.
- Назначать одну primary metric и не подменять ее secondary или exploratory метриками.
- Фиксировать guardrail-метрики с направлением риска до запуска анализа.
- Объявлять eligible population, exposure event и metric windows до расчета эффекта.
- Проверять protocol как машинный контракт, а не как красивый текст в документе.

## Проблема

Команда подписочного сервиса хочет протестировать новый Android paywall с короткой
подсказкой в onboarding. После продуктовой фазы уже понятно, почему идея появилась:
ранняя активация может вырасти, но у команды есть риск роста обращений в поддержку,
отмен подписки и refund.

Плохой старт эксперимента звучит так:

```text
Запустим A/B, посмотрим на activation, trial, revenue, support и сегменты.
Если что-нибудь будет значимым, примем решение.
```

Такой план не говорит, какой вопрос главный, какие ухудшения запрещают rollout и что
делать при смешанном результате. После получения чисел команда легко меняет критерий:
если primary не сработала, смотрит secondary; если overall нейтрален, ищет удачный
сегмент; если guardrail ухудшился, называет его "наблюдением на потом".

В этом уроке вы фиксируете protocol до анализа:

```text
product hypothesis -> variants -> eligible population -> metrics -> windows -> decision rule
```

Артефакт урока должен ответить: можно ли этот experiment protocol отдать в работу, не
оставляя аналитику свободу поменять правила после просмотра результата?

## Концепция

### Продуктовая и статистическая гипотеза отвечают на разные вопросы

Продуктовая гипотеза описывает механизм продукта:

```text
Если Android-пользователь увидит более ясный paywall с onboarding hint, он чаще дойдет
до первого value moment за семь дней.
```

Статистическая гипотеза переводит это в сравнение вариантов:

```text
H0: activation_rate_7d(treatment) = activation_rate_7d(control)
H1: activation_rate_7d(treatment) > activation_rate_7d(control)
```

Если первая часть не сформулирована, эксперимент превращается в поиск отличий. Если
вторая часть не сформулирована, продуктовая идея остается рассказом без проверяемого
критерия.

### Primary metric - это не самая красивая метрика после расчета

Primary metric выбирают заранее, потому что она определяет основной успех эксперимента.
В уроке это:

```text
activation_rate_7d
```

Secondary metrics помогают понять механизм:

```text
paywall_to_trial_conversion_7d
realized_revenue_per_user_7d
```

Exploratory metrics помогают сформулировать следующие вопросы, но не дают права менять
launch decision. Например, post-hoc разрез по acquisition channel может объяснить сигнал,
но не заменяет primary metric.

### Guardrail - это граница риска

Guardrail-метрика говорит не "интересно посмотреть", а "дальше нельзя, если стало хуже".
В протоколе урока:

```text
support_ticket_rate_7d              up_is_bad
subscription_cancel_rate_14d        up_is_bad
refund_rate_7d                      up_is_bad
```

Положительный lift primary metric не является запуском, если guardrails breached. Это
продуктовое правило, а не статистическая тонкость.

### Metric window меняет смысл эффекта

`activation_rate_7d` после exposure и `activation_rate_7d` после регистрации отвечают на
разные вопросы. В эксперименте окно должно стартовать от события, через которое вариант
мог повлиять на пользователя:

```text
exposure_event = paywall_viewed
metric_window = 7 days after exposure_event
```

Если окно выбирается после результата, оно становится частью подгонки.

### Decision rule должен быть скучным

Хороший rule заранее ограничивает набор решений:

```text
launch
hold
rollback
iterate
inconclusive
```

И заранее говорит, что нужно для launch: primary metric проходит заявленный критерий,
effect size не меньше MDE, а guardrails не breached. В реальной работе это снижает
конфликт: команда спорит о протоколе до эксперимента, а не о трактовке после.

## Соберите это

Откройте `code/main.py`. Ручная часть урока не считает p-value. Она показывает, что
первый уровень проверки протокола можно сделать без статистической библиотеки:

```python
def manual_metric_role_map(specs):
    roles = {"primary": [], "guardrail": [], "secondary": [], "exploratory": []}
    for spec in specs:
        role = spec["role"]
        if role in roles:
            roles[role].append(spec["metric_id"])
    return {role: sorted(metric_ids) for role, metric_ids in roles.items() if metric_ids}
```

Запустите пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/01-hypothesis-and-metric/code/main.py
```

Фрагмент результата:

```json
{
  "primary_metric": "activation_rate_7d",
  "guardrail_metrics": [
    "support_ticket_rate_7d",
    "subscription_cancel_rate_14d",
    "refund_rate_7d"
  ],
  "manual_missing_metric_windows": [],
  "protocol_valid": true,
  "blocking_checks": []
}
```

### Шаг 1: зафиксируйте variants

В `outputs/experiment_protocol.json` есть два варианта:

```json
[
  {"variant_id": "control", "is_control": true},
  {"variant_id": "treatment", "is_control": false}
]
```

Traffic allocation должен ссылаться ровно на эти `variant_id` и суммироваться в `1.0`.
Если allocation не совпадает с вариантами, дальше нельзя проверять SRM и effect.

### Шаг 2: задайте eligible population

В уроке эксперимент касается только eligible non-test Android users:

```json
{
  "unit": "user_id",
  "source_table": "users",
  "filters": [
    {"field": "platform", "operator": "==", "value": "android"},
    {"field": "is_test_user", "operator": "==", "value": false}
  ]
}
```

Это не просто фильтр в pandas. Это обещание, о какой популяции будет решение. Если в
анализ попадут web users или internal traffic, эффект будет отвечать на другой вопрос.

### Шаг 3: свяжите metrics и protocol

`outputs/metric_specs.json` описывает каждую метрику:

```text
metric_id
role
grain
eligible_population
numerator
denominator
window_days
expected_direction
source_tables
validation_checks
```

Protocol должен ссылаться на эти же `metric_id`. Primary metric обязана иметь роль
`primary`, guardrails - роль `guardrail`, а secondary metrics - роль `secondary`.

### Шаг 4: объявите MDE, alpha и power

В этом уроке вы не рассчитываете размер выборки. Это будет `10/04`. Но protocol уже
должен сказать, какой эффект считается практически важным:

```json
"minimum_detectable_effect": {
  "metric_id": "activation_rate_7d",
  "absolute": 0.03,
  "relative": 0.1
}
```

Без MDE можно получить "значимый" lift, который слишком мал для продуктового решения, или
назвать эксперимент отрицательным, хотя он просто не имел мощности для нужного эффекта.

### Шаг 5: зафиксируйте decision rule

Launch rule в уроке требует:

```text
primary metric = activation_rate_7d
minimum_absolute_lift = 0.03
p-value <= 0.05
all guardrails not breached
```

Даже если later lessons поменяют способ расчета interval или p-value, правило решения
уже будет известно.

## Используйте это

Артефакт урока - CLI `experiment_protocol_validator.py`.

Запуск из корня урока:

```bash
uv run --locked python outputs/experiment_protocol_validator.py \
  --protocol outputs/experiment_protocol.json \
  --specs outputs/metric_specs.json \
  --data-contract ../data/contract.json \
  --output protocol-report.json
```

Запуск из корня репозитория:

```bash
uv run --locked python phases/10-experiments/01-hypothesis-and-metric/outputs/experiment_protocol_validator.py \
  --protocol phases/10-experiments/01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --specs phases/10-experiments/01-hypothesis-and-metric/outputs/metric_specs.json \
  --data-contract phases/10-experiments/data/contract.json
```

Report содержит stable check ids:

```text
protocol_required_fields
variants_and_allocation
experiment_timeline
statistical_design_parameters
eligible_population_contract
metric_specs_required_fields
metric_roles_declared
protocol_metrics_resolve
metric_windows_declared
metric_sources_exist
guardrail_risk_directions
policies_declared
pre_experiment_covariates_are_pre_treatment
decision_rule_uses_primary_and_guardrails
```

CLI возвращает:

- `0`, если protocol можно считать готовым к pre-registration;
- `1`, если protocol прочитан, но содержит blocking errors;
- `2`, если JSON или путь к файлу не читается.

## Сломайте это

Попробуйте пять мутаций.

1. Поменяйте allocation treatment с `0.5` на `0.4`.

Ожидаемый сбой:

```text
variants_and_allocation
```

2. Измените роль `activation_rate_7d` в metric specs на `secondary`.

Ожидаемый сбой:

```text
protocol_metrics_resolve
```

3. Удалите `activation_rate_7d` из `metric_windows`.

Ожидаемый сбой:

```text
metric_windows_declared
```

4. Поставьте guardrail `support_ticket_rate_7d` direction как `up`.

Ожидаемый сбой:

```text
guardrail_risk_directions
```

5. Разрешите launch без guardrails:

```json
"requires_all_guardrails_not_breached": false
```

Ожидаемый сбой:

```text
decision_rule_uses_primary_and_guardrails
```

Каждая мутация имитирует реальную ошибку: перепутали группы, поменяли главную метрику,
подобрали окно после результата, превратили guardrail в обычную метрику или забыли риск
в решении.

## Проверьте это

Запустите lesson suite:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/01-hypothesis-and-metric/tests -v
```

Тесты проверяют:

- валидный protocol проходит все checks;
- пример `code/main.py` печатает primary, guardrails и отсутствие missing windows;
- duplicate variant и неправильный allocation блокируются;
- primary metric должна ссылаться на spec с ролью `primary`;
- guardrails требуют risk direction `up_is_bad` или `down_is_bad`;
- каждая metric spec имеет exposure-based window;
- source tables существуют в phase data contract;
- timeline соблюдает minimum runtime и metric freeze;
- MDE относится к primary metric и положителен;
- CUPED covariates являются pre-treatment;
- launch decision требует primary success и все guardrails.

Для ручной проверки можно прочитать только `outputs/experiment_protocol.json` и
`outputs/metric_specs.json`: если вы не можете объяснить, почему каждая метрика находится
в своей роли, protocol еще не готов.

## Поставьте результат

Именованный артефакт:

```text
outputs/experiment_protocol_validator.py
```

Он переиспользуется в следующих уроках фазы:

- `10/02` возьмет `randomization_unit`, `analysis_unit`, `assignment_key` и variants;
- `10/03` использует allocation и `aa_srm_policy`;
- `10/04` использует `alpha`, `power`, MDE и `sample_size_plan`;
- `10/05`-`10/07` используют metric specs, windows и CUPED policy;
- `10/11` положит protocol report в итоговый `experiment-decision-package`.

Минимальный handoff после урока:

```text
protocol valid = true
primary metric = activation_rate_7d
guardrails = support_ticket_rate_7d, subscription_cancel_rate_14d, refund_rate_7d
decision rule = launch only when primary success and all guardrails not breached
```

## Упражнения

1. Добавьте secondary metric `trial_started_rate_7d` и добейтесь, чтобы validator принял
   ее только при наличии metric window и source tables.
2. Измените experiment на iOS population: какие поля protocol и data contract должны
   измениться, а какие останутся теми же?
3. Добавьте новый guardrail `app_crash_rate_7d` с направлением риска `up_is_bad` и
   объясните, почему он не должен становиться exploratory после результата.
4. Сформулируйте decision rule для случая, когда primary metric нейтральна, но один
   predeclared segment сильно выигрывает.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Product hypothesis | То же самое, что H0/H1 | Объяснение, почему вариант должен изменить поведение пользователя |
| Statistical hypothesis | Формальность для p-value | Проверяемое утверждение о различии метрики между вариантами |
| Primary metric | Метрика, которая сильнее всего изменилась | Главная метрика успеха, выбранная до анализа |
| Guardrail metric | Второстепенная метрика | Метрика риска, которая может заблокировать launch |
| Metric window | Технический параметр расчета | Часть смысла эффекта: когда начинается и заканчивается наблюдение |
| Decision rule | Итоговая рекомендация аналитика | Заранее объявленная логика выбора launch/hold/rollback/iterate/inconclusive |
| Pre-registration | Бюрократия перед запуском | Фиксация методологии до просмотра результата |

## Дополнительное чтение

- [SciPy `ttest_ind`](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.ttest_ind.html) - официальный API для независимого двухвыборочного t-test; читать параметры `equal_var`, `alternative` и `confidence_interval`, которые понадобятся в `10/05`.
- [statsmodels `TTestIndPower`](https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestIndPower.html) - официальный API для power/sample-size calculations; читать перед `10/04`, где MDE станет расчетом, а не только полем protocol.
- [Ensure A/B Test Quality at Scale with Automated Randomization Validation and Sample Ratio Mismatch Detection](https://arxiv.org/abs/2208.07766) - primary source о randomization validation и SRM; полезен для понимания, почему protocol должен заранее знать allocation и variants.
- [Trustworthy Experimentation Under Telemetry Loss](https://arxiv.org/abs/1903.12470) - primary source о telemetry loss; читать как пример того, почему guardrails и quality checks нельзя добавлять только после странного результата.
