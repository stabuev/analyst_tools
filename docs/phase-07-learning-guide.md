# Путеводитель по фазе 07: надёжная аналитика

Фаза 07 не является каталогом тестовых библиотек. Она строит одну систему защиты: от
явного бизнес-инварианта до атомарной публикации. Этот путеводитель показывает порядок,
в котором новичку стоит добавлять проверки.

## Сквозная задача

Есть batch заказов. Нужно посчитать paid revenue, не учесть повторную доставку дважды,
отклонить неизвестный статус и опубликовать результат только после всех blocking gates.

Создайте рабочий файл:

```bash
mkdir -p work/phase-07
```

Начните не с Pandera или Hypothesis, а с таблицы рисков:

| Риск | Минимальный контрпример | Ожидаемая реакция |
|---|---|---|
| повтор заказа | две строки с одним `order_id` | blocker или явная дедупликация |
| неизвестный status | `status="complete"` | schema/domain failure |
| пропуск суммы paid | `amount=None` | blocker до агрегации |
| неполный batch | окно не закрыто | не переключать current pointer |

## 1. Инвариант раньше тестового фреймворка

Сформулируйте свойства на естественном языке:

```text
одна логическая версия на order_id
paid revenue равна сумме paid-строк после принятой дедупликации
сумма status counts равна числу заказов
повторный запуск на том же batch не меняет опубликованную версию
```

Затем сделайте проверки обычными функциями, возвращающими stable check ID:

```python
def check_unique_order_id(rows):
    keys = [row["order_id"] for row in rows]
    return {
        "id": "orders.order_id.unique",
        "passed": len(keys) == len(set(keys)),
        "observed": len(keys) - len(set(keys)),
    }
```

Stable ID принадлежит вашему контракту. Текст исключения библиотеки может измениться при
обновлении зависимости и остаётся диагностикой.

## 2. Unit test проверяет поведение на границе

Сначала happy path, затем минимальный дефект:

```python
def test_paid_revenue_ignores_pending():
    rows = [
        {"order_id": "O1", "status": "paid", "amount": 100},
        {"order_id": "O2", "status": "pending", "amount": 900},
    ]
    assert paid_revenue(rows) == 100


def test_duplicate_order_is_rejected():
    rows = [
        {"order_id": "O1", "status": "paid", "amount": 100},
        {"order_id": "O1", "status": "paid", "amount": 100},
    ]
    with pytest.raises(OrderContractError, match="order_id"):
        paid_revenue(rows)
```

Тест публичной функции устойчивее теста внутренних локальных переменных. Он должен падать
при изменении бизнес-поведения и переживать безопасный рефакторинг реализации.

## 3. Defect matrix определяет минимальное покрытие

Не пытайтесь получить абстрактные «100% coverage». Для каждого риска зафиксируйте:

- fixture или mutation;
- ожидаемый check ID;
- severity;
- слой обнаружения;
- может ли pipeline продолжать работу.

Если два теста ловят один дефект одинаковым способом, это дублирование. Если critical
defect не имеет ни одного test case, высокая line coverage ничего не доказывает.

## 4. Property-based test появляется после oracle

Начните с свойства, которое можно выразить независимо от основной реализации:

```python
from hypothesis import given
from hypothesis import strategies as st


@given(st.lists(st.integers(min_value=0, max_value=10_000)))
def test_total_is_invariant_to_order(amounts):
    assert total(amounts) == total(list(reversed(amounts)))
```

Затем ограничьте strategy реальным доменом. Произвольная Unicode-строка для `status`
проверяет parser, а не правила заказов. Когда Hypothesis нашёл минимальный контрпример,
сохраните его как обычный regression test, если defect важен для бизнеса.

## 5. Pandera и Pydantic защищают разные границы

- Pandera проверяет табличную форму, dtype, nullable policy, домены и row-level checks.
- Pydantic проверяет конфигурацию запуска до чтения данных.
- Foreign key, reconciliation и temporal completeness остаются отдельными проверками,
  потому что охватывают несколько таблиц или состояний.

Для Pandera сначала напишите контракт словами, затем schema. Для Pydantic запретите
неизвестные поля, если опечатка параметра опаснее обратной совместимости:

```python
class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_path: Path
    expected_currency: Literal["RUB", "USD", "EUR"]
    fail_on_duplicates: bool = True
```

Проверьте отдельно strict parsing и намеренное coercion. Автоматическое преобразование
`"false"` в truthy string — типичный источник неверного режима запуска.

## 6. SQL checks и golden dataset

SQL-проверки должны возвращать failing records или измеримое observed value, а не только
boolean. Сохраняйте query рядом с check ID и ожидаемым grain.

Golden dataset должен быть маленьким: одна строка для каждого существенного правила и
ожидаемый semantic snapshot. Нормализуйте порядок, timestamps и числовое представление до
сравнения. Обновление golden — review изменения бизнес-семантики, а не команда для
получения зелёного теста.

## 7. Observability не заменяет gate

Run report отвечает как минимум на вопросы:

- какой batch и data window проверены;
- какие checks прошли, предупредили или заблокировали;
- сколько строк попало в quarantine;
- какой manifest описывает outputs;
- изменился ли current pointer.

Dashboard или лог делает состояние видимым. Quality gate принимает решение о публикации.
Не смешивайте эти роли.

## 8. Атомарная публикация

Безопасный порядок:

```text
validate config
-> read immutable inputs
-> calculate into staging
-> run blocking gates
-> write output manifest
-> move staging to immutable version
-> atomically replace current pointer
```

Failed run сохраняет диагностику, но не меняет версию, которую читает потребитель.
Повторный запуск с теми же inputs либо переиспользует тот же version ID, либо выпускает
байтово эквивалентный результат по объявленной policy.

## Финальная самопроверка

Пройдите фазу ещё раз как цепочку решений, а не библиотек:

1. Какой риск существует?
2. Как выглядит минимальный контрпример?
3. Какая проверка обнаруживает его раньше всего?
4. Является результат warning или blocker?
5. Что увидит потребитель после failed run?

Затем запустите:

```bash
uv run --locked python scripts/run_quiz.py --phase 7 --stage post --limit 8
```

Фаза освоена, если вы можете добавить новый defect в matrix, написать behavioral test,
протянуть stable check ID в run report и доказать, что failed gate не изменил опубликованную
версию.
