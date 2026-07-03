# Train, validation и test

> Split - это часть постановки ML-задачи: train учит, validation выбирает, test один раз
> проверяет обещание.

**Тип:** Build  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/01-problem-framing`  
**Время:** ~75 минут  
**Результат:** вы строите train/validation/test split manifest, который уважает
prediction time, user grouping, label horizon и роли validation/test.

## Цели обучения

- Превратить `problem_spec.json` в machine-readable `ml_split_manifest.csv`.
- Разделить роли: train для fit, validation для выбора модели/threshold, test для
  финальной однократной оценки.
- Проверить, что один `user_id` не попадает в разные split.
- Защитить временной holdout: train prediction times раньше validation, validation раньше
  test.
- Заблокировать split rows с незавершенным label horizon или ручным test peeking.

## Проблема

После первого урока у вас есть честная supervised ML-постановка: score строится за 7 дней
до конца trial, target `churn_14d` появляется после 14-дневного окна, forbidden feature
sources зафиксированы. Теперь хочется обучить baseline.

Плохой shortcut - вызвать случайный `train_test_split` на строках и сразу смотреть score.
Для churn-risk задачи такой split может быть нечестным:

- один пользователь попадает в train и test разными snapshot rows;
- validation и test перемешиваются, и threshold подбирается на test;
- строки с более поздним `prediction_time` оказываются в train, а ранние - в test;
- label еще не наблюден после полного horizon, но строку уже используют для оценки;
- split не зафиксирован как артефакт, поэтому следующий запуск оценивает другую задачу.

В этом уроке модель еще не обучается. Вы строите split manifest и аудитор, который
говорит: эти строки можно отдавать будущим урокам про метрики и baseline.

## Концепция

У supervised split есть три разные роли.

| Split | Что делает | Что запрещено |
|---|---|---|
| Train | Fit preprocessing и estimator. | Выбирать threshold по будущему test. |
| Validation | Выбирать model family, hyperparameters и threshold. | Называть итоговой оценкой качества. |
| Test | Один раз оценить выбранный pipeline. | Менять модель, threshold или preprocessing после просмотра результата. |

Для продукта со временем и повторными пользователями добавляются две оси:

- **group axis**: один `user_id` должен принадлежать только одному split;
- **time axis**: prediction times должны идти от прошлого к будущему.

В `tiny` profile фазы 15 split выглядит так:

| Split | Prediction time | Rows | Positive labels | Роль |
|---|---|---:|---:|---|
| train | `2026-05-10T09:00:00+03:00` | 4 | 2 | fit preprocessing and estimator |
| validation | `2026-05-17T09:00:00+03:00` | 3 | 1 | model and threshold selection |
| test | `2026-05-24T09:00:00+03:00` | 5 | 1 | final once-only evaluation |

Такой split крошечный и поэтому годится только для contract validation. В production
числа должны быть намного больше, но правила те же: сначала фиксируем split, потом
обучаем модели.

## Соберите это

Начните с ручного split manifest. Возьмите только eligible snapshots из `problem_spec`:

```python
eligible = [
    row for row in snapshots
    if row["eligible_for_offer"] == "true" and int(row["days_until_trial_end"]) == 7
]
```

Назначьте split по `prediction_time`, а не по случайной перестановке строк:

```python
def split_for(prediction_time: str) -> tuple[str, int, str]:
    if prediction_time.startswith("2026-05-10"):
        return "train", 1, "fit_preprocessing_and_estimator"
    if prediction_time.startswith("2026-05-17"):
        return "validation", 2, "model_selection_and_threshold_selection"
    return "test", 3, "final_once_only_evaluation"
```

Минимальный manifest должен дублировать review-поля из snapshots:

```text
snapshot_id,user_id,prediction_time,split,split_order,role,assigned_by_policy
```

Это намеренное дублирование. Если кто-то вручную меняет `prediction_time` в manifest, audit
должен поймать расхождение с immutable scoring snapshot.

Теперь проверьте group isolation:

```python
from collections import defaultdict

splits_by_user = defaultdict(set)
for row in manifest:
    splits_by_user[row["user_id"]].add(row["split"])

leaking_users = {
    user_id: splits
    for user_id, splits in splits_by_user.items()
    if len(splits) > 1
}
assert leaking_users == {}
```

И временной порядок:

```python
assert max(train_times) < min(validation_times)
assert max(validation_times) < min(test_times)
```

Такие проверки выглядят скучно, пока не поймают первую модель, которая «победила» только
потому, что один пользователь или будущее окно попали в обе стороны оценки.

## Используйте это

Урок поставляет CLI `ml-split-auditor`:

```bash
python outputs/ml_split_auditor.py \
  --spec ../data/tiny/problem_spec.json \
  --snapshots ../data/tiny/ml_scoring_snapshots.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --output outputs/ml_split_report.json
```

Отчет содержит:

- `valid`: можно ли отдавать split следующим урокам;
- `rows_by_split`: train/validation/test объемы;
- `positives_by_split` и `negatives_by_split`: sanity check классов;
- `prediction_time_range_by_split`: фактические temporal boundaries;
- `blocking_errors`: нарушения, которые запрещают modeling;
- `warnings`: ограничения, которые нужно явно пронести дальше.

Базовый tiny report валиден, но предупреждает о маленьком размере:

```json
{
  "valid": true,
  "rows_by_split": {"train": 4, "validation": 3, "test": 5},
  "positives_by_split": {"train": 2, "validation": 1, "test": 1},
  "warnings": ["tiny_split_expected"]
}
```

Warning не блокирует урок: tiny data нужна для проверки контракта. Но в production такой
размер нельзя использовать для выбора модели или надежной оценки качества.

## Сломайте это

Проверьте семь поломок.

1. Скопируйте первую строку `ml_split_manifest.csv`. Check
   `manifest_schema_and_coverage` должен найти duplicate `snapshot_id`.
2. Удалите строку `S006` из manifest. Audit должен заблокировать missing eligible row.
3. Добавьте ineligible `S008` в validation. Manifest не должен расширять eligible
   population после problem framing.
4. Поменяйте `user_id` у `S009` на `U001` в snapshots и manifest. Check
   `groups_do_not_cross_splits` должен поймать train/test leakage.
5. Перенесите `S004` из train в test. Check
   `prediction_time_order_respects_holdout` должен заблокировать ранний test row.
6. Поставьте test row роль `model_selection_and_threshold_selection`. Test больше не
   финальная оценка.
7. Сделайте `label_window_complete = false` для `S010`. Строка с незавершенным horizon не
   может участвовать ни в train, ни в evaluation.

Строгий режим возвращает non-zero даже при warnings:

```bash
python outputs/ml_split_auditor.py \
  --spec ../data/tiny/problem_spec.json \
  --snapshots ../data/tiny/ml_scoring_snapshots.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --fail-on-warning
```

Он нужен, если pipeline не должен продолжать с tiny или underpowered split без review.

## Проверьте это

Behavioral tests запускаются так:

```bash
uv run --locked python -m unittest discover \
  -s phases/15-applied-machine-learning/02-data-splitting/tests -v
```

Они проверяют:

- валидный train/validation/test manifest;
- воспроизводимость `data/generate_data.py --check`;
- запуск `code/main.py` и запись `ml_split_report.json`;
- duplicate, missing и ineligible snapshot rows;
- group leakage по `user_id`;
- нарушение chronological holdout;
- попытку выбирать threshold на test;
- незавершенный label horizon;
- mismatch между manifest и immutable snapshot fields;
- отсутствие одного из трех split;
- испорченный `split_policy`;
- CLI exit codes и `--fail-on-warning`.

Интерпретация:

```text
valid = true
```

означает, что split contract готов для урока про метрики. Это не означает, что модель
обучена, threshold выбран, baseline побежден или test score можно смотреть много раз.

## Поставьте результат

Итоговый артефакт:

```text
outputs/ml_split_auditor.py
```

Он принимает `problem_spec.json`, scoring snapshots, labels и `ml_split_manifest.csv`, а
возвращает JSON-аудит split readiness.

`code/main.py` запускает аудитор на committed `tiny` profile и обновляет:

```text
outputs/ml_split_report.json
```

Следующий урок использует этот report как вход для metric policy: precision/recall,
threshold и business cost будут считаться уже по зафиксированным ролям validation и test.

## Упражнения

1. Добавьте четвертую неделю данных и решите, должна ли она стать test или новым
   production holdout.
2. Сделайте у одного пользователя два snapshot rows в разные недели и предложите честный
   group policy.
3. Перепишите manifest для случайного group split без time order и объясните, для каких
   задач он допустим, а для каких опасен.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Train split | Любые строки, на которых модель видит labels. | Только данные для fit preprocessing и estimator. |
| Validation split | Маленький test перед настоящим test. | Данные для выбора модели, hyperparameters и threshold. |
| Test split | Данные, где можно подбирать лучший threshold. | Однократная финальная оценка уже выбранного pipeline. |
| Group split | Приятная опция для красивого API. | Контракт, запрещающий одной сущности попадать в разные split. |
| Time holdout | Просто сортировка датафрейма. | Разделение, где будущие prediction times не помогают обучать прошлую оценку. |
| Split manifest | Служебный CSV. | Версионируемый артефакт, который фиксирует строку, split, роль и policy. |
| Test peeking | Смотреть test слишком часто. | Любое использование test для выбора модели, features, threshold или preprocessing. |
| Label horizon | Дата, когда есть поле target. | Минимальное будущее окно, после которого label считается наблюденным. |

## Дополнительное чтение

- [scikit-learn: Cross-validation iterators](https://scikit-learn.org/stable/modules/cross_validation.html) — прочитайте разделы про splitters и leakage; они показывают, почему обычная K-fold логика не всегда подходит для group/time задач.
- [scikit-learn: `GroupShuffleSplit`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html) — посмотрите API group-aware split; в уроке мы строим прозрачный manifest, а этот splitter пригодится позже для production-вариантов.
- [scikit-learn: `train_test_split`](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.train_test_split.html) — разберите, что делает случайный split и почему его нельзя механически применять к temporal churn snapshots.
- [scikit-learn: Common pitfalls and recommended practices](https://scikit-learn.org/stable/common_pitfalls.html) — повторите разделы про leakage и preprocessing; они напрямую связаны с тем, почему validation выбирает, а test только проверяет.
