import ast
from dataclasses import dataclass, field


class CadQueryContractError(ValueError):
    pass


@dataclass(frozen=True)
class CadQuerySourceMetadata:
    contract_version: str
    entrypoint: str
    parameter_ids: list[str] = field(default_factory=list)
    parameter_defaults: dict[str, str | int | float | bool] = field(default_factory=dict)
    output_ids: list[str] = field(default_factory=list)
    output_component_ids: dict[str, list[str]] = field(default_factory=dict)
    component_ids: list[str] = field(default_factory=list)
    expected_solid_counts: dict[str, int] = field(default_factory=dict)


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

RUNTIME_IMPORT_NAMES = frozenset(
    {
        "ParameterSpec",
        "ParameterValidationError",
        "ParameterValues",
        "PrintableOutput",
        "Product",
    }
)

RUNTIME_CONSTRUCTOR_NAMES = frozenset({"ParameterSpec", "PrintableOutput", "Product"})

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


def validate_cadquery_source(
    source: str,
    *,
    contract_version: str = "cadquery-probe-v1",
) -> CadQuerySourceMetadata:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise CadQueryContractError(f"invalid Python syntax: {exc.msg}") from exc

    strict_v1 = contract_version == "cadquery-v1"
    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    has_build_model = False
    build_function: ast.FunctionDef | None = None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            _validate_import_from(node, strict_v1=strict_v1)
            continue
        if not isinstance(node, ALLOWED_TOP_LEVEL_NODE_TYPES):
            raise CadQueryContractError(
                f"unsupported top-level statement: {type(node).__name__}"
            )
        if isinstance(node, ast.Import):
            _validate_import(node)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            _validate_top_level_assignment(node, strict_v1=strict_v1)
        elif isinstance(node, ast.FunctionDef):
            if node.name == "build_model":
                has_build_model = True
            if node.name == "build":
                build_function = node
            _validate_function(node, function_names=function_names, strict_v1=strict_v1)
        elif isinstance(node, ast.ClassDef):
            _validate_class(node)

    if strict_v1:
        if build_function is None:
            raise CadQueryContractError("cadquery-v1 source must define build(params)")
        _validate_build_entrypoint(build_function)
        metadata = _collect_cadquery_v1_metadata(tree)
        if not metadata.output_ids:
            raise CadQueryContractError("cadquery-v1 source must define at least one PrintableOutput")
        if not _has_call_named(tree, "Product"):
            raise CadQueryContractError("cadquery-v1 source must return a Product")
        return metadata

    if not has_build_model:
        raise CadQueryContractError("source must define build_model()")
    return CadQuerySourceMetadata(
        contract_version=contract_version,
        entrypoint="build_model",
    )


def _validate_import(node: ast.Import) -> None:
    if len(node.names) != 1:
        raise CadQueryContractError("only `import cadquery as cq` is allowed")
    alias = node.names[0]
    if alias.name != "cadquery" or alias.asname != "cq":
        raise CadQueryContractError("only `import cadquery as cq` is allowed")


def _validate_import_from(node: ast.ImportFrom, *, strict_v1: bool) -> None:
    if not strict_v1:
        raise CadQueryContractError("only `import cadquery as cq` is allowed")
    if node.module != "volundr_cad.runtime":
        raise CadQueryContractError("only Volundr runtime imports are allowed")
    imported = {alias.name for alias in node.names}
    if any(alias.asname for alias in node.names) or not imported.issubset(RUNTIME_IMPORT_NAMES):
        raise CadQueryContractError("unsupported Volundr runtime import")


def _validate_top_level_assignment(node: ast.Assign | ast.AnnAssign, *, strict_v1: bool = False) -> None:
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
    if value is None:
        raise CadQueryContractError("top-level assignment values must be literal parameters")
    if strict_v1 and _is_runtime_metadata_value(value):
        return
    if not _is_constant_value(value):
        raise CadQueryContractError("top-level assignment values must be literal parameters")


def _validate_function(
    node: ast.FunctionDef,
    *,
    function_names: set[str],
    strict_v1: bool = False,
) -> None:
    if node.decorator_list:
        raise CadQueryContractError("function decorators are not allowed in cadquery-v1")
    if node.args.vararg or node.args.kwarg:
        raise CadQueryContractError("variadic function arguments are not allowed")
    _validate_body(node, function_names=function_names, strict_v1=strict_v1)


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


def _validate_body(node: ast.AST, *, function_names: set[str], strict_v1: bool = False) -> None:
    for child in ast.walk(node):
        if isinstance(child, ast.FunctionDef) and child is not node:
            if child.decorator_list:
                raise CadQueryContractError(
                    "function decorators are not allowed in cadquery-v1"
                )
            if child.args.vararg or child.args.kwarg:
                raise CadQueryContractError("variadic function arguments are not allowed")
        if isinstance(child, ast.Import | ast.ImportFrom):
            raise CadQueryContractError("imports are only allowed at top level")
        if isinstance(child, ast.Global | ast.Nonlocal):
            raise CadQueryContractError("global/nonlocal statements are not allowed")
        if isinstance(child, ast.Try):
            raise CadQueryContractError("try/except is not allowed in generated CadQuery source")
        if isinstance(child, ast.With | ast.AsyncWith):
            raise CadQueryContractError("with statements are not allowed")
        if isinstance(child, ast.Call):
            _validate_call(child, function_names=function_names, strict_v1=strict_v1)
        if isinstance(child, ast.Attribute):
            if child.attr.startswith("__"):
                raise CadQueryContractError("dunder attribute access is not allowed")


def _validate_call(node: ast.Call, *, function_names: set[str], strict_v1: bool = False) -> None:
    dotted_name = _call_dotted_name(node.func)
    if strict_v1 and dotted_name == "cq.exporters.export":
        raise CadQueryContractError("generated source cannot perform artifact writing")
    name = _call_name(node.func)
    if name in UNSAFE_CALL_NAMES:
        raise CadQueryContractError(f"unsafe call is not allowed: {name}")
    if name is None:
        raise CadQueryContractError("dynamic calls are not allowed")
    if isinstance(node.func, ast.Name) and name not in SAFE_CALL_NAMES:
        if name not in function_names and (not strict_v1 or name not in RUNTIME_CONSTRUCTOR_NAMES):
            raise CadQueryContractError(f"unsupported direct function call: {name}")


def _call_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _call_dotted_name(node: ast.expr) -> str | None:
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _is_constant_value(node: ast.expr) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, ALLOWED_CONSTANT_TYPES)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
        return _is_constant_value(node.operand)
    if isinstance(node, ast.List | ast.Tuple):
        return all(_is_constant_value(element) for element in node.elts)
    return False


def _is_runtime_metadata_value(node: ast.expr) -> bool:
    if _is_constant_value(node):
        return True
    if isinstance(node, ast.List | ast.Tuple):
        return all(_is_runtime_metadata_value(element) for element in node.elts)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id != "ParameterSpec":
            return False
        return all(_keyword_value_is_static(keyword.value) for keyword in node.keywords)
    return False


def _keyword_value_is_static(node: ast.expr) -> bool:
    if _is_constant_value(node):
        return True
    if isinstance(node, ast.List | ast.Tuple):
        return all(_is_constant_value(element) for element in node.elts)
    return False


def _validate_build_entrypoint(node: ast.FunctionDef) -> None:
    positional_args = list(node.args.posonlyargs) + list(node.args.args)
    if len(positional_args) != 1 or positional_args[0].arg != "params":
        raise CadQueryContractError("cadquery-v1 source must define build(params)")
    if node.args.defaults or node.args.kw_defaults or node.args.kwonlyargs:
        raise CadQueryContractError("build(params) cannot define default or keyword-only arguments")


def _collect_cadquery_v1_metadata(tree: ast.Module) -> CadQuerySourceMetadata:
    parameter_ids: list[str] = []
    parameter_defaults: dict[str, str] = {}
    output_ids: list[str] = []
    output_component_ids: dict[str, list[str]] = {}
    component_ids: list[str] = []
    expected_solid_counts: dict[str, int] = {}
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        name = _call_name(call.func)
        if name == "ParameterSpec":
            parameter_id = _string_keyword(call, "id")
            if parameter_id:
                parameter_ids.append(parameter_id)
                default_value = _static_keyword_value(call, "default")
                if default_value is not None:
                    parameter_defaults[parameter_id] = default_value
        elif name == "PrintableOutput":
            output_id = _string_keyword(call, "output_id")
            if output_id:
                output_ids.append(output_id)
            component_id = _string_keyword(call, "component_id")
            output_components: list[str] = []
            if component_id:
                component_ids.append(component_id)
                output_components.append(component_id)
            for value in _string_list_keyword(call, "component_ids"):
                component_ids.append(value)
                output_components.append(value)
            if output_id:
                output_component_ids[output_id] = _dedupe(output_components)
            expected_solid_count = _int_keyword(call, "expected_solid_count")
            if output_id and expected_solid_count is not None:
                expected_solid_counts[output_id] = expected_solid_count
    return CadQuerySourceMetadata(
        contract_version="cadquery-v1",
        entrypoint="build",
        parameter_ids=_dedupe(parameter_ids),
        parameter_defaults=parameter_defaults,
        output_ids=_dedupe(output_ids),
        output_component_ids=output_component_ids,
        component_ids=_dedupe(component_ids),
        expected_solid_counts=expected_solid_counts,
    )


def _has_call_named(tree: ast.Module, name: str) -> bool:
    return any(
        isinstance(node, ast.Call) and _call_name(node.func) == name
        for node in ast.walk(tree)
    )


def _string_keyword(node: ast.Call, name: str) -> str | None:
    value = _keyword(node, name)
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _int_keyword(node: ast.Call, name: str) -> int | None:
    value = _keyword(node, name)
    if isinstance(value, ast.Constant) and isinstance(value.value, int):
        return value.value
    return None


def _static_keyword_value(node: ast.Call, name: str) -> str | int | float | bool | None:
    value = _keyword(node, name)
    if isinstance(value, ast.Constant) and isinstance(value.value, str | int | float | bool):
        return value.value
    if isinstance(value, ast.UnaryOp) and isinstance(value.op, ast.USub | ast.UAdd):
        operand = value.operand
        if isinstance(operand, ast.Constant) and isinstance(operand.value, int | float):
            return -operand.value if isinstance(value.op, ast.USub) else operand.value
    return None


def _string_list_keyword(node: ast.Call, name: str) -> list[str]:
    value = _keyword(node, name)
    if not isinstance(value, ast.List | ast.Tuple):
        return []
    return [
        element.value
        for element in value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    ]


def _keyword(node: ast.Call, name: str) -> ast.expr | None:
    for keyword in node.keywords:
        if keyword.arg == name:
            return keyword.value
    return None


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
