# Порог и стоимость решения для сильной модели

> Сильная модель полезна только тогда, когда улучшает действие при заданном бюджете, стоимости ошибок и честной калибровке.

**Тип:** Case  
**Треки:** ML, Decision  
**Пререквизиты:** `16-tabular-ml/07-segment-analysis`  
**Время:** ~75 минут  
**Результат:** cost-sensitive decision evaluator, который выбирает validation threshold, сравнивает top-k budget и блокирует promotion CatBoost-кандидата, если бизнес-стоимость решения хуже baseline.

## Цели обучения

- Разделить score модели, threshold decision и бизнес-действие.
- Посчитать стоимость FP/FN под ограничением `max_actions=2`.
- Выбрать threshold на validation split и не трогать final holdout.
- Сравнить selected threshold, fixed threshold `0.5` и top-k budget.
- Оформить decision gate, который не делает causal claim про retention offer.

## Проблема

В предыдущих уроках мы обучили CatBoost-кандидата и нашли важный неприятный факт: на tiny validation split он меняет top-2 action set не в лучшую сторону. Baseline выбирает `S007,S006`, CatBoost выбирает `S007,S005`, а настоящий positive `S006` выпадает из действия.

Но бизнес-задача не звучит как “получить красивый ROC AUC”. Она звучит так:

- есть пакет eligible trial users;
- команда поддержки может отправить максимум два retention offer;
- false positive тратит бюджет на пользователя, который не churned;
- false negative пропускает high-risk пользователя, который churned;
- по problem spec FN стоит в 5 раз дороже FP.

Значит, следующий вопрос: меняет ли CatBoost бизнес-решение в лучшую сторону, если считать стоимость ошибок, threshold и бюджет? Ответ в этом fixture: нет.

## Концепция

У бинарной модели есть минимум три разных слоя:

| Слой | Что отвечает | Где легко ошибиться |
|---|---|---|
| Score | Насколько объект похож на positive class | Принять score за готовое действие |
| Threshold | С какого score делать действие | Подобрать порог на test или на train |
| Budget | Сколько действий вообще можно сделать | Сравнить модели при разных action count |
| Cost | Что дороже: FP или FN | Оптимизировать precision без учета FN |

В этом уроке baseline получает калиброванный score из фазы 15:

```text
S006: 0.555556, actual=1
S005: 0.222222, actual=0
S007: 0.222222, actual=0
```

CatBoost-кандидат получает declared raw probability из сегментного анализа:

```text
S007: 0.507692, actual=0
S005: 0.492308, actual=0
S006: 0.492308, actual=1
```

Это специально несимметрично. Baseline уже прошел calibration handoff, а CatBoost еще нет. Поэтому gate проверяет не только стоимость, но и статус калибровки.

### Формула стоимости

Для каждого threshold:

```text
total_error_cost = FP * false_positive_cost + FN * false_negative_cost
```

В нашем problem spec:

```text
false_positive_cost = 1
false_negative_cost = 5
max_actions = 2
```

Threshold eligible только если он выбирает не больше двух строк. Если threshold выбирает три строки, он может иметь низкую стоимость ошибок на validation, но нарушает операционный бюджет.

## Соберите это

### Шаг 1. Соберите decision rows

Минимальная таблица для решения не должна тащить весь feature matrix. Нужны только:

- `snapshot_id`;
- `actual_label`;
- `score`;
- `model_role`;
- `score_source`;
- `calibration_status`.

Baseline берется из `calibrated_predictions.csv`, CatBoost - из `strong_model_segment_report.json`.

```python
rows = [
    {"model_role": "baseline", "snapshot_id": "S006", "score": 0.555556, "actual_label": 1},
    {"model_role": "baseline", "snapshot_id": "S005", "score": 0.222222, "actual_label": 0},
    {"model_role": "baseline", "snapshot_id": "S007", "score": 0.222222, "actual_label": 0},
    {"model_role": "catboost", "snapshot_id": "S007", "score": 0.507692, "actual_label": 0},
    {"model_role": "catboost", "snapshot_id": "S005", "score": 0.492308, "actual_label": 0},
    {"model_role": "catboost", "snapshot_id": "S006", "score": 0.492308, "actual_label": 1},
]
```

Важно: обе модели сравниваются на одном и том же validation population: `S005,S006,S007`.

### Шаг 2. Посчитайте threshold table

Для каждого threshold из policy:

```text
1.0, 0.6, 0.5, 0.492308, 0.3
```

делаем action, если `score >= threshold`, затем считаем TP/FP/TN/FN и стоимость.

Ключевой момент: threshold `0.492308` для CatBoost включает и `S005`, и `S006`, потому что сравнение inclusive. Это дает меньшую стоимость ошибок, но выбирает три строки:

```text
selected_ids = S007,S005,S006
total_error_cost = 2
budget_status = over_budget
```

Такой threshold нельзя выбрать, потому что лимит действий равен двум.

### Шаг 3. Выберите лучший threshold

Tie-breaker в policy:

```text
min_total_error_cost -> max_recall -> min_action_count -> threshold_desc
```

На validation:

- baseline выбирает threshold `0.5`, action `S006`, cost `0`;
- CatBoost выбирает threshold `1.0`, action set пустой, cost `5`.

Пустой action set - не победа. Это лучший eligible threshold для CatBoost только потому, что остальные eligible варианты еще хуже или равны по стоимости.

### Шаг 4. Сравните top-k budget

Top-k policy имитирует реальный рабочий режим: взять два highest score.

```text
baseline top-2: S006,S005 -> TP=1, FP=1, FN=0, cost=1
catboost top-2: S007,S005 -> TP=0, FP=2, FN=1, cost=7
```

Здесь видно, почему средний score или ranking “на глаз” опасны. CatBoost поставил настоящего churn user `S006` ниже двух negative строк.

## Используйте это

Запустите урок из корня репозитория:

```bash
uv run --locked python phases/16-tabular-ml/08-cost-sensitive-decisions/code/main.py
```

Ожидаемый summary:

```json
{
  "audit_valid": true,
  "baseline_selected_threshold": 0.5,
  "catboost_selected_threshold": 1.0,
  "baseline_best_total_error_cost": 0.0,
  "catboost_best_total_error_cost": 5.0,
  "baseline_top_k_total_error_cost": 1.0,
  "catboost_top_k_total_error_cost": 7.0,
  "decision_status": "do_not_promote_catboost_candidate",
  "readiness_status": "ready_for_optuna_lesson"
}
```

Основные файлы:

- `outputs/cost_sensitive_decision_rows.csv` - одинаковые validation rows и score sources.
- `outputs/threshold_comparison.csv` - cost по каждому threshold.
- `outputs/budget_impact.csv` - selected threshold, top-k и fixed threshold `0.5`.
- `outputs/decision_gate.csv` - причины, почему CatBoost не продвигается.
- `outputs/cost_sensitive_decision_report.json` - полный отчет для handoff.

Decision gate специально разделяет два вывода:

```text
CatBoost не продвигается в бизнес-решение.
CatBoost можно продолжать улучшать в следующем уроке через Optuna.
```

Это разные решения. Не продвигать текущего кандидата не значит прекращать исследование.

## Сломайте это

### Ошибка 1. Подобрать threshold на test

Измените policy:

```json
"threshold_policy": {
  "selection_data": "test"
}
```

Evaluator вернет:

```text
valid = false
blocking_errors = threshold_selection_uses_validation_only
readiness_status = blocked_before_cost_sensitive_decision
```

Threshold выбирается на validation. Test остается финальной проверкой, а не местом для подбора решения.

### Ошибка 2. Игнорировать calibration status

CatBoost score в этом уроке - declared probability, но не approved calibrated probability. Поэтому даже если бы cost был лучше, promotion gate все равно потребовал бы отдельный calibration handoff.

### Ошибка 3. Считать causal effect offer

Этот отчет говорит только о ranking decision: кому команда поддержки отправит предложение. Он не доказывает, что offer снижает churn. Для этого нужен experiment или causal design.

## Проверьте это

Запустите тесты урока:

```bash
uv run --locked python -m unittest discover -s phases/16-tabular-ml/08-cost-sensitive-decisions/tests
```

Что проверяют тесты:

- baseline и CatBoost сравниваются на тех же `S005,S006,S007`;
- baseline score помечен как calibrated, CatBoost - как not approved;
- threshold `0.5` для baseline дает cost `0`;
- threshold `0.492308` для CatBoost over-budget;
- top-k CatBoost дает cost `7`;
- decision gate блокирует promotion по cost, calibration и segment warnings;
- попытка выбрать threshold на test становится blocking error.

## Поставьте результат

Именованный артефакт:

```text
outputs/cost_sensitive_decision_evaluator.py
```

Standalone запуск:

```bash
uv run --locked python phases/16-tabular-ml/08-cost-sensitive-decisions/outputs/cost_sensitive_decision_evaluator.py \
  --output-root phases/16-tabular-ml/08-cost-sensitive-decisions/outputs
```

Артефакт можно переиспользовать как audit step перед model promotion:

1. Подайте policy с cost, budget и threshold candidates.
2. Подайте калиброванные baseline predictions.
3. Подайте segment report кандидата.
4. Проверьте `decision_status` и `failed_promotion_gates`.

## Упражнения

1. Уберите threshold `1.0` из policy и объясните, какой threshold выберет CatBoost и почему.
2. Поменяйте `false_negative_cost` с `5` на `2` и пересчитайте decision gate.
3. Добавьте gate, который запрещает promotion, если fixed threshold `0.5` ухудшает cost относительно baseline.
4. Сформулируйте, какой эксперимент нужен, чтобы перейти от “кому отправить offer” к “offer действительно снижает churn”.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Decision threshold | `0.5` всегда нормальный порог | Порог зависит от стоимости ошибок, бюджета и цели действия |
| Top-k budget | Это то же самое, что threshold | Top-k фиксирует число действий, threshold фиксирует минимальный score |
| False positive cost | Можно игнорировать, если recall высокий | FP тратит ограниченный операционный бюджет |
| False negative cost | Это просто missed label | FN может быть главным бизнес-риском, если пропущенный positive дорог |
| Calibration handoff | Нужен только для красивого графика | Нужен, чтобы score можно было честно использовать как probability в decision layer |
| Causal effect boundary | Если score хороший, offer работает | Risk score не оценивает эффект интервенции |

## Дополнительное чтение

- [scikit-learn: Tuning the decision threshold for class prediction](https://scikit-learn.org/stable/modules/classification_threshold.html) - прочитайте разделы про разделение probability estimation и decision problem, а также пример cost-sensitive threshold tuning.
- [scikit-learn: Probability calibration](https://scikit-learn.org/stable/modules/calibration.html) - повторите, почему некалиброванный score опасно превращать в бизнес-порог.
- [scikit-learn: Precision, recall and F-measure metrics](https://scikit-learn.org/stable/modules/model_evaluation.html#precision-recall-f-measure-metrics) - используйте как справочник для связи precision/recall с FP/FN.
- [Model Cards for Model Reporting](https://arxiv.org/abs/1810.03993) - первичный источник про intended use, limitations и disaggregated performance, которые нужны рядом с promotion gate.
