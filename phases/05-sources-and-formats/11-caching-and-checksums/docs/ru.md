# Кеширование и контроль целостности

> Публикуйте не набор перезаписанных файлов, а проверенную неизменную версию с атомарным указателем.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 05/10  
**Время:** ~90 минут  
**Результат:** собирает повторяемый загрузчик, который кеширует сырые ответы, атомарно
обновляет данные и проверяет схему и SHA-256 manifest.

## Цели обучения

- Проверять cache hit по checksum.
- Связывать raw pages, schema и dataset одним run id.
- Публиковать immutable partitioned versions.
- Обновлять current pointer только после полной проверки.

## Проблема

Pipeline скачивает три страницы прямо в рабочий каталог и перезаписывает Parquet. На
второй странице процесс падает. Потребитель видит смесь старых и новых файлов, а повторный
запуск не знает, каким cached responses можно доверять.

## Концепция

Финальная структура:

```text
delivery/
├── raw/
│   ├── cache_index.json
│   └── <url-hash>.json
├── datasets/<run-id>/
│   ├── data/order_month=.../currency=.../*.parquet
│   └── manifest.json
└── current.json
```

`run-id` выводится из SHA-256 всех raw pages и schema contract. Dataset version не
перезаписывается. `current.json` является commit point и записывается через temporary file
и `os.replace`.

## Соберите это

Для каждой страницы:

1. найдите URL в cache index;
2. пересчитайте checksum файла;
3. используйте hit только при совпадении;
4. иначе загрузите и атомарно запишите raw bytes;
5. проверьте JSON shape и schema records.

После всех страниц создайте Arrow Table, partitioned Parquet и manifest с checksums. Лишь
затем обновляйте pointer.

```bash
uv run --locked python code/main.py
```

## Используйте это

Учебный CLI полностью работает offline:

```bash
uv run --locked python outputs/resilient_loader.py \
  --url 'https://api.example.test/orders?page=1' \
  --source-dir ../data/tiny \
  --output-dir delivery \
  --schema ../data/parquet_schema.json
```

Без `--source-dir` используется Requests Session с timeout, bounded urllib3 retries,
`Retry-After`, HTTPS, content type и size limit.

Повтор команды использует raw cache и существующую immutable dataset version. `--refresh`
принудительно проверяет источник заново.

## Сломайте это

1. Повредите cached page: checksum должен вызвать refetch.
2. Верните строку вместо amount: current не должен измениться.
3. Удалите обязательное поле: version не публикуется.
4. Создайте pagination cycle.
5. Прервите запись staging directory.
6. Измените schema contract при тех же raw pages: run id должен измениться.

## Проверьте это

- три raw pages дают пять rows;
- повторный запуск не обращается к источнику;
- corrupted cache page загружается заново;
- каждый raw и Parquet файл имеет checksum;
- dataset partitioned по month/currency;
- schema drift не создает current;
- failed refresh сохраняет старый pointer;
- current ссылается на manifest immutable version.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/resilient_loader.py` — интеграционный артефакт фазы. Он объединяет HTTP policy,
pagination, raw cache, schema validation, Arrow/Parquet, partitioning, manifests и
атомарную публикацию.

## Упражнения

1. Добавьте ETag и conditional GET.
2. Реализуйте retention policy immutable versions.
3. Добавьте подпись manifest и внешний object storage.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Cache hit | Файл существует | Файл существует и его checksum соответствует index |
| Immutable version | Каталог без chmod | Поставка, bytes которой не меняются под run id |
| Manifest | Человеческое описание | Машинная связь inputs, schema, files и checksums |
| Atomic pointer | Перезапись dataset | Единственная атомарная смена ссылки на готовую версию |
| Replay | Повтор HTTP | Пересборка производных данных из сохраненного raw |

## Дополнительное чтение

- [Python: `os.replace`](https://docs.python.org/3/library/os.html#os.replace) — изучите атомарную замену пути на одном filesystem.
- [Python: `hashlib`](https://docs.python.org/3/library/hashlib.html) — используйте SHA-256 для идентичности raw и delivery files.
- [urllib3: Retry](https://urllib3.readthedocs.io/en/stable/reference/urllib3.util.html#urllib3.util.Retry) — разберите bounded retries и `Retry-After`.
- [PyArrow: Datasets](https://arrow.apache.org/docs/python/dataset.html) — свяжите partitioned write, discovery и filtering с immutable version.
