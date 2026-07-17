---
version: alpha
name: Research Operations Console
description: A restrained, evidence-first interface for EV bus optimization experiments.
colors:
  primary: "#16324F"
  secondary: "#526273"
  tertiary: "#0C7C73"
  neutral: "#F4F7F9"
  surface: "#FFFFFF"
  surface-container: "#E8EEF2"
  on-surface: "#18212B"
  on-primary: "#FFFFFF"
  on-tertiary: "#FFFFFF"
  outline: "#B9C5CE"
  warning: "#8A5A00"
  error: "#B42318"
typography:
  headline-lg:
    fontFamily: Yu Gothic UI
    fontSize: 22px
    fontWeight: 700
    lineHeight: 1.25
  headline-md:
    fontFamily: Yu Gothic UI
    fontSize: 16px
    fontWeight: 700
    lineHeight: 1.35
  body-md:
    fontFamily: Yu Gothic UI
    fontSize: 13px
    fontWeight: 400
    lineHeight: 1.5
  label-md:
    fontFamily: Yu Gothic UI
    fontSize: 12px
    fontWeight: 600
    lineHeight: 1.35
rounded:
  sm: 3px
  md: 6px
spacing:
  xs: 4px
  sm: 8px
  md: 12px
  lg: 20px
components:
  button-primary:
    backgroundColor: "{colors.tertiary}"
    textColor: "{colors.on-tertiary}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 10px
  button-secondary:
    backgroundColor: "{colors.surface-container}"
    textColor: "{colors.on-surface}"
    typography: "{typography.label-md}"
    rounded: "{rounded.sm}"
    padding: 8px
  panel:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.on-surface}"
    rounded: "{rounded.md}"
    padding: 12px
---

## Overview

This is a research operations console, not a consumer dashboard. It should feel calm, precise, and auditable. The interface prioritizes experiment scope, physical constraints, solver conditions, and result validity over decoration.

## Colors

Navy identifies structure and headings. Teal is reserved for the primary next action or a valid ready state. Warning and error colors communicate research validity risks; weather conditions and vehicle types must not be encoded only by color.

## Typography

Use Yu Gothic UI for Japanese and Latin text. Labels are concise and sentence case. Units appear in every numeric field label. Technical storage keys may appear as secondary help text, not as the main label.

## Layout

The primary workflow is ordered as: scenario and scope, depot/fleet inputs, model and cost conditions, Prepare/solve, then evidence review. Related settings live together. Advanced JSON and compatibility controls use progressive disclosure. Persistent actions remain visible while long parameter sections scroll.

## Elevation & Depth

Use borders and spacing instead of shadows. A panel hierarchy of page, section, and field group is sufficient for this desktop tool.

## Shapes

Use small corner radii and rectangular controls. Dense research tables should remain square and aligned.

## Components

Primary buttons start or save a deliberate workflow step. Secondary buttons open editors or diagnostics. Tables show only comparison-critical columns by default; detailed fields belong in the selected-row editor. Terminal-SOC policy is a named choice with an explanation of its mathematical effect.

## Do's and Don'ts

- Do keep the BESS hard operating range separate from an optional terminal target.
- Do show units, data provenance, solver time limit, MIP gap, and fallback status.
- Do preserve existing scenario behavior when loading legacy data.
- Do not hide research-critical values behind color, tooltips, or raw JSON alone.
- Do state explicitly that a selected terminal target is a hard model boundary; range-only mode has no target equality.
- Do not scatter one asset's capacity, SOC, flow permissions, and cost across unrelated pages.
