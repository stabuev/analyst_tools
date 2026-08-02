# От наблюдения к аналитическому выводу

> Хороший EDA заканчивается не красивой картинкой, а проверяемым выводом с ограничениями и следующим действием.

**Тип:** Case  
**Треки:** Core  
**Пререквизиты:** 06/10  
**Время:** ~105 минут  
**Результат:** собирает воспроизводимый EDA-отчет, связывает каждый вывод с вопросом,
расчетом и графиком и отделяет наблюдение от объяснения, ограничения и следующего шага.

## Цели обучения

- Собирать результаты всех шагов в одну delivery.
- Разделять observation, explanation, limitation и recommendation.
- Связывать утверждения с расчетами и файлами evidence.
- Проверять целостность поставки checksum manifest.

## Проблема

После EDA часто остается notebook с десятками графиков и выводом «похоже, проблема в
Android». Коллега не знает, какие строки исключены, где знаменатель, какой interval
показан и какой файл подтверждает утверждение. При повторном экспорте часть картинок
меняется независимо от текста.

## Концепция

Финальный аналитический блок состоит из четырех разных утверждений:

| Блок | Вопрос |
|---|---|
| Observation | что непосредственно показывают проверенные данные |
| Explanation | какие механизмы согласуются с наблюдением |
| Limitation | что дизайн данных не позволяет утверждать |
| Next step | какое действие уменьшит неопределенность |

Evidence map связывает каждое observation с control calculation и artifact. Manifest
связывает все файлы с конкретными bytes и параметрами.

## Соберите это

Минимальная функция не смешивает четыре поля:

```bash
uv run --locked python code/main.py
```

Фраза «Android ухудшился» является observation только после явного сравнения. Фраза
«релиз сломал Android» остается hypothesis без causal design.

## Используйте это

```bash
uv run --locked python outputs/eda_report_builder.py \
  --input ../data/tiny/user_journeys.csv \
  --contract ../data/contract.json \
  --output-dir eda-report
```

Delivery содержит:

```text
eda-report/
├── question.json
├── audit.json
├── report.md
├── visual-review.json
├── figures/
│   ├── activation-overview.png
│   ├── activation-overview.svg
│   └── segment-comparison.png
├── interactive/
│   └── anomaly-explorer.html
├── specs/
│   └── linked-segments.vl.json
└── manifest.json
```

Builder переиспользует исполняемые артефакты предыдущих уроков через их standalone API,
а заполненный brief 06/01 переносит как reviewable decision record. Аудитор 06/02
исполняет contract, после чего основной activation frame и фигура применяют его
checksum-bound selection plan. Статус rubric review не подменяет data readiness:
фактическое evidence находится в `audit.json`, а применённые decision ids попадают в
manifest фигуры. Bootstrap unit, seed и repeats записываются в manifest.

## Сломайте это

1. Измените фигуру после создания manifest.
2. Удалите audit decision log.
3. Смешайте observation и causal explanation.
4. Не покажите sample size.
5. Сформулируйте следующий шаг как «исправить активацию».

Checksum должен обнаружить изменение, а review - отсутствие конкретного evidence или
action.

## Проверьте это

- обязательные файлы существуют;
- question содержит результат rubric review, несколько возможных исходов и ссылку на
  отдельное evidence готовности данных в `audit.json`;
- audit сохраняет известные defects;
- анализ использует 22 из 25 строк tiny;
- report имеет четыре раздела и evidence map;
- HTML standalone, spec содержит linked selection;
- checksum каждого файла совпадает с manifest.

```bash
uv run --locked python -m unittest discover -s tests
```

## Поставьте результат

`outputs/eda_report_builder.py` - интеграционный артефакт фазы. Каталог можно передать
коллеге без notebook state: вопрос, решения аудита, расчеты, статические и интерактивные
представления и целостность поставки находятся рядом.

## Упражнения

1. Соберите delivery на sample profile.
2. Добавьте CSV с period и segment metrics в evidence map.
3. Введите schema version и проверку обратной совместимости manifest.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Observation | Любая интерпретация | Проверяемое описание данных |
| Explanation | Доказанная причина | Гипотеза механизма, если нет identification |
| Limitation | Формальная оговорка | Граница допустимого вывода |
| Next step | Общая рекомендация | Конкретная проверка или решение |
| Evidence map | Список картинок | Связь утверждения, расчета и файла |
| Delivery manifest | Архив файлов | Версия, параметры, paths и checksums |

## Дополнительное чтение

- [Government Analysis Function: Communicating quality, uncertainty and change](https://analysisfunction.civilservice.gov.uk/policy-store/communicating-quality-uncertainty-and-change/) - изучите явное сообщение ограничений и uncertainty.
- [The Turing Way: Reproducible Research](https://book.the-turing-way.org/reproducible-research/overview) - сопоставьте reproducibility, provenance и reusable outputs.
- [NIST: Exploratory Data Analysis](https://www.itl.nist.gov/div898/handbook/eda/eda.htm) - вернитесь к роли EDA как проверки структуры и предпосылок, а не финального causal вывода.
