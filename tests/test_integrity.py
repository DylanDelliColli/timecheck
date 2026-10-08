import copy
import gzip
import hashlib
import json
from pathlib import Path
import pytest
from timecheck.ids import new_id
from timecheck.validate import domain
from test_integration import dataset, change, build, cli, rows, SNAPSHOTS, VIEWS


def clone(c):
 c=copy.deepcopy(c);c['id']=new_id('claim')
 for e in c['evidence']:e['id']=new_id('evidence')
 if c.get('valid_years'):
  y=c['valid_years'];y['from_evidence']=c['evidence'][0]['id'] if y['from'] is not None else None;y['to_evidence']=c['evidence'][0]['id'] if y['to'] is not None else None
 if 'years' in c['object']:
  y=c['object']['years'];y['from_evidence']=c['evidence'][0]['id'] if y['from'] is not None else None;y['to_evidence']=c['evidence'][0]['id'] if y['to'] is not None else None
 return c

@pytest.mark.parametrize('file,mutate,error',[
 ('references/alpha.json',lambda d:d['claims'][1]['valid_years'].update(from_evidence='ev-zzzzzzzzzz'),'year_evidence'),
 ('references/alpha.json',lambda d:d['claims'][1]['valid_years'].update(to=1999),'invalid_years'),
 ('references/alpha.json',lambda d:d['claims'][1]['evidence'][0].update(quote='tiny'),'quote_too_short'),
 ('references/alpha.json',lambda d:d['claims'][1]['evidence'][0].update(quote='                      a'),'quote_too_short'),
 ('references/alpha.json',lambda d:d['claims'][1].pop('review'),'schema_error'),
 ('references/alpha.json',lambda d:d['claims'][1]['evidence'][0].update(match_mode='fuzzy'),'schema_error'),
 ('calibers/one.json',lambda d:d['claims'][2]['object'].update(value='self_winding'),'schema_error'),
 ('references/alpha.json',lambda d:d['claims'][1]['object'].update(entity='brand:example'),'predicate_object'),
 ('calibers/one.json',lambda d:d['claims'][2].update(predicate='in_line',object={'entity':'line:example'}),'predicate_subject'),
 ('sources/example.json',lambda d:d.update(licence='CC BY-NC-SA 4.0'),'banned_source'),
 ('sources/example.json',lambda d:d.update(content_type='image_scan'),'unsupported_content_type'),
 ('sources/example.json',lambda d:d.update(content_type='pdf_text'),'unsupported_content_type')])
def test_integrity_errors(dataset,tmp_path,file,mutate,error):
 change(dataset,file,mutate);r,report=build(dataset,tmp_path,'--strict');assert r.returncode==2
 assert error in report['errors_by_class'],report

def test_gzip_raw_hash(dataset,tmp_path):
 raw=next(SNAPSHOTS.iterdir()).read_bytes();packed=gzip.compress(raw,mtime=0);sha=hashlib.sha256(packed).hexdigest()
 snapshots=tmp_path/'snapshots';snapshots.mkdir();(snapshots/(sha+'.bin')).write_bytes(packed)
 change(dataset,'sources/example.json',lambda d:d.update(snapshot_sha256=sha))
 r=cli('build','--data-dir',dataset,'--snapshot-dir',snapshots,'--strict','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');assert r.returncode==0,(r.stdout,r.stderr)

def test_manual_pending_no_snapshot(dataset,tmp_path):
 change(dataset,'sources/example.json',lambda d:d.update(content_type='image_scan'))
 for file in dataset.glob('*/*.json'):
  if file.parent.name in ['sources','targets']:continue
  def manual(d):
   for c in d['claims']:
    c['status']='proposed';c.pop('review',None)
    for e in c['evidence']:e['match_mode']='manual'
  change(dataset,file.relative_to(dataset),manual)
 r=cli('build','--data-dir',dataset,'--offline','--strict','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');assert r.returncode==0,(r.stdout,r.stderr)
 report=json.loads((tmp_path/'report.json').read_text());assert len(report['pending_manual_attestations'])==23
 assert rows(tmp_path,'v_evidence')==[]
 assert len(rows(tmp_path,'v_evidence_all'))==23

def test_competing_attributes_cross_product(dataset,tmp_path):
 def add(d):
  c=clone(d['claims'][3]);c['object']['value']=23;c['evidence'][0]['quote']='A competing documented specification gives caliber One 23 jewels.';d['claims'].append(c)
 change(dataset,'calibers/one.json',add)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0,(r.stdout,r.stderr)
 j=[r for r in rows(tmp_path,'v_lineage_diff') if r['attribute']=='jewels'];assert {r['before_value'] for r in j}=={'21','23'}
 assert report['disputed']==2

def test_identical_produced_bounds_are_not_disputed(dataset,tmp_path):
 change(dataset,'references/alpha.json',lambda d:d['claims'].append(clone(d['claims'][2])))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 assert report['disputed']==0

def test_unknown_years_no_overlap_and_null_diff(dataset,tmp_path):
 change(dataset,'references/alpha.json',lambda d:d['claims'][1]['valid_years'].update(**{'from':None,'from_evidence':None}))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 assert len(report['years_unknown'])==1
 assert len(rows(tmp_path,'v_lineage_diff'))==12
 assert all(r['changed'] is None for r in rows(tmp_path,'v_lineage_diff'))

def test_branch_reported_excluded_from_diffs(dataset,tmp_path):
 def add(d):
  c=clone(d['claims'][2]);c['object']['entity']='reference:gamma';d['claims'].append(c)
 change(dataset,'references/beta.json',add)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 assert report['branches']=={'reference:beta':['reference:alpha','reference:gamma']}
 assert rows(tmp_path,'v_lineage_diff')==[]

def test_alias_resolution_and_rename_warning(dataset,tmp_path):
 change(dataset,'calibers/one.json',lambda d:d.update(aliases=['caliber:old-one']))
 change(dataset,'references/alpha.json',lambda d:d['claims'][1]['object'].update(entity='caliber:old-one'))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==1
 assert report['warnings_by_class']=={'alias_used':1}
 assert rows(tmp_path,'v_reference_calibers')[0]['caliber_id']=='caliber:one'

def test_domain_cap_and_psl(dataset,tmp_path):
 assert domain('https://a.example.co.uk/x')=='example.co.uk'
 change(dataset,'sources/example.json',lambda d:d.update(reuse_class='cite_only',url='https://a.example.co.uk/specification'))
 def add(d):
  for _ in range(27):d['claims'].append(clone(d['claims'][0]))
 change(dataset,'calibers/one.json',add)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==2
 assert report['evidence_count']==50 and report['errors_by_class']['domain_cap']==1

def test_primary_filter_recomposes_graph(dataset,tmp_path):
 # Every use is primary but the family relation is secondary.
 source=json.loads((dataset/'sources/example.json').read_text());source.update(id='source:secondary',trust_tier='secondary');(dataset/'sources/secondary.json').write_text(json.dumps(source))
 for file in ['calibers/two.json','calibers/two-top.json']:
  def mutate(d):
   for c in d['claims']:
    if c['predicate'] in ['derived_from','grade_of']:
     for e in c['evidence']:e['source']='source:secondary'
  change(dataset,file,mutate)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 assert len(rows(tmp_path,'v_shared_dna'))==2
 assert all(r['has_primary']==0 for r in rows(tmp_path,'v_shared_dna'))
 for view in ['v_caliber_family','v_shared_dna']:
  q=cli('query',view,'--primary-only','--db',tmp_path/'graph.sqlite','--json');assert q.returncode==0,q.stderr;assert json.loads(q.stdout)==[]
 q=cli('query','v_reference_calibers','--primary-only','--include-proposed','--db',tmp_path/'graph.sqlite','--json');assert len(json.loads(q.stdout))==2

def test_grade_conflict_visible(dataset,tmp_path):
 # The same quote documents a competing grade name as a synthetic variant.
 p=dataset/'calibers/two-top.json';d=json.loads(p.read_text());c=clone(d['claims'][1]);c['object']['value']='Other';d['claims'].append(c);p.write_text(json.dumps(d))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 beta=[r for r in rows(tmp_path,'v_reference_calibers') if r['reference_id']=='reference:beta'];assert {r['grade'] for r in beta}=={'Top','Other'}
 assert all(r['disputed']==1 for r in beta)

def test_unknown_upper_bound_stays_unknown(dataset,tmp_path):
 change(dataset,'references/alpha.json',lambda d:d['claims'][1]['valid_years'].update(to=None,to_evidence=None))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 alpha=next(r for r in rows(tmp_path,'v_lineage') if r['reference_id']=='reference:alpha');assert alpha['year_to'] is None and alpha['year_to_kind']=='unknown'

def test_targets_object_accepts_unseeded(dataset,tmp_path):
 target=dataset/'targets/example.json';target.write_text(json.dumps({'schema_version':1,'line':'line:example','source':'source:example','references':['reference:alpha','reference:unseeded']}))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 assert report['coverage']['line:example']=={'target':2,'covered':1,'missing':['reference:unseeded']}

def test_exact_view_columns(dataset,tmp_path):
 expected={
 'v_reference_calibers':'reference_id caliber_id grade year_from year_to year_to_kind year_from_sort claim_id status disputed contested has_primary',
 'v_caliber_family':'caliber_id related_id relation_path depth',
 'v_shared_dna':'reference_id other_reference_id via_caliber_id relation_path disputed has_primary',
 'v_lineage':'line_id reference_id year_from year_to year_to_kind year_from_sort caliber_id grade succeeds_reference_id claim_id status disputed contested has_primary',
 'v_lineage_diff':'line_id reference_id predecessor_id attribute before_value after_value changed before_status after_status before_evidence_id after_evidence_id',
 'v_evidence':'claim_id evidence_id source_id tier match_mode quote locator archive_url retrieved_at'}
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 import sqlite3
 with sqlite3.connect(tmp_path/'graph.sqlite') as db:
  for view,cols in expected.items():
   for suffix in ['','_all']:assert [c[1] for c in db.execute(f'PRAGMA table_info({view+suffix})')]==cols.split()

def test_family_cycle_shortest_paths_and_depth_cap(dataset,tmp_path):
 # Construct a documented synthetic chain using the existing synthetic excerpt.
 template=json.loads((dataset/'calibers/two.json').read_text())
 for i in range(8):
  doc=copy.deepcopy(template);doc.update(id=f'caliber:chain-{i}',display_name=f'Chain {i}',claims=[])
  if i:
   c=clone(template['claims'][1]);c['object']['entity']=f'caliber:chain-{i-1}';doc['claims'].append(c)
  (dataset/f'calibers/chain-{i}.json').write_text(json.dumps(doc))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 family=rows(tmp_path,'v_caliber_family');assert max(x['depth'] for x in family)==6
 assert not any(x['caliber_id']=='caliber:chain-0' and x['related_id']=='caliber:chain-7' for x in family)
 assert set(report['family_truncated'])=={'caliber:chain-0','caliber:chain-7'}
 # Cycles in caliber family graphs are allowed and bounded by the visited path.
 def loop(d):
  c=clone(template['claims'][1]);c['object']['entity']='caliber:chain-7';d['claims'].append(c)
 change(dataset,'calibers/chain-0.json',loop)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 family=rows(tmp_path,'v_caliber_family');pairs=[(x['caliber_id'],x['related_id']) for x in family];assert len(pairs)==len(set(pairs))
 assert next(x['depth'] for x in family if x['caliber_id']=='caliber:chain-0' and x['related_id']=='caliber:chain-7')==1
 assert report['family_truncated']==[]

def test_primary_filter_does_not_hide_a_branch(dataset,tmp_path):
 source=json.loads((dataset/'sources/example.json').read_text());source.update(id='source:secondary',trust_tier='secondary');(dataset/'sources/secondary.json').write_text(json.dumps(source))
 def add(d):
  c=clone(d['claims'][2]);c['object']['entity']='reference:gamma';c['evidence'][0]['source']='source:secondary';d['claims'].append(c)
 change(dataset,'references/beta.json',add)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 q=cli('query','v_lineage_diff','--primary-only','--db',tmp_path/'graph.sqlite','--json');assert q.returncode==0
 assert json.loads(q.stdout)==[]

def test_verified_scan_agent_attestation_rejected(dataset,tmp_path):
 # Policy cannot authenticate arbitrary reviewers, but known worker/agent identities
 # must not set scan evidence verified.
 change(dataset,'sources/example.json',lambda d:d.update(content_type='image_scan'))
 for file in dataset.glob('*/*.json'):
  if file.parent.name in ['sources','targets']:continue
  def manual(d):
   for c in d['claims']:
    c['review']['by']='w-timecheck-fixture'
    for e in c['evidence']:e['match_mode']='manual'
  change(dataset,file.relative_to(dataset),manual)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==2
 assert report['errors_by_class']['manual_attestation_required']==23

def test_offline_hash_cache(dataset,tmp_path):
 import shutil
 cache=tmp_path/'cache';shutil.copytree(SNAPSHOTS,cache)
 r=cli('build','--data-dir',dataset,'--cache-dir',cache,'--offline','--strict','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');assert r.returncode==0
 next(cache.iterdir()).write_bytes(b'bad cached bytes')
 r=cli('build','--data-dir',dataset,'--cache-dir',cache,'--offline','--strict','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');assert r.returncode==2
 assert json.loads((tmp_path/'report.json').read_text())['errors_by_class']['snapshot_hash_mismatch']==23
 # Failed builds preserve the last successful database.
 assert len(rows(tmp_path,'v_reference_calibers'))==2

def test_wikipedia_policy(dataset,tmp_path):
 change(dataset,'sources/example.json',lambda d:d.update(url='https://en.wikipedia.org/w/index.php?oldid=123',licence='CC BY-SA 4.0'))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 change(dataset,'sources/example.json',lambda d:d.update(url='https://en.wikipedia.org/wiki/Example'))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==2
 assert report['errors_by_class']['wikipedia_policy']==23

def test_missing_data_dir_is_error(tmp_path):
 r=cli('build','--data-dir',tmp_path/'absent','--offline','--strict','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');assert r.returncode==2
 assert json.loads((tmp_path/'report.json').read_text())['errors_by_class']=={'data_unavailable':1}

def test_contested_grade_absence_visible(dataset,tmp_path):
 change(dataset,'calibers/one.json',lambda d:d['claims'][1].update(contested=True))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 alpha=next(r for r in rows(tmp_path,'v_reference_calibers') if r['reference_id']=='reference:alpha');assert alpha['grade']=='none' and alpha['contested']==1

def test_competing_grade_offer_booleans_visible(dataset,tmp_path):
 def add(d):
  c=clone(d['claims'][1]);c['object']['value']=True;d['claims'].append(c)
 change(dataset,'calibers/one.json',add)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0
 alpha=[r for r in rows(tmp_path,'v_reference_calibers') if r['reference_id']=='reference:alpha'];assert {r['grade'] for r in alpha}=={'none','unknown'}
 assert all(r['disputed']==1 for r in alpha)

def test_no_evidence_structural_build_marks_every_item_unchecked(dataset,tmp_path):
 # A wrong quote cannot pass strict evidence checking but structural checking is
 # explicit and must record that the bytes/quote were not verified.
 change(dataset,'references/alpha.json',lambda d:d['claims'][1]['evidence'][0].update(quote='This synthetic quote is absent from the pinned archive.'))
 r=cli('build','--data-dir',dataset,'--no-evidence','--strict','--offline','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json')
 assert r.returncode==0,(r.stdout,r.stderr)
 report=json.loads((tmp_path/'report.json').read_text())
 assert len(report['evidence_verification'])==23
 assert set(report['evidence_verification'].values())=={'unchecked'}
 assert len(rows(tmp_path,'v_reference_calibers'))==2
 change(dataset,'references/alpha.json',lambda d:d['claims'][1]['object'].update(entity='caliber:missing'))
 r=cli('build','--data-dir',dataset,'--no-evidence','--strict','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');assert r.returncode==2
 assert json.loads((tmp_path/'report.json').read_text())['errors_by_class']['unresolved_slug']==1

def test_all_proposed_lineage_builds_without_verified_line_membership(dataset,tmp_path):
 for file in dataset.glob('*/*.json'):
  if file.parent.name in ['sources','targets']:continue
  def propose(d):
   for c in d['claims']:
    c['status']='proposed';c.pop('review',None)
  change(dataset,file.relative_to(dataset),propose)
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==0,(r.stdout,r.stderr)
 assert report['claim_counts']['status']=={'proposed':23}
 assert report['coverage']['line:example']['covered']==0
 assert rows(tmp_path,'v_reference_calibers')==[]
 assert len(rows(tmp_path,'v_reference_calibers_all'))==2
 lineage=rows(tmp_path,'v_lineage_all')
 beta=next(r for r in lineage if r['reference_id']=='reference:beta')
 assert beta['line_id']=='line:example' and beta['succeeds_reference_id']=='reference:alpha'
 # Both variants retain the rule that diffs need verified succession edges.
 assert rows(tmp_path,'v_lineage_diff')==[] and rows(tmp_path,'v_lineage_diff_all')==[]
 change(dataset,'references/alpha.json',lambda d:d['claims'][0]['object'].update(entity='line:different'))
 line=json.loads((dataset/'lines/example.json').read_text());line.update(id='line:different',claims=[])
 (dataset/'lines/different.json').write_text(json.dumps(line))
 r,report=build(dataset,tmp_path,'--strict');assert r.returncode==2
 assert report['errors_by_class']['succeeds_line']==1

@pytest.mark.parametrize('view',['v_lineage','v_lineage_all'])
def test_produced_fallback_retains_conflict_review_and_source_flags(dataset,tmp_path,view):
 # Append a second synthetic statement so both competing year claims have a real
 # matching quote, and give that statement secondary evidence.
 raw=next(SNAPSHOTS.iterdir()).read_bytes()+b'<p>Gamma was produced from 1997 to 1999.</p>'
 sha=hashlib.sha256(raw).hexdigest();snapshots=tmp_path/'snapshots';snapshots.mkdir();(snapshots/(sha+'.bin')).write_bytes(raw)
 change(dataset,'sources/example.json',lambda d:d.update(snapshot_sha256=sha))
 secondary=json.loads((dataset/'sources/example.json').read_text());secondary.update(id='source:secondary',trust_tier='secondary')
 (dataset/'sources/secondary.json').write_text(json.dumps(secondary))
 def conflict(d):
  c=clone(d['claims'][1]);c['object']['years']['from']=1997;c['contested']=True
  c['evidence'][0].update(source='source:secondary',quote='Gamma was produced from 1997 to 1999.');d['claims'].append(c)
 change(dataset,'references/gamma.json',conflict)
 result=cli('build','--data-dir',dataset,'--snapshot-dir',snapshots,'--strict','--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json');assert result.returncode==0,(result.stdout,result.stderr)
 report=json.loads((tmp_path/'report.json').read_text());assert report['disputed']==2
 gamma=[r for r in rows(tmp_path,view) if r['reference_id']=='reference:gamma']
 assert len(gamma)==2
 assert all(r['disputed']==1 for r in gamma)
 assert {(r['year_from'],r['contested'],r['has_primary']) for r in gamma}=={(1998,0,1),(1997,1,0)}

@pytest.mark.parametrize('predicate,quote',[
 ('hacking','This caliber has no hacking problems and the hacking function works correctly.'),
 ('offers_grades','There are no grade differences in dimensions; all three grades use the same casing.')])
def test_absence_negation_of_another_concept_rejected(dataset,tmp_path,predicate,quote):
 def replace(d):
  c=next(c for c in d['claims'] if c['predicate']==predicate)
  c['evidence'][0]['quote']=quote
 change(dataset,'calibers/one.json',replace)
 # Structural mode isolates the absence validator while exercising the real CLI.
 result,report=build(dataset,tmp_path,'--strict','--no-evidence')
 assert result.returncode==2,(result.stdout,result.stderr)
 assert report['errors_by_class']=={'explicit_absence_required':1}

@pytest.mark.parametrize('strict,code',[(True,2),(False,1)])
@pytest.mark.parametrize('raw',[
 b'\x1f\x8b\x08\x00'+b'\x00'*6+b'\xff'*16,
 b'\x1f\x8b\x07\x00'+b'\x00'*6+b'\x00'*16,
 b'\x1f\x8b\x08\x00'])
def test_corrupt_gzip_reports_decode_failure_without_traceback(dataset,tmp_path,strict,code,raw):
 sha=hashlib.sha256(raw).hexdigest();snapshots=tmp_path/'snapshots';snapshots.mkdir();(snapshots/(sha+'.bin')).write_bytes(raw)
 change(dataset,'sources/example.json',lambda d:d.update(snapshot_sha256=sha))
 flags=['--strict'] if strict else []
 result=cli('build','--data-dir',dataset,'--snapshot-dir',snapshots,'--out',tmp_path/'graph.sqlite','--report',tmp_path/'report.json',*flags)
 assert result.returncode==code,(result.stdout,result.stderr)
 assert 'Traceback' not in result.stderr
 report=json.loads((tmp_path/'report.json').read_text())
 problems=report['errors'] if strict else report['warnings']
 assert len(problems)==23 and {p['class'] for p in problems}=={'snapshot_unavailable'}
 assert all('decode' in p['message'].lower() for p in problems)

@pytest.mark.parametrize('predicate,phrase',[
 ('hacking','has no hacking.'),('hacking','is without any hacking;'),
 ('hacking','is non-hacking.'),('hacking','does not have hacking.'),
 ('hacking','does not hack.'),('hacking','Hacking is not available.'),
 ('hacking','Hacking absent.'),('hacking','Hacking unavailable.'),
 ('offers_grades','offers no grades.'),('offers_grades','does not offer any grades.'),
 ('offers_grades','Grades are not offered.'),('offers_grades','Grades unavailable.'),
 ('offers_grades','has a single grade.'),('offers_grades','has one grade only.'),
 ('offers_grades','There are no grades offered.')])
def test_explicit_absence_supported_forms(dataset,tmp_path,predicate,phrase):
 def replace(d):
  c=next(c for c in d['claims'] if c['predicate']==predicate)
  c['evidence'][0]['quote']='Synthetic documentation: '+phrase
 change(dataset,'calibers/one.json',replace)
 result,report=build(dataset,tmp_path,'--strict','--no-evidence')
 assert result.returncode==0,(result.stdout,result.stderr,report['errors'])
