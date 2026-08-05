"""Fail-closed canonicalization for provider geometry-slot representation.

Only representation-level aliases owned by Volundr belong here.  This module
does not invent geometry, repair CadQuery APIs, or accept semantically vacuous
operations merely because a name can be normalized.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from typing import Any


class GeometrySlotContractCanonicalizer:
    """Normalize only unambiguous scaffold aliases in one geometry slot."""

    def canonicalize(self, slot: dict[str, Any]) -> dict[str, Any]:
        original = [str(item) for item in slot.get("statements", [])]
        slot_id = str(slot.get("slot_id"))
        required = str(slot.get("required_result_symbol") or "body")
        inputs = [str(item) for item in slot.get("authoritative_input_symbols", [])]
        allowed = {str(item) for item in slot.get("allowed_names", [])} | set(inputs) | {required}
        if len(inputs) != 1 or inputs[0] != required:
            return self._rejected(slot_id, original, "ambiguous_authoritative_input", ambiguity=True)
        parsed: list[ast.Module] = []
        for statement in original:
            try:
                tree = ast.parse(statement, mode="exec")
            except SyntaxError:
                return self._rejected(slot_id, original, "invalid_python_statement", ambiguity=False)
            if len(tree.body) != 1:
                return self._rejected(slot_id, original, "statement_must_contain_one_operation", ambiguity=False)
            parsed.append(tree)
        if not parsed:
            return self._rejected(slot_id, original, "empty_slot", ambiguity=False)
        loads = {node.id for tree in parsed for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        stores = {node.id for tree in parsed for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))}
        unknown = sorted(name for name in loads if name not in allowed and name not in stores and name not in {"True", "False", "None"})
        if unknown:
            return self._rejected(slot_id, original, f"undefined_names:{','.join(unknown)}", ambiguity=True)
        if "prior_shape" not in loads:
            validation = self._validate(parsed, required, allowed)
            if not validation["valid"]:
                return self._rejected(slot_id, original, validation["reason"], ambiguity=validation.get("ambiguity", False))
            return {"accepted": True, "slot_id": slot_id, "normalized_statements": original, "actions": [], "validation": validation, "ambiguity": False}
        if "prior_shape" in inputs or len(inputs) != 1:
            return self._rejected(slot_id, original, "ambiguous_prior_shape_input", ambiguity=True)
        if "prior_shape" not in allowed:
            return self._rejected(slot_id, original, "prior_shape_is_not_declared_alias", ambiguity=True)
        normalized_trees: list[ast.Module] = []
        for tree in parsed:
            transformed = _AliasNameTransformer("prior_shape", required).visit(deepcopy(tree))
            ast.fix_missing_locations(transformed)
            normalized_trees.append(transformed)
        normalized = [
            original[index] if not any(isinstance(node, ast.Name) and node.id == "prior_shape" for node in ast.walk(parsed[index])) else ast.unparse(tree).strip()
            for index, tree in enumerate(normalized_trees)
        ]
        before_ops = _operation_signature(parsed)
        after_ops = _operation_signature(normalized_trees)
        before_numbers = _numeric_literals(parsed)
        after_numbers = _numeric_literals(normalized_trees)
        if before_ops != after_ops:
            return self._rejected(slot_id, original, "operation_changed_during_alias_normalization", ambiguity=False)
        if before_numbers != after_numbers:
            return self._rejected(slot_id, original, "numeric_literals_changed_during_alias_normalization", ambiguity=False)
        validation = self._validate(normalized_trees, required, allowed)
        if not validation["valid"]:
            return self._rejected(slot_id, original, validation["reason"], ambiguity=validation.get("ambiguity", False), normalized=normalized)
        action_indexes = [index for index, (before, after) in enumerate(zip(original, normalized)) if before != after]
        actions = []
        for index in action_indexes:
            actions.append({
                "rule_id": "sole-authoritative-prior-shape-alias",
                "slot_id": slot_id,
                "original_statement": original[index],
                "normalized_statement": normalized[index],
                "authoritative_input": required,
                "required_result_symbol": required,
                "semantic_operation_changed": False,
                "numeric_literals_changed": False,
                "operation_order_changed": False,
                "ambiguity": False,
            })
        return {"accepted": True, "slot_id": slot_id, "normalized_statements": normalized, "actions": actions, "validation": validation, "ambiguity": False}

    def validate(self, slot: dict[str, Any], statements: list[str] | None = None) -> dict[str, Any]:
        values = statements if statements is not None else [str(item) for item in slot.get("statements", [])]
        trees: list[ast.Module] = []
        for statement in values:
            try:
                trees.append(ast.parse(statement, mode="exec"))
            except SyntaxError:
                return {"valid": False, "reason": "invalid_python_statement"}
        return self._validate(trees, str(slot.get("required_result_symbol") or "body"), {str(item) for item in slot.get("allowed_names", [])} | {str(slot.get("required_result_symbol") or "body")})

    @staticmethod
    def _validate(trees: list[ast.Module], required: str, allowed: set[str]) -> dict[str, Any]:
        if not trees:
            return {"valid": False, "reason": "empty_slot"}
        statements = [ast.unparse(tree).strip() for tree in trees]
        text = "\n".join(statements)
        if _is_self_union(trees, required):
            return {"valid": False, "reason": "semantic_invalid_self_union"}
        final_targets = _assignment_targets(trees[-1])
        if final_targets and final_targets[-1] != required:
            return {"valid": False, "reason": "final assignment target does not match required result symbol"}
        loads = {node.id for tree in trees for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
        stores = {node.id for tree in trees for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
        unknown = sorted(name for name in loads if name not in allowed and name not in stores and name not in {"True", "False", "None"})
        if unknown:
            return {"valid": False, "reason": f"undefined_names:{','.join(unknown)}", "ambiguity": True}
        return {"valid": True, "statement_count": len(statements), "final_assignment_target": final_targets[-1] if final_targets else None, "text": text}

    @staticmethod
    def _rejected(slot_id: str, original: list[str], reason: str, *, ambiguity: bool, normalized: list[str] | None = None) -> dict[str, Any]:
        return {"accepted": False, "slot_id": slot_id, "normalized_statements": normalized or original, "actions": [], "validation": {"valid": False, "reason": reason}, "ambiguity": ambiguity, "reason": reason}


class _AliasNameTransformer(ast.NodeTransformer):
    def __init__(self, alias: str, target: str) -> None:
        self.alias = alias
        self.target = target

    def visit_Name(self, node: ast.Name) -> ast.Name:
        if node.id == self.alias:
            node.id = self.target
        return node


def _assignment_targets(tree: ast.AST) -> list[str]:
    targets: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    targets.append(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets.append(node.target.id)
    return targets


def _numeric_literals(trees: list[ast.Module]) -> list[Any]:
    values: list[Any] = []
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, complex)) and not isinstance(node.value, bool):
                values.append(node.value)
    return values


def _operation_signature(trees: list[ast.Module]) -> list[tuple[str, int]]:
    signature: list[tuple[str, int]] = []
    for tree in trees:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                function = node.func
                if isinstance(function, ast.Attribute):
                    signature.append((function.attr, len(node.args) + len(node.keywords)))
                elif isinstance(function, ast.Name):
                    signature.append((function.id, len(node.args) + len(node.keywords)))
    return signature


def _is_self_union(trees: list[ast.Module], required: str) -> bool:
    for tree in trees:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "union":
                continue
            receiver = node.func.value
            if isinstance(receiver, ast.Name) and receiver.id == required and len(node.args) == 1 and isinstance(node.args[0], ast.Name) and node.args[0].id == required:
                return True
    return False


__all__ = ["GeometrySlotContractCanonicalizer"]
