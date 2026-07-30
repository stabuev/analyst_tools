# HTTP и Requests

> Успешный запрос — это не «сервер что-то вернул», а ожидаемое представление, прошедшее
> явную политику до публикации.

**Тип:** Learn  
**Треки:** Core  
**Пререквизиты:** 05/03  
**Время:** ~75 минут  
**Результат:** безопасно получает один JSON-ресурс: проверяет status, media type, UTF-8
и redirect policy, ограничивает ожидание и размер и атомарно сохраняет тело ответа.

## Цели обучения

- Читать один HTTP GET как request и response со status, headers и body.
- Отличать media type, charset, content encoding и фактические сохраненные bytes.
- Задавать connect/read timeout, точный status и ограничение размера.
- Проверять каждый redirect до следующего запроса.
- Сохранять только полностью проверенное представление через уникальный временный файл.

## Как этот урок продолжает маршрут

В 05/03 нормализатор начинал с уже сохраненных raw bytes: проверял UTF-8 и JSON, затем
строил две таблицы. Теперь появляется предыдущий слой — получение этих bytes из сети.
Downloader не выбирает grain и не исправляет JSON. Его результат становится входом
контракта 05/03.

Из 00/04 уже известно, что API token нельзя помещать в Git, URL или вывод команды.
В этом уроке вы увидите место секретного request header, но не будете изучать OAuth.

После урока клиент умеет безопасно получить один ответ. В 05/05 тот же контракт
расширится до нескольких страниц, ограниченных retries и backoff. Кеш, ETag, manifest и
полное атомарное обновление набора данных остаются 05/11.

## Проблема

Наивная строка выглядит удобно:

```python
payload = requests.get(url).json()
```

Но она скрывает несколько независимых решений:

- сколько ждать соединения и следующей порции данных;
- является ли ответ готовым полным файлом, а не `202`, `204` или `206`;
- не вернул ли gateway HTML под видом ошибки;
- не перенаправил ли исходный HTTPS URL на другой host или на HTTP;
- какую кодировку и compression применил сервер;
- сколько bytes окажется на диске после декомпрессии;
- что увидит следующий процесс, если загрузка оборвется.

Например, HTML-страница ошибки может иметь непустой body, а gzip-ответ — `Content-Length`,
не равный размеру распакованного JSON. Если сначала вызвать `.json()`, причины уже
смешаны в одной ошибке parser.

## Концепция

### 1. Один GET — это request и response

Клиент отправляет запрос:

| Часть request | Роль в уроке |
|---|---|
| method `GET` | просит получить представление ресурса без изменения его состояния |
| URL | называет scheme, host и путь ресурса |
| `Accept: application/json` | сообщает предпочитаемый media type, но не гарантирует ответ |
| timeout | ограничивает ожидание транспорта |

Сервер возвращает response:

```text
status line
headers

body bytes
```

Status сообщает результат обработки запроса, headers описывают ответ, body переносит
представление. Успешное сетевое соединение не гарантирует ни status `200`, ни JSON, ни
правильную бизнес-схему.

HTTPS шифрует соединение и проверяет сертификат host. Не отключайте TLS-проверку через
`verify=False`: это не средство исправить сертификат и не проверка содержимого ответа.

### 2. Разрешайте точный status, а не «любой 2xx»

Для загрузки полного готового файла default-контракт — `200 OK`.

| Status | Почему не принимается автоматически |
|---:|---|
| `202 Accepted` | работа принята, но результат может быть еще не готов |
| `204 No Content` | представления в body нет |
| `206 Partial Content` | это только диапазон, для полной сборки нужен отдельный протокол |

Если конкретный API документирует другой status, добавьте его в allowlist осознанно и
измените проверки результата. Непустой body не превращает неожиданный status в успех.

### 3. Четыре похожих понятия описывают разные слои

| Поле | Вопрос |
|---|---|
| `Content-Type: application/json` | как интерпретировать декодированное представление |
| `charset=utf-8` | как превратить текстовые bytes в Unicode |
| `Content-Encoding: gzip` | какое сжатие применено поверх представления |
| `Content-Length` | сколько bytes имеет HTTP message content, если длина объявлена |

Requests через `iter_content` автоматически снимает поддерживаемое content encoding.
Поэтому при gzip `Content-Length` может относиться к сжатому body, а downloader сохраняет
уже распакованные bytes. Их размеры не обязаны совпадать.

Из этого следуют три правила:

1. `Content-Length` сохраняется как transport metadata, а не используется как checksum.
2. `max_bytes` считается по фактически полученным и сохраняемым bytes после декомпрессии.
3. SHA-256 относится к сохраненному файлу, который затем прочитает нормализатор.

Для `application/json` межсистемный текст должен быть UTF-8. Заголовок
`charset=iso-8859-1` противоречит политике, но одного правильного header тоже
недостаточно: фактические chunks проверяются incremental decoder. Он умеет пережить
границу многобайтного символа между двумя chunks.

Downloader не проверяет JSON grammar и schema — это делает 05/03 после поставки raw
файла.

### 4. Timeout — не общий deadline

Requests принимает пару:

```python
timeout=(connect_timeout, read_timeout)
```

- connect timeout ограничивает установление соединения;
- read timeout ограничивает ожидание следующей порции данных от уже подключенного
  сервера.

Read timeout не обещает, что вся загрузка завершится за это число секунд. Сервер может
регулярно присылать маленькие chunks и поддерживать процесс дольше. Общий wall-clock
deadline требует отдельного механизма и не входит в этот урок.

Timeout ограничивает одну попытку. Решение, можно ли и сколько раз ее повторить,
появится в 05/05.

### 5. Redirect — это следующий запрос

`302 Location: /new.json` не содержит нужный JSON: он предлагает обратиться к другому
URL. Автоматическое следование скрывает важную границу. Без проверки клиент может:

- уйти с HTTPS на HTTP;
- обратиться к неожиданному host;
- попасть в redirect loop;
- передать чувствительный header не тому получателю.

Артефакт получает redirect с `allow_redirects=False`, разрешает только HTTPS и исходный
host, затем делает следующий GET. Дополнительный host включается отдельной allowlist.
Перед междоменным переходом `Authorization` и `Proxy-Authorization` снимаются.

`--allow-http` не является общим выключателем безопасности: он принимает только
`localhost` и loopback IP для воспроизводимых учебных тестов.

### 6. Streaming ограничивает память, но требует lifecycle

При `stream=True` Requests получает headers до загрузки всего body. Поэтому status,
media type, charset и redirect policy можно проверить до записи.

Затем:

```text
iter_content
-> count decoded bytes
-> validate UTF-8 incrementally
-> update SHA-256
-> write unique temporary file
```

Response обязательно закрывается после полного чтения, раннего отказа и исключения.
Иначе соединение не возвращается в pool.

### 7. Атомарная публикация сохраняет предыдущий успех

Временный файл создается с уникальным именем рядом с final path. Одинаковая файловая
система нужна, чтобы `os.replace` выполнил атомарную замену:

```text
.orders.json.<unique>.part --os.replace--> orders.json
```

Если проверка провалилась, временный файл удаляется. Если по final path уже лежала
предыдущая валидная версия, она остается неизменной. Это не означает, что свежая
загрузка успешна: потребитель обязан читать exit code и `output.written`, а не просто
проверять существование файла.

Уникальный temp не дает параллельным процессам писать в один `.part`, но политика
конкурирующих обновлений и кеша остается задачей 05/11.

### 8. Три класса результата дают разные exit codes

| Код | Класс | Пример |
|---:|---|---|
| `0` | успешная поставка или диагностический `--allow-failures` | проверенный `200 application/json` |
| `1` | response нарушил policy | `503`, неверный type, UTF-8, redirect или размер |
| `2` | конфигурация, transport или filesystem error | публичный HTTP, timeout, недоступный каталог |

`--allow-failures` разрешает посмотреть структурированный невалидный отчет с кодом `0`,
но не публикует body.

## Соберите это

### Шаг 1. Сделайте обмен наблюдаемым

`code/main.py` запускает одноразовый loopback-сервер. Это лабораторный источник, а не
часть downloader. Он позволяет увидеть настоящий Requests response без внешней сети:

```bash
uv run --locked python code/main.py
```

Сначала предскажите:

- какой status должен прийти;
- какой media type указан;
- сколько chunks получится при `chunk_size=32`;
- к каким bytes относится SHA-256.

### Шаг 2. Получите только headers

Прозрачный фрагмент выглядит так:

```python
with requests.Session() as session:
    session.trust_env = False
    response = session.get(
        url,
        headers={"Accept": "application/json"},
        timeout=(1.0, 2.0),
        stream=True,
        allow_redirects=False,
    )
```

`trust_env=False` делает учебный запуск независимым от локальных proxy, `.netrc` и
CA-настроек окружения. В рабочей сети их можно разрешить явно через `--trust-env`.

До чтения body сравните status с allowlist, отделите bare media type от параметров и
проверьте redirect.

### Шаг 3. Проверьте chunks до публикации

В полном артефакте один проход одновременно:

- считает фактический размер;
- проверяет UTF-8 incremental decoder;
- обновляет SHA-256;
- пишет временный файл.

Превышение `max_bytes` и ошибка декодирования являются response-policy failure, а не
необработанным исключением. Temp удаляется, final не меняется.

### Шаг 4. Примените атомарную границу

Только если все checks равны `true`, закрытый temp заменяет final path через
`os.replace`. Report отдельно фиксирует:

- существовал ли предыдущий файл;
- была ли выполнена новая запись;
- заменена ли предыдущая версия;
- размер и SHA-256 поставленных bytes.

## Используйте это

Для воспроизводимого CLI-запуска откройте два терминала из каталога урока.

В первом поднимите static source:

```bash
uv run --locked python -m http.server 8000 \
  --bind 127.0.0.1 \
  --directory ../data/tiny
```

Во втором загрузите один JSON:

```bash
uv run --locked python outputs/http_download.py \
  --url http://127.0.0.1:8000/http_orders.json \
  --output work/http_orders.json \
  --content-type application/json \
  --status 200 \
  --encoding utf-8 \
  --max-bytes 1000000 \
  --allow-http
```

JSON report выводится в stdout. Успешный результат имеет `summary.valid: true`,
`output.written: true` и SHA-256 файла.

Для защищенного API настройте caller-owned Session, опираясь на границу секретов 00/04:

```python
token = os.environ["ORDERS_API_TOKEN"]
with requests.Session() as session:
    session.trust_env = False
    session.headers["Authorization"] = f"Bearer {token}"
    report = download(url, output, session=session)
```

Значение token не передается через URL или CLI argument и не попадает в отчет.
Downloader не реализует OAuth refresh, выдачу credentials или secret storage.

## Сломайте это

Поведенческие сценарии разделены по причинам:

1. `503` и `text/html` отклоняются до чтения body.
2. `204` не принимается как полный JSON-файл только потому, что входит в 2xx.
3. `charset=iso-8859-1` и невалидные UTF-8 bytes блокируют запись.
4. gzip-ответ проходит, хотя compressed `Content-Length` и decoded size различаются.
5. body больше `max_bytes` дает невалидный отчет и не оставляет temp.
6. HTTPS → HTTP, неизвестный redirect host и loop отклоняются до следующего GET.
7. Read timeout является контролируемой transport error.
8. Каталог вместо output file является контролируемой configuration error.
9. Предыдущий валидный final сохраняется при неудачной новой загрузке.

Особенно опасны правдоподобные случаи: `206` с корректным JSON-фрагментом и gzip,
ошибочно проваленный сравнением двух разных размеров.

## Проверьте это

Тесты используют настоящий loopback HTTP для happy path, gzip, redirects и CLI, а
response doubles — только для транспортных и security-сценариев, которые трудно
детерминированно воспроизвести сервером.

Проверяется:

- точный status allowlist;
- порядок header checks до body;
- connect/read timeout и `stream=True`;
- фактический UTF-8 независимо от наличия charset;
- decoded size и SHA-256 сохраненного представления;
- ручная redirect policy без downgrade и loops;
- cleanup уникального temp;
- сохранение предыдущего final при отказе;
- закрытие response и owned Session;
- коды CLI `0`, `1`, `2` и отсутствие traceback.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/http_download.py` — самостоятельный CLI и импортируемая функция для одного GET.
Ему нужны URL, final path и явная response policy. Он не зависит от `code/main.py`,
внешней тестовой сети или незакоммиченного файла.

Артефакт поставляет:

- проверенные decoded representation bytes под final path;
- JSON report в stdout с request policy, response metadata, redirect chain, checks,
  размером и SHA-256;
- различимые exit codes для orchestration.

Слово raw здесь означает «до текстового и JSON parsing», но после HTTP content decoding,
которое выполняет Requests. Wire-level gzip bytes артефакт намеренно не сохраняет.

## Упражнения

1. Подайте через локальный сервер `events_nested.json`, затем передайте скачанный файл
   нормализатору 05/03. Объясните границу двух отчетов.
2. Разрешите дополнительный redirect host и докажите тестом, что sensitive headers не
   переходят на него.
3. Добавьте известный expected SHA-256 от владельца источника. Не сравнивайте файл с
   checksum, вычисленным из того же самого ответа как с независимым доказательством.

## Осознанные границы

- Урок получает один resource. Pagination, retries, `Retry-After` и backoff появляются
  в 05/05.
- `Content-Length` помогает предварительно оценить несжатый ответ, но не доказывает
  целостность и может отсутствовать.
- SHA-256 идентифицирует bytes, но не подтверждает JSON schema или бизнес-корректность.
- ETag, conditional requests, cache freshness, manifest и согласованная поставка набора
  файлов остаются 05/11.
- OAuth flows, custom proxy/TLS infrastructure, resume через Range и общий wall-clock
  deadline не являются скрытыми prerequisites этого урока.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| GET | Любой безопасный вызов API | HTTP method получения представления ресурса |
| Status code | Любой 2xx означает полный файл | Результат обработки request; допустимые значения задает policy |
| Media type | Расширение final-файла | Тип representation из `Content-Type` |
| Charset | То же, что gzip | Правило преобразования текстовых bytes в Unicode |
| Content encoding | Кодировка символов | Сжатие или иное преобразование поверх representation |
| Streaming | Гарантия быстрой загрузки | Инкрементальное чтение без полного body в памяти |
| Redirect | Тот же ответ по новому имени | Предложение выполнить следующий request к другому URL |
| Atomic replace | Удаление предыдущей версии заранее | Появление новой final-версии одной файловой операцией после проверок |

## Дополнительное чтение

- [MDN: обзор протокола HTTP](https://developer.mozilla.org/ru/docs/Web/HTTP/Guides/Overview) — повторите модель client request → server response и роль method, URL, status, headers и body до изучения деталей Requests.
- [MDN: Content-Type](https://developer.mozilla.org/ru/docs/Web/HTTP/Reference/Headers/Content-Type) — разберите media type и параметры; сравните их с отдельными проверками `content_type_expected` и charset policy.
- [MDN: перенаправления в HTTP](https://developer.mozilla.org/ru/docs/Web/HTTP/Guides/Redirections) — изучите 3xx, `Location` и redirect loops; затем объясните, почему downloader проверяет target до следующего GET.
- [Requests: Quickstart — Timeouts](https://requests.readthedocs.io/en/stable/user/quickstart/#timeouts) — прочитайте точное определение timeout и исключений; не интерпретируйте read timeout как общий deadline.
- [Requests: Advanced Usage — Body Content Workflow](https://requests.readthedocs.io/en/stable/user/advanced/#body-content-workflow) — разберите `stream=True`, условное чтение body и обязательное освобождение connection через consume или `close`.
- [Requests API: `Response.iter_content`](https://requests.readthedocs.io/en/stable/api/#requests.Response.iter_content) — проверьте контракт chunks и оговорку о decoding, из-за которой размер каждого результата не равен wire framing.
- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110) — углубите модель representation metadata, status semantics, `Content-Type`, `Content-Encoding` и redirects по первичному стандарту.
- [RFC 8259: JSON](https://www.rfc-editor.org/rfc/rfc8259) — прочитайте раздел 8.1 об UTF-8 и IANA registration `application/json`; это основание encoding policy урока.
- [Python: `tempfile.NamedTemporaryFile`](https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile) — изучите создание уникального temp рядом с final и lifecycle именованного файла перед атомарной заменой.
- [Python: `os.replace`](https://docs.python.org/3/library/os.html#os.replace) — проверьте семантику замены существующего destination и требование одной файловой системы для атомарности.
