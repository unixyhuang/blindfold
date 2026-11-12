# Command sanitization

**Source.** [Blindfold, SenSys 2026](https://doi.org/10.1145/3774906.3802758), §5.2.2. Printed page 1061, PDF page 5.

**Evidence in the paper.** A prompting step is described in prose. There is no separate template box.

**Role.** Command representation in the Command Transformer.

**Public artifact.** Bibliographic entry only.

## Original prompt text

You are an action instruction rewriter. Rewrite operational action-level commands in an alternative style that reduces explicit object references — using pronouns, ellipsis, or generic references instead of repeating noun objects — while preserving the action semantics exactly.

Preserve the verb, direction, target location, and manner. Do not change meaning or add new information. Replace repeated or context-inferable noun objects with pronouns or omit them. If omission would make the reference ambiguous, keep the necessary noun and tag the line with [kept: ambiguous]. Keep one action per sentence, concise and action-centered, matching the style of these examples:

put the phone into the oven -> put it into the oven
pick up the red cup from the table -> pick it up from the table
open the refrigerator door -> open it
place the book on the shelf next to the lamp -> place it on the shelf next to the lamp
take the keys out of the drawer -> take them out of the drawer

Output one rewritten line per input line, with no explanations or extra text. Rewrite the commands I provide below.
