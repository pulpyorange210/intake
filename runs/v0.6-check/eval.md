# Eval: v0.6-check

Forms: 2 | fully correct: 0 | needs_review: 0 | cost: $0.33

## Item detection

Precision 100.0% | Recall 100.0% | F1 100.0% (TP 4, FP 0, FN 0)

Near-twin forms (a non-sold catalog name overlaps a sold one): 1 forms, precision 100.0%, recall 100.0%

## Field accuracy

Overall counts every matched item (abstentions count as wrong). The other columns split it by how the output was marked: unflagged answers, answers flagged ambiguous (value given with the ambiguity next to it), and abstentions (left null because ambiguous).

### Contract items

| Field | Overall | Unflagged | Flagged ambiguous | Abstained |
|---|---|---|---|---|
| currency | 100.0% | 100.0% (n=4) | - | - |
| total_listed_value | 100.0% | 100.0% (n=4) | - | - |
| quantity | 100.0% | 100.0% (n=4) | - | - |
| unit_price | 100.0% | 100.0% (n=4) | - | - |
| service_start_date | 100.0% | 100.0% (n=4) | - | - |
| service_end_date | 100.0% | 100.0% (n=4) | - | - |
| invoicing_schedule_type | 0.0% | 0.0% (n=4) | - | - |
| invoicing_frequency | 100.0% | 100.0% (n=4) | - | - |
| payment_terms | 100.0% | 100.0% (n=4) | - | - |
| special_notes | 0.0% | 0.0% (n=4) | - | - |

### Order form header

| Field | Overall | Unflagged | Flagged ambiguous | Abstained |
|---|---|---|---|---|
| effective_date | 50.0% | 100.0% (n=1) | - | 1 |
| contract_signed_date_buying_company | 100.0% | 100.0% (n=2) | - | - |
| contract_signed_date_selling_company | 100.0% | 100.0% (n=2) | - | - |

invoicing_frequency source: {'inferred_from_pricing': 4}

## Failures

### invoicing_schedule_type (4)
- of-0032 TALENT_ACQUISITION: pred=None gold='hybrid'
- of-0048 TALENT_ACQUISITION_CORE: pred=None gold='upfront'
- of-0048 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='upfront'
- of-0048 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='upfront'

### special_notes (4)
- of-0032 TALENT_ACQUISITION: pred='Up to Customer Employee Size: 10,000' gold='Includes standard onboarding support.'
- of-0048 TALENT_ACQUISITION_CORE: pred='Up to Customer Employee Size: 25,000' gold='Customer-specific pricing approved.'
- of-0048 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred='Up to Customer Employee Size: 25,000' gold='Customer-specific pricing approved.'
- of-0048 TALENT_INTELLIGENCE_PLATFORM: pred='Up to Customer Employee Size: 25,000' gold='Usage caps apply per signed order form.'

### effective_date (1)
- of-0032: ABSTAINED pred=None gold='2024-06-04'
