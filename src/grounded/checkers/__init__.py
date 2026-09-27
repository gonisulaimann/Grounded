"""Deterministic reference checks for code comments, v2.

Not covered here, by design: docstring contracts (params, returns, raises)
and commented-out code. Use darglint or pydoclint (Python),
eslint-plugin-jsdoc (JS/TS), and Ruff ERA001 for those; each was compared
head-to-head and is more precise on its surface (see REMOVED_CHECKERS).

Covered here (no exact incumbent found):
- stale-symbol-ref: comment names a call that resolves nowhere
  (not defined, imported, or used in-file; not stdlib/builtin/keyword).
- stale-file-ref: comment claims a path inside this repo's tree that
  does not exist (namespace- and placeholder-aware).
- number-drift: magic number in a comment disagrees with adjacent code.
- fragile-anchor: line anchors and untracked workaround markers.
- stale-doc-ref (EXPERIMENTAL, opt-in only): fenced code example in
  Markdown calls a symbol defined nowhere in the repo. Off by default;
  enable explicitly. Precision is still being measured (see docs).

A finding is emitted only with positive evidence of contradiction.

One module per rule family; this package re-exports every name the
former single `checkers.py` defined, so `grounded.checkers.X` keeps working.
"""
from __future__ import annotations

from ._shared import (  # noqa: F401
    COMMON_ENGLISH_FUNCWORDS,
    C_KEYWORDS,
    C_STDLIB_FUNCS,
    GO_BUILTINS,
    GO_KEYWORDS,
    IGNORED_DIR_NAMES,
    JS_GLOBALS,
    KEYWORDS,
    PLACEHOLDER_PATH_HINTS,
    PYTHON_BUILTINS,
    REFERENCE_VERBS,
    _BACKTICK_SYMBOL,
    _C_PLATFORM_CAMEL,
    _DATA_MODEL_DUNDERS,
    _DUNDER_OK,
    _FILE_EXT,
    _FILE_REF,
    _GO_STDLIB_PACKAGES,
    _HACK_UPPER,
    _HISTORICAL,
    _ILLUSTRATIVE,
    _JSDOC_TAG_LINE,
    _LINE_ANCHOR,
    _METASYNTACTIC_CALLS,
    _NEGATED,
    _PLACEHOLDER_PATH_SEGMENT,
    _PLACEHOLDER_PATH_STEMS,
    _SEE_ABOVE_BELOW,
    _SPHINX_FIELD_LINE,
    _STDLIB_MODULES,
    _SYMBOL_CALL,
    _TEMPORAL,
    _TICKET,
    _WORKAROUND_WORD,
    _WORKITEM,
    _appears_as_suffix,
    _appears_in_code,
    _code_text,
    _comment_block_text,
    _comment_lines,
    _commented_code_line_set,
    _dedupe,
    _dunder_typo_of,
    _external_or_family,
    _is_dunder,
    _is_placeholder_path,
    _is_reserved,
    _looks_like_code_block,
    _nearby_ticket,
    _scrub_docstring,
    _stdlib_class,
    _strip_strings,
    _suggest,
    _workaround_match,
)
from .symbols import (  # noqa: F401
    check_stale_symbol,
)
from .imports import (  # noqa: F401
    _JS_EXTS,
    _JS_TS_SIBLINGS,
    _alias_prefix_match,
    _base_in_ignored_dir,
    _dynamic_ns,
    _effective_js_exports,
    _effective_symbols,
    _file_tsconfig_excluded,
    _in_repo_scope,
    _js_bare_externally_resolved,
    _js_candidates,
    _js_candidates_raw,
    _js_dir_main_target,
    _js_exists_on_disk,
    _js_self_names,
    _js_target_in_ignored_dir,
    _lazy_string_export,
    _pkg_browser_field,
    _py_target_has_stub,
    _registered_at_runtime,
    _resolve_js_target,
    _resolve_py_base,
    _resolve_py_target,
    _target_escapes_root,
    check_stale_import,
    check_stale_js_import,
)
from .files import (  # noqa: F401
    _drop_literal_blocks,
    _passes_through_file,
    check_stale_file,
)
from .comments import (  # noqa: F401
    _NUMBER_CLAIM,
    _NUMBER_IN_CODE,
    check_fragile_anchor,
    check_number_drift,
)
from .contracts import (  # noqa: F401
    _CONTRACT_DEFAULT_FRAME,
    _CONTRACT_DEPRECATION,
    _CONTRACT_ENV_JS,
    _CONTRACT_ENV_JS_DESTRUCT,
    _CONTRACT_ENV_PY,
    _CONTRACT_LITERAL,
    _CONTRACT_LOCK,
    _CONTRACT_LOCK_LIKE,
    _CONTRACT_NAME,
    _contract_known,
    _contract_norm_literal,
    _loose_dist,
    check_stale_contract_ref,
)
from .docs import (  # noqa: F401
    _DOC_CALL,
    _DOC_DIFF_MARKER,
    _DOC_FENCE_LANGS,
    _DOC_ILLUSTRATIVE_DIRECTIVES,
    _DOC_JS_AMBIENT_ROOTS,
    _DOC_JS_CALL_KEYWORDS,
    _DOC_PLACEHOLDER_NAMES,
    _DOC_PLACEHOLDER_RES,
    _FENCE_LINE,
    _doc_block_is_illustrative,
    _doc_block_known,
    _doc_fence_blocks,
    _fence_info_word,
    _fence_scan,
    _strip_doc_diff_markers,
    _strip_doc_strings,
    check_stale_doc_ref,
    check_unclosed_fence,
)
from .ghost import (  # noqa: F401
    _GHOST_ALL,
    _GHOST_GENERATED_PATH,
    _GHOST_TEST_FILE,
    _ghost_build_tagged_variants,
    _ghost_importers,
    _ghost_used_in_sibling,
    check_ghost_export,
)
from .entrypoints import (  # noqa: F401
    _ENTRY_BUILD_DIRS,
    _entry_line,
    _entry_toml,
    check_stale_entrypoint,
)
from .api import (  # noqa: F401
    check_stale_api_ref,
)
from .mocks import (  # noqa: F401
    _IMPORT_AS,
    _MOCK_PATCH_OBJECT,
    _MOCK_PATCH_STR,
    _mock_import_map,
    _mock_provided,
    _mock_resolve_path,
    _mock_split,
    check_stale_mock_ref,
)
from .phantom import (  # noqa: F401
    _IMPORT_TO_DIST,
    _NODE_BUILTINS,
    _import_line,
    _import_lines,
    _phantom_js,
    _phantom_py,
    check_phantom_package,
)
from .cli_ref import (  # noqa: F401
    _CLI_CONSOLE_TAGS,
    _CLI_SHELL_OPS,
    _CLI_SPEC,
    _CONSOLE_FENCE_TAGS,
    _cli_argv_segments,
    _cli_check_argv,
    _cli_spec,
    _cli_takes_value,
    check_stale_cli_flag,
    check_stale_cli_ref,
)

CHECKERS = {
    "stale-symbol-ref": check_stale_symbol,
    "unclosed-fence": check_unclosed_fence,
    "stale-file-ref": check_stale_file,
    "stale-import": check_stale_import,
    "number-drift": check_number_drift,
    "fragile-anchor": check_fragile_anchor,
    "stale-doc-ref": check_stale_doc_ref,
    "stale-contract-ref": check_stale_contract_ref,
    "ghost-export": check_ghost_export,
    "stale-entrypoint": check_stale_entrypoint,
    "stale-mock-ref": check_stale_mock_ref,
    "phantom-package": check_phantom_package,
    "stale-cli-ref": check_stale_cli_ref,
    "stale-cli-flag": check_stale_cli_flag,
    "stale-api-ref": check_stale_api_ref,
}

CHECKER_DESCRIPTIONS = {
    "stale-cli-flag": "Docs invoke one of this repo's own programs with a long flag no argparse/click/pytest/flag/cobra/commander definition in the repo declares (experimental, opt-in).",
    "stale-symbol-ref": "Comment names a call (foo() or `foo()`) that is not defined, imported, or used in-file (v2: import- and scope-aware).",
    "stale-file-ref": "Comment claims a path inside this repo's tree that does not exist (namespace- and placeholder-aware).",
    "stale-import": "Resolvable `from M import N` where the module is missing or N is not defined, re-exported, or a submodule there.",
    "number-drift": "Comment states a magic number (timeout/port/limit) that disagrees with adjacent code.",
    "fragile-anchor": "Line-number anchors, see-above/below, or untracked HACK/WORKAROUND markers.",
    "stale-doc-ref": "EXPERIMENTAL, opt-in only: fenced Markdown code example calls a symbol defined nowhere in the repo.",
    "stale-contract-ref": "EXPERIMENTAL, opt-in only: deprecation target, lock-holder claim, or env default in a comment that contradicts the repo.",
    "ghost-export": "EXPERIMENTAL, opt-in only: public symbol with no importers, no in-file use, and no deliberate API marking.",
    "stale-entrypoint": "pyproject scripts and package.json bin/main pointing at nothing in the repo (graduated 2026-09-22; re-verified with the checker-error count at 0 — 0 false positives over 15,196 files in svelte/OmniRoute/flask/requests, so the checker demonstrably ran).",
    "stale-mock-ref": "@patch/patch.object strings naming symbols absent from the in-repo module (graduated 2026-09-22; re-verified with the checker-error count at 0 — 0 false positives over 15,196 files in svelte/OmniRoute/flask/requests, so the checker demonstrably ran).",
    "phantom-package": "EXPERIMENTAL, opt-in only: imports declared in no manifest (pyproject, requirements, package.json).",
    "stale-cli-ref": "EXPERIMENTAL, opt-in only: documented `grounded` invocations with unknown subcommands or flags.",
    "stale-api-ref": "EXPERIMENTAL, opt-in only: client calls an HTTP path no OpenAPI/Swagger document in the repo defines.",
    "unclosed-fence": "a Markdown code fence that never closes, or a fence the renderer swallows because an earlier block is still open (both make content render as code and invert the doc checkers' fence state). Graduated 2026-09-22; re-verified with the checker-error count at 0 — 0 false positives over 11,564 Markdown files in eight real repos, and the walk pinned by a differential fuzz against an independent CommonMark reference, so the checker demonstrably ran.",
}

# Opt-in checkers are registered (so --enable/explain work) but excluded
# from every default set. A checker graduates by measured precision, not
# by age: see docs/rules.md. Silence only counts as evidence when the scan
# can prove the checker ran — a checker that raises also returns no findings
# — so graduation requires a checker-error count of 0 (exit code 3).
OPT_IN_CHECKERS = frozenset({"stale-doc-ref", "stale-contract-ref", "ghost-export",
                             "phantom-package", "stale-cli-ref", "stale-cli-flag",
                             "stale-api-ref"})
DEFAULT_ENABLED = frozenset(CHECKERS) - OPT_IN_CHECKERS

# Intentionally unimplemented: docstring contracts and commented-out code
# are covered more precisely by darglint/pydoclint, eslint-plugin-jsdoc,
# and Ruff ERA001. `explain <id>` points users at them.
REMOVED_CHECKERS = {
    "param-mismatch": "removed in v2 (use darglint/pydoclint for Python, eslint-plugin-jsdoc check-param-names/require-param for JS/TS).",
    "raises-mismatch": "removed in v2 (use darglint DAR402/pydoclint DOC502-503 for Python, eslint-plugin-jsdoc require-throws for JS/TS).",
    "return-mismatch": "removed in v2 (use darglint DAR201-202/pydoclint DOC201-203 for Python, eslint-plugin-jsdoc require-returns-check for JS/TS).",
    "commented-code": "removed in v2 (use Ruff ERA001 for Python, eslint-plugin-comment-cleaner for JS/TS).",
}
