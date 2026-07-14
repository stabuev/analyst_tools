# Путеводитель по фазе 03: pandas

Отдельные уроки фазы намеренно компактны. Этот путеводитель связывает их в один рабочий
процесс и показывает, что новичок должен сделать самостоятельно до запуска готовых
артефактов.

## Сквозная задача

Нужно собрать таблицу заказов с grain «одна строка на заказ», добавить сумму позиций и
данные пользователя, посчитать сегментные метрики и передать результат вместе с
контрактом. Источники лежат в `phases/03-pandas/data/tiny/`:

- `users.csv`: одна строка на пользователя;
- `orders.csv`: одна строка на заказ;
- `order_items.csv`: одна строка на товарную позицию заказа.

Создайте рабочую копию:

```bash
mkdir -p work/phase-03
```

Ведите один файл `work/phase-03/pipeline.py`. Не копируйте туда целиком `outputs/`:
добавляйте только тот шаг, который можете объяснить.

## 1. Сначала форма и grain

```python
from pathlib import Path

import pandas as pd

DATA = Path("phases/03-pandas/data/tiny")
orders = pd.read_csv(DATA / "orders.csv")

print(orders.shape)
print(orders.columns.tolist())
print(orders.dtypes)
print(orders["order_id"].is_unique)
print(orders["order_id"].isna().sum())
```

До следующего шага ответьте письменно:

1. Что означает одна строка?
2. Какой столбец проверяет это утверждение?
3. Может ли технический индекс `0..n` заменить бизнес-ключ?
4. Какие дубликаты допустимы в `order_items`, но недопустимы в `orders`?

Сохраните проверку как функцию. Функция должна отклонять пропуски и дубликаты ключа, а не
только печатать их число.

## 2. Семантические типы раньше вычислений

`read_csv` угадывает физический dtype по текущему файлу. Бизнес-смысл нужно объявить
отдельно:

| Поле | Смысл | Политика пропусков |
|---|---|---|
| `order_id` | идентификатор заказа | запрещены |
| `amount` | денежная сумма | зависит от статуса и источника |
| `ordered_at` | момент события | ошибка parsing не заменяется текущей датой |
| `status` | ограниченная категория | неизвестное значение не становится `other` молча |

В рабочем файле создайте новые нормализованные столбцы, не перезаписывая raw до проверки:

```python
normalized = orders.assign(
    status_normalized=orders["status"].astype("string").str.strip().str.lower(),
    amount_numeric=pd.to_numeric(orders["amount"], errors="coerce"),
    ordered_at_utc=pd.to_datetime(orders["ordered_at"], utc=True, errors="coerce"),
)
```

Сравните число пропусков до и после преобразования. Новый `NA` означает строку, которую
парсер не смог интерпретировать; это диагностический сигнал, а не разрешение удалить её.

## 3. Маска — именованное правило

Не собирайте длинное выражение сразу. Назовите части:

```python
is_paid = normalized["status_normalized"].eq("paid")
has_amount = normalized["amount_numeric"].notna()
is_positive = normalized["amount_numeric"].gt(0)

paid = normalized.loc[is_paid & has_amount & is_positive].copy()
```

Проверьте каждую маску отдельно через `value_counts(dropna=False)`. Если в маске есть
`NA`, сформулируйте политику до `fillna`: исключить, остановить расчёт или отправить строку
в quarantine.

## 4. Преобразование и агрегат имеют разные grain

Производный столбец сохраняет число строк:

```python
items = pd.read_csv(DATA / "order_items.csv").assign(
    line_total=lambda frame: frame["quantity"] * frame["unit_price"]
)
```

Агрегация меняет grain:

```python
item_totals = (
    items.groupby("order_id", as_index=False, dropna=False)
    .agg(item_rows=("product_id", "size"), item_total=("line_total", "sum"))
)
```

Проверьте два независимых условия:

```python
assert item_totals["order_id"].is_unique
assert item_totals["item_total"].sum() == items["line_total"].sum()
```

Первое защищает grain результата, второе — control total. Одно не заменяет другое.

## 5. Join сначала моделируется на бумаге

Перед `merge` заполните таблицу:

| Левая таблица | Правая таблица | Ключ уникален слева | Ключ уникален справа | Ожидаемая cardinality |
|---|---|---|---|---|
| orders | item_totals | да | да | one-to-one |
| orders | users | нет по `user_id` | да | many-to-one |

Только затем выполняйте соединения:

```python
mart = (
    normalized.merge(
        item_totals,
        on="order_id",
        how="left",
        validate="one_to_one",
        indicator="items_match",
    )
    .merge(
        pd.read_csv(DATA / "users.csv"),
        on="user_id",
        how="left",
        validate="many_to_one",
        indicator="user_match",
    )
)
```

`indicator` не решает политику unmatched rows. Он делает проблему наблюдаемой. Проверьте,
что число строк mart совпало с orders и что общая сумма заказа не размножилась.

## 6. Reshape и chaining не должны скрывать проверки

Перед `pivot` докажите уникальность ключа будущей ячейки. Перед длинной цепочкой назовите
стадии и вставьте функции с узким контрактом:

```text
read -> validate grain -> normalize -> enrich -> aggregate detail -> join -> verify -> export
```

Хорошая цепочка читается слева направо, но важные проверки не обязаны помещаться в один
expression. Если промежуточный результат нужен для диагностики или handoff, дайте ему имя.

## 7. Финальная самопроверка

Перед экспортом подтвердите:

- `order_id` уникален и не содержит пропусков;
- строк столько же, сколько в исходной orders;
- сумма paid revenue совпадает с ручным tiny-контролем;
- unmatched users сохранены и имеют явный status;
- timestamp нормализован в UTC, а локальная дата строится только после выбора timezone;
- экспорт содержит schema version, source checksums и описание grain.

После самостоятельного pipeline сравните решения с уроками `03/01`–`03/11`, запустите их
тесты и пройдите квиз:

```bash
uv run --locked python scripts/run_quiz.py --phase 3 --stage post --limit 8
```

Фаза освоена, если вы можете получить правильный mart на tiny-данных и затем намеренно
сломать его дублем заказа, many-to-many join, неизвестной категорией и неразбираемой датой.
