#!/usr/bin/env python3
"""Real zlib workload; standard library only. Each observation is a fresh process."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import sys
import time
import zlib


def save(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def worker(args):
    rng = random.Random(args.seed)
    data = (rng.randbytes(args.size) if args.workload == 'random' else
            (b'Kunpeng-performance-test-0123456789\n' * (args.size // 36 + 2))[:args.size])
    # Ensure requested size independently of seed pattern length.
    if len(data) != args.size:
        data = (data * (args.size // len(data) + 1))[:args.size]
    zlib.compress(data, args.level)  # explicit one-operation warmup
    samples = []
    started = time.perf_counter()
    cpu_start = time.process_time()
    while len(samples) < 3 or (time.perf_counter() - started < args.seconds and len(samples) < 10000):
        t = time.perf_counter_ns()
        compressed = zlib.compress(data, args.level)
        samples.append((time.perf_counter_ns() - t) / 1e6)
    cpu = time.process_time() - cpu_start
    elapsed = time.perf_counter() - started
    correct = zlib.decompress(compressed) == data
    median = statistics.median(samples)
    return dict(size=args.size, size_mib=args.size / 1048576, level=args.level,
                workload=args.workload, latency_ms=median, throughput_mib_s=args.size / 1048576 / (median / 1000),
                min_ms=min(samples), max_ms=max(samples), cpu_seconds=cpu,
                cpu_pct=cpu / elapsed * 100, compressed_ratio=len(compressed) / len(data),
                operations=len(samples), correctness=int(correct), input_sha256=hashlib.sha256(data).hexdigest(),
                inner_operation_ms=samples)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path)
    p.add_argument('--sizes', default='65536,1048576,8388608')
    p.add_argument('--levels', default='1,6,9')
    p.add_argument('--workloads', default='compressible,random')
    p.add_argument('--repeats', type=int, default=7)
    p.add_argument('--seconds', type=float, default=.3)
    p.add_argument('--seed', type=int, default=20261104)
    p.add_argument('--worker', action='store_true')
    p.add_argument('--size', type=int)
    p.add_argument('--level', type=int)
    p.add_argument('--workload')
    args = p.parse_args()
    if args.worker:
        print(json.dumps(worker(args)))
        return
    if args.output is None or args.output.exists():
        p.error('--output must be a new directory')
    sizes = list(map(int, args.sizes.split(',')))
    levels = list(map(int, args.levels.split(',')))
    workloads = args.workloads.split(',')
    if args.repeats < 1 or args.seconds <= 0 or min(sizes) <= 0 or any(x not in range(1, 10) for x in levels) or any(x not in ('random', 'compressible') for x in workloads):
        p.error('invalid experiment matrix')
    args.output.mkdir(parents=True)
    (args.output / 'raw').mkdir()
    metadata = dict(platform=platform.platform(), machine=platform.machine(), python=sys.version,
                    zlib=zlib.ZLIB_RUNTIME_VERSION, cpu_count=os.cpu_count(), command=sys.argv,
                    warmup='one compression per fresh process', sample_level='per-run median of inner operations',
                    seed=args.seed, status='running', affinity=sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None)
    save(args.output / 'environment.json', metadata)
    schedule = []
    rng = random.Random(args.seed)
    for repeat in range(args.repeats):
        block = [(s, l, w) for s in sizes for l in levels for w in workloads]
        rng.shuffle(block)
        schedule.extend((repeat, *case) for case in block)
    save(args.output / 'schedule.json', schedule)
    rows = []
    for order, (repeat, size, level, workload) in enumerate(schedule):
        command = [sys.executable, str(Path(__file__).resolve()), '--worker', '--size', str(size),
                   '--level', str(level), '--workload', workload, '--seconds', str(args.seconds), '--seed', str(args.seed)]
        proc = subprocess.run(command, capture_output=True, text=True, timeout=max(120, args.seconds * 10))
        (args.output / 'raw' / f'{order:04d}.stderr').write_text(proc.stderr, encoding='utf-8')
        if proc.returncode:
            raise RuntimeError(f'worker {order} failed: {proc.stderr}')
        record = json.loads(proc.stdout)
        record.update(run_id=f'run-{order:04d}', repeat=repeat, order=order, captured_at=time.time())
        save(args.output / 'raw' / f'{order:04d}.json', record)
        if not record['correctness']:
            raise RuntimeError('roundtrip failed')
        rows.append({k: v for k, v in record.items() if k != 'inner_operation_ms'})
        print(f'{order+1}/{len(schedule)} {workload} size={size} level={level}', flush=True)
    with (args.output / 'samples.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    if 1 in levels and 6 in levels:
        for metric, higher in [('latency_ms', False), ('throughput_mib_s', True)]:
            payload = dict(performance_field=metric, higher_is_better=higher, correctness_fields=['correctness'], datasets={})
            for size in sizes:
                for workload in workloads:
                    payload['datasets'][f'{workload}-{size}'] = {
                        side: [{metric: r[metric], 'correctness': r['correctness']} for r in rows
                               if r['size'] == size and r['workload'] == workload and r['level'] == level]
                        for side, level in [('baseline', 6), ('candidate', 1)]}
            save(args.output / f'p0-{metric}.json', payload)
    metrics = [dict(name=m, column=m, unit=u, sample_level='summary') for m, u in
               [('latency_ms', 'ms'), ('throughput_mib_s', 'MiB/s'), ('min_ms', 'ms'), ('max_ms', 'ms'),
                ('cpu_seconds', 's'), ('cpu_pct', '% of one core'), ('compressed_ratio', 'output/input')]]
    charts = []
    for kind, metric in [('scatter', 'latency_ms'), ('line', 'throughput_mib_s'), ('box', 'latency_ms'),
                         ('bar', 'cpu_seconds'), ('point', 'compressed_ratio'), ('heatmap', 'latency_ms'),
                         ('hist', 'latency_ms'), ('ecdf', 'latency_ms')]:
        c = dict(id=kind, type=kind, metric=metric, x='size_mib', x_type='numeric',
                 series='level', facet='workload', unit_id='run_id', title='Real zlib measurements: '+metric)
        if kind not in ('box', 'hist', 'ecdf'):
            c.update(aggregate='median', aggregate_summary=True)
        if kind in ('line', 'point', 'bar'):
            c.update(spread='minmax', show_samples=True)
        if kind in ('hist', 'ecdf'):
            c['filter'] = {'size': str(max(sizes))}  # CSV strings; fixed size distribution
        charts.append(c)
    for metric in ('min_ms', 'max_ms'):
        charts.append(dict(id=metric, type='scatter', metric=metric, x='size_mib', x_type='numeric',
                           series='level', facet='workload', unit_id='run_id', title='Per-run '+metric))
    spec = dict(input=dict(path='samples.csv', format='csv'), mapping=dict(metrics=metrics), charts=charts,
                output=dict(directory='charts', formats=['svg', 'png']))
    save(args.output / 'chart-spec.json', spec)
    metadata.update(status='complete', records=len(rows))
    save(args.output / 'environment.json', metadata)


if __name__ == '__main__':
    main()
