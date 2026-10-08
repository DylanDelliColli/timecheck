"""Unit coverage of transport failures. Matcher, extraction and hashing remain real.
The network boundary alone is replaced so the suite needs no external network.
"""
from email.message import Message
import hashlib
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from timecheck.evidence import verify_evidence


class Response(BytesIO):
 def __init__(self,raw,charset=None):
  super().__init__(raw);self.headers=Message()
  if charset:self.headers['Content-Type']='text/plain; charset='+charset


def inputs(raw):
 source={'content_type':'text','archive_url':'https://web.archive.org/web/20261008120000id_/https://example.org','snapshot_sha256':hashlib.sha256(raw).hexdigest()}
 claim={'id':'clm-aaaaaaaaaa','path':'fixture.json','evidence':[{'id':'ev-aaaaaaaaaa','source':'source:example','match_mode':'exact','quote':'The synthetic specification gives café automatic winding.'}]}
 return [claim],{'source:example':source}


def test_fetch_retries_and_hash_before_matching(monkeypatch):
 raw='The synthetic specification gives café automatic winding.'.encode('cp1252');claims,sources=inputs(raw)
 attempts=[];delays=[]
 def fetch(request,timeout):
  attempts.append((request.full_url,timeout))
  if len(attempts)<3:raise URLError('synthetic transient failure')
  return Response(raw,'cp1252')
 monkeypatch.setattr('timecheck.evidence.urlopen',fetch)
 monkeypatch.setattr('timecheck.evidence.time.sleep',delays.append)
 assert verify_evidence(claims,sources,strict=True)==([],[])
 assert len(attempts)==3 and delays==[1,2]


def test_exhausted_fetch_is_warning_or_strict_error(monkeypatch):
 claims,sources=inputs(b'unavailable');attempts=[];delays=[]
 def fetch(*args,**kwargs):attempts.append(1);raise URLError('unavailable')
 monkeypatch.setattr('timecheck.evidence.urlopen',fetch)
 monkeypatch.setattr('timecheck.evidence.time.sleep',delays.append)
 errors,warnings=verify_evidence(claims,sources);assert not errors and warnings[0]['class']=='snapshot_unavailable'
 assert len(attempts)==4 and delays==[1,2,4]
 errors,warnings=verify_evidence(claims,sources,strict=True);assert not warnings and errors[0]['class']=='snapshot_unavailable'


def test_cached_response_preserves_header_charset(monkeypatch,tmp_path):
 raw='The synthetic specification gives café automatic winding.'.encode('cp1252');claims,sources=inputs(raw)
 monkeypatch.setattr('timecheck.evidence.urlopen',lambda *a,**k:Response(raw,'cp1252'))
 assert verify_evidence(claims,sources,cache_dir=tmp_path,strict=True)==([],[])
 assert verify_evidence(claims,sources,cache_dir=tmp_path,offline=True,strict=True)==([],[])


def test_hash_mismatch_before_decompression(monkeypatch):
 claims,sources=inputs(b'the correct bytes')
 monkeypatch.setattr('timecheck.evidence.urlopen',lambda *a,**k:Response(b'\x1f\x8binvalid gzip'))
 errors,warnings=verify_evidence(claims,sources,strict=True)
 assert errors[0]['class']=='snapshot_hash_mismatch' and not warnings
