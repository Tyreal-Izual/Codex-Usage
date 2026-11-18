#!/usr/bin/env python3
"""Offline memory comparisons using generated metadata; never opens account data."""
from __future__ import annotations
import argparse
import gc
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time
import tracemalloc
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def measure(collect):
    gc.collect()
    tracemalloc.start()
    start = time.perf_counter()
    value = collect()
    elapsed = time.perf_counter() - start
    retained, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return value, {'seconds': round(elapsed, 4), 'retained_bytes': retained, 'peak_bytes': peak}


def compare(records, baseline_ref):
    import claude_usage
    from usage_sources import SourceCache
    baseline = types.ModuleType('usage_memory_baseline')
    baseline.__file__ = str(ROOT / 'claude_usage.py')
    sys.modules[baseline.__name__] = baseline
    source = subprocess.check_output(['git', 'show', f'{baseline_ref}:claude_usage.py'], cwd=ROOT, text=True)
    exec(compile(source, baseline.__file__, 'exec'), baseline.__dict__)
    with tempfile.TemporaryDirectory() as directory:
        home = Path(directory)
        project = home / 'projects'
        project.mkdir()
        for file in range(100):
            with (project / f'session-{file}.jsonl').open('w', encoding='utf-8') as handle:
                for index in range(file, records, 100):
                    row = {'type': 'assistant', 'sessionId': f'session-{file}',
                           'timestamp': f'2026-11-{index % 12 + 1:02d}T10:00:00Z',
                           'cwd': '/synthetic/projects/a-long-repeated-project-directory',
                           'requestId': f'request-{index}', 'message': {'id': f'message-{index}',
                           'model': f'model-{index % 4}', 'usage': {'input_tokens': 101,
                           'output_tokens': index % 1000 + 10, 'cache_read_input_tokens': 5001,
                           'cache_creation_input_tokens': 301}}}
                    handle.write(json.dumps(row) + '\n')
                    if index % 7 == 0:  # Repeated streaming snapshots must still count once.
                        row['message']['usage']['output_tokens'] += 7
                        handle.write(json.dumps(row) + '\n')
        outputs, metrics = {}, {}
        for name, module in [('before', baseline), ('after', claude_usage)]:
            module._FILE_CACHE.clear()
            result, metrics[name] = measure(lambda: module.aggregate_local_usage(home, 20, 30))
            outputs[name] = json.dumps(result, sort_keys=True)
            module._FILE_CACHE.clear()
        if outputs['before'] != outputs['after']:
            raise AssertionError('Collector output changed')
        payload = (result, None)
        for name, shared in [('copied_cache', False), ('shared_cache', True)]:
            cache = SourceCache(shared_snapshots=shared)
            cache.get(('fixture',), lambda: payload, 3600)
            def hits():
                for _ in range(500):
                    value = cache.get(('fixture',), lambda: None, 3600)
                return value
            cached, metrics[name] = measure(hits)
            if json.dumps(cached, sort_keys=True) != json.dumps(payload, sort_keys=True):
                raise AssertionError('Cached report changed')
        return {'records': records, 'baseline_ref': baseline_ref, 'identical_output': True, **metrics}


def build_ui(bundle, cycles, baseline_ref=None, changing_values=False, delay_ms=20, value_every=1):
    bundle = bundle.resolve()
    if bundle.suffix != '.app':
        raise ValueError('Choose an .app path for the memory replay')
    identifier = 'com.tyreal.usage-memory.' + bundle.stem.lower()
    info_path = bundle / 'Contents/Info.plist'
    if bundle.exists():
        if not info_path.is_file() or plistlib.loads(info_path.read_bytes()).get('CFBundleIdentifier') != identifier:
            raise ValueError(f'Choose a new path or an existing memory replay app: {bundle}')
    binary = bundle / 'Contents/MacOS/MemoryReplay'
    binary.parent.mkdir(parents=True, exist_ok=True)
    sdk = subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip()
    arch = os.uname().machine
    with tempfile.TemporaryDirectory() as directory:
        source_root = ROOT
        if baseline_ref:
            source_root = Path(directory)
            paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', baseline_ref,
                                             'macOS/Sources/UsageMac'], cwd=ROOT, text=True).splitlines()
            for path in paths:
                target = source_root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(subprocess.check_output(['git', 'show', f'{baseline_ref}:{path}'], cwd=ROOT))
        sources = sorted((source_root / 'macOS/Sources/UsageMac').glob('*.swift'))
        sources = [str(p) for p in sources if p.name != 'UsageMacApp.swift']
        subprocess.run(['xcrun', 'swiftc', '-O', '-parse-as-library', '-sdk', sdk,
                        '-target', f'{arch}-apple-macos14.4', *sources, str(ROOT / 'scripts/memory_replay.swift'),
                        '-o', str(binary)], check=True)
    output = bundle.with_suffix('.json')
    info = {'CFBundleExecutable': 'MemoryReplay', 'CFBundleIdentifier': identifier,
            'CFBundleName': bundle.stem, 'CFBundlePackageType': 'APPL', 'NSPrincipalClass': 'NSApplication',
            'LSEnvironment': {'USAGE_MEMORY_CYCLES': str(cycles), 'USAGE_MEMORY_OUTPUT': str(output),
                              'USAGE_MEMORY_VALUES': '1' if changing_values else '0',
                              'USAGE_MEMORY_VALUE_EVERY': str(value_every),
                              'USAGE_MEMORY_DELAY_MS': str(delay_ms)}}
    info_path.write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign', '--force', '--sign', '-', str(bundle)], check=True)
    print(json.dumps({'app': str(bundle), 'result': str(output)}))


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return number


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ref', default='HEAD')
    parser.add_argument('--records', type=positive_int, default=12000)
    parser.add_argument('--ui-bundle', type=Path)
    parser.add_argument('--ui-baseline-ref', help='Compile the UI from this Git ref for a controlled comparison')
    parser.add_argument('--cycles', type=positive_int, default=600)
    parser.add_argument('--changing-values', action='store_true', help='Exercise number changes and highlight animations')
    parser.add_argument('--delay-ms', type=positive_int, default=20)
    parser.add_argument('--value-every', type=positive_int, default=1)
    args = parser.parse_args()
    if args.ui_bundle:
        build_ui(args.ui_bundle, args.cycles, args.ui_baseline_ref, args.changing_values, args.delay_ms, args.value_every)
    else:
        print(json.dumps(compare(args.records, args.baseline_ref), indent=2))
