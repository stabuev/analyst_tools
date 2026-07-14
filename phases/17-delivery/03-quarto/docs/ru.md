# Воспроизводимые отчеты с Quarto

> Отчет для решения должен пересобираться из чистых входов, а не вспоминаться из последнего открытого notebook.

**Тип:** Build
**Треки:** Delivery
**Пререквизиты:** `17-delivery/02-excel-xlsxwriter`
**Время:** ~90 минут
**Результат:** вы собираете Quarto report package с executable `report.qmd`, параметрами, source links, HTML-preview, audit, rebuild check и checksum manifest.

## Цели обучения

- Разделять исходный `report.qmd`, параметры render, входные evidence-файлы и готовый HTML-output.
- Делать report package проверяемым: source links, checksums, assumptions, limitations и upstream gates.
- Ловить stale output: если вход изменился, зависящие output-файлы должны измениться или доставка блокируется.

## Проблема

После memo и XLSX workbook заказчик просит "нормальный отчет": короткий HTML, где есть рекомендация, таблицы, график, assumptions, limitations и инструкция перезапуска. Самый быстрый путь - открыть notebook, нажать export и отправить HTML.

Цена ошибки неприятная. Через неделю кто-то спросит: "Из каких данных это было собрано? Почему график не совпадает с workbook? Можно пересобрать отчет на свежем окне?" Если ответ зависит от памяти аналитика и состояния notebook, это не delivery artifact.

В этом уроке отчет становится маленьким продуктом:

- clean inputs лежат отдельно;
- `report.qmd` содержит executable Python-блоки;
- `params.yml` фиксирует параметры render;
- `source_links.csv` связывает разделы отчета с входными файлами;
- `render_manifest.json` хранит checksums;
- `rebuild_check.json` показывает, не отправляем ли мы stale output.

## Концепция

Quarto полезен не тем, что "делает HTML". HTML может сделать много инструментов. Его рабочая сила для аналитика - в том, что Markdown, код, таблицы, графики и параметры живут в одном исполняемом документе.

Минимальная модель delivery report:

| Слой | Что проверяем |
|---|---|
| Source | `report.qmd`, `_quarto.yml`, `params.yml` существуют и portable |
| Inputs | metrics, evidence, memo/workbook audits читаются из clean files |
| Execution | в `report.qmd` есть executable Python blocks и parameters cell |
| Evidence | каждый source artifact имеет link, section и SHA-256 |
| Claim boundary | assumptions и limitations видны в отчете |
| Rebuild | измененный input меняет зависящие outputs или блокирует доставку |

Локальная среда курса не требует установленный Quarto CLI: внешний бинарь не входит в `uv.lock`. Поэтому артефакт урока генерирует настоящий Quarto source package и детерминированный HTML-preview для тестов. Если у вас установлен Quarto, этот же пакет можно отрендерить командой из manifest:

```bash
quarto render report.qmd --to html --execute-params params.yml
```

## Соберите это

Сначала вручную опишите, что должен доказать report package.

```python
from pathlib import Path

required = {
    "source": ["_quarto.yml", "report.qmd", "params.yml"],
    "inputs": ["metric_summary.csv", "claim_evidence_matrix.csv", "workbook_audit.json"],
    "outputs": ["report.html", "source_links.csv", "render_manifest.json"],
    "narrative": ["assumptions", "limitations", "rerun"],
}

def has_contract(package_dir: Path) -> bool:
    return all((package_dir / name).exists() for names in required.values() for name in names)
```

Эта функция еще наивная: она проверяет только наличие файлов. В реальной поставке важно не просто "файл есть", а:

- `report.qmd` содержит исполняемые блоки, а не pasted output;
- source links указывают на существующие входы;
- HTML содержит таблицы, график и limitations;
- manifest хранит hashes;
- rebuild check сравнивает текущую сборку с предыдущей.

## Используйте это

Запустите готовый CLI из корня репозитория:

```bash
uv run --locked python phases/17-delivery/03-quarto/outputs/quarto_report_packager.py \
  --write-example /tmp/quarto-inputs \
  --output-dir /tmp/quarto-report-package
```

Пакет содержит:

```text
quarto-report-package/
├── _quarto.yml
├── params.yml
├── report.qmd
├── report.html
├── figures/
│   └── guardrail_status.svg
├── source_links.csv
├── report_audit.json
├── rebuild_check.json
└── render_manifest.json
```

Откройте `report.qmd`. В нем есть параметры:

````markdown
```{python}
#| tags: [parameters]
metrics_path = "metric_summary.csv"
evidence_path = "claim_evidence_matrix.csv"
workbook_audit_path = "workbook_audit.json"
memo_audit_path = "memo_audit.json"
```
````

И есть executable-блоки для таблиц:

````markdown
```{python}
#| label: tbl-metrics
#| tbl-cap: "Stakeholder metric summary"
metrics[["metric_id", "label", "current", "baseline", "threshold", "status", "owner"]]
```
````

`report.html` в этом уроке - deterministic preview, чтобы тесты не зависели от внешнего Quarto CLI. В рабочей среде, где установлен Quarto, source package можно пересобрать настоящим renderer. Важно, что команда render лежит в `render_manifest.json`, а не в голове автора.

## Сломайте это

Проверьте типовые поломки.

1. Удалите limitations из `report_spec.json`. Audit должен заблокировать отчет: recommendation без границ легко превращается в overclaim.
2. Поменяйте `source_artifacts[0].path` на несуществующий файл. Audit должен найти broken source link.
3. Добавьте в `metric_summary.csv` колонку `user_email`. Даже если HTML ее не показывает, source package больше не stakeholder-safe.
4. Удалите `figures/guardrail_status.svg` после сборки и запустите audit. Отчет без required figure нельзя отправлять как готовый.
5. Соберите пакет, затем измените `metric_summary.csv` и пересоберите с `--previous-manifest`. `rebuild_check.json` должен показать changed input и changed outputs.

Пример проверки rebuild:

```bash
uv run --locked python phases/17-delivery/03-quarto/outputs/quarto_report_packager.py \
  --spec /tmp/quarto-inputs/report_spec.json \
  --metrics /tmp/quarto-inputs/metric_summary.csv \
  --evidence /tmp/quarto-inputs/claim_evidence_matrix.csv \
  --workbook-audit /tmp/quarto-inputs/workbook_audit.json \
  --memo-audit /tmp/quarto-inputs/memo_audit.json \
  --previous-manifest /tmp/quarto-report-package/render_manifest.json \
  --output-dir /tmp/quarto-report-package-rerun
```

## Проверьте это

Тесты урока проверяют:

- happy path создает Quarto source package, HTML-preview, figure, audit и manifest;
- `_quarto.yml` и `params.yml` portable и нацелены на `report.qmd`;
- `report.qmd` содержит Python parameters cell, tables, figure cross-reference и render command;
- `source_links.csv` покрывает required artifacts и хранит SHA-256;
- invalid workbook/memo handoff блокирует report;
- missing limitations, broken source links, sensitive source fields and missing figures блокируют delivery;
- rebuild check видит changed input and output drift;
- CLI возвращает exit code `2` при `--fail-on-invalid`.

Запуск:

```bash
uv run --locked python -m unittest discover -s phases/17-delivery/03-quarto/tests -v
```

## Поставьте результат

Именованный артефакт: `outputs/quarto_report_packager.py`.

Он принимает явные пути:

```bash
uv run --locked python phases/17-delivery/03-quarto/outputs/quarto_report_packager.py \
  --spec /path/to/report_spec.json \
  --metrics /path/to/metric_summary.csv \
  --evidence /path/to/claim_evidence_matrix.csv \
  --workbook-audit /path/to/workbook_audit.json \
  --memo-audit /path/to/memo_audit.json \
  --output-dir /path/to/quarto-report-package \
  --fail-on-invalid
```

Для передачи другому человеку отправляйте не только `report.html`, а весь package или хотя бы `report.qmd`, `params.yml`, `source_links.csv`, `report_audit.json`, `rebuild_check.json` и `render_manifest.json`. Иначе получатель видит страницу, но не может доказать, откуда она взялась.

## Упражнения

1. Добавьте в `report_spec.json` второй figure requirement и расширьте audit так, чтобы он проверял оба SVG.
2. Сделайте отдельный `format_target` для PDF, но не запускайте PDF render: только добавьте contract и test, который объясняет, почему PDF появится в следующем уроке.
3. Добавьте в `source_links.csv` колонку `section_anchor` и проверьте, что каждый anchor есть в HTML-preview.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Quarto report | Это просто красивый HTML | Исполняемый документ, где текст, код, параметры и outputs связаны render-командой |
| Source links | Список файлов для удобства | Проверяемая lineage-таблица: source id, path, section и checksum |
| Render manifest | Лог запуска | Контракт воспроизводимости: render command, input/output hashes, renderer boundary |
| Rebuild check | Timestamp последней сборки | Сравнение текущих inputs/outputs с предыдущим manifest, чтобы не отправить stale output |
| Limitations | Формальность в конце | Граница claim, без которой delivery может ввести заказчика в заблуждение |

## Дополнительное чтение

- [Quarto: Using Python](https://quarto.org/docs/computations/python.html) — как executable Python blocks попадают в `.qmd` и как работает `quarto render`.
- [Quarto: Execution Options](https://quarto.org/docs/computations/execution-options.html) — какие cell-level и document-level options управляют `echo`, `warning`, `error`, output и include.
- [Quarto: Parameters](https://quarto.org/docs/computations/parameters.html) — как задавать параметры для Jupyter/Python reports и передавать их через `--execute-params`.
- [Quarto: Project Basics](https://quarto.org/docs/projects/quarto-projects.html) — зачем нужны `_quarto.yml`, project render targets и общий metadata contract.
- [Quarto: HTML Basics](https://quarto.org/docs/output-formats/html-basics.html) — `embed-resources`, external links, anchors и другие детали HTML handoff.
