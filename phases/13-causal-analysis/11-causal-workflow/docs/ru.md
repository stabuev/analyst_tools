# Causal workflow и границы автоматизации

> Автоматизация ускоряет causal workflow, но не имеет права придумывать graph,
> identification и силу вывода вместо аналитика.

**Тип:** Case  
**Треки:** Decision, Product  
**Пререквизиты:** 13/10 — Sensitivity analysis и falsification checks  
**Время:** ~105 минут  
**Результат:** собирает causal-study-package, воспроизводит
model-identify-estimate-refute workflow в DoWhy, сверяет его с прозрачными
RA/IPW/AIPW/DiD расчетами и объясняет, почему EconML не заменяет identification и нужен
только для отдельно поставленной heterogeneity-задачи.

## Цели обучения

- Собрать все артефакты causal study в один воспроизводимый package.
- Проверить checksum manifest для question, DAG, identification, estimates и refutation.
- Разложить исследование на workflow `model -> identify -> estimate -> refute`.
- Сопоставить этот workflow с DoWhy API без подмены assumptions автоматизацией.
- Объяснить, почему DoWhy не доказывает graph и не исправляет unmeasured confounding.
- Объяснить, почему EconML не нужен без CATE/policy-learning вопроса.
- Сформулировать финальный evidence statement с заблокированным strong claim.
- Передать package так, чтобы коллега мог проверить источник каждого числа.

## Проблема

После десяти уроков фазы у нас есть много файлов:

```text
causal_question.json
causal_dag.json
backdoor_adjustment_audit.json
g_formula_estimate_report.json
matching_report.json
ipw_aipw_report.json
did_report.json
quasi_experiment_report.json
sensitivity_report.json
```

Плохой финал:

```text
Мы всё посчитали, вот AIPW = -0.387, значит assisted onboarding вреден.
```

Ещё один плохой финал:

```text
Давайте загрузим всё в causal-библиотеку, она сама решит, что правда.
```

Финальный урок делает другое: собирает `causal-study-package`, где каждое число связано
с вопросом, DAG, identification assumptions, estimator diagnostics, falsification checks
и финальной claim policy.

## Концепция

### Четыре слоя causal workflow

Фаза учила держать четыре слоя отдельно:

| Слой | Вопрос | Ошибка |
|---|---|---|
| Model | Как устроен causal graph? | «Пусть библиотека сама найдет причинность» |
| Identify | Какой estimand identified under assumptions? | «Есть DAG, значит эффект identified» |
| Estimate | Какой estimator считает identified expression? | «Коэффициент и есть causal effect» |
| Refute | Какие проверки ослабляют claim? | «Placebo прошёл, значит assumptions доказаны» |

DoWhy полезен именно потому, что явно разделяет эти шаги:

```text
CausalModel(...)
identify_effect()
estimate_effect(...)
refute_estimate(...)
```

Но порядок API не делает assumptions истинными. Если DAG содержит unmeasured confounder,
automation не превращает `not_identified` в `identified`.

### Что собирает package

Artifact `causal-study-package-builder` строит:

```text
outputs/causal_study_package.json
outputs/checksum_manifest.json
```

Package содержит секции:

```text
question
model
identify
estimate
refute
automation_audit
evidence_statement
checksum_manifest
```

В summary:

```json
{
  "source_files_n": 15,
  "workflow_steps": ["model", "identify", "estimate", "refute"],
  "estimate_rows_n": 7,
  "final_claim_status": "blocked_single_strong_claim",
  "allowed_effect_claim": false
}
```

Это не «провал». Это честный результат: исследование воспроизводимо, но сильный causal
claim заблокирован.

### Почему DoWhy здесь trace, а не новая обязательная зависимость

В текущем locked runtime DoWhy не установлен. Урок намеренно не добавляет тяжелую
optional dependency ради финального packaging шага. Вместо этого package строит
DoWhy-compatible workflow trace:

| Step | DoWhy surface | Package input |
|---|---|---|
| model | `CausalModel(data, treatment, outcome, graph)` | `question`, `model` |
| identify | `model.identify_effect()` | `identify` |
| estimate | `model.estimate_effect(...)` | `estimate` |
| refute | `model.refute_estimate(...)` | `refute` |

Если в реальном проекте DoWhy установлен, этот trace показывает, куда подключить
runtime. Но для учебного package важнее граница:

```text
DoWhy can orchestrate workflow; it cannot invent credible assumptions.
```

### Почему EconML не используется

EconML решает задачи CATE, DML, causal forests, policy learning и другие ML-based
heterogeneity workflows. В этой фазе вопрос другой:

```text
average / design-specific evidence for assisted onboarding
```

Поэтому automation audit фиксирует:

```text
econml_used = false
```

Перед future use нужны:

- explicit heterogeneity estimand;
- достаточный sample size;
- separate ML validation;
- identification, обоснованный вне EconML.

## Соберите это

Файлы урока:

```text
outputs/causal_workflow_spec.json
outputs/causal_study_package_builder.py
outputs/causal_study_package.json
outputs/checksum_manifest.json
```

### Шаг 1: объявите upstream sources

Spec содержит 15 обязательных источников от `13/01` до `13/10`. Каждый source имеет:

```text
id
path
section
```

Builder проверяет:

```text
all_required_sources_are_present
all_required_sources_are_valid_json
upstream_audits_are_structurally_valid
```

Если потерять `causal_question.json`, package станет invalid: финальный вывод нельзя
передавать без исходного вопроса.

### Шаг 2: соберите question/model/identify

Package сохраняет:

```text
estimand_type = ATE
treatment = assisted_within_24h
comparator = no_assistance_within_24h
outcome = activation_14d
graph nodes = 19
graph edges = 44
backdoor_identification_status = not_identified_due_to_unmeasured_confounding
unmeasured_confounders = 1
```

Это принципиально: финальный package не прячет главный identification failure за
красивой таблицей estimates.

### Шаг 3: соберите estimates без pooling

Estimate table:

| Estimate | Source | Estimand | Value |
|---|---|---|---:|
| g_formula_manual_ate | 13/05 | ATE under outcome regression | -0.400 |
| matching_att | 13/06 | ATT after matching population change | -0.250 |
| ipw_hajek_ate | 13/07 | ATE under propensity weighting | -0.085 |
| aipw_ate | 13/07 | ATE under doubly robust assumptions | -0.387 |
| did_estimate | 13/08 | regional rollout ATT | +0.080 |
| rdd_wald_local_effect_diagnostic | 13/09 | local cutoff diagnostic | -1.000 |
| iv_wald_late | 13/09 | LATE for compliers | +0.500 |

Каждая строка имеет:

```text
poolable = false
```

Package проверяет:

```text
different_estimands_are_not_pooled
```

### Шаг 4: добавьте refutation и evidence statement

Из `13/10` package поднимает:

```text
falsification_failures:
- placebo_outcome_pre_activation
- negative_control_outcome_app_crashes

claim_blocking_reasons:
- falsification_checks_failed
- upstream_primary_claim_disallowed
- design_estimates_have_opposite_signs
- different_estimands_not_poolable
```

Final statement:

```text
final_claim_status = blocked_single_strong_claim
allowed_effect_claim = false
```

### Шаг 5: добавьте automation audit

Automation audit проверяет:

```text
dowhy_workflow_trace_has_model_identify_estimate_refute
automation_does_not_override_identification
econml_is_not_used_without_heterogeneity_question
dowhy_runtime_is_optional_and_documented
```

В текущем окружении:

```text
dowhy_runtime_status = not_installed_trace_validates_workflow_contract
econml_used = false
```

## Используйте это

Запуск из корня репозитория:

```bash
python phases/13-causal-analysis/11-causal-workflow/outputs/causal_study_package_builder.py
```

Команда обновляет:

```text
phases/13-causal-analysis/11-causal-workflow/outputs/causal_study_package.json
phases/13-causal-analysis/11-causal-workflow/outputs/checksum_manifest.json
```

Короткий пример:

```bash
python phases/13-causal-analysis/11-causal-workflow/code/main.py
```

Ожидаемый summary:

```json
{
  "package_valid": true,
  "source_files_n": 15,
  "workflow_steps": ["model", "identify", "estimate", "refute"],
  "estimate_rows_n": 7,
  "final_claim_status": "blocked_single_strong_claim",
  "allowed_effect_claim": false,
  "dowhy_runtime_status": "not_installed_trace_validates_workflow_contract",
  "econml_used": false
}
```

Для CI:

```bash
python phases/13-causal-analysis/11-causal-workflow/outputs/causal_study_package_builder.py \
  --fail-on-invalid
```

## Сломайте это

### Missing upstream source

Подмените путь к `causal_question.json` на несуществующий. Package станет invalid:

```text
all_required_sources_are_present = false
```

### Invalid JSON

Укажите source path на файл с невалидным JSON. Builder вернет:

```text
all_required_sources_are_valid_json = false
```

### Wrong workflow order

Поменяйте workflow steps на:

```text
model -> estimate -> identify -> refute
```

Check `dowhy_workflow_trace_has_model_identify_estimate_refute` сработает. Оценка до
identification — ровно та ошибка, которую фаза запрещает.

### Stronger claim than sensitivity allows

Если sensitivity report говорит `allowed_effect_claim = true`, а final evidence statement
остается `false`, package ловит несогласованность:

```text
final_claim_matches_sensitivity_policy = false
```

В реальном проекте обратная ошибка опаснее: финальный текст делает claim сильнее, чем
разрешила sensitivity policy.

### EconML without heterogeneity question

Если кто-то пытается объявить `econml_used = true` без CATE/policy-learning estimand,
package должен блокировать это как scope creep.

## Проверьте это

Поведенческие тесты:

```bash
python -m unittest phases/13-causal-analysis/11-causal-workflow/tests/test_main.py
```

Покрытие:

- valid package summary;
- runnable `code/main.py`;
- required sections и checksum manifest;
- question/model/identification preservation;
- estimate table и no-pooling policy;
- refutation/evidence statement consistency;
- DoWhy workflow trace order;
- automation does not override identification;
- EconML scope audit;
- committed package/manifest reproducibility;
- missing source;
- invalid JSON source;
- wrong workflow order;
- claim stronger than sensitivity policy;
- CLI `--fail-on-invalid`.

## Поставьте результат

Именованный artifact:

```text
causal-study-package-builder
```

Файлы:

```text
outputs/causal_study_package_builder.py
outputs/causal_workflow_spec.json
outputs/causal_study_package.json
outputs/checksum_manifest.json
outputs/artifact.json
```

Handoff-фраза:

```text
Phase 13 causal-study-package is structurally valid and reproducible. It contains
question, DAG, identification, estimates, refutation, DoWhy-compatible workflow trace,
EconML scope audit and checksum manifest for 15 upstream artifacts. The final claim is
blocked: primary backdoor ATE remains not identified due to unmeasured confounding,
falsification checks fail, design estimates target incompatible estimands and have
opposite signs. Report design-specific evidence only and request a cleaner experiment or
stronger natural experiment before a broad rollout decision.
```

## Упражнения

1. Добавьте новый source file в spec и проверьте, что checksum manifest вырос на одну
   строку.
2. Поменяйте `workflow_contract.steps` местами. Почему estimate до identify должен быть
   blocking error?
3. Добавьте CATE question в spec. Какие дополнительные проверки нужны перед EconML?
4. Сформулируйте stakeholder-ready conclusion из `evidence_statement`, не используя
   слово «доказали».
5. Удалите `did_report.json` из source list. Почему package станет менее полезным, даже
   если observational reports остались?

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Causal-study-package | «Папка с результатами» | Воспроизводимый пакет question, assumptions, identification, estimates, refutation и claim policy |
| Model | «Автоматически найденный graph» | DAG, заданный domain assumptions и временным порядком |
| Identify | «Выбрать estimator» | Доказать, какой causal estimand выражается через observed data under assumptions |
| Estimate | «Получить число» | Посчитать identified expression или design-specific estimate с diagnostics |
| Refute | «Доказать robustness» | Попытаться ослабить или опровергнуть claim через placebo/sensitivity checks |
| DoWhy workflow | «Кнопка causal inference» | Полезная структура `model -> identify -> estimate -> refute`, не заменяющая assumptions |
| EconML | «Более умная causal-библиотека» | ML-инструменты для heterogeneity/CATE/DML, не замена identification |
| Checksum manifest | «Техническая мелочь» | Способ доказать, что package ссылается на конкретные версии upstream artifacts |
| Evidence statement | «Красивый текст» | Ограниченный вывод, сила которого следует из diagnostics и claim policy |

## Дополнительное чтение

- [DoWhy documentation](https://www.pywhy.org/dowhy/main/index.html) — официальный workflow causal model, identify, estimate и refute; читать как orchestration layer, а не замену assumptions.
- [DoWhy refutation guide](https://www.pywhy.org/dowhy/main/user_guide/causal_tasks/refuting_causal_estimates/index.html) — официальные refuters и связь с placebo/sensitivity checks.
- [EconML documentation](https://www.pywhy.org/EconML/index.html) — границы CATE/DML/policy-learning инструментов; полезно понять, почему они не нужны без heterogeneity question.
- [Hernán and Robins, Causal Inference: What If](https://miguelhernan.org/whatifbook) — первичный учебник по target trial, identification assumptions и осторожной интерпретации observational effects.
- [Cinelli and Hazlett, 2020](https://doi.org/10.1111/rssb.12348) — primary source по sensitivity analysis, чтобы углубить финальный refutation block.
