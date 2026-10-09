#!/usr/bin/env python3
"""CI-only evidence selection; structural checks always cover the complete graph."""
import argparse
from datetime import date
import json
from pathlib import Path
import subprocess

from timecheck.build import build
from timecheck.validate import load_data


ENTITY_FOLDERS = {'brands', 'lines', 'references', 'calibers'}


def _git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], text=True)


def _revision_data(repo, revision):
    # Resolve revisions to immutable commit ids before reading any objects.
    commit = _git(repo, 'rev-parse', '--verify', revision + '^{commit}').strip()
    paths = _git(repo, 'ls-tree', '-r', '--name-only', commit, '--', 'data').splitlines()
    evidence, sources = {}, {}
    for name in paths:
        parts = Path(name).parts
        if len(parts) != 3 or parts[2].endswith('.json') is False:
            continue
        if parts[1] not in ENTITY_FOLDERS | {'sources'}:
            continue
        doc = json.loads(_git(repo, 'show', commit + ':' + name))
        if parts[1] == 'sources':
            sources[doc['id']] = doc
        else:
            for claim in doc.get('claims', []):
                for item in claim['evidence']:
                    evidence[item['id']] = item
    return evidence, sources


def changed_evidence(repo, base, head):
    """Compare evidence items and source metadata, ignoring claim status/review."""
    old, old_sources = _revision_data(repo, base)
    new, new_sources = _revision_data(repo, head)
    return {ident for ident, item in new.items()
            if old.get(ident) != item or old_sources.get(item['source']) != new_sources.get(item['source'])}


def sample_evidence(claims, sources, *, day, size=10):
    """Rotate through pinned captures; check every item using sampled captures."""
    captures = {}
    for claim in claims:
        for item in claim['evidence']:
            if item['match_mode'] == 'manual' or item['source'] not in sources:
                continue
            source = sources[item['source']]
            key = (source['archive_url'], source['snapshot_sha256'], source['content_type'])
            captures.setdefault(key, set()).add(item['id'])
    keys = sorted(captures)
    if not keys or size <= 0:
        return set()
    count = min(size, len(keys)); start = (day * count) % len(keys)
    return set().union(*(captures[keys[(start + i) % len(keys)]] for i in range(count)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--base')
    mode.add_argument('--sample', action='store_true')
    parser.add_argument('--head')
    parser.add_argument('--sample-size', type=int, default=10)
    parser.add_argument('--data-dir', default='data')
    parser.add_argument('--snapshot-dir')
    parser.add_argument('--cache-dir')
    parser.add_argument('--out', default='timecheck.sqlite')
    parser.add_argument('--report', default='report.json')
    args = parser.parse_args(argv)
    if args.base:
        if not args.head:
            parser.error('--base requires --head')
        selected = changed_evidence(Path.cwd(), args.base, args.head)
    else:
        _, sources, claims, _, _, _ = load_data(args.data_dir)
        selected = sample_evidence(claims, sources, day=date.today().toordinal(), size=args.sample_size)
    print(json.dumps({'selected_evidence_ids': sorted(selected), 'count': len(selected)}), flush=True)
    code, report = build(data_dir=args.data_dir, strict=True, evidence_ids=selected,
                         snapshot_dir=args.snapshot_dir, cache_dir=args.cache_dir,
                         out=args.out, report=args.report)
    print(json.dumps({'exit_code': code, 'errors': report['errors_by_class'],
                      'warnings': report['warnings_by_class'], 'report': args.report}))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
