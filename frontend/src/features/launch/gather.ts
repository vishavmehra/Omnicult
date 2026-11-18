/**
 * Gathering: fills observation groups from records Omnicult already holds, so a person does not retype them.
 *
 * Today only the Evidence Meter is read here (Market Lens, `GET /workspaces/{id}/regions/{code}/evidence-meter`, an exact
 * field-for-field reading). Quick Read, Risk Check, transcreation checks, reference grounding and objective checks are still
 * entered by hand; a backend stream is wiring their automatic gathering. When it lands, extend `gatherInputs` (or replace its
 * body with the new endpoint) and the editor, status chips and "what is missing" text already handle the result.
 */
import { fetchEvidenceMeter } from "./api";
import { GROUP_LABEL, GROUPS, type GroupKey, type MeterDraft } from "./observations";

export type Gathered = { group: "evidence_meter"; value: MeterDraft; source: string };

export type GatherResult = {
  gathered: Gathered[];
  /** Groups Omnicult cannot read automatically yet, in display order. */
  notGathered: GroupKey[];
  /** Groups it tried to read and could not, with the reason. */
  failed: { group: GroupKey; message: string }[];
};

export async function gatherInputs(args: { workspaceId: string | null; regionCode: string }): Promise<GatherResult> {
  const result: GatherResult = { gathered: [], notGathered: [], failed: [] };
  const readable: GroupKey[] = [];

  if (args.workspaceId) {
    readable.push("evidence_meter");
    try {
      const m = await fetchEvidenceMeter(args.workspaceId, args.regionCode);
      result.gathered.push({
        group: "evidence_meter",
        source: `Market Lens Evidence Meter, ${m.region_name}`,
        value: {
          strength: m.strength,
          claims: String(m.claims),
          supported_claims: String(m.supported_claims),
          open_conflicts: String(m.open_conflicts),
          stale_claims: String(m.stale_claims),
        },
      });
    } catch (error) {
      result.failed.push({ group: "evidence_meter", message: error instanceof Error ? error.message : "The Evidence Meter could not be read." });
    }
  }
  result.notGathered = GROUPS.filter((g) => !readable.includes(g));
  return result;
}

export const describeGroups = (groups: GroupKey[]) => groups.map((g) => GROUP_LABEL[g]).join(", ");
