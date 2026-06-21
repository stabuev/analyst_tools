<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 11: Analytics Engineering

> Организуйте SQL-преобразования как тестируемый граф моделей.

**Треки:** data  
**Пререквизиты:** Фаза 07  
**Время:** ~14-18 часов  
**Итоговый артефакт:** Документированная аналитическая витрина

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | Слои и контракты аналитических данных | 75 мин | Проектирует raw, staging, intermediate и mart слои: фиксирует grain, ключи, владельца, freshness, допустимые изменения схемы и правила публикации аналитической витрины. | Machine-readable layer contract и mart design brief | designed |
| 02 | Структура dbt-проекта | 75 мин | Собирает минимальный dbt-проект с `dbt_project.yml`, profile contract, каталогами models/tests/macros/snapshots и воспроизводимыми командами parse, compile и debug. | Проверяемый dbt project skeleton с configuration audit | designed |
| 03 | Sources, refs и зависимости | 75 мин | Объявляет raw tables как sources, строит model dependencies через `source()` и `ref()`, проверяет source freshness и запрещает скрытые прямые обращения к raw-таблицам. | Source/ref lineage auditor для dbt graph | designed |
| 04 | Модели и materializations | 90 мин | Строит staging, intermediate и mart модели, выбирает view/table/ephemeral materialization по grain, стоимости и потребителю и сверяет compiled SQL с ожидаемой логикой. | Набор dbt-моделей для customer revenue mart с materialization report | designed |
| 05 | Data tests | 90 мин | Добавляет generic и singular data tests для not null, unique, relationships, accepted values, freshness и бизнес-reconciliation, отделяя contract failures от warning diagnostics. | dbt data test suite и machine-readable test report | designed |
| 06 | Jinja и macros без злоупотребления | 75 мин | Выносит повторяемые SQL-правила в читаемые Jinja macros, проверяет compiled SQL, документирует аргументы и не прячет бизнес-логику за избыточной абстракцией. | Набор dbt macros с compiled-SQL review checklist | designed |
| 07 | Инкрементальные модели | 90 мин | Проектирует incremental mart с `is_incremental()`, `unique_key`, late-arrival window, full-refresh policy и тестами против дубликатов, пропущенных обновлений и schema change. | Incremental model contract и backfill/full-refresh playbook | designed |
| 08 | Snapshots и история изменений | 75 мин | Использует dbt snapshots для SCD type 2 истории mutable source tables и проверяет unique key, updated_at/check strategy, validity windows и исключение шумных колонок. | Snapshot model и SCD history audit | designed |
| 09 | Документация и lineage | 75 мин | Публикует описания sources, models, columns, tests и exposures, генерирует dbt docs artifacts и связывает downstream claims с lineage и owners. | Документированный lineage package с manifest/catalog summary | designed |
| 10 | SQLFluff и единый стиль | 60 мин | Настраивает SQLFluff для DuckDB/dbt SQL, выбирает templater под CI или быстрый feedback, исключает generated artifacts и отличает style violations от semantic test failures. | SQLFluff configuration и lint report для dbt-проекта | designed |
| 11 | Локальный проект с dbt-duckdb | 120 мин | Собирает локальный dbt-duckdb проект: sources, staging/intermediate/mart models, tests, macros, incremental model, snapshot, docs, lineage, SQLFluff report, run artifacts и checksum manifest. | Воспроизводимый analytics-mart-dbt package для customer revenue health mart | designed |

## Критерий завершения

dbt-проект строит витрину, проверяет источники и ключи и публикует документацию lineage.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
