# Excel и XlsxWriter для stakeholder workbook

> Workbook для заказчика — это не "таблица в Excel". Это проверяемый интерфейс поверх evidence: summary, фильтры, словарь данных, формулы и audit.

**Тип:** Build  
**Треки:** delivery  
**Пререквизиты:** `17-delivery/01-analytical-memo`  
**Время:** ~75 минут

## Цели обучения

- Спроектировать XLSX workbook как delivery artifact, а не как ручную выгрузку.
- Разделять summary, data tables, data dictionary и checks.
- Использовать XlsxWriter для стабильных sheets, Excel tables, freeze panes, formatting и formulas.
- Проверять workbook через openpyxl: листы, таблицы, формулы, cached values и dictionary coverage.
- Блокировать publication, если upstream memo invalid, totals не сходятся или workbook содержит sensitive columns.

## Проблема

После decision memo заказчик часто просит Excel:

```text
Можно прислать файл, где я сам посмотрю метрики и evidence?
```

Плохой ответ — просто выгрузить CSV в `.xlsx`. Такой файл быстро становится новой точкой правды: кто-то фильтрует строки, кто-то меняет формулу, кто-то не видит, откуда взялась колонка, а ограничения из memo остаются в другом документе.

Еще опаснее workbook, который выглядит аккуратно, но не связан с исходной поставкой:

- summary totals набраны руками;
- нет словаря данных;
- нет проверки, что формулы остались формулами;
- нет связи с `memo_audit.json`;
- sensitive columns просто скрыты, а не исключены;
- reviewer без пересчета формул видит старые cached values.

В этом уроке мы строим `stakeholder-workbook-builder`: он превращает `workbook_spec.json`, `metric_summary.csv`, `claim_evidence_matrix.csv` и `memo_audit.json` в XLSX workbook, workbook audit, data dictionary CSV и manifest.

## Концепция

Stakeholder workbook держится на четырех слоях.

**Summary.** Первый лист отвечает на вопрос "что делать": audience, owner, decision status, freshness и несколько сверяемых totals.

**Tables.** Рабочие листы `Metrics` и `Evidence` используют Excel tables. Это дает фильтры, стабильные диапазоны и понятный audit.

**Data dictionary.** Каждая видимая колонка имеет описание, source, expected type и sensitive flag. Если колонка stakeholder-facing, ее нужно объяснить.

**Workbook audit.** XLSX проверяется как артефакт: листы в правильном порядке, таблицы есть, panes frozen, formulas сохранены, cached values сходятся с CSV, upstream memo valid.

Важно: workbook не пересчитывает исходный анализ. Он делает проверенную evidence удобной для просмотра и handoff. Новые вычисления должны возвращаться в pipeline, а не жить только в Excel.

## Соберите это

Артефакт урока - `outputs/stakeholder_workbook_builder.py`.

Входы:

```text
workbook_spec.json          # audience, owner, decision status, data dictionary
metric_summary.csv          # метрики для листа Metrics
claim_evidence_matrix.csv   # excerpt из 17/01 для листа Evidence
memo_audit.json             # upstream readiness из decision memo
```

Запуск со встроенным примером:

```bash
uv run --locked python phases/17-delivery/02-excel-xlsxwriter/outputs/stakeholder_workbook_builder.py \
  --write-example /tmp/workbook-inputs \
  --output-dir /tmp/stakeholder-workbook
```

Builder создаст:

```text
/tmp/stakeholder-workbook/
├── stakeholder_workbook.xlsx
├── workbook_audit.json
├── data_dictionary.csv
└── manifest.json
```

Внутри XLSX пять листов:

```text
Summary
Metrics
Evidence
Data Dictionary
Checks
```

Ручная часть механизма — контракт workbook: какие листы нужны, какие колонки видимы, какие totals должны сверяться, какие sensitive fields запрещены. XlsxWriter отвечает за создание файла, но не за смысл поставки.

## Используйте это

Откройте `workbook_audit.json`.

Ключевые checks:

1. `upstream_memo_audit_is_valid` — нельзя делать красивый workbook поверх заблокированной записки.
2. `data_dictionary_covers_exported_columns` — каждая видимая колонка описана.
3. `no_sensitive_columns_in_workbook` — скрытие в Excel не считается защитой.
4. `required_excel_tables_present` — `Metrics`, `Evidence`, `Data Dictionary` и `Checks` являются Excel tables.
5. `summary_formulas_are_present` — summary totals остались формулами.
6. `summary_cached_totals_match_sources` — cached values совпадают с исходными CSV.

Проверьте пример:

```bash
uv run --locked python phases/17-delivery/02-excel-xlsxwriter/code/main.py
```

Он создаст временные входы, соберет workbook package и напечатает summary: valid, readiness status, blocking errors и список файлов.

## Сломайте это

Попробуйте четыре поломки.

1. В `memo_audit.json` поставьте `valid: false`. Workbook должен стать invalid.
2. Удалите колонку `threshold` из `metric_summary.csv`. Check `metric_summary_has_required_columns` должен упасть.
3. Пометьте колонку словаря как `sensitive: true`. Check `no_sensitive_columns_in_workbook` должен упасть.
4. Замените formula cell `Summary!B10` на число. Check `summary_formulas_are_present` должен упасть.

Так workbook перестает быть ручным приложением к письму и становится проверяемой частью delivery pipeline.

## Проверьте это

Запустите тесты урока:

```bash
cd phases/17-delivery/02-excel-xlsxwriter
uv run --locked python -m unittest discover -s tests -v
```

Тесты проверяют:

- sample workbook valid и пишет все package files;
- workbook содержит ожидаемые листы, Excel tables и freeze panes;
- summary formulas имеют cached values, совпадающие с source metrics;
- Metrics и Evidence сохраняют порядок исходных строк;
- Data Dictionary покрывает видимые колонки;
- blocked upstream memo audit блокирует workbook;
- отсутствующая metric column блокирует input contract;
- неизвестный metric status отклоняется;
- sensitive dictionary column блокирует публикацию;
- audit ловит tampered summary formula;
- manifest хеширует входы и выходы;
- CLI строит package через `--write-example`;
- CLI возвращает non-zero для invalid workbook в strict mode;
- `code/main.py` запускается без внешних файлов.

## Поставьте результат

Готовый результат урока:

- `outputs/stakeholder_workbook_builder.py` - CLI-builder stakeholder workbook package;
- `stakeholder_workbook.xlsx` - XLSX с `Summary`, `Metrics`, `Evidence`, `Data Dictionary`, `Checks`;
- `workbook_audit.json` - машинная проверка workbook contract;
- `data_dictionary.csv` - словарь видимых колонок;
- `manifest.json` - SHA-256 manifest входов и выходов;
- `tests/test_main.py` - behavioral tests для workbook delivery contract.

Handoff для коллеги:

```text
Stakeholder workbook собран поверх valid decision memo. Summary totals являются
формулами и cached values сходятся с metric_summary.csv. Metrics/Evidence отданы
как Excel tables с фильтрами; Data Dictionary покрывает все видимые колонки.
Sensitive columns в workbook не попали. Workbook audit valid.
```

## Упражнения

1. Добавьте лист `Risks` с таблицей risks и расширьте data dictionary.
2. Сделайте `Summary!B12` ссылкой на named range или Excel table formula и обновите audit.
3. Добавьте проверку, что все `owner` в Metrics входят в заранее утвержденный список.
4. Добавьте conditional formatting для `quality_status == warn` на листе Evidence и проверьте его в audit.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Stakeholder workbook | "Excel-выгрузка" | Проверяемый XLSX-интерфейс поверх уже проверенной evidence |
| Excel table | "Просто диапазон с заголовками" | Именованный объект Excel с фильтрами и стабильным диапазоном |
| Data dictionary | "Опциональное описание" | Контракт видимых колонок: смысл, source, expected type и sensitive flag |
| Cached value | "Неважная служебная деталь" | Значение формулы, которое увидит reviewer без пересчета workbook |
| Workbook audit | "Проверка, что файл открылся" | Набор инвариантов о структуре, формулах, источниках и безопасности workbook |
| Sensitive column | "Колонка, которую можно скрыть" | Поле, которое нельзя публиковать в stakeholder workbook; скрытие не является защитой |

## Дополнительное чтение

- [XlsxWriter: Working with Pandas and XlsxWriter](https://xlsxwriter.readthedocs.io/working_with_pandas.html) - официальный раздел о writer engine, workbook/worksheet objects, tables, formatting и формулах рядом с DataFrame output.
- [XlsxWriter: The Worksheet Class](https://xlsxwriter.readthedocs.io/worksheet.html) - API worksheet для freeze panes, tables, formulas, conditional formatting и layout controls.
- [pandas.ExcelWriter](https://pandas.pydata.org/docs/reference/api/pandas.ExcelWriter.html) - как pandas выбирает Excel writer engine и где проходит граница между DataFrame export и workbook customization.
- [openpyxl tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html) - чтение XLSX обратно для audit: листы, ячейки, формулы и cached values.
- [Аналитическая записка для решения](../../01-analytical-memo/docs/ru.md) - предыдущий урок: workbook строится поверх valid memo, а не вместо него.
