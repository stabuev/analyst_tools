# Предобработка как часть модели

> Предобработка не является подготовкой "до модели": это обучаемая часть модели со своим
> fit-state и теми же правилами train/validation/test.

**Тип:** Build  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/03-metrics`  
**Время:** ~75 минут  
**Результат:** вы разделяете raw features, train-fitted preprocessing и transformed
feature matrix, блокируя fit-before-split, silent missing-value policy и unknown
categories.

## Цели обучения

- Отличить raw feature table от transformed feature matrix.
- Fit-ить imputation, scaling и categorical vocabulary только на train split.
- Применять один и тот же preprocessing state к train, validation и test через `transform`.
- Сделать missing values явной частью контракта, а не побочным эффектом библиотеки.
- Обнаружить unknown categories на validation/test и обработать их заранее объявленной
  политикой.
- Подготовить стабильный feature schema для следующего урока про `Pipeline`.

## Проблема

После `15/03` у нас есть supervised ML-задача, split manifest и metric policy. Следующий
шаг кажется бытовым: "почистим фичи и обучим модель". Именно здесь часто появляется
утечка.

Примеры плохих решений:

- посчитать медиану для imputation на всех строках сразу;
- обучить scaler на train + validation, потому что так "стабильнее";
- сделать one-hot отдельно на каждом split и получить разный набор колонок;
- проигнорировать новую категорию на validation/test и не заметить, что сигнал пропал;
- удалить строки с пропусками после split и незаметно изменить population.

Для churn-risk задачи это ломает весь договор предыдущих уроков. Validation перестает быть
model-selection split, test перестает быть финальной проверкой, а будущая модель получает
матрицу, которую невозможно повторить в production scoring.

## Концепция

Предобработка в ML состоит из трех разных объектов:

| Объект | Что содержит | Что нельзя делать |
|---|---|---|
| Raw features | Исходные признаки на grain `snapshot_id` | Смешивать с target, score, split role или post-prediction columns. |
| Preprocessing state | Imputation values, scaler statistics, categories, feature order | Fit-ить на validation/test или full dataset. |
| Transformed matrix | Только числовые features в стабильном порядке | Менять schema между train, validation и test. |

Главное правило:

```text
fit preprocessing only on train
transform train, validation, test with the fitted state
```

В tiny profile урока есть новая таблица:

```text
phases/15-applied-machine-learning/data/tiny/ml_raw_features.csv
```

Она содержит пять numeric features и четыре categorical features. В ней специально есть
дефекты:

- missing `sessions_14d` на train и test;
- missing `active_days_14d` на validation;
- missing `revenue_30d` на train;
- missing `support_tickets_14d` на test;
- новая категория `influencer` на validation;
- новая категория `partnership` на test;
- missing categorical value в `acquisition_channel`.

Контракт лежит рядом:

```text
phases/15-applied-machine-learning/data/tiny/preprocessing_contract.json
```

В нем зафиксировано:

```json
{
  "fit_split": "train",
  "missing_value_policy": "explicit_impute",
  "unknown_category_policy": "bucket",
  "unknown_category_bucket": "__unknown__",
  "missing_category_bucket": "__missing__"
}
```

Это означает: новые категории не исчезают молча. Они попадают в отдельный bucket, который
виден в report и в transformed feature names.

## Соберите это

Начните с ручной train-fitted imputation. Для numeric feature:

```python
def fit_median_imputer(train_rows, column):
    observed = sorted(float(row[column]) for row in train_rows if row[column] != "")
    middle = len(observed) // 2
    if len(observed) % 2:
        return observed[middle]
    return (observed[middle - 1] + observed[middle]) / 2
```

Для `sessions_14d` train values такие:

| Snapshot | Raw value |
|---|---:|
| `S001` | 8 |
| `S002` | 4 |
| `S003` | 2 |
| `S004` | missing |

Train median равна `4.0`. После imputation train vector становится:

```text
[8, 4, 2, 4]
```

`StandardScaler`-style statistics тоже считаются на train:

```python
def fit_standard_scaler(values):
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    scale = variance ** 0.5 or 1.0
    return {"mean": mean, "scale": scale}
```

Для `sessions_14d`:

```json
{
  "fill_value": 4.0,
  "mean": 4.5,
  "scale": 2.179449
}
```

Теперь transform:

```python
value = fill_value if raw_value == "" else float(raw_value)
transformed = (value - mean) / scale
```

Для `S004` missing sessions превращается в:

```text
(4.0 - 4.5) / 2.179449 = -0.229416
```

Categorical features требуют похожего fit-state. На train для `acquisition_channel`
видны только:

```text
organic, paid_search, referral
```

Но contract заранее добавляет служебные buckets:

```text
organic
paid_search
referral
__missing__
__unknown__
```

Validation value `influencer` не появлялась на train, поэтому transform не создает новую
колонку `cat__acquisition_channel=influencer`. Он ставит `1.0` в:

```text
cat__acquisition_channel=__unknown__
```

Так feature schema остается стабильной.

## Используйте это

Урок поставляет CLI `preprocessing-contract-checker`:

```bash
python outputs/preprocessing_contract_checker.py \
  --spec ../data/tiny/problem_spec.json \
  --contract ../data/tiny/preprocessing_contract.json \
  --features ../data/tiny/ml_raw_features.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --output outputs/preprocessing_report.json \
  --matrix-output outputs/preprocessed_feature_matrix.csv \
  --state-output outputs/preprocessing_state.json
```

Отчет содержит:

- `preprocessing_state`: imputation values, scaler statistics, categories и feature order;
- `transformed_matrix_preview`: первые строки numeric matrix;
- `unknown_category_events`: новые категории, найденные вне train;
- `checks`: gates для problem alignment, split roles, feature population, fit-on-train,
  missing policy, unknown category policy и matrix schema.

Короткий итог tiny profile:

```json
{
  "fit_split": "train",
  "fit_row_count": 4,
  "transformed_row_count": 12,
  "transformed_feature_count": 23,
  "unknown_category_events": 2,
  "warnings": [
    "unknown_categories_bucketed",
    "tiny_preprocessing_sample_expected"
  ],
  "readiness_status": "ready_for_pipeline_lesson"
}
```

В production scikit-learn этот договор обычно собирают из `SimpleImputer`,
`StandardScaler`, `OneHotEncoder`, `ColumnTransformer` и `Pipeline`. Важна не магия
классов, а тот же порядок операций: `fit` на train, затем `transform` для validation,
test и production scoring. Следующий урок превратит этот контракт в настоящий
scikit-learn `Pipeline`.

## Сломайте это

Проверьте типовые поломки.

1. Поставьте `fit_split = "validation"` в `preprocessing_contract.json`. Audit должен
   заблокировать preprocessing: statistics нельзя учить на validation.
2. Удалите `test` из `transform_splits`. Contract больше не описывает финальную проверку.
3. Удалите `impute` у `sessions_14d`. Missing value policy стала неявной.
4. Поставьте `handle_unknown = "ignore"` для `acquisition_channel`. Новая категория
   `influencer` будет скрыта вместо явного bucket.
5. Добавьте колонку `churned_14d` в raw features. Target не может быть feature.
6. Удалите строку `S006` из `ml_raw_features.csv`. Feature table больше не покрывает
   manifest population.
7. Добавьте строку `S008`. Ineligible snapshot не должен появляться в transformed matrix.

Строгий режим возвращает non-zero даже при warnings:

```bash
python outputs/preprocessing_contract_checker.py \
  --spec ../data/tiny/problem_spec.json \
  --contract ../data/tiny/preprocessing_contract.json \
  --features ../data/tiny/ml_raw_features.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --fail-on-warning
```

В tiny profile warnings ожидаемы: мало train rows для production statistics, а новые
категории специально оставлены как учебный edge case.

## Проверьте это

Behavioral tests запускаются так:

```bash
uv run --locked python -m unittest discover \
  -s phases/15-applied-machine-learning/04-preprocessing/tests -v
```

Они проверяют:

- train-only fit state;
- numeric imputation и StandardScaler-style statistics;
- categorical one-hot schema с `__missing__` и `__unknown__`;
- transformed matrix на 12 rows и 23 features;
- отсутствие raw target/score/split columns в feature table;
- блокировку missing row, duplicate row и extra ineligible row;
- запрет fit на validation/test;
- запрет silent missing-value policy и silent unknown-category handling;
- CLI exit codes и `--fail-on-warning`;
- воспроизводимость `data/generate_data.py --check`.

Интерпретация:

```text
valid = true
```

означает, что preprocessing contract готов к превращению в Pipeline. Это еще не означает,
что preprocessing оптимален для production модели или что chosen features достаточно
хороши. Это означает, что state воспроизводим и не подглядывает в validation/test.

## Поставьте результат

Итоговый артефакт:

```text
outputs/preprocessing_contract_checker.py
```

Он принимает problem spec, preprocessing contract, raw feature table и split manifest, а
возвращает JSON-аудит preprocessing state.

`code/main.py` запускает артефакт на committed tiny profile и обновляет:

```text
outputs/preprocessing_report.json
outputs/preprocessing_state.json
outputs/preprocessed_feature_matrix.csv
```

Следующий урок использует эти файлы как мост: та же логика должна жить внутри одного
scikit-learn `Pipeline`, чтобы preprocessing и estimator fit-ились одним объектом.

## Упражнения

1. Измените imputation strategy для `sessions_14d` с `median` на `constant = 0` и
   объясните, какие transformed values изменились.
2. Добавьте новую test category `enterprise_partner` в `acquisition_channel` и проверьте,
   что она не создает новую колонку.
3. Удалите `__unknown__` bucket из contract и сформулируйте, какой production incident
   это могло бы вызвать.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Raw features | Это уже матрица для модели. | Таблица исходных признаков на prediction grain до обучаемых преобразований. |
| Preprocessing state | Временная техническая деталь. | Train-fitted параметры transform: fill values, means, scales, categories и order. |
| Fit vs transform | Два названия одного действия. | `fit` учит параметры на train, `transform` применяет уже выученные параметры. |
| Imputation | Просто замена пустот на среднее. | Явная политика обработки missingness, fit-имая только на разрешенном split. |
| Unknown category | Ошибка данных, которую всегда надо удалить. | Категория, не виденная на train; она требует заранее объявленной политики. |
| Feature schema | Список raw columns. | Итоговый порядок числовых transformed columns, который увидит estimator. |

## Дополнительное чтение

- [scikit-learn: Common pitfalls and recommended practices](https://scikit-learn.org/stable/common_pitfalls.html) — прочитайте разделы про inconsistent preprocessing и data leakage: это ровно failure mode, который предотвращает урок.
- [scikit-learn: Preprocessing data](https://scikit-learn.org/stable/modules/preprocessing.html) — раздел про standardization и transformer API: какие statistics учит scaler и почему их применяют к новым данным тем же объектом.
- [scikit-learn: Imputation of missing values](https://scikit-learn.org/stable/modules/impute.html) — `SimpleImputer`, стратегии mean/median/most frequent/constant и почему imputation должна быть частью pipeline.
- [scikit-learn: `OneHotEncoder`](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.OneHotEncoder.html) — параметры `handle_unknown`, `sparse_output` и `categories_`; особенно важно понять, что происходит с unseen categories.
- [scikit-learn: ColumnTransformer for heterogeneous data](https://scikit-learn.org/stable/modules/compose.html#columntransformer-for-heterogeneous-data) — как production API маршрутизирует numeric и categorical columns через разные transformations.
