# Независимое ревью capstone

Фаза `18/06` требует reviewer, который не является автором проекта. Для самостоятельного
прохождения не нужен платный наставник: допустим peer из учебного сообщества или отдельный
AI-agent с чистым контекстом. Автоматические тесты остаются precheck и не могут сами
закрыть найденное замечание.

## Вариант 1: взаимное peer review

Обменяйтесь только verification packages, а не рабочими папками и историями подсказок.
Каждый reviewer:

1. фиксирует свой ID и отсутствие авторства;
2. записывает SHA-256 полученного verification manifest;
3. выполняет команды из runbook в чистом каталоге;
4. проверяет claims по evidence paths;
5. возвращает findings с severity, ожидаемым поведением и способом повторной проверки;
6. после исправлений проверяет только новый package и явно закрывает либо переоткрывает
   каждый finding.

## Вариант 2: independent agent

Создайте новую задачу или новый чат без истории разработки проекта. Не передавайте туда
свои объяснения, предполагаемые слабые места и готовые ответы на challenge questions.
Передайте:

- путь или архив verification package;
- точный SHA-256 manifest;
- review spec из `18/06`;
- команду clean rerun;
- этот prompt:

```text
Проведи независимое evidence-based review capstone package.

Ты не автор проекта. Не доверяй итоговому статусу и тексту findings автора. Сначала
проверь manifest и воспроизводимый запуск, затем claims, данные, методологию, негативные
сценарии и публичную границу. Для каждого замечания верни finding_id, severity
(blocker/major/minor/question), точный evidence path, наблюдаемое поведение, ожидаемое
поведение и rerun check. Не закрывай замечание без нового evidence и повторной проверки.
Если блокирующих замечаний нет, скажи это прямо и перечисли остаточные риски.
```

После review сохраните disclosure:

```json
{
  "reviewer_type": "independent_agent",
  "is_project_author": false,
  "conflict_of_interest": false,
  "clean_review_context": true,
  "assistance_disclosed": true
}
```

Новый agent не становится независимым только из-за другого имени. Контекст считается
чистым, если он получил frozen package и review contract, но не участвовал в выборе
метрики, реализации, исправлениях или self-review.

## Что вернуть автору

Минимальный handoff reviewer-а:

```text
reviewer-identity.json
reviewed-manifest.sha256
review-findings.json
review-summary.md
```

Автор отвечает на findings отдельно. Поля автора не должны менять `raised_by`, severity
или исходное evidence reviewer-а. После изменения кода или данных выпускается новый
verification package; старый approval не переносится автоматически.

## Когда ревью считается завершённым

- reviewer видел ровно тот manifest, который передан в defense;
- каждый blocker и major имеет независимый re-review;
- rerun evidence относится к исправленной версии;
- открытые minor/question не скрыты и перенесены в limitations;
- reviewer не подтверждает causal, production или privacy claim только по успешным тестам.
