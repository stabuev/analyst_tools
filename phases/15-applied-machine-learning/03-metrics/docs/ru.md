# Метрики и стоимость ошибки

> Метрика классификации - это не число для лидерборда, а договор о том, какую ошибку
> бизнес готов терпеть.

**Тип:** Case  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/02-data-splitting`  
**Время:** ~75 минут  
**Результат:** вы связываете confusion matrix, precision/recall/FPR/FNR,
PR-oriented metrics, threshold и business cost ошибки в metric policy.

## Цели обучения

- Посчитать confusion matrix при заданном threshold и вывести precision, recall, FPR,
  FNR и accuracy.
- Отличить score модели от бизнес-решения: score ранжирует риск, threshold превращает
  risk score в action.
- Выбрать threshold только на validation split и применить его к test без peeking.
- Сравнить threshold по offer budget и error cost: false positive тратит бюджет,
  false negative пропускает пользователя с churn risk.
- Зафиксировать, почему accuracy в imbalance-задаче остается diagnostic-only.

## Проблема

После `15/01` и `15/02` у вас есть supervised ML-постановка и честный split manifest.
Следующий соблазн - обучить модель и сказать: "accuracy 80%, значит хорошо". Для churn
risk это почти всегда плохой вывод.

В нашей задаче action ограничен: support может отправить retention offer не всем, а только
нескольким eligible trial users. Ошибки несимметричны:

- **false positive**: оффер ушел пользователю, который не churned. Бюджет потрачен зря.
- **false negative**: пользователь churned, но модель не подняла его выше threshold.
- **true positive**: support увидел пользователя с реальным риском.
- **true negative**: модель не тратит бюджет на пользователя без churn.

Модель может выдавать probability-like score, но решение рождается только после threshold.
Threshold нельзя выбирать на test: если вы посмотрели test precision и поменяли порог, test
перестал быть финальной проверкой.

## Концепция

Для бинарной классификации при фиксированном threshold каждая строка попадает в одну
ячейку:

| Target | Predicted positive | Predicted negative |
|---|---:|---:|
| Positive | TP | FN |
| Negative | FP | TN |

Из этих четырех чисел получаются основные decision metrics:

| Метрика | Формула | Что показывает |
|---|---|---|
| Precision | `TP / (TP + FP)` | Какая доля отправленных offer была по positive users. |
| Recall | `TP / (TP + FN)` | Какую долю positive users поймали. |
| FPR | `FP / (FP + TN)` | Как часто тревожим negative users. |
| FNR | `FN / (TP + FN)` | Как часто пропускаем positive users. |
| Accuracy | `(TP + TN) / N` | Общая доля верных labels, часто misleading при imbalance. |

В tiny profile урока есть `ml_candidate_scores.csv`. Это еще не обученная production-модель,
а deterministic score table для проверки metric policy:

| Split | Rows | Positive labels | Offer budget | Threshold source |
|---|---:|---:|---:|---|
| train | 4 | 2 | 2 | не выбираем threshold |
| validation | 3 | 1 | 2 | выбираем threshold |
| test | 5 | 1 | 2 | только оцениваем выбранный threshold |

Business cost зафиксирован в `problem_spec.json`:

```json
{
  "metric_policy": {
    "primary_metric": "precision_at_offer_budget",
    "secondary_metrics": ["recall", "pr_auc", "roc_auc", "log_loss"],
    "accuracy_role": "diagnostic_only",
    "cost_weights": {
      "false_positive": 1.0,
      "false_negative": 5.0
    }
  },
  "threshold_policy": {
    "selection_data": "validation",
    "rule": "min_error_cost_under_offer_budget"
  }
}
```

Это не универсальная экономика. Это явный договор для текущего продукта: пропустить churner
дороже, чем отправить лишний offer.

## Соберите это

Начните с ручной функции confusion matrix. Вход - строки со score, target и threshold:

```python
def confusion(rows, threshold):
    tp = fp = tn = fn = 0
    for row in rows:
        predicted_positive = row["score"] >= threshold
        if predicted_positive and row["target"]:
            tp += 1
        elif predicted_positive and not row["target"]:
            fp += 1
        elif not predicted_positive and row["target"]:
            fn += 1
        else:
            tn += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}
```

Метрики выводятся из тех же четырех чисел:

```python
precision = tp / (tp + fp) if tp + fp else None
recall = tp / (tp + fn) if tp + fn else None
fpr = fp / (fp + tn) if fp + tn else None
fnr = fn / (tp + fn) if tp + fn else None
```

Теперь добавьте стоимость:

```python
total_error_cost = fp * false_positive_cost + fn * false_negative_cost
```

Validation score table в tiny profile устроен так:

| Snapshot | Target | Score |
|---|---:|---:|
| `S005` | 0 | 0.74 |
| `S006` | 1 | 0.60 |
| `S007` | 0 | 0.30 |

Threshold sweep показывает trade-off:

| Threshold | Offers | TP | FP | TN | FN | Precision | Recall | Cost |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.00 | 0 | 0 | 0 | 2 | 1 | null | 0.0 | 5.0 |
| 0.74 | 1 | 0 | 1 | 1 | 1 | 0.0 | 0.0 | 6.0 |
| 0.60 | 2 | 1 | 1 | 1 | 0 | 0.5 | 1.0 | 1.0 |
| 0.30 | 3 | 1 | 2 | 0 | 0 | 0.333333 | 1.0 | 2.0 |

Порог `0.30` виден в sweep, но нарушает offer budget `2`. Порог `0.60` имеет минимальную
error cost среди threshold rows внутри бюджета, поэтому его можно передать дальше.

## Используйте это

Урок поставляет CLI `classification-metric-evaluator`:

```bash
python outputs/classification_metric_evaluator.py \
  --spec ../data/tiny/problem_spec.json \
  --snapshots ../data/tiny/ml_scoring_snapshots.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --scores ../data/tiny/ml_candidate_scores.csv \
  --output outputs/classification_metric_report.json
```

Отчет содержит:

- `validation_threshold_sweep`: все validation thresholds, confusion rows, metrics и cost;
- `selected_threshold`: threshold, выбранный только на validation;
- `metrics_at_selected_threshold.validation`: validation result для выбранного threshold;
- `metrics_at_selected_threshold.test`: финальная оценка выбранного threshold на test;
- `ranking_metrics_by_split`: average precision, ROC AUC и log loss;
- `checks`: quality gates для score coverage, metric policy, label completeness и roles.

Короткий итог tiny profile:

```json
{
  "selected_threshold": 0.6,
  "threshold_selected_on": "validation",
  "metrics_at_selected_threshold": {
    "test": {
      "tp": 1,
      "fp": 1,
      "tn": 3,
      "fn": 0,
      "precision": 0.5,
      "recall": 1.0,
      "fpr": 0.25,
      "total_error_cost": 1.0
    }
  }
}
```

Важно: test numbers не меняют threshold. Они только показывают, как заранее выбранное
решение повело себя на holdout.

## Сломайте это

Проверьте типовые поломки.

1. Удалите score для `S006`. Audit должен заблокировать metric report: split row без score
   нельзя оценить.
2. Добавьте score для ineligible `S008`. Score table не должен расширять population после
   problem framing.
3. Поставьте `score = 1.2`. Probability-like score обязан лежать в `[0, 1]`.
4. Поменяйте `threshold_policy.selection_data` на `test`. Это test peeking.
5. Сделайте `metric_policy.cost_weights.false_negative = -1`. Стоимость ошибки не может
   быть отрицательной.
6. Поменяйте validation label `S006` на `false`. PR metrics больше не имеют positive class
   на validation.
7. Поставьте test row роль `model_selection_and_threshold_selection`. Test потеряет роль
   final once-only evaluation.

Строгий режим возвращает non-zero даже при warnings:

```bash
python outputs/classification_metric_evaluator.py \
  --spec ../data/tiny/problem_spec.json \
  --snapshots ../data/tiny/ml_scoring_snapshots.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --scores ../data/tiny/ml_candidate_scores.csv \
  --fail-on-warning
```

Tiny warning ожидаем: три validation rows и пять test rows годятся для contract validation,
но не для production threshold tuning.

## Проверьте это

Behavioral tests запускаются так:

```bash
uv run --locked python -m unittest discover \
  -s phases/15-applied-machine-learning/03-metrics/tests -v
```

Они проверяют:

- выбранный threshold `0.6` и запрет test peeking;
- ручные TP/FP/TN/FN, precision, recall, FPR и cost;
- ranking metrics и diagnostic-only роль accuracy;
- запуск `code/main.py` и запись `classification_metric_report.json`;
- воспроизводимость `data/generate_data.py --check`;
- missing, duplicate, extra и invalid score rows;
- train-fitted provenance для score table;
- validation/test label class coverage;
- CLI exit codes и `--fail-on-warning`.

Интерпретация:

```text
valid = true
```

означает, что metric policy и threshold selection готовы для следующих уроков. Это не
означает, что модель уже обучена, откалибрована или безопасна для production rollout.

## Поставьте результат

Итоговый артефакт:

```text
outputs/classification_metric_evaluator.py
```

Он принимает `problem_spec.json`, scoring snapshots, labels, split manifest и candidate
scores, а возвращает JSON-аудит classification metric policy.

`code/main.py` запускает артефакт на committed tiny profile и обновляет:

```text
outputs/classification_metric_report.json
```

Следующий урок использует этот report как договор: preprocessing и baseline должны
производить score table того же grain, а threshold и test boundary уже зафиксированы.

## Упражнения

1. Измените `false_negative` cost с `5.0` на `2.0` и объясните, изменится ли выбранный
   threshold.
2. Добавьте новый validation score между `0.60` и `0.74` и пересчитайте threshold sweep
   вручную.
3. Сделайте offer budget равным `1` и опишите, почему precision может вырасти, а recall
   упасть.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Confusion matrix | Таблица нужна только для отчета. | Это минимальный учет ошибок, из которого выводятся decision metrics. |
| Precision | То же самое, что accuracy. | Доля true positives среди всех predicted positives. |
| Recall | Доля правильных predictions вообще. | Доля найденных positives среди всех actual positives. |
| Threshold | Свойство модели. | Отдельное decision rule, выбираемое по validation и business policy. |
| PR AUC / average precision | Всегда лучше ROC AUC. | Полезнее при rare positive class, но все равно требует связи с decision cost. |
| Test peeking | Только прямое обучение на test. | Любое изменение threshold, модели или features после просмотра test результата. |

## Дополнительное чтение

- [scikit-learn: Tuning the decision threshold for class prediction](https://scikit-learn.org/stable/modules/classification_threshold.html) — прочитайте разделы про разделение probability prediction и decision threshold, а также предупреждение про tuning threshold не на train/test.
- [scikit-learn: Metrics and scoring](https://scikit-learn.org/stable/modules/model_evaluation.html#classification-metrics) — карта classification metrics и различие между scoring API, metric functions и business-aligned scoring.
- [scikit-learn: `confusion_matrix`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.confusion_matrix.html) — API, к которому удобно сверять ручные TP/FP/TN/FN расчеты.
- [scikit-learn: `average_precision_score`](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html) — как scikit-learn считает PR-oriented ranking metric для probability scores.
