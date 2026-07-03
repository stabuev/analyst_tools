# scikit-learn Pipeline

> Pipeline - это не удобная обертка вокруг модели, а исполняемый договор: какие шаги fit-ятся
> на train и какие шаги только применяются к validation/test.

**Тип:** Build  
**Треки:** ML  
**Пререквизиты:** `15-applied-machine-learning/04-preprocessing`  
**Время:** ~90 минут  
**Результат:** вы собираете scikit-learn `Pipeline`, где preprocessing и estimator обучаются
одним объектом, а predictions воспроизводимо строятся для validation/test.

## Цели обучения

- Объяснить, почему preprocessing должен жить внутри model pipeline, а не в отдельном
  "предварительном" скрипте.
- Собрать минимальный sklearn-compatible transformer с `fit`, `transform` и
  `get_feature_names_out`.
- Fit-ить `Pipeline` только на train split и использовать `predict_proba` только для
  validation/test.
- Сохранить serialized spec: шаги, estimator params, feature names и trace операций.
- Блокировать внешнюю preprocessed matrix как опасный вход для обучения модели.
- Подготовить артефакт к следующему уроку про `ColumnTransformer`.

## Проблема

В `15/04` мы сделали честный preprocessing contract: imputation, scaling и one-hot schema
fit-ятся только на train. Но если оставить этот код отдельным шагом, появляется новый класс
ошибок:

- analyst запускает preprocessing на full dataset, а потом обучает модель на "готовой"
  матрице;
- validation/test случайно участвуют в fit encoder-а или scaler-а;
- порядок колонок в saved matrix расходится с тем, что получает модель;
- в production вызывается модель без того же preprocessing state;
- audit видит только прогнозы, но не видит, какой объект и на каких rows был fit-нут.

В прикладном ML это особенно неприятно: метрики могут выглядеть лучше, чем в реальности, а
ошибка обнаружится только при переносе модели в scoring. Поэтому следующий шаг после
preprocessing contract - собрать preprocessing и estimator в один объект с проверяемым
порядком операций.

## Концепция

`Pipeline` в scikit-learn хранит последовательность named steps. Все промежуточные шаги
должны уметь `fit` и `transform`; последний шаг обычно является estimator-ом и умеет `fit`,
`predict` или `predict_proba`.

Для этого урока договор такой:

| Шаг | Что делает | На каких строках fit |
|---|---|---|
| `preprocess` | impute, scale, one-hot encode по `preprocessing_contract.json` | только train |
| `estimator` | `LogisticRegression` для churn probability | только train |
| `predict_proba` | строит probability scores | validation и test |

Важно различать два входа:

| Вход | Статус | Почему |
|---|---|---|
| Raw features + contract | Разрешен | Pipeline сам fit-ит preprocessing state на train. |
| External preprocessed matrix | Запрещен | Нельзя доказать, на каких данных были fit-нуты imputer, scaler и encoder. |

В tiny profile появился новый файл:

```text
phases/15-applied-machine-learning/data/tiny/pipeline_spec.json
```

В нем зафиксирован исполняемый контракт:

```json
{
  "pipeline_id": "trial-churn-sklearn-pipeline-v0",
  "fit_split": "train",
  "predict_splits": ["validation", "test"],
  "preprocessing_location": "inside_pipeline",
  "steps": ["preprocess", "estimator"]
}
```

Этот spec не заменяет sklearn-объект. Он делает объект проверяемым: тесты могут сравнить
заявленный порядок шагов, split boundaries, estimator params и выходные файлы.

## Соберите это

Начнем с минимального transformer-а. scikit-learn вызывает у промежуточных шагов `fit` на
обучении и `transform` при обучении и прогнозировании. Для нашего контракта это выглядит
так:

```python
class ContractPreprocessor:
    def fit(self, X, y=None):
        self.numeric_state_ = fit_numeric_state(X)
        self.categorical_state_ = fit_categorical_state(X)
        self.feature_names_out_ = build_feature_names(self.categorical_state_)
        return self

    def transform(self, X):
        numeric = transform_numeric(X, self.numeric_state_)
        categorical = transform_categorical(X, self.categorical_state_)
        return hstack(numeric, categorical)
```

Суффикс `_` у fitted attributes - соглашение sklearn: такие поля появляются после `fit`.
Это удобно для аудита. Если `transform` вызывается до `fit`, это ошибка.

Минимальная ручная схема выполнения:

```python
preprocess = ContractPreprocessor(contract)
X_train_transformed = preprocess.fit(train_raw_features).transform(train_raw_features)

estimator = LogisticRegression(solver="liblinear", C=1.0, l1_ratio=0.0, random_state=0)
estimator.fit(X_train_transformed, y_train)

X_validation_transformed = preprocess.transform(validation_raw_features)
validation_scores = estimator.predict_proba(X_validation_transformed)[:, 1]
```

Такой код уже держит правильный порядок, но его легко случайно разорвать. Например, можно
сохранить `X_train_transformed` в CSV, передать не тот файл или refit-нуть preprocess на
validation. Поэтому финальная сборка должна быть одним объектом:

```python
pipeline = Pipeline(
    steps=[
        ("preprocess", ContractPreprocessor(contract)),
        ("estimator", LogisticRegression(solver="liblinear", C=1.0, l1_ratio=0.0, random_state=0)),
    ]
)

pipeline.fit(X_train, y_train)
validation_scores = pipeline.predict_proba(X_validation)[:, 1]
test_scores = pipeline.predict_proba(X_test)[:, 1]
```

Теперь `Pipeline.fit` сам вызывает:

```text
preprocess.fit(train)
preprocess.transform(train)
estimator.fit(transformed_train, y_train)
```

А `Pipeline.predict_proba(validation)` вызывает:

```text
preprocess.transform(validation)
estimator.predict_proba(transformed_validation)
```

Никакого `fit` на validation/test в этой цепочке быть не должно.

## Используйте это

Урок поставляет CLI `pipeline-runner`:

```bash
python outputs/pipeline_runner.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --output outputs/pipeline_report.json \
  --predictions-output outputs/pipeline_predictions.csv \
  --serialized-spec-output outputs/pipeline_serialized_spec.json
```

Короткий пример запуска из `code/main.py`:

```bash
python code/main.py
```

Ожидаемый итог tiny profile:

```json
{
  "audit_valid": true,
  "pipeline_id": "trial-churn-sklearn-pipeline-v0",
  "sklearn_version": "1.9.0",
  "fit_split": "train",
  "fit_row_count": 4,
  "prediction_row_count": 8,
  "transformed_feature_count": 23,
  "validation_score_mean": 0.528642,
  "test_score_mean": 0.432755,
  "warnings": [
    "pipeline_unknown_categories_bucketed",
    "tiny_pipeline_training_sample_expected"
  ],
  "readiness_status": "ready_for_column_transformer_lesson"
}
```

Warnings здесь ожидаемые:

- `pipeline_unknown_categories_bucketed` - на validation/test есть новые категории
  `influencer` и `partnership`, они отправлены в `__unknown__`;
- `tiny_pipeline_training_sample_expected` - учебный train split содержит 4 строки, это
  нормально для tiny profile и недопустимо для production.

`pipeline_predictions.csv` содержит только validation/test:

```text
snapshot_id,pipeline_id,split,score,score_type,trained_on_split,generated_at
S005,trial-churn-sklearn-pipeline-v0,validation,0.501623,churn_risk_probability,train,2026-07-02T09:00:00+03:00
S006,trial-churn-sklearn-pipeline-v0,validation,0.302765,churn_risk_probability,train,2026-07-02T09:00:00+03:00
S007,trial-churn-sklearn-pipeline-v0,validation,0.781539,churn_risk_probability,train,2026-07-02T09:00:00+03:00
```

`pipeline_serialized_spec.json` фиксирует:

- версию sklearn;
- names и classes шагов;
- params `LogisticRegression`;
- `coef_shape` и `intercept`;
- итоговые transformed feature names;
- `fit_trace`.

Фрагмент trace:

```json
[
  {
    "event": "pipeline.fit",
    "split": "train",
    "snapshot_ids": ["S001", "S002", "S003", "S004"],
    "fits_preprocessing": true,
    "fits_estimator": true
  },
  {
    "event": "pipeline.predict_proba",
    "split": "validation",
    "fits_anything": false
  }
]
```

Именно этот trace связывает модельный результат с договором предыдущих уроков.

## Сломайте это

Попробуйте изменить `pipeline_spec.json`:

```json
{
  "fit_split": "validation"
}
```

CLI должен вернуть неуспех:

```text
pipeline_spec_declares_single_safe_pipeline
```

Другие failure modes:

| Поломка | Почему блокируется |
|---|---|
| `preprocessing_location = "external_preprocessed_matrix"` | Нельзя доказать train-only fit preprocessing. |
| `predict_splits = ["train", "validation"]` | Prediction report не должен смешивать train scores с validation/test audit. |
| Steps идут как `["estimator", "preprocess"]` | Estimator не должен получать raw categorical strings. |
| Нет `random_state` | Reproducibility contract не зафиксирован. |
| В raw features появилась `churned_14d` | Target leakage внутри feature table. |
| У train labels остался один класс | `LogisticRegression` не может обучить binary classifier. |

Для строгого CI можно включить предупреждения как hard gate:

```bash
python outputs/pipeline_runner.py \
  --spec ../data/tiny/problem_spec.json \
  --preprocessing-contract ../data/tiny/preprocessing_contract.json \
  --pipeline-spec ../data/tiny/pipeline_spec.json \
  --features ../data/tiny/ml_raw_features.csv \
  --labels ../data/tiny/ml_labels.csv \
  --manifest ../data/tiny/ml_split_manifest.csv \
  --fail-on-warning
```

На tiny profile команда завершится с non-zero exit code из-за ожидаемых warning-ов. В
production такое поведение полезно, если новая категория должна открывать расследование.

## Проверьте это

Запустите тесты урока:

```bash
python -m unittest discover -s phases/15-applied-machine-learning/05-pipeline/tests
```

Тесты проверяют:

- валидный Pipeline fit-ится на 4 train rows и строит 8 validation/test scores;
- serialized spec содержит steps `preprocess -> estimator`;
- `fit_trace` не содержит fit на validation/test;
- predictions имеют probability scores в `[0, 1]` и `trained_on_split = train`;
- preprocessing state совпадает с train-fitted state из `15/04`;
- unknown categories видны в warning-е;
- CLI возвращает non-zero для invalid spec и для `--fail-on-warning`.

Также полезно прогонять весь курс:

```bash
python scripts/validate_course.py
python scripts/run_lesson_tests.py
```

## Поставьте результат

Артефакт урока:

```text
outputs/pipeline_runner.py
```

Он нужен, когда у вас уже есть:

- problem spec;
- split manifest;
- preprocessing contract;
- raw feature table;
- labels;
- pipeline spec.

На выходе вы получаете:

```text
outputs/pipeline_report.json
outputs/pipeline_predictions.csv
outputs/pipeline_serialized_spec.json
```

`pipeline_report.json` - основной audit artifact. Его можно приложить к ML-ревью перед
следующими шагами: `ColumnTransformer`, linear baseline, threshold selection и model card.

## Упражнения

1. Добавьте в `pipeline_spec.json` новый параметр `max_iter = 500` и проверьте, что он
   появился в serialized spec.
2. Измените одну validation категорию на уже известную train категорию и убедитесь, что
   warning про unknown categories меняется.
3. Сделайте отдельный check, который запрещает `class_weight = "balanced"` без явного
   объяснения в spec.
4. Добавьте в prediction report колонку `model_family` и проверьте ее тестом.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| `Pipeline` | Просто способ писать меньше кода | Последовательность fitted steps с единым `fit` и prediction API. |
| Transformer | Любой preprocessing script | Объект с `fit` и `transform`, который хранит fitted state. |
| Estimator | Только финальная модель | Любой sklearn-объект с `fit`; в Pipeline последний шаг обычно предсказывает. |
| Serialized spec | Pickle модели | Читаемый audit report о версии, шагах, параметрах и feature names. |
| Fit trace | Лог выполнения для красоты | Проверка, какие splits обучали state, а какие только прогнозировались. |

## Дополнительное чтение

- [scikit-learn: Pipeline and composite estimators](https://scikit-learn.org/stable/modules/compose.html#pipeline) - прочитайте раздел про `Pipeline`, чтобы увидеть официальный порядок `fit`, `transform` и chaining.
- [sklearn.pipeline.Pipeline API](https://scikit-learn.org/stable/modules/generated/sklearn.pipeline.Pipeline.html) - проверьте параметры конструктора, named steps и методы prediction API.
- [scikit-learn: Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html) - особенно разделы про inconsistent preprocessing и data leakage.
- [sklearn.linear_model.LogisticRegression API](https://scikit-learn.org/stable/modules/generated/sklearn.linear_model.LogisticRegression.html) - посмотрите параметры solver, regularization и reproducibility для baseline classifier.
- [sklearn.compose.ColumnTransformer API](https://scikit-learn.org/stable/modules/generated/sklearn.compose.ColumnTransformer.html) - мост к следующему уроку, где routing numeric/categorical columns станет стандартным sklearn-объектом.
