from app.services.openscad.parameters import extract_editable_parameters


def test_extracts_top_level_customizer_parameters_before_modules() -> None:
    source = """
/* [Dimensions] */
// Overall bracket width
bracket_width = 18; // [10:1:40]
material_thickness = 5; // [2:0.5:10]

/* [Style] */
fish_style = "perch"; // [plain, perch, trout]
show_fins = true;
body_color = "#4682B4"; // color
body_size = [80, 18, 5]; // [1:1:200]

module main_model() {
  hidden_internal = 12;
  cube([bracket_width, material_thickness, 10]);
}
"""

    parameters = extract_editable_parameters(source)
    by_id = {parameter.id: parameter for parameter in parameters}

    assert list(by_id) == [
        "bracket_width",
        "material_thickness",
        "fish_style",
        "show_fins",
        "body_color",
        "body_size[0]",
        "body_size[1]",
        "body_size[2]",
    ]
    assert by_id["bracket_width"].type == "number"
    assert by_id["bracket_width"].value == 18
    assert by_id["bracket_width"].description == "Overall bracket width"
    assert by_id["bracket_width"].group == "Dimensions"
    assert by_id["bracket_width"].minimum == 10
    assert by_id["bracket_width"].maximum == 40
    assert by_id["bracket_width"].step == 1
    assert by_id["material_thickness"].step == 0.5

    assert by_id["fish_style"].type == "string"
    assert by_id["fish_style"].options == ["plain", "perch", "trout"]
    assert by_id["fish_style"].group == "Style"

    assert by_id["show_fins"].type == "boolean"
    assert by_id["show_fins"].value is True

    assert by_id["body_color"].type == "color"
    assert by_id["body_color"].value == "#4682B4"

    assert by_id["body_size[0]"].display_name == "Body Width"
    assert by_id["body_size[1]"].display_name == "Body Depth"
    assert by_id["body_size[2]"].display_name == "Body Height"
    assert by_id["body_size[0]"].value == 80


def test_ignores_derived_values_internal_assignments_and_malformed_constants() -> None:
    source = """
base_width = 80; // [20:1:200]
derived_width = base_width + 10;
multi_line = [
  1,
  2
];
bad_array = [1, base_width, 3];

function helper(x) = x + 1;

post_function_parameter = 22;
"""

    parameters = extract_editable_parameters(source)

    assert [parameter.id for parameter in parameters] == ["base_width"]
    assert parameters[0].value == 80


def test_parses_customizer_enum_labels_and_bare_step_or_length_comments() -> None:
    source = """
resolution = 48; // 4
fit_class = "standard"; // [loose:Loose Fit, standard:Standard Fit, tight:Tight Fit]
label_text = "VOLUNDR"; // 24
"""

    parameters = extract_editable_parameters(source)
    by_id = {parameter.id: parameter for parameter in parameters}

    assert by_id["resolution"].step == 4
    assert by_id["fit_class"].options == ["loose", "standard", "tight"]
    assert by_id["fit_class"].option_labels == {
        "loose": "Loose Fit",
        "standard": "Standard Fit",
        "tight": "Tight Fit",
    }
    assert by_id["label_text"].maximum == 24
