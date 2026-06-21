# Протокол решения и коммуникация

> Хорошее experiment decision - это не одно число, а воспроизводимый пакет: evidence,
> gates, решение, причины и checksums.

**Тип:** Case  
**Треки:** Product  
**Пререквизиты:** 10/10 - Сегменты и неоднородные эффекты  
**Время:** ~105 минут  
**Результат:** собирает experiment-decision package: protocol, assignment audit, A/A/SRM,
power, primary effect, bootstrap/CUPED checks, multiple-testing policy, peeking audit,
segment report, guardrails, decision и checksum manifest.

## Цели обучения

- Собрать все evidence artifacts эксперимента в одну воспроизводимую папку.
- Проверить assignment-to-exposure integrity перед интерпретацией эффекта.
- Применить заранее заданный decision policy к raw, bootstrap, CUPED, multiple-testing,
  peeking и segment evidence.
- Сформулировать `launch`, `hold`, `rollback`, `iterate` или `inconclusive` без
  hindsight-подбора.
- Зафиксировать SHA-256 checksums для проверки неизменности evidence.

## Проблема

В реальной работе эксперимент часто заканчивается не анализом, а спором:

```text
primary не прошел, но revenue вырос
сегмент выглядит хорошо
interim dashboard был зеленый
guardrails вроде не страшные
```

Если у команды нет decision package, каждый участник разговора выбирает свой любимый
артефакт. Product смотрит на segment lift, аналитик - на p-value, инженер - на telemetry,
а руководитель хочет короткое решение.

Финальный урок фазы превращает набор артефактов `10/01`-`10/10` в один пакет:

```text
outputs/experiment-decision-package/
```

В нем есть не только `decision_summary.json`, но и evidence, markdown report и checksum
manifest. Это делает решение проверяемым.

## Концепция

### Decision package отделяет evidence от интерпретации

Evidence - это входы:

```text
experiment_protocol.json
assignments.csv
randomization_health_report.json
power_plan.json
effect_results.csv
bootstrap_intervals.json
variance_reduction_report.json
multiple_testing_report.json
sequential_monitoring_report.json
heterogeneity_report.json
```

Decision - это применение заранее заданной политики к этим входам:

```text
launch_requires all required gates
rollback_when any guardrail breached
hold_when primary/sample/gates block launch
iterate_when signal exists but product follow-up is needed
```

Эти слои нельзя смешивать. Если decision не нравится, надо менять следующий experiment
protocol, а не переписывать текущую интерпретацию.

### Assignment audit - первый integrity gate

Перед статистикой нужно проверить механику:

```text
one assignment unit -> one variant
every eligible assignment has exposure
exposure variant equals assignment variant
no duplicate exposures
no extra exposures
```

В нашем tiny-наборе assignment audit проходит:

```text
assigned_units = 5
exposed_units = 5
variant_counts = control: 3, treatment: 2
```

Если exposure variant не совпадает с assignment variant, downstream effect analysis уже
нельзя считать надежным.

### Launch требует всех gates

В `decision_policy.json` launch требует:

```text
assignment_audit_valid
randomization_health_ready
power_plan_ready
effect_analysis_ready
multiple_testing_allows_launch
peeking_ready_for_decision
heterogeneity_report_valid
no_guardrail_breach
```

В этом эксперименте часть базовой механики здорова:

```text
assignment_audit_valid = true
randomization_health_ready = true
power_plan_ready = true
```

Но decision gates не очищены:

```text
effect_analysis_ready = false
multiple_testing_allows_launch = false
peeking_ready_for_decision = false
```

Итог:

```text
decision = hold
launch_allowed = false
rollback_required = false
```

### Hold - это тоже решение

`hold` не означает "мы ничего не поняли". В этом кейсе причины конкретны:

```text
missed_primary_direction
guardrails_not_cleared
observed_sample_below_power_plan
assumption_warnings_present
multiple_testing_does_not_allow_launch
unplanned decision looks
segment_cells_below_minimum_size
interaction_checks_insufficient_overlap
```

Коммуникация должна быть короткой:

```text
Do not launch from this experiment; keep segment findings as exploratory inputs
for a new pre-registered iteration.
```

### Checksums делают пакет проверяемым

`checksums.json` хранит SHA-256 digest для каждого файла evidence package. Если после
решения кто-то изменит `effect_results.csv` или `heterogeneity_report.json`, digest
перестанет совпадать.

Это не защита от всех проблем, но хорошая рабочая гарантия:

```text
вот ровно те файлы, по которым было принято решение
```

## Соберите это

Откройте `outputs/experiment_decision_packager.py`. Артефакт делает шесть шагов.

### Шаг 1: объявите required evidence

В `EVIDENCE_FILES` перечислены источники:

```text
id
category
source
package_path
required_for
```

Например:

```text
08_multiple_testing_report.json -> multiple_testing gate
09_sequential_monitoring_report.json -> peeking gate
10_heterogeneity_report.json -> segment diagnostics
```

Если source file отсутствует, package не собирается.

### Шаг 2: скопируйте evidence в package

Packager копирует файлы в:

```text
outputs/experiment-decision-package/evidence/
```

и строит `evidence_index.json`. Индекс объясняет, зачем нужен каждый файл и какой у него
SHA-256 digest.

### Шаг 3: постройте assignment audit

`assignment_audit()` сверяет `assignments.csv` и `exposures.csv`:

```text
missing exposure units
extra exposure units
variant mismatches
duplicate exposures
```

Результат записывается как generated evidence:

```text
evidence/02_assignment_audit.json
```

### Шаг 4: извлеките decision facts

Из предыдущих артефактов packager берет:

```text
raw primary lift = -0.666667
raw primary p-value = 0.931981
bootstrap CI = [-1.0, 0.0]
CUPED adjusted lift = -0.416667
guardrails = watch
multiple_testing_launch_allowed = false
peeking_ready_for_decision = false
segment_findings_not_launch_gates = true
```

Эти facts не редактируются руками внутри финального отчета.

### Шаг 5: примените decision policy

Policy строит `launch_requirements` и `decision_reasons`. В этом кейсе:

```text
launch_allowed = false
rollback_required = false
decision = hold
```

Почему не rollback? Потому что guardrails в статусе `watch`, но нет подтвержденного
breach. Почему не iterate? Потому что primary missed direction и sample/readiness gates
не позволяют трактовать эксперимент как успешный сигнал для итерации rollout.

### Шаг 6: выпустите checksums

Packager считает SHA-256 по файлам package:

```text
decision_summary.json
decision_report.md
evidence_index.json
evidence/*
```

Затем пишет:

```text
checksums.json
manifest.json
```

`manifest.json` дополнительно хранит digest самого `checksums.json`.

## Используйте это

Соберите package из папки урока:

```bash
uv run --locked python outputs/experiment_decision_packager.py \
  --phase-root .. \
  --decision-policy outputs/decision_policy.json \
  --output-dir outputs/experiment-decision-package
```

Откройте главный итог:

```text
outputs/experiment-decision-package/decision_summary.json
```

Короткий человекочитаемый вариант:

```text
outputs/experiment-decision-package/decision_report.md
```

Минимальный пример:

```bash
uv run --locked python code/main.py
```

Он собирает package во временную папку и печатает только decision summary.

## Сломайте это

Попробуйте три поломки.

1. Удалите один required evidence file.
   Packager должен остановиться с `FileNotFoundError`, а не выпустить неполный package.
2. В test copy поменяйте variant у exposure.
   `assignment_audit` должен найти `exposure_variant_matches_assignment`.
3. Уберите `hold` из `allowed_decisions`.
   Packager должен отклонить выбранное решение, потому что policy не разрешает такой
   decision label.

Эти поломки проверяют не статистику, а операционную надежность: можно ли доверять
упаковке результата.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s tests -v
```

Тесты проверяют:

```text
committed package matches rebuilt package
decision = hold
launch_allowed = false
rollback_required = false
primary raw/bootstrap/CUPED facts propagated
all required evidence items are present
assignment audit catches variant mismatch
checksums match package files
CLI writes complete package
```

Если checksum test падает, значит изменился один из файлов evidence или итоговый отчет
нужно пересобрать.

## Поставьте результат

Именованный артефакт:

```text
outputs/experiment_decision_packager.py
```

Итоговый package:

```text
outputs/experiment-decision-package/
├── decision_summary.json
├── decision_report.md
├── evidence_index.json
├── checksums.json
├── manifest.json
└── evidence/
```

Это финальный deliverable фазы 10. Его можно приложить к продуктовой задаче или PRD как
проверяемое объяснение:

```text
мы не запускаем, потому что конкретные gates не очищены
```

## Упражнения

1. Добавьте в `decision_report.md` отдельный раздел `Open Questions` и заполните его из
   `decision_reasons`.
2. Расширьте `decision_policy.json` так, чтобы `inconclusive` выбирался, когда primary
   CI включает MDE и sample plan выполнен.
3. Добавьте CSV `stakeholder_summary.csv` с колонками `audience`, `message`,
   `evidence_link`, чтобы один package давал разные форматы для product, analytics и
   engineering.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Decision package | Красивый финальный отчет | Папка evidence, summary, report, index и checksums |
| Launch gate | Любой положительный сигнал | Заранее заданное условие, которое должно быть выполнено для запуска |
| Hold | Отсутствие решения | Осознанное решение не запускать по конкретным blockers |
| Rollback | Любой неуспешный тест | Решение при подтвержденном вреде или guardrail breach |
| Checksum manifest | Техническая мелочь | Контроль неизменности файлов, на которых основано решение |

## Дополнительное чтение

- [Python hashlib](https://docs.python.org/3/library/hashlib.html) - официальный API для SHA-256 checksums, используемых в package manifest.
- [Python json](https://docs.python.org/3/library/json.html) - официальный формат сериализации `decision_summary.json`, `evidence_index.json` и manifest.
- [Подглядывание и последовательный анализ](../../09-peeking/docs/ru.md) - повторите, почему unplanned looks остаются decision blockers в финальном package.
- [Сегменты и неоднородные эффекты](../../10-heterogeneous-effects/docs/ru.md) - повторите, почему segment findings входят в evidence, но не становятся standalone launch gate.
