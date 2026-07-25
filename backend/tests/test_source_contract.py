from app.services.openscad.source_contract import SourceContractValidator, scan_openscad_source


VALID_SOURCE = """
/*
Project: Mounting plate
Units: millimeters
Purpose: Mount a controller
Assumptions:
- none
Print notes:
- flat on Z=0
*/

// ===== QUALITY =====
$fn = 48;
eps = 0.01;

// ===== USER PARAMETERS =====
// @volundr-requirement hole_spacing
hole_spacing = 60;

// ===== DERIVED VALUES =====
plate_width = 90;

// ===== VALIDATION =====
assert(hole_spacing > 0, "hole_spacing must be positive");

// ===== MODULES =====
// @volundr-feature mounting_method
module mounting_holes() {
  translate([hole_spacing / 2, 0, 0]) cylinder(h=6, d=4.5);
}

// ===== FINAL MODEL =====
module main_model() {
  difference() {
    cube([plate_width, 30, 6]);
    mounting_holes();
  }
}

main_model();
"""


DESIGN_SPEC = {
    "schema_version": "1.0",
    "critical_dimensions": [
        {
            "id": "hole_spacing",
            "label": "Hole spacing",
            "value": 60,
            "unit": "mm",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
    "functional_requirements": [
        {
            "id": "mounting_method",
            "description": "Use two mounting holes",
            "source": "user",
            "importance": "critical",
            "protected": True,
        }
    ],
}


def test_scanner_ignores_prohibited_text_in_comments_and_strings() -> None:
    source = VALID_SOURCE.replace(
        "eps = 0.01;",
        'eps = 0.01; // import("bad.stl")\nlabel = "surface(\\"not real\\")";',
    )

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert not [finding.rule_id for finding in result.hard_violations]


def test_scanner_detects_real_import_and_include() -> None:
    source = VALID_SOURCE.replace("eps = 0.01;", 'eps = 0.01;\nimport("bad.stl");\ninclude <x.scad>;')
    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert {finding.rule_id for finding in result.hard_violations} >= {
        "source_security.forbidden_import",
        "source_security.forbidden_include",
    }


def test_scanner_distinguishes_module_definition_from_invocation_and_final_call() -> None:
    metadata = scan_openscad_source(VALID_SOURCE).metadata

    assert "main_model" in metadata.module_names
    assert "mounting_holes" in metadata.module_names
    assert metadata.top_level_calls == ["main_model"]


def test_scanner_rejects_comment_only_main_model_call() -> None:
    source = VALID_SOURCE.replace("main_model();", "// main_model();")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "source_structure.missing_final_main_model_call" in {
        finding.rule_id for finding in result.hard_violations
    }


def test_scanner_detects_unbalanced_source() -> None:
    source = VALID_SOURCE.replace("module main_model() {", "module main_model() { {")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "source_structure.unbalanced_braces" in {
        finding.rule_id for finding in result.hard_violations
    }


def test_scanner_extracts_assignments_and_markers() -> None:
    metadata = scan_openscad_source(VALID_SOURCE).metadata

    assert "hole_spacing" in metadata.parameter_names
    assert metadata.requirement_mappings["hole_spacing"].target_name == "hole_spacing"
    assert metadata.feature_mappings["mounting_method"].target_name == "mounting_holes"
    assert metadata.has_unbalanced_parentheses is False


def test_valid_complete_source_passes_hard_checks() -> None:
    result = SourceContractValidator().validate(
        VALID_SOURCE,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert result.passed_hard_checks is True
    assert result.hard_violations == []


def test_missing_main_model_module_fails() -> None:
    source = VALID_SOURCE.replace("module main_model()", "module not_main_model()")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "source_structure.missing_main_model_module" in {
        finding.rule_id for finding in result.hard_violations
    }


def test_multiple_top_level_geometry_calls_fail() -> None:
    source = VALID_SOURCE + "\ncube([1, 1, 1]);\n"

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "source_structure.unintended_top_level_call" in {
        finding.rule_id for finding in result.hard_violations
    }


def test_missing_user_parameters_section_fails_for_new_ai_generation() -> None:
    source = VALID_SOURCE.replace("// ===== USER PARAMETERS =====", "// ===== CONTROLS =====")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "source_structure.missing_user_parameters_section" in {
        finding.rule_id for finding in result.hard_violations
    }


def test_protected_dimension_mismatch_fails() -> None:
    source = VALID_SOURCE.replace("hole_spacing = 60;", "hole_spacing = 55;")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    finding = next(
        finding
        for finding in result.specification_findings
        if finding.rule_id == "specification_compliance.protected_value_mismatch"
    )
    assert finding.is_blocking is True
    assert finding.detected_value == "55"
    assert finding.threshold_value == "60"
    assert result.passed_hard_checks is False


def test_missing_protected_mapping_fails() -> None:
    source = VALID_SOURCE.replace("// @volundr-requirement hole_spacing\n", "")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "specification_compliance.missing_protected_requirement_mapping" in {
        finding.rule_id for finding in result.specification_findings
    }


def test_unverifiable_protected_value_fails() -> None:
    source = VALID_SOURCE.replace("hole_spacing = 60;", "hole_spacing = lookup_spacing();")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "specification_compliance.protected_value_unverifiable" in {
        finding.rule_id for finding in result.specification_findings
    }


def test_required_feature_marker_missing_fails() -> None:
    source = VALID_SOURCE.replace("// @volundr-feature mounting_method\n", "")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "specification_compliance.missing_required_feature_marker" in {
        finding.rule_id for finding in result.specification_findings
    }


def test_source_with_only_comments_and_parameters_fails() -> None:
    source = """
// ===== USER PARAMETERS =====
// @volundr-requirement hole_spacing
hole_spacing = 60;
module main_model() {
}
main_model();
"""

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert "source_structure.empty_main_model_body" in {
        finding.rule_id for finding in result.hard_violations
    }


def test_quality_findings_do_not_block_compilation() -> None:
    source = VALID_SOURCE.replace("assert(hole_spacing > 0, \"hole_spacing must be positive\");", "")
    source = source.replace("Print notes:", "Print details:")
    source = source.replace("$fn = 48;", "$fn = 180;")

    result = SourceContractValidator().validate(
        source,
        design_specification=DESIGN_SPEC,
        source_type="ai_initial",
    )

    assert result.passed_hard_checks is True
    assert {finding.rule_id for finding in result.quality_findings} >= {
        "source_parameterization.missing_assertions",
        "source_structure.missing_print_notes",
        "source_complexity.excessive_fn",
    }
    assert all(not finding.is_blocking for finding in result.quality_findings)
