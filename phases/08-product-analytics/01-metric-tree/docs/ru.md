# Дерево метрик

> Продуктовая метрика полезна только тогда, когда ясно, какое решение она защищает.

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 07/10 - Интеграционный quality gate  
**Время:** ~75 минут  
**Результат:** строит дерево outcome, input и guardrail-метрик, задает для каждой
метрики grain, population, numerator, denominator и window и валидирует metric specs.

## Цели обучения

- Начинать дерево метрик с продуктового решения, а не с доступной таблицы.
- Разделять outcome, input и guardrail-метрики.
- Фиксировать grain, eligible population, numerator, denominator и window до расчета.
- Связывать метрику с source tables, validation checks и known failure modes.
- Ловить методологические дефекты дерева машинным отчетом.

## Проблема

Команда изменила onboarding и paywall. В первые дни после rollout ранняя активация
выросла, но support tickets и отмены подписки тоже пошли вверх. Нужно решить, что делать:

```text
continue
rollback
investigate
run_experiment
```

Наивный ответ звучит так:

```text
Активация выросла, значит продолжаем rollout.
```

Это опасно. Возможно, активация выросла из-за другого состава traffic, а новый paywall
создал больше обращений и ранних отмен. Еще хуже, если "активация" посчитана как число
событий `feature_value_seen`, а не как доля пользователей. Тогда активные пользователи с
несколькими событиями раздувают числитель, а знаменатель вообще не назван.

Нужен не один график, а дерево:

```text
activation_rate_7d
├── onboarding_completion_rate
├── paywall_to_trial_conversion_7d
├── guardrail: support_ticket_rate_7d
└── guardrail: subscription_cancel_rate_14d
```

Такое дерево говорит, какую метрику мы улучшаем, какие рычаги могут ее двигать и какие
риски нельзя ухудшить незаметно.

## Концепция

### Outcome, input и guardrail

| Роль | Вопрос | Пример |
|---|---|---|
| Outcome | Какой результат продукта мы хотим улучшить? | `activation_rate_7d` |
| Input | Через какой пользовательский механизм outcome может измениться? | `onboarding_completion_rate` |
| Guardrail | Что не должно ухудшиться ради красивого outcome? | `support_ticket_rate_7d` |

Outcome без input плохо помогает действовать. Input без outcome превращается в локальную
оптимизацию интерфейса. Outcome без guardrail провоцирует "улучшение" через ухудшение
пользовательского опыта, качества данных или монетизации.

### Метрика - это спецификация, а не название

Название `conversion` ничего не гарантирует. Для метрики нужны:

```text
metric_id
question
owner
role
grain
eligible_population
numerator
denominator
window
filters
dimensions
expected_direction
guardrails
known_failure_modes
source_tables
validation_checks
```

Например, `paywall_to_trial_conversion_7d` и `paywall_to_trial_conversion_session` могут
использовать одни и те же события, но иметь разные окна, grain и знаменатели. Их нельзя
сравнивать как одну метрику.

### Guardrail должен иметь направление риска

Для outcome обычно достаточно `up`, `down` или `neutral`. Для guardrail этого мало:

```text
support_ticket_rate_7d: up_is_bad
data_freshness_delay_minutes: up_is_bad
tracking_completeness: down_is_bad
```

Иначе команда увидит изменение guardrail, но не поймет, это риск или улучшение.

### Дерево не доказывает причинность

Дерево метрик показывает рабочую гипотезу: какой механизм связан с результатом и какие
риски нужно мониторить. Оно не доказывает, что paywall вызвал изменение activation.
Статистическая неопределенность будет в фазе 09, эксперименты - в фазе 10, причинные
предпосылки - в фазе 13.

## Соберите это

Откройте `code/main.py`. Минимальная ручная проверка дерева считает роли:

```python
def manual_role_counts(tree: dict) -> dict[str, int]:
    counts = {"outcome": 0, "input": 0, "guardrail": 0}
    for node in tree["nodes"]:
        counts[node["role"]] += 1
    return counts
```

Запустите:

```bash
uv run --locked python code/main.py
```

Вы увидите:

```json
{
  "manual_role_counts": {
    "outcome": 1,
    "input": 2,
    "guardrail": 2
  },
  "valid": true
}
```

Это еще не полноценная валидация, но первый важный шаг: дерево не может состоять только
из outcome-метрик.

### Шаг 1: сформулируйте решение

Не начинайте с "посчитаем retention". Запишите decision set:

```text
continue
rollback
investigate
run_experiment
```

Теперь каждая метрика обязана помогать выбрать один из этих вариантов или ограничивать
риск.

### Шаг 2: задайте outcome

Для задачи rollout outcome:

```text
activation_rate_7d
grain: user_id
eligible_population: registered non-test users with complete 7-day window
numerator: users with feature_value_seen within 7 days after account_created
denominator: registered non-test users in the cohort
window: 7 days after account_created
```

Обратите внимание на `complete 7-day window`. Если пользователь зарегистрировался вчера,
его нельзя честно использовать в 7-дневной activation rate.

### Шаг 3: добавьте input-метрики

Input-метрика должна быть механизмом, а не еще одним синонимом outcome:

```text
onboarding_completion_rate
paywall_to_trial_conversion_7d
```

Они отвечают на вопросы:

```text
Пользователь завершает onboarding?
Пользователь после paywall начинает trial?
```

### Шаг 4: добавьте guardrails

Для этой задачи риски:

```text
support_ticket_rate_7d: up_is_bad
subscription_cancel_rate_14d: up_is_bad
```

Если activation растет вместе с этими guardrails, рекомендация `continue` уже не
безопасна.

## Используйте это

Артефакт `outputs/metric_tree_validator.py` проверяет дерево и metric specs:

```bash
uv run --locked python outputs/metric_tree_validator.py \
  --tree outputs/metric_tree.json \
  --specs outputs/metric_specs.json \
  --output metric-tree-report.json
```

Успешный report содержит stable check ids:

```json
{
  "id": "metric_denominator_defined",
  "valid": true
}
```

CLI проверяет:

1. дерево содержит узлы и связи;
2. `metric_id` уникальны;
3. есть хотя бы один `outcome`, `input` и `guardrail`;
4. связи указывают на существующие разные метрики;
5. каждому узлу соответствует metric spec;
6. у каждой метрики есть denominator, source tables и validation checks;
7. role в дереве совпадает с role в spec;
8. guardrail имеет направление риска `up_is_bad` или `down_is_bad`;
9. ссылки на guardrails ведут именно на guardrail-метрики.

Для учебного просмотра failed report без ненулевого exit code:

```bash
uv run --locked python outputs/metric_tree_validator.py \
  --tree outputs/metric_tree.json \
  --specs broken-metric-specs.json \
  --allow-failures
```

## Сломайте это

Попробуйте испортить `outputs/metric_specs.json` по одному дефекту:

1. Очистите `denominator` у `activation_rate_7d` - должен упасть
   `metric_denominator_defined`.
2. Поменяйте `support_ticket_rate_7d.expected_direction` на `up` - должен упасть
   `metric_direction_declared`.
3. Удалите `source_tables` - должен упасть `metric_sources_declared`.
4. Переименуйте `activation_rate_7d` только в tree, но не в specs - должен упасть
   `metric_specs_match_tree`.
5. Добавьте edge на несуществующую метрику - должен упасть `metric_edges_resolve`.

Главная мысль: плохое дерево часто выглядит красиво в презентации. Машинная проверка
заставляет явно назвать недостающий знаменатель, окно, источник и риск.

## Проверьте это

Запустите behavioral tests:

```bash
uv run --locked python -m unittest discover -s tests -v
```

Тесты проверяют:

- валидный пример содержит 1 outcome, 2 input и 2 guardrail;
- дубликат `metric_id` отклоняется;
- дерево без guardrail-role отклоняется;
- edge на отсутствующую метрику отклоняется;
- метрика без denominator отклоняется;
- guardrail без направления риска отклоняется;
- пустые `source_tables` и `validation_checks` отклоняются;
- source tables из specs существуют в `../data/contract.json`;
- CLI пишет report и возвращает `1` для invalid specs.

Данные фазы лежат в `../data/`. Проверка tiny-профиля:

```bash
uv run --locked python ../data/generate_data.py --check
```

## Поставьте результат

Артефакт урока:

```text
outputs/metric_tree_validator.py
```

Он работает отдельно от текста урока:

```bash
uv run --locked python outputs/metric_tree_validator.py \
  --tree outputs/metric_tree.json \
  --specs outputs/metric_specs.json \
  --output metric-tree-report.json
```

Передавайте вместе с ним:

```text
outputs/metric_tree.json
outputs/metric_specs.json
metric-tree-report.json
```

В следующих уроках эти specs станут контрактом для событийной модели, активности,
воронок, retention, монетизации, сегментации и финальной рекомендации.

## Упражнения

1. Добавьте input-метрику `first_session_value_seen_rate` и свяжите ее с
   `activation_rate_7d`.
2. Добавьте guardrail `tracking_completeness_rate` с направлением `down_is_bad`.
3. Возьмите любую метрику из дерева и перепишите ее для grain `session_id`. Объясните,
   почему изменились population, numerator или denominator.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Outcome metric | Главная метрика, которую можно улучшать любой ценой | Целевой продуктовый результат, который должен быть защищен guardrails |
| Input metric | Любая метрика, которая коррелирует с outcome | Управляемый механизм, через который команда предполагает изменить outcome |
| Guardrail metric | Второстепенная метрика для dashboard | Ограничение риска, ухудшение которого может остановить rollout |
| Grain | Просто технический ключ таблицы | Единица наблюдения, на которой имеет смысл считать метрику |
| Denominator | Можно добавить потом | Часть определения метрики, без которой доля не имеет смысла |
| Window | Фильтр по датам | Временная граница, которая определяет eligibility и честность сравнения |

## Дополнительное чтение

- [Mixpanel: Create A Tracking Plan](https://docs.mixpanel.com/docs/tracking-best-practices/tracking-plan) - прочитайте раздел methodology: он связывает business goals, KPI, user flows, events и properties.
- [Mixpanel: Metric Tree](https://docs.mixpanel.com/docs/metric_tree) - посмотрите, как дерево используется как decision-making framework, а не как галерея метрик.
- [Google Analytics: Set up events](https://developers.google.com/analytics/devguides/collection/ga4/events) - обратите внимание на recommended и custom events, event name и parameters.
- [Mixpanel: Funnels overview](https://docs.mixpanel.com/docs/reports/funnels/funnels-overview) - прочитайте про conversion между событиями в заданном time window; это пригодится в `08/04`.
