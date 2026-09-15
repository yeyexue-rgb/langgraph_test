"""测试管理数据库种子脚本。

创建一个面向测试工程师的 SQLite 数据库，包含三张表：
- test_cases：测试用例库
- defects：缺陷记录
- test_runs：测试执行记录

该数据库供 SQL Agent 查询，所有数据均为演示用途。
运行：python scripts/seed_test_db.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


DATABASE_PATH = Path("data/test_management.db")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS test_cases (
    case_id        TEXT PRIMARY KEY,
    module         TEXT NOT NULL,
    title          TEXT NOT NULL,
    priority       TEXT NOT NULL CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    status         TEXT NOT NULL CHECK (status IN ('active', 'deprecated', 'draft')),
    owner          TEXT NOT NULL,
    created_date   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS defects (
    defect_id      TEXT PRIMARY KEY,
    module         TEXT NOT NULL,
    severity       TEXT NOT NULL CHECK (severity IN ('blocker', 'critical', 'major', 'minor', 'trivial')),
    status         TEXT NOT NULL CHECK (status IN ('open', 'fixed', 'verified', 'closed', 'rejected')),
    reporter       TEXT NOT NULL,
    assignee       TEXT,
    created_date   TEXT NOT NULL,
    resolved_date  TEXT
);

CREATE TABLE IF NOT EXISTS test_runs (
    run_id         TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL,
    result         TEXT NOT NULL CHECK (result IN ('passed', 'failed', 'blocked', 'skipped')),
    executed_by    TEXT NOT NULL,
    executed_at    TEXT NOT NULL,
    duration_ms    INTEGER,
    FOREIGN KEY (case_id) REFERENCES test_cases(case_id)
);
"""


SEED_DATA = """
INSERT OR IGNORE INTO test_cases VALUES
    ('TC-001', '登录模块',   '用户名密码正确登录',     'P0', 'active', '张三', '2026-01-15'),
    ('TC-002', '登录模块',   '密码错误三次锁定',       'P0', 'active', '张三', '2026-01-15'),
    ('TC-003', '购物车',     '添加商品到购物车',       'P1', 'active', '李四', '2026-02-01'),
    ('TC-004', '购物车',     '购物车商品数量修改',     'P1', 'active', '李四', '2026-02-01'),
    ('TC-005', '支付模块',   '微信支付正常流程',       'P0', 'active', '王五', '2026-02-10'),
    ('TC-006', '支付模块',   '支付超时重试',           'P1', 'active', '王五', '2026-02-10'),
    ('TC-007', '订单管理',   '订单列表分页查询',       'P2', 'active', '赵六', '2026-03-01'),
    ('TC-008', '订单管理',   '订单导出Excel',          'P2', 'draft',  '赵六', '2026-03-01'),
    ('TC-009', '用户中心',   '个人信息修改',           'P1', 'active', '张三', '2026-03-05'),
    ('TC-010', '用户中心',   '头像上传格式校验',       'P2', 'active', '张三', '2026-03-05');

INSERT OR IGNORE INTO defects VALUES
    ('DEF-001', '登录模块',   'blocker',   'fixed',    '测试组A', '开发组B', '2026-07-01', '2026-07-03'),
    ('DEF-002', '登录模块',   'major',     'open',     '测试组A',  NULL,     '2026-07-10',  NULL),
    ('DEF-003', '购物车',     'critical',  'verified', '测试组A', '开发组B', '2026-07-05', '2026-07-06'),
    ('DEF-004', '购物车',     'minor',     'open',     '测试组A',  NULL,     '2026-07-15',  NULL),
    ('DEF-005', '支付模块',   'blocker',   'closed',   '测试组A', '开发组C', '2026-06-20', '2026-06-25'),
    ('DEF-006', '支付模块',   'major',     'open',     '测试组A',  NULL,     '2026-07-12',  NULL),
    ('DEF-007', '订单管理',   'minor',     'rejected', '测试组A',  NULL,     '2026-07-08',  NULL),
    ('DEF-008', '用户中心',   'trivial',   'closed',   '测试组A', '开发组B', '2026-06-15', '2026-06-16');

INSERT OR IGNORE INTO test_runs VALUES
    ('R-001', 'TC-001', 'passed',  '自动化CI', '2026-08-01T10:00:00', 1200),
    ('R-002', 'TC-002', 'passed',  '自动化CI', '2026-08-01T10:05:00',  850),
    ('R-003', 'TC-003', 'failed',  '李四',     '2026-08-01T14:00:00', 3200),
    ('R-004', 'TC-004', 'passed',  '李四',     '2026-08-01T14:30:00', 1100),
    ('R-005', 'TC-005', 'blocked', '王五',     '2026-08-01T16:00:00',  100),
    ('R-006', 'TC-006', 'skipped', '王五',     '2026-08-01T16:10:00',   50),
    ('R-007', 'TC-001', 'passed',  '自动化CI', '2026-08-02T10:00:00', 1150),
    ('R-008', 'TC-003', 'passed',  '李四',     '2026-08-02T14:00:00', 2800),
    ('R-009', 'TC-007', 'failed',  '赵六',     '2026-08-02T15:00:00', 5400),
    ('R-010', 'TC-009', 'passed',  '张三',     '2026-08-02T17:00:00',  900);
"""


def seed_database(database_path: Path | None = None) -> None:
    """创建并填充测试管理数据库。"""

    path = database_path or DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(str(path))

    try:
        connection.executescript(SCHEMA_SQL)
        connection.executescript(SEED_DATA)
        connection.commit()
    finally:
        connection.close()

    print(f"测试管理数据库已创建：{path}")
    print(f"  test_cases: 10 条")
    print(f"  defects: 8 条")
    print(f"  test_runs: 10 条")


if __name__ == "__main__":
    seed_database()
