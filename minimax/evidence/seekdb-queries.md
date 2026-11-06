== seekdb 实际执行的查询 ==
SELECT spec_id, title, file_path, MATCH(body) AGAINST (为 增 筛选 能力 加按 过滤 的 订单 国家 IN BOOLEAN MODE) AS score FROM sdd_spec WHERE MATCH(body) AGAINST (为 增 筛选 能力 加按 过滤 的 订单 国家 IN BOOLEAN MODE) ORDER BY score DESC LIMIT 5
SELECT symbol_id, symbol, file_path, kind, spec_id, related_test, MATCH(body) AGAINST (SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents IN BOOLEAN MODE) AS score FROM sdd_symbol WHERE MATCH(body) AGAINST (SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents IN BOOLEAN MODE) ORDER BY score DESC LIMIT 10
SELECT test_id, name, file_path, MATCH(body) AGAINST (SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents IN BOOLEAN MODE) AS score FROM sdd_test WHERE MATCH(body) AGAINST (SPEC CHANGE REQUEST CURRENCY ROUNDING OTHER ORDER FILTERING filter_by_country orders country filter_by_status status filter_by_amount min_cents IN BOOLEAN MODE) ORDER BY score DESC LIMIT 10

== 命中 ==
spec    SPEC-ORDER-FILTERING                                         sample_project/specs/order_filtering.md  score=1.0175
spec    SPEC-CURRENCY-ROUNDING                                       sample_project/specs/currency_rounding.md  score=0.4588
spec    SPEC-CHANGE-REQUEST                                          sample_project/specs/change_request.md  score=0.1031
symbol  SYM-src/orders/filters.py-filter_by_status                   src/orders/filters.py  score=1.7293
symbol  SYM-src/orders/filters.py-filter_by_amount                   src/orders/filters.py  score=1.1595
symbol  SYM-src/orders/filters.py-filter_by_country                  src/orders/filters.py  score=1.0465
symbol  SYM-src/orders/filters.py-sum_by_currency                    src/orders/filters.py  score=0.6399
symbol  SYM-src/orders/filters.py-_normalize_country                 src/orders/filters.py  score=0.1499
test    TST-tests/test_filters.py-test_filter_by_status_keeps_exact_matches tests/test_filters.py  score=1.4591
test    TST-tests/test_filters.py-test_filter_by_amount_uses_a_lower_bound tests/test_filters.py  score=1.4591
test    TST-tests/test_filters.py-test_sum_by_currency_reports_cents_and_uses_other tests/test_filters.py  score=1.1321
test    TST-tests/test_filters.py-test_filter_by_country_ignores_case_and_padding tests/test_filters.py  score=0.6807
test    TST-tests/test_filters.py-test_filter_by_country_does_not_mutate_the_input tests/test_filters.py  score=0.6666
