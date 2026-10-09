"""Replay pasted CLI JSON against the real seed, without archive access."""
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (ROOT / 'docs/querying.md', ROOT / 'README.md')
FENCES = re.compile(r'^```([^\n]*)\n(.*?)^```[ \t]*$', re.MULTILINE | re.DOTALL)


def examples(markdown):
    """Require each output to follow one executable query; skip explicit illustrations."""
    previous = None
    for block in FENCES.finditer(markdown):
        language, body = block.group(1).strip(), block.group(2).strip()
        if language == 'json':
            prefix = markdown[:block.start()].rstrip()
            if prefix.endswith('<!-- illustrative -->'):
                previous = block
                continue
            assert previous is not None, 'JSON output has no preceding command'
            assert previous.group(1).strip() == 'sh', 'JSON output must follow a sh query'
            command = previous.group(2).strip()
            assert '\n' not in command, 'Pasted output needs one query command'
            argv = shlex.split(command)
            assert argv[:2] == ['.venv/bin/timecheck', 'query'], command
            yield command, json.loads(body)
        previous = block


def cli(*args):
    return subprocess.run([sys.executable, '-m', 'timecheck', *map(str, args)],
                          cwd=ROOT, text=True, capture_output=True)


@pytest.fixture(scope='module')
def seed_db(tmp_path_factory):
    directory = tmp_path_factory.mktemp('docs-seed')
    database = directory / 'timecheck.sqlite'
    result = cli('build', '--strict', '--no-evidence', '--data-dir', ROOT / 'data',
                 '--out', database, '--report', directory / 'report.json')
    assert result.returncode == 0, result.stdout + result.stderr
    return database


def canonical_rows(rows):
    # Views promise no ordering; preserve row multiplicity and every column/value.
    assert isinstance(rows, list)
    return sorted(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows)


CASES = [(path, command, expected) for path in DOCUMENTS
         for command, expected in examples(path.read_text())]


@pytest.mark.parametrize('path,command,expected', CASES,
                         ids=[f'{p.relative_to(ROOT)}:{c}' for p, c, _ in CASES])
def test_pasted_cli_output(seed_db, path, command, expected):
    argv = shlex.split(command)[1:]
    # Append our isolated freshly built database, overriding any documented default.
    result = cli(*argv, '--db', seed_db)
    assert result.returncode == 0, f'{path}: {command}\n{result.stderr}'
    assert canonical_rows(json.loads(result.stdout)) == canonical_rows(expected), command


def test_examples_are_present():
    assert len(list(examples(DOCUMENTS[0].read_text()))) >= 12


def test_extracts_output_and_skips_explicit_illustration():
    markdown = '''```sh
.venv/bin/timecheck query v_lineage --json
```

```json
[]
```

<!-- illustrative -->
```json
{"not": "CLI output"}
```
'''
    assert list(examples(markdown)) == [('.venv/bin/timecheck query v_lineage --json', [])]


@pytest.mark.parametrize('markdown', [
    '```json\n[]\n```\n',
    '```sh\necho example\n```\n\n```json\n[]\n```\n',
    '```sh\n.venv/bin/timecheck query v_lineage\necho extra\n```\n\n```json\n[]\n```\n',
])
def test_unreplayable_json_is_rejected(markdown):
    with pytest.raises(AssertionError):
        list(examples(markdown))
