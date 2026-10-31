# Fact extractor evaluation

Model `claude-haiku-5-5`, effort low, structured output via `messages.parse()`. Scored on `tests/fixtures/fact_labels.csv`: 205 history requests with a note, hand-labelled T/F/U for each of the 5 fact questions in policy v1.

**precision_yes**: of the model's yes answers on rows a human labelled yes or no, the share that were yes. This is the number that matters: a wrong yes can approve money. **precision_yes_strict** also counts a yes on a row the human left unlabelled as wrong. **recall_yes**: of the human yes rows, the share the model found. A miss only sends the case to a person.

| fact | labelled_yes | labelled_no | model_yes | precision_yes | precision_yes_strict | recall_yes | yes_on_unlabelled | accuracy_3class |
|---|---|---|---|---|---|---|---|---|
| damage_photo_confirmed | 36 | 10 | 35 | 1.00 | 1.00 | 0.97 | 0 | 0.96 |
| carrier_proof_of_delivery | 5 | 0 | 5 | 1.00 | 1.00 | 1.00 | 0 | 1.00 |
| carrier_investigation_open | 17 | 0 | 17 | 1.00 | 0.76 | 0.76 | 4 | 0.76 |
| card_confirmed_stolen | 11 | 0 | 10 | 1.00 | 1.00 | 0.91 | 0 | 0.91 |
| our_error_confirmed | 16 | 4 | 16 | 1.00 | 1.00 | 1.00 | 0 | 1.00 |

## Cost

- calls: 205 (one per request with a note, all 5 questions in one call)
- total spend for the 205 noted requests: $0.0458
- per call: $0.00022 (mean 1233 input tokens, 199 output tokens, 1406 ms)
- cache seed written to `data/llm_cache_seed.jsonl` (1025 answers) so `refund-agent backtest` reproduces offline

## Yes answers on rows the human left unlabelled (ambiguous notes)

| fact | request_id | quote | customer_note | support_note |
|---|---|---|---|---|
| carrier_investigation_open | RF-2040 | carrier delay confirmed | took 3 weeks | carrier delay confirmed |
| carrier_investigation_open | RF-2045 | carrier delay confirmed | took 3 weeks | carrier delay confirmed |
| carrier_investigation_open | RF-2109 | carrier delay confirmed | took 3 weeks | carrier delay confirmed |
| carrier_investigation_open | RF-2135 | carrier delay confirmed | took 3 weeks | carrier delay confirmed |

## Mismatches against the labels

| fact | request_id | label | model | quote | customer_note | support_note |
|---|---|---|---|---|---|---|
| damage_photo_confirmed | RF-2060 | T | U |  |  | photo attached looks genuine |
| damage_photo_confirmed | RF-1065 | F | U |  |  | New account, no previous orders, first purchase is a $495 item. Says it arrived broken, no photos yet. |
| carrier_investigation_open | RF-2026 | T | U |  |  | tracking inconclusive - last scan 10 days ago |
| carrier_investigation_open | RF-2096 | T | U |  |  | tracking inconclusive - last scan 10 days ago |
| carrier_investigation_open | RF-2151 | T | U |  |  | tracking inconclusive - last scan 10 days ago |
| carrier_investigation_open | RF-2195 | T | U |  | where is my order?? | Last scan: Northfield DC on 08/08. Carrier not answering. |
| card_confirmed_stolen | RF-2129 | T | U |  |  | Real cardholder phoned in: 'I've never shopped with you'. Card cancelled. |
