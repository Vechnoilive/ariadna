"""Own-world branching harness. Never imported by a tournament controller.

The private simulator exists only here: proposals were already made from public
observations, before this harness reconstructs and measures alternate futures.
"""
import copy
import hashlib
import json
from pathlib import Path

from .audit import audit, read_records
from .contracts import canonical, validate
from .counterfactual import CounterfactualController
from .environment import Environment
from .forecast import HORIZON, intent_commands
from .journal import Journal


def digest(value):
    def normalize(item):
        if isinstance(item, dict):
            return {k: normalize(v) for k,v in item.items()}
        if isinstance(item, set):
            return sorted((normalize(v) for v in item), key=canonical)
        if isinstance(item, list):
            return [normalize(v) for v in item]
        return item
    return hashlib.sha256(canonical(normalize(value)).encode()).hexdigest()


def replay_prefix(records, decision_id, log_path=None, map_definition=None):
    environment = Environment(log_path,map_definition)
    for record in records:
        if record['kind'] == 'step' and record['decision_id'] == decision_id:
            return environment
        if record['kind'] not in ('reset', 'step'):
            continue
        response = environment.mutate(record['kind'], record['input'])
        if response != record['output']:
            raise ValueError('Own-world reconstruction differs from recorded physics')
    raise ValueError('Fork decision is not present in the environment log')


def reconstruct_public_controller(records, decision_id):
    reset = next(r for r in records if r["kind"] == "reset")
    if reset.get("audit_profile") == "ariadna.portable.v5":
        from .portable import PortableController
        controller = PortableController()
        controller.configure_capabilities(reset["capabilities"])
    else:
        controller = CounterfactualController()
    previous, parameters = None, None
    results = {r['decision_id']: r['output'] for r in records if r['kind'] == 'result'}
    for record in records:
        if record['kind'] != 'decision':
            continue
        decision = controller.decide(record['observation'], previous, parameters)
        if decision != record['decision']:
            raise ValueError('Public controller reconstruction differs from its evidence')
        if decision['decision_id'] == decision_id:
            return controller, record['observation'], previous, parameters
        controller.observe_result(results[decision['decision_id']])
        previous = {'scenario_ids': decision['selected_configuration']['scenario_ids'], 'role_assignments': decision['role_assignments']}
        parameters = decision['selected_configuration']['parameters']
    raise ValueError('Fork decision is not present in the controller log')


def intervention(entry, previous, parameters, candidate):
    decision = copy.deepcopy(entry['decision'])
    if decision['operation'] != 'safe_stop':
        decision['selected_configuration']['parameters']['ariadna_counterfactual'] = {
            'policy': candidate, 'model': 'ariadna.public_forecast.v1', 'horizon': HORIZON}
        if decision['selected_configuration']['scenario_ids'] == previous['scenario_ids']:
            decision['operation'] = 'keep' if decision['selected_configuration']['parameters'] == parameters and decision['role_assignments'] == previous['role_assignments'] else 'modify'
    else:
        decision['selected_configuration']['parameters'] = copy.deepcopy(parameters)
    decision['explanation']['reason_codes'].append('own_world_research_intervention')
    return decision


def branch(environment_log, controller_log, output, decision_id=None, horizon=HORIZON, map_definition=None):
    if not 1 <= horizon <= 12:
        raise ValueError('Branch horizon must be in [1,12]')
    environment_records, controller_records = read_records(environment_log), read_records(controller_log)
    audit(environment_records, controller_records)
    resets = [r for r in environment_records if r['kind'] == 'reset']
    if len(resets) != 1 or resets[0]['input']['mission']['parameters'].get('profile') != 'rescue_v2':
        raise ValueError('Research branching requires one own-world rescue_v2 episode')
    candidates = [r for r in controller_records if r['kind'] == 'decision' and 'ariadna_counterfactual' in r['decision']]
    if decision_id is None:
        decision_id = next((r['decision_id'] for r in candidates if len({
            c.get('commands_sha256') or digest(c['commands'])
            for c in r['decision']['ariadna_counterfactual']['candidates']
        }) > 1), None)
    if decision_id is None:
        raise ValueError('No distinct alternatives in this episode')
    # Freeze proposals before allocating any reconstructed private environment.
    controller, observation, previous, parameters = reconstruct_public_controller(controller_records, decision_id)
    previous = previous or {'scenario_ids': [], 'role_assignments': {}}
    parameters = parameters or {}
    proposals = controller.last_candidates
    source_decision = next(r['decision'] for r in candidates if r['decision_id'] == decision_id)
    output = Path(output).resolve(); output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Нужен пустой каталог результатов')
    reports, checkpoints = [], set()
    for candidate, entry in proposals.items():
        directory = output/candidate; directory.mkdir()
        environment = replay_prefix(environment_records, decision_id, directory/'environment.jsonl', map_definition)
        checkpoint = digest(environment.state)
        checkpoints.add(checkpoint)
        if environment.observation() != observation:
            raise ValueError('Fork public observations are not identical')
        initial = environment.observation()
        observations, interventions, actual_curve = [initial], [], []
        decision = intervention(entry, previous, parameters, candidate)
        journal = Journal(directory/'interventions.jsonl')
        for step in range(horizon):
            if step:
                current = environment.observation()
                decision = copy.deepcopy(decision)
                decision.update(time=current['time'], previous_configuration={
                    'scenario_ids': decision['selected_configuration']['scenario_ids'], 'role_assignments': decision['role_assignments']})
                identifier = digest([candidate, current])[:24]
                decision.update(request_id='research_step_'+identifier, decision_id='research_decision_'+identifier,
                                operation='keep', commands=intent_commands(current, entry['intents'],
                                    decision['selected_configuration']['parameters'].get('step_scale', 1.), routed=hasattr(controller,'adapter')))
                # A new directive invalidates a frozen experiment instead of being ignored.
                if current['mission']['directives'] != initial['mission']['directives']:
                    decision.update(operation='safe_stop', commands=[])
            validate('decision', decision)
            response = environment.mutate('step', decision)
            journal.append({'kind': 'research_intervention', 'candidate_id': candidate, 'step': step+1,
                            'input': decision, 'output': response,
                            'scope': 'frozen_intent_experiment_not_tournament_controller_log'})
            interventions.append(decision)
            observations.append(response['observation'])
            actual_curve.append({'step': step+1, 'completion': response['metrics']['mission_completion'],
                                 'energy': round(response['metrics']['energy_used']-initial['metrics']['energy_used'], 12),
                                 'connectivity': response['observation']['network']['connectivity_score']})
            if response['status'] != 'running':
                break
        (directory/'replay.json').write_text(json.dumps(observations, ensure_ascii=False), encoding='utf-8')
        reports.append({'candidate_id': candidate, 'selected_in_real_episode': source_decision['ariadna_counterfactual']['selected_candidate'] == candidate,
                        'fork_checkpoint_sha256': checkpoint, 'public_observation_sha256': digest(initial),
                        'steps_observed': len(actual_curve), 'status': response['status'],
                        'actual_curve': actual_curve, 'nominal_forecast': entry['nominal']['curve'][:horizon],
                        'actual_completion_gain': round(response['metrics']['mission_completion']-initial['metrics']['mission_completion'], 9),
                        'actual_energy': actual_curve[-1]['energy'], 'final_metrics': response['metrics']})
    if len(checkpoints) != 1:
        raise AssertionError('Alternative branches did not start at the same private checkpoint')
    report = {'format': 'ariadna.research_branches.v1', 'decision_id': decision_id, 'horizon': horizon,
              'continuation': 'frozen public intents with safety checks; no further headquarters selection',
              'source_environment_sha256': hashlib.sha256(Path(environment_log).read_bytes()).hexdigest(),
              'source_controller_sha256': hashlib.sha256(Path(controller_log).read_bytes()).hexdigest(),
              'private_access_scope': 'offline own-world research harness only', 'branches': reports}
    (output/'branches.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# Переигрывание альтернатив из одной точки эпизода', '', 'Версия 0.4.0.', '',
             '## 1 Методика', '',
             'Предложения восстановлены только из публичных наблюдений до выделения приватной среды. Начальные полные состояния всех ветвей имеют одинаковый SHA-256. После первого решения продолжаются зафиксированные намерения с проверками безопасности. Это ограниченный эксперимент, не результат полной миссии и не журнал турнирного контроллера.', '',
             '## 2 Результат', '',
             '| Вариант | Выбран в исходном эпизоде | Прирост выполнения за горизонт | Энергия за горизонт | Наблюдено шагов | Состояние |',
             '|---|---|---|---|---|---|']
    for row in reports:
        lines.append(f"| {row['candidate_id']} | {'Да' if row['selected_in_real_episode'] else 'Нет'} | {row['actual_completion_gain']:.6f} | {row['actual_energy']:.6f} | {row['steps_observed']} | {row['status']} |")
    lines.extend(['', '## 3 Границы вывода', '', 'Ветви используют одну исходную среду и одно расписание событий. Они раскрывают фактические последствия отклонённых вариантов только в исследовательском контуре. Данные ветвей не поступают в рабочий контроллер и не обучают его задним числом.', ''])
    (output/'branches.md').write_text('\n'.join(lines), encoding='utf-8')
    return report
