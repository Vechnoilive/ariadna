# Библиотека сценариев и игровые формализации Ариадна

Версия программы 0.9.0. Редакция документа от 13.11.2026. Разработчик: Заречкин Артём Алексеевич, группа Б24-507.

## 1 Общая модель

Машинный источник — scenarios/library.json, исполнимый — hackroi/scenarios.py и metacontroller.py. scripts/check_scenarios.py требует точного совпадения деклараций. Сценарий содержит назначение, участников, роли, действия, ограничения, предикаты применимости, завершение, переходы, игровую модель и обработчик.

Для всех классов N — допустимые публичные участники; I — текущее и ранее полученные публичные наблюдения; K — одна команда агенту, резерв, пространство, связь и директивы. Θ — репутация источника, давность, согласованность, уверенность наблюдения и фактическая надёжность исполнения. E — детерминированный выбор положительного допустимого прироста с фильтром безопасности. Это инженерная игровая формализация; доказательство общего равновесия Нэша не заявляется.

Продолжение проверяет тот же предикат, что вход; штатный выход — его отрицание; аварийный выход — features.hard_stop=true. JSON AST интерпретируется ограниченным набором операций без eval.

## 2 Распределённый поиск и покрытие

Идентификатор: coverage_search. Класс игры: potential. Исполнимый обработчик: search.

Роли: scout. Действия A: move, observe, hold; hold означает удержание и отсутствие движения.

Полезность U: 10*new_cell*confidence - distance*0.05 - energy_cost*2. Расстояние и энергия берутся из публичной модели; коэффициенты являются настройками планировщика.

Предикат входа:

```json
{
  "op": "gt",
  "left": {
    "path": "features.searchers"
  },
  "right": {
    "value": 0
  }
}
```

Переходы: priority_service, relay_coalition, safe_degradation, coordination_reconfiguration. Метрики: mission_completion, energy_used, connectivity_score, assignment_utility.

## 3 Выполнение приоритетной задачи

Идентификатор: priority_service. Класс игры: assignment. Исполнимый обработчик: service.

Роли: executor, verifier. Действия A: move, observe, deliver, hold; hold означает удержание и отсутствие движения.

Полезность U: 20*priority*confidence*(0.5+0.5*agent_reliability) - distance*0.05 - energy_cost*2. Расстояние и энергия берутся из публичной модели; коэффициенты являются настройками планировщика.

Предикат входа:

```json
{
  "op": "gt",
  "left": {
    "path": "features.service_pairs"
  },
  "right": {
    "value": 0
  }
}
```

Переходы: coverage_search, relay_coalition, safe_degradation, coordination_reconfiguration. Метрики: mission_completion, energy_used, connectivity_score, assignment_utility.

## 4 Временная коалиция ретрансляции

Идентификатор: relay_coalition. Класс игры: coalition. Исполнимый обработчик: relay.

Роли: relay, beneficiary. Действия A: move, relay, hold; hold означает удержание и отсутствие движения.

Полезность U: 15*newly_connected_members - distance*0.05 - energy_cost*2. Расстояние и энергия берутся из публичной модели; коэффициенты являются настройками планировщика.

Предикат входа:

```json
{
  "op": "and",
  "args": [
    {
      "op": "or",
      "args": [
        {
          "op": "gt",
          "left": {
            "path": "features.disconnected"
          },
          "right": {
            "value": 0
          }
        },
        {
          "op": "gt",
          "left": {
            "path": "features.critical_relays"
          },
          "right": {
            "value": 0
          }
        }
      ]
    },
    {
      "op": "gt",
      "left": {
        "path": "features.relays"
      },
      "right": {
        "value": 0
      }
    }
  ]
}
```

Переходы: coverage_search, priority_service, safe_degradation, coordination_reconfiguration. Метрики: mission_completion, energy_used, connectivity_score, assignment_utility.

## 5 Безопасный режим при деградации

Идентификатор: safe_degradation. Класс игры: constrained. Исполнимый обработчик: recover.

Роли: returning, charging, holding. Действия A: move, charge, hold; hold означает удержание и отсутствие движения.

Полезность U: 30*recoverable_agents - distance*0.05 - energy_cost*2. Расстояние и энергия берутся из публичной модели; коэффициенты являются настройками планировщика.

Предикат входа:

```json
{
  "op": "gt",
  "left": {
    "path": "features.endangered"
  },
  "right": {
    "value": 0
  }
}
```

Переходы: coverage_search, priority_service, relay_coalition, coordination_reconfiguration. Метрики: mission_completion, energy_used, connectivity_score, assignment_utility.

## 6 Реконфигурация координации

Идентификатор: coordination_reconfiguration. Класс игры: leader_election. Исполнимый обработчик: coordinate.

Роли: coordinator, member. Действия A: send_message, hold; hold означает удержание и отсутствие движения.

Полезность U: 10*reliability + 5*energy + degree - reassignment_cost. Расстояние и энергия берутся из публичной модели; коэффициенты являются настройками планировщика.

Предикат входа:

```json
{
  "op": "and",
  "args": [
    {
      "op": "eq",
      "left": {
        "path": "features.leader_change"
      },
      "right": {
        "value": true
      }
    },
    {
      "op": "gt",
      "left": {
        "path": "features.leaders"
      },
      "right": {
        "value": 0
      }
    }
  ]
}
```

Переходы: coverage_search, priority_service, relay_coalition, safe_degradation. Метрики: mission_completion, energy_used, connectivity_score, assignment_utility.

## 7 Композиция синтез и арбитраж

MetaController проверяет применимость всех классов, назначает участников и распределяет команды. Конфликт разрешается в порядке recovery > relay > service > search, после чего выполняется guard. Удержание текущего координатора использует разницу до 3 единиц полезности и минимум 3 такта, пока координатор доступен.

Compose объединяет несколько классов; synthesize строит ограниченный DAG из известных обработчиков с явными nodes/edges и сохраняет его в конфигурации. Это исполнение композиции известных примитивов, не генерация кода. Switch и modify отражают различие смены набора и изменения параметров. События, решение, владельцы команд и исход фиксируются в журнале.

## 8 Прогнозные политики и проверка

Контрфактический штаб рассматривает meta, frontier, nearby, reserve по общей публичной модели на горизонте 6. Они меняют приоритет исполнения и резерва, но не заменяют пять обязательных классов библиотеки. Стрессовый вариант и калибровка ошибки уменьшают зависимость от чрезмерно уверенного прогноза. Обязательная остановка имеет приоритет.

Тесты test_metacontroller, test_forecast, test_portable и check_scenarios.py проверяют применимость, операции, ограниченность графа, арбитраж, воспроизводимость и защиту. Полнота выполнения каждой новой карты и оптимальность назначения не гарантируются. Новые результаты приведены в TEST_PROTOCOL.md.

## Орбитальный мост

Дополнительная миссия использует те же классы coverage_search, priority_service и relay_coalition. После отказа наземных ретрансляторов на t=4 спутник входит в коалицию связи. Его полезность определяется сохранением маршрутов к исполнителям, а не доставкой на поверхность. Ограничения — доступность, покрытие 75 м, наклонная дальность 110 м и энергия. Задержка спутникового звена составляет 2 с. Новая цель на t=9 проверяет продолжение миссии. Парное отключение спутника сохраняет остальные условия и отдельно фиксирует отрицательный результат.
