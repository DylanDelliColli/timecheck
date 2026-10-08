import re
import pytest
from timecheck.normalize import normalize
from timecheck.extract import extract
from timecheck.ids import new_id
from timecheck.build import parse_years, compute_disputed

@pytest.mark.parametrize('raw,want',[
 ('  A\n B\tC  ','A B C'),('ＡＢＣ\u00ad “top”—it’s\u2212ok','ABC "top"-it\'s-ok'),
 ('Case Sensitive','Case Sensitive'),('a\u00a0b','a b'),('a‐b‑c‒d–e—f―g','a-b-c-d-e-f-g')])
def test_normalization(raw,want): assert normalize(raw)==want

@pytest.mark.parametrize('raw,kind,charset,want',[
 (b'<p>A &amp; B</p><p>C</p>','html',None,'A & B C'),
 (b'<div>good<script>bad</script><style>bad</style><noscript>bad</noscript><template><p>bad</p></template>end</div>','html',None,'goodend'),
 (b'<meta charset="windows-1252"><p>caf\xe9</p>','html',None,'caf\xe9'),
 (b'<meta charset="utf-8"><p>caf\xe9</p>','html','windows-1252','caf\xe9'),
 (b'A\xff B','text',None,'A\ufffd B'),(b'A\n B','text',None,'A B')])
def test_extraction(raw,kind,charset,want): assert extract(raw,kind,charset)==want

def test_ids():
 for kind,prefix in [('claim','clm'),('evidence','ev')]:
  minted={new_id(kind) for _ in range(1000)}
  assert len(minted)==1000
  assert all(re.fullmatch(prefix+r'-[a-z2-7]{10}',s) for s in minted)

@pytest.mark.parametrize('value,want',[(None,(None,None,'unknown',9999)),({'from':2000,'to':2005},(2000,2005,'year',2000)),({'from':None,'to':'present'},(None,None,'present',9999))])
def test_years(value,want): assert parse_years(value)==want

def test_disputes():
 def c(i,p,o,y=None,s='verified'):return {'id':i,'subject':'caliber:a','predicate':p,'object':o,'valid_years':y,'status':s,'contested':False}
 assert compute_disputed([c('a','jewels',{'value':21}),c('b','jewels',{'value':23})])=={'a','b'}
 assert compute_disputed([c('a','jewels',{'value':21}),c('b','jewels',{'value':21})])==set()
 assert compute_disputed([c('a','jewels',{'value':21}),c('b','jewels',{'value':23},s='proposed')])==set()
 assert compute_disputed([c('a','uses_caliber',{'entity':'caliber:a'},{'from':2000,'to':2005}),c('b','uses_caliber',{'entity':'caliber:b'},{'from':2005,'to':'present'})])=={'a','b'}
 assert compute_disputed([c('a','uses_caliber',{'entity':'caliber:a'},{'from':None,'to':2005}),c('b','uses_caliber',{'entity':'caliber:b'},{'from':2000,'to':2010})])==set()

def test_normalization_contract_operation_order():
 # Collapse whitespace precedes stripping soft hyphens in norm_version 1.
 assert normalize('a \u00ad b')=='a  b'
