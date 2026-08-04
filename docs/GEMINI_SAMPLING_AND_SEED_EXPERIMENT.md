# Gemini sampling and seed experiment

Profile B (profile-b-sampling) changed only generation sampling: omitted
explicit temperature, top-p, and top-k, set candidate count to one, and used
seed 1701. Prompts, response format, thinking configuration, retry policy,
and safety configuration remained current production behavior.

The partial Phase 1 record contains 4 of the planned 6 calls. Four responses
were accepted by the preliminary evaluator, with one packet showing semantic
repeat agreement so far. The record is incomplete and cannot establish the
required two-packet consistency threshold.

A fixed seed is recorded as a reproducibility input; it is not interpreted as
a guarantee of byte-identical provider responses. Profile B was not promoted.
