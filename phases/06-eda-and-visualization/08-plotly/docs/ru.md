# Интерактивный drill-down с Plotly

> Интерактивность оправдана, когда она помогает перейти от паттерна к конкретному наблюдению.

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 06/07  
**Время:** ~75 минут  
**Результат:** добавляет hover и управляемый drill-down только там, где они раскрывают
отдельные наблюдения, и экспортирует воспроизводимый standalone HTML без Dash.

## Цели обучения

- Формулировать задачу интерактивности.
- Ограничивать hover необходимым контекстом.
- Делать drill-down по заранее выбранной dimension.
- Проверять Figure через JSON без браузера.

## Проблема

Статическая панель показывает длинный хвост onboarding, но не позволяет быстро найти
пользователя, платформу, версию и cohort конкретной точки. Добавление всех возможных
filters и tooltips превращает график в интерфейс без вопроса.

## Концепция

Plotly Figure содержит `data` traces и `layout`. Для anomaly explorer:

- одна trace на platform;
- `customdata` хранит минимальный диагностический контекст;
- `hovertemplate` явно перечисляет отображаемые поля;
- dropdown управляет видимостью traces;
- HTML включает plotly.js и работает без сервера.

## Соберите это

Сначала определите контракт hover как словарь полей:

```bash
uv run --locked python code/main.py
```

Идентификатор нужен для расследования, но tooltip не должен копировать всю строку.

## Используйте это

```bash
uv run --locked python outputs/anomaly_explorer.py \
  --input ../data/tiny/user_journeys.csv \
  --output-dir interactive-output
```

CLI сохраняет standalone HTML, Plotly JSON и report. JSON проверяет traces, customdata,
axis titles и dropdown без pixel snapshots.

## Сломайте это

1. Используйте CDN вместо embedded plotly.js и откройте offline.
2. Удалите `customdata`: точку нельзя связать с наблюдением.
3. Покажите в hover все поля источника.
4. Добавьте свободный набор фильтров без связи с question brief.

## Проверьте это

- по одной trace на web, iOS и Android;
- длина customdata совпадает с числом точек;
- dropdown содержит all и каждую платформу;
- HTML содержит plotly.js;
- report фиксирует `dash_required=false`.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/anomaly_explorer.py` поставляет `anomaly-explorer.html`,
`anomaly-explorer.plotly.json` и report с checksums. Файл открывается локально без Dash.

## Упражнения

1. Добавьте selection по cohort week.
2. Ограничьте размер customdata для sample profile.
3. Сравните embedded и CDN export по размеру и offline-поведению.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Hover | Все поля строки | Минимальный контекст наблюдения |
| Drill-down | Произвольная навигация | Управляемое раскрытие detail |
| Trace | Весь dashboard | Один набор marks с общей семантикой |
| Standalone HTML | Серверное приложение | Документ с embedded runtime |
| Figure JSON | Внутренняя магия | Сериализуемый контракт data и layout |

## Дополнительное чтение

- [Plotly: Graph objects](https://plotly.com/python/graph-objects/) - изучите Figure, traces и layout.
- [Plotly: Hover text and formatting](https://plotly.com/python/hover-text-and-formatting/) - разберите `customdata` и `hovertemplate`.
- [Plotly: Interactive HTML export](https://plotly.com/python/interactive-html-export/) - сравните embedded, CDN и fragment export.
