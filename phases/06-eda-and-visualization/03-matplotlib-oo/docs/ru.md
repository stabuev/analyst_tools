# Воспроизводимая фигура с Matplotlib

> Figure является поставляемым объектом, поэтому данные, Axes, шкалы и экспорт должны быть явными.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 06/02  
**Время:** ~75 минут  
**Результат:** строит детерминированную многоосевую фигуру через явные Figure и Axes,
управляет шкалами и layout и экспортирует PNG и SVG с manifest.

## Цели обучения

- Разделять `Figure`, `Axes` и графические элементы.
- Строить композицию через явные объекты вместо скрытого pyplot-state.
- Показывать значение метрики рядом с ее знаменателем.
- Экспортировать PNG и SVG вместе с параметрами и checksums.

## Проблема

В ноутбуке несколько вызовов `plt.plot()` могут случайно рисовать на текущей области,
наследовать стиль предыдущей ячейки и сохраняться с другим layout. Передача одной PNG
не объясняет, какие данные, размер, DPI и шкалы создали картинку.

## Концепция

`Figure` хранит всю композицию. Каждый `Axes` имеет собственные шкалы, labels и artists.
Для activation нужны две согласованные области:

1. доля по cohort week на полном домене `[0, 1]`;
2. число пользователей в каждой когорте.

Layout и export являются частью контракта, а не ручной доводкой после расчета.

## Соберите это

Создайте Figure без глобального state:

```python
figure = Figure(figsize=(8, 3), layout="constrained")
trend_axis, count_axis = figure.subplots(1, 2)
```

Каждое изменение адресовано конкретному Axes:

```python
trend_axis.plot(weeks, activation, marker="o")
trend_axis.set(ylabel="Доля activation_7d", ylim=(0, 1))
count_axis.bar(weeks, users)
```

```bash
uv run --locked python code/main.py
```

## Используйте это

Фабрика читает только пользователей с полным окном, удаляет повторную доставку, строит
контрольную таблицу и экспортирует два формата:

```bash
uv run --locked python outputs/figure_factory.py \
  --input ../data/tiny/user_journeys.csv \
  --output-dir figure-output
```

PNG удобен для документов, SVG сохраняет векторную структуру. `manifest.json` содержит
backend, размер, DPI, диапазон activation, число когорт и SHA-256 обоих файлов.

## Сломайте это

1. Уберите `ylim=(0, 1)` и сравните визуальное впечатление.
2. Постройте count и rate на одной dual axis: смысл станет менее проверяемым.
3. Сохраните SVG без удаления даты metadata: bytes перестанут быть воспроизводимыми.
4. Не закрывайте Figure в batch-процессе: память будет расти.

## Проверьте это

Тесты проверяют объекты, а не пиксельный snapshot:

- ровно два Axes;
- labels и честная шкала rate;
- наличие denominator;
- PNG/SVG и совпадение checksums.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/figure_factory.py` - CLI-фабрика статической фигуры. Она поставляет
`activation-overview.png`, `activation-overview.svg` и manifest, достаточный для
повторного экспорта и ревью.

## Упражнения

1. Добавьте общий legend без дублирования на каждом Axes.
2. Экспортируйте control table в CSV рядом с фигурой.
3. Добавьте параметр business release date.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Figure | Сам график | Контейнер всей композиции |
| Axes | Ось x или y | Область данных со шкалами и artists |
| Artist | Только линия | Любой отрисовываемый элемент |
| DPI | Качество анализа | Плотность растрового экспорта |
| Manifest | Подпись картинки | Машинный контракт параметров и файлов |

## Дополнительное чтение

- [Matplotlib: Application Interfaces](https://matplotlib.org/stable/users/explain/figure/api_interfaces.html) - сравните explicit и implicit interfaces.
- [Matplotlib: Figure API](https://matplotlib.org/stable/api/figure_api.html) - изучите композицию, layout и методы экспорта Figure.
- [Matplotlib: Saving figures](https://matplotlib.org/stable/users/explain/figure/backends.html) - разберите backend и различия растровых и векторных форматов.
