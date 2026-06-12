# Индексация, срезы и маски

> Перед изменением подмассива выясните, разделяет ли он память с источником: базовый срез обычно является view, а boolean и advanced indexing создают копию.

**Тип:** Build
**Треки:** Core
**Пререквизит:** `02-numpy/03-dtypes`
**Время:** ~60 минут
**Результат:** извлекает и изменяет подмножества данных без скрытого копирования.

## Цели обучения

- выбирать элементы по индексам и срезам нескольких осей;
- строить составные булевы маски;
- различать basic и advanced indexing;
- проверять совместное использование памяти;
- делать изменение источника или копии явным.

## Проблема

Аналитик берёт первые сто строк большого массива, исправляет выбросы и ожидает получить
новый набор данных:

```python
sample = values[:100]
sample[sample < 0] = 0
```

Но `sample` является view. Изменения попадают и в `values`.

В другом месте фильтрация маской:

```python
positive = values[values > 0]
```

создаёт новый массив. Изменение `positive` уже не затронет источник. Одинаковый синтаксис
квадратных скобок скрывает разные контракты памяти.

## Концепция

### Базовая индексация

К basic indexing относятся:

- целочисленный индекс;
- срез `start:stop:step`;
- кортеж целых индексов и срезов;
- `...` и `np.newaxis`.

```python
matrix[1, 2]
matrix[:, 0]
matrix[1:4, ::2]
```

Базовый срез обычно возвращает view. Он содержит собственные `shape` и `strides`, но
ссылается на тот же буфер данных.

### Advanced indexing

К advanced indexing относятся массивы целых индексов и булевы маски:

```python
matrix[[0, 2]]
matrix[matrix > 0]
```

Результат содержит выбранные значения в новом буфере.

### Маска

Булева маска должна быть согласована с формой индексируемых данных:

```text
values: [5, 12, 18, 27]
mask:   [F, T,  T,  F]
result: [12, 18]
```

Каждое условие заключайте в скобки:

```python
mask = (values >= 10) & (values <= 20)
```

Операторы Python `and` и `or` не выполняют поэлементную логику ndarray.

## Соберите это

### Маска диапазона

```python
def range_mask(values, lower, upper):
    result = []
    for value in values:
        keep = value >= lower and value <= upper
        result.append(keep)
    return result
```

```python
assert range_mask([5, 12, 18, 27], 10, 20) == [
    False,
    True,
    True,
    False,
]
```

Ручная версия показывает соответствие позиций, но не решает вопрос пропусков. В
числовом контракте урока не конечные значения исключаются:

```text
is finite AND satisfies lower bound AND satisfies upper bound
```

### Явная политика изменения

Функция изменения должна сообщать, работает она in-place или с копией:

```python
def replace_where(values, mask, replacement, in_place=False):
    result = values if in_place else values.copy()
    result[mask] = replacement
    return result
```

Параметр `in_place` не делает один вариант универсально правильным. Он делает намерение
проверяемым.

## Используйте это

```python
import numpy as np

values = np.array([5.0, 12.0, np.nan, 18.0, 27.0])
mask = np.isfinite(values) & (values >= 10) & (values <= 20)
selected = values[mask]

np.testing.assert_array_equal(selected, [12.0, 18.0])
```

### Несколько осей

```python
matrix = np.arange(12).reshape(3, 4)

second_row = matrix[1]
first_two_columns = matrix[:, :2]
corners = matrix[[0, 2]][:, [0, 3]]
```

Предсказывайте форму после каждого шага. Смешивание нескольких advanced indices имеет
дополнительные правила формы, поэтому для читаемого аналитического кода иногда лучше
разделить выборку на два именованных этапа.

### Проверка памяти

```python
source = np.arange(6)
view = source[1:5]
copy = source[source % 2 == 0]

assert np.shares_memory(source, view)
assert not np.shares_memory(source, copy)
```

Явная независимая копия:

```python
independent = source[1:5].copy()
assert not np.shares_memory(source, independent)
```

### Артефакт

```bash
uv run --locked python phases/02-numpy/04-indexing-and-masks/outputs/numeric_filters.py \
  --values '[5, 12, 18, 27]' \
  --lower 10 \
  --upper 20
```

CLI возвращает маску, выбранные значения и демонстрацию памяти для basic и advanced
indexing.

## Сломайте это

### Скрыто изменить источник

```python
source = np.array([1, 2, 3, 4])
part = source[1:3]
part[:] = 0

np.testing.assert_array_equal(source, [1, 0, 0, 4])
```

Если это не требуемое поведение, вызывайте `.copy()`.

### Использовать `and`

```python
mask = (values >= 10) and (values <= 20)
```

Python пытается получить одно truth value всего массива и сообщает о неоднозначности.
Используйте `&` и скобки.

### Пропустить NaN

Сравнения с `NaN` обычно дают `False`, но явный `np.isfinite` документирует намерение и
также исключает бесконечности.

### Маска неправильной формы

Изменение через маску должно проверять согласование форм. Артефакт отклоняет маску формы
`(1,)` для массива формы `(3,)`, вместо неявного предположения автора.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/02-numpy/04-indexing-and-masks/tests \
  -v
```

Тесты проверяют включение границ, исключение `NaN`, независимость результата фильтрации,
совместную память среза и явные режимы изменения.

```bash
uv run --locked python phases/02-numpy/04-indexing-and-masks/code/main.py
```

## Поставьте результат

Артефакт `outputs/numeric_filters.py` содержит:

- `range_mask` с четырьмя политиками включения границ;
- `filter_observations`, гарантированно возвращающий независимую выборку;
- `replace_where` с явным `in_place`;
- `memory_report` для демонстрации basic и advanced indexing;
- CLI с JSON-выводом.

Его можно импортировать в численный пайплайн:

```python
from numeric_filters import filter_observations

clean = filter_observations(raw_scores, lower=0, upper=100)
```

## Упражнения

1. Добавьте фильтрацию только по одной границе и проверьте `None` для второй.
2. Реализуйте функцию выбора строк двумерной матрицы по условию на один столбец.
3. Добавьте тест, демонстрирующий, что маленький view удерживает ссылку на большой
   исходный массив, и объясните, когда нужна явная копия.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Basic indexing | «Любой доступ через скобки» | Индексы и срезы, обычно возвращающие view |
| Advanced indexing | «Более быстрый срез» | Выбор массивом индексов или маской, возвращающий копию |
| View | «Независимый массив» | Новый объект массива, разделяющий буфер с источником |
| Copy | «Другое имя массива» | Массив с независимым буфером данных |
| Булева маска | «Один фильтр True/False» | Массив логических решений для соответствующих позиций |
| `np.shares_memory` | «Проверка равенства» | Проверка возможного пересечения областей памяти массивов |

## Дополнительное чтение

- [Indexing on ndarrays](https://numpy.org/doc/stable/user/basics.indexing.html) — официальный справочник basic, advanced и boolean indexing.
- [Copies and views](https://numpy.org/doc/stable/user/basics.copies.html) — модель буфера, metadata, views и явных копий.
- [numpy.shares_memory](https://numpy.org/doc/stable/reference/generated/numpy.shares_memory.html) — точный контракт проверки общей памяти и ограничения стоимости.
- [numpy.isfinite](https://numpy.org/doc/stable/reference/generated/numpy.isfinite.html) — построение маски конечных значений перед числовой фильтрацией.
