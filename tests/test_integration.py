import copy
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
SNAPSHOTS=ROOT/'tests/snapshots'
VIEWS=['v_reference_calibers','v_caliber_family','v_shared_dna','v_lineage','v_lineage_diff','v_evidence']

@pytest.fixture
def dataset(tmp_path):
 data=tmp_path/'data'; shutil.copytree(ROOT/'tests/fixtures/data',data);return data

def change(data,file,fn):
 p=data/file; doc=json.loads(p.read_text());fn(doc);p.write_text(json.dumps(doc))

def cli(*args): return subprocess.run([sys.executable,'-m','timecheck',*map(str,args)],cwd=ROOT,text=True,capture_output=True)

def build(data,tmp_path,*flags):
 result=cli('build','--data-dir',data,'--snapshot-dir',SNAPSHOTS,'--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json',*flags)
 report=json.loads((tmp_path/'report.json').read_text());return result,report

def rows(tmp_path,view):
 with sqlite3.connect(tmp_path/'graph.sqlite') as db:
  db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute('SELECT * FROM '+view)]

def test_real_build_every_view(dataset,tmp_path):
 result,report=build(dataset,tmp_path,'--strict');assert result.returncode==0,result.stderr
 assert report['entity_counts']['reference']==3
 assert report['coverage']['line:example']=={'target':3,'covered':2,'missing':['reference:gamma']}
 r=rows(tmp_path,'v_reference_calibers');assert len(r)==2
 assert {(x['reference_id'],x['grade']) for x in r}=={('reference:alpha','none'),('reference:beta','Top')}
 family=rows(tmp_path,'v_caliber_family');assert any(x['caliber_id']=='caliber:one' and x['related_id']=='caliber:two-top' and x['depth']==2 for x in family)
 dna=rows(tmp_path,'v_shared_dna');assert {(x['reference_id'],x['other_reference_id']) for x in dna}=={('reference:alpha','reference:beta'),('reference:beta','reference:alpha')}
 lineage=rows(tmp_path,'v_lineage');assert len(lineage)==3
 gamma=next(x for x in lineage if x['reference_id']=='reference:gamma');assert gamma['caliber_id'] is None and gamma['year_from']==1998
 diff=rows(tmp_path,'v_lineage_diff');j=next(x for x in diff if x['attribute']=='jewels');assert (j['before_value'],j['after_value'],j['changed'])==('21','25',1)
 assert next(x for x in diff if x['attribute']=='winding')['changed']==0
 assert len(rows(tmp_path,'v_evidence'))==report['evidence_count']
 for view in VIEWS:
  assert rows(tmp_path,view)==rows(tmp_path,view+'_all')
  q=cli('query',view,'--db',tmp_path/'graph.sqlite','--json');assert q.returncode==0,q.stderr;assert json.loads(q.stdout)==rows(tmp_path,view)
 assert cli('query','v_lineage','--db',tmp_path/'graph.sqlite','--where',"reference_id = 'reference:beta'",'--primary-only','--json').returncode==0
 assert cli('query','v_bad','--db',tmp_path/'graph.sqlite','--json').returncode==2
 assert cli('query','v_lineage','--db',tmp_path/'graph.sqlite','--where','invalid sql','--json').returncode==2

@pytest.mark.parametrize('case,error',[
 ('no_evidence','evidence_missing'),('quote_absent','quote_not_found'),('hash_mismatch','snapshot_hash_mismatch'),
 ('unresolved','unresolved_slug'),('duplicate','duplicate_id'),('cycle','succeeds_cycle'),('absence','explicit_absence_required')])
def test_negative_fixtures(dataset,tmp_path,case,error):
 if case=='no_evidence':change(dataset,'references/alpha.json',lambda d:d['claims'][1].update(evidence=[]))
 if case=='quote_absent':change(dataset,'references/alpha.json',lambda d:d['claims'][1]['evidence'][0].update(quote='This synthetic quote never appears in the archive.'))
 if case=='hash_mismatch':
  snaps=tmp_path/'snapshots';shutil.copytree(SNAPSHOTS,snaps)
  next(snaps.iterdir()).write_bytes(b'incorrect snapshot bytes')
  result=cli('build','--data-dir',dataset,'--snapshot-dir',snaps,'--strict','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');report=json.loads((tmp_path/'report.json').read_text())
  assert result.returncode==2;assert error in [x['class'] for x in report['errors']];return
 if case=='unresolved':change(dataset,'references/alpha.json',lambda d:d['claims'][1]['object'].update(entity='caliber:missing'))
 if case=='duplicate':change(dataset,'references/alpha.json',lambda d:d['claims'][1].update(id=d['claims'][0]['id']))
 if case=='cycle':
  beta=json.loads((dataset/'references/beta.json').read_text());c=copy.deepcopy(beta['claims'][2]);c.update(id='clm-zzzzzzzzzz',object={'entity':'reference:beta'});c['evidence'][0]['id']='ev-zzzzzzzzzz'
  change(dataset,'references/alpha.json',lambda d:d['claims'].append(c))
 if case=='absence':change(dataset,'calibers/one.json',lambda d:d['claims'][1]['evidence'][0].update(quote='Caliber One is made by Example Brand'))
 result,report=build(dataset,tmp_path,'--strict');assert result.returncode==2,(result.stdout,result.stderr);assert error in [x['class'] for x in report['errors']]

def test_overlap_disputed(dataset,tmp_path):
 def add(d):
  c=copy.deepcopy(d['claims'][1]);c['id']='clm-zzzzzzzzzz';c['evidence'][0]['id']='ev-zzzzzzzzzz';c['object']['entity']='caliber:two';c['valid_years'].update(from_evidence='ev-zzzzzzzzzz',to_evidence='ev-zzzzzzzzzz');d['claims'].append(c)
 change(dataset,'references/alpha.json',add)
 result,report=build(dataset,tmp_path,'--strict');assert result.returncode==0,result.stderr
 assert all(r['disputed']==1 for r in rows(tmp_path,'v_reference_calibers') if r['reference_id']=='reference:alpha')
 assert report['disputed']==2

def test_proposed_and_manual(dataset,tmp_path):
 change(dataset,'references/beta.json',lambda d:d['claims'][1].update(status='proposed'))
 result,report=build(dataset,tmp_path,'--strict');assert result.returncode==0,result.stderr
 assert len(rows(tmp_path,'v_reference_calibers'))==1
 assert len(rows(tmp_path,'v_reference_calibers_all'))==2
 q=cli('query','v_reference_calibers','--include-proposed','--db',tmp_path/'graph.sqlite','--json');assert len(json.loads(q.stdout))==2

def test_offline_exit_codes_and_changed(dataset,tmp_path):
 for strict,code in [(False,1),(True,2)]:
  args=['--strict'] if strict else []
  result=cli('build','--data-dir',dataset,'--offline','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json',*args);assert result.returncode==code,result.stderr
 result=cli('build','--data-dir',dataset,'--offline','--strict','--only-changed',dataset/'brands/example.json','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');assert result.returncode==0,result.stderr

def test_snapshot_hash_and_id():
 import hashlib,re
 p=next(SNAPSHOTS.iterdir());r=cli('snapshot','hash',p);assert r.stdout.strip()==hashlib.sha256(p.read_bytes()).hexdigest()
 assert re.fullmatch(r'clm-[a-z2-7]{10}',cli('id','new','claim').stdout.strip())
