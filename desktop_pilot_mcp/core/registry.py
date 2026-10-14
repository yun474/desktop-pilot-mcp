"""注册表读写（标准库 winreg），始终访问 64 位视图。"""

from __future__ import annotations

import winreg

_ROOTS = {
    "HKCU": winreg.HKEY_CURRENT_USER, "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKLM": winreg.HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKCR": winreg.HKEY_CLASSES_ROOT, "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
    "HKU": winreg.HKEY_USERS, "HKEY_USERS": winreg.HKEY_USERS,
    "HKCC": winreg.HKEY_CURRENT_CONFIG, "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
}
_TYPES = {
    "REG_SZ": winreg.REG_SZ, "REG_EXPAND_SZ": winreg.REG_EXPAND_SZ, "REG_DWORD": winreg.REG_DWORD,
    "REG_QWORD": winreg.REG_QWORD, "REG_MULTI_SZ": winreg.REG_MULTI_SZ, "REG_BINARY": winreg.REG_BINARY,
}
_TYPE_NAMES = {v: k for k, v in _TYPES.items()}
_VIEW = winreg.KEY_WOW64_64KEY
LIST_LIMIT = 200


def _parse(path: str) -> tuple[int, str, str]:
    """返回 (根键, 子路径, 规范化的完整路径)。兼容 HKCU\\x、HKCU:\\x、HKEY_CURRENT_USER\\x 写法。"""
    cleaned = path.strip().replace("/", "\\")
    if cleaned.lower().startswith("registry::"):
        cleaned = cleaned[len("registry::"):]
    root_name, _, sub = cleaned.partition("\\")
    root_name = root_name.rstrip(":").upper()
    if root_name not in _ROOTS:
        raise ValueError(f"无法识别的注册表根键「{root_name}」，可用：HKCU、HKLM、HKCR、HKU、HKCC")
    sub = sub.strip("\\")
    return _ROOTS[root_name], sub, f"{root_name}\\{sub}"


def _format(value, vtype: int) -> str:
    if vtype == winreg.REG_BINARY:
        return value.hex(" ") if value else "(空)"
    if vtype == winreg.REG_MULTI_SZ:
        return " | ".join(value)
    return str(value)


def get(path: str, name: str) -> str:
    root, sub, full = _parse(path)
    with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | _VIEW) as key:
        value, vtype = winreg.QueryValueEx(key, name)
    return f"{full} -> {name or '(默认)'} = {_format(value, vtype)}（{_TYPE_NAMES.get(vtype, vtype)}）"


def set_value(path: str, name: str, value: str, value_type: str = "REG_SZ") -> str:
    root, sub, full = _parse(path)
    vtype_name = value_type.upper()
    if vtype_name not in _TYPES:
        raise ValueError(f"不支持的类型 {value_type}，可用：{', '.join(_TYPES)}")
    vtype = _TYPES[vtype_name]
    if vtype in (winreg.REG_DWORD, winreg.REG_QWORD):
        data = int(value, 0)
    elif vtype == winreg.REG_MULTI_SZ:
        data = value.split("\n")
    elif vtype == winreg.REG_BINARY:
        data = bytes.fromhex(value.replace(" ", ""))
    else:
        data = value
    with winreg.CreateKeyEx(root, sub, 0, winreg.KEY_WRITE | _VIEW) as key:
        winreg.SetValueEx(key, name, 0, vtype, data)
    return f"已设置 {full} -> {name or '(默认)'} = {value}（{vtype_name}）"


def _delete_tree(root: int, sub: str) -> None:
    with winreg.OpenKey(root, sub, 0, winreg.KEY_ALL_ACCESS | _VIEW) as key:
        children = []
        i = 0
        while True:
            try:
                children.append(winreg.EnumKey(key, i))
            except OSError:
                break
            i += 1
    for child in children:
        _delete_tree(root, f"{sub}\\{child}")
    winreg.DeleteKeyEx(root, sub, _VIEW)


def delete(path: str, name: str | None) -> str:
    """提供 name 时删除该值；否则删除整个键（包括所有子键）。"""
    root, sub, full = _parse(path)
    if name is not None:
        with winreg.OpenKey(root, sub, 0, winreg.KEY_SET_VALUE | _VIEW) as key:
            winreg.DeleteValue(key, name)
        return f"已删除值 {full} -> {name or '(默认)'}"
    if not sub:
        raise ValueError("不能删除根键")
    _delete_tree(root, sub)
    return f"已删除键 {full} 及其所有子键"


def list_key(path: str) -> str:
    root, sub, full = _parse(path)
    subkeys, values = [], []
    with winreg.OpenKey(root, sub, 0, winreg.KEY_READ | _VIEW) as key:
        n_sub, n_val, _ = winreg.QueryInfoKey(key)
        for i in range(min(n_sub, LIST_LIMIT)):
            subkeys.append(winreg.EnumKey(key, i))
        for i in range(min(n_val, LIST_LIMIT)):
            vname, value, vtype = winreg.EnumValue(key, i)
            text = _format(value, vtype)
            values.append(f"  {vname or '(默认)'} = {text[:200]}（{_TYPE_NAMES.get(vtype, vtype)}）")
    lines = [f"{full}", f"子键（{n_sub} 个）："]
    lines += [f"  {s}" for s in subkeys] or ["  (无)"]
    lines.append(f"值（{n_val} 个）：")
    lines += values or ["  (无)"]
    if n_sub > LIST_LIMIT or n_val > LIST_LIMIT:
        lines.append(f"（只列出前 {LIST_LIMIT} 项）")
    return "\n".join(lines)
