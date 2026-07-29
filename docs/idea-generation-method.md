# Idea Generation Method

## Goal

Improve ClawShelf's idea generation layer by turning normalized article records
into structured relation graphs. The goal is not to randomly connect similar
articles, but to find useful complements between one article's contribution,
method, limitation, application path, assumptions, and failure modes and another
article's corresponding signals.

## Core Metaphor

Treat each article as a neuron.

- Axons are high-salience outgoing signals: strong contributions, strong
  methods, strong limitations, and strong application methods.
- Dendrites are lower-salience receptive signals: assumptions, data boundaries,
  metric choices, failure modes, weak hints, and extension opportunities.
- An idea appears when one article's outgoing signal usefully complements
  another article's receptive or outgoing signal.

This metaphor should guide the schema and scoring, but the implementation should
use explicit relation fields rather than metaphor-only labels.

## Research-Informed Principles

### Structure Mapping

Good analogies come from matching relational structure, not surface words. For
ClawShelf, this means comparing patterns such as:

```text
method -> problem -> limitation -> possible transfer
```

rather than only comparing shared tags or topic overlap.

Useful candidate patterns:

- `A.contribution -> B.limitation`
- `A.method -> B.application_gap`
- `A.limitation -> B.method`
- `A.failure_mode -> B.evaluation_method`
- `A.assumption -> B.domain_boundary`

### Associative Generation And Executive Filtering

Creative cognition can be treated as a two-stage process:

- Generate candidates broadly through associative memory.
- Filter and refine candidates with goal-directed control.

For ClawShelf, candidate retrieval should be generous, but final idea cards must
pass stricter checks for evidence, complementarity, novelty, and usefulness.

### Conceptual Blending

An idea often combines selected parts of two conceptual spaces rather than
merging both papers wholesale. Therefore, an idea card should name the exact
parts being blended: contribution, method, limitation, assumption, evaluation,
or application method.

## Idea Types

### Innovation

Innovation ideas need enough overlap to be meaningful, but not so much overlap
that the result is only an incremental restatement.

Expected score pattern:

- `overlap_score`: medium
- `complementarity_score`: high
- `novelty_score`: medium or high
- `evidence_score`: medium or high

Typical outputs:

- Apply a method from one article to a limitation in another.
- Transfer an evaluation method into a nearby but not identical domain.
- Combine a strong contribution with an unaddressed application path.

### Consolidation

Consolidation ideas need high overlap, but not total identity. The value is in
replication, boundary testing, robustness checks, benchmark extension, or
stronger evidence.

Expected score pattern:

- `overlap_score`: high
- `difference_score`: non-trivial
- `evidence_value_score`: high
- `novelty_score`: low or medium

Typical outputs:

- Replicate a result under a different dataset or population.
- Stress-test a method under a known limitation.
- Compare two nearby benchmarks or evaluation protocols.

## Required Article Signals

Idea generation depends on normalization quality. Each normalized record should
eventually expose these signals.

### Axon Signals

- Strong Contribution
- Strong Method
- Strong Limitation
- Strong Application Method

### Dendrite Signals

- Assumptions
- Data / Domain Boundary
- Metric Choice
- Failure Mode
- Extension Hint

## Candidate Generation

1. Retrieve a broad candidate set using curated RAG terms, keywords, topic tags,
   method tags, limitation categories, and connection hooks.
2. Build relation-level pairs between article signals.
3. Classify each pair as innovation, consolidation, or reject.
4. Score the pair for overlap, complementarity, novelty, evidence, and
   feasibility.
5. Emit idea cards only when the relation can be explained with source-grounded
   evidence.

## Idea Card Template

```markdown
## 想法标题

### 类型
创新 / 巩固

### 连接来源
- Article A: ...
- Article B: ...

### 互补结构
A 的 [贡献/方法/限制] 可以补 B 的 [限制/应用缺口/失败模式]。

### 为什么不是简单重复
说明 overlap 在哪里，差异在哪里。

### 为什么不是牵强类比
说明共享的关系结构，而不是只共享关键词。

### 可验证假设
如果这个 idea 成立，应该观察到什么？

### 最小实验
最小可做的验证方式。

### 主要风险
最可能失败的原因。

### 下一步
读文献 / 做实验 / 生成 synthesis / 放弃。
```

## Updated Plan

- [x] Create this idea generation method document under `docs/`.
- [x] Update the normalized-record template with Axon Signals and Dendrite
      Signals.
- [x] Update the normalizer parser and validator so the new signal sections are
      recognized and evidence-grounded.
- [x] Update deterministic auto-normalization to emit conservative axon and
      dendrite signals from inspected source text.
- [x] Add relation-pair extraction helpers for contribution-method-limitation
      matching.
- [x] Add an idea candidate scorer with overlap, complementarity, novelty,
      evidence, and feasibility scores.
- [x] Add separate generation modes for Innovation Ideas and Consolidation
      Ideas.
- [x] Add an idea-card template using Chinese user-facing section headings.
- [x] Add tests for signal parsing, candidate classification, and rejection of
      weak keyword-only analogies.
- [x] Run validation on the quant-trading scratch shelf and at least one
      non-trading shelf/article set.
- [x] Update README and skill-design docs after the implementation shape is
      stable.

## Acceptance Criteria

- Ideas cite the exact source signals being connected.
- Innovation ideas have partial overlap plus strong complementarity.
- Consolidation ideas have high overlap plus a non-trivial difference.
- Weak keyword-only matches are rejected or downgraded.
- Every idea card explains why it is not simple repetition and why it is not a
  forced analogy.
- The implementation remains usable for academic papers, industry reports,
  benchmarks, technical notes, and white papers.
