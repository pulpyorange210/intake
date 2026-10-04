| Run | Catalog | Forms | Item precision / recall | Retrieval recall | Fields correct | Input tokens / form | Cost / form | Wrong SKU |
|---|---|---|---|---|---|---|---|---|
| baseline (v0.8, same forms) | inline (21 SKUs) | 10 | 100.0% / 100.0% | - | 174/174 | 29,611 | $0.170 | 0 |
| catalog2000_inline | inline | 10 | 100.0% / 100.0% | - | 174/174 | 534,947 | $0.511 | 0 |
| baseline (v0.8, same forms) | inline (21 SKUs) | 50 | 100.0% / 100.0% | - | 792/792 | 29,889 | $0.168 | 0 |
| catalog2000_retrieval | retrieval | 50 | 100.0% / 100.0% | 132/132 | 792/792 | 57,547 | $0.196 | 0 |

### catalog2000_inline
- total cost $5.11; catalog searches 0
- wrong SKUs: none

### catalog2000_retrieval
- total cost $9.80; catalog searches 230
- wrong SKUs: none
