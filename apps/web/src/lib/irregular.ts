import type { ModelCard } from "../api/types";

/**
 * Are the issue times sample times (Water) rather than a regular grid? Read from the contract (v0.4):
 * `coverage.regular === false`. `coverage.step_hours` is 1 there only because it is the finest step the contract
 * expresses, so a map must show window aggregates, not issue-time instants. A card published before v0.4 has no flag
 * and is taken as regular.
 */
export const isIrregular = (card: Pick<ModelCard, "coverage"> | null | undefined): boolean => card?.coverage?.regular === false;
