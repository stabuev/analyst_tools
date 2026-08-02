<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 05: Источники и форматы данных

> Проверяйте внешние источники на их естественной границе и публикуйте воспроизводимые типизированные версии данных.

- **Треки:** core
- **Пререквизиты:** Фаза 04
- **Время:** ~10-14 часов
- **Итоговый артефакт:** Воспроизводимая поставка из проверенного raw snapshot в immutable partitioned dataset

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [CSV и неоднозначность типов](01-csv) | 75 мин | Объявляет диалект, кодировку, схему и правила пропусков CSV и обнаруживает поврежденные строки до анализа. | CLI-аудитор CSV-диалекта, типов и проблемных строк | complete |
| 02 | [Excel как источник: листы, диапазоны и формулы](02-excel) | 60 мин | Выбирает лист и диапазон, распознает служебное оформление и преобразует рабочую книгу в явную табличную схему. | Аудитор Excel-книги и спецификация извлекаемого диапазона | complete |
| 03 | [JSON и вложенные структуры](03-json) | 75 мин | Нормализует вложенные объекты и массивы в объявленный grain и обнаруживает изменение схемы без потери сырого JSON. | JSON-нормализатор с отчетом о путях и изменениях схемы | complete |
| 04 | [HTTP и Requests](04-http-requests) | 75 мин | Безопасно получает один JSON-ресурс: проверяет status, media type, UTF-8 и redirect policy, ограничивает ожидание и размер и атомарно сохраняет тело ответа. | HTTP-инспектор и безопасный потоковый загрузчик | complete |
| 05 | [Pagination, timeouts и retries](05-pagination-retries) | 90 мин | Проходит все страницы одного JSON API по доверенной цепочке next, ограничивает retries общим бюджетом и атомарно публикует результат только после завершения и проверки grain. | Клиент полного пагинированного JSON-снимка с bounded retry-policy | complete |
| 06 | [HTML и Beautiful Soup](06-html-parsing) | 60 мин | Извлекает один проверяемый табличный grain из сохранённого HTML по версионированному selector contract, обнаруживает drift и публикует результат только после успешных проверок. | HTML-экстрактор с версионированным selector contract и атомарным snapshot | complete |
| 07 | [Подключение к БД через SQLAlchemy](07-sqlalchemy) | 90 мин | Создаёт проверяемую границу чтения из SQL-БД через SQLAlchemy: связывает values отдельно от trusted SQL, управляет Engine и Connection, проверяет source schema, полноту JOIN и safety limit и публикует только валидный snapshot. | Read-only SQLAlchemy reader с trusted SQL, schema contract и completeness checks | complete |
| 08 | [Parquet и колоночное хранение](08-parquet) | 75 мин | Преобразует ограниченный UTF-8 CSV-снимок в Parquet по явному schema, null и grain contract, проверяет roundtrip и физические metadata и поставляет checksum-manifest. | Контрактный CSV-to-Parquet converter с roundtrip verification и checksum-manifest | complete |
| 09 | [Arrow как контракт обмена таблицами](09-arrow) | 60 мин | Проверяет typed in-memory маршруты Arrow → pandas → Arrow и Arrow → DuckDB → Arrow: сравнивает schema, values, nulls и grain, классифицирует metadata drift и фиксирует buffer reuse без универсального zero-copy claim. | Arrow interchange auditor с route contract, metadata drift и buffer-reuse evidence | complete |
| 10 | [Партиционирование наборов данных](10-partitioning) | 90 мин | Формализует representative workload, сравнивает candidate Hive layouts, строит выбранный partitioned Parquet dataset во временном пакете и публикует его только после semantic roundtrip, workload checks и checksum manifest. | Проверенный partitioned dataset package с layout decision, workload evidence и manifest | complete |
| 11 | [Кеширование и контроль целостности](11-caching-and-checksums) | 90 мин | Собирает воспроизводимую поставку: сохраняет raw pages по содержимому, связывает snapshot, schema, layout и pipeline version в run_id, проверяет immutable Parquet version и атомарно переключает current. | CLI воспроизводимой поставки с content-addressed raw snapshot, проверенной immutable Parquet version и current pointer | complete |

## Как проходить фазу

1. Ответьте на входные вопросы до чтения reference implementation.
2. Для каждого урока выполните прозрачную практику в локальной папке `work/`.
3. Запустите пример и тесты либо заполните артефакт и проверьте его по рубрике.
4. Выполните хотя бы одно упражнение, которое меняет данные или правило.
5. После фазы пройдите перемешанную самопроверку:

```bash
uv run --locked python scripts/run_quiz.py --phase 5 --stage post --limit 8
```

Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. Критерий освоения — объяснить решение, воспроизвести расчет или рассуждение и диагностировать хотя бы одну поломку.

## Критерий завершения

Студент выбирает и проверяет source adapter, фиксирует grain, schema и provenance, сохраняет typed snapshot и переключает current только после checksum, semantic и workload checks.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
