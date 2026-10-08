CREATE VIEW selected_claim AS SELECT c.*, o.entity_id, o.value, o.unit,
 y.year_from, y.year_to, COALESCE(y.year_to_kind,'unknown') AS year_to_kind,
 COALESCE(y.year_from_sort,9999) AS year_from_sort
 FROM claim c JOIN claim_object o ON o.claim_id=c.id
 LEFT JOIN claim_years y ON y.claim_id=c.id WHERE c.status = 'verified';

CREATE VIEW v_reference_calibers AS
 SELECT DISTINCT u.subject_id AS reference_id,u.entity_id AS caliber_id,
 CASE WHEN EXISTS(SELECT 1 FROM selected_claim g WHERE g.subject_id=u.entity_id AND g.predicate='grade_of')
 THEN COALESCE(n.value,'unknown')
 WHEN og.value='false' AND og.status='verified'
 THEN 'none' ELSE 'unknown' END AS grade,
 u.year_from,u.year_to,u.year_to_kind,u.year_from_sort,u.id AS claim_id,u.status,
 MAX(u.disputed,COALESCE(n.disputed,0),COALESCE(g.disputed,0),COALESCE(og.disputed,0)) AS disputed,
 MAX(u.contested,COALESCE(n.contested,0),COALESCE(g.contested,0),COALESCE(og.contested,0)) AS contested,
 MIN(u.has_primary,COALESCE(n.has_primary,1),COALESCE(g.has_primary,1),COALESCE(og.has_primary,1)) AS has_primary
 FROM selected_claim u LEFT JOIN selected_claim g ON g.subject_id=u.entity_id AND g.predicate='grade_of'
 LEFT JOIN selected_claim n ON n.subject_id=u.entity_id AND n.predicate='grade_name' AND g.id IS NOT NULL
 LEFT JOIN selected_claim og ON og.subject_id=u.entity_id AND og.predicate='offers_grades' AND g.id IS NULL
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

CREATE VIEW v_lineage AS
 SELECT l.entity_id AS line_id,r.id AS reference_id,
 COALESCE(u.year_from,p.year_from) AS year_from,COALESCE(u.year_to,p.year_to) AS year_to,
 CASE WHEN u.claim_id IS NOT NULL THEN u.year_to_kind ELSE COALESCE(p.year_to_kind,'unknown') END AS year_to_kind,
 CASE WHEN u.claim_id IS NOT NULL THEN u.year_from_sort ELSE COALESCE(p.year_from_sort,9999) END AS year_from_sort,
 u.caliber_id,u.grade,s.entity_id AS succeeds_reference_id,COALESCE(u.claim_id,p.id,l.id) AS claim_id,
 COALESCE(u.status,p.status,l.status,'verified') AS status,
 MAX(COALESCE(u.disputed,0),COALESCE(l.disputed,0),COALESCE(s.disputed,0)) AS disputed,
 MAX(COALESCE(u.contested,0),COALESCE(l.contested,0),COALESCE(s.contested,0)) AS contested,
 MIN(COALESCE(u.has_primary,p.has_primary,l.has_primary,0),COALESCE(l.has_primary,0),COALESCE(s.has_primary,1)) AS has_primary
 FROM reference r LEFT JOIN selected_claim l ON l.subject_id=r.id AND l.predicate='in_line'
 LEFT JOIN v_reference_calibers u ON u.reference_id=r.id
 LEFT JOIN selected_claim p ON p.subject_id=r.id AND p.predicate='produced' AND u.claim_id IS NULL
 LEFT JOIN selected_claim s ON s.subject_id=r.id AND s.predicate='succeeds';

CREATE VIEW v_lineage_diff AS
 WITH attrs(attribute) AS (VALUES ('caliber'),('offers_grades'),('grade_name'),('winding'),('beat_rate'),('jewels'),('power_reserve'),('hacking'),('date_mechanism'),('introduced'),('discontinued'),('years')),
 edges AS (SELECT s.subject_id AS reference_id,s.entity_id AS predecessor_id,l.entity_id AS line_id
 FROM selected_claim s JOIN selected_claim l ON l.subject_id=s.subject_id AND l.predicate='in_line' AND l.status='verified'
 WHERE s.predicate='succeeds' AND s.status='verified'
 AND (SELECT COUNT(DISTINCT bo.entity_id) FROM claim b JOIN claim_object bo ON bo.claim_id=b.id WHERE b.subject_id=s.subject_id AND b.predicate='succeeds' AND b.status='verified')=1),
 unknown_edges AS (SELECT e.* FROM edges e WHERE
 NOT EXISTS(SELECT 1 FROM v_reference_calibers u WHERE u.reference_id=e.reference_id)
 OR NOT EXISTS(SELECT 1 FROM v_reference_calibers u WHERE u.reference_id=e.predecessor_id)
 OR EXISTS(SELECT 1 FROM v_reference_calibers u WHERE u.reference_id IN(e.reference_id,e.predecessor_id) AND (u.year_from IS NULL OR u.year_to_kind='unknown'))),
 pairs AS (SELECT e.*,b.caliber_id AS before_caliber,a.caliber_id AS after_caliber,
 b.claim_id AS before_claim,a.claim_id AS after_claim,b.status AS bstatus,a.status AS astatus,
 CAST(b.year_from AS TEXT) || '-' || COALESCE(CAST(b.year_to AS TEXT),b.year_to_kind) AS byears,
 CAST(a.year_from AS TEXT) || '-' || COALESCE(CAST(a.year_to AS TEXT),a.year_to_kind) AS ayears
 FROM edges e JOIN v_reference_calibers b ON b.reference_id=e.predecessor_id
 JOIN v_reference_calibers a ON a.reference_id=e.reference_id
 WHERE NOT EXISTS(SELECT 1 FROM unknown_edges u WHERE u.reference_id=e.reference_id AND u.predecessor_id=e.predecessor_id)
 AND b.year_from=(SELECT MAX(year_from) FROM v_reference_calibers WHERE reference_id=e.predecessor_id)
 AND a.year_from=(SELECT MIN(year_from) FROM v_reference_calibers WHERE reference_id=e.reference_id)),
 compared AS (SELECT p.line_id,p.reference_id,p.predecessor_id,t.attribute,
 CASE t.attribute WHEN 'caliber' THEN p.before_caliber WHEN 'years' THEN p.byears ELSE b.value END AS before_value,
 CASE t.attribute WHEN 'caliber' THEN p.after_caliber WHEN 'years' THEN p.ayears ELSE a.value END AS after_value,
 CASE WHEN t.attribute IN('caliber','years') THEN p.bstatus ELSE b.status END AS before_status,
 CASE WHEN t.attribute IN('caliber','years') THEN p.astatus ELSE a.status END AS after_status,
 (SELECT MIN(id) FROM evidence WHERE claim_id=CASE WHEN t.attribute IN('caliber','years') THEN p.before_claim ELSE b.id END) AS before_evidence_id,
 (SELECT MIN(id) FROM evidence WHERE claim_id=CASE WHEN t.attribute IN('caliber','years') THEN p.after_claim ELSE a.id END) AS after_evidence_id
 FROM pairs p CROSS JOIN attrs t LEFT JOIN selected_claim b ON b.subject_id=p.before_caliber AND b.predicate=t.attribute
 LEFT JOIN selected_claim a ON a.subject_id=p.after_caliber AND a.predicate=t.attribute)
 SELECT line_id,reference_id,predecessor_id,attribute,before_value,after_value,
 CASE WHEN before_value IS NULL OR after_value IS NULL THEN NULL ELSE before_value<>after_value END AS changed,
 before_status,after_status,before_evidence_id,after_evidence_id FROM compared
 UNION ALL SELECT u.line_id,u.reference_id,u.predecessor_id,t.attribute,NULL,NULL,NULL,NULL,NULL,NULL,NULL FROM unknown_edges u CROSS JOIN attrs t;

CREATE VIEW v_evidence AS SELECT c.id AS claim_id,e.id AS evidence_id,s.id AS source_id,s.trust_tier AS tier,e.match_mode,e.quote,e.locator,s.archive_url,s.retrieved_at
 FROM selected_claim c JOIN evidence e ON e.claim_id=c.id JOIN source s ON s.id=e.source_id;

CREATE VIEW selected_claim_all AS SELECT c.*, o.entity_id, o.value, o.unit,
 y.year_from, y.year_to, COALESCE(y.year_to_kind,'unknown') AS year_to_kind,
 COALESCE(y.year_from_sort,9999) AS year_from_sort
 FROM claim c JOIN claim_object o ON o.claim_id=c.id
 LEFT JOIN claim_years y ON y.claim_id=c.id ;

CREATE VIEW v_reference_calibers_all AS
 SELECT DISTINCT u.subject_id AS reference_id,u.entity_id AS caliber_id,
 CASE WHEN EXISTS(SELECT 1 FROM selected_claim_all g WHERE g.subject_id=u.entity_id AND g.predicate='grade_of')
 THEN COALESCE(n.value,'unknown')
 WHEN og.value='false' AND og.status='verified'
 THEN 'none' ELSE 'unknown' END AS grade,
 u.year_from,u.year_to,u.year_to_kind,u.year_from_sort,u.id AS claim_id,u.status,
 MAX(u.disputed,COALESCE(n.disputed,0),COALESCE(g.disputed,0),COALESCE(og.disputed,0)) AS disputed,
 MAX(u.contested,COALESCE(n.contested,0),COALESCE(g.contested,0),COALESCE(og.contested,0)) AS contested,
 MIN(u.has_primary,COALESCE(n.has_primary,1),COALESCE(g.has_primary,1),COALESCE(og.has_primary,1)) AS has_primary
 FROM selected_claim_all u LEFT JOIN selected_claim_all g ON g.subject_id=u.entity_id AND g.predicate='grade_of'
 LEFT JOIN selected_claim_all n ON n.subject_id=u.entity_id AND n.predicate='grade_name' AND g.id IS NOT NULL
 LEFT JOIN selected_claim_all og ON og.subject_id=u.entity_id AND og.predicate='offers_grades' AND g.id IS NULL
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

CREATE VIEW v_lineage_all AS
 SELECT l.entity_id AS line_id,r.id AS reference_id,
 COALESCE(u.year_from,p.year_from) AS year_from,COALESCE(u.year_to,p.year_to) AS year_to,
 CASE WHEN u.claim_id IS NOT NULL THEN u.year_to_kind ELSE COALESCE(p.year_to_kind,'unknown') END AS year_to_kind,
 CASE WHEN u.claim_id IS NOT NULL THEN u.year_from_sort ELSE COALESCE(p.year_from_sort,9999) END AS year_from_sort,
 u.caliber_id,u.grade,s.entity_id AS succeeds_reference_id,COALESCE(u.claim_id,p.id,l.id) AS claim_id,
 COALESCE(u.status,p.status,l.status,'verified') AS status,
 MAX(COALESCE(u.disputed,0),COALESCE(l.disputed,0),COALESCE(s.disputed,0)) AS disputed,
 MAX(COALESCE(u.contested,0),COALESCE(l.contested,0),COALESCE(s.contested,0)) AS contested,
 MIN(COALESCE(u.has_primary,p.has_primary,l.has_primary,0),COALESCE(l.has_primary,0),COALESCE(s.has_primary,1)) AS has_primary
 FROM reference r LEFT JOIN selected_claim_all l ON l.subject_id=r.id AND l.predicate='in_line'
 LEFT JOIN v_reference_calibers_all u ON u.reference_id=r.id
 LEFT JOIN selected_claim_all p ON p.subject_id=r.id AND p.predicate='produced' AND u.claim_id IS NULL
 LEFT JOIN selected_claim_all s ON s.subject_id=r.id AND s.predicate='succeeds';

CREATE VIEW v_lineage_diff_all AS
 WITH attrs(attribute) AS (VALUES ('caliber'),('offers_grades'),('grade_name'),('winding'),('beat_rate'),('jewels'),('power_reserve'),('hacking'),('date_mechanism'),('introduced'),('discontinued'),('years')),
 edges AS (SELECT s.subject_id AS reference_id,s.entity_id AS predecessor_id,l.entity_id AS line_id
 FROM selected_claim_all s JOIN selected_claim_all l ON l.subject_id=s.subject_id AND l.predicate='in_line' AND l.status='verified'
 WHERE s.predicate='succeeds' AND s.status='verified'
 AND (SELECT COUNT(DISTINCT bo.entity_id) FROM claim b JOIN claim_object bo ON bo.claim_id=b.id WHERE b.subject_id=s.subject_id AND b.predicate='succeeds' AND b.status='verified')=1),
 unknown_edges AS (SELECT e.* FROM edges e WHERE
 NOT EXISTS(SELECT 1 FROM v_reference_calibers_all u WHERE u.reference_id=e.reference_id)
 OR NOT EXISTS(SELECT 1 FROM v_reference_calibers_all u WHERE u.reference_id=e.predecessor_id)
 OR EXISTS(SELECT 1 FROM v_reference_calibers_all u WHERE u.reference_id IN(e.reference_id,e.predecessor_id) AND (u.year_from IS NULL OR u.year_to_kind='unknown'))),
 pairs AS (SELECT e.*,b.caliber_id AS before_caliber,a.caliber_id AS after_caliber,
 b.claim_id AS before_claim,a.claim_id AS after_claim,b.status AS bstatus,a.status AS astatus,
 CAST(b.year_from AS TEXT) || '-' || COALESCE(CAST(b.year_to AS TEXT),b.year_to_kind) AS byears,
 CAST(a.year_from AS TEXT) || '-' || COALESCE(CAST(a.year_to AS TEXT),a.year_to_kind) AS ayears
 FROM edges e JOIN v_reference_calibers_all b ON b.reference_id=e.predecessor_id
 JOIN v_reference_calibers_all a ON a.reference_id=e.reference_id
 WHERE NOT EXISTS(SELECT 1 FROM unknown_edges u WHERE u.reference_id=e.reference_id AND u.predecessor_id=e.predecessor_id)
 AND b.year_from=(SELECT MAX(year_from) FROM v_reference_calibers_all WHERE reference_id=e.predecessor_id)
 AND a.year_from=(SELECT MIN(year_from) FROM v_reference_calibers_all WHERE reference_id=e.reference_id)),
 compared AS (SELECT p.line_id,p.reference_id,p.predecessor_id,t.attribute,
 CASE t.attribute WHEN 'caliber' THEN p.before_caliber WHEN 'years' THEN p.byears ELSE b.value END AS before_value,
 CASE t.attribute WHEN 'caliber' THEN p.after_caliber WHEN 'years' THEN p.ayears ELSE a.value END AS after_value,
 CASE WHEN t.attribute IN('caliber','years') THEN p.bstatus ELSE b.status END AS before_status,
 CASE WHEN t.attribute IN('caliber','years') THEN p.astatus ELSE a.status END AS after_status,
 (SELECT MIN(id) FROM evidence WHERE claim_id=CASE WHEN t.attribute IN('caliber','years') THEN p.before_claim ELSE b.id END) AS before_evidence_id,
 (SELECT MIN(id) FROM evidence WHERE claim_id=CASE WHEN t.attribute IN('caliber','years') THEN p.after_claim ELSE a.id END) AS after_evidence_id
 FROM pairs p CROSS JOIN attrs t LEFT JOIN selected_claim_all b ON b.subject_id=p.before_caliber AND b.predicate=t.attribute
 LEFT JOIN selected_claim_all a ON a.subject_id=p.after_caliber AND a.predicate=t.attribute)
 SELECT line_id,reference_id,predecessor_id,attribute,before_value,after_value,
 CASE WHEN before_value IS NULL OR after_value IS NULL THEN NULL ELSE before_value<>after_value END AS changed,
 before_status,after_status,before_evidence_id,after_evidence_id FROM compared
 UNION ALL SELECT u.line_id,u.reference_id,u.predecessor_id,t.attribute,NULL,NULL,NULL,NULL,NULL,NULL,NULL FROM unknown_edges u CROSS JOIN attrs t;

CREATE VIEW v_evidence_all AS SELECT c.id AS claim_id,e.id AS evidence_id,s.id AS source_id,s.trust_tier AS tier,e.match_mode,e.quote,e.locator,s.archive_url,s.retrieved_at
 FROM selected_claim_all c JOIN evidence e ON e.claim_id=c.id JOIN source s ON s.id=e.source_id;
