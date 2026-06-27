from __future__ import annotations

from pathlib import Path

from repoanalyzer.cpp.ingest import ingest_repo
from repoanalyzer.evidence.collect import collect_evidence
from repoanalyzer.evidence.claim_extraction import verify_claim_text
from repoanalyzer.evidence_eval.runner import run_eval
from repoanalyzer.query import find_callers, find_definitions
from repoanalyzer.store.sqlite import SQLiteStore
from repoanalyzer.core.paths import index_db_path


FIXTURE = Path(__file__).parent / "fixtures_cpp" / "basic_call"
GATING_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "compile_commands_gating"
INACTIVE_IF0_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "inactive_if0"
CONDITIONAL_GUARD_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "conditional_guard"
MACRO_GUARD_EVAL_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "macro_guard_eval"
COMPLEX_IF_EVAL_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "complex_if_eval"
BRANCH_GUARD_FACTS_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "branch_guard_facts"
CONFIG_HEADER_MACROS_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "config_header_macros"
COMPARE_IF_EVAL_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "compare_if_eval"
MACRO_REFERENCE_EVAL_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "macro_reference_eval"
ARITHMETIC_IF_EVAL_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "arithmetic_if_eval"
BITWISE_IF_EVAL_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "bitwise_if_eval"
UNSUPPORTED_PREPROCESSOR_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "unsupported_preprocessor_expression"
SEMANTIC_PHASE3_MVP_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_phase3_mvp_integration"


def test_ingest_and_find_basic_call_facts() -> None:
    result = ingest_repo(FIXTURE, reset=True)
    assert result.files == 3
    assert result.facts >= 6

    defs = find_definitions(FIXTURE, "init_device")
    assert len(defs) == 1
    assert defs[0].path == "src/device.cpp"

    callers = find_callers(FIXTURE, "init_device")
    assert [(f.caller, f.callee, f.path) for f in callers] == [("start_device", "init_device", "src/device.cpp")]


def test_collect_evidence_callers() -> None:
    ingest_repo(FIXTURE, reset=True)
    bundle = collect_evidence(FIXTURE, "init_device はどこから呼ばれる？", mode="callers")
    assert bundle.answerability == "answerable"
    assert any(f.fact_type == "call" and f.caller == "start_device" and f.callee == "init_device" for f in bundle.facts)




def test_collect_evidence_marks_conditional_facts_as_partial_with_constraints() -> None:
    ingest_repo(CONDITIONAL_GUARD_FIXTURE, reset=True)
    bundle = collect_evidence(CONDITIONAL_GUARD_FIXTURE, "init_device はどこから呼ばれる？", mode="callers")

    assert bundle.answerability == "partial"
    assert any(fact.payload.get("build_status") == "conditional" for fact in bundle.facts)

    conditional_unknowns = [
        unknown for unknown in bundle.unknowns if unknown.unknown_type == "conditional_build_evidence"
    ]
    assert len(conditional_unknowns) == 1
    assert "FEATURE_EXTRA" in conditional_unknowns[0].message
    assert "feature_entry->init_device" in conditional_unknowns[0].affects
    assert any("build_status=conditional" in constraint for constraint in bundle.response_constraints)


def test_collect_evidence_keeps_unconditional_bundle_answerable() -> None:
    ingest_repo(FIXTURE, reset=True)
    bundle = collect_evidence(FIXTURE, "init_device はどこから呼ばれる？", mode="callers")

    assert bundle.answerability == "answerable"
    assert [unknown.unknown_type for unknown in bundle.unknowns] == []
    assert bundle.response_constraints == []


def test_evidence_eval_basic_call_cases_pass() -> None:
    ingest_repo(FIXTURE, reset=True)
    result = run_eval(FIXTURE, FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_compile_commands_gating_excludes_sources_outside_target_build() -> None:
    result = ingest_repo(GATING_FIXTURE, reset=True)
    assert result.files == 3

    assert find_definitions(GATING_FIXTURE, "ghost_entry") == []

    callers = find_callers(GATING_FIXTURE, "init_device")
    assert [(f.caller, f.callee, f.path) for f in callers] == [("start_device", "init_device", "src/device.cpp")]


def test_ingest_without_compile_commands_scans_all_cpp_sources(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "target.cpp").write_text("void target() {\n}\n", encoding="utf-8")
    (src / "ghost.cpp").write_text("void ghost_entry() {\n    target();\n}\n", encoding="utf-8")

    result = ingest_repo(tmp_path, reset=True)
    assert result.files == 2

    callers = find_callers(tmp_path, "target")
    assert [(f.caller, f.callee, f.path) for f in callers] == [("ghost_entry", "target", "src/ghost.cpp")]


def test_if0_inactive_facts_are_excluded_from_normal_queries() -> None:
    result = ingest_repo(INACTIVE_IF0_FIXTURE, reset=True)
    assert result.files == 3

    assert find_definitions(INACTIVE_IF0_FIXTURE, "ghost_entry") == []
    start_defs = find_definitions(INACTIVE_IF0_FIXTURE, "start_device")
    assert len(start_defs) == 1
    assert start_defs[0].path == "src/device.cpp"

    callers = find_callers(INACTIVE_IF0_FIXTURE, "init_device")
    assert [(f.caller, f.callee, f.path) for f in callers] == [("start_device", "init_device", "src/device.cpp")]

    stored_facts = SQLiteStore(index_db_path(INACTIVE_IF0_FIXTURE)).all_facts()
    inactive_symbols = [
        fact
        for fact in stored_facts
        if fact.fact_type == "symbol" and fact.symbol == "ghost_entry"
    ]
    assert len(inactive_symbols) == 1
    assert inactive_symbols[0].payload["build_status"] == "inactive"
    assert inactive_symbols[0].payload["inactive_reason"] == "if0"

    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "0" and fact.payload.get("status") == "inactive" for fact in guards)


def test_evidence_eval_inactive_if0_cases_pass() -> None:
    ingest_repo(INACTIVE_IF0_FIXTURE, reset=True)
    result = run_eval(INACTIVE_IF0_FIXTURE, INACTIVE_IF0_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_unresolved_build_guards_mark_facts_as_conditional_but_keep_them_queryable() -> None:
    result = ingest_repo(CONDITIONAL_GUARD_FIXTURE, reset=True)
    assert result.files == 3

    callers = find_callers(CONDITIONAL_GUARD_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "feature_entry",
        "default_helper",
        "alt_entry",
        "fallback_entry",
    ]

    conditional_by_caller = {fact.caller: fact for fact in callers if fact.payload.get("build_status") == "conditional"}
    assert set(conditional_by_caller) == {"feature_entry", "default_helper", "alt_entry"}
    assert conditional_by_caller["feature_entry"].payload["guard_expressions"] == ["FEATURE_EXTRA"]
    assert conditional_by_caller["feature_entry"].payload["guard_directives"] == ["ifdef"]
    assert conditional_by_caller["default_helper"].payload["guard_expressions"] == ["DISABLE_DEFAULT_HELPER"]
    assert conditional_by_caller["default_helper"].payload["guard_directives"] == ["ifndef"]
    assert conditional_by_caller["alt_entry"].payload["guard_expressions"] == ["FEATURE_ALT"]
    assert conditional_by_caller["alt_entry"].payload["guard_directives"] == ["if"]

    assert find_definitions(CONDITIONAL_GUARD_FIXTURE, "ghost_entry") == []
    fallback_defs = find_definitions(CONDITIONAL_GUARD_FIXTURE, "fallback_entry")
    assert len(fallback_defs) == 1
    assert fallback_defs[0].payload["build_status"] == "active"

    stored_facts = SQLiteStore(index_db_path(CONDITIONAL_GUARD_FIXTURE)).all_facts()
    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "FEATURE_EXTRA" and fact.payload.get("status") == "conditional" for fact in guards)
    assert any(fact.payload.get("expression") == "DISABLE_DEFAULT_HELPER" and fact.payload.get("status") == "conditional" for fact in guards)
    assert any(fact.payload.get("expression") == "FEATURE_ALT" and fact.payload.get("status") == "conditional" for fact in guards)
    assert any(fact.payload.get("expression") == "0" and fact.payload.get("status") == "inactive" for fact in guards)


def test_evidence_eval_conditional_guard_cases_pass() -> None:
    ingest_repo(CONDITIONAL_GUARD_FIXTURE, reset=True)
    result = run_eval(CONDITIONAL_GUARD_FIXTURE, CONDITIONAL_GUARD_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_compile_commands_macros_evaluate_simple_build_guards() -> None:
    result = ingest_repo(MACRO_GUARD_EVAL_FIXTURE, reset=True)
    assert result.files == 3

    callers = find_callers(MACRO_GUARD_EVAL_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "feature_entry",
        "disabled_default_fallback",
        "alt_entry",
        "zero_fallback",
        "unresolved_entry",
    ]

    assert find_definitions(MACRO_GUARD_EVAL_FIXTURE, "feature_fallback") == []
    assert find_definitions(MACRO_GUARD_EVAL_FIXTURE, "default_helper") == []
    assert find_definitions(MACRO_GUARD_EVAL_FIXTURE, "alt_fallback") == []
    assert find_definitions(MACRO_GUARD_EVAL_FIXTURE, "zero_entry") == []

    conditional = [fact for fact in callers if fact.caller == "unresolved_entry"]
    assert len(conditional) == 1
    assert conditional[0].payload["build_status"] == "conditional"
    assert conditional[0].payload["guard_expressions"] == ["UNRESOLVED_FEATURE"]

    active_callers = [fact for fact in callers if fact.caller != "unresolved_entry"]
    assert all(fact.payload.get("build_status") == "active" for fact in active_callers)

    stored_facts = SQLiteStore(index_db_path(MACRO_GUARD_EVAL_FIXTURE)).all_facts()
    inactive_symbols = {
        fact.symbol: fact
        for fact in stored_facts
        if fact.fact_type == "symbol"
        and fact.symbol in {"feature_fallback", "default_helper", "alt_fallback", "zero_entry"}
    }
    assert set(inactive_symbols) == {"feature_fallback", "default_helper", "alt_fallback", "zero_entry"}
    assert all(fact.payload["build_status"] == "inactive" for fact in inactive_symbols.values())

    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "FEATURE_EXTRA" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "DISABLE_DEFAULT_HELPER" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "FEATURE_ALT" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "FEATURE_ZERO" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "UNRESOLVED_FEATURE" and fact.payload.get("status") == "conditional" for fact in guards)


def test_evidence_eval_macro_guard_eval_cases_pass() -> None:
    ingest_repo(MACRO_GUARD_EVAL_FIXTURE, reset=True)
    result = run_eval(MACRO_GUARD_EVAL_FIXTURE, MACRO_GUARD_EVAL_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_compile_commands_macros_evaluate_defined_and_boolean_if_expressions() -> None:
    result = ingest_repo(COMPLEX_IF_EVAL_FIXTURE, reset=True)
    assert result.files == 3

    callers = find_callers(COMPLEX_IF_EVAL_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "complex_active_entry",
        "zero_and_fallback",
        "true_or_unknown_entry",
        "not_zero_and_alt_entry",
        "disabled_by_macro_fallback",
        "unresolved_complex_entry",
    ]

    for inactive_symbol in [
        "complex_inactive_fallback",
        "zero_and_entry",
        "true_or_unknown_fallback",
        "disabled_by_macro_entry",
    ]:
        assert find_definitions(COMPLEX_IF_EVAL_FIXTURE, inactive_symbol) == []

    conditional = [fact for fact in callers if fact.caller == "unresolved_complex_entry"]
    assert len(conditional) == 1
    assert conditional[0].payload["build_status"] == "conditional"
    assert conditional[0].payload["guard_expressions"] == ["defined(UNKNOWN_FEATURE) || FEATURE_ZERO"]

    active_callers = [fact for fact in callers if fact.caller != "unresolved_complex_entry"]
    assert all(fact.payload.get("build_status") == "active" for fact in active_callers)

    stored_facts = SQLiteStore(index_db_path(COMPLEX_IF_EVAL_FIXTURE)).all_facts()
    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "defined(FEATURE_EXTRA) && FEATURE_ALT" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "defined(FEATURE_EXTRA) && FEATURE_ZERO" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "defined(FEATURE_EXTRA) || UNRESOLVED_FEATURE" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "!FEATURE_ZERO && FEATURE_ALT" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "!defined(DISABLE_BY_MACRO) || FEATURE_ZERO" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "defined(UNKNOWN_FEATURE) || FEATURE_ZERO" and fact.payload.get("status") == "conditional" for fact in guards)


def test_evidence_eval_complex_if_eval_cases_pass() -> None:
    ingest_repo(COMPLEX_IF_EVAL_FIXTURE, reset=True)
    result = run_eval(COMPLEX_IF_EVAL_FIXTURE, COMPLEX_IF_EVAL_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_build_guard_facts_include_elif_else_branches() -> None:
    result = ingest_repo(BRANCH_GUARD_FACTS_FIXTURE, reset=True)
    assert result.files == 3

    callers = find_callers(BRANCH_GUARD_FACTS_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "b_entry",
        "unknown_entry",
        "maybe_b_entry",
        "maybe_fallback_entry",
    ]

    assert find_definitions(BRANCH_GUARD_FACTS_FIXTURE, "a_entry") == []
    assert find_definitions(BRANCH_GUARD_FACTS_FIXTURE, "fallback_entry") == []

    conditional_callers = {fact.caller: fact for fact in callers if fact.payload.get("build_status") == "conditional"}
    assert set(conditional_callers) == {"unknown_entry", "maybe_b_entry", "maybe_fallback_entry"}
    assert conditional_callers["unknown_entry"].payload["guard_directives"] == ["if"]
    assert conditional_callers["unknown_entry"].payload["guard_expressions"] == ["UNKNOWN_FEATURE"]
    assert conditional_callers["maybe_b_entry"].payload["guard_directives"] == ["elif"]
    assert conditional_callers["maybe_b_entry"].payload["guard_expressions"] == ["FEATURE_B"]
    assert conditional_callers["maybe_fallback_entry"].payload["guard_directives"] == ["else"]

    stored_facts = SQLiteStore(index_db_path(BRANCH_GUARD_FACTS_FIXTURE)).all_facts()
    branch_guards = [fact for fact in stored_facts if fact.fact_type == "build_guard" and fact.payload.get("kind") == "guard_branch"]

    def branch(directive: str, expression: str, group_start_line: int):
        matches = [
            fact for fact in branch_guards
            if fact.payload.get("directive") == directive
            and fact.payload.get("expression") == expression
            and fact.payload.get("group_start_line") == group_start_line
        ]
        assert len(matches) == 1
        return matches[0]

    first_if = branch("if", "FEATURE_A", 10)
    first_elif = branch("elif", "FEATURE_B", 10)
    first_else = branch("else", "else of FEATURE_A", 10)
    assert first_if.payload["status"] == "inactive"
    assert first_elif.payload["status"] == "active"
    assert first_else.payload["status"] == "inactive"
    assert first_if.payload["group_end_line"] == first_elif.payload["group_end_line"] == first_else.payload["group_end_line"] == 22
    assert [first_if.payload["branch_index"], first_elif.payload["branch_index"], first_else.payload["branch_index"]] == [0, 1, 2]

    second_if = branch("if", "UNKNOWN_FEATURE", 24)
    second_elif = branch("elif", "FEATURE_B", 24)
    second_else = branch("else", "else of UNKNOWN_FEATURE", 24)
    assert second_if.payload["status"] == "conditional"
    assert second_elif.payload["status"] == "conditional"
    assert second_else.payload["status"] == "conditional"
    assert second_if.payload["effective_status"] == second_elif.payload["effective_status"] == second_else.payload["effective_status"] == "conditional"


def test_evidence_eval_branch_guard_facts_cases_pass() -> None:
    ingest_repo(BRANCH_GUARD_FACTS_FIXTURE, reset=True)
    result = run_eval(BRANCH_GUARD_FACTS_FIXTURE, BRANCH_GUARD_FACTS_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_config_header_macros_feed_build_guard_evaluation() -> None:
    result = ingest_repo(CONFIG_HEADER_MACROS_FIXTURE, reset=True)
    assert result.files == 5

    callers = find_callers(CONFIG_HEADER_MACROS_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "forced_entry",
        "forced_disabled_fallback",
        "direct_entry",
        "zero_header_fallback",
        "disabled_header_define_entry",
        "unresolved_config_entry",
    ]

    for inactive_symbol in [
        "forced_fallback",
        "enabled_when_not_disabled",
        "direct_fallback",
        "zero_header_entry",
    ]:
        assert find_definitions(CONFIG_HEADER_MACROS_FIXTURE, inactive_symbol) == []

    conditional_by_caller = {fact.caller: fact for fact in callers if fact.payload.get("build_status") == "conditional"}
    assert set(conditional_by_caller) == {"disabled_header_define_entry", "unresolved_config_entry"}
    assert conditional_by_caller["disabled_header_define_entry"].payload["guard_expressions"] == ["DISABLED_HEADER_DEFINE"]
    assert conditional_by_caller["unresolved_config_entry"].payload["guard_expressions"] == ["UNRESOLVED_FROM_CONFIG_TEST"]

    active_callers = [fact for fact in callers if fact.caller not in conditional_by_caller]
    assert all(fact.payload.get("build_status") == "active" for fact in active_callers)

    stored_facts = SQLiteStore(index_db_path(CONFIG_HEADER_MACROS_FIXTURE)).all_facts()
    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "FEATURE_FORCED" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "DISABLE_FROM_FORCED" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "FEATURE_FROM_DIRECT && FEATURE_EXPR_FROM_HEADER" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "FEATURE_ZERO_FROM_HEADER" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "DISABLED_HEADER_DEFINE" and fact.payload.get("status") == "conditional" for fact in guards)


def test_evidence_eval_config_header_macros_cases_pass() -> None:
    ingest_repo(CONFIG_HEADER_MACROS_FIXTURE, reset=True)
    result = run_eval(CONFIG_HEADER_MACROS_FIXTURE, CONFIG_HEADER_MACROS_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_facts_record_translation_unit_context_from_compile_commands_and_headers() -> None:
    ingest_repo(CONFIG_HEADER_MACROS_FIXTURE, reset=True)

    callers = find_callers(CONFIG_HEADER_MACROS_FIXTURE, "init_device")
    direct_entry = next(fact for fact in callers if fact.caller == "direct_entry")
    context = direct_entry.payload["tu_context"]

    assert context["kind"] == "translation_unit"
    assert context["source"] == "src/device.cpp"
    assert context["compile_commands"] is True
    assert context["compile_commands_entry"] is True
    assert context["precision"] == "translation_unit"
    assert context["included_headers"] == [
        "include/build_config.h",
        "include/device.h",
        "src/local_config.h",
    ]
    assert "FEATURE_FORCED" in context["macro_names"]
    assert "FEATURE_FORCED=1" in context["header_macros"]
    assert "FEATURE_FROM_DIRECT=1" in context["header_macros"]

    header_facts = [
        fact
        for fact in SQLiteStore(index_db_path(CONFIG_HEADER_MACROS_FIXTURE)).all_facts()
        if fact.path == "src/local_config.h"
    ]
    assert header_facts
    header_contexts = [fact.payload["tu_context"] for fact in header_facts]
    standalone_context = next(context for context in header_contexts if context["kind"] == "header_standalone")
    assert standalone_context["kind"] == "header_standalone"
    assert standalone_context["precision"] == "header_unattributed"
    assert standalone_context["compile_commands"] is True
    projected_context = next(context for context in header_contexts if context["kind"] == "header_projected_into_tu")
    assert projected_context["source"] == "src/device.cpp"
    assert projected_context["header"] == "src/local_config.h"
    assert projected_context["precision"] == "translation_unit_projected_header"


def test_facts_record_command_line_macros_in_translation_unit_context() -> None:
    ingest_repo(MACRO_GUARD_EVAL_FIXTURE, reset=True)

    callers = find_callers(MACRO_GUARD_EVAL_FIXTURE, "init_device")
    feature_entry = next(fact for fact in callers if fact.caller == "feature_entry")
    context = feature_entry.payload["tu_context"]

    assert context["kind"] == "translation_unit"
    assert context["source"] == "src/device.cpp"
    assert context["command_macros"] == [
        "DISABLE_DEFAULT_HELPER",
        "FEATURE_ALT=1",
        "FEATURE_EXTRA",
        "FEATURE_ZERO=0",
    ]
    assert set(context["macro_names"]) >= {
        "DISABLE_DEFAULT_HELPER",
        "FEATURE_ALT",
        "FEATURE_EXTRA",
        "FEATURE_ZERO",
    }


def test_compile_commands_macros_evaluate_comparison_if_expressions() -> None:
    result = ingest_repo(COMPARE_IF_EVAL_FIXTURE, reset=True)
    assert result.files == 3

    callers = find_callers(COMPARE_IF_EVAL_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "mode_two_entry",
        "mode_not_two_fallback",
        "range_entry",
        "level_nonpositive_fallback",
        "hex_entry",
        "negative_entry",
        "unresolved_compare_entry",
    ]

    for inactive_symbol in [
        "mode_two_fallback",
        "mode_not_two_entry",
        "level_positive_entry",
    ]:
        assert find_definitions(COMPARE_IF_EVAL_FIXTURE, inactive_symbol) == []

    conditional_by_caller = {fact.caller: fact for fact in callers if fact.payload.get("build_status") == "conditional"}
    assert set(conditional_by_caller) == {"unresolved_compare_entry"}
    assert conditional_by_caller["unresolved_compare_entry"].payload["guard_expressions"] == ["UNKNOWN_VERSION >= 2"]

    active_callers = [fact for fact in callers if fact.caller != "unresolved_compare_entry"]
    assert all(fact.payload.get("build_status") == "active" for fact in active_callers)

    stored_facts = SQLiteStore(index_db_path(COMPARE_IF_EVAL_FIXTURE)).all_facts()
    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "MODE == 2" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "MODE != 2" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "MINOR >= 5 && MODE < 3" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "LEVEL > 0" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "HEX_VALUE == 16" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "NEGATIVE_VALUE < 0" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "UNKNOWN_VERSION >= 2" and fact.payload.get("status") == "conditional" for fact in guards)


def test_evidence_eval_compare_if_eval_cases_pass() -> None:
    ingest_repo(COMPARE_IF_EVAL_FIXTURE, reset=True)
    result = run_eval(COMPARE_IF_EVAL_FIXTURE, COMPARE_IF_EVAL_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_macro_alias_values_feed_if_expression_evaluation() -> None:
    result = ingest_repo(MACRO_REFERENCE_EVAL_FIXTURE, reset=True)
    assert result.files == 4

    callers = find_callers(MACRO_REFERENCE_EVAL_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "cli_alias_entry",
        "header_alias_entry",
        "negative_alias_entry",
        "zero_alias_fallback",
        "unresolved_alias_entry",
        "cycle_alias_entry",
    ]

    for inactive_symbol in [
        "cli_alias_fallback",
        "header_alias_fallback",
        "zero_alias_entry",
    ]:
        assert find_definitions(MACRO_REFERENCE_EVAL_FIXTURE, inactive_symbol) == []

    conditional = {
        fact.caller: fact
        for fact in callers
        if fact.payload.get("build_status") == "conditional"
    }
    assert set(conditional) == {"unresolved_alias_entry", "cycle_alias_entry"}
    assert conditional["unresolved_alias_entry"].payload["guard_expressions"] == ["UNRESOLVED_ALIAS == 1"]
    assert conditional["cycle_alias_entry"].payload["guard_expressions"] == ["CYCLE_A == 1"]

    active_callers = [fact for fact in callers if fact.caller not in conditional]
    assert all(fact.payload.get("build_status") == "active" for fact in active_callers)

    stored_facts = SQLiteStore(index_db_path(MACRO_REFERENCE_EVAL_FIXTURE)).all_facts()
    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "ACTIVE_MODE == 2" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "ACTIVE_HEADER_MODE == 3" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "NEGATIVE_ALIAS < 0" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "ZERO_ALIAS" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "UNRESOLVED_ALIAS == 1" and fact.payload.get("status") == "conditional" for fact in guards)
    assert any(fact.payload.get("expression") == "CYCLE_A == 1" and fact.payload.get("status") == "conditional" for fact in guards)


def test_evidence_eval_macro_reference_eval_cases_pass() -> None:
    ingest_repo(MACRO_REFERENCE_EVAL_FIXTURE, reset=True)
    result = run_eval(MACRO_REFERENCE_EVAL_FIXTURE, MACRO_REFERENCE_EVAL_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()

def test_arithmetic_if_expressions_feed_build_guard_evaluation() -> None:
    result = ingest_repo(ARITHMETIC_IF_EVAL_FIXTURE, reset=True)
    assert result.files == 3

    callers = find_callers(ARITHMETIC_IF_EVAL_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "additive_entry",
        "subtract_entry",
        "multiply_entry",
        "division_entry",
        "modulo_entry",
        "parenthesized_entry",
        "unary_minus_entry",
        "arithmetic_else_entry",
        "unresolved_arithmetic_entry",
        "division_by_zero_entry",
    ]

    for inactive_symbol in [
        "additive_fallback",
        "inactive_arithmetic_entry",
    ]:
        assert find_definitions(ARITHMETIC_IF_EVAL_FIXTURE, inactive_symbol) == []

    conditional = {
        fact.caller: fact
        for fact in callers
        if fact.payload.get("build_status") == "conditional"
    }
    assert set(conditional) == {"unresolved_arithmetic_entry", "division_by_zero_entry"}
    assert conditional["unresolved_arithmetic_entry"].payload["guard_expressions"] == ["UNKNOWN_VALUE + 1 == 2"]
    assert conditional["division_by_zero_entry"].payload["guard_expressions"] == ["DIVIDEND / ZERO == 1"]

    active_callers = [fact for fact in callers if fact.caller not in conditional]
    assert all(fact.payload.get("build_status") == "active" for fact in active_callers)

    stored_facts = SQLiteStore(index_db_path(ARITHMETIC_IF_EVAL_FIXTURE)).all_facts()
    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "BASE + OFFSET == 3" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "BASE - OFFSET == 1" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "SCALE * 2 == 8" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "DIVIDEND / DIVISOR == 3" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "MOD_VALUE % 3 == 1" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "(BASE + OFFSET) * SCALE == 12" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "-BASE + OFFSET < 0" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "BASE + OFFSET == 4" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "UNKNOWN_VALUE + 1 == 2" and fact.payload.get("status") == "conditional" for fact in guards)
    assert any(fact.payload.get("expression") == "DIVIDEND / ZERO == 1" and fact.payload.get("status") == "conditional" for fact in guards)


def test_evidence_eval_arithmetic_if_eval_cases_pass() -> None:
    ingest_repo(ARITHMETIC_IF_EVAL_FIXTURE, reset=True)
    result = run_eval(ARITHMETIC_IF_EVAL_FIXTURE, ARITHMETIC_IF_EVAL_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()



def test_bitwise_if_expressions_feed_build_guard_evaluation() -> None:
    result = ingest_repo(BITWISE_IF_EVAL_FIXTURE, reset=True)
    assert result.files == 3

    callers = find_callers(BITWISE_IF_EVAL_FIXTURE, "init_device")
    caller_names = [fact.caller for fact in callers]
    assert caller_names == [
        "start_device",
        "bit_and_entry",
        "bit_and_fallback",
        "bit_or_entry",
        "bit_xor_entry",
        "bit_xor_fallback",
        "bit_not_entry",
        "left_shift_entry",
        "right_shift_entry",
        "negative_shift_entry",
        "unresolved_bitwise_entry",
    ]

    for inactive_symbol in [
        "inactive_bit_and_entry",
        "inactive_bit_xor_entry",
    ]:
        assert find_definitions(BITWISE_IF_EVAL_FIXTURE, inactive_symbol) == []

    conditional = {
        fact.caller: fact
        for fact in callers
        if fact.payload.get("build_status") == "conditional"
    }
    assert set(conditional) == {"negative_shift_entry", "unresolved_bitwise_entry"}
    assert conditional["negative_shift_entry"].payload["guard_expressions"] == ["SHIFT_BASE << NEGATIVE_SHIFT == 1"]
    assert conditional["unresolved_bitwise_entry"].payload["guard_expressions"] == ["UNKNOWN_FLAGS & ENABLE_A"]

    active_callers = [fact for fact in callers if fact.caller not in conditional]
    assert all(fact.payload.get("build_status") == "active" for fact in active_callers)

    stored_facts = SQLiteStore(index_db_path(BITWISE_IF_EVAL_FIXTURE)).all_facts()
    guards = [fact for fact in stored_facts if fact.fact_type == "build_guard"]
    assert any(fact.payload.get("expression") == "FLAGS & ENABLE_A" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "FLAGS & DISABLED_FLAG" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "FLAGS | DISABLED_FLAG" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "FLAGS ^ ENABLE_A" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "FLAGS ^ FLAGS" and fact.payload.get("status") == "inactive" for fact in guards)
    assert any(fact.payload.get("expression") == "~ZERO_VALUE & ENABLE_A" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "SHIFT_BASE << SHIFT_AMOUNT == 8" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "FLAGS >> 1 == 1" and fact.payload.get("status") == "active" for fact in guards)
    assert any(fact.payload.get("expression") == "SHIFT_BASE << NEGATIVE_SHIFT == 1" and fact.payload.get("status") == "conditional" for fact in guards)
    assert any(fact.payload.get("expression") == "UNKNOWN_FLAGS & ENABLE_A" and fact.payload.get("status") == "conditional" for fact in guards)


def test_evidence_eval_bitwise_if_eval_cases_pass() -> None:
    ingest_repo(BITWISE_IF_EVAL_FIXTURE, reset=True)
    result = run_eval(BITWISE_IF_EVAL_FIXTURE, BITWISE_IF_EVAL_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_nested_preprocessor_model_reports_effective_line_status() -> None:
    from repoanalyzer.cpp.macro_eval import macro_map
    from repoanalyzer.cpp.preprocessor_model import analyze_preprocessor

    text = """#if FEATURE_A
void active_line();
#if 0
void inactive_line();
#endif
#elif FEATURE_B
void inactive_sibling();
#else
void inactive_else();
#endif
#if UNKNOWN_FEATURE
void conditional_line();
#endif
"""
    model = analyze_preprocessor(text, macro_map(["FEATURE_A=1", "FEATURE_B=1"]))

    assert model.line_status[2].status == "active"
    assert model.line_status[4].status == "inactive"
    assert model.line_status[7].status == "inactive"
    assert model.line_status[9].status == "inactive"
    assert model.line_status[12].status == "conditional"
    assert [guard.expression for guard in model.line_status[12].guard_stack] == ["UNKNOWN_FEATURE"]


def test_include_resolution_visibility_and_header_projection_facts_are_recorded() -> None:
    ingest_repo(CONFIG_HEADER_MACROS_FIXTURE, reset=True)
    facts = SQLiteStore(index_db_path(CONFIG_HEADER_MACROS_FIXTURE)).all_facts()

    direct_includes = [
        fact
        for fact in facts
        if fact.path == "src/device.cpp" and fact.fact_type == "include" and fact.predicate == "includes"
    ]
    assert any(
        fact.object == "device.h"
        and fact.payload.get("resolved_path") == "include/device.h"
        and fact.payload.get("resolution_status") == "resolved"
        for fact in direct_includes
    )
    assert any(
        fact.object == "local_config.h"
        and fact.payload.get("resolved_path") == "src/local_config.h"
        and fact.payload.get("resolution_status") == "resolved"
        for fact in direct_includes
    )

    visible_headers = {
        fact.object
        for fact in facts
        if fact.path == "src/device.cpp"
        and fact.fact_type == "include"
        and fact.predicate == "header_visible_in_tu"
    }
    assert visible_headers == {"include/build_config.h", "include/device.h", "src/local_config.h"}

    projected = [
        fact
        for fact in facts
        if (fact.payload.get("tu_context") or {}).get("kind") == "header_projected_into_tu"
    ]
    assert projected
    assert any(fact.path == "src/local_config.h" for fact in projected)
    assert all(fact.payload.get("projected_from", {}).get("path") == fact.path for fact in projected)


def test_collect_evidence_reports_missing_compile_commands_context(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "target.cpp").write_text("void target() {\n}\n", encoding="utf-8")
    (src / "caller.cpp").write_text("void caller() {\n    target();\n}\n", encoding="utf-8")

    ingest_repo(tmp_path, reset=True)
    bundle = collect_evidence(tmp_path, "target はどこから呼ばれる？", mode="callers")

    assert bundle.answerability == "partial"
    assert any(unknown.unknown_type == "source_without_compile_commands" for unknown in bundle.unknowns)
    assert any("source_without_compile_commands" in constraint for constraint in bundle.response_constraints)
    assert bundle.facts[0].payload["tu_context"]["kind"] == "source_without_compile_commands"


def test_unsupported_preprocessor_expressions_are_explained_in_payload_and_bundle() -> None:
    ingest_repo(UNSUPPORTED_PREPROCESSOR_FIXTURE, reset=True)

    callers = find_callers(UNSUPPORTED_PREPROCESSOR_FIXTURE, "init_device")
    by_caller = {fact.caller: fact for fact in callers}
    assert set(by_caller) == {"start_device", "ternary_entry", "function_like_entry", "unresolved_entry"}

    ternary = by_caller["ternary_entry"]
    assert ternary.payload["build_status"] == "conditional"
    assert ternary.payload["guard_evaluation_reasons"] == ["unsupported_preprocessor_expression"]
    assert ternary.payload["unsupported_preprocessor_kinds"] == ["ternary_operator"]
    assert ternary.payload["guard_stack"][0]["unsupported_kind"] == "ternary_operator"

    function_like = by_caller["function_like_entry"]
    assert function_like.payload["build_status"] == "conditional"
    assert function_like.payload["unsupported_preprocessor_kinds"] == ["function_like_macro_call"]

    unresolved = by_caller["unresolved_entry"]
    assert unresolved.payload["build_status"] == "conditional"
    assert unresolved.payload["guard_evaluation_reasons"] == ["unresolved_macro"]
    assert unresolved.payload["unresolved_guard_symbols"] == ["UNKNOWN_VALUE"]

    bundle = collect_evidence(UNSUPPORTED_PREPROCESSOR_FIXTURE, "init_device はどこから呼ばれる？", mode="callers")
    unknown_types = {unknown.unknown_type for unknown in bundle.unknowns}
    assert "conditional_build_evidence" in unknown_types
    assert "unsupported_preprocessor_expression" in unknown_types
    unsupported = [unknown for unknown in bundle.unknowns if unknown.unknown_type == "unsupported_preprocessor_expression"][0]
    assert "ternary_operator" in unsupported.message
    assert "function_like_macro_call" in unsupported.message
    assert "ternary_entry->init_device" in unsupported.affects
    assert "function_like_entry->init_device" in unsupported.affects
    assert any("unsupported preprocessor expressions" in c for c in bundle.response_constraints)


def test_evidence_eval_unsupported_preprocessor_expression_cases_pass() -> None:
    ingest_repo(UNSUPPORTED_PREPROCESSOR_FIXTURE, reset=True)
    result = run_eval(UNSUPPORTED_PREPROCESSOR_FIXTURE, UNSUPPORTED_PREPROCESSOR_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()

SEMANTIC_MULTILINE_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_multiline_symbols"
SEMANTIC_OVERLOAD_MEMBER_CALLBACKS_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_overload_member_callbacks"
SEMANTIC_VIRTUAL_DISPATCH_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_virtual_dispatch"
SEMANTIC_CROSS_TU_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_cross_tu_resolution"


def test_phase3_extracts_qualified_multiline_symbols_and_member_calls() -> None:
    ingest_repo(SEMANTIC_MULTILINE_FIXTURE, reset=True)

    defs = find_definitions(SEMANTIC_MULTILINE_FIXTURE, "app::Device::start")
    assert any(f.qualified_name == "app::Device::start" and f.payload["signature"] == "int" for f in defs)
    short_defs = find_definitions(SEMANTIC_MULTILINE_FIXTURE, "start")
    assert any(f.qualified_name == "app::Device::start" for f in short_defs)

    store = SQLiteStore(index_db_path(SEMANTIC_MULTILINE_FIXTURE))
    facts = store.all_facts()
    assert any(f.fact_type == "symbol" and f.kind == "constructor" and f.qualified_name == "app::Device::Device" for f in facts)
    assert any(f.fact_type == "symbol" and f.kind == "destructor" and f.qualified_name == "app::Device::~Device" for f in facts)

    callers = find_callers(SEMANTIC_MULTILINE_FIXTURE, "app::Device::start")
    assert any(f.caller == "app::run" and f.call_kind == "member_direct" for f in callers)


def test_phase3_resolves_overloads_members_callbacks_and_function_pointers() -> None:
    ingest_repo(SEMANTIC_OVERLOAD_MEMBER_CALLBACKS_FIXTURE, reset=True)
    start_bundle = collect_evidence(SEMANTIC_OVERLOAD_MEMBER_CALLBACKS_FIXTURE, "app::Device::start はどこから呼ばれる？", mode="callers")
    assert start_bundle.answerability == "answerable"
    assert any(f.caller == "app::setup" and f.callee == "app::Device::start" and f.call_kind == "member_direct" for f in start_bundle.facts)

    overload_bundle = collect_evidence(SEMANTIC_OVERLOAD_MEMBER_CALLBACKS_FIXTURE, "set_mode はどこから呼ばれる？", mode="callers")
    assert overload_bundle.answerability == "partial"
    assert any(u.unknown_type == "ambiguous_overload_resolution" for u in overload_bundle.unknowns)

    callback_bundle = collect_evidence(SEMANTIC_OVERLOAD_MEMBER_CALLBACKS_FIXTURE, "on_event はどこから呼ばれる？", mode="callers")
    assert callback_bundle.answerability == "partial"
    assert any(u.unknown_type == "indirect_call_unresolved" for u in callback_bundle.unknowns)
    assert any(u.unknown_type == "callback_relation_not_execution" for u in callback_bundle.unknowns)

    store = SQLiteStore(index_db_path(SEMANTIC_OVERLOAD_MEMBER_CALLBACKS_FIXTURE))
    facts = store.all_facts()
    assert any(f.fact_type == "relation" and f.predicate == "registers_callback" and f.object == "on_event" for f in facts)
    assert any(f.fact_type == "relation" and f.predicate == "callback_candidate" and f.object == "on_error" for f in facts)
    assert any(f.fact_type == "call" and f.call_kind == "function_pointer" and "app::on_event" in f.payload.get("candidate_qualified_names", []) for f in facts)


def test_phase3_reports_virtual_dispatch_candidates() -> None:
    ingest_repo(SEMANTIC_VIRTUAL_DISPATCH_FIXTURE, reset=True)
    bundle = collect_evidence(SEMANTIC_VIRTUAL_DISPATCH_FIXTURE, "app::Base::run はどこから呼ばれる？", mode="callers")

    assert bundle.answerability == "partial"
    virtual_calls = [f for f in bundle.facts if f.call_kind == "virtual_candidate"]
    assert len(virtual_calls) == 1
    assert virtual_calls[0].caller == "app::dispatch"
    assert "app::A::run" in virtual_calls[0].payload["candidate_qualified_names"]
    assert "app::B::run" in virtual_calls[0].payload["candidate_qualified_names"]
    assert any(u.unknown_type == "virtual_dispatch_candidates" for u in bundle.unknowns)


def test_phase3_resolves_cross_tu_direct_member_and_overloaded_calls() -> None:
    ingest_repo(SEMANTIC_CROSS_TU_FIXTURE, reset=True)

    cross_callers = find_callers(SEMANTIC_CROSS_TU_FIXTURE, "app::cross_target")
    cross_edges = [f for f in cross_callers if f.caller == "app::Device::start"]
    assert len(cross_edges) == 1
    assert cross_edges[0].payload["resolution_status"] == "resolved"
    assert cross_edges[0].payload["resolution_scope"] == "cross_translation_unit"
    assert cross_edges[0].payload["callee_qualified_name"] == "app::cross_target"
    assert cross_edges[0].payload["callee_definition_path"] == "src/util.cpp"
    assert cross_edges[0].payload["cross_tu"] is True

    start_callers = find_callers(SEMANTIC_CROSS_TU_FIXTURE, "app::Device::start")
    main_edges = [f for f in start_callers if f.caller == "main" and f.call_kind == "member_direct"]
    assert len(main_edges) == 1
    assert main_edges[0].payload["resolution_scope"] == "cross_translation_unit"
    assert main_edges[0].payload["callee_definition_path"] == "src/device.cpp"

    overloaded_callers = find_callers(SEMANTIC_CROSS_TU_FIXTURE, "app::overloaded")
    resolved_signatures = sorted(
        f.payload.get("callee_signature")
        for f in overloaded_callers
        if f.caller == "app::Device::start" and f.payload.get("resolution_scope") == "cross_translation_unit"
    )
    assert resolved_signatures == ["const char*", "int"]

    store = SQLiteStore(index_db_path(SEMANTIC_CROSS_TU_FIXTURE))
    relation_facts = store.all_facts()
    assert any(
        f.fact_type == "relation"
        and f.predicate == "declared_symbol_resolves_to_definition"
        and f.object == "app::cross_target()"
        and f.payload.get("definition_path") == "src/util.cpp"
        for f in relation_facts
    )


def test_phase3_cross_tu_call_path_uses_resolved_qualified_edges() -> None:
    ingest_repo(SEMANTIC_CROSS_TU_FIXTURE, reset=True)
    bundle = collect_evidence(SEMANTIC_CROSS_TU_FIXTURE, "main から app::cross_target へ到達する call path", mode="call_path")

    assert bundle.answerability == "answerable"
    path_facts = [f for f in bundle.facts if f.fact_type == "call_path"]
    assert len(path_facts) == 1
    assert path_facts[0].route == ["main", "app::Device::start", "app::cross_target"]
    assert path_facts[0].payload["edge_statuses"] == ["resolved", "resolved"]
    assert path_facts[0].payload["ambiguous_edges"] == []


def test_phase3_cross_tu_evidence_eval_cases_pass() -> None:
    ingest_repo(SEMANTIC_CROSS_TU_FIXTURE, reset=True)
    result = run_eval(SEMANTIC_CROSS_TU_FIXTURE, SEMANTIC_CROSS_TU_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_phase3_evidence_eval_cases_pass() -> None:
    for fixture in [SEMANTIC_MULTILINE_FIXTURE, SEMANTIC_OVERLOAD_MEMBER_CALLBACKS_FIXTURE, SEMANTIC_VIRTUAL_DISPATCH_FIXTURE]:
        ingest_repo(fixture, reset=True)
        result = run_eval(fixture, fixture / "cases.yaml")
        assert result.failed == 0, result.to_dict()



def test_phase3_mvp_resolves_type_alias_member_calls_and_header_inline_symbols() -> None:
    result = ingest_repo(SEMANTIC_PHASE3_MVP_FIXTURE, reset=True)
    assert result.files == 3

    callers = find_callers(SEMANTIC_PHASE3_MVP_FIXTURE, "app::Device::start")
    resolved_member_calls = [
        fact for fact in callers
        if fact.caller == "app::phase3_driver"
        and fact.payload.get("callee_qualified_name") == "app::Device::start"
    ]
    assert len(resolved_member_calls) >= 3
    assert all(fact.payload.get("resolution_status") == "resolved" for fact in resolved_member_calls)
    assert all(fact.payload.get("callee_definition_path") == "src/device.cpp" for fact in resolved_member_calls)
    assert {fact.payload.get("receiver_type") for fact in resolved_member_calls} == {"app::Device"}
    assert {fact.payload.get("receiver_type_original") for fact in resolved_member_calls} >= {"HeaderDevice"}

    inline_callers = find_callers(SEMANTIC_PHASE3_MVP_FIXTURE, "app::header_inline_target")
    assert any(fact.caller == "app::Device::start" for fact in inline_callers)
    assert any(fact.caller == "app::phase3_driver" for fact in inline_callers)


def test_phase3_mvp_enriches_cross_tu_callbacks_and_function_pointers() -> None:
    ingest_repo(SEMANTIC_PHASE3_MVP_FIXTURE, reset=True)

    bundle = collect_evidence(SEMANTIC_PHASE3_MVP_FIXTURE, "app::callback_target はどこから呼ばれる？", mode="callers")
    assert bundle.answerability == "partial"
    assert any(unknown.unknown_type == "callback_relation_not_execution" for unknown in bundle.unknowns)
    relation = next(
        fact for fact in bundle.facts
        if fact.fact_type == "relation" and fact.predicate == "registers_callback"
    )
    assert relation.payload["callback_qualified_name"] == "app::callback_target"
    assert relation.payload["callback_definition_path"] == "src/device.cpp"

    fp_calls = [
        fact for fact in find_callers(SEMANTIC_PHASE3_MVP_FIXTURE, "app::callback_target")
        if fact.call_kind == "function_pointer"
    ]
    assert len(fp_calls) == 1
    assert "app::callback_target" in fp_calls[0].payload["candidate_qualified_names"]
    assert fp_calls[0].payload["resolution_scope"] == "global_symbol_table_candidate_enrichment"


def test_phase3_mvp_reports_template_symbols_as_unsupported_constructs() -> None:
    ingest_repo(SEMANTIC_PHASE3_MVP_FIXTURE, reset=True)

    defs = find_definitions(SEMANTIC_PHASE3_MVP_FIXTURE, "app::passthrough")
    assert defs
    assert any(fact.payload.get("unknown_type") == "unsupported_cpp_construct" for fact in defs)

    bundle = collect_evidence(SEMANTIC_PHASE3_MVP_FIXTURE, "app::passthrough の定義は？", mode="definition")
    assert bundle.answerability == "partial"
    assert any(unknown.unknown_type == "unsupported_cpp_construct" for unknown in bundle.unknowns)


def test_evidence_eval_phase3_mvp_integration_cases_pass() -> None:
    ingest_repo(SEMANTIC_PHASE3_MVP_FIXTURE, reset=True)
    result = run_eval(SEMANTIC_PHASE3_MVP_FIXTURE, SEMANTIC_PHASE3_MVP_FIXTURE / "cases.yaml")
    assert result.failed == 0, result.to_dict()

from repoanalyzer.evidence.claims import Claim
from repoanalyzer.evidence.verify import verify_claim, verify_claims
from repoanalyzer.claim_eval.runner import run_claim_eval

SEMANTIC_CROSS_TU_FIXTURE = Path(__file__).parent / "fixtures_cpp" / "semantic_cross_tu_resolution"


def test_phase4_verify_claim_supported_conditional_contradicted_and_unknown_verdicts() -> None:
    ingest_repo(SEMANTIC_PHASE3_MVP_FIXTURE, reset=True)
    supported = verify_claim(
        SEMANTIC_PHASE3_MVP_FIXTURE,
        Claim("calls", subject="app::phase3_driver", object="app::Device::start"),
    )
    assert supported.verdict == "supported"
    assert supported.reason_code == "call_edge_supported"
    assert any(fact.payload.get("resolution_scope") == "cross_translation_unit" for fact in supported.supporting_facts)

    callback = verify_claim(
        SEMANTIC_PHASE3_MVP_FIXTURE,
        Claim("callback_registers", subject="app::registerCallback", object="app::callback_target"),
    )
    assert callback.verdict == "conditional"
    assert callback.reason_code == "callback_registration_supported"
    assert any(unknown.unknown_type == "callback_relation_not_execution" for unknown in callback.unknowns)

    ingest_repo(FIXTURE, reset=True)
    contradicted = verify_claim(FIXTURE, Claim("calls", subject="start_device", object="missing_target"))
    assert contradicted.verdict == "contradicted"
    assert contradicted.reason_code == "resolved_outgoing_calls_do_not_include_target"

    unknown = verify_claim(FIXTURE, Claim("definition_exists", subject="missing_target"))
    assert unknown.verdict == "unknown"
    assert unknown.reason_code == "definition_not_found"


def test_phase4_verify_reaches_and_build_active_claims() -> None:
    ingest_repo(SEMANTIC_CROSS_TU_FIXTURE, reset=True)
    reaches = verify_claim(
        SEMANTIC_CROSS_TU_FIXTURE,
        Claim("reaches", subject="main", object="app::cross_target"),
    )
    assert reaches.verdict == "supported"
    assert reaches.reason_code == "call_path_supported"
    assert any(fact.fact_type == "call_path" and fact.route[-1] == "app::cross_target" for fact in reaches.supporting_facts)

    ingest_repo(INACTIVE_IF0_FIXTURE, reset=True)
    inactive = verify_claim(INACTIVE_IF0_FIXTURE, Claim("build_active", subject="ghost_entry"))
    assert inactive.verdict == "contradicted"
    assert inactive.reason_code == "target_only_has_inactive_build_evidence"

    ingest_repo(CONDITIONAL_GUARD_FIXTURE, reset=True)
    conditional = verify_claim(CONDITIONAL_GUARD_FIXTURE, Claim("build_active", subject="feature_entry"))
    assert conditional.verdict == "conditional"
    assert conditional.reason_code == "target_has_conditional_build_evidence"


def test_phase4_verify_claims_bundle_and_claim_eval_cases_pass() -> None:
    ingest_repo(SEMANTIC_PHASE3_MVP_FIXTURE, reset=True)
    bundle = verify_claims(
        SEMANTIC_PHASE3_MVP_FIXTURE,
        [
            Claim("definition_exists", subject="app::Device::start"),
            Claim("callback_registers", subject="app::registerCallback", object="app::callback_target"),
        ],
    )
    assert bundle.overall_verdict == "conditional"
    assert [verdict.verdict for verdict in bundle.verdicts] == ["supported", "conditional"]

    result = run_claim_eval(SEMANTIC_PHASE3_MVP_FIXTURE, SEMANTIC_PHASE3_MVP_FIXTURE / "claim_cases.yaml")
    assert result.failed == 0, result.to_dict()

    ingest_repo(FIXTURE, reset=True)
    basic_result = run_claim_eval(FIXTURE, FIXTURE / "claim_cases.yaml")
    assert basic_result.failed == 0, basic_result.to_dict()

from repoanalyzer.evidence.claim_extraction import extract_claims, verify_claim_text


def test_phase4_extracts_structured_claims_from_natural_language_text() -> None:
    text = (
        "app::phase3_driver は app::Device::start を呼び出す。"
        "app::registerCallback は app::callback_target をコールバック登録する。"
        "app::Device::start の定義が存在する。"
        "src/main.cpp includes \"api.h\"."
    )
    extracted = extract_claims(text)
    claims = [item.claim for item in extracted.extracted_claims]

    assert [claim.claim_type for claim in claims] == [
        "calls",
        "callback_registers",
        "definition_exists",
        "includes",
    ]
    assert claims[0].subject == "app::phase3_driver"
    assert claims[0].object == "app::Device::start"
    assert claims[1].subject == "app::registerCallback"
    assert claims[1].object == "app::callback_target"
    assert claims[2].subject == "app::Device::start"
    assert claims[3].subject == "src/main.cpp"
    assert claims[3].object == "api.h"
    assert all(item.claim.payload.get("extraction", {}).get("pattern_id") for item in extracted.extracted_claims)


def test_phase4_verify_text_batches_extracted_claims() -> None:
    ingest_repo(SEMANTIC_PHASE3_MVP_FIXTURE, reset=True)
    text = (
        "app::phase3_driver は app::Device::start を呼び出す。"
        "app::registerCallback は app::callback_target をコールバック登録する。"
        "app::Device::start の定義が存在する。"
    )
    bundle = verify_claim_text(SEMANTIC_PHASE3_MVP_FIXTURE, text)

    assert len(bundle.extracted_claims) == 3
    assert bundle.overall_verdict == "conditional"
    assert [verdict.verdict for verdict in bundle.verdicts] == ["supported", "conditional", "supported"]
    assert bundle.verdicts[0].reason_code == "call_edge_supported"
    assert bundle.verdicts[1].reason_code == "callback_registration_supported"
    assert any(unknown.unknown_type == "callback_relation_not_execution" for unknown in bundle.verdicts[1].unknowns)


def test_phase4_verify_text_reports_contradicted_and_extraction_warnings() -> None:
    ingest_repo(INACTIVE_IF0_FIXTURE, reset=True)
    bundle = verify_claim_text(INACTIVE_IF0_FIXTURE, "ghost_entry は対象ビルドで有効。")
    assert bundle.overall_verdict == "contradicted"
    assert bundle.verdicts[0].reason_code == "target_only_has_inactive_build_evidence"

    no_claims = verify_claim_text(INACTIVE_IF0_FIXTURE, "これは解析対象外のメモです。")
    assert no_claims.overall_verdict == "unknown"
    assert no_claims.verdicts == []
    assert no_claims.extraction_warnings[0]["warning_type"] == "no_supported_claim_patterns"


def test_semantic_receiver_chain_resolves_sakura_style_member_access() -> None:
    fixture = Path("tests/fixtures_cpp/semantic_receiver_chain")
    result = ingest_repo(fixture, reset=True)
    assert result.status == "indexed"

    search_callers = find_callers(fixture, "sakura::CLayoutMgr::SearchWord")
    search_edges = [fact for fact in search_callers if fact.caller == "sakura::CViewCommander::Command_SEARCH_NEXT"]
    assert len(search_edges) == 1
    search_payload = search_edges[0].payload
    assert search_edges[0].call_kind == "member_direct"
    assert search_payload["resolution_status"] == "resolved"
    assert search_payload["receiver_type_resolved"] == "sakura::CLayoutMgr"
    assert search_payload["resolution_basis"] in {"receiver_chain_local", "receiver_chain_cross_tu"}
    assert any(step.get("name") == "m_cLayoutMgr" for step in search_payload.get("receiver_chain_steps", []))

    method_callers = find_callers(fixture, "sakura::Inner::method")
    method_edges = [fact for fact in method_callers if fact.caller == "sakura::CViewCommander::Command_MEMBER_CHAIN"]
    assert len(method_edges) == 2
    assert all(edge.payload["resolution_status"] == "resolved" for edge in method_edges)
    assert all(edge.payload["receiver_type_resolved"] == "sakura::Inner" for edge in method_edges)

    claim_bundle = verify_claim_text(
        fixture,
        "sakura::CViewCommander::Command_SEARCH_NEXT calls sakura::CLayoutMgr::SearchWord",
    )
    assert claim_bundle.overall_verdict == "supported"
    assert [item.claim.object for item in claim_bundle.extracted_claims] == ["sakura::CLayoutMgr::SearchWord"]


def test_evidence_eval_semantic_receiver_chain_cases_pass() -> None:
    fixture = Path("tests/fixtures_cpp/semantic_receiver_chain")
    ingest_repo(fixture, reset=True)
    result = run_eval(fixture, fixture / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_semantic_sakura_grep_method_return_chain_resolution() -> None:
    fixture = Path("tests/fixtures_cpp/semantic_sakura_grep_chain")
    result = ingest_repo(fixture, reset=True)
    assert result.status == "indexed"

    addtail_callers = find_callers(fixture, "sakura::CViewCommander::Command_ADDTAIL")
    addtail_edges = [fact for fact in addtail_callers if fact.caller == "sakura::CGrepAgent::AddTail"]
    assert len(addtail_edges) == 1
    addtail_payload = addtail_edges[0].payload
    assert addtail_edges[0].call_kind == "member_direct"
    assert addtail_payload["resolution_status"] == "resolved"
    assert addtail_payload["receiver_type_resolved"] == "sakura::CViewCommander"
    assert addtail_payload["resolution_basis"] in {"receiver_chain_local", "receiver_chain_cross_tu"}
    assert any(step.get("kind") == "method_return" and step.get("name") == "GetCommander" for step in addtail_payload.get("receiver_chain", []))

    draw_callers = find_callers(fixture, "sakura::CEditWnd::SetDrawSwitchOfAllViews")
    draw_edges = [fact for fact in draw_callers if fact.caller == "sakura::CGrepAgent::DoGrepTree"]
    assert len(draw_edges) == 1
    draw_payload = draw_edges[0].payload
    assert draw_edges[0].call_kind == "member_direct"
    assert draw_payload["resolution_status"] == "resolved"
    assert draw_payload["receiver_type_resolved"] == "sakura::CEditWnd"
    assert draw_payload["resolution_basis"] in {"receiver_chain_local", "receiver_chain_cross_tu"}
    assert draw_payload["receiver_chain_root_name"] == "CEditWnd::getInstance"
    assert any(step.get("kind") == "function_return" and step.get("name") == "CEditWnd::getInstance" for step in draw_payload.get("receiver_chain", []))


def test_evidence_eval_semantic_sakura_grep_chain_cases_pass() -> None:
    fixture = Path("tests/fixtures_cpp/semantic_sakura_grep_chain")
    ingest_repo(fixture, reset=True)
    result = run_eval(fixture, fixture / "cases.yaml")
    assert result.failed == 0, result.to_dict()


def test_semantic_sakura_grep_replace_traces_write_and_replace_flow() -> None:
    fixture = Path("tests/fixtures_cpp/semantic_sakura_grep_replace")
    result = ingest_repo(fixture, reset=True)
    assert result.status == "indexed"

    constructed = find_callers(fixture, "sakura::CWriteData::CWriteData")
    constructed_edges = [fact for fact in constructed if fact.caller == "sakura::CGrepAgent::DoGrepReplaceFile"]
    assert len(constructed_edges) == 1
    assert constructed_edges[0].call_kind == "constructor"
    assert constructed_edges[0].payload["resolution_status"] == "resolved"
    assert constructed_edges[0].payload["constructed_type"] == "sakura::CWriteData"

    append_buffer = find_callers(fixture, "sakura::CWriteData::AppendBuffer")
    append_edges = [fact for fact in append_buffer if fact.caller == "sakura::CGrepAgent::DoGrepReplaceFile"]
    assert len(append_edges) == 1
    assert append_edges[0].call_kind == "member_direct"
    assert append_edges[0].payload["resolution_status"] == "resolved"
    assert append_edges[0].payload["receiver_type_resolved"] == "sakura::CWriteData"

    type_manager = find_callers(fixture, "sakura::CDocTypeManager::GetTypeConfigMini")
    type_edges = [fact for fact in type_manager if fact.caller == "sakura::CGrepAgent::DoGrepReplaceFile"]
    assert len(type_edges) == 1
    assert type_edges[0].call_kind == "member_direct"
    assert type_edges[0].payload["resolution_status"] == "resolved"
    assert type_edges[0].payload["receiver_type_resolved"] == "sakura::CDocTypeManager"
    assert any(step.get("kind") == "temporary_object" for step in type_edges[0].payload.get("receiver_chain", []) + type_edges[0].payload.get("receiver_chain_cross_tu", []))

    encoder = find_callers(fixture, "sakura::CCodeBase::UnicodeToCode")
    encoder_edges = [fact for fact in encoder if fact.caller == "sakura::CWriteData::Output"]
    assert len(encoder_edges) == 1
    assert encoder_edges[0].call_kind == "member_direct"
    assert encoder_edges[0].payload["resolution_status"] == "resolved"
    assert encoder_edges[0].payload["receiver_type_resolved"] == "sakura::CCodeBase"
    assert encoder_edges[0].payload["resolution_basis"] in {"implicit_this_field", "receiver_chain_cross_tu"}


def test_evidence_eval_semantic_sakura_grep_replace_cases_pass() -> None:
    fixture = Path("tests/fixtures_cpp/semantic_sakura_grep_replace")
    ingest_repo(fixture, reset=True)
    result = run_eval(fixture, fixture / "cases.yaml")
    assert result.failed == 0, result.to_dict()
