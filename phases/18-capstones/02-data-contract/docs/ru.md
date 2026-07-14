# Контракт и аудит данных

> Данные готовы не тогда, когда файл открывается, а когда их происхождение, grain,
> временные границы и право использования выдерживают проверяемый контракт.

**Тип:** Case  
**Треки:** core, product, data, decision, ml, delivery  
**Пререквизиты:** `18-capstones/01-problem-selection`  
**Время:** ~360 минут

## Цели обучения

После урока вы сможете:

- продолжить passing `capstone_state.json`, не потеряв route и claim boundary;
- разделить dataset manifest, data contract и фактический audit;
- объявить grain, keys, schema, relationships и many-to-one cardinality до join;
- проверить source owner, origin, license, allowed uses и reproducibility command;
- зафиксировать `data_as_of`, freshness и complete observation windows;
- выбрать leakage/quality controls для конкретного capstone-маршрута;
- отделить restricted raw inputs от агрегированного public sample;
- передать следующему stage checksum inventory, lineage и статус `data_ready`.

## Проблема

После passing brief хочется сразу открыть notebook и посчитать первую метрику. Именно в
этой точке capstone чаще всего получает скрытый дефект, который обнаруживается слишком
поздно:

- `user_week` принимают за одну строку на пользователя, хотя grain равен
  `user_id x as_of_week`;
- join с тикетами размножает пользователей и меняет denominator;
- свежий по имени файл содержит обновления двухмесячной давности;
- feature рассчитан после prediction time;
- наблюдение еще не имеет полного outcome window;
- скачанный датасет технически читается, но его лицензия не разрешает portfolio release;
- в Git попадает row-level CSV с псевдонимизированными, но все еще restricted IDs.

Такие ошибки не лечатся более сложным методом. Более того, сложная модель или
интерактивная поставка способны скрыть их лучше простого расчета. Поэтому второй stage
капстоуна заканчивается до baseline и отвечает на вопрос: «какие именно данные разрешено
интерпретировать в рамках утвержденного brief?»

Reference case использует три детерминированных synthetic source:

| Source | Grain | Primary key | Роль |
|---|---|---|---|
| `users` | одна строка на пользователя | `user_id` | dimension и parent |
| `user_week` | пользователь на отчетную неделю | `user_id, as_of_week` | analysis population |
| `support_tickets` | один тикет | `ticket_id` | event source |

Все raw source объявлены `restricted`. В публикуемый пакет попадает только агрегат по
`as_of_week, segment_id` после minimum group size gate.

## Концепция

### Три разных доказательства

Названия часто смешивают, но у файлов разные обязанности.

| Слой | На какой вопрос отвечает | Что не доказывает |
|---|---|---|
| Dataset manifest | Какие конкретно байты были входом? | Корректность смысла и право публикации |
| Data contract | Как эти данные разрешено читать и использовать? | Что текущие файлы соответствуют обещанию |
| Data audit | Выполнен ли contract на текущих байтах? | Что будущий метод даст хороший результат |

Manifest фиксирует resource path, SHA-256, bytes, row count и порядок columns. Contract
фиксирует schema, grain, relationships, freshness, lineage и policy. Audit заново читает
файлы и сопоставляет обещание с наблюдением.

Если checksum совпал, доказана идентичность байтов. Не доказаны отсутствие leakage,
правильность типов, лицензия, privacy и пригодность для решения.

### Grain раньше join

Grain - это единица одной строки. Он задается ключами и проверяется на данных:

```python
grain_keys = ["user_id", "as_of_week"]
keys = [(row["user_id"], row["as_of_week"]) for row in user_week]

assert all(all(part for part in key) for key in keys)
assert len(keys) == len(set(keys))
```

Уникальность каждой таблицы еще не делает join безопасным. Для связи
`user_week -> users` contract требует:

```text
from: user_week.user_id
to:   users.user_id
cardinality: many_to_one
orphan_policy: block
```

Parent key должен быть уникален, а каждый child key должен найти parent. Если справа две
строки на пользователя, это уже не many-to-one. Если child не нашел parent, silent drop
при inner join меняет population.

### Schema включает policy

Имя и тип поля недостаточны. В reference contract каждое поле получает
`classification`:

- `public`: разрешено в объявленном публичном представлении;
- `aggregated`: вычислено на допустимом агрегированном grain;
- `restricted`: доступно для локального анализа, но не для public package;
- `secret`: не должно попадать ни в public sample, ни в диагностический output.

`user_id` остается restricted, даже если выглядит как `u1`. Замена имени на стабильный ID
не превращает строку в анонимную. Поэтому public sample строится не удалением пары
columns, а отдельной агрегацией с minimum group size.

### Source policy до вычислений

Для каждого source нужны:

- `owner`: кто отвечает за смысл и доступность;
- `origin`: откуда появились данные;
- `license`: на каких условиях они используются;
- `allowed_uses`: разрешены ли course, internal analysis или public portfolio;
- `publication_class`: что допустимо выпускать;
- `reproducibility.command`: как воспроизвести разрешенный input;
- `known_defects`: какие ограничения уже известны и как контролируются.

Открытый URL не равен открытой лицензии. Доступ к таблице не равен разрешению публиковать
ее строки. Synthetic fixture тоже требует явного origin, чтобы reviewer не принял его за
реальные evidence.

### Время как часть schema

`data_as_of` задает момент, относительно которого проверяется доступность. Все timestamps
timezone-aware и нормализованы в UTC.

```python
latest_source_update <= data_as_of
data_as_of - latest_source_update <= max_age_days
```

Первое условие блокирует future information. Второе блокирует stale input. Отдельный
`window_complete` не позволяет включить пользователя, для которого семидневный outcome
еще не успел проявиться.

Freshness и observation completeness не взаимозаменяемы. Файл может быть обновлен сегодня,
но содержать незрелые outcomes. И наоборот, полное историческое окно может быть слишком
старым для текущего решения.

### Route-specific controls

Общие schema gates одинаковы, но утечка зависит от обещания проекта.

| Route | Обязательные data controls |
|---|---|
| Core analytics | complete windows, только descriptive/associational claim |
| Product experiments | randomization unit, assignment/exposure integrity, SRM check |
| Data/analytics engineering | complete lineage, freshness SLA, grain tests |
| Decision science causal | pre-treatment covariates, treatment/outcome timing, post-treatment exclusion |
| Decision science forecast | chronological cutoff, known-at-origin features, complete time index |
| ML baseline/strong | prediction time, label horizon, split roles, feature availability |
| Delivery product | verified upstream evidence, visible freshness, no hidden recompute |

Список намеренно минимален для route. Core capstone не обязан притворяться ML-проектом,
но и не вправе сделать causal claim только потому, что нашел сильную корреляцию. Delivery
не пересчитывает скрыто upstream evidence внутри интерфейса. Forecast и ML не используют
поля, появившиеся после момента прогноза.

### Stage state как handoff

Passing package обновляет состояние из `18/01`:

```json
{
  "current_stage": "data_contract",
  "stage_status": "data_ready",
  "data_contract_id": "weekly-retention-data-v1",
  "baseline_id": null,
  "open_blockers": []
}
```

`baseline_id` остается `null`: data gate не подменяет следующий результат. Upstream
warning про reference profile переносится дальше, чтобы synthetic evidence не стало
портфолио-доказательством из-за очередного успешного шага.

## Соберите это

Standalone artifact находится в
[`../outputs/capstone_data_contract_auditor.py`](../outputs/capstone_data_contract_auditor.py).

### 1. Продолжите проверенный brief

Аудитор принимает не произвольный `project_id`, а package предыдущего урока. Он проверяет:

- наличие `capstone_state.json`, `capstone_brief_audit.json`, `brief_manifest.json`;
- passing status `ready_for_data_contract`;
- совпадение checksum состояния с upstream manifest;
- согласованность `project_id` между state и audit.

Если brief изменился после утверждения, data contract нужно пересмотреть. Новый checksum
нельзя молча подставить в старый package.

### 2. Объявите таблицы

Минимальная запись source выглядит так:

```json
{
  "source_id": "user_week",
  "path": "user_week.csv",
  "owner": "analytics-platform",
  "origin": "deterministic_synthetic_generator",
  "license": "CC0-1.0",
  "allowed_uses": ["course", "portfolio_public_aggregate"],
  "publication_class": "restricted",
  "grain": {
    "keys": ["user_id", "as_of_week"],
    "duplicate_policy": "forbid"
  }
}
```

Затем добавьте ordered schema, freshness и reproducibility. Путь должен быть относительным
и не выходить из `source_root` через `..`.

### 3. Снимите manifest с фактических bytes

```python
rows, columns = read_csv(path)
resource = {
    "path": "user_week.csv",
    "sha256": sha256_file(path),
    "bytes": path.stat().st_size,
    "rows": len(rows),
    "columns": columns,
}
```

Manifest создается после получения разрешенного input, но до аналитических преобразований.
При обновлении source нужно выпустить новую согласованную версию manifest, а не исправить
число строк после failed gate.

### 4. Проверьте contract против rows

Reference auditor выполняет десять checks:

1. upstream brief ready и untampered;
2. contract complete и связан с тем же project;
3. source policy и known defects объявлены;
4. manifest совпадает с файлами;
5. schema, types, nullability и grain выполняются;
6. relationships имеют ожидаемую cardinality и ноль orphans;
7. freshness и observation windows корректны;
8. route-specific controls присутствуют и ссылаются на evidence;
9. public policy исключает restricted/secret;
10. aggregate sample проходит minimum group size.

Status `data_ready` появляется только при всех десяти passing checks.

### 5. Выпустите только разрешенное представление

Raw files используются для локального аудита, но не копируются. Public sample содержит:

```text
as_of_week,segment_id,users,activated_users,activation_rate,
support_ticket_count,churned_users
```

В нем нет `user_id`, `ticket_id`, точных signup timestamps и row-level outcomes. Package
manifest явно фиксирует `raw_sources_copied: false`.

## Используйте это

Создайте детерминированный upstream brief, raw fixture, contract и manifest, затем соберите
data package:

```bash
uv run --locked python \
  phases/18-capstones/02-data-contract/outputs/capstone_data_contract_auditor.py \
  --write-example /tmp/capstone-data-input \
  --output-dir /tmp/capstone-data-package \
  --fail-on-invalid
```

CLI вернет краткий machine-readable итог:

```json
{
  "status": "data_ready",
  "valid": true,
  "source_count": 3,
  "public_sample_rows": 2,
  "blocking_errors": []
}
```

Пакет имеет следующий состав:

```text
/tmp/capstone-data-package/
├── data_contract.json
├── dataset_manifest.json
├── data_audit.json
├── lineage_report.csv
├── checksum_inventory.csv
├── public_data_sample.csv
├── capstone_state.json
└── data_package_manifest.json
```

Для собственного проекта передайте входы явно:

```bash
uv run --locked python \
  phases/18-capstones/02-data-contract/outputs/capstone_data_contract_auditor.py \
  --upstream-brief-package path/to/brief-package \
  --data-contract path/to/data_contract.json \
  --dataset-manifest path/to/dataset_manifest.json \
  --source-root path/to/restricted-source-data \
  --output-dir path/to/data-package \
  --fail-on-invalid
```

Exit code `0` означает passing audit. Код `1` означает содержательный
`data_contract_block`, а `2` - missing/invalid input или другую системную ошибку.

## Сломайте это

### Измените source после manifest

Добавьте строку в `users.csv`, не меняя `dataset_manifest.json`. Gate
`dataset_manifest_matches_source_bytes` покажет расхождения `sha256`, `bytes` и `rows`.

Это не повод автоматически переписать manifest. Сначала выясните, откуда появилась новая
строка и должна ли она войти в analysis population.

### Размножьте parent key

Скопируйте `users.user_id`. Получите сразу два сигнала:

- grain source перестал быть уникальным;
- many-to-one relationship больше не имеет уникальной to-side.

Оба важны: первый локализует дефект таблицы, второй объясняет риск для join.

### Создайте orphan

Укажите в `user_week.user_id` значение, которого нет в `users`. Нельзя просто перейти на
inner join: строка исчезнет, а вместе с ней изменится заявленная population.

### Подложите future feature

Поставьте `source_updated_at` позже `data_as_of`. Аудитор отметит `future availability`.
Для forecast/ML этого недостаточно: feature availability также должна быть определена
относительно каждого prediction origin, а не только общего package timestamp.

### Попробуйте опубликовать restricted rows

Добавьте `restricted` в `allowed_classifications` или поднимите row-level file в output.
Первое блокирует policy gate. Второе нарушает package boundary даже при passing checksum.

### Сделайте группы слишком маленькими

Установите `minimum_group_size: 5`, когда в каждом сегменте только четыре пользователя.
Агрегатор не выпустит строки и вернет blocker
`public_sample_meets_aggregate_grain_and_group_size`.

## Проверьте это

Запустите behavioral tests урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/18-capstones/02-data-contract/tests -v
```

Тесты проверяют happy path и failure modes:

- tampered upstream state;
- project mismatch и неполную source policy;
- manifest drift;
- type/nullability, duplicate и null keys;
- wrong cardinality и orphans;
- stale/future timestamps и incomplete windows;
- все восемь route/variant profiles;
- causal overclaim в core route;
- privacy policy и minimum group size;
- checksum/lineage outputs, state handoff и CLI exit codes;
- отсутствие raw sources в package.

Дополнительно выполните курс-уровневые проверки:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Stage готов к baseline, когда reviewer получает:

- passing upstream brief package;
- versioned `data_contract.json` и byte-exact `dataset_manifest.json`;
- `data_audit.json` без blocking errors;
- `lineage_report.csv` и `checksum_inventory.csv`;
- только policy-compliant `public_data_sample.csv`;
- `capstone_state.json` со статусом `data_ready`;
- `data_package_manifest.json` с hashes каждого output и
  `raw_sources_copied: false`.

Не включайте restricted raw inputs в portfolio repository. В handoff укажите, где и на
каких условиях reviewer может получить разрешенные данные либо как воспроизвести
synthetic fallback. Следующий урок строит baseline только поверх этого зафиксированного
состояния.

## Упражнения

1. **Core analytics.** Добавьте второй `as_of_week`, объявите новый `data_as_of` и
   докажите, что public sample не смешивает недели и включает только complete windows.
2. **Выбранный маршрут.** Замените core route policy на свой profile. Для каждого control
   укажите evidence field и создайте failing test на пропуск одного обязательного gate.
3. **Privacy.** Добавьте поле `email_domain` с классификацией `restricted`. Убедитесь, что
   оно проверяется в raw schema, но не появляется в public sample и package inventory.
4. **Lineage.** Добавьте source `billing_events`, объявите grain и many-to-one связь с
   `users`, затем сломайте parent key и сравните grain error с relationship error.
5. **Версионирование.** Измените source осознанно, выпустите manifest v2 и опишите, какие
   downstream evidence из будущих stages должны быть инвалидированы.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Dataset manifest | Список имен файлов | Версионированное описание конкретных resources, их bytes, hashes, rows и columns |
| Data contract | Только schema типов | Проверяемое соглашение о grain, keys, semantics, time, lineage, quality и usage policy |
| Grain | Размер таблицы | Единица одной строки, выраженная ключами и duplicate policy |
| Cardinality | Вид SQL join | Ожидаемое число соответствий между ключами двух sources |
| Orphan | Строка с null | Child key, для которого отсутствует допустимый parent key |
| `data_as_of` | Время запуска скрипта | Зафиксированная временная граница доступной информации package |
| Observation window | Любой фильтр по дате | Период, который должен полностью завершиться до использования outcome |
| Feature availability | Поле есть в таблице | Значение известно в момент конкретного prediction/decision origin |
| Classification | Тип данных Python | Policy-класс поля: public, aggregated, restricted или secret |
| Public sample | Первые N строк | Отдельное разрешенное представление на безопасном grain с group-size gate |

## Дополнительное чтение

- [Frictionless Data Package](https://specs.frictionlessdata.io/data-package/) - изучите структуру package и resources; сравните descriptor с `dataset_manifest.json` урока.
- [Frictionless Data Resource](https://specs.frictionlessdata.io/data-resource/) - посмотрите, как path, hashes, bytes, schema и primary keys превращают файл в описанный resource.
- [Datasheets for Datasets](https://arxiv.org/abs/1803.09010) - первичный источник о документировании происхождения, состава, intended uses и ограничений датасета.
- [The Aqua Book](https://www.gov.uk/government/publications/the-aqua-book-guidance-on-producing-quality-analysis-for-government) - прочитайте главы о proportionate quality assurance, audit trail и роли независимой проверки аналитики.
