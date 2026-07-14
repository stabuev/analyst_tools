# Проверки и независимая валидация

> Воспроизводимый баг остается багом. Clean-room rerun подтверждает повторяемость, а
> независимый shadow calculation проверяет правильность ключевого результата.

**Тип:** Case  
**Треки:** core, product, data, decision, ml, delivery  
**Пререквизиты:** `18-capstones/04-implementation`  
**Время:** ~420 минут  
**Результат:** independently verified package с clean-room rerun, shadow calculation,
negative fixtures, sensitivity и claim-evidence audit

## Цели обучения

После урока вы сможете:

- принять только checksum-verified `implementation_ready` package;
- зафиксировать verification plan до просмотра результатов проверки;
- повторить implementation в изолированном временном workspace и subprocess;
- сравнить каждый опубликованный output с clean-room output по SHA-256;
- независимо пересчитать score, ranking, denominator, capacity и acceptance gate;
- отделить повторяемость реализации от правильности аналитического результата;
- спроектировать negative fixtures, которые обязаны падать на конкретных gates;
- провести predeclared threshold/capacity sensitivity без изменения frozen решения;
- проверить claim не только по пути к файлу, но и по полям, limitation и shadow support;
- раскрыть skipped/xfail tests и не спрятать под ними обязательную проверку;
- перевести capstone state из `implementation_ready` только в `verification_ready`;
- передать package на peer review, не называя verification самим review.

## Проблема

После `18/04` проект выглядит убедительно:

- CLI завершается с кодом `0`;
- behavioral tests проходят;
- manifest содержит hashes;
- candidate metrics и decision сохранены;
- evidence ledger связывает claims с outputs;
- команда сборки документирована.

Но все эти доказательства создал тот же implementation layer. Он может последовательно и
воспроизводимо повторять одну ошибку:

- неверный denominator используется и в расчете, и во внутреннем тесте;
- stale input принят, потому что state gate проверен не полностью;
- `candidate_score` и «ручная» сверка вызывают одну функцию;
- output перезаписан, а manifest обновлен вместе с ним;
- evidence path существует, но заявленного поля в файле нет;
- `xfail` скрывает обязательный route-specific check;
- sensitivity выполнена только после того, как автор увидел удобный сценарий.

Поэтому утверждение

```text
implementation tests pass
```

не эквивалентно утверждению

```text
independent verification supports the published result
```

Reference implementation ранжирует `high_touch` первым, получает candidate value
`0.666667` при frozen threshold `0.766667` и сохраняет baseline. Verification должна
проверить этот неудобный вывод. Если verifier снижает threshold или использует тот же
расчет, он не проверяет проект, а повторяет предпочтение автора.

## Концепция

### Семь независимых доказательств

Verification package объединяет семь разных вопросов:

| Доказательство | Вопрос | Что не доказывает |
|---|---|---|
| Package integrity | Это тот же reviewed input? | Что формула правильна |
| Clean-room rerun | Код повторяет опубликованные outputs? | Что output содержательно верен |
| Shadow calculation | Независимая формула дает тот же результат? | Что метод решает бизнес-задачу |
| Negative fixtures | Защиты замечают известные дефекты? | Что покрыты все будущие ошибки |
| Sensitivity | От каких assumptions зависит решение? | Что можно поменять frozen gate |
| Claim audit | Evidence действительно поддерживает текст claim? | Что claim причинный без design |
| Test disclosure | Не спрятана ли обязательная проверка? | Что passing tests заменяют review |

Эти проверки нельзя схлопнуть в один зеленый флаг. Например:

```text
clean_room_match = true
shadow_pass = false
```

означает: реализация воспроизводима, но ключевой результат не подтвержден. Итоговый статус
должен быть `verification_block`.

### Независимость как свойство процесса

Полная организационная независимость требует другого человека. Локальный harness
проверяет техническую независимость:

- verification logic не импортирует implementation functions;
- implementation запускается отдельным subprocess;
- source CLI и `uv.lock` pinned hashes;
- inputs копируются в новый temporary repository;
- `HOME`, `TMPDIR`, `PYTHONHASHSEED`, `PYTHONPATH`, locale и timezone контролируются;
- output directory создается заново;
- verifier использует собственную реализацию shadow oracle;
- fixture mutations применяются только к временным копиям.

`--write-example` генерирует reference inputs отдельным subprocess. Этот вспомогательный
режим не является shadow calculation: после создания inputs verifier читает только
package boundary и запускает собственные проверки.

Clean room не обязательно означает Docker. Для небольшого standard-library CLI
изолированный temporary repository, новый process, минимальный environment и pinned
source/lock hashes дают проверяемую границу. Если проект зависит от system libraries,
services или native runtime, к этой границе добавляется container или другой declared
runtime image.

### Package integrity до содержательной проверки

Verifier принимает четыре независимых input:

```text
upstream implementation package
implementation runner source
upstream baseline package
verification spec
```

Он проверяет:

1. Все обязательные implementation outputs существуют.
2. SHA-256 и bytes совпадают с `implementation_manifest.json`.
3. Baseline manifest и acceptance gate совпадают с input hashes implementation.
4. Runner, verification harness и `uv.lock` совпадают с pinned source contract.
5. State имеет `current_stage=implementation` и `stage_status=implementation_ready`.
6. `verification_id`, `review_id` и `defense_id` еще не заполнены.
7. `open_blockers` пуст.

Checksum не заменяет semantic gate. Fixture
`stale_stage_with_rehashed_manifest` специально меняет state и честно пересчитывает hash.
Integrity проходит, но state gate блокирует package.

### Verification spec до запуска

`verification_spec.json` фиксирует:

- project, contract, baseline и implementation IDs;
- новый `verification_id`;
- route и variant;
- independence policy;
- hashes implementation runner, verification harness и lock file;
- route-specific controls;
- полный набор high-level checks;
- четыре negative fixtures и expected failing gates;
- пять sensitivity scenarios;
- required test IDs;
- пустые или объясненные `skipped`/`xfail` lists;
- isolated environment policy;
- одну reproducible command.

В spec запрещены observed result fields:

```text
candidate_value
candidate_pass
selected_method
observed_result
verification_pass
final_status
```

Иначе автор может сначала увидеть outcome, а затем назвать удобный набор проверок
«заранее запланированным».

### Clean-room rerun

Harness строит временную структуру:

```text
temporary-repo/
├── uv.lock
├── phases/18-capstones/04-implementation/outputs/
│   └── capstone_route_implementation.py
├── input/
│   ├── baseline-package/
│   └── implementation_spec.json
└── output/
    └── implementation-package/
```

Runner выполняется через текущий Python из locked environment. После запуска verifier:

- сравнивает десять manifest outputs по SHA-256;
- сравнивает весь regenerated implementation manifest;
- сохраняет return code и sanitized stdout payload;
- не сохраняет volatile absolute paths temporary directory;
- блокируется при timeout, non-zero exit или любом mismatch.

Reference clean-room rerun дает десять совпадений из десяти.

### Shadow calculation без implementation functions

Shadow oracle читает `baseline_metrics.csv`, frozen weights и immutable
`acceptance_gate.json`. Для каждого сегмента он заново считает:

```text
activation_gap = 1 - activation_rate

component(x_i) =
    0,                                     if max(x) = min(x)
    (x_i - min(x)) / (max(x) - min(x)),   otherwise

score = 0.6 * churn_component
      + 0.2 * activation_gap_component
      + 0.2 * support_load_component
```

Затем применяется отдельная сортировка:

```text
candidate_score descending
churn_rate descending
segment_id ascending
```

Для выбранного сегмента oracle независимо считает:

```text
captured_churned_users = 2
total_churned_users = 3
candidate_value = 2 / 3 = 0.666667
reviewed_users = 4
```

И применяет frozen gate:

```text
metric_pass = candidate_value + tolerance >= 0.766667
capacity_pass = reviewed_users <= 4
candidate_pass = metric_pass and capacity_pass
selected_method = baseline
```

`shadow_calculation.csv` содержит 22 атомарные сверки: components, score, rank,
selection, denominator, value, capacity, threshold, pass и final selection. Для numeric
fields сохраняются difference и tolerance; для categorical fields требуется exact match.

### Negative fixtures должны падать правильно

Reference suite содержит четыре predeclared fixtures:

| Fixture | Мутация | Ожидаемый failing gate |
|---|---|---|
| `tampered_output_checksum` | Добавляет byte в candidate metrics без обновления manifest | Package integrity |
| `stale_stage_with_rehashed_manifest` | Возвращает state в baseline и обновляет hash | State readiness |
| `changed_shadow_denominator` | Добавляет единицу к denominator только в oracle | Shadow calculation |
| `missing_evidence_field_with_rehashed_manifest` | Добавляет несуществующее evidence field и обновляет hash | Claim traceability |

Fixture считается прошедшей, только если:

```text
observed_check_id == expected_check_id
observed_check_valid == false
fixture_copy_removed == true
```

Просто получить любой exception недостаточно. Например, malformed CSV, который падает до
проверки denominator, не доказывает работу denominator gate.

### Sensitivity не меняет frozen решение

Reference scenarios:

| Scenario | Threshold | Capacity | Selection |
|---|---:|---:|---|
| Frozen gate | 0.766667 | 4 | baseline |
| Threshold - 0.1 | 0.666667 | 4 | candidate |
| Threshold + 0.1 | 0.866667 | 4 | baseline |
| Capacity - 1 | 0.766667 | 3 | baseline |
| Capacity + 1 | 0.766667 | 5 | baseline |

Снижение threshold ровно до observed candidate value меняет решение. Verifier сохраняет
frozen baseline и добавляет warning:

```text
candidate_conclusion_is_threshold_sensitive
```

Это полезный вывод: candidate не имеет запаса practical improvement. Но sensitivity не
дает права ретроспективно принять candidate.

### Claim-evidence traceability

Implementation ledger содержал три claims. Verification проверяет для каждой строки:

- `claim_id` уникален;
- `evidence_path` безопасен и существует;
- все `evidence_fields` реально присутствуют в JSON или CSV;
- limitation непустая;
- claim type не шире upstream boundary;
- независимый shadow поддерживает значение claim.

Поэтому существующий `candidate_decision.json` с отсутствующим полем уже не считается
достаточным evidence. И наоборот, поле существует, но расходится с shadow result, claim
также блокируется.

### Skipped и xfail являются частью результата

`test_results.json` хранит:

- все required verification test IDs;
- `passed`, `failed`, `skipped`, `xfail` counts;
- missing required tests;
- required tests, скрытые в skip/xfail;
- reason для каждого допустимого skip/xfail.

Обязательный `shadow_calculation`, помеченный `skip`, не превращает suite в зеленую. Он
блокирует verification даже с объяснением. Необязательный platform-specific test можно
пропустить только с явным reason и границей риска.

### Route-specific oracle

Общий package gate одинаков, но содержательные controls зависят от маршрута:

| Route / variant | Независимый фокус |
|---|---|
| Core analytics / standard | Grain, denominator, ranking, descriptive boundary |
| Product experiments / standard | Assignment/exposure, SRM, metric denominator, experiment claim |
| Data / standard | Keys/grain, lineage/freshness, full-vs-incremental equivalence |
| Decision science / causal | Estimand, effect recalculation, overlap/falsification, assumptions |
| Decision science / forecast | Origins/horizon, temporal leakage, forecast metric, scope |
| ML / baseline | Split/availability, prediction metric, threshold/capacity, predictive claim |
| ML / strong model | Holdout isolation, tuning trace, metric, predictive claim |
| Delivery / standard | Rebuild, freshness/state, public scan, upstream claim preservation |

Reference package исполняет core controls. Остальные profiles фиксируют обязательный
интерфейс для проектов соответствующего маршрута; они не превращают core formula в
универсальный oracle.

## Соберите это

### Шаг 1. Зафиксируйте verification spec

Сначала создайте deterministic reference inputs:

```bash
uv run --locked python \
  phases/18-capstones/05-verification/outputs/capstone_independent_verifier.py \
  --write-example /tmp/capstone-verification-input \
  --output-dir /tmp/capstone-verification-package \
  --fail-on-invalid
```

В production workflow `--write-example` не нужен. Передайте утвержденные paths явно:

```bash
uv run --locked python \
  phases/18-capstones/05-verification/outputs/capstone_independent_verifier.py \
  --upstream-implementation-package path/to/implementation-package \
  --implementation-runner \
  phases/18-capstones/04-implementation/outputs/capstone_route_implementation.py \
  --upstream-baseline-package path/to/baseline-package \
  --verification-spec path/to/verification_spec.json \
  --output-dir path/to/verification-package \
  --fail-on-invalid
```

CLI возвращает:

- `0` — package построен; с `--fail-on-invalid` все verification gates прошли;
- `1` — проверка выполнена, но есть verification blocker;
- `2` — отсутствуют inputs или они не читаются как contract.

### Шаг 2. Проверьте immutable boundary

Не начинайте shadow calculation, если:

- implementation manifest невалиден;
- source hash runner изменился;
- baseline gate отличается от принятого implementation;
- state уже содержит verification/review evidence;
- upstream package имеет blockers.

Иначе verifier будет производить точные числа для неутвержденной версии проекта.

### Шаг 3. Выполните clean-room rerun

Создайте новый temporary repository. Скопируйте только declared files, установите
контролируемый environment и выполните runner как subprocess. Сравнивайте outputs из
manifest, а не только exit code.

Не переносите в report абсолютные temporary paths: они делают downstream manifest
недетерминированным. Reference harness сохраняет только устойчивые поля stdout payload.

### Шаг 4. Напишите отдельный shadow oracle

Не импортируйте функцию `run_core_adapter`. Снова реализуйте:

1. Count/rate reconciliation.
2. Min-max components.
3. Weighted score.
4. Tie-breaking и ranking.
5. Selection capacity.
6. Captured numerator и total denominator.
7. Frozen threshold/tolerance comparison.

Oracle должен быть короче production path и использовать минимальный независимый набор
inputs. Если обе реализации разделяют сложный helper, независимость потеряна.

### Шаг 5. Спроектируйте failure fixtures

Для каждой важной защиты ответьте:

```text
Какой минимальный дефект обязан изменить status?
Какой именно check должен стать false?
Может ли более ранняя ошибка скрыть проверяемый gate?
Удаляется ли mutated copy после теста?
```

Минимум три fixtures обязательны. Reference package использует четыре, чтобы отдельно
проверить bytes, semantic state, analytical denominator и claim evidence.

### Шаг 6. Проведите sensitivity

Scenarios должны быть в spec до запуска. Всегда сохраняйте baseline scenario с точными
frozen values. Perturbations могут менять вывод; report обязан показать flip и не менять
официальную selection.

### Шаг 7. Проверьте claims и test disclosure

Для каждого claim свяжите:

```text
claim -> exact path -> exact fields -> limitation -> independent support
```

Затем сравните executed test IDs с required list и отдельно проверьте skip/xfail.

### Шаг 8. Выпустите verification package

Reference output содержит:

```text
verification-package/
├── verification_spec.json
├── verification_report.json
├── clean_room_rerun.json
├── shadow_calculation.csv
├── failure_fixture_results.csv
├── failure-fixtures/
│   ├── tampered_output_checksum.json
│   ├── stale_stage_with_rehashed_manifest.json
│   ├── changed_shadow_denominator.json
│   └── missing_evidence_field_with_rehashed_manifest.json
├── sensitivity_report.csv
├── claim_evidence_audit.csv
├── route_verification_report.json
├── test_results.json
├── capstone_state.json
└── verification_manifest.json
```

Manifest включает nested fixture files, source hashes, package flags и hashes всех
outputs. Два последовательных reference-run дают одинаковый verification manifest.

## Используйте это

Для пересборки committed reference outputs выполните:

```bash
uv run --locked python phases/18-capstones/05-verification/code/main.py
```

Ожидаемая summary:

```json
{
  "status": "verification_ready",
  "clean_room_match": true,
  "shadow_pass": true,
  "negative_fixtures": 4,
  "negative_fixtures_pass": true,
  "sensitivity_decision_flips": ["threshold_minus_practical_improvement"],
  "verified_claims": 3,
  "selected_method": "baseline"
}
```

Проверяйте files в таком порядке:

1. `verification_report.json` — blockers и summary.
2. `clean_room_rerun.json` — subprocess и output hash comparisons.
3. `shadow_calculation.csv` — атомарные независимые сверки.
4. `failure_fixture_results.csv` — expected и observed failing gates.
5. `sensitivity_report.csv` — frozen result и decision flips.
6. `claim_evidence_audit.csv` — независимая поддержка claims.
7. `test_results.json` — фактически выполненные tests и disclosure.
8. `verification_manifest.json` — final content-addressed package.

`verification_ready` не означает, что проект принят peer reviewer. Он означает, что
package достаточно проверяем и может войти в `18/06` без открытого verification blocker.

## Сломайте это

### Подмените output без manifest

Добавьте строку в `candidate_metrics.csv`. Integrity gate должен указать точный
`outputs.candidate_metrics.sha256` mismatch. Остальные проверки не должны маскировать
измененную версию как verified.

### Пересчитайте hash для stale state

Измените `current_stage` на `baseline`, затем обновите manifest hash. Integrity станет
green, но state readiness обязан блокировать package. Это демонстрирует границу checksum.

### Измените denominator только в shadow

Используйте `total_churned_users + 1`. Shadow candidate value станет `0.5` вместо
`0.666667`; clean-room по-прежнему пройдет. Итог verification должен быть blocked.

### Подмените опубликованное решение и обновите manifest

Замените selected segment на `self_serve` и обновите hash. Integrity пройдет, но
clean-room rerun не воспроизведет candidate decision и manifest.

### Добавьте несуществующее evidence field

Укажите `missing_field`, обновите ledger hash. Claim audit должен заблокировать конкретный
claim, даже если package integrity зеленый.

### Спрячьте shadow в skip

Добавьте required `shadow_calculation` в `test_disclosure.skipped` с reason. Disclosure
будет явным, но verification останется blocked: обязательную проверку нельзя заменить
объяснением.

### Расширьте claim

Измените descriptive claim type на causal или установите
`causal_effect_claimed=true`. Route claim boundary должна остановить package до peer
review.

## Проверьте это

Запустите behavioral suite урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/18-capstones/05-verification/tests -v
```

29 behavioral tests проверяют:

- successful transition в `verification_ready` без выбора candidate;
- полный CLI/help/write-example contract;
- implementation output и baseline gate tampering;
- rehashed stale state;
- IDs, route и variant alignment;
- independence, isolated environment и pinned source hashes;
- отсутствие observed result fields в predeclared spec;
- восемь route/variant verification profiles;
- drift adapter, claim boundary и route controls;
- byte-identical clean-room rerun без volatile paths;
- clean-room mismatch для rehashed fake published result;
- независимые components, ranking, denominator, tolerance и gate;
- changed-denominator fixture;
- четыре specific negative fixtures и запрет missing fixture;
- frozen sensitivity и threshold flip;
- exact evidence fields, limitations и shadow support;
- required skip/xfail disclosure;
- route-specific reference controls;
- state transition без review/defense IDs;
- nested manifest hashes и deterministic package;
- отсутствие upstream mutations;
- public aggregate boundary;
- CLI exit codes `0/1/2`.

Курс-уровневые проверки:

```bash
uv run --locked python scripts/validate_course.py
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

Verification stage готов к peer review, когда reviewer получает:

- exact immutable implementation и baseline packages;
- pinned implementation runner, verifier source и lock file;
- predeclared verification spec без observed result fields;
- isolated clean-room rerun с exact output comparisons;
- независимый shadow calculation ключевого результата;
- минимум три negative fixtures, падающие на ожидаемых gates;
- sensitivity с frozen scenario и явными flips;
- claim-evidence audit до exact fields и limitations;
- полный test inventory со skipped/xfail disclosure;
- route-specific controls;
- `capstone_state.json` со статусом `verification_ready`;
- SHA-256 manifest всех inputs, nested fixtures и outputs;
- flags `raw_sources_copied=false`, `upstream_inputs_mutated=false` и
  `fixture_mutations_persisted=false`.

Не исправляйте implementation внутри verification directory. Любое содержательное
исправление возвращает проект на затронутый upstream stage, создает новую versioned
реализацию и требует полного rerun verification.

## Упражнения

1. **Другой denominator.** Создайте fixture, где из total churn исключен один сегмент.
   Укажите exact expected shadow row и объясните, почему checksum этого не обнаружит.
2. **Passing candidate.** Постройте synthetic package, где candidate проходит metric и
   capacity. Сделайте claim audit generic: он должен подтвердить candidate без
   hardcoded method name.
3. **Route transfer.** Выберите свой маршрут и реализуйте четыре controls из его profile.
   Для каждого добавьте positive и negative behavioral test.
4. **Non-critical xfail.** Добавьте platform-specific test с явным xfail reason, который
   не входит в required list. Проверьте, что disclosure сохраняется, но package не
   блокируется.
5. **Reproducibility drift.** Внесите volatile timestamp или absolute temp path в
   clean-room report. Сравните manifests двух запусков и устраните источник drift.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Independent verification | Повторный запуск функции автора | Отдельный process, source contract и oracle ключевого результата |
| Clean-room rerun | Любой второй запуск | Запуск в новом declared workspace/environment без скрытого state |
| Shadow calculation | Еще один wrapper над implementation | Независимая минимальная реализация ключевой формулы |
| Package integrity | Доказательство правильности | Доказательство неизменности конкретной версии bytes |
| Negative fixture | Любая ошибка в тесте | Преднамеренная мутация с exact expected failing gate |
| Sensitivity | Поиск параметра, где результат удобен | Predeclared perturbations вокруг frozen reference decision |
| Decision flip | Причина поменять основной gate | Evidence зависимости вывода от assumption |
| Claim traceability | Существующий путь к файлу | Claim, exact fields, limitation, type и independent support |
| Skipped disclosure | Косметическая статистика | Проверка отсутствующего coverage и причины исключения |
| Verification ready | Проект прошел review | Независимые технические gates пройдены, package готов к review |

## Дополнительное чтение

- [pytest: temporary directories](https://docs.pytest.org/en/stable/how-to/tmp_path.html) - разберите уникальные temporary paths, retention и границы изоляции fixture; для destructive mutations используйте только test-owned directory.
- [pytest: skip and xfail](https://docs.pytest.org/en/stable/how-to/skipping.html) - изучите различия skip/xfail/strict xfail и спроектируйте disclosure, который не скрывает required gate.
- [uv: running commands](https://docs.astral.sh/uv/concepts/projects/run/) - сопоставьте project environment и locked execution с source/lock contract clean-room rerun.
- [W3C PROV Overview](https://www.w3.org/TR/prov-overview/) - свяжите implementation/verification entities, activities и agents с manifests, rerun и evidence lineage.
- [The Turing Way: reproducible research](https://book.the-turing-way.org/reproducible-research/reproducible-research/) - сравните reproducibility, replicability и reusable research components с семью verification evidence layers урока.
