# Статистические сравнения с Seaborn

> Высокоуровневый API экономит код, но estimator, interval и facet остаются частью методологии.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 06/06  
**Время:** ~90 минут  
**Результат:** воспроизводит распределения, связи и оценки через dataset-oriented API,
явно задает estimator, errorbar и facets и дорабатывает результат через Matplotlib Axes.

## Цели обучения

- Связывать поля DataFrame с semantic roles.
- Явно задавать estimator и errorbar.
- Использовать facets как согласованные small multiples.
- Проверять Seaborn-оценки числовой control table.

## Проблема

Один вызов `sns.catplot()` может построить mean и interval, но default не объясняет
читателю метод. Без явной фиксации нельзя понять, показан spread данных или uncertainty
mean, сколько bootstrap draws использовано и одинаков ли порядок периодов.

## Концепция

Seaborn принимает long-form dataset и mapping:

```text
x=period, y=activated_7d, col=platform
```

Figure-level `catplot` создает `FacetGrid`, а каждый facet остается Matplotlib Axes.
Поэтому статистическую семантику задает Seaborn, а шкалы, labels и grid проверяются через
явные Axes.

## Соберите это

Сначала создайте control pivot:

```bash
uv run --locked python code/main.py
```

Он показывает, какие значения должны появиться в панелях до вызова plotting API.

## Используйте это

```bash
uv run --locked python outputs/seaborn_panel.py \
  --input ../data/tiny/user_journeys.csv \
  --output-dir seaborn-output
```

Артефакт фиксирует `estimator="mean"`, `errorbar=("ci", 95)`, `n_boot`, seed,
period order и platform order. JSON сохраняет семантику, CSV - estimates и sample sizes.

## Сломайте это

1. Уберите `order` и измените порядок категорий во входе.
2. Замените CI на SD, не меняя подпись.
3. Смешайте платформы одной линией.
4. Не сохраните control table.

## Проверьте это

- три facet соответствуют web, iOS, Android;
- outcome имеет значения 0/1;
- y-domain равен `[0, 1]`;
- estimator и errorbar записаны в report;
- control table содержит estimate и users.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/seaborn_panel.py` поставляет статистическую панель, control table и report с
параметрами estimator и uncertainty.

## Упражнения

1. Сравните `errorbar="sd"` и `errorbar=("ci", 95)`.
2. Добавьте row facet по acquisition channel.
3. Воспроизведите estimates независимым `groupby`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Dataset-oriented API | Автоматически правильный анализ | Mapping полей на semantic roles |
| Estimator | Любая линия | Функция агрегирования observations |
| Errorbar | Универсальная ошибка | Явно выбранная семантика spread или uncertainty |
| Facet | Несвязанный subplot | Small multiple по уровню переменной |
| FacetGrid | Только Seaborn | Контейнер Matplotlib Figure/Axes |

## Дополнительное чтение

- [Seaborn: Statistical estimation and error bars](https://seaborn.pydata.org/tutorial/error_bars.html) - сравните parametric и nonparametric intervals.
- [Seaborn: catplot](https://seaborn.pydata.org/generated/seaborn.catplot.html) - изучите figure-level API, facets и параметры estimator.
- [Seaborn: Data structures](https://seaborn.pydata.org/tutorial/data_structure.html) - разберите long-form и wide-form datasets.
