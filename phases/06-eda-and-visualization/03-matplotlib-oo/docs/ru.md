# Воспроизводимая фигура с Matplotlib

> Поставляйте не картинку из неизвестных строк, а цепочку «проверенные данные →
> контрольная таблица → Figure → файлы и manifest».

**Тип:** Build  
**Треки:** Core  
**Пререквизиты:** 06/02  
**Время:** ~90 минут
**Результат:** строит из audited selection самостоятельный пакет статической фигуры:
контрольную таблицу с числителем и знаменателем, явную Figure/Axes-композицию,
byte-repeatable PNG и SVG и manifest с параметрами вопроса и provenance.

## Цели обучения

- Превращать проверенные строки в маленькую контрольную таблицу до построения графика.
- Различать `Figure`, `Axes`, `Axis`, `Artist`, canvas и backend без изучения внутреннего
  устройства Matplotlib целиком.
- Использовать `plt.subplots()` только для создания объектов, а изменения направлять
  явным `Axes` references.
- Делать дату сравнения, шкалу, layout и экспорт частью проверяемого контракта.
- Различать воспроизводимость расчёта, повторяемость bytes и checksum уже созданного файла.

## Проблема

После data audit коллега получил 22 подходящих пользовательских наблюдения и хочет
показать семидневную активацию вокруг релиза. В ноутбуке легко написать несколько
вызовов `plt.plot()`, увидеть правдоподобную линию и отправить PNG.

Но у получателя остаются вопросы:

- из каких строк получена каждая точка;
- сколько активированных пользователей находится в числителе;
- сколько подходящих пользователей находится в знаменателе;
- какая дата разделяет периоды;
- почему шкала и размер Figure именно такие;
- можно ли повторно получить те же файлы;
- доказывает ли checksum корректность графика или только неизменность bytes.

Один PNG не отвечает ни на один из этих вопросов. Более того, неявный pyplot-state может
направить следующую линию на текущий `Axes`, а SVG способен получить новые внутренние
идентификаторы при каждом сохранении. Визуально результат тот же, но bytes и checksum уже
другие.

## Концепция

### Фигура начинается с контрольной таблицы

`06/01` зафиксировал вопрос и потребовал контрольный расчёт, а `06/02` выпустил
checksum-bound selection plan. Следующая граница выглядит так:

```text
source CSV + audit.json
        │ checksum, readiness, selection plan
        ▼
audited user-level rows
        │ group by cohort_week
        ▼
control table: numerator + denominator + rate
        │ explicit plotting contract
        ▼
Figure → Axes → Artists
        │ Agg renderer + fixed export settings
        ▼
control.csv + PNG + SVG + manifest.json
```

График не является контрольным расчётом. Он является представлением уже проверенной
таблицы. Для доли в ней нужны три поля:

```text
activated_users   — числитель
eligible_users    — знаменатель
activation_rate   — activated_users / eligible_users
```

Если точку нельзя воспроизвести по этим полям, график пока рано поставлять.

### Figure, Axes, Axis и Artist

Имена похожи, но отвечают за разные уровни:

- `Figure` — вся поставляемая композиция: области данных, общий заголовок и layout;
- `Axes` — одна область данных, например линия activation или столбцы знаменателя;
- `Axis` — одна координатная ось внутри `Axes`, её ticks, labels и scale;
- `Artist` — любой рисуемый объект: линия, столбец, текст, сетка или release marker;
- canvas — поверхность, на которой backend рендерит `Figure`;
- backend — реализация отображения или записи формата; для batch-экспорта используется
  неинтерактивный `Agg`.

`Axes` во множественном числе — это не «ось X и ось Y». Один `Axes` обычно содержит два
объекта `Axis`.

### Explicit API не означает запрет pyplot

Код:

```python
figure, axes = plt.subplots(1, 2)
trend_axis, count_axis = axes
trend_axis.plot(weeks, rates)
count_axis.bar(weeks, users)
```

использует pyplot для создания объектов, но строит график через явные references. Каждый
вызов адресован определённому `Axes`.

В неявном варианте:

```python
plt.plot(weeks, rates)
plt.ylabel("Доля")
```

Matplotlib выбирает текущую Figure и текущий Axes. Это удобно для одноразового
исследования, но хрупко в функции, тесте и batch-процессе.

### Что именно означает «воспроизводимый»

Здесь нужны три разных утверждения:

1. **Расчёт воспроизводим:** source связан с audit checksum, а numerator, denominator и
   rate находятся в контрольной таблице.
2. **Экспорт повторяем в locked-окружении:** дата metadata и случайная соль SVG
   зафиксированы, поэтому два независимых запуска дают одинаковые bytes.
3. **Файл не изменился:** checksum совпадает с manifest.

Третье не доказывает первые два. Ошибочный график тоже можно надёжно захешировать.
Byte-identical результат также не обещается между произвольными версиями Python,
Matplotlib, шрифтов и ОС — поэтому версии runtime записываются в manifest, а зависимости
курса фиксируются в `uv.lock`.

### Шкала и знаменатель — часть смысла

Activation rate имеет известный допустимый домен `[0, 1]`. Полная шкала помогает читать
абсолютный размер доли и не преувеличивать небольшие колебания. Это не универсальное
правило «все оси начинаются с нуля»: для другой величины диапазон должен следовать её
смыслу и вопросу.

Вторая панель показывает `eligible_users` для тех же cohort weeks. Она не заменяет
неопределённость оценки — этому посвящён `06/06`, — но не позволяет читать одинаково
надёжными точки с резко разными знаменателями.

## Соберите это

### Шаг 1. Рассчитайте две точки вручную

До pandas и Matplotlib возьмите две когорты:

| cohort_week | activated_users | eligible_users | activation_rate |
|---|---:|---:|---:|
| 2026-02-23 | 3 | 4 | 0.75 |
| 2026-03-02 | 2 | 5 | 0.40 |

Проверьте два инварианта:

```text
0 <= activated_users <= eligible_users
activation_rate = activated_users / eligible_users
```

Студент должен сначала предсказать положение двух точек и относительную высоту двух
столбцов, а уже затем запускать код.

### Шаг 2. Создайте объекты и сохраните references

```python
figure, (trend_axis, count_axis) = plt.subplots(
    1,
    2,
    figsize=(8, 3),
    layout="constrained",
)
```

`layout="constrained"` просит Matplotlib распределить место с учётом labels и titles.
Он не гарантирует хороший дизайн, но предотвращает типичное наложение подписей без
последующей ручной правки координат.

### Шаг 3. Получите и проверьте Artists

```python
trend_line = trend_axis.plot(weeks, rates, marker="o")[0]
count_bars = count_axis.bar(weeks, users)
trend_axis.set(ylabel="Доля activation_7d", ylim=(0, 1))
count_axis.set(ylabel="Подходящие пользователи")
```

Возвращаемые линия и контейнер столбцов нужны не только для настройки. Тест может
проверить число точек и столбцов, не сравнивая хрупкий pixel snapshot.

### Шаг 4. Закройте lifecycle

Если Figure создана через pyplot, после сохранения или проверки её нужно закрыть:

```python
plt.close(figure)
```

Иначе pyplot продолжит хранить Figure в своём registry. В цикле это даёт предупреждения
и рост памяти даже тогда, когда файлы успешно записываются.

Запустите прозрачный пример:

```bash
uv run --locked python code/main.py
```

Он выводит контрольные строки, число `Axes`, количество line points и bars и диапазон
rate-axis. Файлы пока не сохраняются: цель шага — увидеть объекты и инварианты до CLI.

## Используйте это

Сначала получите audit evidence из предыдущего урока:

```bash
uv run --locked python ../02-data-audit/outputs/eda_audit.py \
  --input ../data/tiny/user_journeys.csv \
  --contract ../data/contract.json \
  --analysis activation_7d \
  --output audit.json
```

Затем передайте source, audit report и дату из visual question brief самостоятельной
фабрике:

```bash
uv run --locked python outputs/figure_factory.py \
  --input ../data/tiny/user_journeys.csv \
  --audit audit.json \
  --release-date 2026-03-02 \
  --output-dir figure-output
```

Фабрика не импортирует код `06/02` и не ищет файлы по структуре репозитория. Она сама
читает публичный контракт `selection_plan` из `audit.json`:

1. отклоняет `blocked` readiness;
2. сверяет checksum source;
3. применяет только объявленное решение об exact duplicates;
4. применяет eligibility полного семидневного окна;
5. приводит только перечисленные типы и проверяет user-level grain;
6. строит контрольную таблицу;
7. строит Figure из этой таблицы.

Пакет результата:

```text
figure-output/
├── activation-overview-control.csv
├── activation-overview.png
├── activation-overview.svg
└── manifest.json
```

### Зачем нужны оба формата

- PNG содержит готовый растр для документа или сообщения; его размер в пикселях зависит
  от inches и DPI.
- SVG хранит векторные элементы и лучше подходит для масштабирования и инспекции.

SVG использует внутренние identifiers. При `svg.hashsalt=None` Matplotlib создаёт их с
новой случайной солью. Поэтому фабрика задаёт постоянный `svg.hashsalt` во время
`savefig`, а не только при создании Figure.

### Что находится в manifest

`manifest.json` фиксирует:

- Python, Matplotlib, pandas и backend;
- metric, numerator, denominator, comparison axis и release date;
- границу интерпретации: изменение после даты не доказывает эффект релиза;
- размер, DPI, layout, домен rate и SVG salt;
- source rows, canonical audit checksum, audit status, decision ids и source checksum;
- размер и SHA-256 контрольной таблицы, PNG и SVG.

Checksum позволяет обнаружить замену поставленного файла. Корректность чисел доказывают
reconciliation контрольной таблицы и behavioral tests, а не сам хеш.

## Сломайте это

1. **Измените один byte source после аудита.** Старый selection plan должен быть
   отклонён до чтения графика.
2. **Поставьте readiness `blocked`.** Фабрика не должна выпускать даже пустую Figure.
3. **Подмените exact duplicate конфликтующей строкой.** Решение `drop exact duplicate`
   не разрешает выбирать одну из разных версий пользователя.
4. **Сделайте eligibility пустой.** Пустая картинка не является ответом и должна
   приводить к ошибке.
5. **Подставьте rate `1.1`.** Figure contract должен остановиться до рендера.
6. **Уберите `svg.hashsalt` только во время `savefig`.** Два запуска дадут визуально
   одинаковые SVG с разными bytes.
7. **Захардкодьте release date и не запишите её в manifest.** Получатель не сможет
   восстановить точку сравнения из пакета.
8. **Замените наблюдение причинным утверждением.** Линия после даты показывает
   сопутствующее изменение, но не идентифицирует эффект релиза.

## Проверьте это

Behavioral tests проверяют не конкретные пиксели, а наблюдаемый контракт:

- audited selection содержит 22 уникальных пользователя полного окна;
- изменённый source, рассогласованный audit report и blocked readiness отклоняются;
- conflicting duplicate не скрывается selection plan;
- пустая выборка и недопустимый rate блокируют экспорт;
- control table содержит numerator, denominator и согласованный rate;
- Figure содержит два явных `Axes`, release marker и полный rate domain;
- пакет содержит CSV, PNG, SVG и manifest с совпадающими checksums;
- два независимых CLI-процесса создают byte-identical пакет;
- скопированный `figure_factory.py` работает без структуры курса;
- после batch-экспорта Figure удалена из pyplot registry.

```bash
uv run --locked python -m unittest discover -s tests
```

Pixel snapshot сознательно не используется: малозначимое изменение renderer или шрифта
делает такой тест красным, не объясняя, нарушен ли аналитический смысл. Для этого урока
важнее данные Artists, шкалы, контрольная таблица и повторяемость поставляемых bytes в
locked-окружении.

## Поставьте результат

`outputs/figure_factory.py` — самостоятельная CLI-фабрика пакета статической фигуры.
Ей нужны только явно переданные CSV, `audit.json`, release date и output directory; путь
к предыдущему уроку не является скрытой runtime-зависимостью.

Артефакт пригоден:

- для регулярного обновления одного и того же графика после нового аудита;
- как статическая часть EDA-report `06/11`;
- для ревью, где коллега сначала открывает control CSV и manifest, а затем изображение;
- как основа следующих уроков, которые меняют статистическое представление, но сохраняют
  явные `Figure`/`Axes` и проверяемый экспорт.

## Упражнения

1. **Закрепление.** Добавьте в control CSV столбец `inactive_users` и behavioral test
   равенства `activated + inactive = eligible`; график при этом не меняйте.
2. **Перенос.** Постройте тем же lifecycle долю обращений в поддержку по cohort week:
   сначала назовите numerator и denominator, затем измените labels и manifest.
3. **Новая поломка.** Добавьте режим focused y-domain. Требуйте явного параметра,
   записывайте границы в manifest и визуально обозначайте, что шкала не показывает весь
   допустимый домен доли.

## Ключевые термины

| Термин | Распространённое заблуждение | Точное значение |
|---|---|---|
| Control table | Данные для подписи графика | Маленькая таблица, из которой независимо воспроизводятся plotted values |
| Figure | Одна линия | Контейнер всей поставляемой композиции |
| Axes | Ось X или Y | Область данных со своими шкалами, labels и Artists |
| Axis | Вся область графика | Координатная ось, ticks и labels внутри Axes |
| Artist | Только декоративный объект | Любой объект, который renderer рисует на Figure |
| Backend | Тема оформления | Механизм показа или записи Figure в конкретный формат |
| DPI | Качество анализа | Число raster dots на inch при экспорте |
| Byte-identical | Визуально похоже | Файлы имеют ровно одинаковые bytes и checksum |
| Checksum | Доказательство корректности | Идентификатор bytes, обнаруживающий их изменение |
| Manifest | Подпись картинки | Машиночитаемый контракт вопроса, runtime, данных и поставленных файлов |

## Дополнительное чтение

- [Яндекс Хендбук: модуль pandas](https://education.yandex.ru/handbook/python/article/modul-pandas) — откройте финальный пример визуализации и перепишите его неявные `plt.hist` / `plt.xlabel` через `figure, axis = plt.subplots()` и методы `axis`; это короткий русскоязычный мост к explicit API.
- [Microsoft Learn: визуализация данных с помощью Matplotlib](https://learn.microsoft.com/ru-ru/shows/even-more-python-for-beginners-data-tools/visualizing-data-with-matplotlib--even-more-python-for-beginners-data-tools-29-of-31) — просмотрите базовый video walkthrough, если до урока вы ещё не создавали Figure; используйте его для знакомства, а контракт экспорта берите из этого урока.
- [Яндекс Образование: как сделать числа и отчёты понятными](https://education.yandex.ru/journal/vizualizaciya) — прочитайте этапы от задачи до полировки и список типичных ошибок; материал помогает не спутать технически воспроизводимую Figure с содержательно полезным сообщением.
- [Matplotlib: Quick start guide](https://matplotlib.org/stable/users/explain/quick_start.html) — изучите разделы `Parts of a Figure` и `Working with multiple Figures and Axes`, чтобы закрепить различия Figure, Axes, Axis и Artist на официальной схеме.
- [Matplotlib: Application interfaces](https://matplotlib.org/stable/users/explain/figure/api_interfaces.html) — сравните explicit Axes interface с implicit pyplot interface; обратите внимание, что `plt.subplots()` допустим и в explicit-стиле.
- [Matplotlib: Axes and subplots](https://matplotlib.org/stable/users/explain/axes/index.html) — используйте карту разделов про plotting methods, labels, limits и multiple Axes как справочник после освоения минимального API урока.
- [Matplotlib: Constrained layout guide](https://matplotlib.org/stable/users/explain/axes/constrainedlayout_guide.html) — разберите, какие decorations учитывает layout engine и почему его нужно включать при создании Figure, а не пытаться чинить экспорт постфактум.
- [Matplotlib: Figure.savefig](https://matplotlib.org/stable/api/_as_gen/matplotlib.figure.Figure.savefig.html) — прочитайте точный контракт `dpi`, `format`, `metadata`, `facecolor` и backend-dependent параметров перед расширением фабрики новыми форматами.
- [Matplotlib: Output backends](https://matplotlib.org/stable/users/explain/figure/backends.html) — сопоставьте interactive и non-interactive backends и таблицу поддерживаемых форматов; это объясняет выбор `Agg` для batch CLI.
- [Matplotlib: Customizing with rcParams](https://matplotlib.org/stable/users/explain/customizing.html) — найдите `svg.hashsalt`, `figure.figsize`, `figure.dpi` и savefig-настройки; материал показывает, какие скрытые defaults нужно либо фиксировать, либо записывать в provenance.
