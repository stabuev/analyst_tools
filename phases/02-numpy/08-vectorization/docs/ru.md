# Векторизация и производительность

> Сначала докажите эквивалентность формул, затем измеряйте несколько повторов и сообщайте границы benchmark.

**Тип:** Case
**Треки:** Core
**Пререквизит:** `02-numpy/07-random-simulations`
**Время:** ~75 минут
**Результат:** заменяет цикл векторной операцией и корректно измеряет ускорение.

## Цели обучения

- переписать поэлементный цикл как выражение над массивами;
- проверить численную эквивалентность реализаций;
- отделить подготовку входов от измеряемого расчёта;
- использовать warm-up, повторы и медиану;
- не превращать наблюдаемый speedup в нестабильный тест.

## Проблема

Для каждой позиции заказа нужно рассчитать выручку после скидки:

```text
price * quantity * (1 - discount)
```

Обычный цикл понятен, но на сотнях тысяч элементов тратит время на интерпретацию каждой
итерации Python. NumPy может выполнить ту же поэлементную формулу в скомпилированных
циклах.

Однако короткий векторный код ещё не доказывает:

- что формула совпадает;
- что измеряется одинаковый объём работы;
- что результат быстрее на целевом размере;
- что память не стала новым ограничением.

## Концепция

Векторизация означает выражение операции над целыми массивами:

```python
revenue = prices * quantities * (1.0 - discounts)
total = revenue.sum()
```

Внутренние циклы остаются, но выполняются библиотекой над однородной памятью.

### Контракт benchmark

Корректное сравнение фиксирует:

1. одинаковые входные значения;
2. одинаковую формулу и точность результата;
3. границы измерения;
4. warm-up перед замерами;
5. несколько повторов;
6. устойчивую статистику, например медиану;
7. размер данных, seed, версии и среду.

## Соберите это

### Циклический baseline

```python
def python_net_revenue(prices, quantities, discounts):
    total = 0.0
    for price, quantity, discount in zip(
        prices,
        quantities,
        discounts,
        strict=True,
    ):
        total += price * quantity * (1.0 - discount)
    return total
```

`strict=True` не позволяет тихо отбросить хвост более длинной последовательности.

### Векторная формула

```python
def numpy_net_revenue(prices, quantities, discounts):
    line_revenue = prices * quantities * (1.0 - discounts)
    return float(np.sum(line_revenue, dtype=np.float64))
```

### Проверка результата

```python
np.testing.assert_allclose(
    python_result,
    numpy_result,
    rtol=1e-12,
    atol=1e-8,
)
```

Из-за другого порядка сложения последние биты могут различаться. Это не повод применять
точное `==`.

## Используйте это

```python
import time


def measure(function, repeat):
    function()  # warm-up
    durations = []
    for _ in range(repeat):
        started = time.perf_counter()
        function()
        durations.append(time.perf_counter() - started)
    return statistics.median(durations)
```

В уроке преобразование ndarray в списки выполняется до замеров. Scope явно равен
«расчёт на уже подготовленном представлении». Для end-to-end вопроса нужно включить
загрузку и преобразования в обе ветки.

Запустите benchmark:

```bash
uv run --locked python phases/02-numpy/08-vectorization/outputs/vectorization_benchmark.py \
  --size 100000 \
  --repeat 7 \
  --seed 42
```

Результат содержит:

- проверенную сумму;
- все отдельные времена;
- медианы;
- отношение медиан;
- описание измеряемого scope.

Повторите для нескольких размеров:

```bash
for size in 100 10000 1000000; do
  uv run --locked python \
    phases/02-numpy/08-vectorization/outputs/vectorization_benchmark.py \
    --size "$size" \
    --repeat 7 \
    --seed 42
done
```

На малых данных накладные расходы NumPy могут быть заметны. На больших проявляется
преимущество скомпилированного цикла, но точные числа зависят от машины.

## Сломайте это

### Сравнить разные формулы

Если loop применяет скидку до умножения количества, а vectorized версия после, benchmark
сравнивает не производительность, а разные расчёты. Сверка результата должна происходить
до тайминга.

### Один запуск

Первый вызов может отличаться из-за cold caches, фоновой нагрузки и инициализации. Один
результат не позволяет оценить разброс.

### Включить преобразование только с одной стороны

```python
time(np.asarray(values) * 2)
time([value * 2 for value in values])
```

Первый замер включает создание ndarray, второй работает на готовом списке. Это может быть
валидным end-to-end вопросом, но scope нужно назвать, а не выдавать за чистую скорость
арифметики.

### Требовать speedup в тесте

```python
assert speedup > 10
```

Такой тест зависит от железа и нагрузки CI. Behavioral tests должны проверять
эквивалентность, положительные измерения и структуру отчёта. Performance regression
требует контролируемой среды и отдельной политики.

### Создать огромный intermediate

Векторизация нескольких выражений может выделить временные массивы. Если память важнее
Python overhead, рассмотрите chunking, `out=`, специализированный алгоритм или внешний
цикл по крупным блокам.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/02-numpy/08-vectorization/tests \
  -v
```

Тесты не закрепляют конкретное ускорение. Они проверяют формулу, воспроизводимые входы,
валидацию размеров, повторы и метаданные benchmark.

```bash
uv run --locked python phases/02-numpy/08-vectorization/code/main.py
```

## Поставьте результат

`outputs/vectorization_benchmark.py` является переносимым сравнением:

```bash
uv run --locked python phases/02-numpy/08-vectorization/outputs/vectorization_benchmark.py \
  --size 500000 \
  --repeat 9 \
  --seed 2026 \
  --output /tmp/vectorization-benchmark.json
```

При передаче результата укажите CPU, ОС, версию Python, версию NumPy и состояние нагрузки.
JSON без контекста машины не является универсальной характеристикой библиотеки.

## Упражнения

1. Постройте таблицу медианного времени для трёх размеров и объясните изменение speedup.
2. Добавьте реализацию с `np.dot(prices * (1 - discounts), quantities)` и проверьте
   эквивалентность.
3. Измерьте end-to-end сценарий, включающий преобразование списков в ndarray, и сравните
   вывод с calculation-only benchmark.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Векторизация | «Обязательно SIMD или GPU» | Выражение операции через array API вместо Python-цикла по элементам |
| Baseline | «Заведомо плохой код» | Прозрачная эталонная реализация для сверки |
| Warm-up | «Подгонка результата» | Неизмеряемый предварительный запуск |
| Медиана | «Среднее всех значений» | Центральное значение, устойчивое к отдельным выбросам времени |
| Speedup | «Гарантия библиотеки» | Отношение времён в конкретном benchmark и среде |
| Scope | «Размер массива» | Точная граница работы, включённой в измерение |

## Дополнительное чтение

- [Universal functions basics](https://numpy.org/doc/stable/user/basics.ufuncs.html) — устройство поэлементных ufunc, broadcasting, `out` и редукций.
- [NumPy CPU/SIMD optimizations](https://numpy.org/doc/stable/reference/simd/index.html) — официальный обзор аппаратных оптимизаций и runtime dispatch.
- [Python time.perf_counter](https://docs.python.org/3/library/time.html#time.perf_counter) — монотонный высокоточный таймер для коротких измерений.
- [Python timeit](https://docs.python.org/3/library/timeit.html) — стандартный инструмент повторяемых микроbenchmark и его ограничения.
