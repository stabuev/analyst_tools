# HTTP и Requests

> Получить ответ недостаточно: сначала докажите, что это ожидаемый ответ, затем публикуйте его байты.

**Тип:** Learn  
**Треки:** Core  
**Пререквизиты:** 05/03  
**Время:** ~75 минут  
**Результат:** проверяет статус, заголовки, content type и кодировку ответа, задает timeout
и потоково сохраняет тело ответа.

## Цели обучения

- Разделять транспорт, HTTP-метаданные и тело ответа.
- Задавать connect и read timeout.
- Проверять статус и media type до парсинга.
- Потоково сохранять ответ с лимитом размера и атомарной заменой.

## Проблема

Скрипт вызывает `requests.get(url).json()`. При сбое gateway возвращает HTML со статусом
503, при редиректе конечный URL меняется, а большой ответ целиком попадает в память.
Иногда процесс завершается посередине записи и оставляет файл, который выглядит готовым.

## Концепция

HTTP-ответ имеет независимые слои:

| Слой | Что проверять |
|---|---|
| Status | допустим ли код, обычно 2xx |
| Headers | `Content-Type`, `Content-Length`, charset, redirect |
| Body | лимит размера, checksum, формат |

Timeout `(connect, read)` ограничивает разные ожидания. Read timeout относится к паузе
между получениями данных, а не обязательно ко всему времени загрузки.

`Content-Type: application/json; charset=utf-8` содержит media type и параметр charset.
Для выбора парсера сравнивают media type без параметров.

## Соберите это

Сформируйте request policy до вызова:

```python
response = session.get(
    url,
    stream=True,
    timeout=(3.05, 30.0),
    allow_redirects=True,
    headers={"Accept": "application/json"},
)
```

Проверьте статус и media type. Только затем читайте `iter_content`, одновременно считая
размер и SHA-256. Пишите в `.name.part`; после полной проверки используйте
`os.replace(part, final)`.

При превышении `max_bytes`, несовпадении `Content-Length` или сетевой ошибке временный
файл удаляется.

```bash
uv run --locked python code/main.py
```

## Используйте это

Requests `Session` переиспользует соединения и хранит общие настройки. Контекстный
менеджер или явный `close()` освобождает ресурсы. При `stream=True` тело нужно прочитать
или закрыть response.

Артефакт:

```bash
uv run --locked python outputs/http_download.py \
  --url https://example.org/data.json \
  --output raw/data.json \
  --content-type application/json
```

Для реальных источников используется HTTPS. `--allow-http` предназначен для локального
учебного сервера.

## Сломайте это

Behavioral tests имитируют:

1. статус 503;
2. `text/html` вместо JSON;
3. тело больше лимита;
4. неверный `Content-Length`;
5. HTTP без явного разрешения.

Ни один случай не должен оставить частичный файл под финальным именем.

## Проверьте это

- request получает `stream=True` и пару timeout;
- media type отделяется от charset;
- непредусмотренный status и type блокируют запись;
- размер проверяется во время потока;
- checksum соответствует сохраненным байтам;
- response всегда закрывается;
- CLI работает против локального HTTP-сервера без внешней сети.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/http_download.py` поставляет raw-файл и JSON-отчет с request policy, final URL,
headers, размером и SHA-256. Код возврата отличает нарушенный ответ от ошибки конфигурации
или транспорта.

## Упражнения

1. Добавьте проверку `ETag` и условный запрос.
2. Ограничьте число redirect и разрешенные host names.
3. Добавьте декомпрессию только после проверки лимита распакованных данных.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Status code | Любой ответ означает успех | Машинный результат обработки HTTP-запроса |
| Media type | Расширение файла | Тип представления из `Content-Type` |
| Charset | Формат JSON | Правило декодирования текста из байтов |
| Streaming | Быстрая загрузка | Инкрементальное чтение без полного тела в памяти |
| Atomic publish | Обычный rename | Появление финального пути только после полной проверки |

## Дополнительное чтение

- [Requests: Advanced Usage](https://requests.readthedocs.io/en/latest/user/advanced/) — изучите Session, streaming body и освобождение соединения.
- [Requests: Timeouts](https://requests.readthedocs.io/en/latest/user/quickstart/#timeouts) — разберите смысл connect/read ожидания и обязательность явного timeout.
- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110) — сопоставьте status codes, fields и representation metadata.
- [Python: `hashlib`](https://docs.python.org/3/library/hashlib.html) — используйте инкрементальное обновление digest при потоковой записи.
