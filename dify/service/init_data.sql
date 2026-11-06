-- =====================================================================
--  雾隐镇 · 夜班档案室 —— seekdb 初始化脚本
--  目标库：wuyin_archive   引擎：InnoDB / utf8mb4
--
--  用法（任选其一）：
--    1) mysql -h 127.0.0.1 -P 2881 -u root -p < init_data.sql
--    2) python smoke_test.py --init          （不需要 mysql 客户端）
--
--  说明：
--    * 第 1 段 建库建表（只用了最通用的 DDL，任何 MySQL 协议库都能执行）
--    * 第 2 段 灌入初始数据（4 个案子 / 21 条物证 / 8 位镇民 / 8 条镇志
--      + 1 条初始记忆 + 2 条历史问答日志）
--    * 第 3 段 全文索引（可选）：seekdb 支持 MySQL 全文索引，
--      工具服务启动时会自动补建；这段放在最后，失败也不影响前面。
-- =====================================================================

CREATE DATABASE IF NOT EXISTS wuyin_archive DEFAULT CHARACTER SET utf8mb4;
USE wuyin_archive;

-- ---------------------------------------------------------------------
-- 第 1 段：建表
-- ---------------------------------------------------------------------

-- 案件卷宗
CREATE TABLE IF NOT EXISTS case_files (
  case_id      VARCHAR(32)  NOT NULL COMMENT '案件编号',
  title        VARCHAR(128) NOT NULL COMMENT '卷宗标题',
  crime_type   VARCHAR(32)  NOT NULL COMMENT '案件类型',
  location     VARCHAR(64)  NOT NULL COMMENT '案发地点',
  occurred_at  DATETIME     NOT NULL COMMENT '案发时间',
  severity     INT          NOT NULL DEFAULT 3 COMMENT '严重度 1-5',
  keywords     VARCHAR(255) NOT NULL COMMENT '检索关键词（逗号分隔）',
  summary      TEXT         NULL COMMENT '卷宗摘要',
  status       VARCHAR(16)  NOT NULL DEFAULT 'open' COMMENT 'open / closed',
  closed_at    DATETIME     NULL COMMENT '结案时间',
  closed_by    VARCHAR(64)  NULL COMMENT '结案人',
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (case_id),
  KEY idx_case_files_location (location),
  KEY idx_case_files_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='雾隐镇案件卷宗';

-- 物证
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id  VARCHAR(32)  NOT NULL COMMENT '物证编号',
  case_id      VARCHAR(32)  NOT NULL COMMENT '所属案件',
  name         VARCHAR(128) NOT NULL COMMENT '物证名称',
  detail       VARCHAR(512) NOT NULL COMMENT '物证描述',
  location     VARCHAR(64)  NOT NULL COMMENT '发现地点',
  found_at     DATETIME     NOT NULL COMMENT '发现时间',
  keywords     VARCHAR(255) NOT NULL COMMENT '检索关键词',
  weight       INT          NOT NULL DEFAULT 1 COMMENT '关键程度 1-3',
  PRIMARY KEY (evidence_id),
  KEY idx_evidence_case (case_id),
  KEY idx_evidence_location (location)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='雾隐镇物证';

-- 镇民（嫌疑人）
CREATE TABLE IF NOT EXISTS suspects (
  suspect_id   VARCHAR(32)  NOT NULL COMMENT '镇民编号',
  name         VARCHAR(64)  NOT NULL COMMENT '姓名',
  alias        VARCHAR(64)  NOT NULL COMMENT '绰号',
  occupation   VARCHAR(64)  NOT NULL COMMENT '职业',
  motive       VARCHAR(255) NOT NULL COMMENT '动机',
  hideout      VARCHAR(64)  NOT NULL COMMENT '常去的地方',
  alibi        VARCHAR(255) NOT NULL COMMENT '自称的不在场证明',
  note         VARCHAR(255) NOT NULL DEFAULT '' COMMENT '备注',
  PRIMARY KEY (suspect_id),
  KEY idx_suspects_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='雾隐镇镇民';

-- 镇志（常识）
CREATE TABLE IF NOT EXISTS town_lore (
  lore_id      VARCHAR(32)  NOT NULL COMMENT '条目编号',
  topic        VARCHAR(64)  NOT NULL COMMENT '话题',
  content      VARCHAR(512) NOT NULL COMMENT '内容',
  keywords     VARCHAR(255) NOT NULL COMMENT '检索关键词',
  PRIMARY KEY (lore_id),
  KEY idx_lore_topic (topic)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='雾隐镇镇志';

-- 玩家进度（跨会话记忆）
CREATE TABLE IF NOT EXISTS player_progress (
  player_id           VARCHAR(64) NOT NULL COMMENT '侦探代号',
  case_id             VARCHAR(32) NOT NULL COMMENT '案件编号',
  cleared_evidence    TEXT        NULL COMMENT '已掌握物证编号 JSON 数组',
  eliminated_suspects TEXT        NULL COMMENT '已排除镇民编号 JSON 数组',
  notes               TEXT        NULL COMMENT '调查笔记',
  turns               INT         NOT NULL DEFAULT 0 COMMENT '已进行的轮次',
  updated_at          DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (player_id, case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='侦探调查进度（跨会话记忆）';

-- 问答日志（写回闭环）
CREATE TABLE IF NOT EXISTS investigation_log (
  log_id       BIGINT       NOT NULL AUTO_INCREMENT,
  player_id    VARCHAR(64)  NOT NULL COMMENT '侦探代号',
  case_id      VARCHAR(32)  NOT NULL COMMENT '案件编号',
  action       VARCHAR(16)  NOT NULL DEFAULT 'note' COMMENT 'note / close',
  question     VARCHAR(512) NOT NULL COMMENT '侦探提问',
  reply        TEXT         NULL COMMENT '阿灯回答',
  evidence_ids VARCHAR(255) NOT NULL DEFAULT '' COMMENT '关联物证编号',
  suspect_ids  VARCHAR(255) NOT NULL DEFAULT '' COMMENT '关联镇民编号',
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  KEY idx_log_player (player_id, case_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='调查问答日志';

-- ---------------------------------------------------------------------
-- 第 2 段：初始数据
-- ---------------------------------------------------------------------

-- 先清掉旧数据，保证本脚本可重复执行（幂等）
DELETE FROM investigation_log WHERE player_id IN ('detective_001', 'smoke_tester');
DELETE FROM player_progress    WHERE player_id IN ('detective_001', 'smoke_tester');
DELETE FROM case_files      WHERE case_id IN ('CASE-2401', 'CASE-2402', 'CASE-2403', 'CASE-2404');
DELETE FROM evidence        WHERE evidence_id IN ('EV-0101', 'EV-0102', 'EV-0103', 'EV-0104', 'EV-0105', 'EV-0201', 'EV-0202', 'EV-0203', 'EV-0204', 'EV-0205', 'EV-0301', 'EV-0302', 'EV-0303', 'EV-0304', 'EV-0305', 'EV-0306', 'EV-0401', 'EV-0402', 'EV-0403', 'EV-0404', 'EV-0405');
DELETE FROM suspects        WHERE suspect_id IN ('SUS-01', 'SUS-02', 'SUS-03', 'SUS-04', 'SUS-05', 'SUS-06', 'SUS-07', 'SUS-08');
DELETE FROM town_lore       WHERE lore_id IN ('LORE-01', 'LORE-02', 'LORE-03', 'LORE-04', 'LORE-05', 'LORE-06', 'LORE-07', 'LORE-08');
-- 4 个待查案件 -------------------------------------------------------
INSERT INTO case_files
  (case_id, title, crime_type, location, occurred_at, severity, keywords, summary, status)
VALUES
  ('CASE-2401', '灯塔下的第三盏灯', '失窃', '灯塔', '2026-03-02 23:40:00', 2,
   '灯塔,灯油,备用灯,林海,失窃,夜班,潮汐,第三盏灯',
   '三月二日夜里，灯塔的整箱灯油和第七盏备用灯同时不见了。守夜人林海说他在塔顶擦镜，可油箱的封条是完好的。',
   'open'),
  ('CASE-2402', '咸鱼仓的红盐账本', '失窃', '咸鱼仓', '2026-03-05 04:15:00', 3,
   '咸鱼仓,红盐,账本,盐税,亏空,周掌柜,红线,记账',
   '咸鱼仓的红盐账本少了三页，那三页恰好是本月盐税最重的一笔。账本用红线记账，红线断在哪里，亏空就在哪里。',
   'open'),
  ('CASE-2403', '雾钟停摆的那一夜', '破坏', '钟楼', '2026-03-09 02:05:00', 5,
   '雾钟,钟楼,停摆,齿轮,海雾,预警,温砚,撞钟,铜锤',
   '三月九日凌晨雾钟停摆，整条海岸线在海雾里失去了预警。有人用一柄铜锤砸断了钟舌的固定销。',
   'open'),
  ('CASE-2404', '纸鸢街的第十三个风筝', '恐吓', '纸鸢街', '2026-03-11 19:30:00', 3,
   '纸鸢街,风筝,匿名信,无主,恐吓,苏小鸢,铜线,线轴,第十三个',
   '三月十一日起，纸鸢街连续三晚出现无主的风筝，第三个风筝的线轴上绑着一封匿名信。',
   'open');

-- 21 条物证 ----------------------------------------------------------
INSERT INTO evidence
  (evidence_id, case_id, name, detail, location, found_at, keywords, weight)
VALUES
  ('EV-0101', 'CASE-2401', '封条完整的油箱', '油箱封条完好，锁扣也没有撬痕——像是根本没被打开过。', '灯塔', '2026-03-03 06:20:00', '灯塔,油箱,封条,锁扣,灯油', 3),
  ('EV-0102', 'CASE-2401', '少了一盏的备用灯架', '备用灯架只剩六个卡位，第七盏连同登记簿一起不见。', '灯塔', '2026-03-03 06:25:00', '备用灯,灯架,登记簿,第七盏,三盏', 2),
  ('EV-0103', 'CASE-2401', '塔顶擦镜的棉布', '一块沾着镜面蜡的棉布挂在栏杆上，蜡还是新的。', '灯塔', '2026-03-03 07:10:00', '擦镜,棉布,蜡,栏杆,林海', 1),
  ('EV-0104', 'CASE-2401', '潮汐表上的红圈', '值班室的潮汐表上，三月二日夜潮被画了一个红圈。', '灯塔', '2026-03-03 07:30:00', '潮汐表,红圈,夜潮,值班室,潮汐', 2),
  ('EV-0105', 'CASE-2401', '半袋被换过的灯油', '秦三的仓里有一袋灯油，桶身是咸鱼仓的记号，油却是新的。', '咸鱼仓', '2026-03-04 09:00:00', '灯油,咸鱼仓,秦三,桶,换过', 3),
  ('EV-0201', 'CASE-2402', '被撕走的三页', '账本上撕掉的三页，边缘还留着红色的装订线。', '咸鱼仓', '2026-03-05 07:00:00', '账本,三页,撕,红线,红盐', 3),
  ('EV-0202', 'CASE-2402', '断在第三行的红账', '红线记账的账本上，有一笔账只记到第三行就断了。', '咸鱼仓', '2026-03-05 07:05:00', '红账,红线,亏空,盐税,记账', 3),
  ('EV-0203', 'CASE-2402', '认得红盐账的手套', '仓里找到一只沾着红盐的手套，指腹有长期记账磨出的硬茧。', '咸鱼仓', '2026-03-05 08:30:00', '红盐,手套,记账,硬茧,周掌柜', 2),
  ('EV-0204', 'CASE-2402', '深夜开门的木梯', '咸鱼仓后巷架着一把新踩过的木梯，梯脚沾着盐霜。', '咸鱼仓', '2026-03-05 08:40:00', '木梯,后巷,盐霜,开门,陈阿婆', 2),
  ('EV-0205', 'CASE-2402', '教堂的空长椅', '三月五日凌晨教堂里只有陈阿婆一个人，可她脚上的鞋是干的。', '纸鸢街', '2026-03-05 06:40:00', '教堂,念经,陈阿婆,鞋,干', 2),
  ('EV-0301', 'CASE-2403', '断掉的钟舌销', '铜锤砸在钟舌固定销上，销子从中间断开，断口是新的。', '钟楼', '2026-03-09 07:10:00', '钟舌,固定销,铜锤,断口,钟楼,雾钟', 3),
  ('EV-0302', 'CASE-2403', '钟楼下的铜屑', '钟楼石阶缝里扫出一小撮铜屑，说明有人在楼下挥过锤。', '钟楼', '2026-03-09 07:20:00', '铜屑,石阶,锤,钟楼,停摆', 3),
  ('EV-0303', 'CASE-2403', '记在别人名下的修钟费', '温砚的账上有一笔修钟费，挂在丁叔名下，一直没收上来。', '钟楼', '2026-03-10 09:00:00', '修钟费,温砚,丁叔,账,钟', 2),
  ('EV-0304', 'CASE-2403', '停在两点整的摆钟', '温砚铺子里的摆钟停在两点整，和雾钟停摆的时刻分毫不差。', '钟楼', '2026-03-10 09:10:00', '摆钟,两点整,停摆,温砚,修钟', 2),
  ('EV-0305', 'CASE-2403', '海雾预警的空档', '雾钟停摆的那两个小时，海雾预警簿上是一片空白。', '钟楼', '2026-03-10 10:00:00', '预警,空白,海雾,簿,雾钟', 3),
  ('EV-0306', 'CASE-2403', '码头方向的口哨', '雾里有人吹了两短一长的口哨，那是码头工的号子。', '钟楼', '2026-03-10 10:20:00', '口哨,码头,秦三,号子,海雾', 2),
  ('EV-0401', 'CASE-2404', '第十三个风筝', '前十二个都收得干净，只有第十三个整夜挂在天上。', '纸鸢街', '2026-03-12 07:00:00', '第十三个,风筝,纸鸢街,无主', 3),
  ('EV-0402', 'CASE-2404', '线轴上的匿名信', '匿名信只有一行：图纸我拿走了，想要就拿盐税来换。', '纸鸢街', '2026-03-12 07:10:00', '匿名信,线轴,图纸,盐税,风筝', 3),
  ('EV-0403', 'CASE-2404', '铜线打的风筝', '匿名信那只风筝用的是铜线，不是镇上的麻线。', '纸鸢街', '2026-03-12 07:20:00', '铜线,风筝,麻线,纸鸢街', 2),
  ('EV-0404', 'CASE-2404', '被雨泡烂的图纸', '后院废纸篓里有半张被雨泡烂的鸢图，右下角盖着苏家的印。', '纸鸢街', '2026-03-12 08:00:00', '图纸,废纸篓,苏小鸢,泡烂,印', 3),
  ('EV-0405', 'CASE-2404', '苗娘的姜汤锅', '三月十一日晚，苗娘的姜汤锅还温着，可她说自己一直在熬汤。', '纸鸢街', '2026-03-12 08:10:00', '苗娘,姜汤,锅,温,旅店', 2);

-- 8 位镇民 -----------------------------------------------------------
INSERT INTO suspects
  (suspect_id, name, alias, occupation, motive, hideout, alibi, note)
VALUES
  ('SUS-01', '陈阿婆', '盐婆', '咸鱼仓帮工', '欠了一屁股盐税，怕被催债的人找上门', '咸鱼仓后巷', '声称三月五日凌晨在教堂念经', '鞋底常沾红盐'),
  ('SUS-02', '周掌柜', '账房', '咸鱼行掌柜', '账本上有亏空，最怕有人翻账', '咸鱼行二楼账房', '声称当晚在清点货包', '算盘不离手'),
  ('SUS-03', '林海', '老灯', '灯塔守夜人', '没有动机，守灯三十年的老手艺人', '灯塔二层', '声称在塔顶擦镜', '手上有镜面蜡'),
  ('SUS-04', '秦三', '三爷', '码头工头', '私下走货，怕被查', '废弃仓库', '声称在清点渔获', '两短一长的号子'),
  ('SUS-05', '温砚', '砚师傅', '修钟匠', '一笔没人付的修钟费', '钟楼下铺', '声称熬夜修摆', '铺子里有一柄铜锤'),
  ('SUS-06', '苏小鸢', '鸢娘', '纸鸢匠', '图纸被人抢了', '纸鸢街后院', '声称在糊浆糊', '鸢图右下角盖苏家印'),
  ('SUS-07', '苗娘', '苗姑', '潮汐旅店老板娘', '欠了秦三的债', '旅店后厨', '声称在熬姜汤', '常在深夜熬汤'),
  ('SUS-08', '老丁', '丁叔', '巡夜人', '没有动机', '更衣棚', '声称那晚在钟楼附近转悠', '记着全镇每个人的门');

-- 8 条镇志 -----------------------------------------------------------
INSERT INTO town_lore (lore_id, topic, content, keywords) VALUES
  ('LORE-01', '起雾祭', '雾隐镇每年三月十五过起雾祭，那几天潮水最猛，海雾也最重。', '起雾祭,三月十五,潮水,海雾,雾隐镇'),
  ('LORE-02', '雾钟镇雾', '雾钟的钟声能压住海雾。雾钟一停，海雾就会漫上街面。', '雾钟,钟声,压住,海雾,镇雾'),
  ('LORE-03', '红线记账', '咸鱼行用红线记账，红线断在哪里，亏空就在哪里。', '红线,记账,亏空,咸鱼行,红盐'),
  ('LORE-04', '备用灯只有三盏', '灯塔的备用灯一共三盏，全都登记在守夜人林海名下。', '备用灯,三盏,登记,林海,灯塔'),
  ('LORE-05', '纸鸢用铜线', '纸鸢街的风筝线是铜线，风大的时候整条街都能听见响。', '纸鸢,铜线,风筝,纸鸢街'),
  ('LORE-06', '潮汐与十五', '潮水在每月农历十五前后最猛，夜潮的潮位能没过石阶。', '潮汐,农历十五,夜潮,石阶'),
  ('LORE-07', '三花猫', '镇上的猫叫三花，它总在案发前就不见踪影。', '三花,猫,失踪,案发'),
  ('LORE-08', '教堂与雾钟共振', '教堂的钟声和雾钟同频，两处一起响，海雾会散得更快。', '教堂,钟声,共振,同频,海雾');

-- 初始记忆状态：detective_001 在 CASE-2403 上已经有一轮调查 ------
INSERT INTO player_progress
  (player_id, case_id, cleared_evidence, eliminated_suspects, notes, turns, updated_at)
VALUES
  ('detective_001', 'CASE-2403',
   '["EV-0302"]',
   '["SUS-08"]',
   '上一夜已排除丁叔（老丁）：他那晚确实在钟楼附近转悠，但没碰过钟。铜屑这条线还没查清是谁留下的。',
   2, '2026-03-10 23:50:00');

-- 上一轮会话留下的问答日志（用来验证跨会话记忆） --------------------
INSERT INTO investigation_log
  (player_id, case_id, action, question, reply, evidence_ids, suspect_ids, created_at)
VALUES
  ('detective_001', 'CASE-2403', 'note', '钟楼的雾钟到底是怎么坏的？',
   '（上一轮）我在钟楼石阶的缝里扫到过一撮铜屑，说明有人在地上挥过锤。这条我记下了。',
   'EV-0302', '', '2026-03-10 23:20:00'),
  ('detective_001', 'CASE-2403', 'note', '老丁那晚在哪儿？',
   '（上一轮）丁叔说他在钟楼附近转悠，身上没有锤也没带火。我先把他记成已排除的人——不过我还想再问一次。',
   'EV-0302', 'SUS-08', '2026-03-10 23:45:00');

-- ---------------------------------------------------------------------
-- 第 3 段（可选）：全文索引
--   seekdb 基于 OceanBase 内核，支持 MySQL 兼容的 FULLTEXT 索引。
--   工具服务启动时会自动探测并补建下面这些索引；
--   如果你的 seekdb 版本不支持，忽略本段即可，检索会自动退回 LIKE 方案。
-- ---------------------------------------------------------------------
ALTER TABLE case_files ADD FULLTEXT KEY ft_case_files (keywords, summary);
ALTER TABLE evidence  ADD FULLTEXT KEY ft_evidence  (name, keywords, detail);
ALTER TABLE suspects  ADD FULLTEXT KEY ft_suspects  (name, alias);
ALTER TABLE town_lore ADD FULLTEXT KEY ft_lore      (topic, content);
