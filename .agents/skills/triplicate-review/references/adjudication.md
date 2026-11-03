# Convergence and adjudication

## Cluster

Treat findings as the same when they point at the same file and nearby lines
(roughly within 5) and describe the same underlying problem, even if worded
differently. When unsure whether two findings match, compare the failure
scenarios: the same scenario means the same finding.

For each cluster record:
- how many reviewers reported it (3/3, 2/3, singleton)
- the highest severity any reviewer gave, and note if severities disagree
- the clearest wording and suggestion among them

## Treat by agreement

- **3/3 and 2/3**: accept as findings. Still skim the cited code so you can
  explain each one.
- **Singletons**: adjudicate before accepting.

## Adjudicate singletons

For each singleton:
1. Read the cited code and its surroundings.
2. Try to disprove it: look for a guard elsewhere, a test that covers it, or a
   convention that makes it intentional.
3. If it is cheap, run a test or repro.
4. Decide:
   - **Confirmed**: promote it to a finding at the severity you can justify.
   - **Rejected**: drop it; keep a one-line reason for the report.
   - **Uncertain**: keep it out of the review and ask the human.

A singleton is not weaker for being alone; reviewers often differ in what they
dig into. It is weaker only if you cannot confirm it.

## Fewer than three reviewers

- **Two**: label findings 2/2 or singleton and treat them as above.
- **One**: every finding is a singleton; adjudicate all of them, and say in the
  report that only one review completed.
- **None**: stop and tell the human.

## Verdict

Use the verdict rule in `.agents/shared/pr-comments.md`. The human's extra
guidance can move the lines (for example, "treat medium as blocking").
