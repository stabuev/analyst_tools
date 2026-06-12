# Shape, axes и размерность

> Форма результата должна быть известна до запуска вычисления: операция либо сохраняет ось, либо переставляет, добавляет или удаляет её по явному правилу.

**Тип:** Build
**Треки:** Core
**Пререквизит:** `02-numpy/01-arrays`
**Время:** ~60 минут
**Результат:** предсказывает форму результата до выполнения операции.

## Цели обучения

- читать `shape` как упорядоченный контракт осей;
- вручную предсказывать форму редукции, `reshape`, `transpose` и `expand_dims`;
- нормализовать отрицательные номера осей;
- проверять форму результата через именованный assertion.

## Проблема

Пусть массив заказов имеет форму `(7, 24, 3)`:

- ось `0`: семь дней;
- ось `1`: двадцать четыре часа;
- ось `2`: три показателя.

Код `values.mean(axis=1)` корректен синтаксически, но без понимания осей невозможно
сказать, что он усредняет. Ошибка в `axis` часто не вызывает исключения: она возвращает
правдоподобные числа неправильного смысла.

Перед вычислением нужно ответить на два вопроса:

1. Какую семантическую ось меняет операция?
2. Какой `shape` обязан получиться?

## Концепция

`shape` является упорядоченным кортежем длин осей. Позиция длины важна:

```text
(days, hours, metrics) = (7, 24, 3)
```

Ось можно указать положительным или отрицательным индексом:

```text
axis=0   -> days
axis=1   -> hours
axis=2   -> metrics
axis=-1  -> metrics
axis=-2  -> hours
```

Отрицательный индекс нормализуется правилом:

```text
normalized_axis = axis + ndim
```

### Четыре семейства операций

| Операция | Что происходит с осями | Число элементов |
|---|---|---:|
| редукция | выбранные оси удаляются или становятся длины `1` | уменьшается |
| `reshape` | длины осей меняются | сохраняется |
| `transpose` | порядок осей меняется | сохраняется |
| `expand_dims` | добавляется ось длины `1` | сохраняется |

## Соберите это

### Нормализация оси

```python
def normalize_axis(axis, ndim):
    normalized = axis + ndim if axis < 0 else axis
    if normalized < 0 or normalized >= ndim:
        raise ValueError("axis is out of bounds")
    return normalized
```

Для `ndim == 3` ось `-1` превращается в `2`.

### Форма редукции

Без `keepdims` выбранная ось исчезает:

```python
def reduction_shape(shape, axis):
    axis = normalize_axis(axis, len(shape))
    return tuple(
        length
        for index, length in enumerate(shape)
        if index != axis
    )
```

```python
assert reduction_shape((7, 24, 3), 1) == (7, 3)
```

С `keepdims=True` ось остаётся, но её длина становится равной `1`:

```python
def reduction_shape_keepdims(shape, axis):
    axis = normalize_axis(axis, len(shape))
    return tuple(
        1 if index == axis else length
        for index, length in enumerate(shape)
    )
```

```python
assert reduction_shape_keepdims((7, 24, 3), 1) == (7, 1, 3)
```

### Контракт reshape

`reshape` не может изменить число элементов:

```python
from math import prod


def can_reshape(source, target):
    return prod(source) == prod(target)
```

```python
assert can_reshape((2, 3, 4), (6, 4))
assert not can_reshape((2, 3, 4), (5, 5))
```

Одна длина `-1` может быть вычислена автоматически:

```text
(2, 3, 4) -> (6, -1)
24 / 6 = 4
result: (6, 4)
```

### Перестановка осей

Для `transpose((2, 0, 1))` новая форма собирается из старой по указанному порядку:

```python
shape = (7, 24, 3)
axes = (2, 0, 1)
result = tuple(shape[index] for index in axes)

assert result == (3, 7, 24)
```

`axes` должны быть перестановкой всех номеров от `0` до `ndim - 1`.

## Используйте это

```python
import numpy as np

values = np.arange(24).reshape(2, 3, 4)
```

### Редукция

```python
values.sum(axis=1).shape
# (2, 4)

values.sum(axis=1, keepdims=True).shape
# (2, 1, 4)
```

`keepdims=True` полезен, когда результат затем должен участвовать в операции с исходным
массивом.

### Изменение формы

```python
matrix = values.reshape(6, 4)
assert matrix.shape == (6, 4)

inferred = values.reshape(6, -1)
assert inferred.shape == (6, 4)
```

`reshape` возвращает view, когда это возможно, но может создать копию. Используйте его
для изменения логической организации элементов, а не как гарантию совместной памяти.

### Перестановка и добавление оси

```python
permuted = np.transpose(values, (2, 0, 1))
assert permuted.shape == (4, 2, 3)

expanded = np.expand_dims(values, axis=-1)
assert expanded.shape == (2, 3, 4, 1)
```

Запустите артефакт:

```bash
uv run --locked python phases/02-numpy/02-shape-and-axes/outputs/shape_contract.py \
  --shape '[2, 3, 4]' \
  --axis 1 \
  --keepdims \
  --reshape '[6, 4]' \
  --transpose '[2, 0, 1]' \
  --expand-axis -1
```

CLI предсказывает формы без выделения массива заданного размера.

## Сломайте это

### Неверная ось

Для массива с `ndim == 2` оси `2` не существует:

```bash
uv run --locked python phases/02-numpy/02-shape-and-axes/outputs/shape_contract.py \
  --shape '[2, 3]' \
  --axis 2
```

### Несовместимый reshape

```python
np.zeros((2, 3)).reshape(4, 2)
```

Шесть элементов нельзя разместить в форме, требующей восемь.

### Потеря оси

```python
matrix = np.zeros((4, 3))
means = matrix.mean(axis=0)

assert means.shape == (3,)
```

Если следующий контракт требует `(1, 3)`, используйте `keepdims=True`, а не надейтесь,
что отсутствующая ось восстановится автоматически.

### Перепутанная перестановка

`transpose((0, 0, 1))` недопустим: ось `0` повторяется, а одна ось пропущена.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/02-numpy/02-shape-and-axes/tests \
  -v
```

Тесты сравнивают ручные предсказания с фактическими формами NumPy для отрицательных осей,
редукций, `reshape`, `transpose` и `expand_dims`.

```bash
uv run --locked python phases/02-numpy/02-shape-and-axes/code/main.py
```

## Поставьте результат

Артефакт `outputs/shape_contract.py` предоставляет:

- `normalize_axes`;
- `reduction_shape`;
- `reshape_shape`;
- `transpose_shape`;
- `expand_dims_shape`;
- `assert_shape`;
- CLI с JSON-отчётом.

Пример проверки внутри аналитической функции:

```python
features = np.zeros((100, 8))
shape_contract.assert_shape(features, (100, 8), name="features")
```

Именованная ошибка сообщает не только фактическую форму, но и роль массива.

## Упражнения

1. Добавьте поддержку нескольких осей в CLI через JSON-аргумент `--axes`.
2. Предскажите формы `x[:, None, :]`, `x.squeeze()` и `x.T` для `x.shape == (2, 1, 3)`,
   затем проверьте ответы в NumPy.
3. Добавьте функцию `squeeze_shape`, которая удаляет только оси длины `1` и отклоняет
   попытку удалить любую другую ось.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Ось | «Строка или столбец» | Позиция в упорядоченной форме массива |
| Отрицательная ось | «Другая ось» | Индекс оси, отсчитанный с конца |
| Редукция | «Любое уменьшение массива» | Операция, сворачивающая выбранные оси |
| `keepdims` | «Не выполнять редукцию» | Сохранить редуцированные оси с длиной `1` |
| `reshape` | «Добавить или удалить данные» | Изменить форму без изменения числа элементов |
| `transpose` | «Развернуть значения» | Переставить оси в заданном порядке |

## Дополнительное чтение

- [numpy.reshape](https://numpy.org/doc/stable/reference/generated/numpy.reshape.html) — официальный контракт формы, `-1`, порядка индексов и возможного копирования.
- [numpy.expand_dims](https://numpy.org/doc/stable/reference/generated/numpy.expand_dims.html) — точные правила вставки новой оси и связь с `np.newaxis`.
- [Indexing on ndarrays](https://numpy.org/doc/stable/user/basics.indexing.html) — раздел про целочисленные индексы, срезы и изменение размерности результата.
- [numpy.mean](https://numpy.org/doc/stable/reference/generated/numpy.mean.html) — поведение `axis`, нескольких осей и `keepdims` у реальной редукции.
