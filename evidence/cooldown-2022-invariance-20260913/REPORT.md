# 2022 cooldown structural check

The separately frozen protocol passed for both corrected2022 AlphaMax runs300/301. Both retained streams contain253 marks, zero halt bars and zero rearms. The only runtime read of the cooldown occurs inside the already-halted branch. The public setting is consumed only by strategy constructor wiring. Existing frozen implementation and data bindings were verified.

Both336- and10-session risk state machines were checked on the full saved equity streams, preserving state across legs. States and gross multipliers match at every observation; neither enters a halt. This holds with both actual first-observation initialization and a conservative100000 starting-equity seed. By deterministic first-divergence reasoning, an inactive cooldown cannot alter these retained strategy paths. No new alpha forecasts, orders, portfolio returns or trial identities were generated.

The10-session rule may now serve as a provisional research reference alongside its preserved336-session control: broader combined excessSharpe0.406954 normal/0.079523 stress; the retained2022 combined result remains1.230693/1.124948 through structural non-influence, not a newly measured candidate rerun. This check is not untouched validation, independent live reproduction, a qualified sleeve or proof of future performance. All original source and implementation limitations remain.
