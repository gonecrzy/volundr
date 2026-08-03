import hashlib
import json
from pathlib import Path


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "diagnostic_inputs"
EXPECTED_FAMILIES = {"five_tray_wall_carrier", "desktop_organizer", "screw_lid_container"}


def test_diagnostic_input_packages_are_complete_and_immutable() -> None:
    packages = [path for path in FIXTURE_ROOT.glob("*.json") if path.stem != "manifest"]
    assert {path.stem for path in packages} == EXPECTED_FAMILIES
    for path in packages:
        package = json.loads(path.read_text(encoding="utf-8"))
        assert package["package_version"] == "diagnostic-input-v1"
        assert package["user_request"]
        assert "approved_fact_sheet" in package
        assert package["clarification_answers"] == []
        assert package["authoritative_requirements"]
        assert package["provenance"]
        assert package["expected_components"]
        assert package["expected_outputs"]
        assert package["required_functional_features"]
        assert package["verification_targets"]
        assert package["exposed_controls"] == []
        assert package["prompt_context_pack"]["context_hash"]
        assert package["provider_contract_manifest"]["manifest_hash"]
        unsigned = dict(package)
        package_hash = unsigned.pop("package_hash")
        canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
        assert hashlib.sha256(canonical).hexdigest() == package_hash
