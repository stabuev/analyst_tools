# HTML, PDF и DOCX как delivery formats

> Формат отчета выбирают под способ принятия решения, а не под кнопку Export.

**Тип:** Build
**Треки:** Delivery
**Пререквизиты:** `17-delivery/03-quarto`
**Время:** ~75 минут
**Результат:** вы выпускаете HTML, PDF и DOCX версии отчета из Quarto report package и проверяете format QA: links, figures, embedded resources, layout warnings, target commands и checksums.

## Цели обучения

- Разделять один reproducible report source и несколько delivery targets: HTML, PDF, DOCX.
- Проверять форматные риски: self-contained HTML, static fallback для PDF/DOCX, валидный OOXML, source links и figure traceability.
- Писать manifest, который сохраняет реальные `quarto render --to ...` команды и hashes всех отправленных файлов.

## Проблема

В прошлом уроке появился `report.qmd` и HTML-preview. Теперь заказчик просит "пришлите PDF для согласования, DOCX для комментариев и HTML для страницы проекта". Наивный ответ - три раза нажать Export и разложить файлы по письмам.

Так ломается delivery:

- HTML может ссылаться на локальный `figures/guardrail_status.svg`, которого нет у получателя;
- PDF может потерять интерактивный смысл, широкую таблицу или SVG, если нет подходящего PDF engine;
- DOCX может выглядеть как документ, но содержать external relationships или устаревший текст;
- три файла могут быть собраны из разных версий входов.

В этом уроке формат становится проверяемым контрактом. Вы собираете три delivery targets из одного upstream report package и рядом кладете `format_qa_report.json`, `asset_inventory.csv`, `link_audit.csv` и `format_manifest.json`.

## Концепция

Один аналитический отчет может иметь несколько потребителей.

| Формат | Хорошо подходит для | Что проверяем отдельно |
|---|---|---|
| HTML | Быстрый просмотр, публикация в репозитории, файл для браузера | embedded resources, anchors, figures, source links |
| PDF | Согласование, архив, печать, fixed layout | static content, layout warnings, PDF engine boundary |
| DOCX | Комментарии, редактура, юридический или управленческий review | OOXML package, отсутствие external relationships, переносимость текста |

Quarto умеет нацеливать один `.qmd` на разные output formats. Но сам факт существования `report.pdf` не доказывает, что он собран из того же source, что HTML, и не потерял важный context. Поэтому форматный QA отвечает на четыре вопроса:

1. Все targets явно объявлены?
2. Все outputs трассируются к одному upstream package?
3. Ресурсы, figures и links не сломаны?
4. Форматные ограничения видны как blockers или warnings?

В локальной среде курса внешний Quarto CLI, TeX engine и Word renderer не входят в `uv.lock`. Поэтому артефакт урока делает deterministic preview-файлы: настоящий self-contained HTML, минимальный валидный PDF и минимальный валидный DOCX. Реальные команды Quarto сохраняются в manifest:

```bash
quarto render report.qmd --to html --execute-params params.yml
quarto render report.qmd --to pdf --execute-params params.yml
quarto render report.qmd --to docx --execute-params params.yml
```

Это важная граница: lesson renderer проверяет delivery contract, но не заменяет полноценный Quarto renderer в рабочей среде.

## Соберите это

Сначала опишите минимальный format contract.

```python
from pathlib import Path

required_targets = {"html": "report.html", "pdf": "report.pdf", "docx": "report.docx"}

def delivery_targets_exist(package_dir: Path) -> bool:
    return all((package_dir / filename).is_file() for filename in required_targets.values())
```

Эта функция слишком слабая: она не понимает, из чего собраны файлы. Усильте контракт:

```python
def target_manifest_is_traceable(manifest: dict) -> bool:
    commands = manifest["render_commands"]
    outputs = manifest["outputs"]
    return (
        commands["html"].startswith("quarto render report.qmd --to html")
        and commands["pdf"].startswith("quarto render report.qmd --to pdf")
        and commands["docx"].startswith("quarto render report.qmd --to docx")
        and all(len(outputs[key]["sha256"]) == 64 for key in ["html_report", "pdf_report", "docx_report"])
    )
```

Теперь QA проверяет не наличие красивых файлов, а их происхождение и пригодность для передачи.

## Используйте это

Запустите CLI из корня репозитория:

```bash
uv run --locked python phases/17-delivery/04-document-formats/outputs/multi_format_report_renderer.py \
  --write-example /tmp/format-example \
  --output-dir /tmp/multi-format-report
```

`--write-example` сначала собирает upstream Quarto report package из урока `17/03`, затем выпускает delivery targets:

```text
multi-format-report/
├── report.html
├── report.pdf
├── report.docx
├── format_targets.json
├── asset_inventory.csv
├── link_audit.csv
├── format_qa_report.json
└── format_manifest.json
```

Откройте `format_targets.json`. Там зафиксированы три target-команды и policy:

```json
{
  "required_targets": ["html", "pdf", "docx"],
  "format_limits": {
    "max_table_columns_for_pdf": 8,
    "max_unbroken_token_chars": 52,
    "block_interactive_content_for_static_targets": true
  }
}
```

Откройте `format_qa_report.json`. В happy path статус `ready`, а blockers пустые. Если вы собираете реальный проект с установленным Quarto, замените deterministic preview на настоящий render, но оставьте тот же QA contract.

## Сломайте это

Проверьте типовые поломки.

1. Удалите `docx` из `required_targets`. QA должен заблокировать пакет: stakeholders ожидают три формата.
2. Исправьте `source_links.csv` так, чтобы один source path указывал на несуществующий файл. `link_audit.csv` должен показать `missing`.
3. Замените embedded SVG в HTML на `src="figures/guardrail_status.svg"`. Self-contained HTML больше не готов к file handoff.
4. Добавьте `<script>plotly()</script>` в `report.qmd`. PDF/DOCX должны быть заблокированы, пока нет static fallback.
5. Сделайте `max_table_columns_for_pdf` меньше фактической ширины таблицы. QA должен оставить пакет valid, но записать layout warning.

Важно: layout warning не равен blocker. Широкая таблица может быть приемлемой для analyst review, но риск должен быть виден до отправки executive-потребителю.

## Проверьте это

Тесты урока проверяют:

- happy path создает HTML, PDF, DOCX, targets, asset inventory, link audit, QA report и manifest;
- HTML содержит embedded SVG data URI и сохраняет checksum traceability;
- PDF является настоящим PDF-файлом с header/EOF и target command;
- DOCX является OOXML zip package без external relationships;
- manifest хранит команды `quarto render --to html/pdf/docx`, input/output hashes и renderer boundary;
- broken source links, invalid upstream report audit, missing target, unsupported target, non-embedded HTML resource, external DOCX relationship и interactive-only content блокируют delivery;
- layout warning остается warning, а не blocker;
- rebuild check видит changed upstream input and changed outputs.

Запуск:

```bash
uv run --locked python -m unittest discover -s phases/17-delivery/04-document-formats/tests -v
```

## Поставьте результат

Именованный артефакт: `outputs/multi_format_report_renderer.py`.

Он принимает уже собранный report package:

```bash
uv run --locked python phases/17-delivery/04-document-formats/outputs/multi_format_report_renderer.py \
  --report-dir /path/to/quarto-report-package \
  --format-spec /path/to/format_targets.json \
  --output-dir /path/to/multi-format-report \
  --fail-on-invalid
```

Передавать дальше нужно не только `report.pdf` или `report.docx`, а весь небольшой bundle: три target-файла, `format_qa_report.json`, `format_manifest.json`, `asset_inventory.csv` и `link_audit.csv`. Тогда получатель или следующий аналитик видит, какие файлы были отправлены, откуда они собраны и что QA считал риском.

## Упражнения

1. Добавьте `html_minimal` как optional target и проверьте, что отсутствие optional output не блокирует required HTML/PDF/DOCX.
2. Расширьте `asset_inventory.csv` колонкой `consumer_task`: review, archive, browser, comment.
3. Добавьте проверку максимального размера self-contained HTML и переведите ее из warning в blocker для email-handoff policy.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Delivery target | Просто расширение файла | Формат с явным потребителем, render-командой, ограничениями и QA |
| Self-contained HTML | HTML без ссылок вообще | HTML, где ресурсы отображения встроены; source links как lineage могут сохраняться |
| PDF engine boundary | Деталь установки | Условие воспроизводимости PDF: без engine нельзя считать PDF target настоящим render |
| OOXML package | Обычный бинарный Word-файл | ZIP-структура DOCX, где можно проверить document XML и relationships |
| Layout warning | Ошибка данных | Риск читаемости или переноса, который виден в QA и не всегда блокирует delivery |

## Дополнительное чтение

- [Quarto: HTML Basics](https://quarto.org/docs/output-formats/html-basics.html) — раздел про `embed-resources`, self-contained HTML, anchors и поведение внешних ссылок.
- [Quarto: PDF Basics](https://quarto.org/docs/output-formats/pdf-basics.html) — prerequisites для PDF, роль TeX/TinyTeX и опции вроде TOC, numbering, syntax highlighting.
- [Quarto: Word Basics](https://quarto.org/docs/output-formats/ms-word.html) — как выглядит `docx` target, какие опции переносятся в Word и где граница templates.
- [Quarto: All Formats](https://quarto.org/docs/output-formats/all-formats.html) — обзор format options, полезный когда нужно понять, что является target option, а что общим project metadata.
