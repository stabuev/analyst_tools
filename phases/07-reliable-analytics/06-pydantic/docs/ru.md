# Валидация конфигурации с Pydantic

> Конфигурационная ошибка должна остановить запуск до первого чтения данных.

**Тип:** Build  
**Треки:** core  
**Пререквизиты:** 07/05  
**Время:** ~75 минут

## Цели обучения

- моделировать вложенную конфигурацию pipeline;
- запрещать неизвестные поля и неявное числовое coercion;
- возвращать структурированные validation errors.

## Проблема

Словарь конфигурации принимает опечатку `max_order`, строку `"100"` вместо числа и
несуществующую timezone. Ошибка проявляется далеко от источника и может выглядеть как
дефект данных.

## Концепция

Pydantic-модель задает поля, типы, ограничения и cross-field rules. В этом уроке
`extra="forbid"` ловит опечатки, strict mode запрещает числовые строки, validators
проверяют IANA timezone и порядок volume bounds. Validation error сериализуется в
стабильные location/type/message.

## Соберите это

Изучите `PipelineConfig` и `QualityThresholds` в `outputs/pipeline_config.py`.

```bash
uv run --locked python phases/07-reliable-analytics/06-pydantic/outputs/pipeline_config.py \
  --config phases/07-reliable-analytics/06-pydantic/outputs/example_config.json
```

JSON mode осознанно принимает стандартное строковое представление `date` и `Path`, но
числовые thresholds остаются strict.

## Используйте это

После успешной валидации работайте только с нормализованным `model_dump(mode="json")`.
Не передавайте дальше исходный словарь: иначе поздние стадии снова увидят
непроверенные значения.

## Сломайте это

Добавьте неизвестное поле, замените `min_orders` на строку, укажите
`Mars/Olympus` или сделайте `min_orders > max_orders`. Сравните locations ошибок.

## Проверьте это

```bash
uv run --locked python -m unittest discover \
  -s phases/07-reliable-analytics/06-pydantic/tests
```

## Поставьте результат

Результат: `outputs/pipeline_config.py` и `outputs/example_config.json`. CLI пригоден как
нулевой gate локального и автоматического запуска.

## Упражнения

1. Добавьте optional golden path и проверьте его расширение.
2. Решите, какие поля допускают coercion, и задокументируйте причины.
3. Добавьте schema migration с версии `1.0.0` на `1.1.0`.

## Ключевые термины

| Термин | Распространенное заблуждение | Точное значение |
|---|---|---|
| Strict validation | Запрещает JSON-строки вообще | Запрещает нежелательное преобразование совместимых значений |
| Extra forbid | Игнорирует неизвестные поля | Превращает неизвестное поле в validation error |
| Cross-field rule | Check одного Field | Ограничение на согласованность нескольких полей модели |

## Дополнительное чтение

- [Pydantic models](https://docs.pydantic.dev/latest/concepts/models/) — объявление и сериализация моделей.
- [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/) — различия strict и lax validation.
- [Pydantic validators](https://docs.pydantic.dev/latest/concepts/validators/) — field и model validators для доменных правил.
