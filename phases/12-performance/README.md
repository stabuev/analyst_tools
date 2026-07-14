<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 12: Производительность аналитики

> Выбирайте движок и формат на основании измерений, а не моды.

- **Треки:** data, ml
- **Пререквизиты:** Фаза 07
- **Время:** ~12-16 часов
- **Итоговый артефакт:** Бенчмарк одного пайплайна на нескольких движках

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Корректный benchmarking](01-benchmarking) | 75 мин | Строит воспроизводимый benchmark harness: фиксирует вход, версии, warm-up, повторы, cache policy, equivalence gate и интерпретирует разброс измерений без ложной точности. | Benchmark harness с environment report и equivalence gate | complete |
| 02 | [CPU и memory profiling](02-profiling) | 75 мин | Профилирует один аналитический pipeline по wall time, CPU и памяти, отделяет Python overhead, native allocations, IO и algorithmic hot spots и выпускает actionable profile report. | CPU/memory profiling report и hot-spot classifier | complete |
| 03 | [Память и типы данных](03-memory-and-dtypes) | 75 мин | Оценивает footprint DataFrame, выбирает dtype policy для чисел, строк, категорий, дат и nullable fields и проверяет, что экономия памяти не меняет бизнес-смысл. | Schema optimization plan с memory budget и semantic checks | complete |
| 04 | [Projection и predicate pushdown](04-parquet-pushdown) | 75 мин | Проектирует Parquet layout с row groups, partitions, statistics и нужными колонками, измеряет projection/predicate pushdown и подтверждает его через query plans. | Parquet layout audit с pushdown benchmark report | complete |
| 05 | [Arrow memory model](05-arrow-memory) | 75 мин | Разбирает Arrow buffers, null bitmaps, offsets, chunks и dictionary encoding, инспектирует PyArrow Table/Array и отличает zero-copy обмен от скрытого копирования. | Arrow memory inspector и copy audit | complete |
| 06 | [DuckDB и данные больше памяти](06-duckdb-out-of-core) | 90 мин | Запускает DuckDB workload с заданными memory_limit, temp_directory и threads, читает EXPLAIN/EXPLAIN ANALYZE, распознает blocking operators и проверяет larger-than-memory ограничения. | DuckDB out-of-core runbook и query profile report | complete |
| 07 | [Polars expressions](07-polars-expressions) | 90 мин | Переносит pipeline из pandas в Polars expressions, использует select/with_columns/filter/group_by contexts, избегает row-wise Python UDF и проверяет эквивалентность результата. | Polars expression pipeline с equivalence tests | complete |
| 08 | [Lazy execution и оптимизация](08-lazy-execution) | 90 мин | Строит lazy scan-план, читает optimized logical plan, подтверждает projection/predicate pushdown и показывает, где ранний collect или UDF блокирует оптимизацию. | Optimized Polars lazy plan audit | complete |
| 09 | [Streaming и пакетная обработка](09-streaming) | 75 мин | Проектирует chunked/streaming обработку для ограниченной памяти, отличает ассоциативные агрегаты от операций с полной координацией и выпускает checkpointed batch report. | Streaming batch processor с checkpoint и correctness report | complete |
| 10 | [Обмен между pandas, Arrow и Polars](10-interoperability) | 75 мин | Передает таблицу между pandas, PyArrow, DuckDB и Polars, проверяет schema/null/timezone/category semantics, фиксирует копии и выбирает минимально дорогую границу обмена. | Interoperability matrix и conversion audit | complete |
| 11 | [Ibis как переносимый DataFrame API](11-ibis) | 120 мин | Выражает один performance pipeline переносимым Ibis API, сравнивает backend-specific планы и измерения с pandas, DuckDB и Polars и оформляет решение о движке с ограничениями. | Multi-engine benchmark package с Ibis portability audit | complete |

## Как проходить фазу

1. Ответьте на входные вопросы до чтения reference implementation.
2. Для каждого урока воспроизведите ручной механизм в локальной папке `work/`.
3. Запустите пример, один failure mode и тесты урока.
4. Выполните хотя бы одно упражнение, которое меняет данные или правило.
5. После фазы пройдите перемешанную самопроверку:

```bash
uv run --locked python scripts/run_quiz.py --phase 12 --stage post --limit 8
```

Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. Критерий освоения — объяснить решение, воспроизвести расчёт и диагностировать хотя бы одну поломку.

## Критерий завершения

Студент воспроизводимо измеряет время и память и обосновывает выбор pandas, DuckDB или Polars.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
