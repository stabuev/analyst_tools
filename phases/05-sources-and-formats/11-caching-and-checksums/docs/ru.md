# Кеширование и контроль целостности

> Сначала зафиксируйте неизменяемый raw snapshot, затем проверьте производную версию и
> только после этого переключайте указатель потребителя.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 05/10  
**Время:** ~90 минут  
**Результат:** собирает воспроизводимую поставку: сохраняет raw pages по содержимому,
связывает snapshot, schema, layout и pipeline version в `run_id`, проверяет immutable
Parquet version и атомарно переключает `current`.

## Цели обучения

- Отличать HTTP cache, raw replay store, snapshot и опубликованную dataset version.
- Считать cache hit доказанным только после проверки ожидаемого SHA-256.
- Объяснять, почему failed refresh не должен изменять старые raw bytes, cache index и
  `current`.
- Выводить идентичность запуска из всех входов, которые меняют результат.
- Проверять существующую immutable version перед повторным использованием.
- Публиковать один проверенный package и менять видимый pointer последней операцией.

## Мост от предыдущих уроков

Вы уже построили отдельные надёжные границы:

| Урок | Что уже умеете | Что добавляет 05/11 |
|---|---|---|
| 05/04 | безопасно получить один JSON body | сохранить полученные bytes для replay |
| 05/05 | пройти доверенную цепочку `next` до `null` | зафиксировать всю цепочку одним snapshot |
| 05/08 | проверить schema, grain и Parquet roundtrip | связать schema contract с конкретным запуском |
| 05/10 | построить проверенный partitioned package | не пересобирать и не принимать его без проверки |

Следующая фаза начинает EDA. Ей нужен не «последний файл в каталоге», а вход, для
которого можно ответить: из каких raw bytes он получен, какими контрактами проверен и
какая версия сейчас разрешена потребителям.

## Проблема

Загрузчик скачивает три страницы и сразу перезаписывает рабочий dataset. Во время refresh
вторая страница приходит с неверным `amount`, а процесс завершается с ошибкой.

Если raw-файл назван только по URL и уже перезаписан, возникают две разные поломки:

1. `current` всё ещё указывает на старый dataset, но raw bytes для его повторной сборки
   потеряны;
2. следующий запуск видит файл в кеше и может принять новое повреждённое тело за старый
   проверенный ответ.

Проверка «файл существует» здесь не отвечает ни на один важный вопрос. Нужны отдельные
идентичности raw bytes, snapshot и производной версии.

## Концепция

### 1. Blob хранится по содержимому, а не по месту получения

Для тела страницы `body` вычисляется:

```text
digest = SHA-256(body)
path   = raw/blobs/<digest>.json
```

Одинаковые bytes дают то же имя; изменённые bytes получают другое имя. Старый blob не
перезаписывается при refresh. Такой способ называют **content-addressed storage**:
адресом объекта является отпечаток его содержимого.

SHA-256 здесь проверяет целостность относительно доверенного digest. Он не доказывает,
кто создал файл, и не заменяет цифровую подпись. Если злоумышленник может одновременно
подменить bytes и все сохранённые digests, один checksum не установит подлинность.

### 2. Cache index — подсказка, а не доказательство

Индекс отвечает на вопрос «какой digest последний раз успешно связан с этим URL»:

```json
{
  "version": "1.0.0",
  "entries": {
    "https://api.example.test/orders?page=2": {
      "sha256": "...",
      "bytes": 742
    }
  }
}
```

Cache hit допустим, только если:

```text
index contains URL
AND blob exists at path derived from digest
AND observed bytes equal declared bytes
AND SHA-256(blob) equals declared digest
```

Путь не берётся из индекса. Поэтому повреждённый JSON не может подсунуть
`../../another-file` вместо blob.

Это не полноценный HTTP cache. Здесь нет freshness, `Cache-Control`, `Vary`, ETag и
conditional request. Raw replay store решает более узкую задачу: сохранить точные bytes
аналитического запуска и воспроизвести преобразование без сети.

### 3. Snapshot фиксирует не только множество blobs, но и цепочку

Три страницы нельзя описать неупорядоченным набором хешей. Важны URL, порядок,
завершение по `next=null` и число записей:

```text
snapshot = [
  {url: page=1, sha256: A, items: 2},
  {url: page=2, sha256: B, items: 2},
  {url: page=3, sha256: C, items: 1}
]
snapshot_id = SHA-256(canonical(snapshot))
```

Если изменилась одна страница, порядок или start URL, изменится `snapshot_id`. До его
расчёта каждая страница должна пройти строгий JSON page contract, schema и grain.

### 4. `run_id` обязан учитывать все входы результата

Одинаковый raw snapshot не гарантирует одинаковый dataset. Результат может измениться
из-за schema, layout или логики преобразования:

```text
run_id = SHA-256(
  snapshot_id
  + delivery_contract_digest
  + schema_contract_digest
  + layout_contract_digest
  + pipeline_version
)
```

`pipeline_version` — явная версия семантики кода. Её нужно повысить, если преобразование
меняет значения или форму результата. Это честнее, чем притворяться, что checksum
исходных страниц полностью описывает вычисление.

### 5. Immutable version и `current` решают разные задачи

Структура поставки выглядит так:

```text
delivery/
├── raw/
│   ├── blobs/<sha256>.json
│   └── cache_index.json
├── datasets/<run-id>/
│   ├── data/order_month=.../currency=.../*.parquet
│   └── manifest.json
└── current.json
```

- `datasets/<run-id>/` хранит неизменяемую проверенную версию;
- `manifest.json` связывает snapshot, contracts, logical schema, files, checksums и
  workload evidence;
- `current.json` говорит потребителю, какую готовую версию читать сейчас.

Сначала весь version package строится в уникальном соседнем staging-каталоге. После
semantic roundtrip, workload checks и file checksums каталог переименовывается в
`datasets/<run-id>`. Затем атомарно записываются cache index и `current`.

`os.replace` даёт атомарную смену одного пути на той же локальной файловой системе:
читатель увидит старый или новый pointer. Это не обещание crash durability после потери
питания и не контракт публикации в object storage.

### 6. Три запуска образуют одну модель состояния

```text
первый запуск
  fetch pages → new blobs → validate snapshot → build version → current = run A

replay
  verify cached blobs → same snapshot → verify version A → current = run A

невалидный refresh
  fetch to new blobs → validation fails → index unchanged → current = run A
```

Новый blob после неуспешного refresh может остаться ничем не связанным. Это безопасный
orphan, а не опубликованный результат. Retention таких blobs — отдельная операционная
политика, которой в обязательной практике нет.

## Соберите это

Прозрачный пример использует только словари, JSON и `hashlib`. Перед запуском
предскажите:

1. сколько fetches будет в первом запуске;
2. совпадут ли `snapshot_id` и `run_id` при replay;
3. изменятся ли cache index и `current` после невалидного refresh.

```bash
uv run --locked python code/main.py
```

В примере четыре операции видны напрямую:

```python
checksum = sha256(body)
blobs[checksum] = body
candidate_index[url] = checksum
snapshot_id = sha256(canonical(page_journal))
```

Ключевой момент — `candidate_index` не становится рабочим индексом внутри
`prepare_run`. Вызывающий код делает commit только после проверки candidate. Поэтому
ошибка не требует «откатывать» уже опубликованное состояние.

Пример не пишет Parquet и не реализует HTTP. Его задача — сделать наблюдаемой
транзакционную границу, которую рабочий CLI соединит с механизмами предыдущих уроков.

## Используйте это

### 1. Прочитайте внешний delivery contract

`../data/delivery_contract.json` фиксирует:

- start URL и разрешённый HTTPS origin;
- точные имена `items`, `next` и `page`;
- `max_pages`;
- timeout, decoded page size, redirects и per-page retry budget;
- `pipeline_version` и алгоритм целостности.

Schema и layout не дублируются: CLI принимает актуальные контракты 05/08 и 05/10.
Все три JSON-файла разбираются строго: duplicate и unknown keys или неизвестная версия
останавливают запуск.

### 2. Выполните первый offline run

Из корня урока:

```bash
uv run --locked python outputs/resilient_loader.py \
  --contract ../data/delivery_contract.json \
  --schema ../data/parquet_schema.json \
  --layout-contract ../data/partition_layout_contract.json \
  --source-dir ../data/tiny \
  --output-dir work/delivery
```

Ожидаемый public report содержит:

```text
source.pages        = 3
source.rows         = 5
source.fetched_pages = 3
dataset.partition_by = [order_month, currency]
summary.valid       = true
```

Пути в report и manifest относительны package root. В них не сохраняются staging paths
или локальный `/Users/...`.

### 3. Повторите команду

Во втором запуске:

```text
source.reused_pages  = 3
source.fetched_pages = 0
dataset.reused_version = true
```

`reused_version=true` не означает «каталог уже был, поэтому мы ему поверили». CLI снова
проверяет:

- provenance manifest против текущего snapshot и contracts;
- точное множество Parquet files;
- размер и SHA-256 каждого файла;
- logical schema и все значения после Hive discovery;
- grain и результаты workload filters.

Только после этого версия снова допустима для `current`.

### 4. Выполните refresh

Флаг `--refresh` запрещает cache hits, но не удаляет старые blobs:

```bash
uv run --locked python outputs/resilient_loader.py \
  --contract ../data/delivery_contract.json \
  --schema ../data/parquet_schema.json \
  --layout-contract ../data/partition_layout_contract.json \
  --source-dir ../data/tiny \
  --output-dir work/delivery \
  --refresh
```

Если bytes не изменились, получится тот же snapshot и будет проверена та же version.
Если источник валидно изменился, появятся новый snapshot, новый `run_id` и новый version
directory. Если источник невалиден, прежние cache index и `current` сохранятся byte for
byte.

### 5. Отделите коды завершения

| Код | Значение | Пример |
|---:|---|---|
| `0` | поставка проверена и pointer обновлён | первый run или replay |
| `1` | source или candidate нарушил контракт | schema drift, cycle, checksum mismatch |
| `2` | конфигурация невалидна | unknown contract key, path collision |

В network mode CLI дополнительно проверяет HTTPS, same-origin redirects, media type,
decoded size и bounded per-page retries. Переход `next` проверяется до следующего fetch.
Полный эксперимент с общим retry budget уже был в 05/05 и здесь не повторяется.

## Сломайте это

### Повреждённый raw blob

Измените bytes существующего `raw/blobs/<sha256>.json`. Индекс всё ещё хранит старый
digest, поэтому hit отклоняется и страница запрашивается заново. При тех же исходных
bytes blob восстанавливается под тем же content address.

### Невалидный refresh

Верните `amount="not-a-number"` на второй странице. Новые bytes могут попасть в новый
blob, но schema validation завершит run до записи cache index и `current`. Старая
поставка остаётся воспроизводимой.

### Подмена готового Parquet

Измените один файл внутри `datasets/<run-id>/data`. Повторный запуск не должен принимать
каталог как cache hit: checksum verification блокирует reuse.

### Правдоподобная подмена с новым checksum

Измените значение, затем перепишите file checksum в manifest. Одного совпавшего checksum
уже недостаточно: semantic roundtrip сравнивает dataset с проверенным raw snapshot и
обнаруживает другой `amount` при том же числе строк.

### Изменение pipeline без новой версии

Если код изменил семантику, а `pipeline_version` остался прежним, идентичность запуска
описана неверно. Это организационная граница content identity: автоматический тест не
угадает намерение автора. Изменяйте версию вместе с изменением результата.

### Параллельный или прерванный staging

Фиксированное имя `.run-id.staging` опасно: новый процесс может удалить каталог другого
процесса. CLI создаёт уникальное имя через `tempfile.mkdtemp`, удаляет только свой
candidate и не трогает похожие чужие каталоги.

## Проверьте это

```bash
uv run --locked python -m unittest discover -s tests
```

44 behavioral tests проверяют:

- первый run, offline CLI, replay cache и повторную проверку version;
- content-addressed blobs и восстановление повреждённого blob;
- новый snapshot при валидном refresh;
- сохранение pointer, index и старых blobs при failed refresh;
- raw provenance, три contract digests, workload evidence и относительные пути;
- изменение `run_id` при новой pipeline, schema или layout identity;
- checksum, file-list и semantic drift существующей версии;
- unique staging, очистку failed candidate и сохранность похожего каталога;
- relative и absolute same-origin `next`, HTTPS downgrade, cross-origin и cycle;
- page contract, page number, max pages и max page bytes;
- schema fields, domain, decimal scale, timezone и grain;
- strict JSON contracts, cache index и CLI exit codes.

Проверка полного значения нужна вместе с checksum. Checksum отвечает «совпадают ли эти
bytes с объявленным digest», а semantic roundtrip — «представляют ли проверенные bytes
тот же набор заказов».

## Поставьте результат

`outputs/resilient_loader.py` — самостоятельный CLI `replayable-source-delivery`. Для
переноса на другой API передайте четыре внешних входа:

1. delivery contract с page и network policy;
2. schema contract с grain и допустимыми значениями;
3. layout contract с выбранными partitions и workload;
4. source adapter: HTTPS по умолчанию или локальная папка для воспроизводимого replay.

Потребитель начинает с `current.json`, проверяет `manifest_sha256`, затем открывает
указанный immutable dataset. Ему не нужны рабочая директория урока, staging path или
живой API.

Граница артефакта намеренно локальная. Подпись manifest, locks, object-store commit
protocol, retention и garbage collection требуют инфраструктурного контекста и не
объявляются свойствами этого CLI.

## Упражнения

1. **Наблюдение.** Выполните первый run и replay. Сопоставьте каждый счётчик report с
   конкретным файлом в `raw/` или `datasets/`.
2. **Перенос.** Измените только `pipeline_version`. Объясните, почему raw snapshot тот же,
   а `run_id` и version directory новые.
3. **Поломка.** Повредите cached blob. До запуска предскажите, какая одна страница будет
   fetched и почему остальные останутся hits.
4. **Осознанное расширение.** Спроектируйте ETag/`If-None-Match` как отдельный network
   optimization. Не заменяйте ответ `304` отсутствующими raw bytes: он может ссылаться
   только на уже проверенный blob.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Content address | имя файла по URL | путь, выведенный из digest содержимого |
| Cache hit | запись URL есть в index | index, размер и checksum указывают на доступный blob |
| Raw replay | повторить HTTP | повторить преобразование из сохранённых исходных bytes |
| Snapshot | набор последних файлов | упорядоченный журнал проверенных страниц одного обхода |
| `snapshot_id` | идентификатор dataset | digest raw page journal до преобразования |
| `run_id` | время запуска | digest snapshot и всех контрактов результата |
| Immutable version | каталог нельзя chmod | bytes под данным `run_id` после публикации не меняются |
| Manifest | описание для человека | машинная связь provenance, contracts, files и checks |
| Commit point | первый записанный Parquet | последняя атомарная смена видимого `current` pointer |
| Checksum | цифровая подпись | контроль идентичности bytes относительно доверенного digest |

## Дополнительное чтение

1. [RU: Кеширование HTTP — MDN](https://developer.mozilla.org/ru/docs/Web/HTTP/Guides/Caching) — прочитайте разделы о freshness, validation и `Vary`: они показывают, чем стандартный HTTP cache шире учебного raw replay store.
2. [RU: Версионирование бакета — Yandex Object Storage](https://yandex.cloud/ru/docs/storage/concepts/versioning) — прочитайте, как object versions защищают от случайной перезаписи; сравните эту инфраструктурную гарантию с локальными content-addressed blobs урока.
3. [RU: Объекты Git — Pro Git](https://git-scm.com/book/ru/v2/Git-%D0%B8%D0%B7%D0%BD%D1%83%D1%82%D1%80%D0%B8-%D0%9E%D0%B1%D1%8A%D0%B5%D0%BA%D1%82%D1%8B-Git) — изучите content-addressed object database как более крупный пример хранения неизменяемых blobs по содержимому.
4. [EN: RFC 9111 — HTTP Caching](https://www.rfc-editor.org/rfc/rfc9111) — прочитайте sections 4–5 о cache lookup, freshness и validation; используйте стандарт как границу перед добавлением ETag.
5. [EN: `tempfile.NamedTemporaryFile` — Python](https://docs.python.org/3/library/tempfile.html#tempfile.NamedTemporaryFile) — изучите уникальные временные имена и lifecycle файла, на которых основана безопасная локальная запись pointer и index.
6. [EN: `os.replace` — Python](https://docs.python.org/3/library/os.html#os.replace) — проверьте точную семантику атомарной замены и требование одной filesystem; не переносите это обещание автоматически на object storage.
7. [EN: PyArrow Dataset](https://arrow.apache.org/docs/python/dataset.html) — повторите partitioned write, Hive discovery и filtering, которые CLI проверяет внутри immutable version.
8. [EN: Data Package specification](https://specs.frictionlessdata.io/data-package/) — разберите `resources`, metadata и machine-readable package boundary; сравните спецификацию с узким manifest этого урока.
9. [EN: W3C PROV Overview](https://www.w3.org/TR/prov-overview/) — прочитайте модель entity, activity и agent; она помогает расширить page and contract digests до полноценного provenance без смешения с checksum.
10. [EN: Secure Hash Standard — NIST FIPS 180-4](https://csrc.nist.gov/pubs/fips/180-4/upd1/final) — используйте первичный стандарт для точного смысла SHA-256 и помните: стандарт hash function сам по себе не задаёт подпись или доверенную доставку digest.
