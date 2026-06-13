# Декларативная спецификация с Altair

> Когда типы полей и encodings записаны в JSON, семантическую ошибку можно найти до рендера.

**Тип:** Learn  
**Треки:** Core  
**Пререквизиты:** 06/08  
**Время:** ~75 минут  
**Результат:** описывает mark, encodings, типы полей, transforms и selection parameters
как проверяемую Vega-Lite-спецификацию и находит ошибочную семантику до рендера.

## Цели обучения

- Объявлять mark и semantic field types.
- Читать compiled Vega-Lite JSON.
- Связывать views named selection parameter.
- Проверять encodings и transforms структурными тестами.

## Проблема

Императивный код может успешно нарисовать `sessions_7d` как категории, хотя вопрос
требует количественную шкалу. Ошибка выглядит правдоподобно и обнаруживается только при
чтении графика. В декларативной spec тип поля является проверяемым значением.

## Концепция

Altair описывает:

```text
data + mark + encoding + transform + parameter
```

`sessions_7d:Q` означает quantitative, `platform:N` - nominal, `cohort_week:T` -
temporal. Named interval parameter `journey_brush` создается в scatter, а bar view
использует `transform_filter`.

## Соберите это

Минимальная ручная spec:

```bash
uv run --locked python code/main.py
```

Даже без рендера видно, какие поля попали в `x`, `y` и `color`.

## Используйте это

```bash
uv run --locked python outputs/chart_spec_builder.py \
  --input ../data/tiny/user_journeys.csv \
  --output linked-segments.vl.json
```

CLI вызывает Altair schema validation и дополнительный semantic validator. Результат
содержит scatter, linked bar view, tooltip и interval selection.

## Сломайте это

1. Замените `sessions_7d:Q` на `:N`.
2. Удалите named parameter.
3. Оставьте bar view без `transform_filter`.
4. Назначьте `cohort_week` nominal type.

Каждая ошибка должна быть видна в JSON или semantic report до браузера.

## Проверьте это

- spec проходит Altair validation;
- semantic types явны;
- есть `journey_brush`;
- вторая view фильтруется parameter;
- неверный type обнаруживается unit test.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/chart_spec_builder.py` поставляет валидированную `.vl.json` specification. Ее
можно хранить в Git, проверять diff и рендерить совместимым Vega-Lite runtime.

## Упражнения

1. Добавьте conditional color для selected points.
2. Свяжите временной overview и detail chart.
3. Введите validator против aggregate без sample size.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Declarative spec | Список draw calls | Описание отображения данных |
| Semantic type | Python dtype | Роль поля в visual grammar |
| Encoding | Цветовая настройка | Mapping field на visual channel |
| Parameter | CLI-аргумент | Named signal для interaction |
| Transform filter | pandas filter | Декларативное преобразование view |

## Дополнительное чтение

- [Altair: Encodings](https://altair-viz.github.io/user_guide/encodings/index.html) - изучите field types и channels.
- [Altair: Parameters and conditions](https://altair-viz.github.io/user_guide/interactions/parameters.html) - разберите selection parameters и linked views.
- [Vega-Lite Specification](https://vega.github.io/vega-lite/docs/spec.html) - сопоставьте top-level и composite specifications.
