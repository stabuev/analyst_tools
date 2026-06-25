# Обмен между pandas, Arrow и Polars

> Совпадение значений не означает совпадение schema, а Arrow-compatible API не означает
> автоматический zero-copy.

**Тип:** Case
**Треки:** Data, ML
**Пререквизиты:** `12-performance/09-streaming`
**Время:** ~75 минут
**Результат:** передает таблицу между pandas, PyArrow, DuckDB и Polars, проверяет
schema/null/timezone/category semantics, фиксирует копии и выбирает минимально дорогую
границу обмена.

## Цели обучения

- Задать канонический Arrow schema contract до конвертаций.
- Разделить value equivalence, logical type equivalence и exact schema equivalence.
- Проверить Arrow-backed pandas через `pd.ArrowDtype`.
- Найти re-encoding строк и ordered category при обмене с Polars.
- Зафиксировать материализацию результата и timezone policy в DuckDB.
- Выбрать один engine boundary вместо цепочки взаимных конвертаций.

## Проблема

Аналитический pipeline редко живет в одной библиотеке. Данные могут прийти как Arrow,
подготовиться в Polars, попасть в pandas-only API и агрегироваться SQL-запросом DuckDB.
Каждый переход выглядит простым:

```python
pandas_frame = arrow_table.to_pandas()
polars_frame = pl.from_arrow(arrow_table)
duckdb.sql("select * from arrow_table")
```

Но за коротким вызовом скрываются разные вопросы:

- сохранились ли exact decimal, null и timezone instants;
- осталась ли категория ordered;
- сохранились ли field nullability и schema metadata;
- переиспользованы buffers или данные перекодированы;
- материализован ли новый результат;
- зависит ли Arrow timestamp от timezone сессии.

Урок не ищет магический "самый быстрый DataFrame". Он строит evidence matrix для
конкретных границ.

## Концепция

У совместимости есть несколько уровней:

| Уровень | Вопрос |
|---|---|
| Values | Совпадают ли бизнес-значения после round-trip? |
| Null semantics | Остались ли null в тех же колонках и строках? |
| Logical types | Остались ли decimal, timestamp, integer и category теми же сущностями? |
| Exact Arrow schema | Совпали ли type parameters, nullability, field/schema metadata? |
| Physical reuse | Используются ли те же buffers в памяти? |

Граница может сохранить values, но изменить schema:

```text
string -> large_string
dictionary<int8, string, ordered=true>
    -> dictionary<uint32, large_string, ordered=false>
```

Такой переход не обязательно плох. Он становится опасным, когда drift не измерен, а
downstream полагается на исходный contract.

## Соберите это

Артефакт создает каноническую `pyarrow.Table` с намеренно сложными полями:

- non-null primary key;
- `timestamp[us, tz=UTC]`;
- ordered dictionary `plan_tier`;
- integer cents;
- `decimal128(14, 2)`;
- nullable integer и string;
- field metadata и schema metadata;
- несколько chunks.

### Шаг 1. Зафиксируйте Arrow contract

```python
source = build_canonical_arrow_table(rows=24, chunk_size=8, seed=42)
```

`plan_tier` содержит порядок:

```text
trial < basic < plus < pro
```

Он записан и как `dictionary(..., ordered=True)`, и как field metadata. Это позволяет
увидеть разницу между сохранением строковых значений и сохранением бизнес-порядка.

### Шаг 2. Передайте Arrow в pandas

```python
frame = source.to_pandas(types_mapper=pd.ArrowDtype)
```

Без `types_mapper` часть колонок может перейти в NumPy/object representation. В
артефакте каждая pandas dtype обязана быть `pd.ArrowDtype`.

Для проверки storage вызывается `__arrow_array__()` у extension array. Адреса buffers
сравниваются с канонической таблицей. На установленной версии все колонки используют
исходные Arrow buffers.

Но обратная сборка:

```python
pa.Table.from_pandas(frame, preserve_index=False)
```

не сохраняет полный schema contract:

- non-null fields становятся nullable;
- исходные field/schema metadata заменяются pandas metadata.

Values и exact Arrow types при этом сохраняются. Поэтому перед persistence нужно
повторно применить канонический schema или валидировать его явно.

### Шаг 3. Передайте Arrow в Polars

```python
polars_frame = pl.from_arrow(source, rechunk=False)
returned = polars_frame.to_arrow(
    compat_level=pl.CompatLevel.oldest()
)
```

Audit показывает:

- integer, decimal и timestamp buffers переиспользуются;
- string representation меняется на `large_string`;
- dictionary indices меняются с `int8` на `uint32`;
- category values сохраняются;
- `ordered=True` превращается в `ordered=False`.

Polars не "ломает значения". Но category ordering нельзя считать автоматически
сохраненным бизнес-контрактом.

### Шаг 4. Передайте Arrow в DuckDB

```python
connection.execute("SET TimeZone = 'UTC'")
connection.register("canonical_arrow", source)
returned = connection.execute("SELECT ...").to_arrow_table()
```

DuckDB читает Arrow relation, но Arrow result query является новым материализованным
выходом. В audit исходные buffers не переиспользуются.

Кроме того:

- ordered dictionary декодируется в string;
- field/schema metadata не переносится;
- decimal и null values сохраняются;
- timezone output зависит от `TimeZone` сессии.

Counterexample выполняет тот же запрос с `TimeZone=Europe/Moscow`. Абсолютные instants
совпадают, но тип меняется:

```text
timestamp[us, tz=UTC]
-> timestamp[us, tz=Europe/Moscow]
```

### Шаг 5. Постройте matrix

Каждая строка `interoperability-matrix.csv` содержит:

- API границы;
- classification;
- совпадение values и null counts;
- logical и exact type checks;
- nullability и metadata checks;
- category values и ordering;
- колонки с buffer reuse и без него.

Главный принцип: `values_preserved_with_schema_drift` лучше, чем неявное "вроде
совместимо", но требует documented controls.

## Используйте это

Запустите пример:

```bash
uv run --locked python phases/12-performance/10-interoperability/code/main.py
```

Запустите CLI:

```bash
uv run --locked python phases/12-performance/10-interoperability/outputs/interoperability_audit.py \
  --rows 24 \
  --chunk-size 8 \
  --output-dir /tmp/interoperability-audit
```

Пакет содержит:

- `canonical-input.arrow`;
- `pandas-roundtrip.arrow`;
- `polars-roundtrip.arrow`;
- `duckdb-utc-output.arrow`;
- `interoperability-matrix.csv`;
- `conversion-audit.json`;
- `engine-boundary-decision.md`;
- `report.json`.

Для данного pipeline выбран путь:

```text
PyArrow -> Polars -> PyArrow
```

Причины:

1. pipeline остается columnar;
2. пересекается одна граница движка;
3. reuse primitive/decimal/timestamp buffers подтвержден;
4. re-encoding строк и categories явно виден;
5. canonical Arrow schema можно восстановить перед публикацией.

Это не утверждение, что Polars всегда быстрее. Выбор относится к стоимости обмена в
этом сценарии; вычислительную скорость сравнивает следующий интеграционный benchmark.

## Сломайте это

### Уберите `pd.ArrowDtype`

Проверьте, какие колонки становятся object или NumPy-backed. Значения могут совпасть,
но Arrow storage и nullable semantics изменятся.

### Сравнивайте только `to_pylist()`

Так вы пропустите потерю ordered category, field nullability и metadata.

### Используйте category codes как business key

Polars переупаковывает dictionary indices. Код `0` не является переносимым значением
категории; контрактом является label и отдельно заданный порядок.

### Не задавайте DuckDB timezone

Один и тот же timestamp получит Arrow timezone текущей сессии. Абсолютный момент
останется тем же, но exact schema и отображение изменятся.

### Делайте ping-pong conversion

Цепочка `Arrow -> pandas -> Polars -> DuckDB -> pandas` создает больше границ, чем
задач. Выберите один compute engine и экспортируйте уменьшенный результат.

## Проверьте это

Точечные тесты:

```bash
uv run --locked python -m unittest discover \
  -s phases/12-performance/10-interoperability/tests -v
```

Контракт отчета:

- все четыре границы сохраняют values и null counts;
- pandas использует Arrow-backed dtypes и исходные buffers;
- pandas round-trip показывает metadata/nullability drift;
- Polars сохраняет category values, но теряет ordered metadata;
- Polars reuse для numeric/decimal/timestamp подтвержден адресами;
- DuckDB декодирует dictionary и материализует Arrow output;
- timezone counterexample меняет label, но не instant;
- решение использует одну границу вычислительного движка.

## Поставьте результат

Именованный артефакт - `interoperability-audit`:

```bash
uv run --locked python phases/12-performance/10-interoperability/outputs/interoperability_audit.py \
  --rows 24 \
  --chunk-size 8 \
  --output-dir /tmp/interoperability-audit
```

Используйте его перед добавлением новой engine boundary:

1. задайте канонический schema;
2. добавьте сложные типы и null;
3. сравните values отдельно от schema;
4. измерьте buffers там, где reuse можно наблюдать;
5. классифицируйте drift;
6. оставьте один compute engine между input и output.

## Упражнения

1. Добавьте `duration[us]` и проверьте поведение каждой границы.
2. Уберите `ordered=True` у `plan_tier` и объясните, какой risk исчез, а какой остается.
3. Добавьте прямую границу `Polars -> pandas(use_pyarrow_extension_array=True)` и
   отделите semantic check от утверждения о direct buffer reuse.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Arrow-backed pandas | Любой pandas DataFrame из Arrow | Extension arrays с `pd.ArrowDtype`, сохраняющие Arrow storage |
| Value equivalence | Полная совместимость | Совпадение нормализованных бизнес-значений |
| Exact schema | Только имена и dtype strings | Types, parameters, nullability, field metadata и schema metadata |
| Buffer reuse | API называется zero-copy | Наблюдаемое совпадение адресов buffers для конкретной границы |
| Ordered category | Порядок dictionary codes | Отдельная семантика порядка labels, которую движок может не сохранить |
| Engine boundary | Один вызов conversion | Место смены representation/runtime с возможной копией и semantic drift |

## Дополнительное чтение

- [PyArrow: pandas integration](https://arrow.apache.org/docs/python/pandas.html) - изучите ArrowDtype, nullable conversion и условия zero-copy.
- [pandas: PyArrow functionality](https://pandas.pydata.org/docs/user_guide/pyarrow.html) - разберите Arrow-backed arrays, dtype inference и ограничения pandas operations.
- [Polars: Arrow interoperability](https://docs.pola.rs/user-guide/misc/arrow/) - прочитайте условия mostly zero-copy и исключения для categorical/string representation.
- [DuckDB: SQL on Arrow](https://duckdb.org/docs/stable/guides/python/sql_on_arrow) - посмотрите регистрацию Arrow relation и возврат результатов через Arrow API.
