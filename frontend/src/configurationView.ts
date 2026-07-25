export type ConfigurationValidationState =
  | "configuration_ready"
  | "clarification_required"
  | "invalid_configuration"
  | "requires_design_revision"
  | "configuration_failed";

export type ConfigurationParameter = {
  id: string;
  label: string;
  value: number | string | boolean | null;
  unit: string | null;
  type: "number" | "integer" | "boolean" | "enum" | string;
  editable: boolean;
  protected: boolean;
  source_mapped: boolean;
  minimum: number | null;
  maximum: number | null;
  allowed_values: Array<string | number | boolean>;
  affected_components: string[];
  affected_outputs: string[];
};

export type ConfigurationChange = {
  id: string;
  validation_state: ConfigurationValidationState;
  selected_preset_id: string | null;
  resolved_parameters: Record<string, unknown>;
  user_overrides: Record<string, unknown>;
  requested_changes: Record<string, unknown>;
  affected_parameters: string[];
  affected_components: string[];
  affected_outputs: string[];
  validation_errors: Array<{
    code: string;
    parameter_id: string;
    message: string;
    metadata?: Record<string, unknown>;
  }>;
  generated_revision_id: string | null;
};

export type ConfigurationPreset = {
  id: string;
  preset_id: string;
  label: string;
  parameter_values: Record<string, unknown>;
  source: string;
};

export function configurationStateLabel(state: ConfigurationValidationState | null): string {
  switch (state) {
    case "configuration_ready":
      return "Configuration ready";
    case "clarification_required":
      return "Clarification required";
    case "invalid_configuration":
      return "Invalid configuration";
    case "requires_design_revision":
      return "Requires design revision";
    case "configuration_failed":
      return "Configuration failed";
    default:
      return "No configuration preview";
  }
}

export function canGenerateConfiguration(change: ConfigurationChange | null): boolean {
  return change?.validation_state === "configuration_ready" && !change.generated_revision_id;
}

export function configurationControlKind(parameter: ConfigurationParameter): string {
  if (!parameter.editable || !parameter.source_mapped) {
    return "readonly";
  }
  if (parameter.type === "boolean") {
    return "checkbox";
  }
  if (parameter.type === "enum") {
    return "select";
  }
  if (parameter.type === "number" || parameter.type === "integer") {
    return "number";
  }
  return "readonly";
}

export function configurationImpactLabel(change: ConfigurationChange | null): string {
  if (!change) {
    return "No affected outputs";
  }
  const outputs = change.affected_outputs.length;
  const components = change.affected_components.length;
  return `${components} component${components === 1 ? "" : "s"}, ${outputs} output${outputs === 1 ? "" : "s"}`;
}
