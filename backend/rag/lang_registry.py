"""Tree-sitter language registry for shared AST chunk extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, FrozenSet, Optional


@dataclass(frozen=True)
class LanguageSpec:
    """Maps tree-sitter node types to CodeChunk roles for one language."""

    language: str
    load_language: Callable
    function_nodes: FrozenSet[str]
    class_nodes: FrozenSet[str]
    type_nodes: FrozenSet[str] = frozenset()
    impl_nodes: FrozenSet[str] = frozenset()
    interface_nodes: FrozenSet[str] = frozenset()


def _load_python():
    import tree_sitter_python as tspython
    from tree_sitter import Language

    return Language(tspython.language())


def _load_rust():
    import tree_sitter_rust as tsrust
    from tree_sitter import Language

    return Language(tsrust.language())


def _load_javascript():
    import tree_sitter_javascript as tsjs
    from tree_sitter import Language

    return Language(tsjs.language())


def _load_typescript():
    import tree_sitter_typescript as tst
    from tree_sitter import Language

    return Language(tst.language_typescript())


def _load_tsx():
    import tree_sitter_typescript as tst
    from tree_sitter import Language

    return Language(tst.language_tsx())


def _load_go():
    import tree_sitter_go as tsgo
    from tree_sitter import Language

    return Language(tsgo.language())


PYTHON_SPEC = LanguageSpec(
    language="python",
    load_language=_load_python,
    function_nodes=frozenset({"function_definition", "async_function_definition"}),
    class_nodes=frozenset({"class_definition"}),
)

RUST_SPEC = LanguageSpec(
    language="rust",
    load_language=_load_rust,
    function_nodes=frozenset({"function_item"}),
    class_nodes=frozenset(),
    type_nodes=frozenset({"struct_item", "enum_item", "trait_item"}),
    impl_nodes=frozenset({"impl_item"}),
)

JS_SPEC = LanguageSpec(
    language="javascript",
    load_language=_load_javascript,
    function_nodes=frozenset({"function_declaration", "method_definition"}),
    class_nodes=frozenset({"class_declaration"}),
)

TS_SPEC = LanguageSpec(
    language="typescript",
    load_language=_load_typescript,
    function_nodes=frozenset({"function_declaration", "method_definition"}),
    class_nodes=frozenset({"class_declaration"}),
    interface_nodes=frozenset({"interface_declaration"}),
)

TSX_SPEC = LanguageSpec(
    language="tsx",
    load_language=_load_tsx,
    function_nodes=frozenset({"function_declaration", "method_definition"}),
    class_nodes=frozenset({"class_declaration"}),
    interface_nodes=frozenset({"interface_declaration"}),
)

GO_SPEC = LanguageSpec(
    language="go",
    load_language=_load_go,
    function_nodes=frozenset({"function_declaration", "method_declaration"}),
    class_nodes=frozenset(),
    type_nodes=frozenset({"type_declaration"}),
)


EXTENSION_SPECS: dict[str, LanguageSpec] = {
    ".py": PYTHON_SPEC,
    ".rs": RUST_SPEC,
    ".js": JS_SPEC,
    ".mjs": JS_SPEC,
    ".cjs": JS_SPEC,
    ".ts": TS_SPEC,
    ".tsx": TSX_SPEC,
    ".go": GO_SPEC,
}


def spec_for_suffix(suffix: str) -> Optional[LanguageSpec]:
    return EXTENSION_SPECS.get(suffix.lower())