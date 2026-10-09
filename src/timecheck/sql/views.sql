CREATE VIEW selected_claim AS SELECT c.*, o.entity_id, o.value, o.unit,
 y.year_from, y.year_to, COALESCE(y.year_to_kind,'unknown') AS year_to_kind,
 COALESCE(y.year_from_sort,9999) AS year_from_sort
 FROM claim c JOIN claim_object o ON o.claim_id=c.id
 LEFT JOIN claim_years y ON y.claim_id=c.id WHERE c.status = 'verified';

CREATE VIEW grade_facts AS
 SELECT subject_id,predicate,entity_id,value,
 CASE WHEN MAX(status='verified') THEN 'verified' ELSE 'proposed' END AS status,
 MAX(disputed) AS disputed,MAX(contested) AS contested,
 CASE WHEN MAX(status='verified') THEN MAX(CASE WHEN status='verified' THEN has_primary END)
 ELSE MAX(has_primary) END AS has_primary
 FROM selected_claim WHERE predicate IN ('grade_of','grade_name','offers_grades')
 GROUP BY subject_id,predicate,entity_id,value;

CREATE VIEW grade_metadata AS
 SELECT subject_id,MAX(predicate='grade_of') AS is_grade,
 CASE WHEN COUNT(DISTINCT CASE WHEN predicate='grade_name' THEN value END)=1
 THEN MAX(CASE WHEN predicate='grade_name' THEN value END) ELSE 'unknown' END AS grade_name,
 MAX(predicate='offers_grades' AND status='verified' AND value='false') AS has_no_grades,
 MAX(disputed) AS disputed,MAX(contested) AS contested,MIN(has_primary) AS has_primary
 FROM grade_facts GROUP BY subject_id;

CREATE VIEW v_reference_calibers AS
 SELECT u.subject_id AS reference_id,u.entity_id AS caliber_id,
 CASE WHEN gm.is_grade=1 THEN gm.grade_name
 WHEN gm.has_no_grades=1 THEN 'none' ELSE 'unknown' END AS grade,
 u.year_from,u.year_to,u.year_to_kind,u.year_from_sort,u.id AS claim_id,u.status,
 MAX(u.disputed,COALESCE(gm.disputed,0)) AS disputed,
 MAX(u.contested,COALESCE(gm.contested,0)) AS contested,
 MIN(u.has_primary,COALESCE(gm.has_primary,1)) AS has_primary
 FROM selected_claim u LEFT JOIN grade_metadata gm ON gm.subject_id=u.entity_id
 WHERE u.predicate='uses_caliber';

CREATE VIEW family_paths AS
 WITH RECURSIVE edges(a,b,kind,primary_flag,disputed_flag) AS (
 SELECT subject_id,entity_id,predicate,has_primary,disputed FROM selected_claim WHERE predicate IN ('derived_from','clone_of','grade_of')
 UNION SELECT entity_id,subject_id,predicate,has_primary,disputed FROM selected_claim WHERE predicate IN ('derived_from','clone_of','grade_of')
 ), walk(caliber_id,related_id,relation_path,depth,visited,has_primary,disputed) AS (
 SELECT id,id,'',0,'|' || id || '|',1,0 FROM caliber
 UNION ALL SELECT w.caliber_id,e.b,CASE WHEN w.depth=0 THEN e.kind ELSE w.relation_path || ',' || e.kind END,
 w.depth+1,w.visited || e.b || '|',MIN(w.has_primary,e.primary_flag),MAX(w.disputed,e.disputed_flag)
 FROM walk w JOIN edges e ON e.a=w.related_id WHERE w.depth<6 AND instr(w.visited,'|' || e.b || '|')=0)
 SELECT * FROM walk;

CREATE VIEW v_caliber_family AS
 WITH ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY caliber_id,related_id ORDER BY depth,relation_path) AS n
 FROM family_paths WHERE depth>0)
 SELECT caliber_id,related_id,relation_path,depth FROM ranked WHERE n=1;

CREATE VIEW v_shared_dna AS
 WITH connections(a,b,path,has_primary,disputed) AS (
 SELECT id,id,'',1,0 FROM caliber UNION ALL
 SELECT f.caliber_id,f.related_id,f.relation_path,MAX(p.has_primary),MAX(p.disputed)
 FROM v_caliber_family f JOIN family_paths p
 ON p.caliber_id=f.caliber_id AND p.related_id=f.related_id AND p.relation_path=f.relation_path AND p.depth=f.depth
 GROUP BY f.caliber_id,f.related_id,f.relation_path)
 SELECT DISTINCT u.reference_id,v.reference_id AS other_reference_id,u.caliber_id AS via_caliber_id,
 f.path AS relation_path,MAX(u.disputed,v.disputed,f.disputed) AS disputed,MIN(u.has_primary,v.has_primary,f.has_primary) AS has_primary
 FROM v_reference_calibers u JOIN connections f ON f.a=u.caliber_id
 JOIN v_reference_calibers v ON v.caliber_id=f.b WHERE u.reference_id<>v.reference_id;

CREATE VIEW membership AS
 SELECT subject_id,CASE WHEN COUNT(DISTINCT entity_id)=1 THEN MIN(entity_id) ELSE NULL END AS entity_id,
 COALESCE(MIN(CASE WHEN status='verified' THEN id END),MIN(id)) AS id,
 CASE WHEN MAX(status='verified') THEN 'verified' ELSE 'proposed' END AS status,
 MAX(disputed) AS disputed,MAX(contested) AS contested,MAX(has_primary) AS has_primary
 FROM selected_claim WHERE predicate='in_line' GROUP BY subject_id;

-- Keep a usage interval intact when either bound is known. Production is a
-- fallback for wholly unknown usage, with its own claim id for year provenance.
CREATE VIEW lineage_years AS
 SELECT r.id AS reference_id,u.caliber_id,u.grade,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN u.year_from ELSE p.year_from END AS year_from,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN u.year_to ELSE p.year_to END AS year_to,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN u.year_to_kind ELSE COALESCE(p.year_to_kind,'unknown') END AS year_to_kind,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN u.year_from_sort ELSE COALESCE(p.year_from_sort,9999) END AS year_from_sort,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN 'usage'
 WHEN p.year_from IS NOT NULL OR p.year_to_kind<>'unknown' THEN 'produced' ELSE 'unknown' END AS year_source,
 COALESCE(u.claim_id,p.id) AS claim_id,COALESCE(p.id,u.claim_id) AS years_claim_id,
 COALESCE(u.status,p.status) AS status,
 MAX(COALESCE(u.disputed,0),COALESCE(p.disputed,0)) AS disputed,
 MAX(COALESCE(u.contested,0),COALESCE(p.contested,0)) AS contested,
 MIN(COALESCE(u.has_primary,1),COALESCE(p.has_primary,1)) AS has_primary
 FROM reference r LEFT JOIN v_reference_calibers u ON u.reference_id=r.id
 LEFT JOIN selected_claim p ON p.subject_id=r.id AND p.predicate='produced'
 AND (u.claim_id IS NULL OR (u.year_from IS NULL AND u.year_to_kind='unknown'));

CREATE VIEW v_lineage AS
 WITH verified_predecessors AS (
 SELECT c.subject_id,COUNT(DISTINCT o.entity_id) AS predecessor_count
 FROM claim c JOIN claim_object o ON o.claim_id=c.id
 WHERE c.predicate='succeeds' AND c.status='verified' GROUP BY c.subject_id
 ), succession AS (
 SELECT s.subject_id,
 CASE WHEN COALESCE(v.predecessor_count,0)>1 THEN NULL
 WHEN COUNT(DISTINCT CASE WHEN s.status='verified' THEN s.entity_id END)=1
 THEN MAX(CASE WHEN s.status='verified' THEN s.entity_id END)
 WHEN COALESCE(v.predecessor_count,0)=0 AND COUNT(DISTINCT s.entity_id)=1 THEN MAX(s.entity_id)
 ELSE NULL END AS entity_id,
 MAX(s.disputed) AS disputed,MAX(s.contested) AS contested,
 CASE WHEN COUNT(DISTINCT CASE WHEN s.status='verified' THEN s.entity_id END)=1
 THEN MAX(CASE WHEN s.status='verified' THEN s.has_primary END)
 WHEN COUNT(DISTINCT s.entity_id)=1 THEN MAX(s.has_primary) ELSE MIN(s.has_primary) END AS has_primary
 FROM selected_claim s LEFT JOIN verified_predecessors v ON v.subject_id=s.subject_id
 WHERE s.predicate='succeeds' GROUP BY s.subject_id,v.predecessor_count
 )
 SELECT l.entity_id AS line_id,r.id AS reference_id,
 u.year_from,u.year_to,u.year_to_kind,u.year_from_sort,u.year_source,
 u.caliber_id,u.grade,s.entity_id AS succeeds_reference_id,COALESCE(u.claim_id,l.id) AS claim_id,
 COALESCE(u.status,l.status,'verified') AS status,
 MAX(u.disputed,COALESCE(l.disputed,0),COALESCE(s.disputed,0)) AS disputed,
 MAX(u.contested,COALESCE(l.contested,0),COALESCE(s.contested,0)) AS contested,
 MIN(u.has_primary,COALESCE(l.has_primary,0),COALESCE(s.has_primary,1)) AS has_primary
 FROM reference r LEFT JOIN membership l ON l.subject_id=r.id
 JOIN lineage_years u ON u.reference_id=r.id
 LEFT JOIN succession s ON s.subject_id=r.id;

CREATE VIEW v_lineage_diff AS
 WITH attrs(attribute) AS (VALUES ('caliber'),('offers_grades'),('grade_name'),('winding'),('beat_rate'),('jewels'),('power_reserve'),('hacking'),('date_mechanism'),('introduced'),('discontinued'),('years')),
 edges AS (SELECT DISTINCT s.subject_id AS reference_id,s.entity_id AS predecessor_id,l.entity_id AS line_id
 FROM selected_claim s JOIN membership l ON l.subject_id=s.subject_id
 WHERE s.predicate='succeeds' AND s.status='verified'
 AND (SELECT COUNT(DISTINCT bo.entity_id) FROM claim b JOIN claim_object bo ON bo.claim_id=b.id WHERE b.subject_id=s.subject_id AND b.predicate='succeeds' AND b.status='verified')=1),
 usage AS (SELECT * FROM lineage_years WHERE caliber_id IS NOT NULL),
 -- Production dates describe the reference, never the order of its calibers.
 -- Count distinct calibers so duplicate claims do not create a start-year tie.
 tied_starts AS (SELECT reference_id FROM usage GROUP BY reference_id,year_from
 HAVING COUNT(DISTINCT caliber_id)>1),
 ordering AS (SELECT reference_id,COUNT(DISTINCT caliber_id) AS caliber_count,
 MAX(year_source<>'usage' OR year_from IS NULL) AS unknown_start,MIN(year_from) AS earliest,MAX(year_from) AS latest
 FROM usage GROUP BY reference_id),
 unknown_edges AS (SELECT e.* FROM edges e
 LEFT JOIN ordering b ON b.reference_id=e.predecessor_id
 LEFT JOIN ordering a ON a.reference_id=e.reference_id
 WHERE b.caliber_count IS NULL OR a.caliber_count IS NULL
 OR (b.caliber_count>1 AND b.unknown_start=1) OR (a.caliber_count>1 AND a.unknown_start=1)
 OR e.predecessor_id IN (SELECT reference_id FROM tied_starts)
 OR e.reference_id IN (SELECT reference_id FROM tied_starts)),
 pairs AS (SELECT e.*,b.caliber_id AS before_caliber,a.caliber_id AS after_caliber,
 b.claim_id AS before_claim,a.claim_id AS after_claim,
 b.years_claim_id AS before_years_claim,a.years_claim_id AS after_years_claim,
 COALESCE(CAST(b.year_from AS TEXT),'unknown') || '-' || COALESCE(CAST(b.year_to AS TEXT),b.year_to_kind) AS byears,
 COALESCE(CAST(a.year_from AS TEXT),'unknown') || '-' || COALESCE(CAST(a.year_to AS TEXT),a.year_to_kind) AS ayears
 FROM edges e JOIN usage b ON b.reference_id=e.predecessor_id
 JOIN usage a ON a.reference_id=e.reference_id
 JOIN ordering bo ON bo.reference_id=e.predecessor_id
 JOIN ordering ao ON ao.reference_id=e.reference_id
 WHERE NOT EXISTS(SELECT 1 FROM unknown_edges u WHERE u.reference_id=e.reference_id AND u.predecessor_id=e.predecessor_id)
 AND (b.year_from=bo.latest OR (bo.caliber_count=1 AND bo.latest IS NULL))
 AND (a.year_from=ao.earliest OR (ao.caliber_count=1 AND ao.earliest IS NULL))),
 compared AS (SELECT p.line_id,p.reference_id,p.predecessor_id,t.attribute,
 CASE t.attribute WHEN 'caliber' THEN p.before_caliber WHEN 'years' THEN p.byears ELSE b.value END AS before_value,
 CASE t.attribute WHEN 'caliber' THEN p.after_caliber WHEN 'years' THEN p.ayears ELSE a.value END AS after_value,
 CASE t.attribute WHEN 'caliber' THEN p.before_claim WHEN 'years' THEN p.before_years_claim ELSE b.id END AS before_claim_id,
 CASE t.attribute WHEN 'caliber' THEN p.after_claim WHEN 'years' THEN p.after_years_claim ELSE a.id END AS after_claim_id
 FROM pairs p CROSS JOIN attrs t LEFT JOIN selected_claim b ON b.subject_id=p.before_caliber AND b.predicate=t.attribute
 LEFT JOIN selected_claim a ON a.subject_id=p.after_caliber AND a.predicate=t.attribute)
, representatives AS (
 SELECT line_id,reference_id,predecessor_id,attribute,before_value,after_value,
 MIN(before_claim_id) AS before_claim_id,MIN(after_claim_id) AS after_claim_id
 FROM compared GROUP BY line_id,reference_id,predecessor_id,attribute,before_value,after_value)
 SELECT line_id,reference_id,predecessor_id,attribute,before_value,after_value,
 CASE WHEN before_value IS NULL OR after_value IS NULL THEN NULL ELSE before_value<>after_value END AS changed,
 (SELECT status FROM claim WHERE id=before_claim_id) AS before_status,
 (SELECT status FROM claim WHERE id=after_claim_id) AS after_status,
 (SELECT MIN(id) FROM evidence WHERE claim_id=before_claim_id) AS before_evidence_id,
 (SELECT MIN(id) FROM evidence WHERE claim_id=after_claim_id) AS after_evidence_id FROM representatives
 UNION ALL SELECT u.line_id,u.reference_id,u.predecessor_id,t.attribute,NULL,NULL,NULL,NULL,NULL,NULL,NULL FROM unknown_edges u CROSS JOIN attrs t;

CREATE VIEW v_evidence AS SELECT c.id AS claim_id,e.id AS evidence_id,s.id AS source_id,s.trust_tier AS tier,e.match_mode,e.quote,e.locator,s.archive_url,s.retrieved_at
 FROM selected_claim c JOIN evidence e ON e.claim_id=c.id JOIN source s ON s.id=e.source_id;

CREATE VIEW selected_claim_all AS SELECT c.*, o.entity_id, o.value, o.unit,
 y.year_from, y.year_to, COALESCE(y.year_to_kind,'unknown') AS year_to_kind,
 COALESCE(y.year_from_sort,9999) AS year_from_sort
 FROM claim c JOIN claim_object o ON o.claim_id=c.id
 LEFT JOIN claim_years y ON y.claim_id=c.id ;

CREATE VIEW grade_facts_all AS
 SELECT subject_id,predicate,entity_id,value,
 CASE WHEN MAX(status='verified') THEN 'verified' ELSE 'proposed' END AS status,
 MAX(disputed) AS disputed,MAX(contested) AS contested,
 CASE WHEN MAX(status='verified') THEN MAX(CASE WHEN status='verified' THEN has_primary END)
 ELSE MAX(has_primary) END AS has_primary
 FROM selected_claim_all WHERE predicate IN ('grade_of','grade_name','offers_grades')
 GROUP BY subject_id,predicate,entity_id,value;

CREATE VIEW grade_metadata_all AS
 SELECT subject_id,MAX(predicate='grade_of') AS is_grade,
 CASE WHEN COUNT(DISTINCT CASE WHEN predicate='grade_name' THEN value END)=1
 THEN MAX(CASE WHEN predicate='grade_name' THEN value END) ELSE 'unknown' END AS grade_name,
 MAX(predicate='offers_grades' AND status='verified' AND value='false') AS has_no_grades,
 MAX(disputed) AS disputed,MAX(contested) AS contested,MIN(has_primary) AS has_primary
 FROM grade_facts_all GROUP BY subject_id;

CREATE VIEW v_reference_calibers_all AS
 SELECT u.subject_id AS reference_id,u.entity_id AS caliber_id,
 CASE WHEN gm.is_grade=1 THEN gm.grade_name
 WHEN gm.has_no_grades=1 THEN 'none' ELSE 'unknown' END AS grade,
 u.year_from,u.year_to,u.year_to_kind,u.year_from_sort,u.id AS claim_id,u.status,
 MAX(u.disputed,COALESCE(gm.disputed,0)) AS disputed,
 MAX(u.contested,COALESCE(gm.contested,0)) AS contested,
 MIN(u.has_primary,COALESCE(gm.has_primary,1)) AS has_primary
 FROM selected_claim_all u LEFT JOIN grade_metadata_all gm ON gm.subject_id=u.entity_id
 WHERE u.predicate='uses_caliber';

CREATE VIEW family_paths_all AS
 WITH RECURSIVE edges(a,b,kind,primary_flag,disputed_flag) AS (
 SELECT subject_id,entity_id,predicate,has_primary,disputed FROM selected_claim_all WHERE predicate IN ('derived_from','clone_of','grade_of')
 UNION SELECT entity_id,subject_id,predicate,has_primary,disputed FROM selected_claim_all WHERE predicate IN ('derived_from','clone_of','grade_of')
 ), walk(caliber_id,related_id,relation_path,depth,visited,has_primary,disputed) AS (
 SELECT id,id,'',0,'|' || id || '|',1,0 FROM caliber
 UNION ALL SELECT w.caliber_id,e.b,CASE WHEN w.depth=0 THEN e.kind ELSE w.relation_path || ',' || e.kind END,
 w.depth+1,w.visited || e.b || '|',MIN(w.has_primary,e.primary_flag),MAX(w.disputed,e.disputed_flag)
 FROM walk w JOIN edges e ON e.a=w.related_id WHERE w.depth<6 AND instr(w.visited,'|' || e.b || '|')=0)
 SELECT * FROM walk;

CREATE VIEW v_caliber_family_all AS
 WITH ranked AS (SELECT *,ROW_NUMBER() OVER(PARTITION BY caliber_id,related_id ORDER BY depth,relation_path) AS n
 FROM family_paths_all WHERE depth>0)
 SELECT caliber_id,related_id,relation_path,depth FROM ranked WHERE n=1;

CREATE VIEW v_shared_dna_all AS
 WITH connections(a,b,path,has_primary,disputed) AS (
 SELECT id,id,'',1,0 FROM caliber UNION ALL
 SELECT f.caliber_id,f.related_id,f.relation_path,MAX(p.has_primary),MAX(p.disputed)
 FROM v_caliber_family_all f JOIN family_paths_all p
 ON p.caliber_id=f.caliber_id AND p.related_id=f.related_id AND p.relation_path=f.relation_path AND p.depth=f.depth
 GROUP BY f.caliber_id,f.related_id,f.relation_path)
 SELECT DISTINCT u.reference_id,v.reference_id AS other_reference_id,u.caliber_id AS via_caliber_id,
 f.path AS relation_path,MAX(u.disputed,v.disputed,f.disputed) AS disputed,MIN(u.has_primary,v.has_primary,f.has_primary) AS has_primary
 FROM v_reference_calibers_all u JOIN connections f ON f.a=u.caliber_id
 JOIN v_reference_calibers_all v ON v.caliber_id=f.b WHERE u.reference_id<>v.reference_id;

CREATE VIEW membership_all AS
 SELECT subject_id,CASE WHEN COUNT(DISTINCT entity_id)=1 THEN MIN(entity_id) ELSE NULL END AS entity_id,
 COALESCE(MIN(CASE WHEN status='verified' THEN id END),MIN(id)) AS id,
 CASE WHEN MAX(status='verified') THEN 'verified' ELSE 'proposed' END AS status,
 MAX(disputed) AS disputed,MAX(contested) AS contested,MAX(has_primary) AS has_primary
 FROM selected_claim_all WHERE predicate='in_line' GROUP BY subject_id;

-- Keep a usage interval intact when either bound is known. Production is a
-- fallback for wholly unknown usage, with its own claim id for year provenance.
CREATE VIEW lineage_years_all AS
 SELECT r.id AS reference_id,u.caliber_id,u.grade,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN u.year_from ELSE p.year_from END AS year_from,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN u.year_to ELSE p.year_to END AS year_to,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN u.year_to_kind ELSE COALESCE(p.year_to_kind,'unknown') END AS year_to_kind,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN u.year_from_sort ELSE COALESCE(p.year_from_sort,9999) END AS year_from_sort,
 CASE WHEN u.year_from IS NOT NULL OR u.year_to_kind<>'unknown' THEN 'usage'
 WHEN p.year_from IS NOT NULL OR p.year_to_kind<>'unknown' THEN 'produced' ELSE 'unknown' END AS year_source,
 COALESCE(u.claim_id,p.id) AS claim_id,COALESCE(p.id,u.claim_id) AS years_claim_id,
 COALESCE(u.status,p.status) AS status,
 MAX(COALESCE(u.disputed,0),COALESCE(p.disputed,0)) AS disputed,
 MAX(COALESCE(u.contested,0),COALESCE(p.contested,0)) AS contested,
 MIN(COALESCE(u.has_primary,1),COALESCE(p.has_primary,1)) AS has_primary
 FROM reference r LEFT JOIN v_reference_calibers_all u ON u.reference_id=r.id
 LEFT JOIN selected_claim_all p ON p.subject_id=r.id AND p.predicate='produced'
 AND (u.claim_id IS NULL OR (u.year_from IS NULL AND u.year_to_kind='unknown'));

CREATE VIEW v_lineage_all AS
 WITH verified_predecessors AS (
 SELECT c.subject_id,COUNT(DISTINCT o.entity_id) AS predecessor_count
 FROM claim c JOIN claim_object o ON o.claim_id=c.id
 WHERE c.predicate='succeeds' AND c.status='verified' GROUP BY c.subject_id
 ), succession AS (
 SELECT s.subject_id,
 CASE WHEN COALESCE(v.predecessor_count,0)>1 THEN NULL
 WHEN COUNT(DISTINCT CASE WHEN s.status='verified' THEN s.entity_id END)=1
 THEN MAX(CASE WHEN s.status='verified' THEN s.entity_id END)
 WHEN COALESCE(v.predecessor_count,0)=0 AND COUNT(DISTINCT s.entity_id)=1 THEN MAX(s.entity_id)
 ELSE NULL END AS entity_id,
 MAX(s.disputed) AS disputed,MAX(s.contested) AS contested,
 CASE WHEN COUNT(DISTINCT CASE WHEN s.status='verified' THEN s.entity_id END)=1
 THEN MAX(CASE WHEN s.status='verified' THEN s.has_primary END)
 WHEN COUNT(DISTINCT s.entity_id)=1 THEN MAX(s.has_primary) ELSE MIN(s.has_primary) END AS has_primary
 FROM selected_claim_all s LEFT JOIN verified_predecessors v ON v.subject_id=s.subject_id
 WHERE s.predicate='succeeds' GROUP BY s.subject_id,v.predecessor_count
 )
 SELECT l.entity_id AS line_id,r.id AS reference_id,
 u.year_from,u.year_to,u.year_to_kind,u.year_from_sort,u.year_source,
 u.caliber_id,u.grade,s.entity_id AS succeeds_reference_id,COALESCE(u.claim_id,l.id) AS claim_id,
 COALESCE(u.status,l.status,'verified') AS status,
 MAX(u.disputed,COALESCE(l.disputed,0),COALESCE(s.disputed,0)) AS disputed,
 MAX(u.contested,COALESCE(l.contested,0),COALESCE(s.contested,0)) AS contested,
 MIN(u.has_primary,COALESCE(l.has_primary,0),COALESCE(s.has_primary,1)) AS has_primary
 FROM reference r LEFT JOIN membership_all l ON l.subject_id=r.id
 JOIN lineage_years_all u ON u.reference_id=r.id
 LEFT JOIN succession s ON s.subject_id=r.id;

CREATE VIEW v_lineage_diff_all AS
 WITH attrs(attribute) AS (VALUES ('caliber'),('offers_grades'),('grade_name'),('winding'),('beat_rate'),('jewels'),('power_reserve'),('hacking'),('date_mechanism'),('introduced'),('discontinued'),('years')),
 edges AS (SELECT DISTINCT s.subject_id AS reference_id,s.entity_id AS predecessor_id,l.entity_id AS line_id
 FROM selected_claim_all s JOIN membership_all l ON l.subject_id=s.subject_id
 WHERE s.predicate='succeeds' AND s.status='verified'
 AND (SELECT COUNT(DISTINCT bo.entity_id) FROM claim b JOIN claim_object bo ON bo.claim_id=b.id WHERE b.subject_id=s.subject_id AND b.predicate='succeeds' AND b.status='verified')=1),
 usage AS (SELECT * FROM lineage_years_all WHERE caliber_id IS NOT NULL),
 -- Apply the same chronology rule when proposed claims are included.
 tied_starts AS (SELECT reference_id FROM usage GROUP BY reference_id,year_from
 HAVING COUNT(DISTINCT caliber_id)>1),
 ordering AS (SELECT reference_id,COUNT(DISTINCT caliber_id) AS caliber_count,
 MAX(year_source<>'usage' OR year_from IS NULL) AS unknown_start,MIN(year_from) AS earliest,MAX(year_from) AS latest
 FROM usage GROUP BY reference_id),
 unknown_edges AS (SELECT e.* FROM edges e
 LEFT JOIN ordering b ON b.reference_id=e.predecessor_id
 LEFT JOIN ordering a ON a.reference_id=e.reference_id
 WHERE b.caliber_count IS NULL OR a.caliber_count IS NULL
 OR (b.caliber_count>1 AND b.unknown_start=1) OR (a.caliber_count>1 AND a.unknown_start=1)
 OR e.predecessor_id IN (SELECT reference_id FROM tied_starts)
 OR e.reference_id IN (SELECT reference_id FROM tied_starts)),
 pairs AS (SELECT e.*,b.caliber_id AS before_caliber,a.caliber_id AS after_caliber,
 b.claim_id AS before_claim,a.claim_id AS after_claim,
 b.years_claim_id AS before_years_claim,a.years_claim_id AS after_years_claim,
 COALESCE(CAST(b.year_from AS TEXT),'unknown') || '-' || COALESCE(CAST(b.year_to AS TEXT),b.year_to_kind) AS byears,
 COALESCE(CAST(a.year_from AS TEXT),'unknown') || '-' || COALESCE(CAST(a.year_to AS TEXT),a.year_to_kind) AS ayears
 FROM edges e JOIN usage b ON b.reference_id=e.predecessor_id
 JOIN usage a ON a.reference_id=e.reference_id
 JOIN ordering bo ON bo.reference_id=e.predecessor_id
 JOIN ordering ao ON ao.reference_id=e.reference_id
 WHERE NOT EXISTS(SELECT 1 FROM unknown_edges u WHERE u.reference_id=e.reference_id AND u.predecessor_id=e.predecessor_id)
 AND (b.year_from=bo.latest OR (bo.caliber_count=1 AND bo.latest IS NULL))
 AND (a.year_from=ao.earliest OR (ao.caliber_count=1 AND ao.earliest IS NULL))),
 compared AS (SELECT p.line_id,p.reference_id,p.predecessor_id,t.attribute,
 CASE t.attribute WHEN 'caliber' THEN p.before_caliber WHEN 'years' THEN p.byears ELSE b.value END AS before_value,
 CASE t.attribute WHEN 'caliber' THEN p.after_caliber WHEN 'years' THEN p.ayears ELSE a.value END AS after_value,
 CASE t.attribute WHEN 'caliber' THEN p.before_claim WHEN 'years' THEN p.before_years_claim ELSE b.id END AS before_claim_id,
 CASE t.attribute WHEN 'caliber' THEN p.after_claim WHEN 'years' THEN p.after_years_claim ELSE a.id END AS after_claim_id
 FROM pairs p CROSS JOIN attrs t LEFT JOIN selected_claim_all b ON b.subject_id=p.before_caliber AND b.predicate=t.attribute
 LEFT JOIN selected_claim_all a ON a.subject_id=p.after_caliber AND a.predicate=t.attribute)
, representatives AS (
 SELECT line_id,reference_id,predecessor_id,attribute,before_value,after_value,
 MIN(before_claim_id) AS before_claim_id,MIN(after_claim_id) AS after_claim_id
 FROM compared GROUP BY line_id,reference_id,predecessor_id,attribute,before_value,after_value)
 SELECT line_id,reference_id,predecessor_id,attribute,before_value,after_value,
 CASE WHEN before_value IS NULL OR after_value IS NULL THEN NULL ELSE before_value<>after_value END AS changed,
 (SELECT status FROM claim WHERE id=before_claim_id) AS before_status,
 (SELECT status FROM claim WHERE id=after_claim_id) AS after_status,
 (SELECT MIN(id) FROM evidence WHERE claim_id=before_claim_id) AS before_evidence_id,
 (SELECT MIN(id) FROM evidence WHERE claim_id=after_claim_id) AS after_evidence_id FROM representatives
 UNION ALL SELECT u.line_id,u.reference_id,u.predecessor_id,t.attribute,NULL,NULL,NULL,NULL,NULL,NULL,NULL FROM unknown_edges u CROSS JOIN attrs t;

CREATE VIEW v_evidence_all AS SELECT c.id AS claim_id,e.id AS evidence_id,s.id AS source_id,s.trust_tier AS tier,e.match_mode,e.quote,e.locator,s.archive_url,s.retrieved_at
 FROM selected_claim_all c JOIN evidence e ON e.claim_id=c.id JOIN source s ON s.id=e.source_id;
