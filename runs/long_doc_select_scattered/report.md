| Variant | Mode | Pages seen | Page recall | Searches | Input tokens | Output tokens | Cost | Time | Turns | Items correct |
|---|---|---|---|---|---|---|---|---|---|---|
| n1000_scattered | select | 29 | 5/5 | 6 | 857,380 | 7,873 | $1.26 | 92s | 9 | NO |

### n1000_scattered
- needed: p.120 service term (start and end dates); p.415 pricing table; p.640 invoicing schedule and payment terms; p.880 signatures; p.955 amendment changing a price
- pages sent up front: 1, 2, 158, 159, 160, 335, 336, 337, 414, 415, 416, 639, 640, 641, 954, 955, 956, 981, 982, 983
- pages read: 120, 121, 879, 880, 881, 417, 418, 419, 53
- items: ['SKU-001', 'SKU-002', 'SKU-003']; excluded: ['SKU-004', 'SKU-005']
- needs_review: True; problems: ["SKU-001.invoicing_schedule_type: 'upfront' != 'recurring'", "SKU-002.invoicing_schedule_type: 'upfront' != 'recurring'", "SKU-003.invoicing_schedule_type: 'upfront' != 'recurring'"]
- payment terms / special notes: {'SKU-001': ('Net 55', 'Up to Customer Employee Size: 25,000'), 'SKU-002': ('Net 55', 'Up to Customer Employee Size: 25,000'), 'SKU-003': ('Net 55', 'Amended by Amendment No. 1 to Sales Order Form (entered into as of 10/27/2023): the annual Premium Support fee is replaced with $45,000.00 per year for Year 1, Year 2 and Year 3 (original table showed $50,700.00 per year).')}
- header: effective None, signed buyer 2023-10-12, seller 2023-10-12, grand total 1125000.0
