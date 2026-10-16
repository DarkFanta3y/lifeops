"""PyMySQL 连接适配：复用现有仓储 SQL，集中处理已使用的方言差异。"""

from __future__ import annotations

import re
import threading
from urllib.parse import unquote, urlsplit

import pymysql


def mysql_sql(sql: str, parameterized: bool = True) -> str:
    """仅适配仓储内部 SQL；用户内容始终通过驱动参数绑定。"""
    sql = sql.replace("INSERT OR IGNORE INTO", "INSERT IGNORE INTO")
    conflict = re.search(r"\bON CONFLICT\([\w, ]+\) DO UPDATE SET ", sql)
    if conflict:
        updates = sql[conflict.end():]
        updates = re.sub(r"\bexcluded\.(\w+)", r"incoming.\1", updates)
        # SQLite 的双参数 MAX 是标量函数，MySQL 对应 GREATEST。
        updates = re.sub(r"\bMAX\(([^()]+,[^()]+)\)", r"GREATEST(\1)", updates)
        sql = sql[:conflict.start()] + "AS incoming ON DUPLICATE KEY UPDATE " + updates
    # key 是 MySQL 保留字；此字段只出现在仓储 SQL 的标识符位置。
    tokens = re.split(r"('(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\"|`[^`]*`)", sql)
    for index, token in enumerate(tokens):
        if index % 2 == 0:
            token = re.sub(r"\bkey\b", "`key`", token)
            if parameterized:
                token = token.replace("%", "%%").replace("?", "%s")
        elif parameterized:
            token = token.replace("%", "%%")
        tokens[index] = token
    return "".join(tokens)


class MySQLRow(dict):
    """同时支持列名和位置访问，兼容仓储现有的行读取方式。"""

    def __init__(self, names: list[str], values: tuple):
        super().__init__()
        self._values = values
        for name, value in zip(names, values, strict=True):
            self.setdefault(name, value)

    def __getitem__(self, key):
        return self._values[key] if isinstance(key, int) else super().__getitem__(key)


class MySQLCursor:
    def __init__(self, connection: MySQLConnection):
        self.connection = connection
        self.raw = connection.raw().cursor()

    def execute(self, sql: str, params=None):
        if params is not None and "LIMIT ?" in sql:
            # SQLite 的 LIMIT -1 表示不限制，MySQL 使用最大的无符号 BIGINT。
            limit_index = sql[:sql.index("LIMIT ?")].count("?")
            params = list(params)
            if params[limit_index] == -1:
                params[limit_index] = 18446744073709551615
        try:
            if sql.lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE", "REPLACE"}:
                self.connection.local.dirty = True
            self.raw.execute(mysql_sql(sql, params is not None), params)
        except pymysql.MySQLError:
            self.connection.rollback()
            raise
        return self

    def executemany(self, sql: str, params):
        try:
            self.connection.local.dirty = True
            self.raw.executemany(mysql_sql(sql), params)
        except pymysql.MySQLError:
            self.connection.rollback()
            raise
        return self

    def _row(self, values):
        if values is None:
            return None
        return MySQLRow([item[0] for item in self.raw.description], values)

    def fetchone(self):
        return self._row(self.raw.fetchone())

    def fetchall(self):
        return [self._row(values) for values in self.raw.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def lastrowid(self):
        return self.raw.lastrowid

    @property
    def rowcount(self):
        return self.raw.rowcount


class MySQLConnection:
    """每个线程独立连接，避免 FastAPI 与索引工作线程共享 MySQL 协议流。"""

    def __init__(self, url: str):
        parsed = urlsplit(url)
        if parsed.scheme not in {"mysql", "mysql+pymysql"} or not parsed.path.strip("/"):
            raise ValueError("LIFEOPS_DATABASE_URL 必须是包含数据库名的 MySQL URL")
        self.options = {
            "host": parsed.hostname or "127.0.0.1",
            "port": parsed.port or 3306,
            "user": unquote(parsed.username or ""),
            "password": unquote(parsed.password or ""),
            "database": unquote(parsed.path.strip("/")),
            "charset": "utf8mb4",
            "autocommit": False,
            "binary_prefix": True,
            "connect_timeout": 10,
            "read_timeout": 30,
            "write_timeout": 30,
            "init_command": "SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED",
        }
        self.local = threading.local()
        self.connections = []
        self.lock = threading.Lock()

    def _open(self):
        connection = pymysql.connect(**self.options)
        self.local.connection = connection
        with self.lock:
            self.connections.append(connection)
        return connection

    def raw(self):
        connection = getattr(self.local, "connection", None)
        if connection is None:
            return self._open()
        # 仅允许未修改数据的空闲连接恢复，写入中断必须报错并回滚。
        try:
            connection.ping()
        except pymysql.MySQLError:
            dirty = getattr(self.local, "dirty", False)
            self.local.connection = None
            self.local.dirty = False
            if connection.open:
                connection.close()
            if dirty:
                raise
            return self._open()
        return connection

    def cursor(self):
        return MySQLCursor(self)

    def execute(self, sql: str, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        self.raw().commit()
        self.local.dirty = False

    def rollback(self):
        connection = getattr(self.local, "connection", None)
        if connection is not None and connection.open:
            connection.rollback()
        self.local.dirty = False

    def close(self):
        with self.lock:
            for connection in self.connections:
                if connection.open:
                    connection.close()
            self.connections.clear()
        self.local = threading.local()
