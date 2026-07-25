import { describe, expect, it } from "vitest";

import {
  canGenerateConfiguration,
  configurationControlKind,
  configurationImpactLabel,
  configurationStateLabel,
  type ConfigurationChange,
  type ConfigurationParameter,
} from "./configurationView";

function parameter(overrides: Partial<ConfigurationParameter>): ConfigurationParameter {
  return {
    id: "slot_count",
    label: "Slot count",
    value: 4,
    unit: null,
    type: "integer",
    editable: true,
    protected: false,
    source_mapped: true,
    minimum: 1,
    maximum: 12,
    allowed_values: [],
    affected_components: ["body"],
    affected_outputs: ["body"],
    ...overrides,
  };
}

function change(overrides: Partial<ConfigurationChange>): ConfigurationChange {
  return {
    id: "change-1",
    validation_state: "configuration_ready",
    selected_preset_id: null,
    resolved_parameters: {},
    user_overrides: {},
    requested_changes: {},
    affected_parameters: ["slot_count"],
    affected_components: ["body"],
    affected_outputs: ["body"],
    validation_errors: [],
    generated_revision_id: null,
    ...overrides,
  };
}

describe("configuration view helpers", () => {
  it("labels configuration states", () => {
    expect(configurationStateLabel("configuration_ready")).toBe("Configuration ready");
    expect(configurationStateLabel("requires_design_revision")).toBe("Requires design revision");
    expect(configurationStateLabel(null)).toBe("No configuration preview");
  });

  it("selects controls for supported parameter types", () => {
    expect(configurationControlKind(parameter({ type: "integer" }))).toBe("number");
    expect(configurationControlKind(parameter({ type: "boolean" }))).toBe("checkbox");
    expect(configurationControlKind(parameter({ type: "enum" }))).toBe("select");
    expect(configurationControlKind(parameter({ editable: false }))).toBe("readonly");
    expect(configurationControlKind(parameter({ source_mapped: false }))).toBe("readonly");
  });

  it("allows generation only for ready unsent configurations", () => {
    expect(canGenerateConfiguration(change({}))).toBe(true);
    expect(canGenerateConfiguration(change({ validation_state: "invalid_configuration" }))).toBe(false);
    expect(canGenerateConfiguration(change({ generated_revision_id: "rev-1" }))).toBe(false);
  });

  it("summarizes affected components and outputs", () => {
    expect(configurationImpactLabel(change({ affected_components: ["body", "lid"], affected_outputs: ["body"] }))).toBe(
      "2 components, 1 output",
    );
  });
});
