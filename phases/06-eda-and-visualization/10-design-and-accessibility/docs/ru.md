# Дизайн, цвет и доступность

> Дизайн хорош, когда смысл сохраняется без догадок, цвета и устного комментария автора.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 06/09  
**Время:** ~75 минут  
**Результат:** выбирает шкалу, baseline, порядок, подписи и perceptually uniform palette
и дублирует смысл цвета формой, текстом или структурой.

## Цели обучения

- Проверять baseline и domain визуальной шкалы.
- Выбирать palette type по семантике данных.
- Дублировать цвет текстом, формой или facets.
- Поставлять title, source, alt text и data download.

## Проблема

Технически корректный график может быть недоступен: красная и зеленая линии отличаются
только цветом, bar chart начинается с `0.55`, мелкий текст невозможно прочитать, а title
называет тему вместо вывода. Pixel-аудит не знает business meaning, поэтому требования
нужно записать как review contract.

## Концепция

Visual review проверяет четыре слоя:

1. сообщение: title и decision purpose;
2. evidence: source, axes, domain, uncertainty и sample size;
3. perception: palette, order, baseline, font;
4. alternatives: redundant channel, alt text и downloadable data.

Sequential palette кодирует порядок, diverging - отклонение от meaningful center,
categorical - различающиеся уровни без порядка.

## Соберите это

Ручной пример рассчитывает contrast ratio относительных luminance:

```bash
uv run --locked python code/main.py
```

Контраст текста важен, но не решает проблему color-only meaning.

## Используйте это

```bash
uv run --locked python outputs/visual_review.py --example
```

Для своего chart создайте JSON review и передайте `--review`. CLI возвращает `0` для
готового графика, `1` для нарушенного checklist и `2` для нечитаемого контракта.

## Сломайте это

1. Установите `color_only=true`.
2. Обрежьте rate domain до `[0.55, 0.75]`.
3. Для bar chart задайте baseline `0.5`.
4. Уберите interval semantics или sample size.
5. Оставьте alt text «График активации».

## Проверьте это

- example проходит все checks;
- color-only и truncated rate scale падают;
- bar требует zero baseline;
- estimate требует uncertainty semantics и `n`;
- CLI имеет стабильные exit codes.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/visual_review.py` - machine-readable review checklist. Его report можно хранить
рядом с фигурой и включать в delivery manifest.

## Упражнения

1. Добавьте проверку contrast ratio для текстовых элементов.
2. Введите правила direct labels для двух линий.
3. Добавьте localization check для decimal и date formats.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Baseline | Нижний край картинки | Нулевая или содержательная точка сравнения |
| Perceptual palette | Красивые цвета | Шкала с предсказуемым восприятием порядка |
| Redundant channel | Дублирование данных | Повтор смысла цветом и другим каналом |
| Alt text | Название файла | Текстовое описание формы и сообщения |
| Data download | Лишнее приложение | Альтернативный проверяемый доступ к значениям |

## Дополнительное чтение

- [WCAG 2.2: Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html) - изучите требование не полагаться только на цвет.
- [WCAG 2.2: Contrast Minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html) - разберите пороги контраста текста.
- [Matplotlib: Choosing colormaps](https://matplotlib.org/stable/users/explain/colors/colormaps.html) - сопоставьте sequential, diverging и qualitative palettes.
- [Government Analysis Function: Accessibility](https://analysisfunction.civilservice.gov.uk/policy-store/data-visualisation-accessibility/) - проверьте title, alt text, source и альтернативные данные.
