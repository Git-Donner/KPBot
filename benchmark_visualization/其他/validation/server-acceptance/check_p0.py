"""Independent arithmetic oracle for P0 output (does not import production code)."""
import argparse
import json
import math
from pathlib import Path


def median(a):
    a = sorted(a)
    n = len(a)
    return a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2


def main():
    p = argparse.ArgumentParser()
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    data = json.loads(args.input.read_text())
    result = json.loads(args.output.read_text())
    ratios = []
    def equal(a, b):
        if not math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12):
            raise AssertionError((a, b))
    if set(data['datasets']) != set(result['datasets']):
        raise AssertionError('dataset mismatch')
    for name, sides in data['datasets'].items():
        r = result['datasets'][name]
        centers = []
        for side in ('baseline', 'candidate'):
            values = [x[data['performance_field']] for x in sides[side]]
            center = median(values)
            centers.append(center)
            equal(r[side+'_median'], center)
            equal(r[side+'_samples'], len(values))
            s = r[side+'_statistics']
            for key, expected in [('min', min(values)), ('max', max(values)), ('mad', median([abs(x-center) for x in values]))]:
                equal(s[key], expected)
            if s['sample_count_below_three'] != (len(values) < 3):
                raise AssertionError('sample flag mismatch')
        ratio = centers[1]/centers[0] if data['higher_is_better'] else centers[0]/centers[1]
        ratios.append(ratio)
        equal(r['speedup'], ratio)
        equal(r['improvement_percent'], (ratio-1)*100)
    equal(result['geomean_speedup'], math.exp(sum(math.log(x) for x in ratios)/len(ratios)))
    print(f'PASS: {len(ratios)} datasets independently checked')


if __name__ == '__main__':
    main()
