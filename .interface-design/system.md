# AI Scientist Workbench Interface System

## Direction and feel

- A calm light research workbench inside the NAIS Science product family: cool platform canvas, translucent navigation chrome, white work cards, and Apple-blue controls.
- The primary human is a researcher supervising long-running autonomous experiments and reviewing evidence between runs.
- The interface should feel inspectable and operational, closer to a lab console and research notebook than a generic SaaS dashboard.
- Signature: the shared platform shell frames a dark research instrument panel where numbered stages, execution signals, and provenance remain immediately legible.

## Depth and spacing

- Depth strategy: translucent platform chrome, quiet 1–2px panel lift, and restrained borders. Use deeper shadow only for dark executable instruments and overlays.
- Surface order: cool gray `graphite-canvas` / translucent rail → white `bench-surface` cards → gray `bench-raised` and `input-well` controls → dark `rack-ink` research instruments.
- Borders use `glass-line`; selected controls use platform blue, while instrument edges and active signals use phosphor mint.
- Base spacing unit: 4px. Dense component padding is 12–16px; panels use 18–24px; major section gaps use 32–36px.
- Radius scale: controls 11–13px, panels 22px, compact instrument groups 16px, overlays 14px.

## Palette and typography

- Canvas `#f5f5f7`; translucent rail derived from `#f8f8fa`; surface `#ffffff`; raised/input well `#f1f1f3` / `#f5f5f7`.
- Primary ink `#1d1d1f`; secondary `#3a3a3c`; tertiary `#6e6e73`; muted `#86868b`.
- Platform blue `#0071e3` is reserved for navigation, focus, progress, links, and primary actions.
- Research instruments use `#0b1716` rack ink, `#17302c` raised nodes, `#effaf6` primary text, `#58ddb2` phosphor signals, and `#8ea49f` cooled-steel metadata. Mint is reserved for runtime state, indices, and edges; it does not replace primary text.
- Amber communicates caution, coral communicates failure/destructive actions, and green communicates completion.
- Interface type uses Pretendard/Noto Sans KR fallbacks. Records, timestamps, counts, and provenance labels use JetBrains Mono/SFMono fallbacks.
- Large-text default: 18px body, 15px captions, 14px supporting data, and 12–13px even for short provenance/status labels. Section headings are 20–22px and the page heading is 30px mobile / 36px desktop.

## Reusable component patterns

- Primary button — 46px minimum height · 18px horizontal padding · 13px radius · platform-blue fill · soft blue lift · scale to .97 on press.
- Icon button — 40×40px · 12px radius · neutral gray fill · no hard border · explicit hover/focus/press states.
- Panel — 22px radius · 1px quiet border · white surface · layered platform shadow.
- Launch deck — 2:1 form/preview split on wide screens · white editable fields beside a dark live protocol preview · collapse to one column at 900px · preview readiness, route, and outputs update without submitting.
- Research topology — one dark rack panel · white stage titles · compact semantic stage/lane groups · phosphor completion/current signals · platform-blue inspection selection · red only for failed or stopped stages · full-width fit on desktop and vertical sequence on mobile.
- Topology readout — each stage is a semantic button · click or arrow keys select a stage · selected stage uses a blue focus edge while non-selected siblings dim · compact readout below preserves stage number, state, provenance, and a current-stage return action.
- Panel header — 62–76px height depending on density · eyebrow + heading hierarchy · count badge aligned opposite.
- Count badge — 30px minimum height · pill shape · mono 12px · tabular numerals.
- Result one-line conclusion — full-width inset strip directly under the decision-brief header · 12px teal mono label · 19px/620 desktop and 18px mobile conclusion · explicitly retains simulated provenance when applicable.
- Skill scope pair — two equal columns on desktop, one column on mobile; common skills left/top, repository skills right/bottom.
- Skill row — native `details`/`summary` · 52px minimum height · 32px provenance glyph · source label · expandable description.
- Empty state — vertically centered, restrained icon, one strong line and one muted explanatory line; preserve the panel's visual weight.
- Artifact reader — native dialog with an 82px toolbar, readable 780px text measure, serif document body, and structured result sheets.
- Mobile navigation — fixed bottom rail with four equal destinations and 44px-class hit targets.

## Responsive and motion rules

- At ≤1050px, collapse the left rail labels while preserving icons and status.
- At ≤700px, use a fixed bottom navigation; stack paired panels and evidence columns; keep full-width primary actions.
- Mobile in-page destinations use a 118px scroll margin so the sticky top bar never obscures section headings.
- Keep interaction motion below 250ms and animate only opacity/transform where possible.
- Respect `prefers-reduced-motion`; retain color and focus feedback without movement.
- Always validate desktop and 390px mobile layouts with a real browser before shipping UI changes.
