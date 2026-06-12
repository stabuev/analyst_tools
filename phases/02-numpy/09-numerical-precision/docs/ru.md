# Численная точность и сравнение результатов

> Численный тест требует допуска, выбранного из масштаба и цены ошибки; `allclose` без методологии лишь заменяет одно магическое число двумя.

**Тип:** Case
**Треки:** Core
**Пререквизит:** `02-numpy/08-vectorization`
**Время:** ~60 минут
**Результат:** использует tolerances и распознает overflow, underflow и ошибки float.

## Цели обучения

- объяснить ошибку представления floating-point;
- выбирать `rtol` и `atol` для численного контракта;
- обнаруживать integer overflow до вычисления;
- задавать политику деления на ноль и не конечных значений;
- использовать аккумулятор повышенной точности.

## Проблема

Тест финансового расчёта падает:

```python
assert 0.1 + 0.2 == 0.3
```

Разработчик заменяет его на широкий `allclose` и тест становится зелёным, но теперь может
пропустить реальную ошибку. В другом расчёте `int8` переполняется, а деление на ноль
оставляет `inf`, который доходит до итоговой метрики.

Численная надёжность требует нескольких независимых контрактов:

- формы совпадают;
- значения конечны там, где обязаны быть конечны;
- integer результат помещается в диапазон;
- floating результат находится в предметно обоснованном допуске;
- невалидные операции имеют явную политику.

## Концепция

### Floating-point является приближением

Большинство десятичных дробей нельзя точно представить конечной двоичной дробью.

```python
0.1 + 0.2
# 0.30000000000000004
```

Ошибка зависит от представления, порядка операций, dtype и масштаба.

### Относительный и абсолютный допуски

NumPy проверяет приближённое равенство по формуле:

```text
abs(actual - expected) <= atol + rtol * abs(expected)
```

- `rtol` масштабируется относительно эталона;
- `atol` задаёт абсолютный порог и особенно важен около нуля.

`expected` играет роль reference, поэтому формула не полностью симметрична.

### Переполнение и underflow

Integer dtype имеет жёсткий диапазон. Результат за его пределами не представим.

Для float overflow приводит к `inf`, а underflow может превратить очень малое значение в
ноль или subnormal. Предупреждение не является политикой обработки.

## Соберите это

### Ручная проверка допуска

```python
def is_close(actual, expected, rtol, atol):
    error = abs(actual - expected)
    allowed = atol + rtol * abs(expected)
    return error <= allowed
```

```python
assert is_close(0.1 + 0.2, 0.3, rtol=1e-9, atol=1e-12)
```

Около нуля:

```python
assert not is_close(1e-9, 0.0, rtol=1e-5, atol=0.0)
assert is_close(1e-9, 0.0, rtol=1e-5, atol=1e-8)
```

### Проверка integer результата

До преобразования сложите значения как Python integers и сравните с границами:

```python
info = np.iinfo(np.int8)
result = 120 + 20

if result < info.min or result > info.max:
    raise OverflowError("result is outside int8")
```

### Политика деления

```python
valid = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0)
```

Если есть `False`, функция должна либо завершиться ошибкой, либо заполнить эти позиции
явно выбранным значением.

## Используйте это

### Сравнение массивов

```python
actual = np.array([0.1 + 0.2, 10.0])
expected = np.array([0.3, 10.0])

np.testing.assert_allclose(
    actual,
    expected,
    rtol=1e-9,
    atol=1e-12,
)
```

Для production-теста сначала зафиксируйте:

- единицы измерения;
- масштаб типичных значений;
- максимально допустимое бизнес-отклонение;
- эталонный способ расчёта.

### Контроль floating ошибок

```python
with np.errstate(divide="raise", invalid="raise", over="raise"):
    result = numerator / denominator
```

Контекст превращает выбранные категории floating ошибок в `FloatingPointError`. Он не
решает, что делать с ошибкой, а делает её наблюдаемой.

### Аккумулятор

```python
values = np.array([1e8, 1.0, -1e8], dtype=np.float32)

low_precision = np.sum(values, dtype=np.float32)
higher_precision = np.sum(values, dtype=np.float64)
```

Использование `float64` для аккумулятора может уменьшить ошибку, хотя не восстанавливает
информацию, уже потерянную при хранении исходных значений.

### Интеграционный quality gate

```bash
uv run --locked python phases/02-numpy/09-numerical-precision/outputs/numerical_checks.py \
  --actual '[0.30000000000000004, 10.0]' \
  --expected '[0.3, 10.0]' \
  --rtol 1e-9 \
  --atol 1e-12
```

Артефакт объединяет темы фазы:

- shape-контракт перед сравнением;
- dtype и integer range;
- broadcasting в безопасном делении;
- агрегирование с контролируемым аккумулятором;
- численные behavioral checks.

## Сломайте это

### Сравнить float через ==

Точное равенство подходит для значений, которые обязаны быть точными, например некоторых
integer результатов. Для вычисленных float оно часто проверяет детали представления, а
не контракт задачи.

### Оставить default atol около нуля

Универсального default нет. Значение `1e-8` может быть ничтожным для выручки в миллионах
и огромным для вероятности порядка `1e-10`.

### Разрешить broadcasting в тесте незаметно

Сравнение форм `(2,)` и `(1, 2)` может broadcast-иться, хотя downstream-контракт формы
нарушен. Артефакт сначала требует точного совпадения shapes.

### Игнорировать integer overflow

```python
values = np.array([120], dtype=np.int8)
result = values + np.array([20], dtype=np.int8)
```

Перед операцией, где диапазон может быть превышен, расширьте dtype или проверьте границы.

### Подавить warning без политики

```python
with np.errstate(all="ignore"):
    ratio = numerator / denominator
```

Код становится тихим, но `NaN` и `inf` остаются. Проверяйте `np.isfinite` и документируйте
замену или отказ.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/02-numpy/09-numerical-precision/tests \
  -v
```

Тесты покрывают округление `0.1 + 0.2`, значения около нуля, несовпадающие формы,
деление на ноль, integer overflow и точность суммирования.

```bash
uv run --locked python phases/02-numpy/09-numerical-precision/code/main.py
```

После этого запустите все уроки фазы:

```bash
uv run --locked python scripts/run_lesson_tests.py
```

## Поставьте результат

`outputs/numerical_checks.py` предоставляет:

- `tolerance_report`;
- `assert_numerically_close`;
- `safe_divide`;
- `checked_integer_add`;
- `summation_report`;
- интеграционный JSON CLI.

Пример использования в расчёте:

```python
assert_numerically_close(
    actual_revenue,
    expected_revenue,
    rtol=1e-10,
    atol=0.01,
)
```

Здесь абсолютный допуск в одну копейку должен следовать из единиц и правил округления
конкретной задачи, а не копироваться механически.

## Упражнения

1. Подберите допуски для доли, денежной суммы и стандартизованного признака и обоснуйте
   каждый выбор.
2. Добавьте в `tolerance_report` индексы первых пяти несовпавших элементов.
3. Реализуйте безопасное умножение integer-массивов с предварительной проверкой диапазона.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Floating-point error | «Случайная поломка процессора» | Ошибка представления и операций над конечной сеткой чисел |
| `rtol` | «Допуск в абсолютных единицах» | Относительный допуск, масштабируемый эталонным значением |
| `atol` | «Процент ошибки» | Абсолютный допуск в единицах результата |
| Overflow | «Слишком большой массив» | Результат вне представимого диапазона dtype |
| Underflow | «Отрицательное значение» | Слишком малый по модулю floating результат |
| `errstate` | «Исправление вычисления» | Локальная политика реакции на floating ошибки |

## Дополнительное чтение

- [numpy.allclose](https://numpy.org/doc/stable/reference/generated/numpy.allclose.html) — точная формула допусков, асимметрия и предупреждение о default `atol`.
- [numpy.testing.assert_allclose](https://numpy.org/doc/stable/reference/generated/numpy.testing.assert_allclose.html) — assertion для численных тестов и диагностические сообщения.
- [numpy.errstate](https://numpy.org/doc/stable/reference/generated/numpy.errstate.html) — локальное управление divide, over, under и invalid.
- [What every computer scientist should know about floating-point arithmetic](https://docs.oracle.com/cd/E19957-01/806-3568/ncg_goldberg.html) — классический первичный разбор представления, округления и накопления ошибок.
