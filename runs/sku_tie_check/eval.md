# Eval: sku_tie_check

Forms: 21 | fully correct: 0 | needs_review: 3 | cost: $4.48

## Item detection

Products are scored like the fields: unflagged SKUs give precision and recall; a SKU flagged ambiguous with the expected SKU among its candidates is counted in its own column, as neither correct nor wrong.

| | Precision | Recall | F1 | TP | FP | FN | Flagged ambiguous |
|---|---|---|---|---|---|---|---|
| All forms | 100.0% | 100.0% | 100.0% | 56 | 0 | 0 | 2 (expected SKU as the value: 1, among the alternatives: 1) |
| Near-twin forms (20) | 100.0% | 100.0% | | | | | 1 |

(Near-twin forms: a catalog name that isn't sold overlaps a sold one.)

## Field accuracy

Overall counts every matched item (abstentions count as wrong). The other columns split it by how the output was marked: unflagged answers, answers flagged ambiguous (value given with the ambiguity next to it), and abstentions (left null because ambiguous).

### Contract items

| Field | Overall | Unflagged | Flagged ambiguous | Abstained |
|---|---|---|---|---|
| currency | 100.0% | 100.0% (n=58) | - | - |
| total_listed_value | 100.0% | 100.0% (n=58) | - | - |
| quantity | 100.0% | 100.0% (n=58) | - | - |
| unit_price | 100.0% | 100.0% (n=58) | - | - |
| service_start_date | 100.0% | 100.0% (n=58) | - | - |
| service_end_date | 100.0% | 100.0% (n=58) | - | - |
| invoicing_schedule_type | 0.0% | 0.0% (n=58) | - | - |
| invoicing_frequency | 87.9% | 100.0% (n=44) | 50.0% (n=14) | - |
| payment_terms | 100.0% | 100.0% (n=58) | - | - |
| special_notes | 0.0% | 0.0% (n=58) | - | - |

### Order form header

| Field | Overall | Unflagged | Flagged ambiguous | Abstained |
|---|---|---|---|---|
| effective_date | 95.2% | 100.0% (n=20) | - | 1 |
| contract_signed_date_buying_company | 100.0% | 100.0% (n=21) | - | - |
| contract_signed_date_selling_company | 100.0% | 100.0% (n=21) | - | - |

invoicing_frequency source: {'inferred_from_pricing': 58}

## Failures

### SKUs flagged ambiguous (not failures)
- of-0019: PREMIUM_SUPPORT flagged, alternatives ['PREMIER_SUPPORT'], expected PREMIUM_SUPPORT
- of-0031: PREMIER_SUPPORT flagged, alternatives ['PREMIUM_SUPPORT'], expected PREMIUM_SUPPORT

### invoicing_schedule_type (58)
- of-0001 TALENT_ACQUISITION_CORE: pred=None gold='upfront'
- of-0001 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='upfront'
- of-0001 PROFESSIONAL_SERVICE: pred=None gold='upfront'
- of-0003 ELEVATE_SUCCESS_PLAN: pred=None gold='upfront'
- of-0003 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='upfront'
- of-0004 PROFESSIONAL_SERVICE: pred=None gold='hybrid'
- of-0004 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='hybrid'
- of-0006 ELEVATE_SUCCESS_PLAN: pred=None gold='recurring'
- of-0006 PROFESSIONAL_SERVICE: pred=None gold='recurring'
- of-0006 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='recurring'
- of-0006 TALENT_ACQUISITION_CANDIDATE_EXPERIENCE: pred=None gold='recurring'
- of-0008 TALENT_ACQUISITION: pred=None gold='recurring'
- of-0008 TALENT_ACQUISITION_CRM: pred=None gold='recurring'
- of-0008 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='recurring'
- of-0010 TALENT_ACQUISITION: pred=None gold='recurring'
- of-0010 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='recurring'
- of-0014 TALENT_ACQUISITION: pred=None gold='upfront'
- of-0014 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='upfront'
- of-0017 TALENT_ACQUISITION: pred=None gold='upfront'
- of-0017 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='upfront'
- of-0017 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='upfront'
- of-0019 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='upfront'
- of-0019 TALENT_ACQUISITION: pred=None gold='upfront'
- of-0019 PROFESSIONAL_SERVICE: pred=None gold='upfront'
- of-0019 PREMIUM_SUPPORT: pred=None gold='upfront'
- of-0021 TALENT_ACQUISITION: pred=None gold='recurring'
- of-0021 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='recurring'
- of-0021 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='recurring'
- of-0021 TALENT_ACQUISITION_CORE: pred=None gold='recurring'
- of-0025 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='upfront'
- of-0025 TALENT_ACQUISITION_CANDIDATE_EXPERIENCE: pred=None gold='upfront'
- of-0026 TALENT_ACQUISITION: pred=None gold='recurring'
- of-0026 TALENT_MANAGEMENT_CORE: pred=None gold='recurring'
- of-0026 WHATSAPP_SMS_CREDITS: pred=None gold='recurring'
- of-0027 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='hybrid'
- of-0027 PREMIUM_SUPPORT: pred=None gold='hybrid'
- of-0027 SANDBOX: pred=None gold='hybrid'
- of-0031 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='hybrid'
- of-0031 PREMIUM_SUPPORT: pred=None gold='hybrid'
- of-0033 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='hybrid'
- of-0033 TALENT_ACQUISITION_CANDIDATE_EXPERIENCE: pred=None gold='hybrid'
- of-0033 SANDBOX: pred=None gold='hybrid'
- of-0037 PROFESSIONAL_SERVICE: pred=None gold='hybrid'
- of-0037 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='hybrid'
- of-0037 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='hybrid'
- of-0037 TALENT_ACQUISITION: pred=None gold='hybrid'
- of-0038 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='recurring'
- of-0040 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='upfront'
- of-0040 TALENT_ACQUISITION: pred=None gold='upfront'
- of-0043 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='hybrid'
- of-0043 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='hybrid'
- of-0044 TALENT_ACQUISITION_CORE: pred=None gold='hybrid'
- of-0044 TALENT_ACQUISITION: pred=None gold='hybrid'
- of-0044 ELEVATE_SUCCESS_PLAN: pred=None gold='hybrid'
- of-0044 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='hybrid'
- of-0048 TALENT_ACQUISITION_CORE: pred=None gold='upfront'
- of-0048 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='upfront'
- of-0048 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='upfront'

### invoicing_frequency (7)
- of-0004 PROFESSIONAL_SERVICE: [flagged ambiguous] pred='one-time' gold='yearly'
- of-0004 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: [flagged ambiguous] pred='one-time' gold='yearly'
- of-0025 TALENT_MANAGEMENT_ENTERPRISE: [flagged ambiguous] pred='one-time' gold='yearly'
- of-0025 TALENT_ACQUISITION_CANDIDATE_EXPERIENCE: [flagged ambiguous] pred='one-time' gold='yearly'
- of-0026 TALENT_ACQUISITION: [flagged ambiguous] pred='one-time' gold='yearly'
- of-0026 TALENT_MANAGEMENT_CORE: [flagged ambiguous] pred='one-time' gold='yearly'
- of-0026 WHATSAPP_SMS_CREDITS: [flagged ambiguous] pred='one-time' gold='yearly'

### special_notes (58)
- of-0001 TALENT_ACQUISITION_CORE: pred=None gold='Annual uplift terms included as agreed.'
- of-0001 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Annual uplift terms included as agreed.'
- of-0001 PROFESSIONAL_SERVICE: pred=None gold='Subject to master subscription agreement.'
- of-0003 ELEVATE_SUCCESS_PLAN: pred='Up to Customer Employee Size: 10,000' gold='Subject to master subscription agreement.'
- of-0003 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred='Up to Customer Employee Size: 10,000' gold='Subject to master subscription agreement.'
- of-0004 PROFESSIONAL_SERVICE: pred=None gold='Usage caps apply per signed order form.'
- of-0004 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Includes standard onboarding support.'
- of-0006 ELEVATE_SUCCESS_PLAN: pred=None gold='Customer-specific pricing approved.'
- of-0006 PROFESSIONAL_SERVICE: pred=None gold='Annual uplift terms included as agreed.'
- of-0006 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Annual uplift terms included as agreed.'
- of-0006 TALENT_ACQUISITION_CANDIDATE_EXPERIENCE: pred=None gold='Annual uplift terms included as agreed.'
- of-0008 TALENT_ACQUISITION: pred=None gold='Usage caps apply per signed order form.'
- of-0008 TALENT_ACQUISITION_CRM: pred=None gold='Includes standard onboarding support.'
- of-0008 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='Customer-specific pricing approved.'
- of-0010 TALENT_ACQUISITION: pred='Priced up to Customer Employee Size: 2,500' gold='Annual uplift terms included as agreed.'
- of-0010 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred='Priced up to Customer Employee Size: 2,500' gold='Usage caps apply per signed order form.'
- of-0014 TALENT_ACQUISITION: pred=None gold='Subject to master subscription agreement.'
- of-0014 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='Customer-specific pricing approved.'
- of-0017 TALENT_ACQUISITION: pred=None gold='Annual uplift terms included as agreed.'
- of-0017 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Customer-specific pricing approved.'
- of-0017 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='Subject to master subscription agreement.'
- of-0019 TALENT_INTELLIGENCE_PLATFORM: pred='Up to Customer Employee Size: 25,000' gold='Usage caps apply per signed order form.'
- of-0019 TALENT_ACQUISITION: pred='Up to Customer Employee Size: 25,000' gold='Usage caps apply per signed order form.'
- of-0019 PROFESSIONAL_SERVICE: pred=None gold='Annual uplift terms included as agreed.'
- of-0019 PREMIUM_SUPPORT: pred=None gold='Usage caps apply per signed order form.'
- of-0021 TALENT_ACQUISITION: pred=None gold='Annual uplift terms included as agreed.'
- of-0021 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Customer-specific pricing approved.'
- of-0021 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='Includes standard onboarding support.'
- of-0021 TALENT_ACQUISITION_CORE: pred=None gold='Usage caps apply per signed order form.'
- of-0025 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='Usage caps apply per signed order form.'
- of-0025 TALENT_ACQUISITION_CANDIDATE_EXPERIENCE: pred=None gold='Includes standard onboarding support.'
- of-0026 TALENT_ACQUISITION: pred=None gold='Subject to master subscription agreement.'
- of-0026 TALENT_MANAGEMENT_CORE: pred=None gold='Subject to master subscription agreement.'
- of-0026 WHATSAPP_SMS_CREDITS: pred=None gold='Includes standard onboarding support.'
- of-0027 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Customer-specific pricing approved.'
- of-0027 PREMIUM_SUPPORT: pred=None gold='Customer-specific pricing approved.'
- of-0027 SANDBOX: pred=None gold='Usage caps apply per signed order form.'
- of-0031 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Customer-specific pricing approved.'
- of-0031 PREMIUM_SUPPORT: pred=None gold='Usage caps apply per signed order form.'
- of-0033 TALENT_MANAGEMENT_ENTERPRISE: pred='Up to Customer Employee Size: 15,000' gold='Annual uplift terms included as agreed.'
- of-0033 TALENT_ACQUISITION_CANDIDATE_EXPERIENCE: pred='Up to Customer Employee Size: 15,000' gold='Customer-specific pricing approved.'
- of-0033 SANDBOX: pred='Up to Customer Employee Size: 15,000' gold='Subject to master subscription agreement.'
- of-0037 PROFESSIONAL_SERVICE: pred=None gold='Customer-specific pricing approved.'
- of-0037 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Includes standard onboarding support.'
- of-0037 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='Usage caps apply per signed order form.'
- of-0037 TALENT_ACQUISITION: pred=None gold='Annual uplift terms included as agreed.'
- of-0038 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred='Up to Customer Employee Size: 5,000' gold='Includes standard onboarding support.'
- of-0040 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='Subject to master subscription agreement.'
- of-0040 TALENT_ACQUISITION: pred=None gold='Usage caps apply per signed order form.'
- of-0043 TALENT_MANAGEMENT_ENTERPRISE: pred=None gold='Customer-specific pricing approved.'
- of-0043 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Customer-specific pricing approved.'
- of-0044 TALENT_ACQUISITION_CORE: pred=None gold='Customer-specific pricing approved.'
- of-0044 TALENT_ACQUISITION: pred=None gold='Customer-specific pricing approved.'
- of-0044 ELEVATE_SUCCESS_PLAN: pred=None gold='Customer-specific pricing approved.'
- of-0044 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Includes standard onboarding support.'
- of-0048 TALENT_ACQUISITION_CORE: pred=None gold='Customer-specific pricing approved.'
- of-0048 TALENT_INTELLIGENCE_PLATFORM_PREMIUM_ADDON: pred=None gold='Customer-specific pricing approved.'
- of-0048 TALENT_INTELLIGENCE_PLATFORM: pred=None gold='Usage caps apply per signed order form.'

### effective_date (1)
- of-0044: ABSTAINED pred=None gold='2024-03-01'
