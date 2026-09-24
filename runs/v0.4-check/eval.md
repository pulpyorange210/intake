# Eval: v0.4-check

Forms: 6 | fully correct: 0 | needs_review: 0 | cost: $0.89

## Item detection

Precision 100.0% | Recall 100.0% | F1 100.0% (TP 13, FP 0, FN 0)

Near-twin forms (a non-sold catalog name overlaps a sold one): 1 forms, precision 100.0%, recall 100.0%

## Field accuracy (matched items)

Abstained = left null and flagged ambiguous (counted wrong in Accuracy, excluded from Answered).

| Field | Accuracy | Answered accuracy | Abstained |
|---|---|---|---|
| currency | 100.0% | 100.0% | 0 |
| total_listed_value | 100.0% | 100.0% | 0 |
| quantity | 100.0% | 100.0% | 0 |
| unit_price | 100.0% | 100.0% | 0 |
| service_start_date | 100.0% | 100.0% | 0 |
| service_end_date | 100.0% | 100.0% | 0 |
| invoicing_schedule_type | 0.0% | 0.0% | 0 |
| invoicing_frequency | 76.9% | 100.0% | 3 |
| payment_terms | 100.0% | 100.0% | 0 |
| special_notes | 0.0% | 0.0% | 0 |

## Header accuracy

| Field | Accuracy |
|---|---|
| effective_date | 100.0% |
| contract_signed_date_buying_company | 100.0% |
| contract_signed_date_selling_company | 100.0% |

invoicing_frequency source: {'inferred_from_pricing': 10, 'ambiguous': 3}

## Failures

### invoicing_schedule_type (13)
- of-0002 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='upfront'
- of-0011 PROFESSIONAL_SERVICE: pred=None gold='upfront'
- of-0011 SANDBOX: pred=None gold='upfront'
- of-0018 SANDBOX: pred=None gold='recurring'
- of-0034 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='hybrid'
- of-0034 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='hybrid'
- of-0034 SKILLS_PORTFOLIO: pred=None gold='hybrid'
- of-0039 WHATSAPP_SMS_CREDITS: pred=None gold='hybrid'
- of-0039 PREMIUM_SUPPORT: pred=None gold='hybrid'
- of-0044 TALENT_ACQUISITION_CORE: pred=None gold='hybrid'
- of-0044 TALENT_ACQUISITION: pred=None gold='hybrid'
- of-0044 ELEVATE_SUCCESS_PLAN: pred=None gold='hybrid'
- of-0044 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='hybrid'

### invoicing_frequency (3)
- of-0034 TALENT_MANAGEMENT_ENTERPRISE: ABSTAINED (ambiguous) gold='one-time'
- of-0034 TALENT_INTELLIGENCE_PLATFORM: ABSTAINED (ambiguous) gold='one-time'
- of-0034 SKILLS_PORTFOLIO: ABSTAINED (ambiguous) gold='one-time'

### special_notes (13)
- of-0002 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred='Up to Customer Employee Size: 2,500' gold='Annual uplift terms included as agreed.'
- of-0011 PROFESSIONAL_SERVICE: pred=None gold='Includes standard onboarding support.'
- of-0011 SANDBOX: pred=None gold='Usage caps apply per signed order form.'
- of-0018 SANDBOX: pred='Up to Customer Employee Size: 50,000' gold='Includes standard onboarding support.'
- of-0034 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='Annual uplift terms included as agreed.'
- of-0034 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='Annual uplift terms included as agreed.'
- of-0034 SKILLS_PORTFOLIO: pred=None gold='Subject to master subscription agreement.'
- of-0039 WHATSAPP_SMS_CREDITS: pred=None gold='Annual uplift terms included as agreed.'
- of-0039 PREMIUM_SUPPORT: pred=None gold='Subject to master subscription agreement.'
- of-0044 TALENT_ACQUISITION_CORE: pred=None gold='Customer-specific pricing approved.'
- of-0044 TALENT_ACQUISITION: pred=None gold='Customer-specific pricing approved.'
- of-0044 ELEVATE_SUCCESS_PLAN: pred=None gold='Customer-specific pricing approved.'
- of-0044 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Includes standard onboarding support.'
