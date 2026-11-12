# Prompt inventory for Blindfold

This directory indexes the prompt roles described in [Blindfold, SenSys 2026](https://doi.org/10.1145/3774906.3802758). Each entry reserves a place for source-verified wording and identifies any separately authored public implementation. The reserved sections are empty and are not loaded by the prompt runners. The [runnable template catalog](../README.md) describes the public templates.

Section 5 contains five core prompt roles and four distinct prompt boxes. Section 5.2.2 describes its prompt in prose. Section 5.3.2 uses one box for branch creation and completion and another for chain fusion. Print page numbers below follow the proceedings. PDF page 1 is print page 1057.

## Core roles

| Entry | Section | Print page | Material in the paper | Public coverage |
| --- | --- | --- | --- | --- |
| [Proxy planning](proxy-planning.md) | §5.2.1 | 1061 | Boxed illustration | [Household planning](../progprompt/README.md) for the ordinary task domain only |
| [Command sanitization](command-sanitization.md) | §5.2.2 | 1061 | Prose description | Original slot open. [Reference audit](../reference_audit.txt) addresses explicit references in existing records. |
| [Dominant action identification](dominant-action-identification.md) | §5.3.1 | 1062 | Simplified scoring box | Source record only |
| [Cover branch creation and completion](cover-branch-generation.md) | §5.3.2 | 1063 | One shared simplified box | Source record only |
| [Chain fusion](chain-fusion.md) | §5.3.2 | 1063 | Separate simplified box | [Checked reconciliation](../README.md#tabletop-chain-fusion) for two logs of the same household transfer |

## Additional interfaces

| Entry | Section | Print page | Material in the paper |
| --- | --- | --- | --- |
| [Structured verifier feedback](verifier-feedback.md) | §5.4.1 | 1064 | The paper describes structured feedback. It does not print a standalone feedback prompt. |
| [Target planner context (ProgPrompt)](target-planner.md) | §4.1 and §6.1 | 1059 and 1064 | External framework used by the target system. The full system-message text used in the experiments is not printed here. |

## External evaluation safeguards

| Entry | Section | Print page | Material in the paper |
| --- | --- | --- | --- |
| [Evaluation safeguard: input check](input-safeguard.md) | §4.2.2 and §7, Defenses | 1060 and 1065 | External POEX safeguard described in the evaluation setup. The paper does not reproduce its full system prompt. |
| [Evaluation safeguard: output check](output-safeguard.md) | §4.2.2 | 1060 | External POEX output check described alongside the input check. No complete system message appears in this section. |

The additional entries distinguish structured verifier feedback and an external planning context from the core prompts. The two POEX checks are optional evaluation dependencies. Local model fine-tuning, random chain extension, and the deterministic precondition/effect verifier have no separate inference-prompt template specified by the paper.

For attribution of an original experiment prompt, the publication record needs its exact wording and version or an upstream source revision, and the terms under which it can be distributed. A simplified box or an independently written public adaptation does not establish that provenance.
