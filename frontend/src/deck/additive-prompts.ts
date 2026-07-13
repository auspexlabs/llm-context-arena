/** Mirrors backend/prompts/registry.py — additive framing only (not variable payloads). */

export const PROMPT_IDS = {
  stage1: 'council.stage1',
  rank: 'council.rank',
  chairPreamble: 'council.chair.preamble',
  chairInstructions: 'council.chair.instructions',
  ragControl: 'rag.control',
  summarizeRag: 'context.summarize.rag',
  summarizeUser: 'context.summarize.user',
  midTurn: 'mid_turn.semantic',
} as const;

export const ADDITIVE_TEMPLATES: Record<string, { label: string; text: string }> = {
  [PROMPT_IDS.stage1]: {
    label: 'Stage 1 — arena wrapper',
    text: `Answer the user question directly. You are a single model providing your own answer.
Do not speak for other models or imply a panel.`,
  },
  [PROMPT_IDS.rank]: {
    label: 'Stage 2 — peer-ranking instructions',
    text: `You are evaluating different responses to the following question.

Your task:
1. Evaluate each response individually first.
2. End with a FINAL RANKING: section (numbered Response labels only).
3. Penalize responses that ignore instructions or invent extra roles.`,
  },
  [PROMPT_IDS.chairPreamble]: {
    label: 'Stage 3 — chairman role preamble',
    text: `You are the Chairman of an LLM Arena. Multiple AI models have provided responses to a user's question, and then ranked each other's responses.`,
  },
  [PROMPT_IDS.chairInstructions]: {
    label: 'Stage 3 — chairman synthesis instructions',
    text: `First, briefly summarize what you saw in each stage (2 sentences or a short paragraph per item). Label this section "What I saw".

Then, provide the final answer to the original question. Consider individual responses, peer rankings, and agreement/disagreement patterns.`,
  },
  [PROMPT_IDS.ragControl]: {
    label: 'RAG retrieval guidance (appended when context injected)',
    text: `# Retrieval guidance
If the provided context seems incomplete or missing related files or functions, explicitly say what seems missing (by filename or concept) and ask the user to provide it.`,
  },
  [PROMPT_IDS.summarizeRag]: {
    label: 'Chairman summarizer poke — compress RAG (pre-arena)',
    text: `You are the Chairman of an LLM arena. Summarize the provided context for a smaller model window… Return only the compressed context, not an answer.`,
  },
  [PROMPT_IDS.summarizeUser]: {
    label: 'Chairman summarizer poke — compress user input',
    text: `Compress the user's question or input for a smaller model window… Return only the compressed user input, not an answer.`,
  },
  [PROMPT_IDS.midTurn]: {
    label: 'Mid-turn compression poke (keeps stage 2 moving)',
    text: `Compress intermediate arena responses for peer evaluation. Preserve Response A/B labels. Return only the compressed block.`,
  },
};

export function stage1WrapperFromFull(promptFull: string | null | undefined): string {
  if (!promptFull) return ADDITIVE_TEMPLATES[PROMPT_IDS.stage1].text;
  const marker = 'User question:\n';
  const idx = promptFull.indexOf(marker);
  if (idx <= 0) return ADDITIVE_TEMPLATES[PROMPT_IDS.stage1].text;
  return promptFull.slice(0, idx).trim();
}

export function additiveTemplate(promptId: string): { label: string; text: string } | null {
  return ADDITIVE_TEMPLATES[promptId] ?? null;
}