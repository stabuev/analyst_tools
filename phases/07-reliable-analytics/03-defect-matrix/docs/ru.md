# Минимальные контрпримеры и матрица дефектов

> Один fixture должен доказывать один класс дефекта минимальным изменением валидного baseline.

**Тип:** Learn  
**Треки:** core  
**Пререквизиты:** 07/02  
**Время:** ~75 минут

## Цели обучения

- сводить производственный сбой к минимальному контрпримеру;
- связывать класс дефекта с ожидаемым quality gate;
- строить fixtures как детерминированные мутации baseline.

## Проблема

Полная копия «плохой» выгрузки быстро устаревает и часто содержит сразу несколько
дефектов. Когда тест падает, непонятно, какой именно дефект он доказал.

## Концепция

Начните с маленького валидного набора и внесите одну мутацию: повторите строку, очистите
ключ или измените одну сумму. Матрица дефектов хранит стабильный ID, класс, изменяемый
файл и gates, которые обязаны сработать.

## Соберите это

`outputs/defect_factory.py` описывает 12 failure classes. Восемь сценариев можно
материализовать в CSV; конфигурационная, regression, volume и publication ошибки
остаются сценариями для профильных уроков.

```bash
uv run --locked python phases/07-reliable-analytics/03-defect-matrix/outputs/defect_factory.py \
  --matrix
uv run --locked python phases/07-reliable-analytics/03-defect-matrix/outputs/defect_factory.py \
  --baseline-dir phases/07-reliable-analytics/data/tiny \
  --scenario item_total_mismatch --output-dir /tmp/item-total-defect
```

## Используйте это

Читайте `defect.json`: он фиксирует mutation, affected file, row delta, ожидаемые gates
и checksums всего набора. Неизмененные файлы остаются byte-identical baseline.

## Сломайте это

Попробуйте создать fixture, который одновременно меняет status и amount. Такой fixture
не локализует причину. Разделите его на два сценария и назначьте каждому ожидаемый gate.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/07-reliable-analytics/03-defect-matrix/tests
```

Проверяется полнота классов, минимальность row delta, drift столбца, неизменность соседних
файлов и отказ материализовать концептуальный сценарий.

## Поставьте результат

Результат: `outputs/defect_factory.py` и machine-readable `DEFECT_MATRIX`, пригодные для
contract, SQL, monitoring и integration tests следующих уроков.

## Упражнения

1. Добавьте сценарий неизвестной валюты с одним измененным значением.
2. Опишите минимальный fixture для timezone drift.
3. Решите, какой gate должен первым ловить duplicate item key.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Контрпример | Большая реальная выгрузка | Минимальный вход, нарушающий сформулированное свойство |
| Fixture builder | Копия CSV | Детерминированная функция построения тестового состояния |
| Failure class | Текст исключения | Устойчивая категория дефекта для маршрутизации и анализа |

## Дополнительное чтение

- [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html) — композиция повторно используемых тестовых состояний.
- [pytest parametrization](https://docs.pytest.org/en/stable/how-to/parametrize.html) — запуск одного контракта на матрице сценариев.
- [Hypothesis examples](https://hypothesis.readthedocs.io/en/latest/examples.html) — переход от найденного контрпримера к воспроизводимому тесту.
