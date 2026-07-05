"""Directive parsing for LLM Context Arena.

Extracts @directives from user input and returns structured flags.

Supported directives:
    @norag / @raw       - Skip RAG retrieval
    @summarize          - Force context summarization
    @tokenbudget <n>    - Override per-turn context budget
    @trace / @debug     - Include retrieval metadata
    @short              - Hint for concise response
    @detailed           - Hint for detailed response
    @cite               - Require inline citations
    @noexecute          - No tool/action execution
    @reset              - Reset conversation state
    @temp <0-1>         - Override temperature
    @maxtokens <n>      - Override max output tokens
    @iterations <n>     - Override iteration count for complex modes
    @safe / @relaxed    - Safety level hint
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Tuple


class ParsedDirectives(BaseModel):
    """Parsed directive flags from user input."""
    skip_rag: bool = False
    force_summarize: bool = False
    use_last_chair: bool = False
    budget_override: Optional[int] = None
    trace: bool = False
    length_hint: Optional[str] = None  # "short" | "detailed"
    cite: bool = False
    noexecute: bool = False
    reset: bool = False
    temp_override: Optional[float] = None
    maxtokens_override: Optional[int] = None
    safety: Optional[str] = None  # "safe" | "relaxed"
    iterations_override: Optional[int] = None
    warnings: List[str] = Field(default_factory=list)


class DirectiveParser:
    """Parser for @directives in user input."""

    # Directive patterns mapped to their canonical names
    DIRECTIVE_ALIASES = {
        "norag": "skip_rag",
        "raw": "skip_rag",
        "summarize": "force_summarize",
        "trace": "trace",
        "debug": "trace",
        "short": "length_short",
        "detailed": "length_detailed",
        "cite": "cite",
        "noexecute": "noexecute",
        "reset": "reset",
        "safe": "safety_safe",
        "relaxed": "safety_relaxed",
    }

    # Directives that take a value
    VALUE_DIRECTIVES = {"tokenbudget", "temp", "maxtokens", "iterations"}

    @staticmethod
    def _try_parse_int(val: str) -> Optional[int]:
        """Attempt to parse an integer value."""
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _try_parse_float(val: str) -> Optional[float]:
        """Attempt to parse a float value."""
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _split_inline_val(token: str) -> Optional[str]:
        """Extract inline value from token like 'tokenbudget=1000' or 'temp:0.5'."""
        for sep in ("=", ":"):
            if sep in token:
                return token.split(sep, 1)[1]
        return None

    def parse(self, raw_text: str) -> Tuple[str, ParsedDirectives]:
        """
        Extract @directives from raw user text.

        Args:
            raw_text: The raw user input potentially containing @directives

        Returns:
            Tuple of (cleaned_text, ParsedDirectives)
        """
        words = raw_text.split()
        remaining: List[str] = []
        flags = ParsedDirectives()

        i = 0
        while i < len(words):
            word = words[i]

            # Not a directive - keep as is
            if not word.startswith("@"):
                remaining.append(word)
                i += 1
                continue

            token = word[1:]  # Remove @ prefix
            lower = token.lower()

            def consume_next_as_value() -> Optional[str]:
                """Consume the next word as a value if it's not a directive."""
                nonlocal i
                if i + 1 < len(words) and not words[i + 1].startswith("@"):
                    i += 1
                    return words[i]
                return None

            handled = True

            # Simple flag directives
            if lower in {"norag", "raw"}:
                flags.skip_rag = True
            elif lower == "summarize":
                flags.force_summarize = True
            elif lower in {"trace", "debug"}:
                flags.trace = True
            elif lower == "short":
                flags.length_hint = "short"
            elif lower == "detailed":
                flags.length_hint = "detailed"
            elif lower == "cite":
                flags.cite = True
            elif lower == "noexecute":
                flags.noexecute = True
            elif lower == "reset":
                flags.reset = True
            elif lower in {"lastchair"}:
                flags.use_last_chair = True
            elif lower in {"safe", "relaxed"}:
                flags.safety = lower

            # Value directives
            elif lower.startswith("tokenbudget"):
                val = self._split_inline_val(token) or consume_next_as_value()
                parsed = self._try_parse_int(val) if val else None
                if parsed and parsed > 0:
                    flags.budget_override = parsed
                else:
                    flags.warnings.append("Invalid @tokenbudget value; must be positive integer")

            elif lower.startswith("temp"):
                val = self._split_inline_val(token) or consume_next_as_value()
                parsed = self._try_parse_float(val) if val else None
                if parsed is not None and 0 <= parsed <= 1:
                    flags.temp_override = parsed
                else:
                    flags.warnings.append("Invalid @temp value; must be 0-1")

            elif lower.startswith("maxtokens"):
                val = self._split_inline_val(token) or consume_next_as_value()
                parsed = self._try_parse_int(val) if val else None
                if parsed and parsed > 0:
                    flags.maxtokens_override = parsed
                else:
                    flags.warnings.append("Invalid @maxtokens value; must be positive integer")

            elif lower.startswith("iterations"):
                val = self._split_inline_val(token) or consume_next_as_value()
                parsed = self._try_parse_int(val) if val else None
                if parsed and parsed > 0:
                    flags.iterations_override = parsed
                else:
                    flags.warnings.append("Invalid @iterations value; must be > 0")

            else:
                # Unrecognized directive - keep as-is in text
                handled = False

            if not handled:
                remaining.append(word)

            i += 1

        cleaned = " ".join(remaining).strip()
        return cleaned, flags


def build_directive_instructions(flags: ParsedDirectives) -> str:
    """
    Build instruction text based on parsed directives.

    Args:
        flags: Parsed directive flags

    Returns:
        Instruction string to append to prompts
    """
    lines: List[str] = []

    if flags.length_hint == "short":
        lines.append("Answer concisely (<= ~5 sentences unless code is needed).")
    elif flags.length_hint == "detailed":
        lines.append("Provide a detailed answer with rationale and steps.")

    if flags.cite:
        lines.append("When using provided context, include inline citations like [file:line].")

    if flags.noexecute:
        lines.append("Do not invoke tools or external actions; reasoning only.")

    return "\n".join(lines)


def build_mode_instructions(mode: str) -> str:
    """
    Build instruction text based on arena mode.

    Args:
        mode: The arena mode name

    Returns:
        Instruction string describing the mode
    """
    mode = (mode or "council").lower()

    mode_instructions = {
        "baseline": "Mode: Council. Multiple models answer, then rank, then chairman synthesizes.",
        "council": "Mode: Council. Multiple models answer, then rank, then chairman synthesizes.",
        "round_robin": "Mode: Round Robin. Consider prior drafts, improve accuracy/clarity, keep useful detail.",
        "fight": "Mode: Fight. Take a clear position on the question and be ready to defend it. Later prompts will explicitly guide critiques and defenses.",
        "stacks": "Mode: Stacks. Provide an answer suitable for later merge/judge steps; retain optionality.",
        "complex_iterative": "Mode: Complex Iterative. Extract constraints and propose next steps succinctly.",
        "complex_questioning": "Mode: Complex Questioning. Provide answer and note uncertainties for later reflection.",
    }

    return mode_instructions.get(mode, "")


# Module-level parser instance for convenience
_parser = DirectiveParser()


def parse_directives(raw_text: str) -> Tuple[str, ParsedDirectives]:
    """
    Convenience function to parse directives from raw text.

    Args:
        raw_text: The raw user input potentially containing @directives

    Returns:
        Tuple of (cleaned_text, ParsedDirectives)
    """
    return _parser.parse(raw_text)
