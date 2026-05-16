import re
import time

def translate_datetime(sql: str, db_is_local: bool) -> str:
    if db_is_local:
        return sql
    pattern = re.compile(
        r"DATETIME\(\s*'now'\s*,\s*'(?P<offset>[^']+)'\s*\)", flags=re.IGNORECASE
    )

    def replace(match):
        offset = match.group("offset").strip()
        return f"NOW() - INTERVAL '{offset}'"

    return pattern.sub(replace, sql)


def translate_date(sql: str, db_is_local: bool) -> str:
    if db_is_local:
        return sql
    pattern = re.compile(
        r"DATE\(\s*'now'\s*,\s*'(?P<offset>[^']+)'\s*\)", flags=re.IGNORECASE
    )

    def replace(match):
        offset = match.group("offset").strip()
        return f"(CURRENT_DATE - INTERVAL '{offset}')::date"

    return pattern.sub(replace, sql)


def translate_time_comparison(sql: str, db_is_local: bool) -> str:
    if db_is_local:
        return sql
    pattern = re.compile(
        r"(?P<col>[a-zA-Z0-9_.]+)\s*(?P<op>>=|<=|>|<)\s*(?P<expr>\(?\s*(?:NOW\(\)|CURRENT_TIMESTAMP|CURRENT_DATE)(?:\s*-\s*INTERVAL\s*'[^']+')?\s*\)?(?:::[a-zA-Z_]+)?)",
        flags=re.IGNORECASE,
    )

    def replace(match):
        col = match.group("col")
        op = match.group("op")
        expr = match.group("expr")
        if "::" not in col:
            col = f"{col}::timestamptz"
        return f"{col} {op} {expr}"

    return pattern.sub(replace, sql)


def execute_with_retries(db, sql: str, retries: int = 3, delay: float = 0.2):
    last_exc = None
    for attempt in range(retries):
        try:
            return db.query(sql)
        except Exception as exc:
            last_exc = exc
            if attempt < retries - 1:
                time.sleep(delay)
    raise last_exc


def translate_group_concat(sql: str, db_is_local: bool) -> str:
    if db_is_local:
        return sql
    pattern = re.compile(r"GROUP_CONCAT\(([^)]+)\)", flags=re.IGNORECASE)

    def replace(match):
        inner = match.group(1).strip()
        parts = re.split(r"\bORDER\s+BY\b", inner, flags=re.IGNORECASE, maxsplit=1)
        expr = parts[0].strip()
        order_clause = ""
        if len(parts) > 1:
            order_clause = f" WITHIN GROUP (ORDER BY {parts[1].strip()})"
        args = _split_args_top(expr)
        expr_part = args[0]
        sep_arg = args[1] if len(args) > 1 else ",','"
        expr_no_distinct = re.sub(r"(?i)\\bDISTINCT\\s+", "", expr_part)
        expr_cast = expr_no_distinct.strip() or expr_part.strip()
        if "::" not in expr_cast:
            expr_cast = f"{expr_cast}::text"
        sep = _normalize_separator(sep_arg)
        return f"STRING_AGG({expr_cast}, {sep}){order_clause}"

    return pattern.sub(replace, sql)


def _split_args_top(text: str):
    args = []
    buf = []
    depth = 0
    in_str = False
    quote = None
    for ch in text:
        if in_str:
            buf.append(ch)
            if ch == quote:
                in_str = False
            continue
        if ch in {"'", '"'}:
            in_str = True
            quote = ch
            buf.append(ch)
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(buf).strip())
            buf = []
            continue
        buf.append(ch)
    if buf:
        args.append("".join(buf).strip())
    return [arg for arg in args if arg]


def _normalize_separator(sep: str) -> str:
    if not sep:
        return "','"
    sep = sep.strip()
    if sep.startswith("'") and sep.endswith("'"):
        return sep
    if sep.startswith('"') and sep.endswith('"'):
        return sep
    if len(sep) == 1:
        return f"'{sep}'"
    return f"'{sep}'"
