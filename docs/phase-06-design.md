# Проект фазы 06: EDA и визуальное мышление

Канонический порядок, статусы, длительность и результаты уроков находятся в
[`../curriculum.json`](../curriculum.json). Этот документ фиксирует границы содержания,
единый набор данных, роли библиотек и контракт интеграционного проекта.

## Результат фазы

Студент начинает не с типа графика, а с рабочего вопроса и единицы анализа. До
визуализации он проверяет данные, затем выбирает представление под сравнение, показывает
неопределенность и завершает исследование ограниченным фактами выводом.

Фаза состоит из четырех последовательных блоков:

1. `06/01`–`06/02`: постановка вопроса и аудит входных данных.
2. `06/03`–`06/06`: статическая фигура, распределения, связи и неопределенность.
3. `06/07`–`06/09`: высокоуровневая статистическая, интерактивная и декларативная
   визуализация.
4. `06/10`–`06/11`: доступность, визуальное ревью и интеграционный EDA-отчет.

Суммарная длительность — 930 минут, или 15,5 часа.

## Границы содержания

- **Аудит данных, не production contract.** `06/02` проверяет пригодность конкретного
  среза к исследованию. Переиспользуемые схемы, Pandera и quality gates остаются фазе 07.
- **Визуальная неопределенность, не полный статистический вывод.** `06/06` вводит
  bootstrap как прозрачный способ показать изменчивость оценки. Выборочные механизмы,
  свойства оценок и доверительные интервалы систематизируются в фазе 09.
- **Связь, не причинность.** Стратификация помогает обнаружить смешение сегментов, но
  график не доказывает причинный эффект. Причинные утверждения остаются фазе 13.
- **Exploration, не финальная доставка.** Plotly в `06/08` используется для hover и
  drill-down в отдельные наблюдения. Полированный интерактивный отчет и выбор формата для
  заказчика остаются фазе 17.
- **Спецификация, не еще одна gallery.** Altair в `06/09` нужен для явных типов полей,
  encodings, transforms и linked selections, которые можно инспектировать и тестировать
  как JSON.
- **Дизайн служит чтению данных.** Декоративные 3D-графики, dual axis без строгой
  необходимости, pie chart gallery и dashboard layout не являются целями фазы.

## Роли библиотек

| Инструмент | Задача в фазе | Что сознательно не покрывается |
|---|---|---|
| Matplotlib | Явные `Figure`/`Axes`, композиция, шкалы, annotations, PNG/SVG export | GUI backends, animation, custom backend development |
| Seaborn | Dataset-oriented statistical comparisons, facets, estimator и `errorbar` | Полный обзор функций и experimental objects API |
| Plotly | Hover, точечный drill-down, responsive standalone HTML, JSON figure | Dash и production-приложения |
| Altair | Декларативные encodings, transforms, parameters и linked views | Большие embedded datasets и сложная Vega-разработка |

В корневом locked environment зафиксированы Matplotlib 3.11.0, Seaborn 0.13.2,
Plotly 6.8.0 и Altair 6.2.1. Pre-release версии не используются. `06/01` и `06/02`
опираются на уже зафиксированные NumPy и pandas.

Проверенные официальные контракты:

- [Matplotlib application interfaces](https://matplotlib.org/stable/users/explain/figure/api_interfaces.html)
  — explicit `Figure`/`Axes` interface является базовым уровнем композиции и настройки;
- [Seaborn statistical estimation and error bars](https://seaborn.pydata.org/tutorial/error_bars.html)
  — spread и uncertainty имеют разную семантику и должны задаваться явно;
- [Plotly graph objects](https://plotly.com/python/graph-objects/) и
  [HTML export](https://plotly.com/python/interactive-html-export/) — Plotly Express
  возвращает `Figure`, а результат можно сериализовать и передать как standalone HTML;
- [Altair encodings](https://altair-viz.github.io/user_guide/encodings/index.html) и
  [parameters](https://altair-viz.github.io/user_guide/interactions/parameters.html) —
  тип поля, encoding и interaction являются частью декларативной спецификации;
- [WCAG 2.2: Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)
  — цвет не должен быть единственным способом различать информацию.

## Единый набор данных

Фаза использует синтетическую таблицу `user_journeys` о первых семи днях после регистрации
в подписочном сервисе. Grain — одна строка на пользователя и одно фиксированное окно
наблюдения.

Поля:

| Поле | Смысл |
|---|---|
| `user_id` | уникальный идентификатор пользователя |
| `registered_at` | момент регистрации |
| `cohort_week` | календарная неделя регистрации в бизнес-зоне |
| `platform` | `web`, `ios` или `android` |
| `app_version` | версия приложения; структурно отсутствует для `web` |
| `country` | страна пользователя |
| `acquisition_channel` | канал привлечения |
| `plan` | выбранный тариф |
| `observed_days` | фактически доступная длина окна, от 1 до 7 дней |
| `onboarding_seconds` | длительность первого onboarding flow |
| `sessions_7d` | число сессий в полном семидневном окне |
| `activated_7d` | завершил ли пользователь целевую активацию за семь дней |
| `first_order_amount_rub` | сумма первого заказа; отсутствует без заказа |
| `support_tickets_7d` | число обращений в поддержку за семь дней |

Профили:

- `tiny`: десятки строк в Git для ручных расчетов, тестов и разбора каждого дефекта;
- `sample`: около 20 тысяч детерминированных строк, генерируется локально для
  распределений, overplotting, faceting и bootstrap.

Заложенные свойства и failure modes:

- повторная строка с тем же `user_id`;
- неполные окна у последних cohort weeks;
- структурный пропуск `app_version` для web и случайные пропуски `country`;
- сильная правосторонняя асимметрия `onboarding_seconds` и `first_order_amount_rub`;
- невозможное отрицательное время как дефект и несколько валидных экстремальных значений;
- смена состава acquisition channels, создающая aggregate decline;
- дополнительное ухудшение Android на одной версии, которое не объясняется только
  составом трафика;
- nonlinear relationship между числом сессий и активацией;
- группы разного размера, чтобы error bars без sample size вводили в заблуждение.

Генератор обязан быть детерминированным, сохранять `tiny`, создавать локальный `sample` и
выпускать manifest с количеством строк и SHA-256.

## Интеграционный мини-проект

Рабочий вопрос: «Почему после мартовского релиза снизилась семидневная активация и что
команде продукта проверить следующим?»

`06/11` собирает каталог поставки:

```text
eda-report/
├── question.json
├── audit.json
├── report.md
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

Отчет обязан:

- исключить неполные observation windows до сравнения activation;
- показать общий тренд и стратифицированные сравнения;
- различать composition effect и остаточное сегментное ухудшение без причинного заявления;
- показывать uncertainty, sample size и единицу ресемплирования;
- использовать цвет не как единственный канал смысла;
- связывать каждый вывод с идентификатором вопроса, расчетом и файлом графика;
- фиксировать ограничения и следующий проверяемый шаг.

## Проверяемость

- Числовые summaries, bins и bootstrap воспроизводятся по seed.
- Behavioral tests проверяют данные и семантику объектов графика: labels, scales, traces,
  encodings, intervals и source rows.
- PNG pixel snapshots не являются основным контрактом.
- Plotly и Altair проверяются через сериализованные JSON specifications; браузер и сеть
  не нужны для lesson tests.
- Manifest содержит SHA-256 всех передаваемых файлов и параметры построения.
