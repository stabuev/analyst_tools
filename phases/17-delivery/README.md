<!-- Generated from curriculum.json. Do not edit manually. -->

# Фаза 17: Доставка аналитического результата

> Превращайте проверенный анализ в воспроизводимый продукт для решения заказчика.

- **Треки:** delivery
- **Пререквизиты:** Фаза 07
- **Время:** ~12-18 часов
- **Итоговый артефакт:** Stakeholder delivery package

## Уроки

| № | Урок | Время | Проверяемый результат | Артефакт | Статус |
|---:|---|---:|---|---|---|
| 01 | [Аналитическая записка для решения](01-analytical-memo) | 75 мин | Пишет короткий decision memo: вопрос, варианты решения, рекомендация, evidence, ограничения и следующий шаг без расширения исходного claim. | Decision memo builder с claim-evidence matrix и no-overclaim audit | complete |
| 02 | [Excel и XlsxWriter для stakeholder workbook](02-excel-xlsxwriter) | 75 мин | Собирает XLSX workbook для заказчика с summary, таблицами, словарем данных, проверками, formatting и сверкой totals с исходными артефактами. | Stakeholder workbook builder с workbook audit, formulas check и data dictionary | complete |
| 03 | [Воспроизводимые отчеты с Quarto](03-quarto) | 90 мин | Переводит анализ в executable Quarto report, где код, таблицы, графики, assumptions и limitations пересобираются из clean inputs одной командой. | Quarto report package с render manifest, source links и rebuild check | complete |
| 04 | [HTML, PDF и DOCX как delivery formats](04-document-formats) | 75 мин | Выпускает HTML, PDF и DOCX версии отчета, проверяя ссылки, figures, layout-sensitive warnings, embedded resources и форматные ограничения. | Multi-format report renderer с HTML/PDF/DOCX outputs и format QA report | complete |
| 05 | [Интерактивный отчет Plotly](05-interactive-plotly) | 75 мин | Добавляет интерактивное Plotly-приложение к отчету: hover context, filters, source table links, sensitive-field redaction и static fallback. | Plotly interactive appendix с figure spec, HTML export и fallback images | complete |
| 06 | [Приложение на Streamlit](06-streamlit) | 90 мин | Собирает Streamlit-приложение поверх проверенных артефактов: фильтры, decision views, warnings, download actions и app contract без скрытого ad-hoc пересчета. | Streamlit stakeholder app с app contract, filters audit и download bundle | complete |
| 07 | [Кеширование, состояние и свежесть приложения](07-caching-and-state) | 75 мин | Разделяет data cache, resource cache и session state, задает TTL/freshness policy и тестирует инвалидацию по checksum входов. | Streamlit cache/state auditor с freshness panel, TTL policy и stale-output checks | complete |
| 08 | [CLI для повторяемого запуска](08-cli) | 75 мин | Оформляет delivery pipeline как CLI с явными input/output paths, `--check`, manifest, атомарной публикацией и различимыми exit codes. | Delivery CLI с check mode, publish manifest и exit-code policy | complete |
| 09 | [Запуски по расписанию и freshness report](09-scheduled-runs) | 75 мин | Проектирует scheduled refresh: cron metadata, timezone/UTC assumptions, last-success marker, run history, freshness report и failure visibility. | Scheduled delivery workflow с run history, freshness report и failure notification mock | complete |
| 10 | [FastAPI как факультативный интерфейс](10-fastapi) | 75 мин | Добавляет optional read-only API к поставленному результату, фиксируя Pydantic request/response schemas, OpenAPI contract и CLI fallback. | FastAPI delivery endpoint с OpenAPI schema, contract tests и read-only boundary | complete |
| 11 | [Docker как факультативная упаковка](11-docker) | 75 мин | Упаковывает CLI/app/API в локальный контейнер, проверяя minimal build context, `.dockerignore`, no-secret policy и equivalence с локальным запуском. | Docker packaging audit с Dockerfile, context report и container run manifest | complete |
| 12 | [Handoff, документация и сопровождение](12-handoff) | 105 мин | Собирает stakeholder delivery package: memo, workbook, report, interactive appendix, app, CLI/schedule, optional API/container, runbook, support policy и checksum manifest. | Stakeholder delivery package с handoff runbook, support policy, decision status и manifest | complete |

## Критерий завершения

Студент поставляет результат в нескольких форматах, пересобирает его одной командой, показывает свежесть, ограничения, owner и понятный handoff.

[Вернуться к общей дорожной карте](../../ROADMAP.md)
