## Eval: PASS (replay mode, 51 forms)

| Metric | Result | Threshold |
|---|---|---|
| Line-item recall | 100.0% | 1 |
| Wrong values (amounts, dates, billing terms) | 0 | 0 |
| Wrong SKU matches | 0 | 0 |
| Forms needing no review | 49 / 51 | 47 |
| Cost per form | $0.171 | 0.25 |
| Time per form | 28.3 s | - |

Not counted as wrong: 29 values flagged ambiguous, 0 SKUs flagged ambiguous, 0 values left blank.

Replay mode: cost and time are from the recorded live runs; the checker, post-processing and matching ran on the current code.

### Forms needing review

- of-0032: [missing_value] order_form.effective_date is blank: more than one reading (see ambiguous_fields): The date is printed in numeric form '0
- example_order_form_redacted: [missing_value] order_form.effective_date is blank: the model's reason: The document never states an effective date for the order form; 

