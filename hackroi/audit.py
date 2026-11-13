"""Проверка связности журналов среды и контроллера."""

import hashlib
import json
from pathlib import Path

from .contracts import canonical, validate


def read_records(path):
    records = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Пустая строка журнала {path}:{number}")
        records.append(json.loads(line))
    return records


def audit(environment_records, controller_records):
    decisions, results, environment_steps = {}, {}, {}
    observations, prior_observations = {}, {}
    def add_unique(mapping, record):
        key = (record["episode_id"], record["decision_id"])
        if key in mapping:
            raise ValueError("Повторяющийся идентификатор решения: " + str(key))
        mapping[key] = record
    for record in environment_records:
        if record["kind"] == "step":
            add_unique(environment_steps, record)
            key = (record["episode_id"], record["decision_id"])
            if record["episode_id"] not in observations:
                raise ValueError("Шаг без предшествующего reset")
            prior_observations[key] = observations[record["episode_id"]]
        if record["kind"] in ("reset", "step", "close"):
            observations[record["episode_id"]] = record["output"]["observation"]
    for record in controller_records:
        if record["kind"] == "decision":
            add_unique(decisions, record)
        elif record["kind"] == "result":
            add_unique(results, record)
    if not decisions:
        raise ValueError("В журнале нет решений")
    if decisions.keys() != results.keys() or decisions.keys() != environment_steps.keys():
        raise ValueError("Неполная цепочка решение — среда — фактический результат")
    meta_episodes = {r["episode_id"] for r in controller_records if r["kind"] == "reset" and r.get("audit_profile") == "ariadna.meta.v3"}
    forecast_episodes = {r["episode_id"] for r in controller_records if r["kind"] == "reset" and r.get("audit_profile") == "ariadna.counterfactual.v4"}
    portable_resets = {r["episode_id"]: r for r in controller_records if r["kind"] == "reset" and r.get("audit_profile") == "ariadna.portable.v5"}
    meta_replayers = {}
    meta_checked = 0
    forecast_checked = 0
    for key, record in decisions.items():
        decision, observation = record["decision"], record["observation"]
        validate("decision", decision)
        validate("observation", observation)
        if observation != prior_observations[key]:
            raise ValueError("Контроллер использовал другое наблюдение: " + str(key))
        environment = environment_steps[key]
        result = results[key]["output"]
        validate("response", result)
        if decision != environment["input"] or result != environment["output"]:
            raise ValueError("Команда или результат расходятся между журналами: " + str(key))
        digest = "sha256:" + hashlib.sha256(canonical(observation).encode()).hexdigest()
        if digest not in decision["explanation"]["observation_refs"]:
            raise ValueError("Объяснение не связано с входным наблюдением: " + str(key))
        if decision["time"] != observation["time"] or result["time"] <= decision["time"]:
            raise ValueError("Некорректное модельное время: " + str(key))
        if len(decision["commands"]) != len(result["command_results"]):
            raise ValueError("Нет результатов всех команд: " + str(key))
        semantics = portable_resets.get(record["episode_id"], {}).get("capabilities", {}).get("execution_semantics", {})
        partial = semantics.get("batch") == "partial" and semantics.get("configuration") == "atomic"
        for command, outcome in zip(decision["commands"], result["command_results"]):
            if (command["agent_id"], command["action"]) != (outcome.get("agent_id"), outcome.get("action")) or outcome.get("status") not in ({"applied", "rejected"} if partial else {"applied"}):
                raise ValueError("Результат относится к другой команде: " + str(key))
        if record["episode_id"] in portable_resets and (decision.get("ariadna_portable", {}).get("version") != "0.5" or decision.get("ariadna_meta", {}).get("version") != "0.3"):
            raise ValueError("Отсутствует обязательное обоснование адаптера")
        if record["episode_id"] in meta_episodes and decision.get("ariadna_meta", {}).get("version") != "0.3":
            raise ValueError("Отсутствует обязательное метаобоснование")
        if record["episode_id"] in forecast_episodes and decision.get("ariadna_counterfactual", {}).get("version") != "0.4":
            raise ValueError("Отсутствует обязательное контрфактическое обоснование")
        if (record["episode_id"] in forecast_episodes or decision.get("ariadna_counterfactual", {}).get("version") == "0.4") and decision.get("ariadna_meta", {}).get("version") != "0.3":
            raise ValueError("Отсутствует обязательное метаобоснование контрфактического решения")
        if decision.get("ariadna_meta", {}).get("version") == "0.3":
            from .metacontroller import MetaController
            from .counterfactual import CounterfactualController
            is_forecast = decision.get("ariadna_counterfactual", {}).get("version") == "0.4"
            episode = record["episode_id"]
            if episode not in meta_replayers:
                if episode in portable_resets:
                    from .portable import PortableController
                    instance=PortableController()
                    instance.configure_capabilities(portable_resets[episode]['capabilities'])
                else:
                    instance=CounterfactualController() if is_forecast else MetaController()
                meta_replayers[episode] = (instance, None, None)
            replayer, prior, parameters = meta_replayers[episode]
            expected = replayer.decide(observation, prior, parameters)
            if decision != expected:
                raise ValueError("Метаобоснование не воспроизводится из публичных наблюдений: " + str(key))
            meta_replayers[episode] = (replayer,
                {"scenario_ids": expected["selected_configuration"]["scenario_ids"],
                 "role_assignments": expected["role_assignments"]},
                expected["selected_configuration"]["parameters"])
            meta_checked += 1
            if is_forecast or episode in portable_resets:
                feedback = replayer.observe_result(result)
                if results[key].get("forecast_feedback") != feedback:
                    raise ValueError("Ошибка прогноза не согласована с фактическим результатом: " + str(key))
                forecast_checked += 1
    result = {"status": "passed", "decisions_checked": len(decisions),
            "environment_steps_checked": len(environment_steps)}
    if meta_checked:
        result["meta_decisions_reproduced"] = meta_checked
    if forecast_checked:
        result["forecast_updates_checked"] = forecast_checked
    if portable_resets:
        result["portable_decisions_reproduced"] = sum(r["episode_id"] in portable_resets for r in decisions.values())
    return result
