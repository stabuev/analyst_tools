# Тесты на границах преобразований

> Хороший тест аналитического pipeline фиксирует наблюдаемый контракт стадии, а не строки ее реализации.

**Тип:** Build  
**Треки:** core  
**Пререквизиты:** 07/01  
**Время:** ~75 минут

## Цели обучения

- разделить pipeline на стадии с явными входами и выходами;
- проверять grain, домен и reconciliation на правильной границе;
- отличать behavioral test от теста внутренней реализации.

## Проблема

Один большой тест «CSV вошел, отчет вышел» плохо локализует сбой. Десятки тестов
приватных функций ломаются при безопасном рефакторинге. Нужен средний масштаб:
контракты нормализации, сборки витрины и агрегации.

## Концепция

Граница стадии описывается допустимым входом, гарантированным выходом и стабильным
идентификатором ошибки. Тест проверяет эти наблюдаемые свойства. Например,
`build_order_mart` обязан сохранить grain заказа и согласовать сумму заказа со строками,
но тесту не важно, сделан расчет через `merge` или SQL.

## Соберите это

Откройте `outputs/order_stage_contracts.py`. Артефакт содержит три стадии:
`normalize_orders`, `build_order_mart`, `build_daily_metrics`. Ошибки представлены
`StageContractError` с `check_id`, поэтому вызывающий код не разбирает текст исключения.

Запустите:

```bash
uv run --locked python phases/07-reliable-analytics/02-unit-tests/code/main.py
uv run --locked python phases/07-reliable-analytics/02-unit-tests/outputs/order_stage_contracts.py \
  --data-dir phases/07-reliable-analytics/data/tiny
```

## Используйте это

Читайте отчет сверху вниз. `mart.grain` подтверждает одну строку на заказ,
`mart.reconciliation` сравнивает две денежные ветки, а `metrics.partition` доказывает,
что дневная группировка не потеряла заказы.

## Сломайте это

Замените один `user_id` на `U999`, повторите `order_id` или увеличьте цену строки на
одну копейку. Каждый дефект должен падать на своей границе и возвращать конкретный
`check_id`, а не неопределенное «pipeline failed».

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/07-reliable-analytics/02-unit-tests/tests
```

Тесты покрывают валидный baseline, duplicate grain, domain status, orphan FK,
reconciliation, сохранение partition и CLI failure report.

## Поставьте результат

Именованный результат урока: `outputs/order_stage_contracts.py`. Его можно подключить к
локальному запуску или CI как самостоятельный contract suite.

## Упражнения

1. Добавьте контракт, что `paid_order_count <= order_count` для каждого дня.
2. Проверьте поведение при заказе без строк и явно выберите политику.
3. Замените реализацию агрегации, не меняя behavioral tests.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Behavioral test | Проверяет конкретный вызов `merge` | Проверяет наблюдаемый контракт результата |
| Boundary | Только внешний API | Любая устойчивая граница между стадиями |
| Oracle | Ожидаемое число, записанное вручную | Независимый способ определить правильный результат |

## Дополнительное чтение

- [pytest: good integration practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) — как размещать тесты и избегать хрупких импортов.
- [pandas testing](https://pandas.pydata.org/docs/reference/testing.html) — точные assertions для Series, DataFrame и ExtensionArray.
- [Python unittest](https://docs.python.org/3/library/unittest.html) — стандартный контракт test case и запуск discovery.
