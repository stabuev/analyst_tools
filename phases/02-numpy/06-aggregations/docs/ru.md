# Агрегации и оси расчета

> `axis` называет ось, которая исчезает при агрегации, а не ось, которую вы хотите увидеть в результате.

**Тип:** Build
**Треки:** Core
**Пререквизит:** `02-numpy/05-broadcasting`
**Время:** ~60 минут
**Результат:** выбирает правильную axis и сохраняет ожидаемую размерность результата.

## Цели обучения

- объяснить смысл `axis=0`, `axis=1` и `axis=None`;
- вручную рассчитать сумму по строкам и столбцам;
- предсказать форму каждой редукции;
- использовать `keepdims` для последующего broadcasting;
- выбирать `ddof` как часть статистического контракта.

## Проблема

Матрица формы `(2, 3)` содержит две торговые точки и три дня:

```text
[[1, 2, 3],
 [4, 5, 6]]
```

Нужны два разных результата:

- сумма по каждой торговой точке: `[6, 15]`;
- сумма по каждому дню: `[5, 7, 9]`.

Обе задачи вызывают `sum`, но с разными осями. Перепутанная ось часто возвращает
корректный массив неправильного смысла.

## Концепция

Редукция сворачивает выбранную ось:

```text
input shape: (stores=2, days=3)

axis=0 removes stores -> result shape (days=3,)
axis=1 removes days   -> result shape (stores=2,)
axis=None removes all -> scalar shape ()
```

Фраза «сумма по столбцам» означает сворачивание строк, то есть `axis=0`.

### keepdims

```text
(2, 3) --mean(axis=1)-->           (2,)
(2, 3) --mean(axis=1, keepdims)--> (2, 1)
```

Второй результат можно сразу вычесть из исходной матрицы благодаря broadcasting.

### ddof

Стандартное отклонение использует делитель:

```text
N - ddof
```

`ddof=0` описывает разброс имеющегося набора как популяции. `ddof=1` часто используется
для выборочной оценки. Выбор зависит от методологии, а не от предпочтения библиотеки.

## Соберите это

### Сумма по оси 0

```python
def sum_axis_0(values):
    width = len(values[0])
    return [
        sum(row[column] for row in values)
        for column in range(width)
    ]
```

### Сумма по оси 1

```python
def sum_axis_1(values):
    return [sum(row) for row in values]
```

```python
matrix = [[1, 2, 3], [4, 5, 6]]

assert sum_axis_0(matrix) == [5, 7, 9]
assert sum_axis_1(matrix) == [6, 15]
```

Ручная реализация должна отклонить рваные строки. Иначе понятие столбца не определено.

### Форма результата

```python
def reduced_shape(shape, axis, keepdims=False):
    if keepdims:
        return tuple(
            1 if index == axis else length
            for index, length in enumerate(shape)
        )
    return tuple(
        length
        for index, length in enumerate(shape)
        if index != axis
    )
```

## Используйте это

```python
import numpy as np

matrix = np.array([[1, 2, 3], [4, 5, 6]])

np.sum(matrix, axis=0)
# array([5, 7, 9])

np.sum(matrix, axis=1)
# array([ 6, 15])

np.sum(matrix)
# 21
```

Аналогично работают:

```python
np.mean(matrix, axis=0)
np.min(matrix, axis=0)
np.max(matrix, axis=1)
np.std(matrix, axis=1, ddof=0)
```

### Центрирование строк

```python
row_means = matrix.mean(axis=1, keepdims=True)
centered = matrix - row_means

assert row_means.shape == (2, 1)
assert centered.shape == matrix.shape
```

Без `keepdims` форма `(2,)` не согласуется с `(2, 3)` по последней оси.

### Несколько осей

Для массива `(days, stores, metrics)` можно свернуть первые две оси:

```python
values.mean(axis=(0, 1))
```

Результат имеет форму `(metrics,)`.

### Артефакт

```bash
uv run --locked python phases/02-numpy/06-aggregations/outputs/axis_aggregates.py \
  --values '[[1, 2, 3], [4, 5, 6]]' \
  --axis 0
```

Отчёт содержит значения и формы `count`, `sum`, `mean`, `min`, `max`, `std`.

## Сломайте это

### Перепутать axis

Если ожидаются два итога по магазинам, а результат имеет три элемента, shape уже
доказывает ошибку:

```python
totals = matrix.sum(axis=0)
assert totals.shape == (2,)  # упадёт
```

### Потерять ось перед broadcasting

```python
matrix - matrix.mean(axis=1)
```

Формы `(2, 3)` и `(2,)` несовместимы. Нужен `keepdims=True` или явная форма `(2, 1)`.

### Некорректный ddof

Для двух наблюдений `ddof=2` оставляет нулевой знаменатель. Артефакт отклоняет такой
контракт до вычисления.

### Смешать пропуски и обычные агрегаты

`np.mean` не игнорирует `NaN`. Сначала выберите политику данных. `np.nanmean` является
отдельной операцией и не должна появляться как случайное средство «получить число».

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/02-numpy/06-aggregations/tests \
  -v
```

Тесты проверяют ручные суммы, обе оси, отрицательную ось, `keepdims`, `ddof` и формы
результатов.

```bash
uv run --locked python phases/02-numpy/06-aggregations/code/main.py
```

## Поставьте результат

Артефакт `outputs/axis_aggregates.py` превращает axis в наблюдаемую часть результата:

```python
report = aggregate(values, axis=0, keepdims=False, ddof=0)
```

Каждый агрегат содержит `value` и `shape`, поэтому downstream-проверка может подтвердить
как числа, так и grain результата.

## Упражнения

1. Добавьте `median` и проверьте его по обеим осям.
2. Расширьте API поддержкой кортежа осей и сравните форму с ручным предсказанием.
3. Добавьте отдельный режим пропусков: `error` или `omit`, не меняя поведение по
   умолчанию.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Редукция | «Изменение shape без вычисления» | Сворачивание элементов вдоль выбранных осей |
| `axis` | «Ось, которая останется» | Ось или оси, которые агрегируются |
| `axis=None` | «Первая ось» | Все оси массива |
| `keepdims` | «Оставить исходные значения» | Сохранить редуцированные оси длины `1` |
| `ddof` | «Точность float» | Поправка числа степеней свободы в делителе дисперсии |

## Дополнительное чтение

- [numpy.sum](https://numpy.org/doc/stable/reference/generated/numpy.sum.html) — официальный контракт `axis`, `dtype`, `keepdims`, `where` и поведения integer accumulator.
- [numpy.mean](https://numpy.org/doc/stable/reference/generated/numpy.mean.html) — форма результата и предупреждение о точности среднего для `float32`.
- [numpy.std](https://numpy.org/doc/stable/reference/generated/numpy.std.html) — формула, `ddof`, `mean`, `where` и различие оценок.
- [NumPy statistics routines](https://numpy.org/doc/stable/reference/routines.statistics.html) — карта доступных редукций и их специализированных вариантов.
