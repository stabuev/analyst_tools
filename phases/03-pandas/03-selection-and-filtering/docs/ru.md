# Выбор строк и столбцов

> Фильтр определяет не только строки результата, но и популяцию, о которой будет сделан
> вывод. Поэтому сначала постройте и проверьте nullable-маску, а затем явно решите судьбу
> `NA`.

**Тип:** Build
**Треки:** Core
**Пререквизиты:** 03/02
**Время:** ~90 минут
**Результат:** выбирает строки и столбцы по меткам или позициям, строит согласованную с
индексом nullable-маску, явно разрешает `NA` и изменяет выбранные строки одним
`loc`-присваиванием.

## Цели обучения

После урока вы сможете:

- предсказывать тип и форму результата при выборе одного или нескольких столбцов;
- различать выбор по меткам через `loc` и по позициям через `iloc`;
- строить именованные условия и объединять их операторами `&`, `|` и `~`;
- объяснять результаты `True`, `False` и `pd.NA` в составной nullable-маске;
- проверять dtype и индекс маски до применения к `DataFrame`;
- выбирать явную политику для неизвестного результата условия;
- выбирать строки и нужные столбцы одной операцией `loc`;
- изменять выбранные строки одним присваиванием без chained assignment.

## На что опирается урок

В `02/04` вы уже строили булеву маску NumPy, проверяли её форму и объединяли условия
через `&`, `|` и `~`. Там маска относилась к позициям массива.

В `03/01` появились маркированные оси pandas. Вы увидели, что `Series` хранит индекс, а
операции выравнивают значения по меткам. В `03/02` сравнение nullable-столбца дало уже
не обычные два, а три возможных результата:

```text
известное значение проходит условие     -> True
известное значение не проходит          -> False
значение неизвестно                      -> pd.NA
```

Теперь эти знания соединяются:

```text
03/01: к какой строке относится значение?
03/02: известно ли значение и допустимо ли оно?
03/03: проходит ли строка условие и что делать, если ответ неизвестен?
03/04: как построить новые столбцы для тех же строк?
```

Урок не занимается повторной очисткой данных. Он принимает уже проверенный и
типизированный `DataFrame` из `03/02`. Нормализация предметных строк и категорий будет
систематически разобрана в `03/09`.

## Проблема

Нужно выбрать оплаченные заказы с суммой не меньше 70 единиц. Рассмотрим пять строк:

| Метка строки | `order_id` | `status` | `amount` |
|---|---|---|---:|
| `row-a` | `O1001` | `paid` | `120.0` |
| `row-b` | `O1002` | `paid` | пропуск |
| `row-c` | `O1003` | `refunded` | `80.0` |
| `row-d` | `O1004` | пропуск | `100.0` |
| `row-e` | `O1005` | `refunded` | пропуск |

На первый взгляд достаточно написать:

```python
mask = status.eq("paid") & amount.ge(70)
```

Но итоговая маска содержит три состояния:

| Метка | Статус подходит | Сумма подходит | Итог |
|---|---:|---:|---:|
| `row-a` | `True` | `True` | `True` |
| `row-b` | `True` | `NA` | `NA` |
| `row-c` | `False` | `True` | `False` |
| `row-d` | `NA` | `True` | `NA` |
| `row-e` | `False` | `NA` | `False` |

Строки `row-b` и `row-d` нельзя честно назвать ни прошедшими, ни не прошедшими условие:
для ответа не хватает факта. А `row-e` исключается определённо: даже неизвестная сумма
не изменит того, что заказ не имеет требуемого статуса.

Если сразу выполнить `mask.fillna(False)`, строки `row-b` и `row-d` внешне сольются с
обычными отказами. Аналитик потеряет количество неизвестных решений и не заметит, что
состав популяции зависит от качества данных.

Цена ошибки распространяется дальше:

- изменится число заказов в знаменателе;
- изменится сумма и среднее выбранной группы;
- часть клиентов исчезнет из анализа без объяснения;
- следующий расчёт останется технически корректным, но ответит на другой вопрос.

Поэтому фильтр — это проверяемый контракт популяции, а не короткая строка синтаксиса.
Популяцией здесь называется набор строк, о котором после фильтра будет сделан вывод.

## Концепция

### Выбор должен отвечать на два вопроса

Любая операция выборки задаёт:

1. **какие строки** остаются;
2. **какие столбцы** нужны в результате.

Лучше формулировать это до кода:

```text
строки: status == "paid" AND amount >= 70
столбцы: order_id, status, amount
```

Так легче проверить и популяцию, и структуру результата. Выражение `orders[mask]`
отвечает только на первый вопрос и переносит все столбцы, в том числе случайно лишние.

### Один столбец и таблица из одного столбца — разные результаты

Из `03/01` известно, что один столбец `DataFrame` является `Series`:

```python
amount = orders["amount"]
```

У результата одна ось и форма `(число строк,)`. Двойные скобки оставляют двумерную
таблицу:

```python
amount_table = orders[["amount"]]
```

У неё две оси и форма `(число строк, 1)`.

| Выражение | Тип результата | Число осей |
|---|---|---:|
| `orders["amount"]` | `Series` | 1 |
| `orders[["amount"]]` | `DataFrame` | 2 |
| `orders[["order_id", "amount"]]` | `DataFrame` | 2 |

Это не косметическое различие. Функция, ожидающая таблицу, может проверять столбцы и их
порядок; `Series` такого контракта не содержит.

### `loc` выбирает по меткам, `iloc` — по позициям

Оба индексатора принимают две координаты:

```text
frame.loc[строки_по_меткам, столбцы_по_именам]
frame.iloc[позиции_строк, позиции_столбцов]
```

Например:

```python
orders.loc["row-b", "amount"]
orders.iloc[1, 2]
```

Если `row-b` действительно является второй строкой, оба выражения вернут одно значение.
Но их обещания разные:

- `loc` говорит «строка с меткой `row-b`, столбец `amount`»;
- `iloc` говорит «вторая строка, третий столбец в текущем порядке».

После сортировки или изменения порядка строк позиция может измениться, а метка останется
с сущностью. Поэтому предметные правила обычно читаемее через `loc`; `iloc` нужен, когда
задача действительно позиционная.

Индексированная булева `Series` относится к миру меток, поэтому её применяют через
`loc`. Передача такой `Series` в `iloc` завершается ошибкой: позиционный индексатор не
использует её индекс для выравнивания.

### У срезов `loc` и `iloc` разные правые границы

Позиционный срез наследует правило Python: правая граница не включается.

```python
orders.iloc[1:4]
```

Он берёт позиции `1`, `2`, `3`.

Срез `loc` по меткам включает обе границы:

```python
orders.loc["row-b":"row-d"]
```

Он берёт `row-b`, `row-c` и `row-d`, если индекс упорядочен соответствующим образом.
Это полезный API-контракт, но он способен дать ошибку на одну строку, если механически
перенести привычку из Python-срезов.

В этом уроке срезы нужны только для понимания границы `loc`/`iloc`. Сложные правила
сортировки и MultiIndex не входят в основной маршрут.

### Булева маска pandas является маркированной `Series`

В NumPy маска связывалась с данными общей позицией. В pandas у неё есть ещё и индекс:

```text
orders.index: row-a  row-b  row-c  row-d  row-e
mask.index:   row-a  row-b  row-c  row-d  row-e
mask.values:   True    NA   False    NA   False
```

Pandas умеет выравнивать булеву `Series` по меткам перед `loc`. Это продолжение label
alignment из `03/01`. Но автоматическое выравнивание не доказывает, что маска построена
из нужной таблицы: другая таблица может случайно иметь похожие метки.

Поэтому строгий артефакт урока требует:

- маска является именно `Series`, а не безымянным списком;
- dtype относится к булевым: например, `bool`, nullable `boolean` или
  `bool[pyarrow]`;
- индекс таблицы и маски уникален;
- метки и их порядок совпадают точно.

Pandas допускает более широкое поведение, а артефакт намеренно выбирает более строгий
контракт для аналитического pipeline.

### Условия строятся отдельно и получают имена

Предикат — это условие, которое возвращает одно логическое решение для каждой строки.
Вместо одного длинного выражения полезно дать каждому такому условию предметное имя.

Сравнение `Series` выполняется поэлементно и сохраняет индекс:

```python
is_paid = orders["status"].eq("paid")
amount_is_large = orders["amount"].ge(70)
```

Имена нужны не ради многословия. Они позволяют отдельно проверить:

- правильный столбец;
- правильную границу;
- dtype результата;
- число `True`, `False`, `NA`;
- строки, в которых условие неизвестно.

Только затем условия объединяются:

```python
mask = is_paid & amount_is_large
```

Для поэлементной логики используются:

- `&` — И;
- `|` — ИЛИ;
- `~` — НЕ.

Операторы Python `and`, `or`, `not` ожидают одно логическое значение и не могут решить,
что означает истинность целой `Series`. Скобки обязательны вокруг сравнений, записанных
операторами `==`, `>=` и подобными:

```python
mask = (
    (orders["status"] == "paid")
    & (orders["amount"] >= 70)
)
```

Уже построенные именованные `is_paid` и `amount_is_large` можно соединять без ещё одной
пары скобок: `is_paid & amount_is_large`. Методы `.eq()` и `.ge()` также сначала
возвращают готовые `Series`, поэтому компактная запись с ними не страдает от приоритета
операторов. Именованные предикаты обычно понятнее обоих вариантов.

### Не всякая операция сама сохраняет неизвестность

Сравнение через `.eq("paid")` оставляет `pd.NA` неизвестным. У `.isin({"paid"})` другой
технический контракт: пропуск не является элементом переданного множества, поэтому
метод возвращает для него `False`.

Но технический ответ «маркер отсутствия не лежит в множестве» не всегда совпадает с
предметным ответом «мы не знаем статус заказа». Если по смыслу отсутствие статуса должно
оставить решение неизвестным, восстановите его явно:

```python
status = orders["status"]
is_allowed = status.isin({"paid", "refunded"}).astype("boolean")
is_allowed = is_allowed.mask(status.isna(), pd.NA)
```

Именно такую политику использует `build_order_mask`. Это осознанное решение контракта,
а не универсальное исправление `.isin()`.

### Nullable-логика не равна автоматическому `fillna(False)`

Для AND достаточно запомнить три ключевые строки:

| Выражение | Результат | Почему |
|---|---:|---|
| `True & NA` | `NA` | ответ зависит от неизвестного условия |
| `False & NA` | `False` | одно ложное условие уже исключает строку |
| `NA & NA` | `NA` | ни одно условие не определено |

Для OR логика симметрична по смыслу:

| Выражение | Результат |
|---|---:|
| `True | NA` | `True` |
| `False | NA` | `NA` |
| `NA | NA` | `NA` |

Отрицание также сохраняет неизвестность:

| Выражение | Результат |
|---|---:|
| `~True` | `False` |
| `~False` | `True` |
| `~NA` | `NA` |

Это трёхзначная логика: `NA` означает «неизвестно», а не «ложь».

При непосредственном применении nullable boolean-маски pandas не выбирает позиции `NA`.
Однако техническое поведение библиотеки не должно незаметно становиться предметной
политикой. До выборки посчитайте и сохраните неизвестные строки.

### У неизвестной маски есть несколько честных политик

В этом уроке артефакт реализует две основные политики:

1. **`exclude`** — не включить неизвестные строки, но сохранить их число и метки в
   отчёте;
2. **`error`** — остановить выборку, если хотя бы одно решение неизвестно.

В рабочем процессе возможна и третья ветка: отдельно передать unknown-строки на разбор.
Для неё не нужен ещё один скрытый вариант `fillna`; достаточно сохранить маску
`mask.isna()` и построить отдельный диагностический `DataFrame`.

Политика выбирается по цене ошибки. Например:

- для исследовательского превью допустимо исключить две строки и явно сообщить долю;
- для расчёта обязательной финансовой отчётности неизвестная сумма может требовать
  остановки;
- для контроля источника unknown-строки разумно сохранить отдельным артефактом.

### Чтение и присваивание — разные намерения

Чтение создаёт отдельный результат:

```python
selected = orders.loc[resolved_mask, ["order_id", "status", "amount"]].copy()
```

Явная `.copy()` здесь фиксирует намерение передать независимую таблицу дальше. В pandas 3
Copy-on-Write уже делает изменение одного объекта предсказуемым, но `.copy()` остаётся
полезной границей handoff.

Присваивание отвечает на другой вопрос: какие ячейки выбранного объекта нужно изменить?

```python
result.loc[resolved_mask, "review_status"] = "review"
```

Левая часть одной операции называет:

- объект `result`;
- строки `resolved_mask`;
- столбец `review_status`.

### Chained assignment не является короткой формой `loc`

Неверная запись:

```python
result[resolved_mask]["review_status"] = "review"
```

Сначала создаётся промежуточный объект `result[resolved_mask]`, затем изменяется его
столбец. В pandas 3 Copy-on-Write включён всегда, поэтому такая цепочка не может обновить
исходный `result` и сообщает `ChainedAssignmentError`.

Это не проблема, которую нужно обходить лишней `.copy()` внутри цепочки. Нужно выразить
намерение одной операцией `loc`.

### Граница урока

В основном маршруте остаются только несколько опорных способов выбора:

- `frame["column"]` и `frame[["column", ...]]`;
- `loc` для меток, масок и присваивания;
- `iloc` для позиций;
- `&`, `|`, `~` для составных условий.

Сознательно откладываем:

- `query()` и `eval()`;
- `at` и `iat`;
- callable-indexers;
- MultiIndex;
- сложные срезы по неупорядоченным меткам;
- строковую нормализацию и категории до `03/09`;
- `where`, `mask`, создание производных столбцов и `apply` до `03/04`.

## Соберите это

Сначала воспроизведём решение без pandas. Так станет видно, почему неизвестность нельзя
сразу заменить на `False`.

### Шаг 1. Представьте три логических состояния

В Python используем:

```text
True  -> условие доказано
False -> условие опровергнуто
None  -> для ответа не хватает значения
```

Опишем AND, OR и NOT явно:

```python
def tri_and(left: bool | None, right: bool | None) -> bool | None:
    if left is False or right is False:
        return False
    if left is None or right is None:
        return None
    return True


def tri_or(left: bool | None, right: bool | None) -> bool | None:
    if left is True or right is True:
        return True
    if left is None or right is None:
        return None
    return False


def tri_not(value: bool | None) -> bool | None:
    if value is None:
        return None
    return not value
```

Проверим ключевые ветки:

```python
assert tri_and(True, True) is True
assert tri_and(True, None) is None
assert tri_and(False, None) is False
assert tri_and(None, None) is None

assert tri_or(True, None) is True
assert tri_or(False, None) is None
assert tri_not(True) is False
assert tri_not(None) is None
```

### Шаг 2. Классифицируйте строки вручную

```python
rows = [
    {"order_id": "O1001", "status": "paid", "amount": 120.0},
    {"order_id": "O1002", "status": "paid", "amount": None},
    {"order_id": "O1003", "status": "refunded", "amount": 80.0},
    {"order_id": "O1004", "status": None, "amount": 100.0},
    {"order_id": "O1005", "status": "refunded", "amount": None},
]


def paid_and_large(row: dict[str, object]) -> bool | None:
    status = row["status"]
    amount = row["amount"]

    status_ok = None if status is None else status == "paid"
    amount_ok = None if amount is None else amount >= 70
    return tri_and(status_ok, amount_ok)


decisions = [paid_and_large(row) for row in rows]
assert decisions == [True, None, False, None, False]
```

### Шаг 3. Сохраните три группы

```python
selected_ids = [
    row["order_id"]
    for row, decision in zip(rows, decisions, strict=True)
    if decision is True
]
unknown_ids = [
    row["order_id"]
    for row, decision in zip(rows, decisions, strict=True)
    if decision is None
]

assert selected_ids == ["O1001"]
assert unknown_ids == ["O1002", "O1004"]
```

Только теперь можно принять решение: исключить unknown с отчётом или остановиться. Ручная
версия медленнее pandas, но делает наблюдаемой логику, которую nullable-маска реализует
поэлементно.

## Используйте это

Теперь повторим тот же процесс с маркированными объектами pandas.

### Шаг 1. Создайте уже проверенную таблицу

Пример самодостаточен и намеренно не содержит парсинга:

```python
import pandas as pd
from pandas.api.types import is_bool_dtype

orders = pd.DataFrame(
    {
        "order_id": pd.array(
            ["O1001", "O1002", "O1003", "O1004", "O1005"],
            dtype="string",
        ),
        "status": pd.array(
            ["paid", "paid", "refunded", pd.NA, "refunded"],
            dtype="string",
        ),
        "amount": pd.array(
            [120.0, pd.NA, 80.0, 100.0, pd.NA],
            dtype="Float64",
        ),
    },
    index=["row-a", "row-b", "row-c", "row-d", "row-e"],
)
```

`status` уже содержит канонические значения, а `amount` уже имеет целевой `Float64`.
Если исходные строки ещё не прошли dtype-аудит `03/02`, фильтровать их рано.

### Шаг 2. Сравните способы выбора столбцов

```python
amount = orders["amount"]
amount_table = orders[["amount"]]
compact = orders[["order_id", "amount"]]

assert isinstance(amount, pd.Series)
assert amount.shape == (5,)

assert isinstance(amount_table, pd.DataFrame)
assert amount_table.shape == (5, 1)

assert compact.columns.tolist() == ["order_id", "amount"]
```

### Шаг 3. Сопоставьте `loc` и `iloc`

```python
by_labels = orders.loc[
    "row-b":"row-d",
    ["order_id", "amount"],
]
by_positions = orders.iloc[
    1:4,
    [0, 2],
]

assert by_labels.index.tolist() == ["row-b", "row-c", "row-d"]
assert by_positions.index.tolist() == ["row-b", "row-c", "row-d"]
assert by_labels.columns.tolist() == ["order_id", "amount"]
assert by_positions.columns.tolist() == ["order_id", "amount"]
```

Результаты совпали только потому, что текущий порядок строк и столбцов соответствует
выбранным меткам. После перестановки позиционный контракт изменится.

### Шаг 4. Постройте именованные предикаты

```python
is_paid = orders["status"].eq("paid")
amount_is_large = orders["amount"].ge(70)

assert is_bool_dtype(is_paid.dtype)
assert is_bool_dtype(amount_is_large.dtype)
assert is_paid.index.equals(orders.index)
assert amount_is_large.index.equals(orders.index)
```

Обе маски булевы и допускают неизвестное решение, но строковое представление dtype может
отличаться: в окружении курса сравнение `string` возвращает `bool[pyarrow]`, а сравнение
`Float64` — `boolean`. Проверяйте семейство dtype и поведение `NA`, а не одну строку с
названием внутреннего представления.

Теперь объедините их:

```python
mask = is_paid & amount_is_large
mask.name = "paid_and_large"

mask_values = mask.tolist()
assert mask_values[0] is True
assert pd.isna(mask_values[1])
assert mask_values[2] is False
assert pd.isna(mask_values[3])
assert mask_values[4] is False
```

Проверим оставшиеся операторы на тех же предикатах:

```python
paid_or_large = is_paid | amount_is_large
not_paid = ~is_paid

assert paid_or_large.iloc[:4].tolist() == [True, True, True, True]
assert pd.isna(paid_or_large.iloc[4])
assert not_paid.iloc[:3].tolist() == [False, False, True]
assert pd.isna(not_paid.iloc[3])
assert not_paid.iloc[4] is True
```

Наконец, сопоставим `.eq()` и `.isin()` на пропущенном статусе:

```python
raw_membership = orders["status"].isin({"paid"})
nullable_membership = raw_membership.astype("boolean").mask(
    orders["status"].isna(),
    pd.NA,
)

assert bool(raw_membership.loc["row-d"]) is False
assert pd.isna(nullable_membership.loc["row-d"])
```

Первый результат следует технической семантике `.isin()`, второй — выбранной в уроке
предметной политике: неизвестный статус оставляет неизвестным решение фильтра.

### Шаг 5. Посчитайте неизвестные решения до выборки

```python
selected_positions = mask.eq(True).fillna(False)
excluded_positions = mask.eq(False).fillna(False)
unknown_positions = mask.isna()

assert int(selected_positions.sum()) == 1
assert int(excluded_positions.sum()) == 2
assert int(unknown_positions.sum()) == 2
```

Сохраним метки неизвестных строк без преждевременного pandas-фильтра:

```python
unknown_labels = [
    label
    for label, is_unknown in zip(
        mask.index.tolist(),
        unknown_positions.tolist(),
        strict=True,
    )
    if is_unknown
]

assert unknown_labels == ["row-b", "row-d"]
```

### Шаг 6. Разрешите `NA` явной политикой

Для политики `exclude`:

```python
resolved_mask = mask.fillna(False).astype(bool)

assert resolved_mask.tolist() == [True, False, False, False, False]
```

Мы имеем право выполнить эту строку, потому что количество и метки unknown уже
сохранены. Для политики `error` решение выглядело бы иначе:

```python
if mask.isna().any():
    raise ValueError(f"unknown filter decisions: {unknown_labels}")
```

### Шаг 7. Выберите строки и столбцы одной операцией

```python
selected = orders.loc[
    resolved_mask,
    ["order_id", "status", "amount"],
].copy()

assert selected.index.tolist() == ["row-a"]
assert selected.columns.tolist() == ["order_id", "status", "amount"]
assert selected["order_id"].tolist() == ["O1001"]
```

Форма результата является частью проверки:

```python
assert selected.shape == (1, 3)
```

### Шаг 8. Пометьте строки одним `loc`-присваиванием

Если нужно сохранить исходную таблицу, сначала назовите копию:

```python
labeled = orders.copy()
labeled.loc[resolved_mask, "review_status"] = "review"

assert "review_status" not in orders.columns
assert labeled.loc["row-a", "review_status"] == "review"
assert labeled.loc["row-b":, "review_status"].isna().all()
```

Если задача действительно требует изменить сам `orders`, используйте тот же одинарный
индексатор слева:

```python
orders.loc[resolved_mask, "review_status"] = "review"
```

Важно не наличие копии само по себе, а явный выбор объекта, который должен измениться.

### Шаг 9. Используйте готовый артефакт

Из каталога урока:

```python
from outputs.safe_selection import (
    build_order_mask,
    label_rows,
    select_rows,
)

mask = build_order_mask(
    orders,
    statuses={"paid"},
    min_amount=70,
)

selected, report = select_rows(
    orders,
    mask,
    columns=["order_id", "status", "amount"],
    missing="exclude",
)

labeled, label_report = label_rows(
    orders,
    mask,
    missing="exclude",
)
```

Существенная часть `report`:

```json
{
  "rows": 5,
  "mask_dtype": "boolean",
  "selected_rows": 1,
  "excluded_rows": 2,
  "unknown_rows": 2,
  "selected_index_examples": ["row-a"],
  "unknown_index_examples": ["row-b", "row-d"],
  "missing_policy": "exclude",
  "resolved_selected_rows": 1,
  "columns": ["order_id", "status", "amount"],
  "output_shape": [1, 3]
}
```

Артефакт строже голого `loc`: он отклоняет не-boolean маску, другой порядок индекса,
повторяющиеся метки и отсутствие критериев до применения выборки.

Запустите связный пример:

```bash
uv run --locked python code/main.py
```

## Сломайте это

### Ошибка 1. Повторно очищать данные внутри фильтра

```python
amount = pd.to_numeric(orders["amount"], errors="coerce")
```

Если `orders` ещё содержит `oops`, фильтр снова превратит invalid-значение в пропуск и
отменит контракт `03/02`. Выборка должна принимать уже проверенный dtype.

### Ошибка 2. Нормализовать строки как скрытый побочный шаг

```python
status = orders["status"].str.strip().str.lower()
```

Такая операция может быть правильной частью отдельного контракта нормализации, но не
должна незаметно жить внутри общего селектора. В этом уроке критерии сравниваются с уже
подготовленными значениями точно.

### Ошибка 3. Сразу заменить `NA` на `False`

```python
mask = (is_paid & amount_is_large).fillna(False)
```

Выборка выполнится, но unknown-строки станут неотличимы от доказанных `False`. Сначала
постройте отчёт и только затем разрешите `NA`.

### Ошибка 4. Использовать `and` или забыть скобки

```python
orders["status"].eq("paid") and orders["amount"].ge(70)
```

Python не может получить одно truth value из целой `Series`. Используйте `&`.

Компактное выражение без скобок также читается согласно приоритетам операторов, а не
согласно предполагаемому бизнес-условию. Именованные предикаты уменьшают этот риск.

### Ошибка 5. Передать integer-маску

```python
mask = pd.Series([1, 0, 0, 1, 0], index=orders.index)
orders.loc[mask]
```

Значения `1` и `0` могут быть восприняты как метки, а не логические решения. Проверяйте
dtype маски, а не только её длину.

### Ошибка 6. Передать маску другой таблицы

Две таблицы могут иметь пять строк, но описывать разные заказы. Совпадение длины не
доказывает соответствие. Даже автоматическое выравнивание одинаковых меток не доказывает
происхождение маски, поэтому строгий helper требует точного совпадения индекса и порядка.

### Ошибка 7. Разрешить пустой фильтр как «выбрать всё»

Если вызывающий код забыл передать критерии, маска из одних `True` выглядит успешным
результатом. Безопасный артефакт останавливается с сообщением `at least one selection
criterion is required`.

### Ошибка 8. Перепутать правую границу `loc` и `iloc`

```python
orders.iloc[1:4]              # позиции 1, 2, 3
orders.loc["row-b":"row-d"]  # обе метки включены
```

На текущем примере результаты совпадают, но причина разная. Не переносите правило
полуинтервала на label slice.

### Ошибка 9. Потерять ось столбцов

```python
selected_amount = orders.loc[resolved_mask, "amount"]
```

Это `Series`. Если следующий шаг ожидает таблицу, используйте список:

```python
selected_amount = orders.loc[resolved_mask, ["amount"]]
```

### Ошибка 10. Использовать chained assignment

```python
orders[resolved_mask]["review_status"] = "review"
```

В pandas 3 изменится временный объект, а не `orders`. Используйте одну левую часть:

```python
orders.loc[resolved_mask, "review_status"] = "review"
```

## Проверьте это

Перед применением рабочего фильтра ответьте:

1. Какую популяцию описывает условие?
2. Какие столбцы участвуют в каждом предикате?
3. Какой dtype имеет каждый исходный столбец?
4. Совпадает ли индекс маски с индексом таблицы?
5. Сколько в маске `True`, `False` и `NA`?
6. Какая политика выбрана для `NA` и почему?
7. Какие столбцы и в каком порядке должны попасть в результат?
8. Какой объект должен измениться при присваивании?

Запустите behavioral tests:

```bash
uv run --locked python tests/test_main.py
```

Они проверяют:

- сохранение трёх состояний в составной маске;
- правила `False & NA`, `True & NA`, `False | NA` и `~NA`;
- принятие нативной маски `bool[pyarrow]` как булевой и её приведение к единому
  внутреннему dtype;
- различие технического результата `.isin()` и предметной nullable-политики;
- требование хотя бы одного критерия;
- отсутствие скрытой нормализации строк;
- отказ от повторного преобразования текстовой суммы;
- включение обеих числовых границ;
- evidence для unknown-строк;
- политики `exclude` и `error` и отказ от неизвестного имени политики;
- отказ от integer-, безымянной, переставленной и чужой маски;
- отказ при повторяющемся индексе;
- выбор и порядок столбцов;
- независимость результата от источника;
- изменение только выбранных строк одним `loc`-присваиванием;
- запуск самодостаточного примера.

Главные инварианты артефакта:

```text
mask.index.equals(frame.index)
is_bool_dtype(mask.dtype)
selected_rows + excluded_rows + unknown_rows == input_rows
report.unknown_rows измерен до разрешения NA
result.columns == requested_columns
source остаётся неизменным для select_rows и label_rows
```

## Поставьте результат

Артефакт урока —
`phases/03-pandas/03-selection-and-filtering/outputs/safe_selection.py`.

Он предоставляет пять связанных операций:

- `build_order_mask` строит nullable-маску только из уже проверенных столбцов;
- `validate_mask` проверяет dtype, уникальность и точное совпадение индекса;
- `mask_report` считает `True`, `False`, `NA` и сохраняет примеры меток;
- `select_rows` разрешает unknown-политику и выбирает названные столбцы;
- `label_rows` помечает строки на независимом `DataFrame` одним присваиванием `loc`.

Артефакт намеренно является набором функций, а не CLI. Выборка обычно является частью
pipeline, notebook или теста и должна получать уже типизированный `DataFrame`, а не
повторно читать и очищать CSV.

Его публичный workflow описан в начале `safe_selection.py`: построить маску, получить
отчёт, затем вызвать `select_rows` или `label_rows` с явной missing-политикой. Команда
`uv run --locked python code/main.py` запускает этот workflow целиком без внешних данных.

Он не угадывает критерии, не нормализует строки, не исправляет dtype, не заменяет
unknown бизнес-значением и не изменяет переданный объект побочным эффектом.

## Упражнения

1. Выберите оплаченные заказы в валюте `RUB`. До разрешения маски назовите строки `True`,
   `False` и `NA`; затем верните только `order_id`, `currency` и `amount`.
2. Создайте таблицу со статусом `paid` и пропущенной суммой. Сравните политики `exclude`
   и `error`, сохранив отчёт первой и сообщение второй.
3. Создайте маску с теми же метками в обратном порядке. Покажите обычное выравнивание
   pandas, затем объясните, почему строгий артефакт всё равно отклоняет такую маску.
4. Сравните `orders["amount"]`, `orders[["amount"]]`,
   `orders.loc[:, ["amount"]]` и `orders.iloc[:, [2]]`: зафиксируйте тип, форму и имя
   столбца каждого результата.
5. Добавьте существующий строковый столбец `review_status` и пометьте только выбранные
   строки. Напишите negative test на несовместимое значение для числового столбца.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Популяция фильтра | Все строки исходной таблицы | Набор наблюдений, о которых после применения условия будет сделан вывод |
| Boolean mask | Список номеров строк | `Series` логических решений, связанных со строками индексом |
| Nullable mask | Обычная маска с лишним значением | Маска dtype `boolean`, способная хранить неизвестное решение `pd.NA` |
| Predicate | Готовая таблица после фильтра | Одно именованное условие для каждой строки |
| `loc` | Позиционный срез | Выбор и присваивание по меткам либо согласованной булевой маске |
| `iloc` | Выбор по бизнес-ключу | Выбор по целочисленным позициям текущих осей |
| Missing policy | Всегда `fillna(False)` | Явное решение исключить, остановить или отдельно разобрать unknown-строки |
| Chained assignment | Сокращённый `loc` | Последовательное изменение временного объекта, которое не обновляет источник при Copy-on-Write |
| Copy-on-Write | Каждый выбор немедленно копирует всю таблицу | Модель pandas 3, в которой изменение одного производного объекта не меняет другой объект побочным эффектом |

## Дополнительное чтение

1. [Яндекс Образование: модуль pandas (RU)](https://education.yandex.ru/handbook/python/article/modul-pandas) — повторите разделы об объектах `Series` и `DataFrame`, индексации, срезах и фильтрации на коротких русскоязычных примерах. Группировку, агрегацию и визуализацию пока пропустите: они относятся к следующим урокам фазы.
2. [pandas: How do I select a subset of a DataFrame? (EN)](https://pandas.pydata.org/docs/getting_started/intro_tutorials/03_subset_data.html) — пройдите три части про выбор столбцов, фильтрацию строк и одновременный выбор двух осей. После каждого примера называйте тип и `shape` результата и отдельно сопоставьте `.isin()` с эквивалентным выражением через `|`.
3. [pandas: Indexing and selecting data (EN)](https://pandas.pydata.org/docs/user_guide/indexing.html) — это основной развивающий справочник урока. Прочитайте `Different choices for indexing`, `Slicing ranges`, `Selection by label`, `Selection by position` и `Boolean indexing`; обратите внимание на включённую правую границу `loc`, выравнивание булевой `Series`, трактовку `NA` и ограничение `iloc` для индексированной маски. Callable-indexers и MultiIndex пока не нужны.
4. [`pandas.DataFrame.loc` (EN)](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.loc.html) — разберите таблицу допустимых индексаторов и примеры со скаляром, списком меток, срезом и согласованной булевой `Series`. Отдельно проверьте, когда возникает `KeyError`, как включается конечная метка и как одной операцией выбираются строки, столбцы и ячейки для присваивания.
5. [`pandas.DataFrame.iloc` (EN)](https://pandas.pydata.org/docs/reference/api/pandas.DataFrame.iloc.html) — сопоставьте целое число, список позиций, полуинтервальный срез и булев массив с соответствующими вариантами `loc`. Зафиксируйте различие между `IndexError` для отдельной позиции за границей и допустимым обрезанием позиционного среза.
6. [pandas: Nullable Boolean data type (EN)](https://pandas.pydata.org/docs/user_guide/boolean.html) — обязательны разделы `Indexing with NA values` и `Kleene logical operations`. До просмотра таблицы самостоятельно предскажите `True & NA`, `False & NA`, `True | NA`, `False | NA` и объясните, почему техническое исключение `NA` при индексировании ещё не является предметной политикой.
7. [`pandas.Series.isin` (EN)](https://pandas.pydata.org/docs/reference/api/pandas.Series.isin.html) — изучите точное сравнение значений, инверсию через `~` и ошибку при передаче одной строки вместо коллекции. Затем добавьте в `Series` пропуск и сопоставьте технический `False` от `.isin()` с nullable-политикой, которую явно восстанавливает артефакт урока.
8. [`pandas.Index.equals` (EN)](https://pandas.pydata.org/docs/reference/api/pandas.Index.equals.html) — прочитайте, что метод сравнивает и элементы, и их порядок. На двух переставленных индексах воспроизведите `False` и свяжите результат со строгим требованием `mask.index.equals(frame.index)`; помните, что совпадение индексов всё равно не доказывает происхождение маски.
9. [pandas: Duplicate Labels (EN)](https://pandas.pydata.org/docs/user_guide/duplicates.html) — разберите `Consequences of Duplicate Labels`, `Duplicate Label Detection` и `Disallowing Duplicate Labels`. Материал объясняет, почему pandas допускает неуникальные метки для очистки сырых данных, а строгий селектор аналитического pipeline вправе остановиться до выборки.
10. [pandas: Copy-on-Write — Chained Assignment (EN)](https://pandas.pydata.org/docs/user_guide/copy_on_write.html#chained-assignment) — воспроизведите сломанную цепочку присваиваний и исправление через один `loc`. Остальные оптимизации Copy-on-Write можно оставить на потом; здесь важно понять правило «за одно присваивание изменяется один явно названный объект».
