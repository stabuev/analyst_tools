# HTML и Beautiful Soup

> HTML-парсер должен замечать изменение разметки, а не превращать его в пустые значения.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 05/05  
**Время:** ~60 минут  
**Результат:** извлекает структурированные записи по устойчивым селекторам и явно
обнаруживает изменение HTML-разметки.

## Цели обучения

- Выбирать семантические selectors вместо случайной глубины DOM.
- Требовать ровно одно совпадение обязательного поля.
- Разделять текст, атрибут и тип значения.
- Тестировать extractor на сохраненных HTML-fixtures.

## Проблема

Страница заказов содержит карточки. После редизайна `span.amount` заменяется на `strong`
с другим атрибутом. Скрипт продолжает работу и записывает `None`, поэтому проблема
обнаруживается только в отчете через несколько дней.

## Концепция

HTML является деревом представления, а не API-контрактом. Устойчивость selector обычно
растет в таком порядке:

1. позиция вроде `div > div:nth-child(2)` — хрупкая;
2. CSS-класс оформления — зависит от дизайна;
3. семантический `data-*` attribute — выражает назначение узла.

Контракт урока задает selector записи, attribute идентификатора и по одному selector для
каждого поля.

## Соберите это

Сначала назовите grain: одна карточка на `order_id`. Для каждой карточки вручную
проверьте, что:

- присутствует `data-order-id`;
- selector пользователя находит один узел;
- selector суммы находит один узел;
- значение суммы преобразуется по явному правилу.

Ноль совпадений означает пропавшее поле, два совпадения — неоднозначный контракт.

```bash
uv run --locked python code/main.py
```

## Используйте это

Beautiful Soup поддерживает CSS selectors:

```python
soup = BeautifulSoup(html, "html.parser")
cards = soup.select("[data-order-card]")
amount = card.select_one("[data-field='amount']")
```

Артефакт использует `select`, чтобы считать количество совпадений, и только затем извлекает
text или attribute.

```bash
uv run --locked python outputs/html_extractor.py \
  --input ../data/tiny/orders.html \
  --contract ../data/html_contract.json \
  --output-dir delivery
```

## Сломайте это

`orders_changed.html` заменяет amount второго заказа на новый `data-field="total"`.
Extractor должен назвать record, field, selector и число совпадений.

Дополнительные failure modes:

1. два amount внутри одной карточки;
2. отсутствующий `data-order-id`;
3. дублирующийся order id;
4. строка вместо числа;
5. другая encoding.

## Проверьте это

- valid fixture дает две записи;
- ids равны `O2601`, `O2602`;
- amount разбирается как Decimal;
- changed fixture сообщает ноль совпадений;
- неоднозначный selector сообщает два;
- duplicate id проваливает grain;
- delivery содержит JSONL и отчет.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/html_extractor.py` является contract-driven extractor. Он связывает records с
SHA-256 исходной страницы и не требует живого сайта для regression tests.

## Упражнения

1. Извлеките значение из attribute вместо текста.
2. Добавьте optional field с отдельной политикой.
3. Сравните `html.parser` и `lxml` на намеренно поврежденном HTML.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| DOM | Готовая таблица | Дерево узлов HTML-документа |
| CSS selector | Гарантия стабильности | Правило поиска, устойчивость которого зависит от выбранных признаков |
| data-* | Только оформление | Пользовательский семантический attribute |
| Selector drift | Пустое значение | Изменение разметки, нарушающее договор поиска |
| Fixture test | Тест живого сайта | Проверка extractor на сохраненном документе |

## Дополнительное чтение

- [Beautiful Soup documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) — изучите parser choice, navigation и поиск по CSS selectors.
- [Beautiful Soup: CSS selectors](https://www.crummy.com/software/BeautifulSoup/bs4/doc/#css-selectors-through-the-css-property) — разберите `select` и `select_one`.
- [MDN: data attributes](https://developer.mozilla.org/en-US/docs/Learn_web_development/Howto/Solve_HTML_problems/Use_data_attributes) — поймите назначение семантических `data-*` hooks.
- [WHATWG HTML](https://html.spec.whatwg.org/) — используйте стандарт как справочник по parsing model и attributes.
