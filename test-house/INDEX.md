# Test Index

| id | title | level | file | function |
|---|---|---|---|---|
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
| T-GATE-0035 | Order-dependent test caught under at least one pinned seed | fast | gate/test_seeds.py | test_order_dependent_pinned |
| T-GATE-0036 | Same seed, worker count and selection reproduce same result | fast | gate/test_seeds.py | test_same_seed_reproducible |
| T-GATE-0037 | gate seeds add appends a failing seed with its test id and refuses a hand edit | fast | gate/test_seeds.py | test_seeds_add_appends_and_refuses_hand_edit |
| T-GATE-0038 | Regression seeds run in every later gate run; fresh seed printed; hand edit fails | fast | gate/test_seeds.py | test_regression_and_fresh_seed |
| T-GATE-GOLDEN-001 | Golden regenerate refuses a path outside the golden list | fast | gate/test_index.py | test_golden_refuses_outside |
| T-GATE-GOLDEN-002 | Golden regenerate refuses a dirty tree | fast | gate/test_index.py | test_golden_refuses_dirty |
| T-GATE-GOLDEN-003 | Golden regenerate commits golden files alone | fast | gate/test_index.py | test_golden_commits_alone |
| T-GATE-HASH | gate hash matches the system sha256 on fixture and empty files | fast | gate/test_runner.py | test_hash_matches_shasum |
| T-GATE-KILL | Timeout kill leaves no process from the group alive | slow | gate/test_runner.py | test_kill_process_group_leaves_no_child |
| T-GATE-PHASE | Phase parsing and default current phase | fast | gate/test_runner.py | test_parse_phase_number |
| T-GATE-SELFTEST | selftest fails on bad fixtures and passes on good ones | slow | gate/test_runner.py | test_selftest_passes_violation_returns_1 |
| T-GATE-SELFTEST-REAL | selftest passes against the real P00 fixtures with real tools | slow | gate/test_runner.py | test_selftest_real_round_trip |
| T-GATE-SETS | Set selection resolves quick / phase / nightly correctly | fast | gate/test_runner.py | test_select_sets |
