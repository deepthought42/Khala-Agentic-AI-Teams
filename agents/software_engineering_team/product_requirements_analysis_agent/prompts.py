"""
Prompts for the Product Requirements Analysis Agent.

Prompts for spec review, auto-answer generation, spec update, and spec cleanup phases.
"""

SPEC_REVIEW_PROMPT = """You are a Product Requirements Analysis expert. Review the following product specification to identify gaps, inconsistencies, and areas that need clarification.

Your goal is to ensure the specification is complete and unambiguous before it moves to the planning phase.

Analyze the spec for:
1. **Issues** - Problems, inconsistencies, or conflicts in the specification
2. **Gaps** - Missing requirements, undefined behaviors, or incomplete features
3. **Open Questions** - Items that need clarification from the product owner

For each open question, provide 2-3 answer options based on industry best practices. For each option, include:
- A clear label describing the choice
- A rationale explaining why this might be the right choice
- A confidence score (0.0-1.0) based on how likely this is the best choice
- Mark exactly one option as the recommended default (highest confidence)

Categorize questions as: architecture, security, ux, performance, business, integration, or general.
Prioritize questions as: high (blocking), medium (important), or low (nice to clarify).

Respond with a JSON object only, no markdown:
{{
  "issues": ["issue 1", "issue 2"],
  "gaps": ["gap 1", "gap 2"],
  "open_questions": [
    {{
      "id": "q1",
      "question_text": "What authentication method should be used?",
      "context": "The spec mentions user login but doesn't specify the authentication approach.",
      "category": "security",
      "priority": "high",
      "options": [
        {{
          "id": "opt1",
          "label": "OAuth 2.0 with social providers (Google, GitHub)",
          "is_default": true,
          "rationale": "Industry standard for web apps, reduces password management burden, familiar to users",
          "confidence": 0.85
        }},
        {{
          "id": "opt2", 
          "label": "Email/password with optional 2FA",
          "is_default": false,
          "rationale": "Traditional approach, full control over auth flow, but requires password reset flows",
          "confidence": 0.6
        }},
        {{
          "id": "opt3",
          "label": "Passwordless (magic link or OTP)",
          "is_default": false,
          "rationale": "Modern approach eliminating passwords, but may confuse some users",
          "confidence": 0.5
        }}
      ]
    }}
  ],
  "summary": "Brief summary of the review findings"
}}

Specification:
---
{spec_content}
---
"""

AUTO_ANSWER_PROMPT = """You are a Product Analyst expert. Given the following question about a product specification, select the best answer option based on industry best practices and product success patterns.

Analyze the question considering:
1. **Industry best practices** - What do successful products in this domain typically do?
2. **Product goals and constraints** - What does the spec indicate about priorities?
3. **Risk assessment** - Which option minimizes risk while maximizing value?
4. **User expectations** - What would users expect based on similar products?
5. **Technical feasibility** - Which option is most practical to implement?

Question: {question_text}

Context: {context}

Available Options:
{options}

Product Specification Excerpt:
---
{spec_content}
---

Respond with a JSON object only, no markdown:
{{
  "selected_option_id": "opt1",
  "rationale": "Detailed explanation (2-4 sentences) of why this is the best choice based on the analysis above...",
  "confidence": 0.85,
  "risks": [
    "Potential risk or downside of this choice",
    "Another consideration to keep in mind"
  ],
  "alternatives_considered": "Brief note on why the other options were not selected",
  "industry_references": [
    "Reference to industry best practice or successful product pattern"
  ]
}}
"""

SPEC_UPDATE_PROMPT = """You are a Product Specification Writer. Update the product specification to incorporate the answers to open questions.

For each answered question:
1. Integrate the answer naturally into the specification
2. Add specific details and requirements based on the chosen option
3. Ensure consistency with existing content
4. Make the spec more actionable and unambiguous

Rules:
- Preserve all existing valid content
- Add new sections or details where needed
- Write in clear, professional language
- Use specific, measurable requirements where possible
- Mark any assumptions clearly

Current Specification:
---
{spec_content}
---

Answered Questions:
---
{answered_questions}
---

Respond with the FULL updated specification as plain text (markdown format). Include all original content plus the new details from the answered questions. Do not include any JSON or code blocks - just the specification content.
"""

SPEC_CLEANUP_PROMPT = """You are a Product Specification Validator. Review and clean up the specification to ensure it is complete, consistent, and ready for the planning phase.

Perform the following checks:
1. **Completeness** - All features have clear requirements
2. **Consistency** - No conflicting requirements
3. **Clarity** - No ambiguous language
4. **Structure** - Well-organized with clear sections
5. **Actionability** - Requirements can be turned into tasks

If issues are found, fix them in the output. If the spec is valid, return it with any minor formatting improvements.

Specification:
---
{spec_content}
---

Respond with a JSON object only, no markdown:
{{
  "is_valid": true,
  "validation_issues": ["issue 1 that was found and fixed", "issue 2"],
  "cleaned_spec": "The full cleaned specification content as a string...",
  "summary": "Brief summary of what was validated and any changes made"
}}
"""

QUESTION_GENERATION_PROMPT = """Based on the following gap or issue identified in the specification, generate a structured question with answer options.

Gap/Issue: {issue}

Context from spec:
---
{spec_context}
---

Generate a question that would help resolve this gap. Provide 2-3 practical answer options based on industry best practices.

Respond with JSON only:
{{
  "id": "q_unique_id",
  "question_text": "Clear question to resolve the gap",
  "context": "Why this question matters and what impact the answer will have",
  "category": "architecture|security|ux|performance|business|integration|general",
  "priority": "high|medium|low",
  "options": [
    {{
      "id": "opt1",
      "label": "Option description",
      "is_default": true,
      "rationale": "Why this might be the best choice",
      "confidence": 0.8
    }}
  ]
}}
"""
