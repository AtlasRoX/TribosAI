// Saved model choices that the backend no longer serves (SUPPORTED_MODELS in tribos/utils/llm/llm_factory.py).

export const DEFAULT_MODEL_ID = "muse-spark-1.3";

/**
 * Retired model id -> its replacement: the server no longer lists these, so a turn that kept one would be refused.
 * The NVIDIA models were removed from the catalog in November 2026; a saved choice of one moves to the default.
 */
export const RETIRED_MODELS: Readonly<Record<string, string>> = {
  "nvidia/nemotron-3-super-120b-a12b": DEFAULT_MODEL_ID,
  "nvidia/llama-3.1-nemotron-70b-instruct": DEFAULT_MODEL_ID,
  "nvidia/nemotron-3.5-super-vl-120b-a12b": DEFAULT_MODEL_ID,
  "nvidia/nemotron-3-ultra-550b-a55b": DEFAULT_MODEL_ID,
  // The OpenAI models left the catalog in November 2026 too: muse-spark-1.3 serves every task.
  "gpt-4o": DEFAULT_MODEL_ID,
  "gpt-4o-mini": DEFAULT_MODEL_ID,
};

/** The model to use for a saved choice: its replacement when it was retired, otherwise the saved id itself. */
export function migrateSavedModel(saved: string): string {
  return RETIRED_MODELS[saved.trim()] ?? saved;
}
