"""Paired comparison of four controls, public forecasts and verified actual outcomes."""
import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hackroi.audit import audit, read_records
from hackroi.baselines import FixedController, ReactiveController
from hackroi.contracts import ProtocolError, canonical
from hackroi.counterfactual import CounterfactualController
from hackroi.dossier import save_headquarters
from hackroi.metacontroller import MetaController
from scripts.run_demo import Process
from scripts.run_stage3 import cases as stage3_cases

CONTROLLERS = {'fixed': FixedController, 'reactive': ReactiveController, 'meta': MetaController,
               'counterfactual': CounterfactualController}


def case_parameters(name):
    if name == 'priority_pressure':
        return {'events': [
            {'time': 0., 'type': 'target_detected', 'targets': [], 'parameters': {'position': [12., 8., 0.], 'priority': 1.}},
            {'time': 0., 'type': 'target_detected', 'targets': [], 'parameters': {'position': [45., 8., 0.], 'priority': 4.}}]}
    return stage3_cases()[name]


def aggregate(results):
    groups = []
    for split in sorted({r['split'] for r in results}):
        for name in CONTROLLERS:
            rows = [r for r in results if r['split'] == split and r['controller'] == name]
            if not rows:
                continue
            groups.append({'split': split, 'controller': name, 'episodes': len(rows),
                'successes': sum(r['status'] == 'success' for r in rows),
                'mean_completion': round(sum(r['metrics'].get('mission_completion', 0.) for r in rows)/len(rows), 9),
                'mean_penalized_steps': round(sum(r['time'] if r['status'] == 'success' else r['max_steps'] for r in rows)/len(rows), 9),
                'protocol_errors': sum(r['error'] is not None for r in rows)})
    pairs = []
    for candidate in [r for r in results if r['controller'] == 'counterfactual']:
        baseline = next((r for r in results if (r['split'],r['case'],r['seed'],r['controller']) ==
                         (candidate['split'],candidate['case'],candidate['seed'],'meta')), None)
        if baseline and candidate['status'] == baseline['status'] == 'success':
            pairs.append({'split': candidate['split'], 'case': candidate['case'], 'seed': candidate['seed'],
                          'steps_delta_cf_minus_meta': candidate['time']-baseline['time'],
                          'energy_delta_cf_minus_meta': round(candidate['metrics']['energy_used']-baseline['metrics']['energy_used'], 12)})
    return {'groups': groups, 'paired_success_deltas_vs_meta': pairs}


def write_report(result, output):
    lines = ['# Сравнительные испытания четвёртого этапа', '', 'Версия 0.4.0.', '',
             '## 1 Методика', '',
             'Одинаковые seed, события, ресурсы, предел шагов и начальный публичный снимок для четырёх контроллеров. Ошибка команды сохраняется как ошибка. Неуспех получает полный лимит в показателе penalized_steps. Это внутренние показатели, не официальный балл жюри.', '',
             '## 2 Сводка', '',
             '| Набор | Контроллер | Успехов / эпизодов | Среднее выполнение | Шаги с штрафом за неуспех | Ошибки протокола |',
             '|---|---|---|---|---|---|']
    for row in result['aggregate']['groups']:
        lines.append(f"| {row['split']} | {row['controller']} | {row['successes']} / {row['episodes']} | {row['mean_completion']:.6f} | {row['mean_penalized_steps']:.3f} | {row['protocol_errors']} |")
    lines.extend(['', '## 3 Парные различия с метаконтроллером', '',
                  'Только пары с успешным завершением обоими алгоритмами. Отрицательное различие означает меньшие затраты контрфактического варианта.', '',
                  '| Набор | Случай | Seed | Различие шагов | Различие энергии |', '|---|---|---|---|---|'])
    for row in result['aggregate']['paired_success_deltas_vs_meta']:
        lines.append(f"| {row['split']} | {row['case']} | {row['seed']} | {row['steps_delta_cf_minus_meta']} | {row['energy_delta_cf_minus_meta']:.9f} |")
    lines.extend(['', '## 4 Ограничения', '', 'Небольшой фиксированный набор собственной упрощённой среды. Прогноз использует только известные объекты и условный показатель информации. Отложенные seed не заменяют независимый внешний турнир. Измерение времени исполнения не включается в воспроизводимый журнал решений.', ''])
    (output/'report.md').write_text('\n'.join(lines), encoding='utf-8')


def run(output=None, split='all', selected_cases=None, selected_seeds=None):
    design_path = ROOT/'experiments/stage4_design.json'
    design = json.loads(design_path.read_text(encoding='utf-8'))
    output = Path(output).resolve() if output else ROOT/'artifacts'/('stage4_'+uuid.uuid4().hex[:10])
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError('Нужен пустой каталог результатов')
    seeds = [('development', s) for s in design['development_seeds']] + [('holdout', s) for s in design['holdout_seeds']]
    seeds = [(label,s) for label,s in seeds if split == 'all' or label == split]
    if selected_seeds is not None:
        seeds = [(label,s) for label,s in seeds if s in selected_seeds]
    conditions = selected_cases or design['cases']
    if not seeds or not conditions:
        raise ValueError('Пустой план испытаний')
    results = []
    for label, seed in seeds:
        for case in conditions:
            initial_hashes = set()
            for name, cls in CONTROLLERS.items():
                directory = output/f'{label}_{seed}_{case}'/name
                directory.mkdir(parents=True)
                environment = Process(['environment', '--port', '0', '--log-path', str(directory/'environment.jsonl')])
                try:
                    url = environment.event('ready')['url']
                    controller = cls(directory/'controller.jsonl')
                    controller.mission_parameters = {'profile': 'rescue_v2', 'max_steps': design['max_steps'], **case_parameters(case)}
                    start = time.perf_counter(); error = None
                    try:
                        summary = controller.run(url, seed, design['max_steps']+5, run_id=f'stage4_{case}_{seed}')
                    except ProtocolError as exception:
                        error = {'code': exception.code, 'message': exception.message}
                        records = read_records(directory/'environment.jsonl')
                        final = records[-1]['output']
                        summary = {'episode_id': final['episode_id'], 'status': 'protocol_error', 'time': final['time'], 'metrics': final['metrics']}
                    execution_seconds = time.perf_counter()-start
                    environment_records = read_records(directory/'environment.jsonl')
                    controller_records = read_records(directory/'controller.jsonl')
                    observations = [r['output']['observation'] for r in environment_records if r['kind'] in ('reset', 'step')]
                    initial_hash = hashlib.sha256(canonical(observations[0]).encode()).hexdigest()
                    initial_hashes.add(initial_hash)
                    if error is None:
                        verification = audit(environment_records, controller_records)
                    else:
                        verification = {'status': 'incomplete', 'reason': 'command_rejected_no_fabricated_result'}
                    row = {'split': label, 'case': case, 'seed': seed, 'controller': name, **summary,
                           'max_steps': design['max_steps'], 'initial_public_sha256': initial_hash,
                           'error': error, 'audit': verification, 'execution_seconds': round(execution_seconds, 6)}
                    if name == 'counterfactual':
                        row['calibration'] = controller.calibration.summary()
                        dossier = save_headquarters(controller_records, directory)
                        row['forecast_policy_changes'] = sum(x['selected_candidate'] != 'meta' for x in dossier['decisions'])
                    results.append(row)
                    (directory/'replay.json').write_text(json.dumps(observations, ensure_ascii=False), encoding='utf-8')
                finally:
                    environment.stop()
            if len(initial_hashes) != 1:
                raise AssertionError('Paired controls did not receive identical initial observations')
    result = {'format': 'ariadna.experiment.v4', 'design': design,
              'design_sha256': hashlib.sha256(design_path.read_bytes()).hexdigest(),
              'results': results, 'aggregate': aggregate(results), 'output_directory': str(output)}
    (output/'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    write_report(result, output)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--split', choices=['all', 'development', 'holdout'], default='all')
    parser.add_argument('--case', action='append', choices=['clean', 'priority_pressure', 'resource_recovery', 'relay_recovery'])
    args = parser.parse_args()
    print(json.dumps(run(args.output, args.split, args.case), ensure_ascii=False, indent=2))
