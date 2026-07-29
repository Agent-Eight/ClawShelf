---
source: sources/monitoring-governance.md
source_type: md
source_sha256: fixture
extraction_method: text
confidence: Medium
---

# Monitoring governance notes

## 总结

### 研究问题

The note asks whether centralized monitoring or community monitoring produces better restoration outcomes (source: `sources/monitoring-governance.md`, section: source text).

### 核心贡献

It reports that centralized monitoring lowers reporting cost while measured restoration outcomes fall for local groups (source: `sources/monitoring-governance.md`, section: source text).

### 方法 / 数据 / 场景

The source is a short comparison of centralized reporting and community monitoring on cost and coverage (source: `sources/monitoring-governance.md`, section: source text).

### 关键发现

Restoration outcomes fall when local groups lose access to the monitoring data (source: `sources/monitoring-governance.md`, section: source text).

### 适用条件与局限

The note gives no sample, no time window, and no definition of the cost measure (source: `sources/monitoring-governance.md`, section: source text).

### 可迁移价值

It contradicts records that treat shared monitoring data as sufficient on its own (source: `sources/monitoring-governance.md`, section: source text).

## 文档在资料架中的作用

Map role: contradiction against records that treat shared monitoring data as an unqualified success condition (source: `sources/monitoring-governance.md`, section: source text).

## 研究问题

Does centralized monitoring or community monitoring produce better restoration outcomes for local groups (source: `sources/monitoring-governance.md`, section: source text)?

## 方法 / 数据 / 场景

A short qualitative comparison of centralized reporting and community monitoring on cost, coverage, and restoration outcomes (source: `sources/monitoring-governance.md`, section: source text).

## 主题

- Community monitoring
- Restoration outcomes

## 关键词

- `community monitoring` — compared monitoring practice; evidence: section: source text
- `monitoring data` — access mechanism under comparison; evidence: section: source text
- `restoration outcomes` — measured result; evidence: section: source text
- `local groups` — affected participants; evidence: section: source text
- `centralized reporting` — contrasting practice; evidence: section: source text
- `reporting cost` — stated trade-off; evidence: section: source text

## RAG 术语

- term: community monitoring
  weight: 5
  aliases: local monitoring
  evidence: section: source text
  role: topic

- term: restoration outcomes
  weight: 5
  aliases: restoration results
  evidence: section: source text
  role: finding

- term: monitoring data
  weight: 4
  aliases: shared monitoring data
  evidence: section: source text
  role: dataset

## 知识图谱标签

- Domain: engineering
- Problem fit: governance trade-offs in restoration monitoring
- Map role: contradiction

## 关键论点

- Centralized monitoring lowers reporting cost while measured restoration outcomes fall for local groups (source: `sources/monitoring-governance.md`, section: source text).

## 方法或依据

The basis is a direct qualitative comparison stated in the source note (source: `sources/monitoring-governance.md`, section: source text).

## 局限性

### 使用条件

- category: Data / Evidence Limits
  limitation: The note gives no sample, time window, or cost definition.
  implication: Treat the comparison as a contradiction to test, not a measured result.
  evidence: section: source text

### 改进方向

- category: Evaluation Limits
  direction: Report restoration outcomes and reporting cost on the same sites.
  expected_value: This would make the stated trade-off testable.
  evidence_or_rationale: rationale: section: source text states the trade-off without measurements

## 轴突信号

- type: Strong Application Method
  signal: Publish monitoring data with a documented decision path for local groups in river restoration.
  evidence: section: source text
- type: Strong Contribution
  signal: Centralized monitoring lowers reporting cost while measured restoration outcomes fall for community observers.
  evidence: section: source text
- type: Strong Method
  signal: Community monitoring is compared against centralized reporting on cost and coverage.
  evidence: section: source text
- type: Strong Limitation
  signal: The note reports no sample and no time window for the cost comparison.
  evidence: section: source text

## 树突信号

- type: Assumption
  signal: Reporting cost and restoration outcomes can be traded off against each other.
  evidence: rationale: section: source text states the trade-off as given
- type: Data / Domain Boundary
  signal: The comparison is limited to river-restoration monitoring programmes.
  evidence: section: source text
- type: Metric Choice
  signal: Reporting cost needs an explicit definition before the comparison holds.
  evidence: rationale: section: source text uses cost without defining it
- type: Failure Mode
  signal: Centralized monitoring may fail when local groups lose access to monitoring data.
  evidence: section: source text
- type: Extension Hint
  signal: Test community monitoring against centralized reporting on restoration outcomes.
  evidence: rationale: section: source text supplies a comparable pair of practices

## 证据备注

- Original source: `sources/monitoring-governance.md`, section: source text.

## 想法信号

- Speculative: pair this contradiction with records that treat shared monitoring data as sufficient (source: `sources/monitoring-governance.md`, section: source text).

## 连接钩子

- `restoration outcomes` can connect to monitoring-practice and community-governance records (source: `sources/monitoring-governance.md`, section: source text).

## 警告

- The fixture source is intentionally brief.
