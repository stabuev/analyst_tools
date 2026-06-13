# Связи между переменными

> Видимая связь должна воспроизводиться контрольной таблицей и сохраняться после разумной стратификации.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 06/04  
**Время:** ~90 минут  
**Результат:** выбирает представление по типам переменных, обнаруживает overplotting и
смешение сегментов и проверяет видимую связь стратифицированным расчетом.

## Цели обучения

- Подбирать representation по типам переменных.
- Обнаруживать перекрывающиеся наблюдения.
- Сверять график с групповой control table.
- Различать aggregate association и связь внутри сегментов.

## Проблема

`sessions_7d` дискретна, а `activated_7d` бинарна. Обычный scatter покажет несколько
десятков координат независимо от числа пользователей: сотни строк могут лежать друг на
друге. Общая линия также смешивает web, iOS и Android с разными baseline.

## Концепция

Для binary outcome raw observations полезны вместе с:

- прозрачностью или jitter для плотности;
- grouped rate по каждому значению `sessions_7d`;
- sample size в каждой группе;
- стратификацией по потенциальному confounder.

Стратификация не доказывает причинность. Она проверяет, не исчезает ли aggregate pattern,
когда сравнение проводится внутри более однородных групп.

## Соберите это

Ручная версия группирует boolean outcomes по числу сессий:

```bash
uv run --locked python code/main.py
```

Rate должен быть воспроизводим как `sum(activated) / n`, а weighted rates всех групп
должны совпасть с общей долей.

## Используйте это

```bash
uv run --locked python outputs/relationship_explorer.py \
  --input ../data/tiny/user_journeys.csv \
  --output-dir relationship-output
```

Левая область показывает user-level observations с детерминированным jitter. Правая -
activation rate по sessions отдельно для каждой platform. `control-table.csv` хранит
rates и `users`, а JSON считает число скрытых совпадений координат.

## Сломайте это

1. Уберите jitter и alpha.
2. Постройте только aggregate line без platform.
3. Не показывайте число пользователей в control table.
4. Назовите паттерн «эффектом числа сессий».

Последний пункт недопустим: sessions и activation могут зависеть от общей вовлеченности,
канала или качества приложения.

## Проверьте это

- очищенный срез имеет уникальных пользователей и полные окна;
- weighted strata reconcile с общей activation;
- overplotting измерен;
- jitter воспроизводится по seed;
- report помечен `association_only=true`.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/relationship_explorer.py` поставляет PNG, control table и JSON report. Эти три
файла связывают видимый паттерн, исходные наблюдения и проверяемые агрегаты.

## Упражнения

1. Добавьте разрез по acquisition channel.
2. Перейдите на hexbin для двух continuous variables в sample profile.
3. Найдите пример, где aggregate и stratified directions различаются.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Overplotting | Слишком много графиков | Скрытие наблюдений совпадающими marks |
| Jitter | Изменение данных | Воспроизводимое визуальное смещение |
| Stratification | Причинная поправка | Сравнение внутри уровней сегмента |
| Control table | Дублирование графика | Числовая проверка visual pattern |
| Association | Эффект | Совместная изменчивость без causal design |

## Дополнительное чтение

- [Matplotlib: Scatter plot](https://matplotlib.org/stable/api/_as_gen/matplotlib.axes.Axes.scatter.html) - изучите alpha, size и ограничения плотных данных.
- [Vega-Lite: Binning](https://vega.github.io/vega-lite/docs/bin.html) - сравните raw points и агрегированное представление плотности.
- [The Datasaurus Dozen](https://www.autodesk.com/research/publications/same-stats-different-graphs) - посмотрите, почему одинаковые summaries не заменяют форму связи.
