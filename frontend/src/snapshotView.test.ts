import { describe, expect, it } from "vitest";
import {
  comparisonIsAvailable,
  primarySnapshotView,
  snapshotImageUrl,
  type SnapshotPacket,
} from "./snapshotView";

const packet: SnapshotPacket = {
  schema_version: "geometry-snapshot-packet-v1",
  project_id: "project-1",
  workflow_run_id: "run-1",
  revision_id: "revision-1",
  candidate_state: "ready",
  coordinate_frame: { units: "mm", up_axis: "Z", front_axis: "Y", right_axis: "X" },
  geometry_source: { component_ids: ["body"] },
  render_settings: { image_width: 768, image_height: 768 },
  views: [
    { view_id: "whole:front", view_name: "front", image_artifact_id: "front-id", image_hash: "h", camera: {} },
    { view_id: "whole:isometric", view_name: "isometric", image_artifact_id: "iso-id", image_hash: "h", camera: {} },
  ],
  component_views: [],
  section_views: [],
};

describe("snapshot view model", () => {
  it("selects isometric as the primary view", () => {
    expect(primarySnapshotView(packet)?.image_artifact_id).toBe("iso-id");
  });

  it("builds an owned image URL without exposing filesystem paths", () => {
    expect(snapshotImageUrl("/api", "revision-1", "artifact-1")).toBe(
      "/api/revisions/revision-1/snapshots/images/artifact-1",
    );
  });

  it("only enables comparison when evidence has paired views", () => {
    expect(comparisonIsAvailable({ artifacts: { paired_view_ids: [{ view_name: "isometric" }] } })).toBe(true);
    expect(comparisonIsAvailable({ artifacts: { paired_view_ids: [] } })).toBe(false);
  });
});
