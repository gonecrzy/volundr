export type SnapshotView = {
  view_id: string;
  view_name: string;
  image_artifact_id: string;
  image_hash?: string;
  camera?: Record<string, unknown>;
  width?: number;
  height?: number;
};

export type SnapshotPacket = {
  schema_version: string;
  project_id: string;
  workflow_run_id: string;
  revision_id: string;
  attempt_id?: string | null;
  candidate_state: string;
  coordinate_frame: Record<string, string>;
  geometry_source: Record<string, unknown>;
  render_settings: Record<string, unknown>;
  views: SnapshotView[];
  component_views: SnapshotView[];
  section_views: SnapshotView[];
  packet_hash?: string;
  packet_artifact_id?: string;
  status?: string;
  warnings?: string[];
};

export type RevisionComparison = {
  schema_version?: string;
  from_revision_id?: string;
  to_revision_id?: string;
  revision_instruction?: string | null;
  geometry?: {
    bounding_box_before?: Record<string, number | null>;
    bounding_box_after?: Record<string, number | null>;
    bounding_box_delta?: Record<string, number | null>;
    volume_before?: number | null;
    volume_after?: number | null;
    volume_delta?: number | null;
  };
  artifacts?: { paired_view_ids?: Array<Record<string, unknown>> };
  preserved_requirement_ids?: string[];
  verification?: {
    passed_added?: string[];
    passed_removed?: string[];
    warnings_added?: string[];
    warnings_resolved?: string[];
    blocking_added?: string[];
    blocking_resolved?: string[];
  };
};

export function primarySnapshotView(packet: SnapshotPacket | null): SnapshotView | null {
  if (!packet || packet.status || packet.views.length === 0) {
    return null;
  }
  return packet.views.find((view) => view.view_name === "isometric") ?? packet.views[0] ?? null;
}

export function snapshotImageUrl(apiBase: string, revisionId: string, artifactId: string): string {
  return `${apiBase}/revisions/${encodeURIComponent(revisionId)}/snapshots/images/${encodeURIComponent(artifactId)}`;
}

export function comparisonIsAvailable(comparison: RevisionComparison | null): boolean {
  return Boolean(comparison?.artifacts?.paired_view_ids?.length);
}
