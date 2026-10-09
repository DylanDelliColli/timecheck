"""Real HTTP body reads on localhost, routed at the archive transport boundary.
Build, validation, hashing, matching, SQLite and CLI execution are real.
"""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sqlite3
from threading import Thread
from urllib.request import urlopen
import pytest
from timecheck.cli import main
from test_integration import dataset, SNAPSHOTS


@contextmanager
def archive_server(*, fail_until):
 raw=next(SNAPSHOTS.iterdir()).read_bytes()
 requests=[]
 class Handler(BaseHTTPRequestHandler):
  protocol_version='HTTP/1.1'
  def do_GET(self):
   requests.append(self.path)
   short=len(requests)<=fail_until
   self.send_response(200)
   self.send_header('Content-Type','text/html; charset=utf-8')
   self.send_header('Content-Length',str(len(raw)+128 if short else len(raw)))
   self.send_header('Connection','close')
   self.end_headers()
   self.wfile.write(raw)
   self.wfile.flush()
  def log_message(self,*args):pass
 with ThreadingHTTPServer(('127.0.0.1',0),Handler) as server:
  thread=Thread(target=server.serve_forever,daemon=True);thread.start()
  try:yield f'http://127.0.0.1:{server.server_port}/snapshot',requests
  finally:
   server.shutdown();thread.join(timeout=5)
   assert not thread.is_alive()


@pytest.mark.parametrize('strict,expected',[(True,2),(False,1)])
def test_short_http_body_retries_and_reports_incomplete_read(dataset,tmp_path,monkeypatch,capsys,strict,expected):
 delays=[]
 monkeypatch.setattr('timecheck.evidence.time.sleep',delays.append)
 with archive_server(fail_until=4) as (endpoint,requests):
  # Sources stay valid pinned Wayback records. Only route requests to the fixture
  # endpoint; urlopen and HTTPResponse.read use real sockets and real short bodies.
  monkeypatch.setattr('timecheck.evidence.urlopen',lambda request,timeout:urlopen(endpoint,timeout=timeout))
  flags=['--strict'] if strict else []
  code=main(['build','--data-dir',str(dataset),'--out',str(tmp_path/'graph.sqlite'),'--report',str(tmp_path/'report.json'),*flags])
  assert code==expected
  assert len(requests)==4 and delays==[1,2,4]
 output=capsys.readouterr();assert 'Traceback' not in output.err
 report=json.loads((tmp_path/'report.json').read_text())
 problems=report['errors'] if strict else report['warnings']
 assert len(problems)==23 and {p['class'] for p in problems}=={'snapshot_unavailable'}
 assert all('IncompleteRead' in p['message'] for p in problems)


def test_short_http_body_recovers_on_later_retry(dataset,tmp_path,monkeypatch):
 delays=[]
 monkeypatch.setattr('timecheck.evidence.time.sleep',delays.append)
 with archive_server(fail_until=2) as (endpoint,requests):
  monkeypatch.setattr('timecheck.evidence.urlopen',lambda request,timeout:urlopen(endpoint,timeout=timeout))
  code=main(['build','--strict','--data-dir',str(dataset),'--out',str(tmp_path/'graph.sqlite'),'--report',str(tmp_path/'report.json')])
  assert code==0
  assert len(requests)==3 and delays==[1,2]
 with sqlite3.connect(tmp_path/'graph.sqlite') as db:
  assert db.execute('SELECT COUNT(*) FROM v_lineage').fetchone()[0]==3
 report=json.loads((tmp_path/'report.json').read_text());assert not report['errors'] and not report['warnings']
 assert set(report['evidence_verification'].values())=={'verified'}


@pytest.mark.parametrize('first_response', [429, 503, 'placeholder'])
def test_real_archive_throttle_and_placeholder_recovery(dataset, tmp_path, monkeypatch, first_response):
 raw = next(SNAPSHOTS.iterdir()).read_bytes(); requests = []; delays = []
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   requests.append(self.path)
   first = len(requests) == 1
   status = first_response if first and isinstance(first_response, int) else 200
   body = (b'<html><title>Wayback Machine</title><p>The Wayback Machine has not archived that URL.</p></html>'
           if first and first_response == 'placeholder' else raw)
   self.send_response(status); self.send_header('Content-Type', 'text/html; charset=utf-8')
   self.send_header('Content-Length', str(len(body))); self.send_header('Retry-After', '2')
   self.end_headers(); self.wfile.write(body)
  def log_message(self, *args): pass
 with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
  thread = Thread(target=server.serve_forever, daemon=True); thread.start()
  endpoint = f'http://127.0.0.1:{server.server_port}/snapshot'
  monkeypatch.setattr('timecheck.evidence.urlopen', lambda request, timeout: urlopen(endpoint, timeout=timeout))
  monkeypatch.setattr('timecheck.evidence.time.sleep', delays.append)
  try:
   code = main(['build', '--strict', '--data-dir', str(dataset), '--out', str(tmp_path/'graph.sqlite'),
                '--report', str(tmp_path/'report.json')])
  finally: server.shutdown(); thread.join(timeout=5)
 assert code == 0 and len(requests) == 2
 assert len(delays) == 1 and 5 <= delays[0] <= 60
 with sqlite3.connect(tmp_path/'graph.sqlite') as db:
  assert db.execute('SELECT COUNT(*) FROM v_evidence').fetchone()[0] == 23
