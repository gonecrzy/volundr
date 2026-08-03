"""Conservative lexical-scope analysis for provider-owned Python bodies."""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass, field
from typing import Any


APPROVED_MODULE_ALIASES = frozenset({"cq"})
APPROVED_HELPERS = frozenset(
    {
        "circular_pattern_points",
        "linear_pattern_points",
        "make_hole_pattern",
        "place_pattern_cutters",
        "rectangular_pattern_points",
        "resolve_pattern_points",
    }
)
APPROVED_BUILTINS = frozenset(
    {
        "Exception",
        "ValueError",
        "TypeError",
        "IndexError",
        "KeyError",
        "RuntimeError",
        "abs",
        "all",
        "any",
        "bool",
        "dict",
        "enumerate",
        "float",
        "int",
        "len",
        "list",
        "max",
        "min",
        "range",
        "round",
        "set",
        "str",
        "sum",
        "tuple",
        "zip",
    }
)
PROHIBITED_NAMES = frozenset(
    {
        "__builtins__",
        "builtins",
        "os",
        "pathlib",
        "shutil",
        "subprocess",
        "sys",
    }
)


@dataclass(frozen=True)
class SymbolAnalysis:
    """Stable evidence and blocking findings from one function body."""

    findings: tuple[dict[str, Any], ...] = ()
    classifications: tuple[dict[str, Any], ...] = ()


@dataclass
class _State:
    definite: set[str] = field(default_factory=set)
    conditional: set[str] = field(default_factory=set)

    def clone(self) -> _State:
        return _State(set(self.definite), set(self.conditional))

    def bind(self, name: str, *, definite: bool = True) -> None:
        if definite:
            self.definite.add(name)
            self.conditional.discard(name)
        else:
            if name not in self.definite:
                self.conditional.add(name)

    def discard(self, name: str) -> None:
        self.definite.discard(name)
        self.conditional.discard(name)


class _Analyzer:
    def __init__(
        self,
        *,
        function_id: str,
        function_node: ast.FunctionDef,
        parameter_ids: set[str],
        approved_modules: set[str],
        approved_helpers: set[str],
        approved_builtins: set[str],
        scaffold_owned_identifiers: set[str],
        source_text: str | None,
    ) -> None:
        self.function_id = function_id
        self.function_node = function_node
        self.parameter_ids = set(parameter_ids)
        self.approved = (
            set(approved_modules) | set(approved_helpers) | set(approved_builtins)
        )
        self.approved_modules = set(approved_modules)
        self.approved_helpers = set(approved_helpers)
        self.approved_builtins = set(approved_builtins)
        self.scaffold_owned = set(scaffold_owned_identifiers)
        self.source_text = source_text
        self.findings: list[dict[str, Any]] = []
        self.classifications: list[dict[str, Any]] = []

    def run(self) -> SymbolAnalysis:
        argument_names = {
            argument.arg
            for argument in (
                list(self.function_node.args.posonlyargs)
                + list(self.function_node.args.args)
                + list(self.function_node.args.kwonlyargs)
            )
        }
        state = _State(definite=argument_names)
        for statement in self.function_node.body:
            self._statement(statement, state)
        return SymbolAnalysis(tuple(self.findings), tuple(self.classifications))

    def _statement(self, statement: ast.stmt, state: _State) -> None:
        if isinstance(statement, ast.Assign):
            self._expression(statement.value, state)
            for target in statement.targets:
                self._target(target, state)
            return
        if isinstance(statement, ast.AnnAssign):
            self._expression(statement.annotation, state)
            if statement.value is not None:
                self._expression(statement.value, state)
            self._target(statement.target, state)
            return
        if isinstance(statement, ast.AugAssign):
            self._expression(statement.target, state, load_target=True)
            self._expression(statement.value, state)
            self._target(statement.target, state)
            return
        if isinstance(statement, ast.Expr):
            self._expression(statement.value, state)
            return
        if isinstance(statement, ast.If):
            self._expression(statement.test, state)
            body_state = state.clone()
            for child in statement.body:
                self._statement(child, body_state)
            else_state = state.clone()
            for child in statement.orelse:
                self._statement(child, else_state)
            self._merge_branch_states(state, body_state, else_state)
            return
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            self._expression(statement.iter, state)
            body_state = state.clone()
            self._target(statement.target, body_state)
            for child in statement.body:
                self._statement(child, body_state)
            else_state = body_state.clone()
            for child in statement.orelse:
                self._statement(child, else_state)
            self._merge_loop_state(state, body_state, else_state)
            return
        if isinstance(statement, (ast.While,)):
            self._expression(statement.test, state)
            body_state = state.clone()
            for child in statement.body:
                self._statement(child, body_state)
            else_state = body_state.clone()
            for child in statement.orelse:
                self._statement(child, else_state)
            self._merge_loop_state(state, body_state, else_state)
            return
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            body_state = state.clone()
            for item in statement.items:
                self._expression(item.context_expr, body_state)
                if item.optional_vars is not None:
                    self._target(item.optional_vars, body_state)
            for child in statement.body:
                self._statement(child, body_state)
            state.definite = body_state.definite
            state.conditional = body_state.conditional
            return
        if isinstance(statement, ast.Try):
            try_state = state.clone()
            for child in statement.body:
                self._statement(child, try_state)
            paths = [try_state]
            for handler in statement.handlers:
                handler_state = state.clone()
                if handler.type is not None:
                    self._expression(handler.type, handler_state)
                if handler.name:
                    handler_state.bind(handler.name)
                for child in handler.body:
                    self._statement(child, handler_state)
                # Python deletes ``except ... as name`` after the handler.
                if handler.name:
                    handler_state.discard(handler.name)
                paths.append(handler_state)
            merged = self._intersection_state(paths)
            if statement.finalbody:
                for child in statement.finalbody:
                    self._statement(child, merged)
            state.definite = merged.definite
            state.conditional = merged.conditional
            return
        if isinstance(statement, ast.NamedExpr):
            self._expression(statement.value, state)
            self._target(statement.target, state)
            return
        # Generic statements are deliberately limited to expression loads. The
        # canonicalizer rejects unsupported control constructs separately.
        for child in ast.iter_child_nodes(statement):
            if isinstance(child, ast.expr):
                self._expression(child, state)

    def _expression(
        self,
        expression: ast.AST,
        state: _State,
        *,
        load_target: bool = False,
    ) -> None:
        if isinstance(expression, ast.Name):
            if isinstance(expression.ctx, ast.Load) or load_target:
                self._load(expression, state)
            return
        if isinstance(expression, ast.NamedExpr):
            self._expression(expression.value, state)
            self._target(expression.target, state)
            return
        if isinstance(expression, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            self._comprehension(expression, state)
            return
        if isinstance(expression, ast.DictComp):
            self._comprehension(expression, state)
            return
        for child in ast.iter_child_nodes(expression):
            self._expression(child, state)

    def _comprehension(self, expression: ast.AST, state: _State) -> None:
        scoped = state.clone()
        generators = list(getattr(expression, "generators", ()))
        for generator in generators:
            self._expression(generator.iter, scoped)
            self._target(generator.target, scoped)
            for condition in generator.ifs:
                self._expression(condition, scoped)
        if isinstance(expression, ast.DictComp):
            self._expression(expression.key, scoped)
            self._expression(expression.value, scoped)
        else:
            self._expression(expression.elt, scoped)

    def _target(self, target: ast.AST, state: _State) -> None:
        if isinstance(target, ast.Name):
            state.bind(target.id)
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._target(element, state)
            return
        if isinstance(target, ast.Starred):
            self._target(target.value, state)
            return
        # Attribute and subscript assignment still evaluates their receiver and
        # index expressions, but does not bind a new local name.
        self._expression(target, state, load_target=True)

    def _load(self, node: ast.Name, state: _State) -> None:
        name = node.id
        if name in self.approved:
            if name in self.approved_modules:
                category = "approved_module"
            elif name in self.approved_helpers:
                category = "approved_scaffold_symbol"
            else:
                category = "approved_builtin"
        elif name in state.definite:
            argument_names = {
                argument.arg
                for argument in (
                    list(self.function_node.args.posonlyargs)
                    + list(self.function_node.args.args)
                    + list(self.function_node.args.kwonlyargs)
                )
            }
            category = "function_argument" if name in argument_names else "definitely_assigned_local"
        elif name in state.conditional:
            category = "conditionally_assigned_local"
        elif name in PROHIBITED_NAMES:
            category = "prohibited"
        elif name in self.parameter_ids:
            category = "invalid_parameter_access"
        else:
            category = "unbound"

        evidence = {
            "function_id": self.function_id,
            "symbol": name,
            "classification": category,
            "lineno": getattr(node, "lineno", None),
            "col_offset": getattr(node, "col_offset", None),
        }
        self.classifications.append(evidence)
        if category in {
            "approved_module",
            "approved_scaffold_symbol",
            "approved_builtin",
            "function_argument",
            "definitely_assigned_local",
        }:
            return
        self.findings.append(self._finding(node, category, state))

    def _finding(self, node: ast.Name, category: str, state: _State) -> dict[str, Any]:
        if category == "invalid_parameter_access":
            rule_id = "geometry_body.invalid_parameter_access"
            message = (
                f"Geometry function `{self.function_id}` references parameter `{node.id}` "
                "as a bare Python name; use the approved params access interface."
            )
        elif category == "conditionally_assigned_local":
            rule_id = "geometry_body.conditionally_bound_name"
            message = (
                f"Geometry function `{self.function_id}` uses `{node.id}` before it is "
                "definitely assigned on every path."
            )
        elif category == "prohibited":
            rule_id = "geometry_body.prohibited_name"
            message = f"Geometry function `{self.function_id}` uses prohibited name `{node.id}`."
        else:
            rule_id = "geometry_body.unbound_name"
            message = f"Geometry function `{self.function_id}` uses unbound name `{node.id}`."
        available = sorted(
            self.approved
            | state.definite
            | state.conditional
        )
        parameter_match = node.id if node.id in self.parameter_ids else None
        finding = {
            "rule_id": rule_id,
            "category": "source_symbols",
            "severity": "critical",
            "is_blocking": True,
            "blocking": True,
            "message": message,
            "function_id": self.function_id,
            "symbol": node.id,
            "lineno": getattr(node, "lineno", None),
            "col_offset": getattr(node, "col_offset", None),
            "source_statement": ast.get_source_segment(self.source_text, node)
            if self.source_text is not None
            else None,
            "available_names": available,
            "matched_parameter_id": parameter_match,
            "approved_access": "params[...]" if parameter_match else None,
            "repair_available": True,
            "classification": category,
        }
        return finding

    @staticmethod
    def _merge_branch_states(target: _State, left: _State, right: _State) -> None:
        all_bound = (left.definite | left.conditional | right.definite | right.conditional)
        target.definite = left.definite & right.definite
        target.conditional = all_bound - target.definite

    @staticmethod
    def _merge_loop_state(target: _State, body: _State, else_state: _State) -> None:
        # A loop may execute zero times, so bindings first introduced in the
        # body are conditional after the loop. The loop body itself was
        # analyzed with its target definitely bound.
        all_bound = target.definite | target.conditional | body.definite | body.conditional | else_state.definite | else_state.conditional
        target.definite = target.definite & else_state.definite
        target.conditional = all_bound - target.definite

    @staticmethod
    def _intersection_state(states: list[_State]) -> _State:
        if not states:
            return _State()
        definite = set.intersection(*(state.definite for state in states))
        all_bound: set[str] = set()
        for state in states:
            all_bound |= state.definite | state.conditional
        return _State(definite=definite, conditional=all_bound - definite)


def analyze_function_symbols(
    function_node: ast.FunctionDef,
    *,
    function_id: str,
    parameter_ids: set[str],
    approved_modules: set[str] | None = None,
    approved_helpers: set[str] | None = None,
    approved_builtins: set[str] | None = None,
    scaffold_owned_identifiers: set[str] | None = None,
    source_text: str | None = None,
) -> SymbolAnalysis:
    """Analyze loaded names using the exact scaffold-owned function scope."""

    return _Analyzer(
        function_id=function_id,
        function_node=function_node,
        parameter_ids=parameter_ids,
        approved_modules=approved_modules or set(APPROVED_MODULE_ALIASES),
        approved_helpers=approved_helpers or set(APPROVED_HELPERS),
        approved_builtins=approved_builtins or set(APPROVED_BUILTINS),
        scaffold_owned_identifiers=scaffold_owned_identifiers or set(),
        source_text=source_text,
    ).run()


def allowed_symbol_inventory(
    *,
    signature: str,
    parameter_ids: set[str],
    scaffold_owned_identifiers: set[str],
    approved_helpers: set[str] | None = None,
) -> dict[str, Any]:
    """Return prompt-safe symbol authority for one scaffold signature."""

    tree = ast.parse(f"def _inventory{signature}:\n    pass\n")
    function = tree.body[0]
    arguments = [argument.arg for argument in function.args.args]  # type: ignore[attr-defined]
    return {
        "signature": signature,
        "function_arguments": arguments,
        "approved_module_aliases": sorted(APPROVED_MODULE_ALIASES),
        "approved_helpers": sorted(approved_helpers or APPROVED_HELPERS),
        "approved_builtins": sorted(APPROVED_BUILTINS),
        "parameter_access": "params[<parameter_id>] or params.get(<parameter_id>)",
        "authorized_parameter_ids": sorted(parameter_ids),
        "prohibited_bare_parameter_names": sorted(parameter_ids),
        "scaffold_owned_identifiers": sorted(scaffold_owned_identifiers),
    }


def builtins_inventory() -> set[str]:
    """Expose only the approved builtin subset for callers and tests."""

    return set(APPROVED_BUILTINS) & set(dir(builtins))


def analyze_scaffold_source(source: str) -> list[dict[str, Any]]:
    """Check deterministic scaffold functions against their module globals."""

    tree = ast.parse(source)
    global_names: set[str] = set()
    imported_names: set[str] = set()
    function_nodes: list[ast.FunctionDef] = []
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                imported_names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                if alias.name != "*":
                    imported_names.add(alias.asname or alias.name)
        elif isinstance(statement, ast.FunctionDef):
            global_names.add(statement.name)
            function_nodes.append(statement)
        elif isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    global_names.add(target.id)
    global_names |= imported_names
    findings: list[dict[str, Any]] = []
    for function in function_nodes:
        analysis = analyze_function_symbols(
            function,
            function_id=function.name,
            parameter_ids=set(),
            approved_modules=imported_names,
            approved_helpers=global_names - imported_names,
            source_text=source,
        )
        findings.extend(analysis.findings)
    return findings
