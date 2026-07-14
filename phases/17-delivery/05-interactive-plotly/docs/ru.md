# Интерактивный отчет Plotly

> Интерактивность в отчете полезна только тогда, когда она проверяема, трассируема и имеет статический fallback.

**Тип:** Build
**Треки:** Delivery
**Пререквизиты:** `17-delivery/04-document-formats`
**Время:** ~75 минут
**Результат:** вы добавляете standalone Plotly appendix к проверенному multi-format report package и проверяете hover context, dropdown filters, source table links, sensitive-field redaction, static fallback и rebuild audit.

## Цели обучения

- Проектировать интерактивный appendix как delivery contract, а не как декоративный график.
- Собирать Plotly figure JSON и standalone HTML с dropdown filters, customdata и hovertemplate.
- Проверять source lineage, redaction policy, static fallback и checksum manifest для интерактивного файла.

## Проблема

После HTML, PDF и DOCX у команды появляется новый запрос: "Можно ли открыть отчет и быстро понять, какие guardrail metrics тащат решение `pause_rollout`? Хочу фильтровать breached/watch/ok и видеть evidence прямо на графике".

Наивный ответ - вставить интерактивный график в HTML и отправить файл. В аналитическом delivery это опасно:

- hover может показывать красивые labels, но не давать metric grain, owner и evidence count;
- filters могут скрывать строки так, что человек теряет связь с исходной таблицей;
- HTML может требовать CDN или Dash server, хотя передается как static file;
- source table links могут остаться в основном отчете, но пропасть из интерактивного appendix;
- в hover легко случайно вынести `email`, `user_id`, `token` или другой чувствительный столбец;
- PDF/DOCX-получатель видит пустое место вместо смысла графика, если нет static fallback.

В этом уроке интерактивность становится отдельным проверяемым bundle поверх результата `17/04`.

## Концепция

Интерактивный appendix отвечает не на вопрос "какой график красивый?", а на вопрос "какое решение человек должен проверить быстрее?".

Минимальный контракт:

| Часть | Зачем нужна |
|---|---|
| `interactive_spec.json` | Фиксирует audience task, allowed filters, hover fields, source ids и redaction policy |
| `plotly_figure_spec.json` | Сохраняет Plotly figure как machine-readable JSON |
| `interactive_appendix.html` | Дает standalone HTML, который открывается без backend |
| `source_table_links.csv` | Связывает figure с source tables и их checksums |
| `static-fallbacks/metric_status.svg` | Сохраняет основной смысл для каналов без JavaScript |
| `interaction_audit.json` | Показывает, готов ли appendix к delivery |
| `interaction_manifest.json` | Хэширует inputs/outputs и проверяет rebuild consistency |

Важно отделять две вещи.

Интерактивный график может быть основным способом расследования: dropdown по статусам, hover с evidence, быстрый обзор breached metrics.

Но интерактивный график не должен быть единственным носителем смысла. Поэтому рядом остается статический SVG и source links.

## Соберите это

Сначала соберите маленький контракт без Plotly. Пусть есть rows по метрикам:

```python
rows = [
    {"metric_id": "support_ticket_rate_7d", "label": "Support ticket rate, 7d", "status": "breached"},
    {"metric_id": "support_reason_coverage", "label": "Support reason coverage", "status": "watch"},
]

def rows_for_filter(rows: list[dict], status_filter: str) -> list[dict]:
    if status_filter == "all":
        return rows
    return [row for row in rows if row["status"] == status_filter]
```

Теперь добавьте hover contract:

```python
hover_fields = [
    "metric_id",
    "label",
    "status",
    "current",
    "baseline",
    "threshold",
    "owner",
    "evidence_count",
    "decision_impacts",
]

def customdata_for_rows(rows: list[dict], hover_fields: list[str]) -> list[list[str]]:
    return [[row.get(field, "") for field in hover_fields] for row in rows]
```

Так вы строите механизм, который Plotly позже спрячет внутри trace: одна точка на графике должна нести ровно тот контекст, который нужен для решения.

Добавьте redaction rule:

```python
import re

sensitive_field = re.compile(r"(email|phone|token|secret|password|user_id)", re.I)

def public_row(row: dict) -> dict:
    return {key: value for key, value in row.items() if not sensitive_field.search(key)}
```

Правило простое, но принцип важный: source table может содержать больше полей, чем разрешено показывать в hover или public JSON.

## Используйте это

Запустите артефакт:

```bash
uv run --locked python phases/17-delivery/05-interactive-plotly/outputs/plotly_interactive_appendix.py \
  --write-example /tmp/plotly-example \
  --output-dir /tmp/interactive-appendix \
  --fail-on-invalid
```

`--write-example` сначала собирает upstream package из `17/04`, затем создает интерактивный bundle:

```text
interactive-appendix/
├── interactive_spec.json
├── interactive_appendix.html
├── plotly_figure_spec.json
├── static-fallbacks/
│   └── metric_status.svg
├── source_table_links.csv
├── interaction_audit.json
└── interaction_manifest.json
```

Внутри builder делает обычный Plotly `go.Figure`:

- один bar trace на каждый filter: `all`, `ok`, `watch`, `breached`;
- `customdata` хранит metric id, статус, значения, owner и evidence count;
- `hovertemplate` явно показывает decision context;
- `updatemenus` создает dropdown для фильтрации;
- `pio.to_html(..., full_html=True, div_id="plotly-interactive-appendix")` сохраняет standalone HTML.

Откройте `interaction_audit.json`. В happy path:

```json
{
  "valid": true,
  "readiness_status": "ready",
  "summary": {
    "blocking_errors": []
  }
}
```

Аудит проверяет, что upstream format QA из `17/04` зеленый, source tables резолвятся из manifest, HTML не требует Dash или CDN script, fallback связан из HTML, source links покрывают metric/evidence tables, а чувствительные source fields не попали в public outputs.

## Сломайте это

Проверьте типовые failure modes.

1. Удалите `breached` из `allowed_filters`. Аудит должен заблокировать appendix: фильтры являются частью decision contract.
2. Удалите `owner` или `evidence_count` из `hover_fields`. Hover больше не дает нужный контекст для разбирательства.
3. Исправьте upstream `link_audit.csv`, поставив одному source статус `missing`. Appendix не должен строиться поверх сломанной lineage.
4. Добавьте в source metric table колонку `user_email`. Builder должен не включить ее в HTML, figure JSON, fallback и source links.
5. После сборки вручную допишите `customer@example.com` в HTML. Повторный audit должен поймать sensitive leak.
6. Удалите `static-fallbacks/metric_status.svg`. Даже валидный Plotly HTML больше не готов к delivery без fallback.

Самая частая ошибка - думать, что "это же только hover". Hover является публичным интерфейсом отчета. Относитесь к нему как к короткой таблице, которую увидит любой получатель файла.

## Проверьте это

Тесты урока проверяют:

- happy path пишет HTML, figure JSON, fallback, source table links, audit, manifest и spec;
- Plotly JSON содержит dropdown filters, traces, customdata и hovertemplate;
- HTML содержит `Plotly.newPlot`, нужный div и source/fallback sections, но не требует Dash runtime или CDN script;
- static fallback содержит metric ids и threshold context;
- source links покрывают `metric_summary` и `claim_evidence_matrix` с SHA-256;
- upstream format QA, broken link audit, missing source table link, missing hover field и missing filter блокируют delivery;
- sensitive source column редактируется из public outputs;
- tampered sensitive leak и удаленный fallback ловятся повторным audit;
- rebuild check видит changed source input and changed primary outputs;
- CLI возвращает exit code `2` при `--fail-on-invalid`.

Запуск:

```bash
uv run --locked python -m unittest discover -s phases/17-delivery/05-interactive-plotly/tests -v
```

## Поставьте результат

Именованный артефакт: `outputs/plotly_interactive_appendix.py`.

Для реального multi-format package:

```bash
uv run --locked python phases/17-delivery/05-interactive-plotly/outputs/plotly_interactive_appendix.py \
  --delivery-dir /path/to/multi-format-report \
  --interactive-spec /path/to/interactive_spec.json \
  --output-dir /path/to/interactive-appendix \
  --fail-on-invalid
```

Если пересобираете appendix после изменения данных, передайте previous manifest:

```bash
uv run --locked python phases/17-delivery/05-interactive-plotly/outputs/plotly_interactive_appendix.py \
  --delivery-dir /path/to/multi-format-report \
  --interactive-spec /path/to/interactive_spec.json \
  --previous-manifest /path/to/old/interaction_manifest.json \
  --output-dir /path/to/new/interactive-appendix \
  --fail-on-invalid
```

Передавать дальше нужно не только `interactive_appendix.html`. Delivery bundle включает HTML, figure JSON, fallback SVG, source table links, audit и manifest. Тогда следующий человек может понять, что именно было интерактивным, какие источники использовались, что было отредактировано и почему bundle считается готовым.

## Упражнения

1. Добавьте новый filter `needs_owner_review` и проверьте, что audit требует его присутствия в dropdown.
2. Расширьте `source_table_links.csv` колонкой `used_columns` и проверьте, что она не содержит sensitive fields.
3. Добавьте warning на слишком большой standalone HTML, но не делайте его blocker для файлового handoff.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Plotly appendix | Любой интерактивный график | Отдельный delivery bundle с figure JSON, HTML, fallback, source links, audit и manifest |
| Hover context | Подсказка с красивым текстом | Проверяемый набор полей, который объясняет точку без раскрытия лишних source fields |
| Customdata | Внутренняя деталь Plotly | Место, где per-point context попадает в hovertemplate и поэтому становится частью публичного интерфейса |
| Static fallback | Скриншот для красоты | Минимальный статический носитель смысла для PDF/DOCX, архивов и сред без JavaScript |
| Rebuild audit | Проверка timestamp | Сравнение input/output checksums, которое ловит stale или неожиданно изменившийся appendix |

## Дополнительное чтение

- [Plotly Python Graphing Library](https://plotly.com/python/) — обзор `graph_objects`, Figure API и базовой модели traces/layout, на которой построен artifact урока.
- [Plotly: Hover Text and Formatting](https://plotly.com/python/hover-text-and-formatting/) — как устроены hovertemplate и per-point данные, полезно для контроля decision context.
- [Plotly: Dropdown Menus](https://plotly.com/python/dropdowns/) — раздел про `updatemenus`, buttons и изменение видимости traces через dropdown.
- [Plotly: Interactive HTML Export](https://plotly.com/python/interactive-html-export/) — как сохранять figures в HTML, выбирать `include_plotlyjs` и понимать standalone trade-offs.
