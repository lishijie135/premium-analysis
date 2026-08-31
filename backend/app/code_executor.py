# -*- coding: utf-8 -*-
"""安全代码执行器：在受限命名空间中执行 LLM 生成的 Pandas 分析代码。

核心职责：
1. 安全沙箱 —— AST 预扫描 + 正则过滤，拦截危险模块/函数调用
2. 受限命名空间 —— 仅注入 df / pd / np / json / math / datetime
3. 超时控制 —— 线程 + timeout（默认 30 秒）
4. 输出捕获 —— 重定向 stdout 到 StringIO
5. 自动校验 —— 将执行结果与预计算基准交叉比对
"""
import ast
import io
import json
import logging
import math
import re
import threading
from datetime import datetime
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("code_executor")

# ---------------------------------------------------------------------------
# 安全策略：禁止出现的模块名 / 函数名
# ---------------------------------------------------------------------------
_FORBIDDEN_IMPORTS = {
    "os", "subprocess", "sys", "shutil", "socket", "http", "urllib",
    "requests", "ftplib", "telnetlib", "xmlrpc", "ctypes", "importlib",
    "pickle", "shelve", "marshal", "tempfile", "pathlib", "glob",
    "signal", "multiprocessing", "threading_mod", "webbrowser",
    "sqlite3", "dbm", "csv_mod",
}

_FORBIDDEN_CALLS = {
    "open", "exec", "eval", "compile", "__import__",
    "getattr", "setattr", "delattr", "vars", "globals", "locals",
    "breakpoint", "exit", "quit", "help", "input",
}

# 正则：检测危险模式（在 AST 扫描前做一轮快速拦截）
_DANGEROUS_PATTERNS = [
    re.compile(r"\bimport\s+(os|subprocess|sys|shutil|socket|http|urllib|requests|ctypes|pickle|tempfile|pathlib)\b"),
    re.compile(r"\bfrom\s+(os|subprocess|sys|shutil|socket|http|urllib|requests|ctypes|pickle|tempfile|pathlib)\b"),
    re.compile(r"\b(os|subprocess|sys)\s*\.\s*\w+"),
    re.compile(r"\b__import__\s*\("),
    re.compile(r"\bexec\s*\("),
    re.compile(r"\beval\s*\("),
    re.compile(r"\bopen\s*\("),
    re.compile(r"\bcompile\s*\("),
    re.compile(r"__builtins__"),
]


def _check_safety(code: str) -> Optional[str]:
    """安全检查：正则预扫描 + AST 扫描。返回错误信息或 None（通过）。"""
    # 第一层：正则快速拦截
    for pat in _DANGEROUS_PATTERNS:
        if pat.search(code):
            return f"安全检查未通过：代码包含禁止模式 ({pat.pattern})"

    # 第二层：AST 扫描
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"代码语法错误: {exc}"

    for node in ast.walk(tree):
        # 检查 import 语句
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in _FORBIDDEN_IMPORTS:
                    return f"禁止导入模块: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root in _FORBIDDEN_IMPORTS:
                    return f"禁止导入模块: {node.module}"
        # 检查危险函数调用
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALLS:
                return f"禁止调用函数: {func.id}"
            if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_CALLS:
                return f"禁止调用方法: {func.attr}"

    return None


# ---------------------------------------------------------------------------
# 白名单内置函数（替换 __builtins__）
# ---------------------------------------------------------------------------
_SAFE_BUILTINS = {
    "len": len, "range": range, "str": str, "int": int, "float": float,
    "dict": dict, "list": list, "tuple": tuple, "set": set, "frozenset": frozenset,
    "print": print, "sum": sum, "min": min, "max": max, "abs": abs,
    "round": round, "sorted": sorted, "reversed": reversed,
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
    "isinstance": isinstance, "issubclass": issubclass, "type": type,
    "hasattr": hasattr, "any": any, "all": all,
    "True": True, "False": False, "None": None,
    "bool": bool, "bytes": bytes, "complex": complex,
    "divmod": divmod, "pow": pow, "hash": hash, "id": id,
    "repr": repr, "format": format, "chr": chr, "ord": ord,
    "Exception": Exception, "ValueError": ValueError, "TypeError": TypeError,
    "KeyError": KeyError, "IndexError": IndexError, "AttributeError": AttributeError,
    "RuntimeError": RuntimeError, "StopIteration": StopIteration,
    "ZeroDivisionError": ZeroDivisionError,
}


# ---------------------------------------------------------------------------
# 校验行正则：从 stdout 中提取 [校验] 行
# ---------------------------------------------------------------------------
_VALIDATION_LINE_RE = re.compile(
    r"\[校验\]\s*总行数:\s*(\d+),\s*总保费:\s*([\d.]+),\s*总单量:\s*(\d+)"
)


def _parse_validation_output(stdout_text: str) -> Optional[Dict[str, Any]]:
    """从 stdout 中解析 [校验] 行，返回校验数据或 None。"""
    for line in stdout_text.splitlines():
        m = _VALIDATION_LINE_RE.search(line)
        if m:
            return {
                "code_total_rows": int(m.group(1)),
                "code_total_premium": float(m.group(2)),
                "code_total_policies": int(m.group(3)),
            }
    return None


def _validate_result(
    result: Any,
    stdout_text: str,
    precomputed_stats: Optional[Dict[str, Any]],
    df_row_count: int,
) -> Dict[str, Any]:
    """执行自动校验，返回 validation 字典。

    包含：
    - stdout_validation: 从 print [校验] 行解析的结果 vs precomputed_stats
    - nan_check: result 中是否含 NaN/None
    - warnings: 告警列表
    """
    validation: Dict[str, Any] = {"warnings": []}

    if precomputed_stats is None:
        return validation

    # ---- 1. stdout [校验] 行比对 ----
    code_validation = _parse_validation_output(stdout_text)
    if code_validation:
        stdout_val: Dict[str, Any] = {"code_values": code_validation}
        # 总行数比对
        expected_rows = precomputed_stats.get("total_rows", df_row_count)
        code_rows = code_validation.get("code_total_rows", -1)
        if code_rows != expected_rows:
            stdout_val["row_mismatch"] = {
                "expected": expected_rows, "actual": code_rows,
            }
            validation["warnings"].append(
                f"行数不一致：预期 {expected_rows}，代码报告 {code_rows}"
            )
        # 总保费比对（浮点容差 0.01）
        expected_prem = precomputed_stats.get("total_premium")
        code_prem = code_validation.get("code_total_premium")
        if expected_prem is not None and code_prem is not None:
            if abs(expected_prem - code_prem) > 0.01:
                stdout_val["premium_mismatch"] = {
                    "expected": round(expected_prem, 2),
                    "actual": round(code_prem, 2),
                    "diff": round(abs(expected_prem - code_prem), 2),
                }
                validation["warnings"].append(
                    f"总保费不一致：预期 {expected_prem:.2f}，代码报告 {code_prem:.2f}，差值 {abs(expected_prem - code_prem):.2f}"
                )
        # 总单量比对
        expected_pol = precomputed_stats.get("total_policies")
        code_pol = code_validation.get("code_total_policies")
        if expected_pol is not None and code_pol is not None:
            if expected_pol != code_pol:
                stdout_val["policies_mismatch"] = {
                    "expected": expected_pol, "actual": code_pol,
                }
                validation["warnings"].append(
                    f"总单量不一致：预期 {expected_pol}，代码报告 {code_pol}"
                )
        validation["stdout_validation"] = stdout_val
    else:
        validation["warnings"].append("代码未输出 [校验] 行，跳过 stdout 交叉校验")

    # ---- 2. NaN / None 检查 ----
    nan_fields = _scan_for_nan(result)
    if nan_fields:
        validation["nan_check"] = {"found": True, "fields": nan_fields}
        validation["warnings"].append(f"结果中发现 NaN/None 字段: {', '.join(nan_fields[:5])}")
    else:
        validation["nan_check"] = {"found": False}

    return validation


def _scan_for_nan(obj: Any, prefix: str = "") -> list:
    """递归扫描 dict/list 中的 NaN 和 None 值，返回路径列表。"""
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if v is None:
                found.append(path)
            elif isinstance(v, float) and math.isnan(v):
                found.append(path)
            elif isinstance(v, (dict, list)):
                found.extend(_scan_for_nan(v, path))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            path = f"{prefix}[{i}]"
            if v is None:
                found.append(path)
            elif isinstance(v, float) and math.isnan(v):
                found.append(path)
            elif isinstance(v, (dict, list)):
                found.extend(_scan_for_nan(v, path))
    return found


# ---------------------------------------------------------------------------
# 结果序列化
# ---------------------------------------------------------------------------
def _serialize_result(result: Any) -> Any:
    """将 result 转为 JSON 可序列化对象。"""
    if result is None:
        return None
    if isinstance(result, (dict, list, str, int, float, bool)):
        # 递归处理嵌套的 DataFrame / numpy 类型
        return _deep_serialize(result)
    if isinstance(result, pd.DataFrame):
        return result.to_dict(orient="records")
    if isinstance(result, pd.Series):
        return result.to_dict()
    if isinstance(result, (np.integer,)):
        return int(result)
    if isinstance(result, (np.floating,)):
        return float(result)
    if isinstance(result, np.ndarray):
        return result.tolist()
    # 兜底：转字符串
    return str(result)


def _deep_serialize(obj: Any) -> Any:
    """递归序列化嵌套结构中的 numpy / pandas 类型。"""
    if obj is None:
        return None
    if isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (int,)):
        return int(obj)
    if isinstance(obj, (float,)):
        if math.isnan(obj):
            return None  # NaN → null
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        return None if math.isnan(f) else f
    if isinstance(obj, np.ndarray):
        return [_deep_serialize(x) for x in obj.tolist()]
    if isinstance(obj, pd.DataFrame):
        return obj.to_dict(orient="records")
    if isinstance(obj, pd.Series):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {str(k): _deep_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_deep_serialize(x) for x in obj]
    return str(obj)


# ---------------------------------------------------------------------------
# 主入口：execute_analysis_code
# ---------------------------------------------------------------------------
def execute_analysis_code(
    code: str,
    df: pd.DataFrame,
    precomputed_stats: Optional[Dict[str, Any]] = None,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """在安全沙箱中执行 LLM 生成的分析代码。

    参数:
        code: LLM 生成的 Python 代码（不含 import pandas）
        df: 完整的 cleaned DataFrame
        precomputed_stats: 预计算基准 {total_premium, total_policies, total_rows}
        timeout_seconds: 执行超时秒数（默认 30）

    返回:
        {
            "success": bool,
            "output": str,          # stdout 捕获内容
            "result": any,          # result 变量序列化后的值
            "error": str | None,    # 错误信息
            "validation": dict | None,  # 校验结果
        }
    """
    # 1. 安全检查
    safety_error = _check_safety(code)
    if safety_error:
        logger.warning("代码安全检查未通过: %s", safety_error)
        return {
            "success": False,
            "output": "",
            "result": None,
            "error": safety_error,
            "validation": None,
        }

    # 2. 构建受限命名空间
    safe_builtins = dict(_SAFE_BUILTINS)
    namespace: Dict[str, Any] = {
        "__builtins__": safe_builtins,
        "df": df.copy(),  # 传入副本，防止原始数据被修改
        "pd": pd,
        "np": np,
        "json": json,
        "math": math,
        "datetime": datetime,
        "result": None,
    }

    # 3. 执行代码（线程 + 超时）
    stdout_capture = io.StringIO()
    exec_error: Optional[str] = None
    exec_thread_exception: Optional[BaseException] = None

    def _run():
        nonlocal exec_thread_exception
        old_stdout = None
        try:
            old_stdout = __import__("sys").stdout
            __import__("sys").stdout = stdout_capture
            exec(code, namespace)  # noqa: S102
        except Exception as exc:
            exec_thread_exception = exc
        finally:
            if old_stdout is not None:
                __import__("sys").stdout = old_stdout

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        # 超时：线程仍在运行，放弃等待（daemon 线程会随进程退出）
        exec_error = f"代码执行超时（{timeout_seconds} 秒），已自动终止"
        logger.warning(exec_error)
    elif exec_thread_exception is not None:
        exec_error = f"{type(exec_thread_exception).__name__}: {exec_thread_exception}"
        logger.warning("代码执行异常: %s", exec_error)

    # 4. 获取 stdout 输出
    output_text = stdout_capture.getvalue()
    # 限制输出大小（10KB）
    if len(output_text) > 10240:
        output_text = output_text[:10240] + "\n... [输出已截断，超过 10KB]"

    # 5. 获取 result 变量
    raw_result = namespace.get("result")
    serialized_result = _serialize_result(raw_result)

    # 6. 自动校验
    validation = None
    if exec_error is None:
        validation = _validate_result(
            raw_result, output_text, precomputed_stats, len(df),
        )
        if validation.get("warnings"):
            logger.info("校验告警: %s", validation["warnings"])

    success = exec_error is None
    return {
        "success": success,
        "output": output_text,
        "result": serialized_result,
        "error": exec_error,
        "validation": validation,
    }
