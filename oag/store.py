from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .schema import Ontology

TYPE_MAP = {
    "str": "TEXT",
    "int": "INTEGER",
    "float": "REAL",
    "bool": "INTEGER",
}


class Store:
    def __init__(self, ontology: Ontology, db_path: str = ":memory:"):
        self.ontology = ontology
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def create_tables(self):
        for type_name, obj_def in self.ontology.objects.items():
            table = self.ontology.table_name(type_name)
            cols = ["_id INTEGER PRIMARY KEY AUTOINCREMENT"]
            for prop_name, prop_def in obj_def.properties.items():
                sql_type = TYPE_MAP.get(prop_def.type, "TEXT")
                cols.append(f"{prop_name} {sql_type}")
            ddl = f"CREATE TABLE IF NOT EXISTS {table} ({', '.join(cols)})"
            self.conn.execute(ddl)
        self.conn.commit()

    def load_data(self, object_type: str, data: list[dict],
                  field_mapping: dict[str, str] | None = None):
        table = self.ontology.table_name(object_type)
        obj_def = self.ontology.objects.get(object_type)
        if not obj_def or not data:
            return 0

        count = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count > 0:
            return 0

        valid_cols = set(obj_def.properties.keys())
        inserted = 0
        for raw_row in data:
            row = {}
            for raw_key, value in raw_row.items():
                mapped = field_mapping.get(raw_key, raw_key) if field_mapping else raw_key
                if mapped in valid_cols:
                    row[mapped] = value
            if not row:
                continue
            cols = list(row.keys())
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            self.conn.execute(
                f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                [row[c] for c in cols],
            )
            inserted += 1
        self.conn.commit()
        return inserted

    def load_json_file(self, object_type: str, file_path: str | Path,
                       field_mapping: dict[str, str] | None = None) -> int:
        path = Path(file_path)
        if not path.exists():
            return 0
        text = path.read_text(encoding="utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            cleaned = text.replace("[", "").replace("]", "")
            data = []
            decoder = json.JSONDecoder()
            pos = 0
            while pos < len(cleaned):
                chunk = cleaned[pos:].lstrip(" ,\n\r\t")
                if not chunk:
                    break
                pos = len(cleaned) - len(chunk)
                try:
                    obj, end = decoder.raw_decode(chunk)
                    data.append(obj)
                    pos += end
                except json.JSONDecodeError:
                    break
        return self.load_data(object_type, data, field_mapping)

    def query(self, object_type: str, filters: dict[str, Any] | None = None,
              limit: int | None = None, order_by: str | None = None,
              offset: int | None = None) -> list[dict]:
        obj_def = self.ontology.objects.get(object_type)
        if not obj_def:
            return []
        valid_cols = set(obj_def.properties.keys()) | {"_id"}
        table = self.ontology.table_name(object_type)
        sql = f"SELECT * FROM {table}"
        params: list[Any] = []
        if filters:
            clauses = []
            for k, v in filters.items():
                col = k.split("__")[0] if "__" in k else k
                if col not in valid_cols:
                    continue
                if "__" in k:
                    op = k.split("__", 1)[1]
                    if op == "like":
                        clauses.append(f"{col} LIKE ?")
                        params.append(f"%{v}%")
                    elif op == "gt":
                        clauses.append(f"{col} > ?")
                        params.append(v)
                    elif op == "gte":
                        clauses.append(f"{col} >= ?")
                        params.append(v)
                    elif op == "lt":
                        clauses.append(f"{col} < ?")
                        params.append(v)
                    elif op == "lte":
                        clauses.append(f"{col} <= ?")
                        params.append(v)
                    elif op == "ne":
                        clauses.append(f"{col} != ?")
                        params.append(v)
                    else:
                        clauses.append(f"{col} = ?")
                        params.append(v)
                else:
                    clauses.append(f"{k} = ?")
                    params.append(v)
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
        if order_by:
            col = order_by.lstrip("-")
            if col in valid_cols:
                direction = "DESC" if order_by.startswith("-") else "ASC"
                sql += f" ORDER BY {col} {direction}"
        if limit:
            sql += f" LIMIT {limit}"
        if offset:
            sql += f" OFFSET {offset}"
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count(self, object_type: str, filters: dict[str, Any] | None = None) -> int:
        rows = self.query(object_type, filters)
        return len(rows)

    def query_by_id(self, object_type: str, id_value: Any) -> dict | None:
        id_col = self.ontology.get_id_column(object_type)
        if not id_col:
            return None
        results = self.query(object_type, {id_col: id_value}, limit=1)
        return results[0] if results else None

    def query_links(self, source_type: str, source_id: Any,
                    link_name: str) -> list[dict]:
        link = self.ontology.links.get(link_name)
        if not link:
            return []
        source_id_col = self.ontology.get_id_column(source_type)
        if not source_id_col:
            return []
        source_row = self.query_by_id(source_type, source_id)
        if not source_row:
            return []
        source_key_value = source_row.get(link.join["source_key"])
        if source_key_value is None:
            return []
        return self.query(link.target, {link.join["target_key"]: source_key_value})

    def execute_sql(self, sql: str, params: list | tuple | None = None) -> list[dict]:
        rows = self.conn.execute(sql, params or []).fetchall()
        return [dict(r) for r in rows]

    def execute_write(self, sql: str, params: list | tuple | None = None) -> int:
        cursor = self.conn.execute(sql, params or [])
        self.conn.commit()
        return cursor.rowcount

    def table_count(self, object_type: str) -> int:
        table = self.ontology.table_name(object_type)
        return self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    def insert_record(self, object_type: str, data: dict) -> dict:
        obj_def = self.ontology.objects.get(object_type)
        if not obj_def:
            raise ValueError(f"未知对象类型: {object_type}")
        valid_cols = set(obj_def.properties.keys())
        row = {k: v for k, v in data.items() if k in valid_cols}
        if not row:
            raise ValueError("没有有效字段可插入")
        table = self.ontology.table_name(object_type)
        cols = list(row.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        cursor = self.conn.execute(
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
            [row[c] for c in cols],
        )
        self.conn.commit()
        return {"_id": cursor.lastrowid, "inserted": 1}

    def update_record(self, object_type: str, id_value: Any, data: dict) -> dict:
        obj_def = self.ontology.objects.get(object_type)
        if not obj_def:
            raise ValueError(f"未知对象类型: {object_type}")
        id_col = self.ontology.get_id_column(object_type) or "_id"
        valid_cols = set(obj_def.properties.keys()) - {id_col}
        row = {k: v for k, v in data.items() if k in valid_cols}
        if not row:
            raise ValueError("没有有效字段可更新")
        table = self.ontology.table_name(object_type)
        set_clause = ", ".join(f"{k} = ?" for k in row)
        params = list(row.values()) + [id_value]
        cursor = self.conn.execute(
            f"UPDATE {table} SET {set_clause} WHERE {id_col} = ?", params,
        )
        self.conn.commit()
        return {"updated": cursor.rowcount}

    def delete_record(self, object_type: str, id_value: Any) -> dict:
        obj_def = self.ontology.objects.get(object_type)
        if not obj_def:
            raise ValueError(f"未知对象类型: {object_type}")
        id_col = self.ontology.get_id_column(object_type) or "_id"
        table = self.ontology.table_name(object_type)
        cursor = self.conn.execute(
            f"DELETE FROM {table} WHERE {id_col} = ?", [id_value],
        )
        self.conn.commit()
        return {"deleted": cursor.rowcount}

    def search_text(self, keyword: str, object_types: list[str] | None = None,
                    limit: int = 20) -> list[dict]:
        if not keyword:
            return []
        types_to_search = object_types or list(self.ontology.objects.keys())
        results: list[dict] = []
        pattern = f"%{keyword}%"
        for type_name in types_to_search:
            obj_def = self.ontology.objects.get(type_name)
            if not obj_def:
                continue
            text_cols = [
                p for p, d in obj_def.properties.items() if d.type == "str"
            ]
            if not text_cols:
                continue
            table = self.ontology.table_name(type_name)
            where = " OR ".join(f"{c} LIKE ?" for c in text_cols)
            params = [pattern] * len(text_cols)
            rows = self.conn.execute(
                f"SELECT * FROM {table} WHERE {where} LIMIT ?",
                params + [limit - len(results)],
            ).fetchall()
            for row in rows:
                record = dict(row)
                matched = [c for c in text_cols if record.get(c) and keyword in str(record[c])]
                record["_object_type"] = type_name
                record["_matched_field"] = ", ".join(matched) if matched else text_cols[0]
                results.append(record)
            if len(results) >= limit:
                break
        return results[:limit]

    def close(self):
        self.conn.close()
