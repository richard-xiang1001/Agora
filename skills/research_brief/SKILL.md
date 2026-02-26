name: research_brief
description: Multi-source research synthesis for brief writing
version: "1.0"
permissions_scope: scope_unknown_intersection
preferred_models:
  - gemini-2.5-pro
  - gpt-4.5
input_schema:
  - field: topic
    type: text
output_schema:
  - field: summary
  - field: citations
  - field: uncertainties
verification_strategy: source_independence_check
