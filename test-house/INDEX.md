# Test Index

| id | title | level | file | function |
|---|---|---|---|---|
| T-BASELINE-0001 | Empty baselines are seeded with the measured floor | fast | gate/test_baseline.py | test_update_baselines_seeds_empty |
| T-BASELINE-0002 | A higher measured value ratchets the floor up | fast | gate/test_baseline.py | test_update_baselines_ratchets_up |
| T-BASELINE-0003 | A lowered measured value is rejected and the floor is kept | fast | gate/test_baseline.py | test_update_baselines_rejects_decrease |
| T-BASELINE-0004 | Mixed measured values keep the improved key and reject the decreased one | fast | gate/test_baseline.py | test_update_baselines_mixed_up_and_down |
| T-BASELINE-0005 | check_baseline_decrease flags a lowered value | fast | gate/test_baseline.py | test_check_baseline_decrease_flags_and_clears |
| T-BASELINE-0006 | baselines.json validates against its schema | fast | gate/test_baseline.py | test_baselines_schema_valid_and_invalid |
| T-BASELINE-0007 | A missing measured component reports a decrease | fast | gate/test_baseline.py | test_check_baseline_decrease_missing_component |
| T-CI-0001 | CI workflows use only gate and build steps with actions pinned by hash | fast | gate/test_ci.py | test_ci_workflows_structure |
| T-DOCS-0001 | A missing honesty line makes the docs gate fail | fast | gate/test_docs.py | test_missing_honesty_line_fails |
| T-DOCS-0002 | A fenced code block makes the docs gate fail | fast | gate/test_docs.py | test_code_block_fails |
| T-DOCS-0003 | A Build Progress row count mismatch makes the docs gate fail | fast | gate/test_docs.py | test_row_mismatch_fails |
| T-DOCS-0004 | A broken local link makes the docs gate fail | fast | gate/test_docs.py | test_broken_link_fails |
| T-DOCS-0005 | A hand-edited tick in Build Progress makes the docs gate fail | fast | gate/test_docs.py | test_hand_edited_tick_fails |
| T-DOCS-0006 | A forbidden pattern in the README makes the docs gate fail | fast | gate/test_docs.py | test_forbidden_pattern_fails |
| T-DOCS-LINKS | check_links skips http, https and anchor links | fast | gate/test_docs.py | test_check_links_skips_external_and_anchor |
| T-GATE-0001 | Exit-code semantics (pass / fail / misconfiguration) | fast | gate/test_runner.py | test_exit_code_pass |
| T-GATE-0002 | Gate timeout records reason TIMEOUT | slow | gate/test_runner.py | test_timeout_reason |
| T-GATE-0003 | JSON result has the required schema | fast | gate/test_runner.py | test_json_result_schema |
| T-GATE-0004 | NOT_ACTIVE gates are listed but never counted as passed | fast | gate/test_runner.py | test_not_active_never_counted |
| T-GATE-0005 | A required gate missing from the catalogue returns exit 2 | fast | gate/test_runner.py | test_overdue_activation_returns_2 |
| T-GATE-0006 | Generated gate table matches persisted JSON results | fast | gate/test_runner.py | test_report_matches_json |
| T-GATE-0007 | gate affected returns the complete slow set without a coverage map | fast | gate/test_runner.py | test_affected_fallback |
| T-GATE-0008 | Running an unknown gate name returns exit 2 | fast | gate/test_runner.py | test_unknown_gate_returns_2 |
| T-GATE-0009 | Missing header field fails | fast | gate/test_index.py | test_missing_header_field |
| T-GATE-0010 | Duplicate id fails | fast | gate/test_index.py | test_duplicate_id |
| T-GATE-0011 | Stale index fails | fast | gate/test_index.py | test_stale_index |
| T-GATE-0012 | Unmarked test fails | fast | gate/test_index.py | test_unmarked_test |
| T-GATE-0013 | Order-dependent fixture detected by repeat check | fast | gate/test_index.py | test_order_dependent_detected |
| T-GATE-0014 | Index is byte-identical on regeneration | fast | gate/test_index.py | test_index_byte_identical |
| T-GATE-0015 | hygiene gate fails on a file with a forbidden pattern | fast | gate/test_gates.py | test_hygiene_violation |
| T-GATE-0016 | hygiene gate passes on a clean file | fast | gate/test_gates.py | test_hygiene_clean |
| T-GATE-0017 | secrets gate fails on a pre-computed result with findings | fast | gate/test_gates.py | test_secrets_violation |
| T-GATE-0018 | secrets gate passes on a clean result | fast | gate/test_gates.py | test_secrets_clean |
| T-GATE-0019 | security gate fails on yaml.unsafe_load | slow | gate/test_gates.py | test_security_violation |
| T-GATE-0020 | security gate passes on a clean file | slow | gate/test_gates.py | test_security_clean |
| T-GATE-0021 | deps gate fails on a vulnerable package | fast | gate/test_gates.py | test_deps_violation |
| T-GATE-0022 | deps gate passes on a clean audit | fast | gate/test_gates.py | test_deps_clean |
| T-GATE-0023 | license gate fails on a GPL-family licence | fast | gate/test_gates.py | test_license_violation_gpl |
| T-GATE-0024 | license gate passes on allowlisted licences | fast | gate/test_gates.py | test_license_clean |
| T-GATE-0025 | a modified protected file fails the protect gate | fast | gate/test_protect.py | test_modified_protected_file_fails |
| T-GATE-0026 | a modified hashes file (wrong hash) fails the protect gate | fast | gate/test_protect.py | test_modified_hashes_file_fails |
| T-GATE-0027 | --update without a task that changes a protected path fails | fast | gate/test_protect.py | test_update_without_task_fails |
| T-GATE-0028 | a clean tree with matching hashes passes the protect gate | fast | gate/test_protect.py | test_clean_tree_passes |
| T-GATE-0029 | a new protected file not in the hashes file fails the protect gate | fast | gate/test_protect.py | test_new_protected_file_missing_from_hashes_fails |
| T-GATE-0030 | vendor pattern passes in a declared adapter path and fails elsewhere | fast | gate/test_gates.py | test_vendor_pattern_scope |
| T-GATE-0031 | always-forbidden pattern fails everywhere including a declared path | fast | gate/test_gates.py | test_always_forbidden_in_scope |
| T-GATE-0032 | scope entry outside the permitted path families fails | fast | gate/test_gates.py | test_scope_outside_permitted_families |
| T-GATE-0033 | a present but empty list fails the hygiene gate | fast | gate/test_gates.py | test_empty_list_fails |
| T-GATE-0034 | an expired exception fails the deps gate | fast | gate/test_gates.py | test_expired_exception_fails |
| T-GATE-0035 | Order-dependent test caught under at least one pinned seed | fast | gate/test_seeds.py | test_order_dependent_pinned |
| T-GATE-0036 | Same seed, worker count and selection reproduce same result | fast | gate/test_seeds.py | test_same_seed_reproducible |
| T-GATE-0037 | gate seeds add appends a failing seed with its test id and refuses a hand edit | fast | gate/test_seeds.py | test_seeds_add_appends_and_refuses_hand_edit |
| T-GATE-0038 | Regression seeds run in every later gate run; fresh seed printed; hand edit fails | fast | gate/test_seeds.py | test_regression_and_fresh_seed |
| T-GATE-0039 | without lists a local run reports NOT_RUN_LOCAL | fast | gate/test_gates.py | test_not_run_local |
| T-GATE-0040 | in CI a missing list fails closed | fast | gate/test_gates.py | test_ci_missing_list_fails |
| T-GATE-0041 | commit-check rejects violations and accepts a clean message | fast | gate/test_gates.py | test_commit_check_bad_format |
| T-GATE-0042 | hygiene gate runs in CI (not NOT_RUN_LOCAL) when lists are present | fast | gate/test_gates.py | test_hygiene_pending_in_ci |
| T-GATE-0043 | a transitive package with a licence outside the allowlist fails | fast | gate/test_gates.py | test_license_transitive_bad_license |
| T-GATE-0044 | a stale THIRD_PARTY_NOTICES.txt fails the license gate | fast | gate/test_gates.py | test_license_stale_notices |
| T-GATE-GOLDEN-001 | Golden regenerate refuses a path outside the golden list | fast | gate/test_index.py | test_golden_refuses_outside |
| T-GATE-GOLDEN-002 | Golden regenerate refuses a dirty tree | fast | gate/test_index.py | test_golden_refuses_dirty |
| T-GATE-GOLDEN-003 | Golden regenerate commits golden files alone | fast | gate/test_index.py | test_golden_commits_alone |
| T-GATE-HASH | gate hash matches the system sha256 on fixture and empty files | fast | gate/test_runner.py | test_hash_matches_shasum |
| T-GATE-KILL | Timeout kill leaves no process from the group alive | slow | gate/test_runner.py | test_kill_process_group_leaves_no_child |
| T-GATE-PHASE | Phase parsing and default current phase | fast | gate/test_runner.py | test_parse_phase_number |
| T-GATE-SELFTEST | selftest fails on bad fixtures and passes on good ones | slow | gate/test_runner.py | test_selftest_passes_violation_returns_1 |
| T-GATE-SELFTEST-REAL | selftest passes against the real P00 fixtures with real tools | slow | gate/test_runner.py | test_selftest_real_round_trip |
| T-GATE-SELFTEST-T06 | selftest passes against the hygiene, secrets, security, deps, license | slow | gate/test_gates.py | test_selftest_t06_gates |
| T-GATE-SETS | Set selection resolves quick / phase / nightly correctly | fast | gate/test_runner.py | test_select_sets |
| T-GATE-STUB | stub.txt equals the two lines of <<<P7-STUB>>> and is protected | fast | gate/test_protect.py | test_stub_txt_matches_directive_bytes |
| T-PHASE-0001 | Missing DONE line fails exit check | fast | gate/test_phase.py | test_missing_done_line_fails |
| T-PHASE-0002 | Task commit without DONE line fails | fast | gate/test_phase.py | test_task_commit_without_done_fails |
| T-PHASE-0003 | Squash merge fails merge proof check | fast | gate/test_phase.py | test_squash_merge_fails |
| T-PHASE-0004 | Rebase merge fails merge proof check | fast | gate/test_phase.py | test_rebase_merge_fails |
| T-PHASE-0005 | Dirty tree fails clean-tree check | fast | gate/test_phase.py | test_dirty_tree_fails |
| T-PHASE-0006 | STATE mismatch fails state consistency check | fast | gate/test_phase.py | test_state_mismatch_fails |
| T-PHASE-0007 | Wrong directive hash fails directive hash check | fast | gate/test_phase.py | test_wrong_directive_hash_fails |
| T-PHASE-0008 | Previous branch not deleted fails check | fast | gate/test_phase.py | test_previous_branch_not_deleted_fails |
| T-PHASE-0009 | Missing report field fails validation | fast | gate/test_phase.py | test_missing_report_field_fails |
| T-PHASE-0010 | Extra report field fails validation | fast | gate/test_phase.py | test_extra_report_field_fails |
| T-PHASE-0011 | Handwritten STATE edit fails (state_hash mismatch) | fast | gate/test_phase.py | test_handwritten_state_edit_fails |
| T-PHASE-0012 | Baseline decrease fails check | fast | gate/test_phase.py | test_baseline_decrease_fails |
| T-PHASE-0013 | Non-existent marker in Context Pack fails directive lint | fast | gate/test_directive.py | test_nonexistent_marker_fails |
| T-PHASE-0014 | Missing phase block field fails directive lint | fast | gate/test_directive.py | test_missing_field_fails |
| T-PHASE-0015 | Non-sequential task ids fail directive lint | fast | gate/test_directive.py | test_non_sequential_tasks_fails |
| T-PHASE-0016 | Missing Pnn-RISK before Pnn-END1 fails directive lint | fast | gate/test_directive.py | test_missing_risk_fails |
| T-PHASE-0017 | Duplicated test id range fails directive lint | fast | gate/test_directive.py | test_dup_test_range_fails |
| T-PHASE-0018 | Look-ahead referencing non-existent phase fails | fast | gate/test_directive.py | test_bad_lookahead_fails |
| T-PHASE-0019 | Missing Scope paths line fails directive lint | fast | gate/test_directive.py | test_missing_scope_paths_fails |
| T-PHASE-0020 | Block count differing from phases.toml fails directive lint | fast | gate/test_directive.py | test_block_count_differs_fails |
| T-PHASE-0021 | Clean directive passes all checks | fast | gate/test_directive.py | test_clean_directive_passes |
| T-PHASE-0022 | Path outside scope globs fails scope check | fast | gate/test_directive.py | test_scope_outside_globs_fails |
| T-PHASE-0023 | Protected path not named by a task fails scope check | fast | gate/test_directive.py | test_scope_protected_path_fails |
| T-PHASE-0024 | Rename out of scope fails scope check | fast | gate/test_directive.py | test_scope_rename_out_of_scope_fails |
| T-PHASE-0025 | No baseline decrease passes check | fast | gate/test_phase.py | test_no_baseline_decrease_passes |
| T-PHASE-0026 | All DONE lines present passes check | fast | gate/test_phase.py | test_all_done_lines_pass |
| T-PHASE-0027 | phases.toml loads with 33 phase entries | fast | gate/test_phase.py | test_phases_table_loads |
| T-PHASE-0028 | STOP report with all required fields passes | fast | gate/test_phase.py | test_stop_report_valid |
| T-PHASE-0029 | State hash is deterministic | fast | gate/test_phase.py | test_state_hash_deterministic |
| T-PHASE-0030 | Self-review with 10 findings and no overflow passes | fast | gate/test_phase.py | test_selfreview_10_findings_passes |
| T-PHASE-0041 | Valid stub commit passes stub mode check | fast | gate/test_directive.py | test_valid_stub_passes |
| T-PHASE-0042 | Stub commit that changes another path fails | fast | gate/test_directive.py | test_stub_changes_other_path_fails |
| T-PHASE-0043 | Stub text differing from stub.txt fails | fast | gate/test_directive.py | test_stub_text_differs_fails |
| T-PHASE-0044 | Stub not the last commit fails | fast | gate/test_directive.py | test_stub_not_last_commit_fails |
| T-PHASE-0045 | Parent not P32-END2 fails | fast | gate/test_directive.py | test_parent_not_end2_fails |
| T-PHASE-0046 | Parent directive hash differing from STATE.json fails | fast | gate/test_directive.py | test_parent_hash_differs_fails |
| T-PHASE-0047 | Changed directive.txt outside stub mode fails | fast | gate/test_directive.py | test_changed_directive_outside_stub_fails |
| T-PHASE-0048 | On main with stub and STATE P32 DONE prints RELEASED | fast | gate/test_directive.py | test_released_prints |
| T-PHASE-0049 | 11th finding without OVERFLOW line fails | fast | gate/test_phase.py | test_11_findings_without_overflow_fails |
| T-PHASE-0050 | OVERFLOW line with wrong counts fails | fast | gate/test_phase.py | test_overflow_counts_differ_fails |
| T-PHASE-0051 | Overflow file without OVERFLOW line fails | fast | gate/test_phase.py | test_overflow_file_without_line_fails |
| T-PHASE-0052 | Finding over 40 words fails | fast | gate/test_phase.py | test_finding_over_40_words_fails |
| T-PHASE-0053 | Undefined reason code fails cross-check | fast | gate/test_directive.py | test_cross_undefined_reason_code_fails |
| T-PHASE-0054 | Wrong outcome word fails cross-check | fast | gate/test_directive.py | test_cross_wrong_outcome_word_fails |
| T-PHASE-0055 | Unknown matching mode fails cross-check | fast | gate/test_directive.py | test_cross_unknown_matching_mode_fails |
| T-PHASE-0056 | Unknown label fails cross-check | fast | gate/test_directive.py | test_cross_unknown_label_fails |
| T-PHASE-0057 | Unknown status word fails cross-check | fast | gate/test_directive.py | test_cross_unknown_status_word_fails |
| T-PHASE-0058 | Changed key-fact value fails cross-check | fast | gate/test_directive.py | test_cross_changed_keyfact_value_fails |
| T-PHASE-0059 | Key-fact expression matching nowhere fails cross-check | fast | gate/test_directive.py | test_cross_keyfact_nowhere_fails |
| T-PHASE-0060 | Clean cross-check passes and table block excluded | fast | gate/test_directive.py | test_cross_clean_passes |
