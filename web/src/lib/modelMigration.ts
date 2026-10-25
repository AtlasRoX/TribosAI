// Saved model choices that the backend no longer serves (SUPPORTED_MODELS in tribos/utils/llm/llm_factory.py).

export const DEFAULT_MODEL_ID = "nvidia/nemotron-3.5-super-vl-120b-a12b";

/**
 * Retired model id -> its replacement. NIM answers 404 for these, so a turn that kept one lost every model call.
 * Only these exact ids are migrated: a current model (e.g. "nvidia/nemotron-3-ultra-550b-a55b") is kept as saved.
 */
export const RETIRED_MODELS: Readonly<Record<string, string>> = {
  "nvidia/nemotron-3-super-120b-a12b": DEFAULT_MODEL_ID,
  "nvidia/llama-3.1-nemotron-70b-instruct": DEFAULT_MODEL_ID,
};

/** The model to use for a saved choice: its replacement when it was retired, otherwise the saved id itself. */
export function migrateSavedModel(saved: string): string {
  return RETIRED_MODELS[saved.trim()] ?? saved;
}
