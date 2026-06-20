# Событийная модель продукта

> Событие полезно только тогда, когда оно заранее связано с вопросом, метрикой и
> проверяемым контрактом.

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 08/01 - Дерево метрик  
**Время:** ~75 минут  
**Результат:** проектирует tracking plan для продуктовых событий, связывает события с
metric specs и проверяет event names, versions, required properties, identity fields,
дубликаты и late arrivals.

## Цели обучения

- Отличать продуктовый tracking plan от списка "всего, что можно отправить".
- Проектировать event name, version, trigger, owner, identity policy и properties.
- Связывать события с metric specs из дерева метрик.
- Проверять событийный лог на неизвестные события, версии, свойства, identity, дубликаты
  и late arrivals.
- Понимать, какие дефекты событий ломают activity, funnel, retention и monetization.

## Проблема

В `08/01` команда зафиксировала дерево:

```text
activation_rate_7d
├── onboarding_completion_rate
├── paywall_to_trial_conversion_7d
├── guardrail: support_ticket_rate_7d
└── guardrail: subscription_cancel_rate_14d
```

Теперь хочется посчитать метрики. Но таблица `events` может быть обманчивой:

```text
event_name=paywall_seen
event_version=2
properties_json={}
user_id=""
received_at < occurred_at
```

Если аналитик не проверит это до расчета, воронка paywall -> trial может стать красивой
и неверной. Неизвестное имя события выпадет из числителя, новая версия сломает обязательное
свойство `variant`, пустой `user_id` разрушит user-level метрику, а повторная доставка
одного `event_id` раздует активность.

Нужен tracking plan - машинно читаемый договор между продуктом, разработкой и аналитикой:
какие события существуют, когда они отправляются, какие свойства обязательны и какие
метрики они обслуживают.

## Концепция

### Tracking plan начинается с метрик

Плохой tracking plan начинается так:

```text
Что можем трекать?
```

Хороший начинается так:

```text
Какой продуктовый вопрос и какие metric specs это событие поддерживает?
```

В этом уроке `outputs/tracking_plan.json` связан с
`../01-metric-tree/outputs/metric_specs.json`. Например:

| Событие | Зачем нужно |
|---|---|
| `account_created` | стартовая точка activation и support guardrail |
| `onboarding_started` | знаменатель `onboarding_completion_rate` |
| `onboarding_completed` | числитель `onboarding_completion_rate` |
| `paywall_viewed` | старт conversion window для trial |
| `trial_started` | числитель `paywall_to_trial_conversion_7d` |
| `support_ticket_created` | сигнал риска для `support_ticket_rate_7d` |

### Событие - это контракт

Минимальная спецификация события:

```text
event_name
version
owner
description
trigger
identity_policy
required_properties
optional_properties
allowed_platforms
app_version_policy
used_by_metrics
source
```

`event_name` отвечает на вопрос "что произошло". `trigger` фиксирует, когда именно
отправлять событие. `required_properties` задают контекст, без которого событие нельзя
использовать. `identity_policy` говорит, нужен ли стабильный `user_id` или до регистрации
достаточно `anonymous_id`.

### Version drift лучше ловить до расчета

Переименование `paywall_viewed` в `paywall_seen` кажется мелочью. Для метрики это другой
контракт. То же самое с `event_version`: если версия `2` изменила обязательные свойства,
старый расчет не имеет права молча принять ее как версию `1`.

### `occurred_at` и `received_at` отвечают на разные вопросы

`occurred_at` - когда действие случилось в продукте. `received_at` - когда событие
доехало до аналитического хранилища. Для дневного среза late arrivals важны не меньше,
чем сами значения метрики: если событие пришло через два дня, вчерашний отчет мог быть
неполным.

## Соберите это

Откройте `code/main.py`. Минимальная ручная проверка сначала считает события по именам:

```python
def manual_event_name_counts(events_path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with events_path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            name = row["event_name"]
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))
```

Запустите:

```bash
uv run --locked python code/main.py
```

Вы увидите summary:

```json
{
  "validator_summary": {
    "events": 41,
    "tracking_events": 12,
    "metric_specs": 5
  },
  "valid": true
}
```

Ручной count полезен как sanity check, но он не отвечает на главный вопрос: можно ли
использовать эти события для метрик.

### Шаг 1: перечислите события как действия

Не называйте событие по экрану или имени компонента:

```text
Bad: paywall_modal_v2
Good: paywall_viewed
```

Событие должно означать действие или факт, а `properties_json` должен хранить контекст:

```json
{"variant": "new"}
```

### Шаг 2: зафиксируйте trigger

`account_created` лучше отправлять с backend после создания пользователя, а не с клиента
после клика по кнопке. Иначе failed registration попадет в denominator как созданный
аккаунт.

### Шаг 3: задайте identity policy

До регистрации можно жить с `anonymous_id`. После регистрации user-level метрики требуют
стабильный `user_id`:

```text
signup_started: anonymous_or_user
account_created: known_user
feature_value_seen: known_user
```

### Шаг 4: свяжите события с metric specs

Для `activation_rate_7d` нужны минимум:

```text
account_created
feature_value_seen
```

Для `paywall_to_trial_conversion_7d`:

```text
paywall_viewed
trial_started
```

Эта связь записана в `used_by_metrics`. Если событие ссылается на несуществующую метрику,
валидатор отклонит tracking plan.

## Используйте это

Артефакт урока:

```text
outputs/event_model_validator.py
```

Запуск из папки урока:

```bash
uv run --locked python outputs/event_model_validator.py \
  --events ../data/tiny/events.csv \
  --tracking-plan outputs/tracking_plan.json \
  --metric-specs ../01-metric-tree/outputs/metric_specs.json \
  --output event-model-report.json
```

Успешный report содержит stable check ids:

```json
{
  "id": "event_names_known",
  "valid": true
}
```

CLI проверяет:

1. в логе есть обязательные колонки событий;
2. пары `event_name` / `event_version` уникальны в tracking plan;
3. event names записаны в `lower_snake_case`;
4. каждый `event_id` заполнен и уникален;
5. каждое событие из лога известно tracking plan;
6. версия события существует для данного имени;
7. `properties_json` валиден и содержит обязательные свойства;
8. identity fields соответствуют `identity_policy`;
9. `occurred_at` и `received_at` timezone-aware;
10. `received_at >= occurred_at`;
11. late arrivals не выходят за политику `max_late_minutes`;
12. mobile-события имеют `app_version`;
13. `used_by_metrics` ссылается на существующие metric specs.

Для учебного просмотра failed report без ненулевого exit code:

```bash
uv run --locked python outputs/event_model_validator.py \
  --events broken-events.csv \
  --tracking-plan outputs/tracking_plan.json \
  --metric-specs ../01-metric-tree/outputs/metric_specs.json \
  --allow-failures
```

## Сломайте это

Испортите копию `../data/tiny/events.csv` по одному дефекту:

1. Поменяйте `paywall_viewed` на `paywall_seen` - должен упасть `event_names_known`.
2. Поставьте `event_version=99` - должен упасть `event_versions_known`.
3. Удалите `method` из `account_created.properties_json` - должен упасть
   `required_properties_present`.
4. Очистите `user_id` у `feature_value_seen` - должен упасть
   `identity_policy_satisfied`.
5. Скопируйте один `event_id` в другую строку - должен упасть `event_ids_unique`.
6. Сделайте `received_at` раньше `occurred_at` - должен упасть
   `received_after_occurred`.
7. Для iOS или Android события очистите `app_version` - должен упасть
   `mobile_app_version_present`.

Главная мысль: событийный дефект часто выглядит как маленькая техническая ошибка, но в
продуктовой метрике он меняет числитель, знаменатель или eligibility.

## Проверьте это

Запустите behavioral tests:

```bash
uv run --locked python -m unittest discover -s tests -v
```

Тесты проверяют:

- валидный tiny-log проходит tracking plan и связан с пятью metric specs;
- дубликат `event_id` отклоняется;
- неизвестный `event_name` отклоняется;
- неизвестная версия известного события отклоняется;
- отсутствие обязательного свойства в `properties_json` отклоняется;
- невалидный JSON свойств отклоняется;
- событие с policy `known_user` требует `user_id`;
- `received_at` раньше `occurred_at` отклоняется;
- late arrival сверх политики отклоняется;
- mobile-событие без `app_version` отклоняется;
- ссылка tracking plan на отсутствующую метрику отклоняется;
- CLI пишет report и возвращает `1` для invalid log.

Проверка tiny-профиля данных фазы:

```bash
uv run --locked python ../data/generate_data.py --check
```

## Поставьте результат

Передавайте вместе:

```text
outputs/event_model_validator.py
outputs/tracking_plan.json
event-model-report.json
```

Минимальная команда поставки:

```bash
uv run --locked python outputs/event_model_validator.py \
  --events ../data/tiny/events.csv \
  --tracking-plan outputs/tracking_plan.json \
  --metric-specs ../01-metric-tree/outputs/metric_specs.json \
  --output event-model-report.json
```

В следующих уроках этот tracking plan будет защищать расчеты активности, воронок, когорт,
retention, монетизации и guardrails. Если отчет событийной модели красный, считать
продуктовые метрики рано.

## Упражнения

1. Добавьте в tracking plan новую версию `paywall_viewed` с обязательным свойством
   `placement`. Объясните, почему старый расчет не должен молча принимать эту версию.
2. Добавьте проверку, что server-события не приходят с пустым `user_id`.
3. Создайте копию tiny-log с поздним событием `trial_started` и опишите, какую метрику
   это исказит сильнее всего.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Tracking plan | Таблица для разработчиков, которую можно заполнить после релиза | Живой контракт событий, свойств, владельцев, версий, триггеров и связанных метрик |
| Event name | Любая строка, которую удобно отправить из кода | Стабильное имя действия или факта в продукте |
| Event version | Необязательная техническая деталь | Граница совместимости контракта события |
| Required property | Поле, которое можно восстановить потом | Контекст, без которого событие нельзя честно использовать для заданной метрики |
| Identity policy | Просто наличие `user_id` | Правило, какие идентификаторы допустимы для события до и после регистрации |
| Late arrival | Редкая инфраструктурная проблема | Событие, которое произошло раньше, но доехало после отчетного среза и меняет исторический расчет |

## Дополнительное чтение

- [Mixpanel: Create A Tracking Plan](https://docs.mixpanel.com/docs/tracking-best-practices/tracking-plan) - прочитайте methodology: business goals и KPI сначала связываются с user flows, а потом переводятся в events/properties.
- [Mixpanel: Events & Properties](https://docs.mixpanel.com/docs/data-structure/events-and-properties) - обратите внимание на Event Name, Timestamp, Distinct ID и properties как минимальную модель события.
- [Google Analytics: Set up events](https://developers.google.com/analytics/devguides/collection/ga4/events) - посмотрите различие автоматически собираемых, recommended и custom events, а также роль event parameters.
- [Google Analytics: Set up event parameters](https://developers.google.com/analytics/devguides/collection/ga4/event-parameters) - используйте как ориентир для отделения имени события от контекста в properties.
