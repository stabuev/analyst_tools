# Handoff, документация и сопровождение

> Финальная поставка становится полезной только тогда, когда вместе с файлами передается ответственность за их эксплуатацию.

**Тип:** Case
**Треки:** Delivery
**Пререквизиты:** `17-delivery/11-docker`
**Время:** ~105 минут
**Результат:** вы собираете stakeholder delivery package с memo, workbook, report, interactive appendix, app, CLI/schedule, optional API/container, runbook, support policy и checksum manifest.

## Цели обучения

- Собрать финальный пакет поставки из всех consumer-facing артефактов фазы 17.
- Зафиксировать owner, backup owner, cadence, rerun command, escalation path, known limitations и retirement triggers.
- Превратить upstream audit-ы в явный `decision_status` и root manifest с SHA-256 для каждого файла.
- Проверить, что optional API/container включены только как passing contract-checked interfaces и не скрывают upstream quality gates.

## Проблема

К концу фазы у вас уже есть много хороших артефактов: executive memo, workbook, Quarto report, PDF/DOCX/HTML, Plotly appendix, Streamlit app, CLI, schedule, FastAPI и optional Docker package. Но stakeholder не живет внутри вашего репозитория. Ему нужна не россыпь файлов, а понятная передача:

- что можно использовать прямо сейчас;
- какие предупреждения и ограничения остаются;
- кто владеет поставкой после handoff;
- как перезапустить расчет;
- куда эскалировать проблему;
- когда артефакт нужно снять с поддержки;
- как проверить, что файлы не потерялись и не изменились.

Без этого аналитическая поставка быстро превращается в "вроде где-то был отчет". Ошибка здесь не в расчете метрики, а в эксплуатации результата: никто не знает, какой файл главный, как обновить данные и кто отвечает за stale output.

## Концепция

Handoff package — это контракт передачи результата. Он включает consumer formats, operational docs и audit envelope.

Минимальная структура в этом уроке такая:

```text
stakeholder-delivery-package/
├── input/
│   ├── upstream-package-manifest.json
│   ├── delivery-spec.json
│   ├── evidence-index.csv
│   └── quality-gate-summary.json
├── memo/
├── workbook/
├── report/
├── interactive/
├── app/
├── automation/
├── optional-api/
├── optional-container/
├── handoff/
│   ├── runbook.md
│   ├── support-policy.md
│   ├── changelog.md
│   ├── stakeholder-email.md
│   ├── handoff_contract_tests.json
│   └── handoff_audit.json
└── manifest.json
```

`input/quality-gate-summary.json` переводит технические проверки в управленческий статус:

| Статус | Когда использовать |
|---|---|
| `ship_now` | Все gates проходят, freshness свежий, предупреждений нет или они уже приняты. |
| `ship_with_warnings` | Поставка пригодна, но есть раскрытые warnings. |
| `blocked_by_quality_gate` | Один из upstream layers invalid. |
| `needs_methodology_review` | Технически пакет собран, но нужна методологическая проверка. |
| `stale_input` | Данные или schedule freshness устарели. |
| `owner_handoff_only` | Файлы передаются владельцу, но stakeholder decision еще нельзя запускать. |

Root `manifest.json` нужен не для красоты. Он записывает SHA-256 и размер каждого файла, кроме самого manifest. Получатель может сверить пакет после пересылки, публикации release или копирования в shared storage.

## Соберите это

Артефакт урока лежит в `outputs/stakeholder_delivery_package.py`. Happy path сам генерирует учебные входы через предыдущие уроки фазы и собирает финальный пакет:

```bash
python phases/17-delivery/12-handoff/outputs/stakeholder_delivery_package.py \
  --write-example /tmp/stakeholder-handoff-example \
  --output-dir /tmp/stakeholder-delivery-package
```

Внутри `/tmp/stakeholder-handoff-example` будут созданы upstream packages: workbook из урока 17/02 и цепочка delivery-артефактов до Docker из урока 17/11. Затем builder скопирует только нужные файлы в финальную структуру и запишет:

- `input/evidence-index.csv` — карта слоев, назначений, owner и checksum;
- `input/quality-gate-summary.json` — сводку upstream gates и итоговый `decision_status`;
- `handoff/runbook.md` — как перезапустить и где что лежит;
- `handoff/support-policy.md` — response time, escalation и retirement triggers;
- `handoff/changelog.md` — что добавлено в этой версии;
- `handoff/stakeholder-email.md` — короткий текст передачи результата;
- `handoff/handoff_audit.json` — итоговый audit;
- `manifest.json` — SHA-256 manifest всего пакета.

Если входы уже собраны, передайте их явно:

```bash
python phases/17-delivery/12-handoff/outputs/stakeholder_delivery_package.py \
  --source-root /path/to/delivery-source \
  --docker-package-dir /path/to/docker-delivery-package \
  --workbook-package-dir /path/to/stakeholder-workbook-package \
  --handoff-contract /path/to/handoff_contract.json \
  --output-dir /tmp/stakeholder-delivery-package \
  --fail-on-invalid
```

`--fail-on-invalid` делает артефакт пригодным для CI: upstream quality block возвращает код `10`, handoff contract block — код `2`, системная ошибка — код `30`.

## Используйте это

Начните с `handoff/runbook.md`. Хороший получатель должен за пару минут понять:

1. Какой `decision_status` у поставки.
2. Кто primary owner и backup owner.
3. Какая cadence и команда rerun.
4. Где memo, workbook, report, app, schedule, optional API и optional container.
5. Какие limitations нельзя забывать при интерпретации.

Затем откройте `input/quality-gate-summary.json`. Он показывает не только итоговый статус, но и каждый слой:

```json
{
  "layer": "optional_container",
  "valid": true,
  "status": "success",
  "blocking_errors": [],
  "warnings": []
}
```

Если хотя бы один слой invalid, финальный статус становится `blocked_by_quality_gate`. Это защищает от опасной ситуации, когда красивый handoff скрывает сломанный API, контейнер или stale schedule.

Перед отправкой stakeholder-у проверьте `handoff/stakeholder-email.md`. Это не замена документации, а короткая обложка: что вложено, какой статус, где runbook, где manifest, куда идти за поддержкой.

## Сломайте это

Сломайте handoff contract:

```json
{
  "decision_status": "definitely_ship",
  "owner": {
    "primary": "same-owner",
    "backup": "same-owner",
    "escalation_channel": "#trial-onboarding-delivery"
  },
  "support_policy": {
    "retirement_triggers": []
  }
}
```

Builder должен вернуть `handoff_contract_block`, потому что:

- `decision_status` не входит в allowed list;
- backup owner совпадает с primary owner;
- нет retirement triggers.

Сломайте upstream Docker audit: удалите `docker_audit.json` из Docker package или измените его `valid` на `false`. Финальный handoff должен стать `upstream_package_block`, потому что optional container включается только вместе с passing contract.

Сломайте public artifact: добавьте в любой публичный `.md`, `.json`, `.py` или `.html` строку вида:

```text
TOKEN=do-not-ship
```

Handoff audit должен показать `public_artifacts_have_no_secret_or_private_key_markers`. Пакет нельзя передавать как valid, даже если все метрики посчитаны правильно.

## Проверьте это

Запустите тесты урока:

```bash
python -m unittest phases/17-delivery/12-handoff/tests/test_main.py
```

Тесты проверяют:

- финальный пакет содержит обязательные consumer formats и optional interfaces;
- default handoff contract называет owner, backup, support policy и retirement triggers;
- quality summary покрывает memo, workbook, report, interactive, app, automation, optional API и optional container;
- manifest хеширует каждый файл пакета, кроме самого manifest;
- runbook и support policy содержат rerun, escalation, limitations и retirement policy;
- invalid handoff contract блокирует поставку;
- invalid upstream Docker audit блокирует handoff как upstream quality problem;
- secret marker в публичном файле блокирует handoff;
- CLI и пример из `code/main.py` возвращают валидный summary.

Полная проверка курса:

```bash
python scripts/validate_course.py
python scripts/render_curriculum.py --check
python scripts/render_outputs.py --check
python scripts/render_site.py --check
python -m unittest discover -s tests
python scripts/run_lesson_tests.py
```

## Поставьте результат

Именованный артефакт:

```text
outputs/stakeholder_delivery_package.py
```

Минимальная команда:

```bash
python phases/17-delivery/12-handoff/outputs/stakeholder_delivery_package.py \
  --write-example /tmp/stakeholder-handoff-example \
  --output-dir /tmp/stakeholder-delivery-package
```

Сценарий использования вне урока:

1. Соберите upstream delivery packages через фазу 17.
2. Подготовьте `handoff_contract.json` с владельцами, cadence, rerun command и support policy.
3. Запустите builder с `--fail-on-invalid`.
4. Передайте stakeholder-у весь `stakeholder-delivery-package/`, а не отдельный PDF.
5. В сообщении укажите `decision_status`, ссылку на `handoff/runbook.md`, `handoff/support-policy.md` и `manifest.json`.

## Упражнения

1. Добавьте в handoff contract новый `decision_status` из allowed list и проверьте, как он попадает в `quality-gate-summary.json`.
2. Добавьте в `support_policy.retirement_triggers` условие про смену бизнес-владельца и убедитесь, что оно появляется в `support-policy.md`.
3. Сымитируйте stale freshness report в upstream schedule и проверьте, что итоговый статус становится `stale_input`.
4. Добавьте новый consumer format, например `slides/`, и расширьте contract tests так, чтобы отсутствие slides блокировало handoff.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Handoff package | Просто zip-файл с финальными артефактами | Пакет файлов, ответственности, проверок, инструкций и статуса решения. |
| Runbook | README с общим описанием | Операционная инструкция: как перезапустить, где смотреть ошибки, кто владеет. |
| Support policy | Обещание отвечать на любые вопросы | Ограниченный контракт поддержки: response time, escalation, out-of-scope и retirement triggers. |
| Decision status | Украшение для отчета | Нормализованное состояние, которое говорит, можно ли использовать поставку сейчас. |
| Checksum manifest | Техническая формальность | Способ доказать целостность пакета после передачи или публикации. |
| Retirement trigger | Признак провала | Условие, при котором артефакт честно выводят из поддержки или заменяют новым. |

## Дополнительное чтение

- [GitHub Docs: About READMEs](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-readmes) — прочитайте список вопросов, на которые README должен отвечать пользователю проекта; это хороший минимум для внешней обложки handoff package.
- [GitHub Docs: About releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) — посмотрите, как release notes и assets помогают передавать версионированные артефакты за пределы репозитория.
- [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) — используйте разделы Added, Changed, Fixed и Security как практический словарь для stakeholder-friendly changelog.
- [Diátaxis](https://diataxis.fr/) — сопоставьте runbook с how-to guide, manifest с reference, а limitations с explanation, чтобы документация не смешивала разные задачи читателя.
