"""Summarize caller-side audio timeline measurements without substituting server proxies."""
import argparse
import json
import math
from pathlib import Path


def percentile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low = math.floor(position); high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def summarize(rows):
    if not rows or len({row['turn_id'] for row in rows}) != len(rows):
        raise ValueError('Provide unique caller-side turn IDs')
    groups = {name: [] for name in ['all', 'normal', 'tool_call', 'interrupted']}
    for row in rows:
        end, response = row['speech_end_ms'], row['first_audible_response_ms']
        if not all(math.isfinite(value) for value in (end, response)) or response < end:
            raise ValueError('Use finite timestamps from the same caller-side audio timeline')
        if any(type(row.get(key)) is not bool for key in ('tool_call', 'interrupted')):
            raise ValueError('Label tool and interrupted turns explicitly')
        latency = response - end
        group = 'interrupted' if row['interrupted'] else 'tool_call' if row['tool_call'] else 'normal'
        groups['all'].append(latency); groups[group].append(latency)
    return {name: {'turns': len(values),
                  'p50_ms': percentile(values, .5), 'p95_ms': percentile(values, .95),
                  'p99_ms': percentile(values, .99),
                  'fraction_under_900_ms': sum(value < 900 for value in values) / len(values)}
            for name, values in groups.items() if values}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('measurements', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.measurements.read_text().splitlines() if line.strip()]
    args.output.write_text(json.dumps({'definition': 'Caller end-of-speech to first audible reply',
        'groups': summarize(records)}, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__': main()
