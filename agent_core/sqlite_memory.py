"""基于 SQLite 的 Checkpointer 工厂。

使用 SQLite 持久化 Agent 短期记忆，应用重启后仍可恢复会话状态。
适合本地学习、测试与轻量单机应用；不适用于多实例高并发生产场景。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


@dataclass
class SQLiteMemory:
    """SQLite 短期记忆资源。"""

    checkpointer: SqliteSaver
    connection: sqlite3.Connection
    database_path: Path

    def close(self) -> None:
        """关闭数据库连接。"""

        self.connection.close()


def create_sqlite_memory(
    database_path: str | Path = "data/agent_memory.sqlite3",
) -> SQLiteMemory:
    """创建 SQLite 持久化 Checkpointer。

    不能在函数结束时关闭 connection，因为 Agent 后续读写状态仍需要它。
    返回 SQLiteMemory 由调用方持有，其生命周期应与 AgentService 一致。
    """

    path = Path(database_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False：Streamlit 可能在不同线程中执行请求。
    # 但 SQLite 仍是本地文件数据库，应避免多个独立应用实例同时高频写入。
    connection = sqlite3.connect(
        str(path),
        check_same_thread=False,
        timeout=30,
    )

    # 提升本地应用读写体验。
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute("PRAGMA busy_timeout=30000")

    checkpointer = SqliteSaver(connection)
    checkpointer.setup()

    return SQLiteMemory(
        checkpointer=checkpointer,
        connection=connection,
        database_path=path,
    )
