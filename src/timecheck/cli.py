"""Command line consumer of the build and the six canonical views."""
import argparse
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
import sys
from .build import build
from .ids import new_id
from .status import verify_status
from .snapshot import pin

VIEWS = {'v_reference_calibers','v_caliber_family','v_shared_dna','v_lineage','v_lineage_diff','v_evidence'}


def query(args):
    view = args.view.removesuffix('_all')
    if view not in VIEWS:
        raise ValueError('Unknown canonical view: ' + args.view)
    if args.include_proposed or args.view.endswith('_all'):
        view += '_all'
    with sqlite3.connect(f'{Path(args.db).resolve().as_uri()}?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        if args.primary_only:
            # Recompose every view over primary-supported claims, including family edges.
            sql = files('timecheck').joinpath('sql/views.sql').read_text()
            sql = sql.replace('CREATE VIEW ', 'CREATE TEMP VIEW ')
            sql = sql.replace("WHERE c.status = 'verified';", "WHERE c.status = 'verified' AND c.has_primary=1;")
            sql = sql.replace('LEFT JOIN claim_years y ON y.claim_id=c.id ;', 'LEFT JOIN claim_years y ON y.claim_id=c.id WHERE c.has_primary=1;')
            db.executescript(sql)
        filters = []
        if args.where:
            filters.append('(' + args.where + ')')
        if args.primary_only:
            columns = {row[1] for row in db.execute(f'PRAGMA table_info({view})')}
            if 'has_primary' in columns:
                filters.append('has_primary=1')
            if 'tier' in columns:
                filters.append("tier='primary'")
        sql = f'SELECT * FROM {view}' + (' WHERE ' + ' AND '.join(filters) if filters else '')
        rows = [dict(row) for row in db.execute(sql)]
    print(json.dumps(rows, ensure_ascii=False))
    return 0


def parser():
    root = argparse.ArgumentParser(prog='timecheck')
    cmds = root.add_subparsers(dest='command', required=True)
    b = cmds.add_parser('build')
    for name, default in [('data-dir','data'),('out','timecheck.sqlite'),('report','report.json'),('snapshot-dir',None),('cache-dir',None)]:
        b.add_argument('--' + name, default=default)
    for flag in ('strict','offline','no-evidence'):
        b.add_argument('--' + flag, action='store_true')
    b.add_argument('--only-changed', nargs='*', default=None)
    q = cmds.add_parser('query')
    q.add_argument('view')
    q.add_argument('--where')
    q.add_argument('--primary-only', action='store_true')
    q.add_argument('--include-proposed', action='store_true')
    q.add_argument('--db', default='timecheck.sqlite')
    q.add_argument('--json', action='store_true')
    ids = cmds.add_parser('id').add_subparsers(dest='action', required=True)
    ids.add_parser('new').add_argument('kind', choices=('claim','evidence'))
    snapshot = cmds.add_parser('snapshot').add_subparsers(dest='action', required=True)
    snapshot.add_parser('hash').add_argument('file')
    snapshot.add_parser('pin').add_argument('url')
    status = cmds.add_parser('status').add_subparsers(dest='action', required=True)
    verify = status.add_parser('verify')
    verify.add_argument('--by', required=True)
    verify.add_argument('--at')
    verify.add_argument('--data-dir', default='data')
    verify.add_argument('--report', default='report.json')
    verify.add_argument('--files', nargs='+')
    verify.add_argument('--except', dest='exclude', nargs='+', default=[])
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == 'build':
            code, result = build(**{k: v for k, v in vars(args).items() if k != 'command'})
            print(json.dumps({'exit_code': code, 'entities': sum(result['entity_counts'].values()),
                              'claims': sum(result['claim_counts']['status'].values()),
                              'errors': result['errors_by_class'], 'warnings': result['warnings_by_class'],
                              'report': args.report}))
            return code
        if args.command == 'query':
            return query(args)
        if args.command == 'id':
            print(new_id(args.kind))
            return 0
        if args.command == 'status':
            print(json.dumps(verify_status(**{k: v for k, v in vars(args).items() if k not in {'command', 'action'}})))
            return 0
        if args.action == 'hash':
            print(hashlib.sha256(Path(args.file).read_bytes()).hexdigest())
            return 0
        print(json.dumps(pin(args.url)))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(str(exc), file=sys.stderr)
        return 2
