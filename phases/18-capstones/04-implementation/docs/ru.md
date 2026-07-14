# Реализация проекта

> Успешно выполненный candidate еще не является выбранным решением. Реализация должна
> пройти frozen gate, оставить evidence trail и честно сохранить baseline, если
> практического улучшения нет.

**Тип:** Build  
**Треки:** core, product, data, decision, ml, delivery  
**Пререквизиты:** `18-capstones/03-baseline`  
**Время:** ~720 минут

## Цели обучения

После урока вы сможете:

- продолжить checksum-verified baseline package без изменения upstream contracts;
- отделить route-specific analytical adapter от общего package/gate слоя;
- зафиксировать config, weights, cutoffs, seeds и candidate policy до запуска;
- реализовать deterministic candidate на разрешенном input grain;
- сравнить candidate с immutable acceptance metric, tolerance и capacity;
- сохранить baseline, если candidate не дает practical improvement;
- связать каждый публичный claim с точным output, fields и limitation;
- выпустить ordered run trace и locked reproducible command;
- проверить dependency/runtime/config/hour complexity budget;
- передать `implementation_ready` package на независимую verification.

## Проблема

Три первых stage уже ответили на вопросы, которые реализация не имеет права менять:

- `18/01`: кто принимает решение, какие действия допустимы и какой claim разрешен;
- `18/02`: какие данные, grain, временные границы и права использования зафиксированы;
- `18/03`: какой простой comparator полезен и какой practical threshold должен пройти
  более сложный candidate.

Но именно во время реализации эти решения особенно легко размыть:

- неудобный baseline заменяют более слабым;
- threshold снижают после просмотра candidate result;
- в adapter добавляют row-level source, которого нет в approved package;
- weight или cutoff меняют в notebook без следа;
- test/final result используется для выбора config;
- сложность выходит за budget, но оправдывается уже потраченным временем;
- отчет заявляет больше, чем разрешает claim boundary;
- package нельзя пересобрать одной documented command.

Reference core implementation использует тот же агрегированный input, что baseline, и
строит weighted segment score:

```text
score = 0.6 * normalized(churn_rate)
      + 0.2 * normalized(1 - activation_rate)
      + 0.2 * normalized(support_tickets_per_user)
```

На двух reference-сегментах `high_touch` получает `1.0`, а `self_serve` - `0.0`.
Candidate снова выбирает `high_touch` и получает captured recall `0.666667` при frozen
threshold `0.766667`.

Candidate выполнился корректно, но practical gate не прошел. Поэтому итог реализации:

```text
candidate_pass = false
selected_method = baseline
stage_status = implementation_ready
```

Это не противоречие. Pipeline correctness и candidate usefulness являются разными
проверками.

## Концепция

### Upstream contracts immutable

Implementation package читает:

- `capstone_state.json`;
- `baseline_report.json`;
- `baseline_metrics.csv`;
- `baseline_decision.json`;
- `acceptance_gate.json`;
- `complexity_budget.json`;
- `baseline_manifest.json`.

Каждый файл сверяется с SHA-256 из manifest. Если threshold, baseline metrics или state
изменились, implementation блокируется. Нельзя «просто обновить checksum»: изменение
upstream evidence означает новую версию затронутого stage и повторный downstream run.

Immutable не означает, что файл физически невозможно записать. Это означает, что любая
запись делает package отличным от утвержденной версии и видимо инвалидирует run.

### Adapter отделен от package layer

Общий слой одинаков для шести маршрутов:

```text
validate upstream hashes
  -> load frozen implementation spec
  -> execute route adapter
  -> compare frozen acceptance/capacity gate
  -> link claim evidence
  -> write trace, state and manifest
```

Route adapter отвечает только за domain logic:

| Route | Adapter kind | Главная граница |
|---|---|---|
| Core analytics | `weighted_segment_priority` | observed priority, не intervention effect |
| Product experiments | `randomized_assignment_analysis` | design/SRM gates до experimental claim |
| Data/analytics engineering | `contracted_mart_build` | correctness/lineage/freshness, не user impact |
| Decision causal | `identified_estimand_workflow` | estimand и identification assumptions |
| Decision forecast | `rolling_origin_forecast_workflow` | declared origin/horizon |
| ML baseline | `locked_prediction_pipeline` | predictive priority, не treatment effect |
| ML strong model | `tracked_tuning_and_prediction_pipeline` | tuning только внутри predeclared roles |
| Delivery product | `verified_evidence_delivery_workflow` | usability без усиления upstream claim |

Замена adapter не должна переписывать state machine, manifest или evidence ledger. Общий
слой не должен знать внутренности CatBoost, DiD, dbt или Streamlit.

### Config замораживается до run

Reference `implementation_spec.json` содержит:

```json
{
  "score_weights": {
    "churn_rate": 0.6,
    "activation_gap": 0.2,
    "support_load": 0.2
  },
  "normalization": "min_max_zero_when_constant",
  "ranking_direction": "maximize",
  "max_selected_segments": 1,
  "seed_policy": "not_required_deterministic_adapter"
}
```

Weights неотрицательны и суммируются в единицу. Tie-breakers заданы. Число adjustable
parameters не превышает complexity budget. Поля `candidate_value`, `candidate_pass`,
`selected_method`, `test_score` и `final_score` в predeclared spec запрещены.

Для stochastic route нужен реальный seed policy. Для deterministic arithmetic adapter
seed не придумывается: `not_required_deterministic_adapter` точнее, чем декоративный
`seed=42`.

### Normalization является частью метода

Разные компоненты нельзя складывать в исходных шкалах. Reference adapter использует
min-max внутри approved aggregate sample:

```python
normalized = (value - minimum) / (maximum - minimum)
```

Если все значения одинаковы, component становится нулем. Это predeclared поведение
избегает division by zero и не создает искусственного различия.

Normalization policy входит в config и evidence. Изменение ее после результата является
изменением candidate, а не технической правкой.

### Candidate execution и candidate selection различаются

Adapter сначала производит inspectable output:

| Segment | Churn component | Activation-gap component | Support component | Score |
|---|---:|---:|---:|---:|
| `high_touch` | 1.0 | 1.0 | 1.0 | 1.0 |
| `self_serve` | 0.0 | 0.0 | 0.0 | 0.0 |

Затем общий gate берет только frozen acceptance contract:

```python
metric_pass = candidate_value + tolerance >= candidate_threshold
capacity_pass = reviewed_users <= max_capacity
candidate_pass = metric_pass and capacity_pass
```

В reference case:

```text
0.666667 + 0.000001 < 0.766667
4 <= 4
```

Capacity проходит, metric не проходит. `candidate_rejected_keep_baseline` сохраняется как
результат. Implementation остается ready к verification, потому что отсутствие прироста
не является дефектом pipeline.

### Complexity budget проверяется повторно

Baseline разрешил:

- максимум одну новую runtime dependency;
- runtime не более 30 секунд;
- максимум восемь config parameters;
- максимум 12 часов implementation work.

Reference adapter использует только стандартную библиотеку, семь adjustable parameters и
оценку восемь часов. Runtime ограничен behavioral test timeout, а не выдуманным
детерминированным числом в report.

Нельзя записать `runtime = 0.01`, если wall-clock measurement не выполнялся. Честнее
зафиксировать limit и способ будущей проверки.

### Evidence ledger ограничивает claims

Каждый claim получает:

```text
claim_id
claim_text
claim_type
evidence_path
evidence_fields
limitation
status
```

Reference ledger связывает три утверждения:

1. `high_touch` стоит первым в predeclared weighted ranking;
2. candidate не проходит frozen practical threshold;
3. retain-baseline stop rule оставляет baseline выбранным методом.

Все claim types равны upstream `descriptive`. Claim `weighted score доказывает эффект
manual review` был бы causal overclaim и блокировал package.

Ссылка `см. репозиторий` недостаточна. Reviewer должен знать конкретный файл и fields,
которые подтверждают утверждение.

### Run trace не заменяет verification

`run_trace.csv` фиксирует последовательность:

```text
validate_upstream
load_frozen_config
execute_route_adapter
compare_acceptance_gate
link_evidence
package_outputs
```

Trace доказывает заявленный порядок внутренних events. Он еще не доказывает clean-room
reproducibility, независимый shadow calculation или negative fixtures. Это обязанности
следующего урока.

### Одна команда является частью результата

Spec содержит относительную locked command:

```bash
uv run --locked python \
  phases/18-capstones/04-implementation/outputs/capstone_route_implementation.py \
  --upstream-baseline-package path/to/baseline-package \
  --implementation-spec path/to/implementation_spec.json \
  --output-dir path/to/implementation-package \
  --fail-on-invalid
```

Machine-local `/Users/...` path, скрытый current working directory input или ручной шаг
между командами нарушают contract.

## Соберите это

Standalone artifact находится в
[`../outputs/capstone_route_implementation.py`](../outputs/capstone_route_implementation.py).

### 1. Сверьте baseline package

Проверьте status, identifiers, immutable hashes и два специальных флага:

```json
{
  "raw_sources_copied": false,
  "candidate_results_observed": false
}
```

Baseline acceptance должен иметь `candidate_value: null` и `candidate_pass: null`.

### 2. Опишите adapter

Минимальный adapter contract:

```json
{
  "adapter_id": "core-weighted-segment-priority-v1",
  "adapter_kind": "weighted_segment_priority",
  "input_path": "baseline_metrics.csv",
  "output_grain": ["as_of_week", "segment_id"],
  "primary_output": "candidate_decision.json",
  "claim_boundary": "descriptive_observed_priority_not_intervention_effect"
}
```

Adapter ID версионирует конкретную реализацию. Kind определяет интерфейс маршрута.

### 3. Перепроверьте input

Даже checksum-verified CSV проверяется на exact columns, unique grain, numeric bounds и
`churned_users / users == churn_rate`. Hash доказывает идентичность, schema check -
пригодность для adapter.

### 4. Выполните candidate

Route function получает только normalized parsed metrics и frozen config. Она возвращает:

- candidate rows;
- candidate decision;
- behavioral check результата.

Она не пишет state и manifest. Это сохраняет adapter тестируемым отдельно от filesystem.

### 5. Примените frozen gate

Gate возвращает как candidate status, так и selected method. Candidate failure без
ошибок contract становится warning `candidate_did_not_clear_practical_threshold`, а не
blocker.

### 6. Соберите evidence package

Общий слой пишет outputs, затем hashes, state и manifest. `implementation_id` появляется
только здесь; `verification_id` остается `null`.

## Используйте это

Создайте всю reference chain и implementation package:

```bash
uv run --locked python \
  phases/18-capstones/04-implementation/outputs/capstone_route_implementation.py \
  --write-example /tmp/capstone-implementation-input \
  --output-dir /tmp/capstone-implementation-package \
  --fail-on-invalid
```

CLI вернет:

```json
{
  "status": "implementation_ready",
  "valid": true,
  "selected_segments": ["high_touch"],
  "candidate_value": 0.666667,
  "candidate_threshold": 0.766667,
  "candidate_pass": false,
  "selected_method": "baseline"
}
```

Для собственного проекта:

```bash
uv run --locked python \
  phases/18-capstones/04-implementation/outputs/capstone_route_implementation.py \
  --upstream-baseline-package path/to/baseline-package \
  --implementation-spec path/to/implementation_spec.json \
  --output-dir path/to/implementation-package \
  --fail-on-invalid
```

Package содержит:

```text
implementation-package/
├── implementation_spec.json
├── implementation_report.json
├── implementation_config.json
├── route_adapter_report.json
├── candidate_metrics.csv
├── candidate_decision.json
├── candidate_acceptance.json
├── evidence_ledger.csv
├── run_trace.csv
├── capstone_state.json
└── implementation_manifest.json
```

Exit code `0` означает `implementation_ready`, даже если честно выбран baseline. Код `1`
означает contract blocker, а `2` - missing/invalid input.

## Сломайте это

### Измените acceptance threshold

Поставьте `0.60` вместо `0.766667`. Candidate станет победителем, но checksum upstream
gate изменится раньше вычисления. Это не tuning, а подмена baseline contract.

### Добавьте observed result в spec

Запишите `candidate_value` или `selected_method` в `candidate_policy`. Predeclaration gate
найдет future-result fields и заблокирует run.

### Сделайте weights удобными результату

Поменяйте weights после просмотра candidate. Даже если сумма остается единицей, новый
spec получает другой checksum и является другим run. Без новой версии сравнивать его со
старым evidence нельзя.

### Нарушьте aggregate grain

Добавьте duplicate segment-week row. Upstream hash можно согласованно обновить только
новой baseline version, но adapter все равно отклонит duplicate grain.

### Подмените churn rate

Укажите `0.1` при `2 / 4`. Adapter input reconciliation блокирует scoring до min-max.

### Превысьте capacity

Candidate может охватить всех churned users, выбрав восемь пользователей, но при capacity
четыре это другая задача. Metric pass не компенсирует capacity failure.

### Усильте claim

Замените `descriptive` на `causal` в evidence ledger. Score не идентифицирует эффект
outreach, поэтому claim выходит за upstream boundary.

### Сломайте reproducible command

Уберите `--locked`, output path или `--fail-on-invalid`, либо добавьте `/Users/me/...`.
Команда перестанет быть переносимым build contract.

## Проверьте это

Запустите behavioral tests:

```bash
uv run --locked python -m unittest discover \
  -s phases/18-capstones/04-implementation/tests -v
```

Тесты покрывают:

- honest candidate rejection при valid implementation;
- upstream state и acceptance tampering;
- IDs, route и adapter contract;
- восемь route/variant adapter profiles;
- weights, parameter count и future-result peeking;
- aggregate schema, grain и rate reconciliation;
- deterministic normalized components и ranking;
- metric/capacity acceptance для pass и failure;
- complexity/environment budget;
- evidence paths, fields, limitations и claim boundary;
- locked relative command;
- public aggregate boundary;
- state transition, trace order и manifest hashes;
- CLI exit codes и отсутствие input mutation.

Курс-уровневые проверки:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Implementation stage готов к независимой verification, когда reviewer получает:

- immutable baseline package и matching implementation IDs;
- versioned route adapter и frozen config;
- inspectable candidate metrics/decision;
- exact comparison с frozen acceptance и capacity;
- explicit `selected_method`, включая честное сохранение baseline;
- evidence ledger для каждого public claim;
- locked environment metadata и relative rebuild command;
- ordered run trace;
- `capstone_state.json` со статусом `implementation_ready` и пустым `verification_id`;
- SHA-256 manifest с `raw_sources_copied: false` и
  `upstream_inputs_mutated: false`.

Не называйте этот package независимо проверенным. Следующий stage выполнит clean-room
rerun, shadow calculation, negative fixtures, sensitivity checks и claim-evidence audit.

## Упражнения

1. **Candidate pass.** Создайте synthetic aggregate fixture, где predeclared adapter
   достигает threshold при той же capacity. Проверьте `selected_method=candidate` без
   изменения acceptance gate.
2. **Constant component.** Сделайте support load одинаковым у всех сегментов. Докажите,
   что component становится нулем и division by zero не возникает.
3. **Выбранный маршрут.** Реализуйте adapter своего route, сохранив общий package API.
   Добавьте минимум три route-specific behavioral tests.
4. **Evidence.** Добавьте четвертый claim и точную limitation. Затем намеренно укажите
   несуществующий output и убедитесь, что ledger gate блокирует package.
5. **Config versioning.** Создайте второй predeclared weight profile как отдельную версию,
   не перезаписывая первую. Сравните manifests и объясните, какой run имеет право войти в
   verification.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Immutable upstream | Файл только для чтения ОС | Versioned input, изменение которого инвалидирует downstream checksum |
| Route adapter | Универсальный метод для всех проектов | Изолированный domain workflow с общим package interface |
| Frozen config | Config после выбора лучшего run | Parameters, cutoffs и policy, зафиксированные до candidate result |
| Candidate execution | Candidate выбран | Workflow выполнился и создал проверяемые outputs |
| Candidate acceptance | Код завершился без ошибки | Metric и capacity прошли заранее утвержденный gate |
| Selected method | Самый сложный candidate | Candidate при passing gate, иначе сохраненный baseline |
| Evidence ledger | Список файлов | Связь claim с точным evidence, fields, type и limitation |
| Run trace | Полный audit/verification | Упорядоченный след внутренних events одного run |
| Reproducible command | Команда из истории shell | Documented locked relative command для полного package build |
| Implementation ready | Результат доказан независимо | Package собран и готов к следующей независимой verification |

## Дополнительное чтение

- [uv: running commands](https://docs.astral.sh/uv/concepts/projects/run/) - изучите locked project execution и отличие воспроизводимой команды от запуска в случайном environment.
- [W3C PROV Overview](https://www.w3.org/TR/prov-overview/) - сопоставьте entities, activities и agents с inputs, run trace и evidence ledger урока.
- [The Turing Way: reproducible research](https://book.the-turing-way.org/reproducible-research/reproducible-research/) - разберите, какие данные, код, environment и инструкции нужны другому человеку для rerun.
- [MLflow Tracking](https://mlflow.org/docs/latest/ml/tracking/) - для ML-route сравните tracking parameters/metrics/artifacts с immutable stage manifest; tracking server не заменяет claim gates.
