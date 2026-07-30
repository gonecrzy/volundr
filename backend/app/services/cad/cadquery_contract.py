import ast


class CadQueryContractError(ValueError):
    pass


SAFE_CALL_NAMES = frozenset(
    {
        "abs",
        "bool",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "range",
        "round",
        "str",
        "sum",
        "tuple",
    }
)

UNSAFE_CALL_NAMES = frozenset(
    {
        "__import__",
        "compile",
        "eval",
        "exec",
        "globals",
        "getattr",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
    }
)

ALLOWED_TOP_LEVEL_NODE_TYPES = (
    ast.Import,
    ast.Assign,
    ast.AnnAssign,
    ast.FunctionDef,
    ast.ClassDef,
)

ALLOWED_CONSTANT_TYPES = (str, int, float, bool, type(None))


def validate_cadquery_source(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CadQueryContractError(f"invalid Python syntax: {exc.msg}") from exc

    function_names = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    has_build_model = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            raise CadQueryContractError("only `import cadquery as cq` is allowed")
        if not isinstance(node, ALLOWED_TOP_LEVEL_NODE_TYPES):
            raise CadQueryContractError(
                f"unsupported top-level statement: {type(node).__name__}"
            )
        if isinstance(node, ast.Import):
            _validate_import(node)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            _validate_top_level_assignment(node)
        elif isinstance(node, ast.FunctionDef):
            if node.name == "build_model":
                has_build_model = True
            _validate_function(node, function_names=function_names)
        elif isinstance(node, ast.ClassDef):
            _validate_class(node)

    if not has_build_model:
        raise CadQueryContractError("source must define build_model()")


def _validate_import(node: ast.Import) -> None:
    if len(node.names) != 1:
        raise CadQueryContractError("only `import cadquery as cq` is allowed")
    alias = node.names[0]
    if alias.name != "cadquery" or alias.asname != "cq":
        raise CadQueryContractError("only `import cadquery as cq` is allowed")


def _validate_top_level_assignment(node: ast.Assign | ast.AnnAssign) -> None:
    targets: list[ast.expr]
    value: ast.expr | None
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
        value = node.value
    else:
        targets = [node.target]
        value = node.value
    if len(targets) != 1 or not isinstance(targets[0], ast.Name):
        raise CadQueryContractError("top-level assignment targets must be simple names")
    if value is None or not _is_constant_value(value):
        raise CadQueryContractError("top-level assignment values must be literal parameters")


def _validate_function(node: ast.FunctionDef, *, function_names: set[str]) -> None:
    if node.decorator_list:
        raise CadQueryContractError("function decorators are not allowed in cadquery-v1")
    if node.args.vararg or node.args.kwarg:
        raise CadQueryContractError("variadic function arguments are not allowed")
    _validate_body(node, function_names=function_names)


def _validate_class(node: ast.ClassDef) -> None:
    if node.decorator_list:
        raise CadQueryContractError("class decorators are not allowed in cadquery-v1")
    if node.keywords:
        raise CadQueryContractError("class keyword arguments are not allowed")
    for base in node.bases:
        if not isinstance(base, ast.Name):
            raise CadQueryContractError("class bases must be simple names")
    for child in node.body:
        if not isinstance(child, ast.AnnAssign):
            raise CadQueryContractError("classes may only declare annotated parameter fields")
        _validate_top_level_assignment(child)


def _validate_body(node: ast.AST, *, function_names: set[str]) -> None:
    for child in ast.walk(node):
        if isinstance(child, ast.Import | ast.ImportFrom):
            raise CadQueryContractError("imports are only allowed at top level")
        if isinstance(child, ast.Global | ast.Nonlocal):
            raise CadQueryContractError("global/nonlocal statements are not allowed")
        if isinstance(child, ast.Try):
            raise CadQueryContractError("try/except is not allowed in generated CadQuery source")
        if isinstance(child, ast.With | ast.AsyncWith):
            raise CadQueryContractError("with statements are not allowed")
        if isinstance(child, ast.Call):
            _validate_call(child, function_names=function_names)
        if isinstance(child, ast.Attribute):
            if child.attr.startswith("__"):
                raise CadQueryContractError("dunder attribute access is not allowed")


def _validate_call(node: ast.Call, *, function_names: set[str]) -> None:
    name = _call_name(node.func)
    if name in UNSAFE_CALL_NAMES:
        raise CadQueryContractError(f"unsafe call is not allowed: {name}")
    if name is None:
        raise CadQueryContractError("dynamic calls are not allowed")
    if isinstance(node.func, ast.Name) and name not in SAFE_CALL_NAMES:
        if name not in function_names:
            raise CadQueryContractError(f"unsupported direct function call: {name}")


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_constant_value(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, ALLOWED_CONSTANT_TYPES)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        return _is_constant_value(node.operand)
    if isinstance(node, ast.List | ast.Tuple):
        return all(_is_constant_value(element) for element in node.elts)
    return False
