<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 11: Analytics Engineering

> Организуйте SQL-преобразования как тестируемый граф моделей.

- **Треки:** data
- **Пререквизиты:** Фаза 07
- **Время:** ~14-18 часов
- **Итоговый артефакт:** Документированная аналитическая витрина

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Слои и контракты аналитических данных](01-data-layers) | 75 мин | Проектирует raw, staging, intermediate и mart слои: фиксирует grain, ключи, владельца, freshness, допустимые изменения схемы и правила публикации аналитической витрины. | Machine-readable layer contract и mart design brief | complete |
| 02 | [Структура dbt-проекта](02-dbt-project) | 75 мин | Собирает минимальный dbt-проект с `dbt_project.yml`, profile contract, каталогами models/tests/macros/snapshots и воспроизводимыми командами parse, compile и debug. | Проверяемый dbt project skeleton с configuration audit | complete |
| 03 | [Sources, refs и зависимости](03-sources-and-refs) | 75 мин | Объявляет raw tables как sources, строит model dependencies через `source()` и `ref()`, проверяет source freshness и запрещает скрытые прямые обращения к raw-таблицам. | Source/ref lineage auditor для dbt graph | complete |
| 04 | [Модели и materializations](04-models) | 90 мин | Строит staging, intermediate и mart модели, выбирает view/table/ephemeral materialization по grain, стоимости и потребителю и сверяет compiled SQL с ожидаемой логикой. | Набор dbt-моделей для customer revenue mart с materialization report | complete |
| 05 | [Data tests](05-data-tests) | 90 мин | Добавляет generic и singular data tests для not null, unique, relationships, accepted values, freshness и бизнес-reconciliation, отделяя contract failures от warning diagnostics. | dbt data test suite и machine-readable test report | complete |
| 06 | [Jinja и macros без злоупотребления](06-macros) | 75 мин | Выносит повторяемые SQL-правила в читаемые Jinja macros, проверяет compiled SQL, документирует аргументы и не прячет бизнес-логику за избыточной абстракцией. | Набор dbt macros с compiled-SQL review checklist | complete |
| 07 | [Инкрементальные модели](07-incremental-models) | 90 мин | Проектирует incremental mart с `is_incremental()`, `unique_key`, late-arrival window, full-refresh policy и тестами против дубликатов, пропущенных обновлений и schema change. | Incremental model contract и backfill/full-refresh playbook | complete |
| 08 | [Snapshots и история изменений](08-snapshots) | 75 мин | Использует dbt snapshots для SCD type 2 истории mutable source tables и проверяет unique key, updated_at/check strategy, validity windows и исключение шумных колонок. | Snapshot model и SCD history audit | complete |
| 09 | [Документация и lineage](09-documentation-and-lineage) | 75 мин | Публикует описания sources, models, columns, tests и exposures, генерирует dbt docs artifacts и связывает downstream claims с lineage и owners. | Документированный lineage package с manifest/catalog summary | complete |
| 10 | [SQLFluff и единый стиль](10-sqlfluff) | 60 мин | Настраивает SQLFluff для DuckDB/dbt SQL, выбирает templater под CI или быстрый feedback, исключает generated artifacts и отличает style violations от semantic test failures. | SQLFluff configuration и lint report для dbt-проекта | complete |
| 11 | [Локальный проект с dbt-duckdb](11-dbt-duckdb-project) | 120 мин | Собирает локальный dbt-duckdb проект: sources, staging/intermediate/mart models, tests, macros, incremental model, snapshot, docs, lineage, SQLFluff report, run artifacts и checksum manifest. | Воспроизводимый analytics-mart-dbt package для customer revenue health mart | complete |

## Как проходить фазу

1. Ответьте на входные вопросы до чтения reference implementation.
2. Для каждого урока выполните прозрачную практику в локальной папке `work/`.
3. Запустите пример и тесты либо заполните артефакт и проверьте его по рубрике.
4. Выполните хотя бы одно упражнение, которое меняет данные или правило.
5. После фазы пройдите перемешанную самопроверку:

```bash
uv run --locked python scripts/run_quiz.py --phase 11 --stage post --limit 8
```

Кнопка прогресса на сайте является ручной отметкой, а не сертификатом. Критерий освоения — объяснить решение, воспроизвести расчет или рассуждение и диагностировать хотя бы одну поломку.

## Критерий завершения

dbt-проект строит витрину, проверяет источники и ключи и публикует документацию lineage.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
