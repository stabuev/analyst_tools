# Единица рандомизации

> Causal comparison начинается с вопроса: кого именно мы случайно назначаем в вариант и может ли этот unit остаться в нем стабильно.

**Тип:** Build  
**Треки:** Product  
**Пререквизиты:** 10/01 - Гипотеза и целевая метрика  
**Время:** ~90 минут  
**Результат:** выбирает randomization unit и analysis unit, строит стабильное назначение
вариантов по hash bucket, проверяет one-unit-one-variant, eligibility, exposure timing,
balance и риск interference.

## Цели обучения

- Отличать assignment, exposure и outcome в экспериментальной таблице.
- Выбирать randomization unit и analysis unit до запуска анализа.
- Строить воспроизводимое назначение вариантов через hash bucket, salt и allocation.
- Проверять one-unit-one-variant, eligible population и стабильность bucket.
- Находить exposure timing errors, duplicated exposures и interference risk.

## Проблема

В `10/01` команда подписочного сервиса зафиксировала protocol: Android non-test users
должны увидеть control или treatment paywall, а решение будет приниматься по
`activation_rate_7d` и guardrails. Но protocol еще не отвечает на практический вопрос:

```text
Какая строка получает вариант и как доказать, что повторный запуск назначит ее так же?
```

Плохая экспериментальная таблица обычно ломается не в t-test, а раньше:

```text
один user_id получил два варианта
test user попал в treatment
exposure записался до assignment
пользователь увидел treatment, а в assignments стоит control
один household разделился между control и treatment
```

Если эти ошибки дошли до расчета эффекта, p-value уже отвечает не на исходный
эксперимент, а на смесь логов, дубликатов и поздних событий. В этом уроке вы строите
локальный assignment engine и audit report, который блокирует такие дефекты до анализа
метрик.

## Концепция

### Assignment, exposure и outcome - разные события

Assignment - это обещание платформы: конкретный randomization unit получает конкретный
вариант.

Exposure - это факт, что пользователь действительно увидел событие влияния, например
`paywall_viewed`.

Outcome - это результат в analysis window, например activation за семь дней после
exposure.

Правильная временная цепочка выглядит так:

```text
eligible user -> deterministic assignment -> exposure event -> metric window -> outcome
```

Если exposure появляется раньше assignment или вариант exposure не совпадает с assigned
variant, экспериментальная интерпретация ломается до статистики.

### Randomization unit отвечает на вопрос "кого назначаем"

В этом уроке protocol объявляет:

```text
randomization_unit = user_id
analysis_unit = user_id
```

Это простейший случай: назначаем пользователя и считаем метрику на пользователя. В
реальной работе unit может быть `anonymous_id`, `device_id`, `household_id`, organization
или гео-регион. Выбор unit меняет дизайн:

| Выбор unit | Что защищает | Новый риск |
|---|---|---|
| `user_id` | стабильность после логина, простой user-level outcome | несколько устройств одного человека могут видеть разный опыт до логина |
| `device_id` | стабильность anonymous traffic | один пользователь на двух устройствах может попасть в разные варианты |
| `household_id` | снижает interference внутри семьи или shared account | меньше независимых units и ниже мощность |

Выбор нельзя менять после результата. Это часть pre-registered design, как primary metric
и decision rule.

### Stable hash делает assignment воспроизводимым

В уроке используется детерминированный bucket:

```text
bucket = sha256(salt + experiment_id + assignment_unit_id) % bucket_count
```

Для 50/50 allocation buckets `[0, 5000)` дают control, buckets `[5000, 10000)` дают
treatment. Salt изолирует эксперименты друг от друга: один и тот же user_id не обязан
получать один и тот же вариант во всех будущих тестах.

Hash assignment не заменяет мониторинг качества. На маленьком наборе 3/2 split нормален,
но в production нужно отдельно проверять SRM, telemetry loss и covariate balance. Это
будет темой `10/03`.

### Interference - это риск влияния между units

Эксперимент предполагает, что outcome одного unit не меняется из-за варианта другого
unit. Если два пользователя делят устройство, household или shared account, treatment
одного может изменить поведение второго. В этом уроке audit проверяет, что shared
`household_id` и `device_id` не оказались одновременно в разных вариантах.

Это не доказывает отсутствие interference. Это ранний alarm: выбранный unit может быть
слишком мелким для продукта.

## Соберите это

Откройте `outputs/assignment_engine.py`. Минимальная ручная часть engine состоит из трех
операций: eligible filter, stable bucket и variant mapping.

### Шаг 1: возьмите eligibility из protocol

Protocol `10/01` объявляет eligible population:

```json
[
  {"field": "platform", "operator": "==", "value": "android"},
  {"field": "is_test_user", "operator": "==", "value": false}
]
```

Engine применяет эти фильтры к `../data/tiny/users.csv`. В baseline назначение получают
только `U001`-`U005`; `U006` остается web user, `U007` - iOS user, `U999` - test user.

### Шаг 2: посчитайте bucket

Ключ bucket строится из salt, experiment_id и assignment_unit_id:

```python
def hash_bucket(experiment_id, unit_id, spec):
    digest = hashlib.sha256(f"{spec['salt']}:{experiment_id}:{unit_id}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % int(spec["bucket_count"])
```

Для committed tiny fixture результат стабилен:

```text
U001 -> 0870 -> control
U002 -> 9916 -> treatment
U003 -> 4643 -> control
U004 -> 2880 -> control
U005 -> 9142 -> treatment
```

### Шаг 3: сопоставьте bucket с allocation

Traffic allocation берется из protocol:

```json
{
  "control": 0.5,
  "treatment": 0.5
}
```

Engine сортирует `variant_id`, накапливает доли и выбирает вариант по bucket boundary. В
fixture получается 3 control и 2 treatment. Для tiny-набора это не SRM; это ожидаемая
дискретность маленькой выборки.

### Шаг 4: постройте exposure records

Exposure строится не из assignment, а из первого `paywall_viewed` в `events.csv`:

```text
assignment_unit_id + assigned variant + first paywall_viewed event
```

Если у assigned user нет exposure event, он остается assigned but not exposed. Если
exposure есть, audit проверит, что:

- exposure_id уникален;
- variant_id совпадает с assignment;
- `exposed_at >= assigned_at`;
- `received_at >= exposed_at`;
- exposure попал в experiment window.

## Используйте это

Запустите демонстрационный пример из корня репозитория:

```bash
uv run --locked python phases/10-experiments/02-randomization-unit/code/main.py
```

Фрагмент результата:

```json
{
  "assignment_unit": "user_id",
  "analysis_unit": "user_id",
  "assigned_units": 5,
  "variant_counts": {
    "control": 3,
    "treatment": 2
  },
  "audit_valid": true
}
```

Артефакт урока можно запускать как CLI из корня урока:

```bash
uv run --locked python outputs/assignment_engine.py \
  --users ../data/tiny/users.csv \
  --events ../data/tiny/events.csv \
  --protocol ../01-hypothesis-and-metric/outputs/experiment_protocol.json \
  --spec outputs/randomization_spec.json \
  --write-assignments /tmp/phase10-assignments.csv \
  --write-exposures /tmp/phase10-exposures.csv \
  --output /tmp/phase10-assignment-audit.json
```

CLI печатает JSON audit report. Если audit invalid, команда возвращает non-zero exit code.
Для учебного расследования можно добавить `--allow-failures`, чтобы сохранить report, но
для production gate failures должны блокировать дальнейший анализ.

## Сломайте это

Попробуйте мысленно или в тесте внести по одному дефекту:

1. Продублировать строку `U001` в `assignments.csv`.
2. Удалить assignment для eligible user `U005`.
3. Добавить assignment для test user `U999`.
4. Поменять bucket `U001` или variant `U002`.
5. Поставить `exposed_at` раньше `assigned_at`.
6. Поставить `received_at` раньше `exposed_at`.
7. Назначить двум пользователям с одним `household_id` разные варианты.

Каждый дефект должен падать отдельной проверкой. Это важно: хороший audit report не
просто говорит "invalid", а показывает, какой invariant нарушен и на каком sample.

## Проверьте это

Поведенческие тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/10-experiments/02-randomization-unit/tests -v
```

Они проверяют:

- generated assignments совпадают с committed fixture после CSV serialization;
- eligible population ограничена Android non-test users;
- stable hash ловит изменение bucket или variant;
- duplicate/missing/extra assignments блокируются;
- exposure variant и timestamp order проверяются;
- exposure без assignment блокируется;
- shared interference unit не split across variants;
- CLI пишет assignments, exposures и audit report;
- invalid fixture дает non-zero exit code.

## Поставьте результат

Именованный артефакт:

```text
outputs/assignment_engine.py
outputs/randomization_spec.json
../data/tiny/assignments.csv
../data/tiny/exposures.csv
```

`randomization_spec.json` фиксирует то, что должно быть неизменным при повторном запуске:
assignment unit, analysis unit, hash method, salt, bucket count, assigned_at,
balance tolerance, eligibility и interference columns.

`assignment_engine.py` можно переиспользовать в следующих уроках как upstream gate:
`10/03` добавит A/A, SRM и randomization health checks поверх этих assignment/exposure
fixtures.

## Упражнения

1. Измените `balance_tolerance` на `0.05` и объясните, почему tiny fixture теперь может
   выглядеть подозрительно, хотя hash assignment корректен.
2. Добавьте в `users.csv` второго пользователя с тем же `device_id`, пересчитайте
   assignment и проверьте, когда сработает `interference_units_not_split`.
3. Добавьте третий вариант с allocation `0.1` в protocol и spec, затем обновите тесты
   stable bucket так, чтобы они проверяли новые boundaries.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Randomization unit | "То же самое, что строка результата" | Entity, которую случайно назначают в вариант: user, device, household, org или другой unit |
| Analysis unit | "Всегда совпадает с randomization unit" | Entity, на которой считается outcome; может отличаться, но тогда нужны cluster-aware методы |
| Assignment | "Пользователь увидел treatment" | Стабильное назначение unit в вариант до outcome |
| Exposure | "Любая активность пользователя" | Факт, что пользователь реально увидел событие влияния варианта |
| Stable hash | "Достаточная гарантия валидного эксперимента" | Воспроизводимый routing mechanism; качество назначения все равно нужно аудировать |
| Interference | "Шум, который усреднится" | Нарушение предположения, что treatment одного unit не меняет outcome другого |

## Дополнительное чтение

- [Python `hashlib`](https://docs.python.org/3/library/hashlib.html) — посмотрите API SHA-256 и устройство hash objects для воспроизводимого bucket assignment.
- [Ensure A/B Test Quality at Scale with Automated Randomization Validation and Sample Ratio Mismatch Detection](https://arxiv.org/abs/2208.07766) — primary source о randomization validation и SRM detection; особенно полезен перед уроком `10/03`.
- [Trustworthy Experimentation Under Telemetry Loss](https://arxiv.org/abs/1903.12470) — primary source о том, как telemetry loss и late-arriving events ломают доверие к assignment/exposure logs.
- [Trustworthy Online Controlled Experiments](https://www.cambridge.org/core/books/trustworthy-online-controlled-experiments/DBF1CE91407ADC3B090D5A43DEDE57B7) — книга Kohavi, Tang и Xu; читайте главы про unit of diversion, interference и experiment pitfalls.
