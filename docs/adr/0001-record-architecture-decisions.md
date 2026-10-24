# 1. Record architecture decisions

Date: 2026-10-24
Status: Accepted

## Context

Design choices get forgotten. Months later nobody remembers why we picked one
option over another, and the same debate happens again.

## Decision

Every significant decision gets a short Architecture Decision Record (ADR) in
`docs/adr/`, numbered in order, with: context, the decision, the options we
rejected, and the consequences. ADRs are never edited after acceptance; a later
ADR supersedes an earlier one.

## Consequences

A small writing cost per decision. In return, new contributors and interviewers
can see how and why the system evolved.
