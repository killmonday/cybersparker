-- ============================================================
-- Cybersparker 参考数据 ID 重整脚本
-- ============================================================
-- 用途：将指纹/PoC/标签等参考表的 ID 从膨胀值（多次清空重导导致）
--       重新编号为 1, 2, 3...，同时更新所有外键引用和序列。
--
-- 用法：
--   docker compose exec -T postgres psql -U postgres cybersparker < deploy/seed/reset_ids.sql
--
-- 警告：
--   1. 仅适用于全新部署或已确认参考表无外部引用时执行
--   2. 需要 superuser 权限（Docker postgres 用户默认有）
--   3. 脚本在单事务内执行，出错自动回滚
--   4. 只重整 9 张参考数据表，不碰运行时数据表
-- ============================================================

BEGIN;

-- 禁用所有触发器（包括 FK 约束检查）
SET session_replication_role = 'replica';

-- ============================================================
-- Phase 1: 所有表 ID 上移 10,000,000（避免后续归位碰撞）
--         用 ROW_NUMBER 生成目标 new_id 映射
-- ============================================================

-- 上移 ID + 同时生成带 new_id 的映射表

-- 1a. fingerPrint
CREATE TEMP TABLE _map_fingerprint AS
SELECT id AS old_id, row_number() OVER (ORDER BY id) AS new_id
FROM app_cybersparker_fingerprint;
UPDATE app_cybersparker_fingerprint SET id = id + 10000000;

-- 1b. EXP
CREATE TEMP TABLE _map_exp AS
SELECT id AS old_id, row_number() OVER (ORDER BY id) AS new_id
FROM app_cybersparker_exp;
UPDATE app_cybersparker_exp SET id = id + 10000000;

-- 1c. Tag
CREATE TEMP TABLE _map_tag AS
SELECT id AS old_id, row_number() OVER (ORDER BY id) AS new_id
FROM app_cybersparker_tag;
UPDATE app_cybersparker_tag SET id = id + 10000000;

-- 1d. DirScanDictGroup
CREATE TEMP TABLE _map_dirscandictgroup AS
SELECT id AS old_id, row_number() OVER (ORDER BY id) AS new_id
FROM app_cybersparker_dirscandictgroup;
UPDATE app_cybersparker_dirscandictgroup SET id = id + 10000000;

-- 1e. DirScanDict
CREATE TEMP TABLE _map_dirscandict AS
SELECT id AS old_id, row_number() OVER (ORDER BY id) AS new_id
FROM app_cybersparker_dirscandict;
UPDATE app_cybersparker_dirscandict SET id = id + 10000000;

-- 1f. cveExtensions
CREATE TEMP TABLE _map_cveextensions AS
SELECT id AS old_id, row_number() OVER (ORDER BY id) AS new_id
FROM app_cybersparker_cveextensions;
UPDATE app_cybersparker_cveextensions SET id = id + 10000000;

-- ============================================================
-- Phase 2: 更新子表的外键引用（指向新的 parent ID）
-- ============================================================

-- 2a. exp_relate_fingerprint → EXP_id_id, fingerprint_id_id
UPDATE app_cybersparker_exp_relate_fingerprint r
SET "EXP_id_id" = m.new_id
FROM _map_exp m
WHERE r."EXP_id_id" = m.old_id;

UPDATE app_cybersparker_exp_relate_fingerprint r
SET fingerprint_id_id = m.new_id
FROM _map_fingerprint m
WHERE r.fingerprint_id_id = m.old_id;

-- 2b. exp_tags → exp_id, tag_id
UPDATE app_cybersparker_exp_tags et
SET exp_id = m.new_id
FROM _map_exp m
WHERE et.exp_id = m.old_id;

UPDATE app_cybersparker_exp_tags et
SET tag_id = m.new_id
FROM _map_tag m
WHERE et.tag_id = m.old_id;

-- 2c. cveExtensions → CVE_id
UPDATE app_cybersparker_cveextensions c
SET "CVE_id" = m.new_id
FROM _map_exp m
WHERE c."CVE_id" = m.old_id;

-- 2d. dirscandict_groups → dirscandict_id, dirscandictgroup_id
UPDATE app_cybersparker_dirscandict_groups dg
SET dirscandict_id = m.new_id
FROM _map_dirscandict m
WHERE dg.dirscandict_id = m.old_id;

UPDATE app_cybersparker_dirscandict_groups dg
SET dirscandictgroup_id = m.new_id
FROM _map_dirscandictgroup m
WHERE dg.dirscandictgroup_id = m.old_id;

-- ============================================================
-- Phase 3: 父表 ID 归位
-- ============================================================

UPDATE app_cybersparker_fingerprint f
SET id = m.new_id
FROM _map_fingerprint m
WHERE f.id = m.old_id + 10000000;

UPDATE app_cybersparker_exp e
SET id = m.new_id
FROM _map_exp m
WHERE e.id = m.old_id + 10000000;

UPDATE app_cybersparker_tag t
SET id = m.new_id
FROM _map_tag m
WHERE t.id = m.old_id + 10000000;

UPDATE app_cybersparker_dirscandictgroup dg
SET id = m.new_id
FROM _map_dirscandictgroup m
WHERE dg.id = m.old_id + 10000000;

UPDATE app_cybersparker_dirscandict d
SET id = m.new_id
FROM _map_dirscandict m
WHERE d.id = m.old_id + 10000000;

UPDATE app_cybersparker_cveextensions c
SET id = m.new_id
FROM _map_cveextensions m
WHERE c.id = m.old_id + 10000000;

-- ============================================================
-- Phase 4: 子表 ID 也按顺序重新编号
-- ============================================================

-- 4a. exp_relate_fingerprint
UPDATE app_cybersparker_exp_relate_fingerprint SET id = id + 10000000;
UPDATE app_cybersparker_exp_relate_fingerprint r
SET id = sub.new_id
FROM (SELECT id AS cur_id, row_number() OVER (ORDER BY id) AS new_id FROM app_cybersparker_exp_relate_fingerprint) sub
WHERE r.id = sub.cur_id;

-- 4b. exp_tags
UPDATE app_cybersparker_exp_tags SET id = id + 10000000;
UPDATE app_cybersparker_exp_tags et
SET id = sub.new_id
FROM (SELECT id AS cur_id, row_number() OVER (ORDER BY id) AS new_id FROM app_cybersparker_exp_tags) sub
WHERE et.id = sub.cur_id;

-- 4c. dirscandict_groups
UPDATE app_cybersparker_dirscandict_groups SET id = id + 10000000;
UPDATE app_cybersparker_dirscandict_groups dg
SET id = sub.new_id
FROM (SELECT id AS cur_id, row_number() OVER (ORDER BY id) AS new_id FROM app_cybersparker_dirscandict_groups) sub
WHERE dg.id = sub.cur_id;

-- ============================================================
-- Phase 5: 重置所有序列
-- ============================================================

CREATE OR REPLACE FUNCTION pg_temp.reset_seq(tbl text) RETURNS void AS $$
DECLARE
    seq_name text;
    next_val bigint;
BEGIN
    seq_name := tbl || '_id_seq';
    EXECUTE format('SELECT COALESCE(MAX(id), 0) + 1 FROM ' || tbl) INTO next_val;
    EXECUTE format('ALTER SEQUENCE ' || seq_name || ' RESTART WITH ' || next_val);
END;
$$ LANGUAGE plpgsql;

SELECT pg_temp.reset_seq('app_cybersparker_fingerprint');
SELECT pg_temp.reset_seq('app_cybersparker_exp');
SELECT pg_temp.reset_seq('app_cybersparker_tag');
SELECT pg_temp.reset_seq('app_cybersparker_dirscandictgroup');
SELECT pg_temp.reset_seq('app_cybersparker_dirscandict');
SELECT pg_temp.reset_seq('app_cybersparker_cveextensions');
SELECT pg_temp.reset_seq('app_cybersparker_exp_relate_fingerprint');
SELECT pg_temp.reset_seq('app_cybersparker_exp_tags');
SELECT pg_temp.reset_seq('app_cybersparker_dirscandict_groups');

DROP FUNCTION pg_temp.reset_seq(text);

-- ============================================================
-- Phase 6: 清理
-- ============================================================

DROP TABLE _map_fingerprint;
DROP TABLE _map_exp;
DROP TABLE _map_tag;
DROP TABLE _map_dirscandictgroup;
DROP TABLE _map_dirscandict;
DROP TABLE _map_cveextensions;

SET session_replication_role = 'origin';

-- ============================================================
-- 验证
-- ============================================================

SELECT 'fingerprint' AS 表名, COUNT(*) AS 行数, COALESCE(MAX(id), 0) AS 最大ID FROM app_cybersparker_fingerprint
UNION ALL
SELECT 'exp', COUNT(*), COALESCE(MAX(id), 0) FROM app_cybersparker_exp
UNION ALL
SELECT 'exp_relate_fingerprint', COUNT(*), COALESCE(MAX(id), 0) FROM app_cybersparker_exp_relate_fingerprint
UNION ALL
SELECT 'tag', COUNT(*), COALESCE(MAX(id), 0) FROM app_cybersparker_tag
UNION ALL
SELECT 'exp_tags', COUNT(*), COALESCE(MAX(id), 0) FROM app_cybersparker_exp_tags
UNION ALL
SELECT 'cveextensions', COUNT(*), COALESCE(MAX(id), 0) FROM app_cybersparker_cveextensions
UNION ALL
SELECT 'dirscandictgroup', COUNT(*), COALESCE(MAX(id), 0) FROM app_cybersparker_dirscandictgroup
UNION ALL
SELECT 'dirscandict', COUNT(*), COALESCE(MAX(id), 0) FROM app_cybersparker_dirscandict
UNION ALL
SELECT 'dirscandict_groups', COUNT(*), COALESCE(MAX(id), 0) FROM app_cybersparker_dirscandict_groups
ORDER BY 1;

COMMIT;
