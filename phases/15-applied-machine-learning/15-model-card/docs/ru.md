# Model card и ограничения

> Model card не делает модель production-ready; он делает границы применения проверяемыми.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** 15-applied-machine-learning/14-error-analysis  
**Время:** ~90 минут  
**Результат:** вы собираете финальный ML baseline package: model card, decision report, evidence matrix, risk register и checksum manifest поверх всех артефактов фазы.

## Цели обучения

- Собрать model card из upstream evidence, а не из свободного текста.
- Проверить, что readiness chain проходит через problem framing, split, metrics, preprocessing, pipeline, CV, imbalance, calibration, leakage и error analysis.
- Явно отделить допустимый claim `baseline_package_ready_for_review` от запрещенных claims вроде `production_ready` и `causal_offer_effect`.
- Зафиксировать warnings, ограничения, risks и required follow-ups в decision report.
- Выпустить воспроизводимый package с sha256 manifest для входов и выходов.

## Проблема

Фаза 15 уже построила честный baseline для churn-risk: сформулировала задачу, закрыла split contract, метрики, preprocessing, pipeline, сравнение моделей, imbalance policy, calibration, leakage audit и segment error analysis.

Но набор отчетов сам по себе не является handoff. Через неделю другой аналитик или ML-инженер увидит десятки JSON/CSV и может сделать неверный вывод: "precision at budget 0.5, recall 1.0, значит можно катить". Это опасно. В tiny profile есть 37 upstream warnings, 19 small-n срезов и 4 hidden failure slices. Модель можно обсуждать как baseline, но нельзя объявлять production-ready.

В этом уроке вы собираете финальный пакет, который сохраняет всю полезную evidence и одновременно запрещает лишние обещания.

## Концепция

Model card - это не рекламный лист модели. Это контракт отчетности:

| Блок | Что фиксирует | Что запрещает |
|---|---|---|
| Model details | какая модель и pipeline упакованы | путать baseline с финальной production system |
| Intended use | допустимый сценарий: приоритизация support review | автоматическое действие по аккаунту |
| Data | train/validation/test rows и роль holdout | выбор threshold на test |
| Metrics | precision/recall/error на согласованном decision rule | переносить aggregate score на все сегменты |
| Calibration | метод и test calibration metrics | считать score причинным эффектом offer |
| Error analysis | small-n и hidden failures | прятать неудобные срезы |
| Limitations | риски и required controls | говорить "ограничений нет" |
| Decision | release boundary | писать `production_ready` без review |

Финальный package должен быть машинно-проверяемым. Поэтому урок выпускает не только Markdown, но и структурные файлы:

- `ml_baseline_package.json` - полный пакет evidence и policy summary;
- `ml_baseline_package_report.json` - проверки, warnings и blocking errors;
- `model_card.md` - readable model card;
- `decision_report.md` - решение и условия перехода дальше;
- `evidence_matrix.csv` - 14 upstream reports и их readiness;
- `risk_register.csv` - риски, severity, controls и owner action;
- `model_card_policy_audit.csv` - pass/fail checks policy;
- `ml_baseline_package_manifest.json` - sha256 manifest для 29 inputs и 7 generated outputs.

## Соберите это

### Шаг 1. Package spec

`ml_baseline_package_spec.json` описывает, какие upstream reports и evidence tables обязаны войти в handoff. Это защищает от "случайно забыли leakage audit" или "убрали hidden failure table".

```json
{
  "package_id": "trial-churn-ml-baseline-package-v0",
  "model_card_id": "trial-churn-risk-model-card-v0",
  "source_model_id": "random_forest_depth2_class_weight_balanced",
  "decision_policy": {
    "status_if_valid_with_warnings": "review_required_before_production",
    "allowed_claim": "baseline_package_ready_for_review"
  }
}
```

Spec содержит 14 обязательных upstream reports: от `problem_report` до `error_analysis_report`. Для каждого задан ожидаемый readiness status, поэтому packager проверяет цепочку, а не просто наличие файлов.

### Шаг 2. Evidence matrix

Evidence matrix - это индекс доверия. Каждая строка отвечает на вопрос: "какой урок передал evidence и можно ли на него опираться дальше?"

```python
for report_name, report in upstream_reports.items():
    evidence_rows.append({
        "report_name": report_name,
        "valid": report["valid"],
        "readiness_status": report["summary"]["readiness_status"],
        "warning_count": len(report["summary"].get("warnings", [])),
    })
```

В happy path получается 14 строк. Если один report invalid или имеет неожиданный readiness status, package получает blocking error.

### Шаг 3. Risk register

Warnings не должны теряться в model card. Packager поднимает их в risk register:

| Risk | Почему важен | Контроль |
|---|---|---|
| `tiny_profile_not_production_sample` | данных достаточно для учебного smoke test, но не для production claim | собрать larger holdout |
| `hidden_segment_failure` | aggregate precision скрывает проблемные срезы | segment review и monitoring |
| `small_n_segment_metrics` | часть срезов diagnostic-only | не делать сильные segment claims |
| `no_causal_offer_effect` | churn score не доказывает эффект offer | эксперимент или causal design |
| `model_artifact_security` | serialized sklearn artifacts требуют доверенной среды | security review |

### Шаг 4. Decision boundary

Финальный статус не равен `production_ready`, даже если package structurally valid.

```python
if valid and warnings:
    decision_status = "review_required_before_production"
elif valid:
    decision_status = "ready_for_review"
else:
    decision_status = "blocked"
```

Для этого baseline допустимый claim только один: `baseline_package_ready_for_review`. Запрещены `production_ready`, `causal_offer_effect`, `segment_ready_from_overall_metric` и автоматические действия по аккаунту.

### Шаг 5. Manifest

Manifest считает sha256 для входных evidence files и выходных package files. Он не доказывает качество модели, но делает handoff проверяемым: если кто-то поменял `hidden_failure_slices.csv` или `model_card.md`, hash изменится.

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/15-applied-machine-learning/15-model-card/code/main.py
```

Короткий итог:

```json
{
  "package_valid": true,
  "package_id": "trial-churn-ml-baseline-package-v0",
  "model_card_id": "trial-churn-risk-model-card-v0",
  "decision_status": "review_required_before_production",
  "evidence_row_count": 14,
  "risk_row_count": 8,
  "hidden_failure_slice_count": 4,
  "production_ready": false,
  "readiness_status": "phase_15_complete_baseline_package"
}
```

Report сохраняет важные предупреждения:

- `upstream_warning_count = 37`;
- `small_n_slice_count = 19`;
- `hidden_failure_slice_count = 4`;
- `model_card_requires_human_review_before_production`.

CLI можно запускать напрямую:

```bash
uv run --locked python phases/15-applied-machine-learning/15-model-card/outputs/ml_baseline_packager.py \
  --output-dir phases/15-applied-machine-learning/15-model-card/outputs
```

Для release gate используйте строгий режим:

```bash
uv run --locked python phases/15-applied-machine-learning/15-model-card/outputs/ml_baseline_packager.py \
  --output-dir /tmp/ml-baseline-package \
  --fail-on-warning
```

В этом уроке строгий режим должен завершиться non-zero: package valid, но warnings намеренно блокируют безусловный release.

## Сломайте это

1. Удалите `error_analysis` из `model_card_sections`. Packager должен заблокировать package, потому что model card больше не содержит обязательный раздел.
2. Поменяйте `status_if_valid_with_warnings` на `production_ready`. Policy audit должен отклонить такой claim.
3. Уберите `hidden_failure_slices.csv` или очистите его при наличии `hidden_failure_slice_count = 4` в report. Это blocking error: неудобные срезы нельзя прятать.
4. Сделайте один upstream report invalid. Evidence matrix должна сохранить факт, а package - перейти в blocked state.
5. Запустите с `--fail-on-warning`. Это проверяет release gate, где warnings уже достаточно для остановки автоматического продвижения.

## Проверьте это

```bash
uv run --locked python -m unittest discover -s phases/15-applied-machine-learning/15-model-card/tests
```

Тесты проверяют:

- happy path закрывает фазу статусом `phase_15_complete_baseline_package`;
- `production_ready` остается `false`;
- model card содержит все обязательные sections;
- evidence matrix включает 14 upstream reports;
- hidden failures и small-n warnings не исчезают из package;
- risk register блокирует causal offer-effect claim;
- manifest содержит hashes входов и выходов;
- CLI корректно пишет output directory, падает в `--fail-on-warning` и возвращает structured runtime error при плохом input.

## Поставьте результат

Named artifact:

```text
phases/15-applied-machine-learning/15-model-card/outputs/ml_baseline_packager.py
```

При запуске `code/main.py` урок публикует:

- `ml_baseline_package.json`;
- `ml_baseline_package_report.json`;
- `model_card.md`;
- `decision_report.md`;
- `evidence_matrix.csv`;
- `risk_register.csv`;
- `model_card_policy_audit.csv`;
- `ml_baseline_package_manifest.json`.

Это финальный handoff фазы 15. Следующий этап может улучшать модель, интерпретируемость и production workflow, но baseline теперь имеет проверяемые границы: можно обсуждать review package, нельзя обещать production effect.

## Упражнения

1. Добавьте в `risk_policy` новый risk про drift в unknown categories и проверьте, что он появляется в `risk_register.csv`.
2. Добавьте новый required upstream artifact и убедитесь, что package блокируется, если файл не передан.
3. Перепишите `decision_report.md` так, чтобы он отдельно перечислял blockers, warnings и required owner sign-offs.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Model card | Красивое описание модели | Проверяемый отчет о назначении, данных, метриках, ограничениях и решении |
| Claim boundary | Формальность в тексте | Явный список утверждений, которые можно и нельзя делать |
| Evidence matrix | Список файлов | Таблица lineage для upstream reports и readiness statuses |
| Risk register | То же самое, что warnings | Операционный список рисков, controls и follow-up actions |
| Checksum manifest | Гарантия качества модели | Способ проверить неизменность входов и выходов package |

## Дополнительное чтение

- [Model Cards for Model Reporting](https://arxiv.org/abs/1810.03993) - первичный источник идеи model cards: intended use, evaluation factors, disaggregated metrics и прозрачное раскрытие ограничений.
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) - официальный framework про governance, measurement и risk controls для AI systems; полезен для оформления decision boundary.
- [scikit-learn: Model persistence](https://scikit-learn.org/stable/model_persistence.html) - раздел про сохранение моделей и security boundary: почему serialized artifacts нельзя открывать в недоверенной среде.
- [scikit-learn: Classification metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#classification-metrics) - справочник по classification evaluation, который помогает отделять метрики модели от claims о бизнес-эффекте.
