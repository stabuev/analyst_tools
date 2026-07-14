# Защита решения: сначала блокеры, затем баллы

> Защита не создает evidence: она показывает, что решение, claims и воспроизводимый пакет относятся к одним и тем же проверенным байтам.

**Тип:** Case  
**Треки:** Core | Product | Data | Decision | ML | Delivery  
**Пререквизиты:** 18-capstones/06-peer-review  
**Время:** ~300 минут  
**Результат:** собирает portfolio-ready capstone package, проводит защиту до десяти минут с live rerun, отвечает минимум на три класса challenge questions и получает итоговый статус по blocker gates и общей rubric.

## Цели обучения

- собрать immutable outputs шести стадий в единый portfolio package с provenance и SHA-256 manifest;
- заранее зафиксировать defense contract, чтобы результат презентации не менял правила оценивания;
- провести короткий decision brief и live demo с check mode и повторным запуском;
- отвечать на challenge questions через evidence, границу claim и следующий проверяемый шаг;
- вычислить `revision_required`, `passed` или `passed_with_distinction`, применяя блокеры раньше rubric.

## Проблема

Проект прошел независимую verification и peer review. Все findings закрыты, но это еще не
портфолио и не итоговый `passed`.

Папка с красивыми графиками может скрывать несколько разных версий проекта. Презентация
может ссылаться на результат, которого нет в reviewed package. Live demo может запускать
обновленный код, а reviewer видел старый. Высокий rubric score может отвлечь от утечки
персональных данных или незакрытого blocker. Наконец, уверенный ответ на вопрос может выйти
далеко за границу наблюдаемых данных.

Слабая защита проверяет ораторское мастерство. Сильная защита проверяет цепочку:

```text
decision -> claim -> exact evidence -> reviewed checksum -> reproducible rerun
```

Если любое звено отсутствует, презентация не компенсирует дефект. Задача финальной стадии -
собрать проверенную историю проекта без переписывания этой истории.

## Концепция

### Финальный package - новый слой, а не новая версия прошлого

Каждая предыдущая стадия остается отдельной immutable directory:

```text
brief -> data -> baseline -> implementation -> verification -> review
                                                           exact manifest SHA-256
                                                                     |
                                                                     v
                                                               defense spec
                                                                     |
                           +-----------------------------------------+
                           v
                 portfolio package -> verify mode -> final status
```

Builder копирует только outputs, перечисленные в stage manifests. Для каждого файла он
сохраняет source checksum в `handoff/stage-provenance.json`, а затем строит root
`manifest.json`. Получаются два независимых уровня контроля:

1. Root manifest обнаруживает поврежденный, пропавший или незарегистрированный файл.
2. Stage provenance обнаруживает подмену reviewed evidence, даже если злоумышленник заново
   посчитал root checksum.

Defense audit вычисляет inventory каждой source directory до и после проверки. Если аудит
изменил upstream package, нарушена сама граница стадии.

### Defense contract фиксируется до наблюдения результата

`defense-spec.json` связывает защиту с точными `project_id`, `review_id` и SHA-256
`review_manifest.json`. В нем заранее определены:

- восемь обязательных разделов brief;
- лимит десять минут;
- классы challenge questions и допустимые статусы ответов;
- hash implementation runner и команда check mode;
- критические блокеры;
- шесть измерений rubric и пороги статусов;
- публичная data policy и обязательное дерево package.

Поля вроде `final_status` или `observed_score` в spec запрещены. Иначе документ уже не
предобъявляет правила, а маскирует под них увиденный результат.

### Десятиминутный brief рассказывает decision story

Обязательные разделы идут в одном порядке:

| Раздел | На какой вопрос отвечает |
|---|---|
| Decision | Какое решение и кто должен принять? |
| Data | Каковы grain, временная граница, права и дефекты? |
| Baseline | С чем сравнивали более сложный метод? |
| Method | Что именно реализовано и почему? |
| Result | Что произошло по замороженному критерию? |
| Limitations | Чего evidence не доказывает? |
| Recommendation | Что делать сейчас? |
| Next step | Какой следующий тест уменьшит неопределенность? |

Reference project сохраняет `baseline`: candidate дал `0.666667`, не преодолев
предобъявленный threshold `0.766667`. Это не провал защиты. Отрицательный результат с
честной рекомендацией сильнее post-hoc порога, подобранного под желаемый ответ.

### Live demo показывает проверку, а не скриншот

Demo состоит из двух разных действий:

```text
check mode     проверяет дерево, hashes, provenance, policy и статусы
live rerun     заново исполняет implementation и сравнивает каждый output hash
```

Успешный CLI exit code недостаточен без наблюдаемого сравнения outputs. И наоборот,
совпавшая метрика недостаточна, если manifest stale или package содержит запрещенные
данные.

### Challenge answer имеет четыре опоры

Ответ считается защищенным, когда содержит:

1. ответ или честное указание неизвестного;
2. границу claim;
3. точный evidence path;
4. следующий проверяемый шаг.

Нужно покрыть минимум три разных класса:

- `data_defect`;
- `method_assumption`;
- `alternative_explanation`;
- `failed_deployment_condition`;
- `changed_business_constraint`.

Фраза «я не знаю» допустима. Недопустима только неопределенность без границы и способа ее
уменьшить. Например: «Операционная надежность неизвестна на tiny profile; package не делает
SLA claim; следующий шаг - owned scheduled pilot с freshness и escalation tests».

### Блокеры применяются раньше rubric

Финальная rubric имеет шесть измерений по 0-4:

1. Problem framing.
2. Data contract.
3. Method and baseline.
4. Verification.
5. Delivery and handoff.
6. Review and defense.

Сначала вычисляются критические gates: continuity, checksums, права, privacy, review closure,
bounded claims, live rerun и отсутствие restricted material. Только при отсутствии блокеров
применяются пороги:

```text
passed:
  every dimension >= 2
  data, method/baseline, verification >= 3
  total >= 18

passed_with_distinction:
  every dimension >= 3
  total >= 22

otherwise:
  revision_required
```

Reference package получает `21/24` и `passed`. Distinction не присваивается: problem
framing, data contract и method/baseline ограничены tiny aggregate profile. Итоговый статус
описывает качество evidence этого проекта, а не личную ценность автора.

## Соберите это

### Шаг 1. Проверьте шесть source packages

Для каждой стадии найдите manifest и `capstone_state.json`, затем проверьте status, каждый
output checksum и непрерывность upstream bindings:

```python
bindings = [
    ("data", "upstream_capstone_state", "brief", "capstone_state.json"),
    ("baseline", "upstream_data_manifest", "data", "data_package_manifest.json"),
    ("implementation", "upstream_baseline_manifest", "baseline", "baseline_manifest.json"),
    ("verification", "upstream_implementation_manifest", "implementation", "implementation_manifest.json"),
    ("review", "upstream_verification_manifest", "verification", "verification_manifest.json"),
]
```

Шесть валидных папок еще не образуют один проект. Совпасть должны project, route, stage IDs
и все upstream hashes.

### Шаг 2. Свяжите spec с reviewed manifest

Defense spec и submission должны содержать одинаковый `reviewed_manifest_sha256`. Сам hash
пересчитывается с текущего `review_manifest.json`, а не берется на доверии из формы:

```python
reviewed_hash = sha256_file(review_package / "review_manifest.json")
assert spec["reviewed_manifest_sha256"] == reviewed_hash
assert submission["reviewed_manifest_sha256"] == reviewed_hash
```

После любого изменения review package требуется новый review cycle. Нельзя обновить hash в
форме защиты и сохранить старое approval.

### Шаг 3. Проверьте brief, claims и questions

Для каждого claim храните statement, type, exact evidence path и limitation. Descriptive
claim с формулировкой `causes`, `causal effect` или `guarantees` блокируется.

Challenge question хранит класс, answer status, answer, claim boundary, evidence path и
next check. Минимум три класса должны быть различны; пять классов в reference package
показывают полный профиль failure modes.

### Шаг 4. Выполните live rerun

Runner запускается в чистой временной directory с замороженными baseline package и
implementation spec. Builder сравнивает SHA-256 каждого output из
`implementation_manifest.json`:

```python
match = rerun_sha256 == reviewed_output_sha256
live_rerun_valid = return_code == 0 and all(output_matches)
```

В сохраняемый отчет не попадают случайные temporary paths. Иначе два одинаковых запуска
дали бы разные финальные manifests.

### Шаг 5. Соберите дерево и provenance

Финальный package содержит:

```text
capstone-portfolio-package/
├── brief/              # brief, risks, milestones, source state
├── data/               # contract, manifest, audit, public aggregate sample
├── baseline/           # report, gate, manual cross-check
├── implementation/     # config, runner, outputs, trace and evidence
├── verification/       # rerun, shadow, negative and sensitivity evidence
├── review/             # rubric, findings, responses and re-review
├── defense/            # brief, demo, questions, audit and decision report
├── handoff/            # runbook, limitations, disclosure and provenance
├── capstone-state.json
├── rubric-result.json
└── manifest.json
```

Raw sources не копируются. Для публичного просмотра остается только разрешенный aggregate
или synthetic sample.

### Шаг 6. Вычислите итоговый статус

Builder сначала собирает список failed checks. Любой элемент списка становится blocker и
дает `revision_required`; rubric рассчитывается для диагностики, но не отменяет blocker.

Reference result:

```json
{
  "blocking_errors": [],
  "live_rerun_match": true,
  "rubric_score": 21,
  "status": "passed"
}
```

## Используйте это

Соберите reference inputs и portfolio package одной командой:

```bash
uv run --locked python phases/18-capstones/07-defense/outputs/capstone_portfolio_builder.py \
  --write-example /tmp/capstone-defense-input \
  --output-dir /tmp/capstone-defense-output \
  --fail-on-invalid
```

Для собственного проекта передайте шесть package directories, исходный brief,
implementation runner, defense spec и defense submission отдельными аргументами. Builder
не ищет «последнюю» версию автоматически: каждый вход должен быть назван явно.

Проверьте уже собранный package без пересборки:

```bash
uv run --locked python phases/18-capstones/07-defense/outputs/capstone_portfolio_builder.py \
  --verify-package /tmp/capstone-defense-output/capstone-portfolio-package
```

Нулевой exit code означает, что текущее дерево согласовано с manifest, provenance и public
policy. Он не означает production certification или доказанную причинность.

## Сломайте это

### Fixture 1. Подмените reviewed package и пересчитайте root manifest

Измените `review/re-review-report.json`, затем обновите его checksum в root manifest.
Простая проверка outputs пройдет, но `stage-provenance.json` сохранит исходный source hash и
выдаст `stage_provenance` error.

### Fixture 2. Добавьте fake secret marker

Добавьте в handoff-файл тестовую строку вида `TOKEN=<fake>` и заново посчитайте root
checksum. Verify mode должен остановиться на `public_scan`. Само слово «fake» не делает
публикацию безопасной: policy проверяет форму утечки.

### Fixture 3. Откройте finding и пересчитайте review manifest

Поставьте `open_findings=["RF-001"]`, обновите checksum и синхронизируйте defense form с
новым manifest hash. Package станет checksum-consistent, но review closure останется ложным.

### Fixture 4. Усильте descriptive claim

Замените «ranks high_touch first» на «causes churn reduction». Файл evidence существует,
но claim выходит за границу метода, поэтому защита получает blocker.

### Fixture 5. Уберите следующий шаг у неизвестного

Оставьте `answer_status=unknown_with_testable_next_step`, но очистите `next_check`.
Неопределенность больше не операционализирована, и challenge gate не пройдет.

## Проверьте это

Behavioral suite проверяет 26 сценариев:

- happy path дает `passed`, `21/24`, пять challenge classes и exact live rerun;
- два одинаковых build дают одинаковые output hashes;
- audit не изменяет ни одну source stage directory;
- stale, tampered и rehashed upstream evidence блокируются разными gates;
- открытый finding нельзя закрыть обновлением checksum;
- автор не может оценивать собственную защиту;
- brief длиннее десяти минут или без раздела не проходит;
- claims требуют существующее evidence и bounded language;
- unknown answer требует testable next step;
- PII column, fake secret marker, missing и untracked files обнаруживаются;
- blocker отменяет даже distinction-level rubric score.

Запуск:

```bash
uv run --locked python -m unittest discover \
  -s phases/18-capstones/07-defense/tests -v
```

После сборки отдельно запустите code example и verify mode. Не считайте защиту завершенной,
пока status в `manifest.json`, `capstone-state.json`, `rubric-result.json` и
`defense-audit.json` не совпадает.

## Поставьте результат

Именованный артефакт урока - `capstone-portfolio-builder` в
`outputs/capstone_portfolio_builder.py`. Он работает как CLI и импортируемый модуль.

`code/main.py` строит reference package в
`outputs/capstone-portfolio-package/`. Для передачи начните с
`defense/decision-report.md`, затем покажите `rubric-result.json`, выполните команду из
`handoff/runbook.md` и только после этого открывайте подробное stage evidence.

Перед публичной публикацией выполните verify mode на точной directory, которую собираетесь
передать. Любое последующее изменение требует повторной проверки и нового manifest.

## Упражнения

1. Сократите reference brief до семи минут, не потеряв ни один из восьми разделов, и
   объясните, какое evidence вы оставили для challenge questions.
2. Возьмите собственный capstone route, составьте пять вопросов разных классов и для каждого
   укажите claim boundary, exact evidence path и testable next step.
3. Добавьте новый public policy marker и negative fixture, который пересчитывает root
   manifest после подмены. Докажите, что verify mode все равно блокирует package.
4. Постройте rubric profile на `22/24`, который не получает distinction, и профиль на
   `22/24`, который получает. Объясните роль minimum per dimension.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Defense | Хорошо рассказанная презентация | Проверка decision story, evidence traceability, live rerun и границ claims |
| Provenance | Список файлов в архиве | Проверяемая связь entity с source entity, activity и ответственным agent |
| Live rerun | Повторный показ сохраненного результата | Новый запуск reviewed runner с пофайловым сравнением outputs |
| Blocker-first rubric | Большой балл обычно компенсирует дефект | Любой критический blocker дает `revision_required` до применения порогов |
| Bounded answer | Неуверенный ответ | Утверждение с явной границей, evidence и следующим тестом |
| Public boundary | Удаление очевидных паролей | Запрет raw sources, PII, secrets и любых неразрешенных данных в каждом tracked файле |
| Distinction | Просто высокий total score | `total >= 22` и одновременно каждое измерение не ниже 3 при нуле блокеров |

## Дополнительное чтение

- [W3C PROV-O](https://www.w3.org/TR/prov-o/) - прочитайте starting-point terms `Entity`, `Activity`, `Agent` и связи derivation/attribution; они дают формальную модель для stage provenance.
- [SLSA Provenance](https://slsa.dev/spec/v1.2/provenance) - сопоставьте subject digest, build definition и run details с root manifest, frozen inputs и live rerun этого урока.
- [GitHub Artifact Attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations) - изучите, чем подписанная build provenance усиливает локальные checksums и почему attestation не заменяет policy checks.
- [The Turing Way: Guide for Reproducible Research](https://book.the-turing-way.org/reproducible-research/reproducible-research/) - используйте раздел как следующий шаг от единичного воспроизводимого package к устойчивой практике проекта и команды.
