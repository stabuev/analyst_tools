# Данные фазы 05

Фаза использует небольшие детерминированные файлы, которые показывают неоднозначность
форматов и устойчивую загрузку без внешней сети.

Committed-набор содержит:

- `orders_semicolon_cp1251.csv` — корректный CSV в CP1251 с разделителем `;`,
  десятичной запятой, пробелом тысяч, `NULL`, пустым значением и `;` внутри кавычек;
- `orders_broken_cp1251.csv` — тот же диалект, но одна строка содержит лишнее
  неэкранированное поле;
- `orders_report.xlsx` и `orders_report_shifted.xlsx` — Excel-книга с несколькими
  листами, служебными строками, merged cells и формулами и вариант со сдвинутым header;
- `events_nested.json` и `events_schema_drift.json` — вложенные события с массивом
  позиций и вариант с новым путем и измененным типом;
- `http_orders.json` — небольшое тело HTTP-ответа для локальных streaming-тестов;
- `api_page_1.json`–`api_page_3.json` — страницы API с явной ссылкой `next`;
- `orders.html` и `orders_changed.html` — стабильная HTML-разметка и вариант с
  нарушенным контрактом селектора;
- `analytics.sqlite` — локальная база пользователей и заказов для SQLAlchemy Core;
- `orders_typed.csv` — UTF-8 источник с десятичной точкой для конвертации в Parquet;
- `manifest.json` — размер, число логических строк и SHA-256 каждого файла;
- `contract.json`, `excel_spec.json` и `json_contract.json` — явные договоры форматов.

Пересоздать набор:

```bash
uv run --locked python phases/05-sources-and-formats/data/generate_data.py
```

Проверить, что committed-файлы воспроизводимы:

```bash
uv run --locked python phases/05-sources-and-formats/data/generate_data.py --check
```

Тесты HTTP не зависят от внешней сети: они используют fake response.
