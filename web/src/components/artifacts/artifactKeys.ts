// The execution_artifacts keys of the feature result cards.
//
// The registry (registry.tsx) maps each key to its React component; this module holds the keys alone, in a plain
// .ts file, so the key list can be imported by a node test (node cannot load .tsx) and checked for duplicates.
//
// A feature adds one line here and one entry in registry.tsx.

export const FEATURE_ARTIFACT_KEYS: readonly string[] = [
  "uncertainty",
  "pde",
];
