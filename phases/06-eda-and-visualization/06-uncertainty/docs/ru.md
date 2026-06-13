# Неопределенность на графике

> Показывайте не только оценку, но и то, насколько она меняется при повторном наблюдении сопоставимых пользователей.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 06/05  
**Время:** ~90 минут  
**Результат:** различает разброс данных и неопределенность оценки, воспроизводимо строит
bootstrap-интервалы и показывает interval, sample size и единицу ресемплирования.

## Цели обучения

- Различать variation наблюдений и uncertainty estimator.
- Ресемплировать пользователей, сохраняя grain.
- Фиксировать seed, repeats, confidence и source coverage.
- Показывать estimate, interval и `n` вместе.

## Проблема

Две недели могут иметь activation `60%`, но одна основана на 20 пользователях, другая -
на 20 000. Одна точка не показывает устойчивость оценки. При этом error bar без
описанного метода может означать standard deviation, standard error или confidence
interval.

## Концепция

Percentile bootstrap повторяет следующий механизм:

1. взять `n` пользователей с возвращением;
2. пересчитать activation rate;
3. повторить много раз;
4. взять квантили bootstrap estimates.

Единица ресемплирования должна совпадать с независимым grain. Нельзя ресемплировать
отдельные столбцы пользователя или уже агрегированные пиксели.

Bootstrap здесь визуализирует изменчивость оценки. Систематический bias, неправильный
знаменатель и causal identification он не исправляет.

## Соберите это

Минимальная версия использует `random.choices`:

```bash
uv run --locked python code/main.py
```

Она возвращает observed estimate, квантили draws и явно называет unit `user`.

## Используйте это

```bash
uv run --locked python outputs/bootstrap_visualizer.py \
  --input ../data/tiny/user_journeys.csv \
  --output-dir uncertainty-output \
  --seed 20260613
```

Артефакт сравнивает периоды до и после релиза, подписывает `n`, экспортирует таблицу
интервалов и provenance. SHA-256 списка user IDs доказывает, какие строки покрыты.

## Сломайте это

1. Не фиксируйте seed.
2. Включите неполные observation windows как false.
3. Ресемплируйте строки до удаления дубликата.
4. Подпишите interval просто как `error`.
5. Сравните группы без sample size.

## Проверьте это

- одинаковый seed воспроизводит interval;
- observed estimate лежит между границами;
- сумма group sizes равна числу исходных пользователей;
- Figure использует rate domain `[0, 1]`;
- report фиксирует unit, repeats, confidence и coverage.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/bootstrap_visualizer.py` поставляет PNG, `intervals.csv` и
`bootstrap-report.json`. Артефакт пригоден для ревью метода и повторного расчета.

## Упражнения

1. Сравните percentile и basic bootstrap intervals.
2. Добавьте стратифицированный bootstrap по acquisition channel.
3. Исследуйте coverage симуляцией на известной Bernoulli probability.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Variability | Ширина CI | Разброс отдельных наблюдений |
| Uncertainty | Min-max данных | Изменчивость оценки |
| Resampling unit | Любая строка | Независимая единица выборочного механизма |
| Percentile interval | Квантили данных | Квантили bootstrap estimates |
| Coverage | Число пикселей | Наблюдения, вошедшие в расчет |

## Дополнительное чтение

- [Seaborn: Statistical estimation and error bars](https://seaborn.pydata.org/tutorial/error_bars.html) - сравните spread и uncertainty intervals.
- [NumPy: Generator.choice](https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.choice.html) - изучите воспроизводимое ресемплирование по индексам.
- [Bootstrap Methods and Their Application](https://www.cambridge.org/core/books/bootstrap-methods-and-their-application/ED2FD043579F27952363566DC09CBD6A) - используйте как первичный источник для границ метода.
