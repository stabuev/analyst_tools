# Peer review: замечание закрывает evidence, а не слово resolved

> Автор отвечает на finding, но только независимый re-review связывает исправление с новым checksum и успешным rerun.

**Тип:** Case  
**Треки:** Core | Product | Data | Decision | ML | Delivery  
**Пререквизиты:** 18-capstones/05-verification  
**Время:** ~300 минут  
**Результат:** проводит evidence-based review чужого проекта, классифицирует findings, отвечает на них как автор и получает `review_ready` только после повторной проверки измененных claims и checksums.

## Цели обучения

- зафиксировать self-review и независимость reviewer до чтения его findings;
- превратить замечание в проверяемую запись с severity, точным evidence и способом проверки;
- отличить ответ автора от независимого решения о закрытии finding;
- связать измененный claim с before/after checksum и затронутыми rerun checks;
- сформировать provisional rubric и передать неизменяемый reviewed package на защиту.

## Проблема

После независимой валидации reference project воспроизводится, shadow calculation проходит,
а четыре negative fixtures ломаются в ожидаемых gates. Это еще не означает, что проект готов
к защите.

Автор может сделать более сильный вывод, чем допускают результаты. В нашем примере frozen
gate сохраняет `baseline`, но при снижении threshold один sensitivity scenario переключается
на `candidate`. Формулировка «решение устойчиво во всех сценариях» противоречит собственному
evidence проекта. Есть и более тонкая проблема: `network_access_declared=false` сообщает о
декларации среды, но не доказывает техническую блокировку сети.

Слабый review-процесс выглядит так:

1. Reviewer пишет «поправьте вывод».
2. Автор отвечает «исправлено» и нажимает `Resolve`.
3. Никто не фиксирует, какой файл изменился и какие проверки надо повторить.
4. На защиту попадает пакет, отличный от проверенного.

Цена ошибки - не только пропущенный баг. Исчезает provenance: невозможно установить, какой
claim видел reviewer, что именно изменил автор и относится ли прежний approval к текущим
байтам.

## Концепция

### Review как отдельный stage gate

В capstone review не переписывает verification package. Он создает новый слой поверх точного
`verification_manifest.json`:

```text
verification_ready package
        |
        | exact manifest SHA-256
        v
self-review -> independent review -> findings
                                    |
                                    v
                         author responses + changes
                                    |
                                    v
                         affected checks rerun
                                    |
                                    v
                           independent re-review
                                    |
                    +---------------+---------------+
                    |                               |
               review_ready                    review_block
                    |                               |
                 defense                       peer review
```

У stage есть четыре разных утверждения:

| Утверждение | Кто его делает | Что оно означает |
|---|---|---|
| `accepted` | Автор | Согласен с finding и внес изменение |
| `passed=true` | Rerun check | Новое состояние выдержало затронутую проверку |
| `closed=true` | Reviewer gate | Finding закрыт после проверки change и rerun evidence |
| `review_ready` | Review package | Все stage gates пройдены, можно начинать defense |

Ни одно из них не означает итоговый `passed`. Финальный статус появится только в `18/07`.

### Независимость reviewer

Допустимы три типа reviewer:

| `reviewer_type` | Когда использовать | Обязательное evidence |
|---|---|---|
| `learner_peer` | Взаимная проверка проектов | Идентификатор peer и отсутствие авторства |
| `mentor` | Проверка преподавателем или экспертом | Идентификатор mentor и conflict disclosure |
| `independent_agent` | Самостоятельный маршрут | Clean review context и assistance disclosure |

Любой reviewer фиксирует:

- собственный `reviewer_id`;
- `is_project_author=false`;
- `conflict_of_interest=false`;
- SHA-256 именно того verification manifest, который он видел;
- время начала review после завершения self-review.

Для самостоятельного прохождения используйте пошаговую инструкцию
[`../../../../docs/capstone-independent-review.md`](../../../../docs/capstone-independent-review.md).
Она описывает обмен с learner peer и clean-context workflow для `independent_agent`,
включая готовый review prompt и минимальный handoff reviewer-а.

Автоматический precheck может найти несоответствие. Но автор или тот же precheck не должен
самостоятельно превратить свое finding в независимое approval.

### Finding - это проверяемая гипотеза об ошибке

Минимальный finding содержит:

```json
{
  "finding_id": "review-finding-001",
  "severity": "major",
  "title": "Sensitivity claim is broader than the verified scenarios",
  "claim_id": "claim-sensitivity",
  "evidence_path": "sensitivity_report.csv#scenario_id=threshold_minus_practical_improvement",
  "expected_behavior": "State the frozen selection and disclose the observed decision flip.",
  "verification_method": "Rerun sensitivity_analysis and claim_evidence_audit.",
  "raised_by_reviewer_id": "independent-review-agent-01"
}
```

Severity отвечает на вопрос «что произойдет, если ничего не менять»:

| Severity | Смысл | Условие закрытия |
|---|---|---|
| `blocker` | Package, права, данные или основной claim недостоверны | Исправление и rerun; waiver только с evidence и ответственным owner |
| `major` | Существенно искажены вывод, метод или воспроизводимость | Исправление и rerun либо принятый owner waiver с evidence |
| `minor` | Ошибка ограничена и не меняет основной decision | Исправление с проверкой или аргументированный ответ |
| `question` | Нужна ясность или улучшение handoff | Проверяемый ответ, при изменении - rerun |

`major` не означает «мне не нравится». Finding обязан указывать точный фрагмент evidence,
ожидаемое поведение и способ проверки. Комментарий «сделайте лучше» не удовлетворяет
контракту.

### Ответ автора не является closure

Автор использует только три статуса:

- `accepted` - согласилась, внесла изменение и перечислила rerun checks;
- `partially_accepted` - исправила часть и явно ограничила оставшуюся часть;
- `declined_with_evidence` - не согласилась и приложила проверяемое evidence.

Поле `resolved` запрещено. Оно смешивает две роли: автор может описать свое действие, но не
может сам подтвердить независимость этого действия.

Для принятого finding response хранит logical change scope:

```text
reviewed_claims.json#claim_id=claim-sensitivity
```

Так один физический JSON-файл можно связать с конкретным claim, а не объявлять измененным
целиком без понимания blast radius.

### Checksum доказывает изменение байтов, rerun - изменение поведения

Пусть:

- `H_before` - canonical SHA-256 claim до response;
- `H_after` - canonical SHA-256 reviewed claim;
- `R(scope)` - множество checks из predeclared change map;
- `P(check)` - результат повторной проверки.

Принятое исправление может быть закрыто, если:

```text
changed(scope) = H_before != H_after
checksum_ok(scope) = H_after == response.expected_after_sha256
rerun_ok(scope) = all(P(check) for check in R(scope))

closed(finding) = response_valid and changed(scope)
                  and checksum_ok(scope) and rerun_ok(scope)
```

Свежий hash не доказывает правильность. Можно заново захешировать тот же слишком широкий
claim. Поэтому reference kit отдельно проверяет semantics: sensitivity claim обязан назвать
наблюдаемый flip, а clean-room claim не может превращать declaration в технически доказанную
изоляцию.

### Re-review вычисляет status

`re_review_report.json` строится из findings, responses, changed-file inventory и фактических
rerun results. Автор не передает готовое поле `closed`.

Критичные правила:

- `accepted` без реального change остается открытым;
- `accepted` без любого затронутого rerun остается открытым;
- `partially_accepted` не закрывает `blocker` или `major`;
- `declined_with_evidence` не закрывает `blocker` или `major` без принятого owner waiver;
- изменение upstream verification package блокирует весь review;
- любой открытый finding оставляет reference package в `review_block`.

### Rubric на review еще не финальная

Review оценивает шесть общих измерений от 0 до 4:

1. Problem framing.
2. Data contract.
3. Method and baseline.
4. Verification.
5. Delivery and handoff.
6. Review and defense.

Каждый score содержит evidence links и rationale. Reference package получает `19/24`, но
поле `provisional_only=true` не позволяет трактовать число как итоговый `passed`. Reviewer
еще не видел live demo, challenge answers и собранный portfolio package.

## Соберите это

### Шаг 1. Заморозьте review contract

Сначала задайте допустимые роли, severity, response statuses и change-to-check map. В spec
не должно быть observed results:

```python
change_check_map = {
    "reviewed_claims.json#claim_id=claim-sensitivity": [
        "sensitivity_analysis",
        "claim_evidence_audit",
    ],
    "reviewed_claims.json#claim_id=claim-clean-room": [
        "clean_room_rerun_summary",
        "claim_evidence_audit",
    ],
}
```

Если mapping составить после исправления, автор сможет выбрать только удобные проверки.

### Шаг 2. Проверьте immutable upstream

Review kit читает каждый output из `verification_manifest.json`, пересчитывает размер и
SHA-256, затем сверяет:

```text
verification_report.status == verification_ready
capstone_state.current_stage == verification
capstone_state.review_id is null
capstone_state.defense_id is null
```

До и после аудита строится полный inventory upstream directory. Любая мутация нарушает
stage boundary.

### Шаг 3. Зафиксируйте self-review и disclosure

Self-review проверяет decision boundary, data rights, baseline, verification coverage и
handoff limitations. Его `completed_at` должен быть раньше `review_started_at`.

Для `independent_agent` дополнительно нужны:

```json
{
  "clean_review_context": true,
  "assistance_disclosure": "Independent agent reviewed only the immutable verification package and this review contract."
}
```

Disclosure не переносит ответственность на инструмент. Оно делает происхождение review
видимым.

### Шаг 4. Постройте finding ledger

Reviewer проходит не только код, а весь decision package:

- decision и claim boundary;
- contract, права, privacy и lineage;
- frozen baseline и method assumptions;
- clean-room, shadow, negative и sensitivity evidence;
- consumer artifact, limitations и handoff;
- согласованность claims с evidence.

Каждый найденный дефект получает одну severity. В reference review есть:

| Finding | Severity | Причина |
|---|---|---|
| Слишком широкий sensitivity claim | `major` | Может изменить интерпретацию decision |
| Завышенное утверждение о network isolation | `minor` | Rerun валиден, но limitation потеряна |
| Неявный retained baseline | `question` | Handoff не сообщает основное решение явно |

### Шаг 5. Запишите response ledger

Автор не редактирует finding. Она добавляет отдельный response:

```json
{
  "response_status": "accepted",
  "changed_scopes": [
    "reviewed_claims.json#claim_id=claim-sensitivity"
  ],
  "rerun_check_ids": [
    "sensitivity_analysis",
    "claim_evidence_audit"
  ],
  "reviewed_claim_sha256": "2446fb15..."
}
```

Так сохраняется история: исходное замечание остается неизменным, а ответ можно проверить
отдельно.

### Шаг 6. Перезапустите затронутые checks

Reference project меняет только reviewed claims, поэтому rerun повторно читает immutable
verification evidence:

- `sensitivity_analysis` сверяет frozen `baseline` и один decision flip;
- `claim_evidence_audit` проверяет точные paths, limitations и upstream verified claims;
- `clean_room_rerun_summary` отделяет `network_access_declared=false` от доказанной блокировки.

Если менялись код или данные, mapping должен включать более широкий набор behavioral,
quality, shadow и clean-room checks. Старый зеленый отчет к новым байтам не относится.

### Шаг 7. Выполните re-review

Gate сопоставляет для каждого finding:

```text
finding
  -> exactly one author response
  -> changed scope
  -> matching after checksum
  -> all predeclared reruns
  -> independent closure decision
```

Только после этого `re_review_report.summary.status` становится
`approved_for_defense`, а state переходит в `review_ready`.

## Используйте это

Артефакт урока - CLI `capstone_peer_review_kit.py`. Он использует только стандартную
библиотеку и не вызывает high-level функции implementation или verifier при обычном
review. Upstream verifier нужен только команде `--write-example`, чтобы построить учебный
verification package.

### Воспроизводимый reference run

Из корня репозитория:

```bash
uv run --locked python \
  phases/18-capstones/06-peer-review/outputs/capstone_peer_review_kit.py \
  --write-example /tmp/capstone-review-input \
  --output-dir /tmp/capstone-review-package \
  --fail-on-invalid
```

Ожидаемый stdout:

```json
{"blocking_errors": [], "closed_findings": 3, "findings": 3, "next_stage": "defense", "provisional_rubric_score": 19, "review_id": "weekly-retention-core-review-v1", "status": "review_ready", "valid": true}
```

### Запуск на своем package

```bash
uv run --locked python \
  phases/18-capstones/06-peer-review/outputs/capstone_peer_review_kit.py \
  --upstream-verification-package path/to/verification-package \
  --review-spec path/to/review_spec.json \
  --review-submission path/to/review_submission.json \
  --output-dir path/to/review-package \
  --fail-on-invalid
```

CLI создает:

```text
review-package/
├── review_spec.json
├── review_report.json
├── review_rubric.json
├── finding_ledger.csv
├── author_responses.csv
├── reviewed_claims.json
├── changed_file_inventory.csv
├── rerun_results.json
├── re_review_report.json
├── capstone_state.json
└── review_manifest.json
```

Reference result нужно читать так:

- `3/3` findings закрыты;
- найден один `major`, один `minor` и один `question`;
- все три logical scopes получили новые checksums;
- три независимые rerun-проверки прошли;
- upstream verification package не изменился;
- `19/24` является provisional score;
- следующий stage - `defense`, но итогового решения еще нет.

## Сломайте это

### Дефект 1. Автор добавляет `resolved=true`

Даже если response содержит правдоподобный текст, поле запрещено. Gate
`author_responses_use_evidence_statuses` падает, а re-review оставляет finding открытым.

### Дефект 2. Major принят без rerun

Автор меняет claim и записывает новый checksum, но удаляет `sensitivity_analysis` из
`rerun_check_ids`. Изменение существует, однако affected-check matrix неполна. Статус -
`review_block`.

### Дефект 3. Ложный claim заново захеширован

Автор возвращает `robust_across_scenarios=true` и честно обновляет SHA-256. Checksum
совпадает, но `sensitivity_analysis` видит decision flip и падает. Integrity не заменяет
semantic validation.

### Дефект 4. Reviewer совпадает с автором

Даже полный finding ledger не является независимым review. Gate
`reviewer_independence_is_disclosed` блокирует stage.

### Дефект 5. Upstream перепрыгнул stage

Кто-то меняет state на `review_ready` и обновляет manifest hash. Байты согласованы, но peer
review еще не начинался с `verification_ready`. Проверка stage semantics ловит подмену.

### Дефект 6. Partial acceptance скрывает открытый major

Для `minor` или `question` ограниченный ответ иногда достаточен. Для `major` статус
`partially_accepted` сохраняет finding в `open_blocker_or_major`, даже если часть checks
прошла.

## Проверьте это

Запустите behavioral tests урока:

```bash
uv run --locked python -m unittest discover \
  -s phases/18-capstones/06-peer-review/tests -v
```

Тесты проверяют не наличие файлов, а поведение gates:

- reference package достигает `review_ready`;
- self-review предшествует независимому review;
- agent раскрывает clean context и assistance;
- finding содержит допустимую severity и точный selector;
- response не может сам объявить resolution;
- каждый finding получает ровно один response;
- stale и unchanged claims не считаются исправлением;
- semantic rerun ловит заново захешированный overclaim;
- open или partially accepted major блокирует package;
- tampered и stage-shifted upstream не принимаются;
- review manifest обнаруживает изменение готового output;
- одинаковые inputs создают byte-identical review outputs.

Проверьте итог вручную:

```bash
uv run --locked python phases/18-capstones/06-peer-review/code/main.py
```

Инварианты успешного reference run:

```text
status == review_ready
closed_findings == finding_count == 3
open_findings == []
re_review_pass == true
upstream_inputs_mutated == false
author_declared_resolution_allowed == false
final_defense_result_claimed == false
```

## Поставьте результат

Именованный артефакт урока:

```text
outputs/capstone_peer_review_kit.py
```

Он поставляется вместе с executable reference package в `outputs/`. `artifact.json`
содержит отдельную команду использования, поэтому CLI можно запустить без чтения урока.

Перед handoff в `18/07` передайте:

- exact `review_manifest.json` и его SHA-256;
- finding и author-response ledgers без переписывания истории;
- `reviewed_claims.json`, который увидел re-reviewer;
- changed-file inventory и rerun results;
- provisional rubric с evidence links;
- state `review_ready`, где `defense_id` все еще `null`.

Если после approval изменился любой reviewed claim, code или data artifact, прежний review
перестает относиться к текущему package. Создайте новый checksum manifest, повторите
затронутые checks и запросите re-review.

## Упражнения

1. Добавьте `question`, на который автор отвечает `declined_with_evidence`. Определите,
   какое evidence позволяет закрыть его без изменения claim.
2. Расширьте `change_check_map` сценарием изменения candidate calculation. Включите
   behavioral tests, shadow calculation и clean-room rerun.
3. Создайте failure fixture, где `major` получает owner waiver без evidence path. Докажите,
   что re-review оставляет finding открытым.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Self-review | Заменяет независимую проверку | Обязательная проверка автора до передачи package reviewer'у |
| Independent reviewer | Любой другой ID | Не автор, с раскрытым конфликтом, контекстом и точным reviewed manifest |
| Finding | Свободный комментарий | Проверяемая запись с severity, evidence, expected behavior и verification method |
| Author response | Решение о закрытии | Позиция автора: accepted, partially accepted или declined_with_evidence |
| Changed scope | Весь измененный файл | Логическая часть artifact, связанная с finding и affected checks |
| Rerun evidence | Повтор старого зеленого статуса | Новый результат затронутой проверки для нового checksum |
| Re-review | Формальное нажатие Resolve | Независимая проверка response, change, checksum и rerun evidence |
| Provisional rubric | Итоговая оценка | Evidence-linked score до live defense и final blocker gates |

## Дополнительное чтение

- [GitHub Docs: About pull request reviews](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/reviewing-changes-in-pull-requests/about-pull-request-reviews) - изучите состояния comment, approve, request changes и повторный запрос review после существенных изменений.
- [Google Engineering Practices: Code Review](https://google.github.io/eng-practices/review/) - сопоставьте независимость reviewer и полный предмет review: design, functionality, tests, complexity и documentation.
- [Google Engineering Practices: How to write code review comments](https://google.github.io/eng-practices/review/reviewer/comments.html) - прочитайте рекомендации по ясному rationale и маркировке severity, чтобы отделять обязательные changes от необязательных замечаний.
- [W3C PROV-O](https://www.w3.org/TR/prov-o/) - углубите модель provenance через сущности, действия и агентов; она объясняет, зачем связывать reviewed artifact, change и reviewer identity.
