"""Unit tests for directive parsing."""

import pytest

from backend.directives import (
    DirectiveParser,
    ParsedDirectives,
    parse_directives,
    build_directive_instructions,
    build_mode_instructions,
)


class TestDirectiveParser:
    """Tests for DirectiveParser.parse()"""

    def test_parse_no_directives(self):
        """Text without directives should return unchanged."""
        text = "What is the meaning of life?"
        cleaned, flags = parse_directives(text)
        assert cleaned == text
        assert flags.skip_rag is False
        assert flags.force_summarize is False
        assert flags.budget_override is None

    def test_parse_norag(self):
        """@norag should set skip_rag=True."""
        text = "@norag What is Python?"
        cleaned, flags = parse_directives(text)
        assert cleaned == "What is Python?"
        assert flags.skip_rag is True

    def test_parse_raw_alias(self):
        """@raw should also set skip_rag=True."""
        text = "@raw Explain decorators"
        cleaned, flags = parse_directives(text)
        assert cleaned == "Explain decorators"
        assert flags.skip_rag is True

    def test_parse_summarize(self):
        """@summarize should set force_summarize=True."""
        text = "@summarize What does this code do?"
        cleaned, flags = parse_directives(text)
        assert cleaned == "What does this code do?"
        assert flags.force_summarize is True

    def test_parse_tokenbudget_inline(self):
        """@tokenbudget=5000 should set budget_override."""
        text = "@tokenbudget=5000 Analyze this"
        cleaned, flags = parse_directives(text)
        assert cleaned == "Analyze this"
        assert flags.budget_override == 5000

    def test_parse_tokenbudget_colon(self):
        """@tokenbudget:5000 should also work."""
        text = "@tokenbudget:5000 Analyze this"
        cleaned, flags = parse_directives(text)
        assert cleaned == "Analyze this"
        assert flags.budget_override == 5000

    def test_parse_tokenbudget_space(self):
        """@tokenbudget 5000 (space) should also work."""
        text = "@tokenbudget 5000 Analyze this"
        cleaned, flags = parse_directives(text)
        assert cleaned == "Analyze this"
        assert flags.budget_override == 5000

    def test_parse_tokenbudget_invalid(self):
        """Invalid @tokenbudget should add warning."""
        text = "@tokenbudget=abc Analyze this"
        cleaned, flags = parse_directives(text)
        assert cleaned == "Analyze this"
        assert flags.budget_override is None
        assert len(flags.warnings) == 1
        assert "Invalid @tokenbudget" in flags.warnings[0]

    def test_parse_temp_valid(self):
        """@temp=0.5 should set temp_override."""
        text = "@temp=0.5 Creative writing"
        cleaned, flags = parse_directives(text)
        assert cleaned == "Creative writing"
        assert flags.temp_override == 0.5

    def test_parse_temp_out_of_range(self):
        """@temp=1.5 (out of range) should add warning."""
        text = "@temp=1.5 Creative writing"
        cleaned, flags = parse_directives(text)
        assert cleaned == "Creative writing"
        assert flags.temp_override is None
        assert len(flags.warnings) == 1
        assert "Invalid @temp" in flags.warnings[0]

    def test_parse_multiple_directives(self):
        """Multiple directives should all be parsed."""
        text = "@norag @short @trace What is Python?"
        cleaned, flags = parse_directives(text)
        assert cleaned == "What is Python?"
        assert flags.skip_rag is True
        assert flags.length_hint == "short"
        assert flags.trace is True

    def test_parse_unknown_directive(self):
        """Unknown @directive should be kept in text."""
        text = "@unknown What is Python?"
        cleaned, flags = parse_directives(text)
        assert cleaned == "@unknown What is Python?"

    def test_parse_reset(self):
        """@reset should set reset=True."""
        text = "@reset"
        cleaned, flags = parse_directives(text)
        assert cleaned == ""
        assert flags.reset is True

    def test_parse_iterations(self):
        """@iterations=3 should set iterations_override."""
        text = "@iterations=3 Complex analysis"
        cleaned, flags = parse_directives(text)
        assert cleaned == "Complex analysis"
        assert flags.iterations_override == 3


class TestBuildDirectiveInstructions:
    """Tests for build_directive_instructions()"""

    def test_empty_flags(self):
        """No active flags should return empty string."""
        flags = ParsedDirectives()
        result = build_directive_instructions(flags)
        assert result == ""

    def test_short_hint(self):
        """short hint should add concise instruction."""
        flags = ParsedDirectives(length_hint="short")
        result = build_directive_instructions(flags)
        assert "concisely" in result.lower() or "5 sentences" in result

    def test_detailed_hint(self):
        """detailed hint should add detailed instruction."""
        flags = ParsedDirectives(length_hint="detailed")
        result = build_directive_instructions(flags)
        assert "detailed" in result.lower()

    def test_cite_flag(self):
        """cite flag should add citation instruction."""
        flags = ParsedDirectives(cite=True)
        result = build_directive_instructions(flags)
        assert "citation" in result.lower() or "[file:line]" in result


class TestBuildModeInstructions:
    """Tests for build_mode_instructions()"""

    def test_council_mode(self):
        """council mode should return council instruction."""
        result = build_mode_instructions("council")
        assert "council" in result.lower()

    def test_round_robin_mode(self):
        """round_robin mode should return round robin instruction."""
        result = build_mode_instructions("round_robin")
        assert "round robin" in result.lower()

    def test_fight_mode(self):
        """fight mode should return fight instruction."""
        result = build_mode_instructions("fight")
        assert "fight" in result.lower()

    def test_unknown_mode(self):
        """Unknown mode should return empty string."""
        result = build_mode_instructions("nonexistent")
        assert result == ""

    def test_none_mode(self):
        """None mode should default to council."""
        result = build_mode_instructions(None)
        assert "council" in result.lower()
