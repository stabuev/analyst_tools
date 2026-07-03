# ColumnTransformer

> Если модель получает матрицу, у каждой колонки матрицы должен быть родословный маршрут:
> от raw feature до transformed feature name.

**Тип:** Build  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/05-pipeline`  
**Время:** ~75 минут  
**Результат:** вы маршрутизируете numeric, categorical и binary columns через
`ColumnTransformer`, проверяя dropped columns, transformed feature names и
unknown-category policy.

## Цели обучения

- Разделить raw feature columns на numeric, categorical и binary routes.
- Собрать `ColumnTransformer` внутри sklearn `Pipeline`.
- Сделать `remainder='drop'` осознанным audit decision, а не случайным поведением.
- Сохранить routing table: input column -> route -> transformer -> output feature count.
- Сохранить transformed feature schema через `get_feature_names_out()`.
- Проверить, что unknown categories не меняют schema validation/test.

## Проблема

В `15/05` мы собрали честный `Pipeline`: preprocessing и estimator fit-ятся одним объектом
на train. Но preprocessing был учебным `ContractPreprocessor`, который вручную знал порядок
numeric и categorical features.

Такой код помогает понять механизм, но в реальном sklearn baseline появляется другая
проблема: разные типы колонок требуют разных transformers.

Примеры:

- `sessions_14d`, `revenue_30d` нужно imputе-ить и scale-ить;
- `plan_id`, `platform`, `country` нужно превратить в one-hot columns;
- `had_support_ticket_14d` уже бинарный и не должен scale-иться как revenue;
- `snapshot_id` нужен для join/audit, но не должен попасть в модель;
- новая сырая колонка не должна молча пройти в estimator через `remainder='passthrough'`.

Если не сохранить карту маршрутизации, следующий урок про linear baseline становится
нечестным: коэффициент есть, а что именно он означает — неизвестно.

## Концепция

`ColumnTransformer` применяет разные transformers к разным подмножествам колонок и
склеивает результаты в одну feature matrix. Внутри полного ML pipeline это выглядит так:

```text
raw features
  -> ColumnTransformer
       numeric_median    -> SimpleImputer(median) + StandardScaler
       numeric_constant  -> SimpleImputer(constant=0) + StandardScaler
       categorical       -> UnknownCategoryBucketer + OneHotEncoder
       binary            -> SimpleImputer(constant=0)
       remainder         -> drop
  -> LogisticRegression
  -> predict_proba
```

В tiny profile урока есть новый файл:

```text
phases/15-applied-machine-learning/data/tiny/column_transformer_spec.json
```

Он фиксирует четыре routes:

| Route | Columns | Transformer |
|---|---|---|
| `numeric_median` | `sessions_14d`, `active_days_14d`, `days_since_signup` | `SimpleImputer(strategy="median")` + `StandardScaler` |
| `numeric_constant` | `support_tickets_14d`, `revenue_30d` | `SimpleImputer(strategy="constant", fill_value=0.0)` + `StandardScaler` |
| `categorical` | `plan_id`, `platform`, `country`, `acquisition_channel` | unknown bucket + `OneHotEncoder` |
| `binary` | `had_support_ticket_14d` | `SimpleImputer(strategy="constant", fill_value=0.0)` |

`snapshot_id` остается в raw table, но в route не входит. Он допустимо dropped, потому что
это identifier, а не model feature.

Главный инвариант:

```text
every non-key raw column must be explicitly routed
remainder must be drop
only approved non-feature columns may be dropped
```

## Соберите это

Сначала сделайте route table руками:

```python
routes = {
    "numeric_median": ["sessions_14d", "active_days_14d", "days_since_signup"],
    "numeric_constant": ["support_tickets_14d", "revenue_30d"],
    "categorical": ["plan_id", "platform", "country", "acquisition_channel"],
    "binary": ["had_support_ticket_14d"],
}
```

Проверьте, что каждая raw model feature попала ровно в один route:

```python
routed = [column for columns in routes.values() for column in columns]
duplicates = {column for column in routed if routed.count(column) > 1}
missing = set(raw_columns) - {"snapshot_id"} - set(routed)
```

Если `missing` не пустой, `ColumnTransformer(remainder="drop")` silently выбросит колонку.
Если `remainder="passthrough"`, наоборот, колонка может silently попасть в модель. Оба
варианта плохи без явного решения.

Минимальная sklearn-сборка:

```python
numeric_median = Pipeline(
    [
        ("imputer", SimpleImputer(strategy="median")),
        ("scaler", StandardScaler()),
    ]
)

numeric_constant = Pipeline(
    [
        ("imputer", SimpleImputer(strategy="constant", fill_value=0.0)),
        ("scaler", StandardScaler()),
    ]
)

categorical = Pipeline(
    [
        ("unknown_bucket", UnknownCategoryBucketer(...)),
        ("one_hot", OneHotEncoder(handle_unknown="error", sparse_output=False)),
    ]
)

preprocess = ColumnTransformer(
    transformers=[
        ("numeric_median", numeric_median, routes["numeric_median"]),
        ("numeric_constant", numeric_constant, routes["numeric_constant"]),
        ("categorical", categorical, routes["categorical"]),
        ("binary", SimpleImputer(strategy="constant", fill_value=0.0), routes["binary"]),
    ],
    remainder="drop",
    sparse_threshold=0.0,
    verbose_feature_names_out=True,
)
```

После `fit` обязательно сохраните:

```python
feature_names = preprocess.get_feature_names_out()
```

Для tiny profile первые и последние names такие:

```text
numeric_median__sessions_14d
numeric_median__active_days_14d
...
categorical__acquisition_channel___unknown__
binary__had_support_ticket_14d
```

Prefix route-а важен: он связывает future coefficient с исходной колонкой и
преобразованием.

## Используйте это

Урок поставляет CLI `column-transformer-auditor`:

```bash
python outputs/column_transformer_auditor.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --output outputs/column_transformer_report.json \
  --routing-output outputs/column_transformer_routing.csv \
  --feature-schema-output outputs/column_transformer_feature_schema.csv \
  --predictions-output outputs/column_transformer_predictions.csv \
  --serialized-spec-output outputs/column_transformer_serialized_spec.json
```

Короткий запуск:

```bash
python code/main.py
```

Ожидаемый итог:

```json
{
  "audit_valid": true,
  "column_transformer_id": "trial-churn-column-transformer-v0",
  "fit_split": "train",
  "fit_row_count": 4,
  "routed_input_feature_count": 10,
  "transformed_feature_count": 24,
  "prediction_row_count": 8,
  "dropped_columns": ["snapshot_id"],
  "validation_score_mean": 0.528213,
  "test_score_mean": 0.431829,
  "warnings": [
    "column_transformer_unknown_categories_bucketed",
    "tiny_column_transformer_training_sample_expected"
  ],
  "readiness_status": "ready_for_linear_baseline_lesson"
}
```

Артефакты:

| Файл | Зачем |
|---|---|
| `column_transformer_report.json` | Полный audit report. |
| `column_transformer_routing.csv` | Route table: input column, action, transformer, output count. |
| `column_transformer_feature_schema.csv` | 24 transformed features с source route/column/category. |
| `column_transformer_predictions.csv` | Validation/test probability scores. |
| `column_transformer_serialized_spec.json` | sklearn version, route state, fit trace, estimator params. |

## Сломайте это

Поменяйте:

```json
{
  "remainder": "passthrough"
}
```

Аудитор должен заблокировать spec:

```text
column_transformer_spec_declares_explicit_routes
```

Другие failure modes:

| Поломка | Почему это ошибка |
|---|---|
| Binary column не указана в route | Raw feature есть, но ColumnTransformer не знает, что с ней делать. |
| Одна колонка указана в двух routes | Estimator получит дублирующий сигнал. |
| `OneHotEncoder(handle_unknown="ignore")` без bucket-а | Unknown category станет all-zero без явного бизнес-смысла. |
| Новая raw column появилась в CSV | Она будет dropped или passthrough без ревью. |
| `churned_14d` появился в raw features | Target leakage. |
| `snapshot_id` passthrough в модель | Identifier может стать memorization signal. |

Для строгого режима:

```bash
python outputs/column_transformer_auditor.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --column-transformer-spec ../data/tiny/column_transformer_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --fail-on-warning
```

Tiny profile вернет non-zero exit code, потому что в validation/test есть новые
`acquisition_channel`: `influencer` и `partnership`. Они bucket-ятся в `__unknown__`, но
warning остается видимым.

## Проверьте это

Запустите тесты урока:

```bash
python -m unittest discover -s phases/15-applied-machine-learning/06-column-transformer/tests
```

Тесты проверяют:

- valid `ColumnTransformer` строит 24 transformed features из 10 routed input features;
- `remainder` равен `drop`, а dropped column только `snapshot_id`;
- routing table содержит numeric/categorical/binary routes;
- feature schema содержит `categorical__...___unknown__` columns;
- serialized spec хранит fitted route state и fit trace;
- prediction report содержит только validation/test scores;
- invalid routes, passthrough, missing binary column, target leakage и silent dropped
  columns блокируются.

## Поставьте результат

Именованный артефакт:

```text
outputs/column_transformer_auditor.py
```

Он является handoff к `15/07` «Линейные baseline». Следующий урок сможет взять:

```text
column_transformer_feature_schema.csv
column_transformer_serialized_spec.json
column_transformer_predictions.csv
```

и связать coefficients `LogisticRegression` с конкретными transformed feature names.

## Упражнения

1. Добавьте второй binary feature и обновите routing/feature schema tests.
2. Сделайте `remainder="passthrough"` и объясните, какая колонка могла бы попасть в модель.
3. Измените порядок categorical categories в spec и проверьте, как меняется feature schema.
4. Добавьте check, который запрещает one-hot category list без `__missing__`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| `ColumnTransformer` | Просто удобный wrapper для pandas columns | sklearn transformer, который применяет разные pipelines к разным колонкам и склеивает output. |
| Route | Неформальный список колонок | Явный contract: columns, transformer, action и output feature count. |
| `remainder` | Неважная настройка по умолчанию | Политика для колонок без route: drop, passthrough или transformer. |
| Feature schema | То же самое, что raw schema | Список transformed features после imputation/scaling/encoding. |
| Unknown bucket | Способ улучшить метрику | Стабильная schema-policy для категорий, не виденных в fit vocabulary. |

## Дополнительное чтение

- [sklearn.compose.ColumnTransformer API](https://scikit-learn.org/stable/modules/generated/sklearn.compose.ColumnTransformer.html) - параметры `transformers`, `remainder`, `verbose_feature_names_out` и `get_feature_names_out`.
- [scikit-learn: ColumnTransformer for heterogeneous data](https://scikit-learn.org/stable/modules/compose.html#columntransformer-for-heterogeneous-data) - как ColumnTransformer используется вместе с Pipeline для смешанных типов данных.
- [sklearn.preprocessing.OneHotEncoder API](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.OneHotEncoder.html) - `handle_unknown`, `sparse_output`, явные categories и generated feature names.
- [sklearn.impute.SimpleImputer API](https://scikit-learn.org/stable/modules/generated/sklearn.impute.SimpleImputer.html) - стратегии mean/median/most_frequent/constant и fitted `statistics_`.
- [sklearn.preprocessing.StandardScaler API](https://scikit-learn.org/stable/modules/generated/sklearn.preprocessing.StandardScaler.html) - train-fitted mean/scale и формула standard score.
