# Steep — Style Reference
> serif analytics on warm paper

**Theme:** light

Source measurements are normalized; roles and recommendations are interpreted. Font summary lists are independent, not paired by position. HTML examples are reconstructions, not source components.

Steep renders analytics as editorial — serif Signifier headlines float over a near-monochrome white canvas while a single warm peach accent (#fbe1d1) punctuates an otherwise achromatic system. The page reads like a product magazine spread: oversized italicized display type, generous breathing room, large soft-edged cards at 24px radius, and pill-shaped controls that sit flat against the surface. Components feel quiet and weightless — shadows are barely-there, borders are hairline, and color is rationed to functional emphasis (a peach callout card, a dark brown label on peach). The product surfaces (region tables, activation charts, AI composers) are presented as floating artifacts around the headline, not nested in a dashboard shell.

## Tokens — Colors

| Name | Value | Token | Role |
|------|-------|-------|------|
| Ink Black | `#17191c` | `--color-ink-black` | Primary text, filled button background, nav logo — the only dark surface in the system; every CTA and body headline resolves to this near-black |
| Paper White | `#ffffff` | `--color-paper-white` | Page canvas, button text, elevated card surfaces — the dominant background tone carrying ~76 frequency points |
| Mist Gray | `#f2f2f3` | `--color-mist-gray` | Card surfaces, secondary backgrounds, input fills — the quiet layer beneath paper for nested content |
| Fog White | `#fafafb` | `--color-fog-white` | Secondary page background for alternating sections, hover surfaces — one step above paper for subtle band variation |
| Slate Gray | `#777b86` | `--color-slate-gray` | Link color, muted helper text, footer copy — cool desaturated gray that sits between body text and disabled |
| Ash Gray | `#979799` | `--color-ash-gray` | Tertiary labels, category tags (Marketing, Finance, Sales) — one step lighter than link color |
| Smoke Gray | `#a3a6af` | `--color-smoke-gray` | Placeholder text (Ask anything…), disabled labels — the lightest functional gray, used when text recedes |
| Blush Peach | `#fbe1d1` | `--color-blush-peach` | Accent card background, warm highlight wash — the only chromatic surface in the system; creates editorial warmth against monochrome |
| Sienna Brown | `#5d2a1a` | `--color-sienna-brown` | Text and stroke on peach surfaces, dark accent for chart line strokes — a warm deep brown that pairs with Blush Peach like ink on kraft paper |

## Tokens — Typography

### Signifier — Display and headline serif — used exclusively for H1/H2 at three sizes; weight stays at 400 (regular) at every scale, which is the signature choice: the serif whispers authority rather than shouting in bold · `--font-signifier`
- **Substitute:** GT Sectra, Tiempos Headline, Source Serif 4, or ui-serif/Georgia as fallback
- **Weights:** 400
- **Sizes:** 44px, 64px, 90px
- **Line height:** 1.30
- **Letter spacing:** -2.25px at 90px, -0.96px at 64px, -0.66px at 44px
- **Role:** Display and headline serif — used exclusively for H1/H2 at three sizes; weight stays at 400 (regular) at every scale, which is the signature choice: the serif whispers authority rather than shouting in bold

### Sohne — Body, UI, and navigation sans — the workhorse covering everything from 14px metadata to 26px subheads; the half-step weights (430, 450, 480) create fine-grained hierarchy without jumping to bold · `--font-sohne`
- **Substitute:** Inter, Söhne (Klim Type Foundry), or ui-sans-serif/system-ui stack
- **Weights:** 400, 430, 450, 480, 500
- **Sizes:** 14px, 15px, 16px, 17px, 18px, 20px, 22px, 26px
- **Line height:** 1.00–1.50
- **Letter spacing:** -0.234px at 26px, -0.162px at 18px, 0 at body sizes
- **Role:** Body, UI, and navigation sans — the workhorse covering everything from 14px metadata to 26px subheads; the half-step weights (430, 450, 480) create fine-grained hierarchy without jumping to bold

### Type Scale

| Role | Family | Weight | Size | Line Height | Letter Spacing | Token |
|------|--------|--------|------|-------------|----------------|-------|
| caption | — | — | 15px | 1.5 | — | `--text-caption` |
| body | — | — | 17px | 1.35 | — | `--text-body` |
| body-lg | — | — | 20px | 1.35 | — | `--text-body-lg` |
| subheading | — | — | 22px | 1.5 | — | `--text-subheading` |
| heading-sm | — | — | 26px | 1.18 | -0.23px | `--text-heading-sm` |
| heading | — | — | 44px | 1.3 | -0.66px | `--text-heading` |
| heading-lg | — | — | 64px | 1.3 | -0.96px | `--text-heading-lg` |
| display | — | — | 90px | 1.3 | -2.25px | `--text-display` |

## Tokens — Spacing & Shapes

**Base unit:** 4px

**Density:** comfortable

### Spacing Scale

| Name | Value | Token |
|------|-------|-------|
| 4 | 4px | `--spacing-4` |
| 8 | 8px | `--spacing-8` |
| 12 | 12px | `--spacing-12` |
| 16 | 16px | `--spacing-16` |
| 20 | 20px | `--spacing-20` |
| 24 | 24px | `--spacing-24` |
| 28 | 28px | `--spacing-28` |
| 32 | 32px | `--spacing-32` |
| 40 | 40px | `--spacing-40` |
| 64 | 64px | `--spacing-64` |
| 80 | 80px | `--spacing-80` |
| 96 | 96px | `--spacing-96` |
| 124 | 124px | `--spacing-124` |
| 128 | 128px | `--spacing-128` |
| 160 | 160px | `--spacing-160` |

### Border Radius

| Element | Value |
|---------|-------|
| cards | 24px |
| images | 12px |
| inputs | 16px |
| buttons | 9999px |
| smallCards | 16px |
| elevatedCards | 20px |

### Shadows

| Name | Value | Token |
|------|-------|-------|
| subtle | `oklab(0 0 0 / 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.08) ...` | `--shadow-subtle` |
| subtle-2 | `oklab(0 0 0 / 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1) 0...` | `--shadow-subtle-2` |
| subtle-3 | `rgba(4, 23, 43, 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1)...` | `--shadow-subtle-3` |

### Layout

- **Page max-width:** 1200px
- **Section gap:** 80px
- **Card padding:** 20px
- **Element gap:** 8px

## Components

### Pill Button — Filled
**Role:** Primary call-to-action (Get started, Book a demo)

Background #17191c, text #ffffff, border 1px solid #ffffff (invisible against fill), border-radius 9999px (fully rounded), padding 0 20px, height auto with text. Sohne 16px weight 400. No shadow. The pill shape and dark fill against white is the signature action element — it reads as a solid black lozenge.

### Pill Button — Ghost
**Role:** Secondary action paired with filled primary (Book a demo beside Get started)

Background transparent, text #17191c, border 1px solid #17191c, border-radius 9999px, padding 0 20px. Sohne 16px weight 400. Shares the pill geometry with the filled variant so they read as a matched pair on the same baseline.

### Text Link with Arrow
**Role:** Inline navigation and section transitions (Learn more →, Read the story →)

No background, no border, no border-radius, text #17191c, Sohne 16px weight 400, padding 20px 0. The arrow glyph (→) is part of the label, not a separate icon. This is the lowest-emphasis interactive element — underlines only on hover.

### Nav Link
**Role:** Top navigation items (Product, Resources, Customers, Pricing)

No background or border, text #17191c, Sohne 16px weight 400, padding 2px 0. Sits in a transparent top bar with the logo left and CTAs right. The nav is whisper-quiet — no background, no shadow, no separator.

### Neutral Card
**Role:** Feature blocks, content containers, and base card surface

Background #f2f2f3, border-radius 24px, no shadow, no border, padding varies (0 internally with content children providing their own padding). This is the default workhorse card — flat, soft, and quiet.

### Accent Peach Card
**Role:** Editorial highlight or callout panel (customer quotes, feature spotlights)

Background #fbe1d1, text and strokes #5d2a1a, border-radius 24px, no shadow, no border. The warm-on-warm palette creates a kraft-paper effect — these cards should be rare (one per page maximum) to preserve their impact.

### Floating Product Artifact
**Role:** Hero and section visual elements (region table, activation chart, registration card, AI composer)

Background #ffffff, border-radius 20px, subtle box-shadow: 0 0 0 1px rgba(4,23,43,0.05), 0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1), padding 16px 20px 12px 12px. These are the product UI fragments that float around hero text — they are the only elements with visible shadow, and only at 10% opacity.

### Input / Composer
**Role:** AI question input field (Ask anything…)

Background #ffffff, border 1px solid #ececec or hairline, border-radius 16px, padding 16px, placeholder text #a3a6af in Sohne 16px. Contains left-side @ and ⓘ icons and a right-side dark circular send button (40px diameter, #17191c fill, white arrow icon).

### Stat Card with Chart
**Role:** Data display fragment (Registrations 2.4k, Activation 46.2%)

White floating artifact surface with a bold metric in Sohne 20px weight 500 #17191c, a delta line (↑ 5.5x vs last week) in Sohne 14px #777b86, and a minimal line or radial chart in #5d2a1a stroke. No axes, no gridlines — the chart is a gestural line, not a data dashboard.

### Avatar Bubble
**Role:** User presence indicator on floating cards (JB, AF initials)

Circular, 40px diameter, border-radius 9999px, background tinted (light green for JB, light blue for AF), 2-letter monogram in Sohne weight 500, small directional arrow (cursor pointer) extending from the bubble edge.

### Tag / Category Label
**Role:** Section or content category markers (Marketing, Finance, Sales)

No background, no border, text in Sohne 14px weight 400 #979799. Intentionally ghost-like — these are typographic tags, not badges. They group without visual weight.

## Do's and Don'ts

### Do
- Use Signifier weight 400 at 44/64/90px for all display and heading copy; never substitute a sans-serif at these sizes
- Use the peach #fbe1d1 card surface at most once per page and only for editorial emphasis — treat it as a rare accent, not a background
- Set border-radius to 9999px on all buttons and 24px on all content cards; these are the two structural radii of the system
- Pair every filled pill button (#17191c) with a ghost pill button (#17191c border, transparent fill) as a secondary action on the same row
- Use Sohne half-step weights (430, 450, 480) for body hierarchy before reaching weight 500 — the scale is finer than standard 400/500/700
- Set letter-spacing to -0.025em on 90px display, -0.015em on 64/44px headings, and -0.009em on 26/18px Sohne — tighter tracking at larger sizes is the typographic signature
- Keep the 4px base unit: use 4/8/12/16/20/24px for component padding, and 80px for section gaps

### Don't
- Don't use chromatic colors beyond the peach/brown pair — the system is intentionally 97% achromatic; introducing blue, green, or purple will break the editorial restraint
- Don't use bold (600+) or semibold (500) weights in Signifier — the serif stays at 400 across all sizes, that restraint is the signature
- Don't apply drop shadows to content cards (Neutral Card or Accent Peach Card) — only floating product artifacts earn elevation
- Don't use border-radius below 16px on cards or below 9999px on buttons — sharp corners and moderate radii are not part of this system
- Don't underline inline text links at rest — the arrow suffix (→) carries the link affordance; underlines appear only on hover
- Don't place the peach #fbe1d1 card on a non-white section background — it needs Paper White or Card Mist beneath it to read as warm-on-neutral
- Don't use the #5d2a1a Sienna Brown outside peach surfaces — it's the ink for Blush Peach cards and chart strokes, never body text on white

## Surfaces

| Level | Name | Value | Purpose |
|-------|------|-------|---------|
| 0 | Canvas | `#ffffff` | Default page background; the white paper everything sits on |
| 1 | Card Mist | `#f2f2f3` | Quietly nested content blocks, feature cards, tab panels |
| 2 | Section Fog | `#fafafb` | Alternating section bands that break up the white canvas without contrast |
| 3 | Accent Blush | `#fbe1d1` | Editorial accent cards; the chromatic punctuation of the system |
| 4 | Elevated White | `#ffffff` | Floating product UI artifacts (region tables, activation charts, AI composer) that overlap hero/section content with subtle shadow |

## Elevation

- **Floating Product Artifact:** `0 0 0 1px rgba(4,23,43,0.05), 0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)`
- **Modal / Overlay Card:** `oklab(0 0 0 / 0.05) 0px 0px 0px 1px, rgba(0,0,0,0.1) 0px 8px 40px 0px`
- **Dropdown / Popover:** `oklab(0 0 0 / 0.05) 0px 0px 0px 1px, rgba(0,0,0,0.08) 0px 4px 24px 0px`

## Imagery

Imagery is product-first, not lifestyle: floating UI fragments (region tables with 5-row data, line charts showing activation over Aug–Nov, radial progress rings, AI input composers) are positioned as cropped screenshots around editorial headlines. No photography, no illustration, no abstract graphics. All product visuals sit on white floating-artifact cards with hairline borders and soft 10% shadows. Avatar circles carry a small directional cursor pointer — a visual motif that signals live interaction. The hero composition is a text-and-UI collage, not a centered headline with a stock photo.

## Layout

Page model is max-width 1200px centered, with hero sections going near full-bleed but staying within the container. The hero pattern is a centered oversized serif headline with a subhead and pill button pair, surrounded by four floating product artifact cards (region table top-left, registration card right, activation chart bottom-left, AI composer bottom-center) that overlap the white canvas at varied offsets. Sections alternate between Paper White and Card Mist backgrounds to create quiet rhythm without strong contrast. Feature sections use a 2-column text+UI layout with generous 80px vertical gaps. Navigation is a single transparent top bar (no background, no border, no shadow) with logo left, nav links center, and two CTAs (text link + filled pill) right. The overall density is spacious — the page breathes between sections, and content never crowds the edges.

## Agent Prompt Guide

## Quick Color Reference
- text: #17191c
- background: #ffffff
- border: #ececec
- muted text: #777b86
- accent: #fbe1d1
- primary action: #17191c (filled action)

## Example Component Prompts
1. **Hero headline + accent card collage**: White canvas (#ffffff). Display headline at 90px Signifier weight 400, #17191c, letter-spacing -2.25px, with one italicized phrase mid-sentence. Subhead at 17px Sohne weight 400, #777b86. Below: a filled pill button (background #17191c, text #ffffff, border-radius 9999px, padding 0 20px, Sohne 16px) and a ghost pill button (background transparent, border 1px solid #17191c, text #17191c, border-radius 9999px) side by side. Surround the text with three white floating product artifact cards: a data table card, a line chart card, and a stat card — each with background #ffffff, border-radius 20px, box-shadow 0 0 0 1px rgba(4,23,43,0.05) + 0 20px 25px -5px rgba(0,0,0,0.1), positioned with negative margins to overlap the text margins.

2. **Accent editorial card**: Background #fbe1d1, text #5d2a1a, border-radius 24px, no shadow, padding 40px. Title at 26px Sohne weight 450, #5d2a1a, letter-spacing -0.23px. Body quote at 18px Sohne weight 430, #5d2a1a. Attribution at 14px Sohne weight 400, #5d2a1a. Place this card once on a #ffffff section, never on a colored or dark background.

3. **Neutral feature card**: Background #f2f2f3, border-radius 24px, no shadow, padding 32px 20px. Category label at 14px Sohne weight 400, #979799 (no background, no badge style). Title at 20px Sohne weight 500, #17191c. Body at 16px Sohne weight 400, #17191c, line-height 1.5. Text link below: Sohne 16px weight 400, #17191c, no border-radius, padding 20px 0, with → arrow suffix.

4. **AI composer input**: White background #ffffff, border 1px solid #ececec, border-radius 16px, padding 16px, width 480px. Placeholder text Ask anything… at 16px Sohne weight 400, #a3a6af. Left side: two ghost icon buttons (40px circle, no fill). Right side: 40px circular send button with background #17191c, white arrow icon centered.

5. **Section with alternating background**: Section background #fafafb (Fog White), padding 80px vertical. Section title at 64px Signifier weight 400, #17191c, letter-spacing -0.96px. Subhead at 18px Sohne weight 430, #777b86. Below: 3-column grid of neutral feature cards (#f2f2f3 background, 24px radius, 20px padding, no shadow) with 24px column gap.

## Similar Brands

- **Linear** — Same monochrome dark-text-on-white approach with oversized serif-free type and pill-shaped CTAs; Linear's restraint matches Steep's editorial minimalism
- **Pitch** — Presentation tool that pairs serif display headlines with a warm accent palette and floating UI cards; shares the editorial-product hybrid visual language
- **Arc** — Browser with a soft warm-toned monochrome interface, generous border-radius on cards, and the same whisper-quiet typography approach
- **Framer** — Large serif headlines floating over white with minimal chrome and pill controls; shares the magazine-spread page architecture

## Quick Start

### CSS Custom Properties

```css
:root {
  /* Colors */
  --color-ink-black: #17191c;
  --color-paper-white: #ffffff;
  --color-mist-gray: #f2f2f3;
  --color-fog-white: #fafafb;
  --color-slate-gray: #777b86;
  --color-ash-gray: #979799;
  --color-smoke-gray: #a3a6af;
  --color-blush-peach: #fbe1d1;
  --color-sienna-brown: #5d2a1a;

  /* Typography — Font Families */
  --font-signifier: 'Signifier', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-sohne: 'Sohne', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

  /* Typography — Scale */
  --text-caption: 15px;
  --leading-caption: 1.5;
  --text-body: 17px;
  --leading-body: 1.35;
  --text-body-lg: 20px;
  --leading-body-lg: 1.35;
  --text-subheading: 22px;
  --leading-subheading: 1.5;
  --text-heading-sm: 26px;
  --leading-heading-sm: 1.18;
  --tracking-heading-sm: -0.23px;
  --text-heading: 44px;
  --leading-heading: 1.3;
  --tracking-heading: -0.66px;
  --text-heading-lg: 64px;
  --leading-heading-lg: 1.3;
  --tracking-heading-lg: -0.96px;
  --text-display: 90px;
  --leading-display: 1.3;
  --tracking-display: -2.25px;

  /* Typography — Weights */
  --font-weight-regular: 400;
  --font-weight-w430: 430;
  --font-weight-w450: 450;
  --font-weight-w480: 480;
  --font-weight-medium: 500;

  /* Spacing */
  --spacing-unit: 4px;
  --spacing-4: 4px;
  --spacing-8: 8px;
  --spacing-12: 12px;
  --spacing-16: 16px;
  --spacing-20: 20px;
  --spacing-24: 24px;
  --spacing-28: 28px;
  --spacing-32: 32px;
  --spacing-40: 40px;
  --spacing-64: 64px;
  --spacing-80: 80px;
  --spacing-96: 96px;
  --spacing-124: 124px;
  --spacing-128: 128px;
  --spacing-160: 160px;

  /* Layout */
  --page-max-width: 1200px;
  --section-gap: 80px;
  --card-padding: 20px;
  --element-gap: 8px;

  /* Border Radius */
  --radius-sm: 0.01px;
  --radius-xl: 12px;
  --radius-2xl: 16px;
  --radius-2xl-2: 20px;
  --radius-3xl: 24px;

  /* Named Radii */
  --radius-cards: 24px;
  --radius-images: 12px;
  --radius-inputs: 16px;
  --radius-buttons: 9999px;
  --radius-smallcards: 16px;
  --radius-elevatedcards: 20px;

  /* Shadows */
  --shadow-subtle: oklab(0 0 0 / 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.08) 0px 4px 24px 0px;
  --shadow-subtle-2: oklab(0 0 0 / 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1) 0px 8px 40px 0px;
  --shadow-subtle-3: rgba(4, 23, 43, 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1) 0px 20px 25px -5px, rgba(0, 0, 0, 0.1) 0px 8px 10px -6px;

  /* Surfaces */
  --surface-canvas: #ffffff;
  --surface-card-mist: #f2f2f3;
  --surface-section-fog: #fafafb;
  --surface-accent-blush: #fbe1d1;
  --surface-elevated-white: #ffffff;
}
```

### Tailwind v4

```css
@theme {
  /* Colors */
  --color-ink-black: #17191c;
  --color-paper-white: #ffffff;
  --color-mist-gray: #f2f2f3;
  --color-fog-white: #fafafb;
  --color-slate-gray: #777b86;
  --color-ash-gray: #979799;
  --color-smoke-gray: #a3a6af;
  --color-blush-peach: #fbe1d1;
  --color-sienna-brown: #5d2a1a;

  /* Typography */
  --font-signifier: 'Signifier', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-sohne: 'Sohne', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;

  /* Typography — Scale */
  --text-caption: 15px;
  --leading-caption: 1.5;
  --text-body: 17px;
  --leading-body: 1.35;
  --text-body-lg: 20px;
  --leading-body-lg: 1.35;
  --text-subheading: 22px;
  --leading-subheading: 1.5;
  --text-heading-sm: 26px;
  --leading-heading-sm: 1.18;
  --tracking-heading-sm: -0.23px;
  --text-heading: 44px;
  --leading-heading: 1.3;
  --tracking-heading: -0.66px;
  --text-heading-lg: 64px;
  --leading-heading-lg: 1.3;
  --tracking-heading-lg: -0.96px;
  --text-display: 90px;
  --leading-display: 1.3;
  --tracking-display: -2.25px;

  /* Spacing */
  --spacing-4: 4px;
  --spacing-8: 8px;
  --spacing-12: 12px;
  --spacing-16: 16px;
  --spacing-20: 20px;
  --spacing-24: 24px;
  --spacing-28: 28px;
  --spacing-32: 32px;
  --spacing-40: 40px;
  --spacing-64: 64px;
  --spacing-80: 80px;
  --spacing-96: 96px;
  --spacing-124: 124px;
  --spacing-128: 128px;
  --spacing-160: 160px;

  /* Border Radius */
  --radius-sm: 0.01px;
  --radius-xl: 12px;
  --radius-2xl: 16px;
  --radius-2xl-2: 20px;
  --radius-3xl: 24px;

  /* Shadows */
  --shadow-subtle: oklab(0 0 0 / 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.08) 0px 4px 24px 0px;
  --shadow-subtle-2: oklab(0 0 0 / 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1) 0px 8px 40px 0px;
  --shadow-subtle-3: rgba(4, 23, 43, 0.05) 0px 0px 0px 1px, rgba(0, 0, 0, 0.1) 0px 20px 25px -5px, rgba(0, 0, 0, 0.1) 0px 8px 10px -6px;
}
```

## Atlas additions

How ExFuzzy Atlas (`apps/web`) applies Steep, and what a data app needs that a landing page does not. The tokens live
on `:root` in `apps/web/src/styles.css`; the data colours in `apps/web/src/lib/territories.ts` and `lib/ruleColours.ts`.
Added 2026-11-09.

### Fonts

- **Source Serif 4** (variable, with optical sizes; roman and italic) stands in for Signifier, always at weight 400.
  **Inter** (variable) stands in for Söhne, so the half-step weights 430 / 450 / 480 exist. Both are SIL OFL 1.1 and
  self-hosted from npm (`@fontsource-variable/source-serif-4`, `@fontsource-variable/inter`, imported in
  `apps/web/src/main.tsx`): no font CDN, the demo works offline.
- Serif scale for an app: 44 px hero headline (32 px on phones), 32 px page title (H1), 26 px section title (H2 of a
  card), ~20 px headings of the side panels (H2). The 64 and 90 px sizes are used only on the landing page (see Landing
  page). The serif stays on H1/H2; H3 and below are Inter 500 (a side card's title is Inter 20 px 500).
- Inter: body 16 px at 430, controls 450, labels 480, emphasis and figures 500. Nothing at 600 or more.
- The hero's key figure is the "one italicized phrase": `HeroAccent` sets it in the italic serif, in terracotta (see
  Colour in titles).

### Text-safe greys

| Token | Value | Use |
|---|---|---|
| `--muted` | `#666a75` | Slate darkened for text: 5.4:1 on Paper, 4.8:1 on Mist. Every subhead, helper text, label and axis text. |

Slate `#777b86` measures 4.2:1 on white, Ash `#979799` 2.9:1 and Smoke `#a3a6af` 2.4:1: all three fail 4.5:1 for normal
text, so in Atlas they only draw non-text (axis lines, glyph outlines, dashed "not used" tiles). On Peach, text is
Sienna (9.3:1), never a grey.

### Surfaces and elevation in the app

- Canvas Paper; every card is a **Neutral Card** (Mist, 24 px, no border, no shadow). Content nested in a Mist card sits
  on white small cards (16 px, no shadow): rule cards, matrix rows, side panels, legends, tables.
- The big map frames of Predicción and Explorar are one Neutral Card holding the map (16 px, hairline ring), the white
  side panels and the white timeline.
- **Floating Product Artifact** elevation is used only by the hero's KPI tiles and the landing page's artifacts. The **Dropdown / Popover** elevation is
  used by the rule hovercards, the map tooltip and the attribution popover. Nothing else has a shadow.
- **Accent Peach Card**: at most one per page; the app uses exactly one, «Qué hacen estas reglas» on Patrones (the
  AI-written description of the rule base). It is the only prose in the app written in a voice, so it reads as a quote:
  Sienna on Peach, its title in the serif, and the "written by Claude (AI)" note as its attribution line. The verdict
  sentence of the performance report stays the hero's Slate subhead, next to the figures it summarises.
- Warnings that are not errors (an artificial what-if scenario, a merged class) are said in words on Mist, with an ink
  rule or an ink-outlined pill: no amber. Errors keep a red (`--error: #b42318`, 6.6:1), the one status colour.

### Controls

- Buttons are pills: ghost (1 px Ink border) by default, filled Ink when primary or pressed. Small utility buttons (the
  timeline's steps) use a hairline border instead of Ink, so a row of them stays quiet.
- Segmented controls (territories, horizon, ES | EN, colour modes, metric) sit on a Mist pill; the pressed segment is
  filled Ink with white text. Section tabs are pills too, the selected one filled Ink.
- Text links are Ink at weight 500 (body text is 430), underlined only on hover and focus. A link that takes the reader
  to another tab ends in → (generated by CSS, hidden from screen readers). The helper text around a link is `--muted`,
  so the link differs from it by more than 3:1 as well as by weight (WCAG 1.4.1).
- Focus: a 2 px Ink outline, 2 px offset (Sienna inside the Peach card). `prefers-reduced-motion` turns off every
  transition and the hovercard's entrance.
- The header is transparent, without border or shadow. Each territory's domain («Calidad del aire») is a tag above its
  pill on desktop, beside it on phones.

### Layout

- The app shell is fluid (2026-11-09, the user's request: "use the whole screen"): header and pages take the full width
  up to `--shell-max: 1680px`, with `--gutter: clamp(16px, 2.4vw, 40px)` at the sides. Maps, the rule matrix and the
  report use the extra width; reading text keeps its measure (leads and subheads ≤ 72ch, the hero verdict 60ch, the KPI
  row ≤ 64rem). At 390 px the gutter is 16 px and nothing scrolls sideways.
- Section gaps are 40 px (32 px on phones). 80 px is a landing page's rhythm (the landing page uses it) and leaves a
  data page half empty.
- On Patrones the rule matrix shares the 1200 px with the map (side panel 20–21.5 rem), so its term glyphs are drawn at
  60 px (52 px with six variables) and the arrow before «Entonces» is left out.
- Predicción and Explorar split map and side panel 1.6 : 1.

### Territory washes

The app root carries `data-domain` (`air`, `water`, `mobility`, from the active territory's domain). It drives one token,
`--territory-wash`, a tint that appears only at the edges of the page (the user's request, 2026-11-10: "a slightly
different background depending on the example", then "subtler, mostly at the edges"). The centre, where the content sits,
stays Paper; Mist, the cards and every other token are unchanged. No dark mode exists, so none was added.

| Domain | Tint | `--territory-wash` |
|---|---|---|
| none yet | none | `#ffffff` |
| air, option (a), the default | lavender, a sky or haze | `#c4b7f0` |
| air, option (b) | pale sage | `#b0d4a6` |
| water | clear water blue | `#7fcbf6` |
| mobility (taxis) | taxi yellow | `#f8c81c` |

The hues are thematic (the user, 2026-11-10): blue is water's, yellow the taxis', and air takes a colour that is neither
of those nor an EAQI category colour on its map (so not a blue, a yellow or a green-teal): lavender (a) reads as sky or
haze; sage (b) is the alternative. Air's token is `--wash-air` in `styles.css`, set to `--wash-air-a` and switched to
`--wash-air-b` by changing that one line.

It is drawn on a fixed layer behind the content (`.app::before`, no image): a left and right linear gradient that peaks at
24 % of the tint on the edge and falls off smoothly over 25 % of the width (twelve eased stops, so it does not band), plus
a lower corner glow at 8 %, so the total never passes 30 %. At 640 px and below the same layer is drawn at half its
opacity (15 % at most). The property is registered with `@property` as a colour, so changing territory fades it in 0.6 s;
`prefers-reduced-motion` turns the transition off. The landing's territory cards echo it as the tile behind each map
(`--lp-tile`: `#f8f6fd` for air (a), `#f0f9fe`, `#fef9e5`).

Contrast (WCAG) at the strongest pixel of the layer (30 % of the tint, where no text sits but which bounds every other
place), air (a) / air (b) / water / mobility: Ink 14.8:1 or more; `--muted` `#666a75` 4.5:1 / 4.7:1 / 4.6:1 / 4.7:1 (4.7:1
or more at the edge alone, 4.9:1 or more on the phone); terracotta `#a05339` 4.65:1 or more; Sienna 9.7:1 or more. The
dataviz validator on those composites (`#ede9fa`, `#e7f2e4`, `#d9effc`, `#fdeebb`, `--mode light --pairs all`), for the
five rule colours and for the diverging pair `#a05339` / `#3a6fa3`: all checks pass (CVD ΔE 11.9 and 16.1, normal-vision
ΔE 17.8 and 20.2, unchanged by the surface). The only WARN is the orange `#eb6834` against the surface, 2.7:1 to 2.8:1
(2.9:1 on Paper), the same relief as before (dark rim on the map, every legend and table names the rule).

### Colour in titles (a deliberate deviation)

Steep is near-achromatic; the user asked for "a little bit more colour in the titles" (2026-11-09). One restrained step,
in the warm pair Steep already has, never on body text:

| Where | Colour | Contrast |
|---|---|---|
| The hero's italic figure (`HeroAccent`, 44 px; 32 px on phones) and the landing headline's italic phrase | terracotta `#a05339` (`--terracotta`, the sienna arm's step 3) | 5.5:1 on Paper, 4.9:1 on Mist; 4.0:1 at the landing wash's strongest point, where it is ≥ 44 px (large text needs 3:1) |
| Eyebrows (the hero's "Alemania · +1 h · 2025", the landing's section eyebrows) | Sienna `#5d2a1a`, weight 480 | 11.6:1 on Paper, ≥ 9.6:1 on the app wash |
| Section titles (the serif H2 of a Neutral Card: «Las reglas de un vistazo», report and summary cards) | the title stays Ink; a 28 × 3 px terracotta rule sits above it | 4.9:1 on Mist (non-text, needs 3:1) |

Page titles (H1), side-card titles (H3), the Peach card's title and all body text stay Ink. Sienna is still never body
text on white: on Paper it appears only at eyebrow size and weight.

### Term phrases

A linguistic term is never shown bare («alta», «Medio>L»): `lib/termPhrases.ts` turns it into a complete phrase with
the variable's noun, agreeing in gender in Spanish («demanda alta», «humedad media», «viento alto», «pH bajo») and in
English order ("high demand"). Terms that already say everything stay as published: EAQI classes («Buena»), named
periods («Mediodía», «Domingo», «Invierno»), Beaufort names («Brisa ligera»). Water's detection-limit terms say L in
words: `<=L` «en el límite de detección o por debajo», `Medio>L` «medio, sobre el límite de detección».

- On its own (rule matrix cells, the hovercard's terms, the partitions table, outcome pills) the term is the whole phrase
  in italics: *demanda alta*.
- In a rule sentence the variable is named once, with its article, and the term agrees with it: «Si la **demanda hace
  1 h** es *alta* → *demanda alta*», «Si el **NO₂ hace 1 h (último dato)** es *Buena*». The variable stays bold and the
  term italic (the alternative, the whole condition in italics, reads as one grey block and loses the variable/term
  contrast). A trailing unit in parentheses is left out of the sentence; NYC's «Nivel hace N h» is said «la demanda hace
  N h», since its classes are levels of demand.
- Inside a plot titled by its variable (the terms plots), the curve labels stay short, in italics.

### Data colours

"Don't use chromatic colours beyond peach/brown" governs the interface chrome. Data keeps its own encodings, chosen by
the job they do (the dataviz method: identity, magnitude, polarity), and is validated with the dataviz validator.

**Rule identity** (maps of Patrones and Predicción, legends, rule chips): five colours for the rules that decide most,
one grey for the others. No red, green, yellow or cyan, so a rule never reads as a class.

| Slot | Hex | |
|---|---|---|
| 1 | `#2a78d6` | blue |
| 2 | `#eb6834` | orange |
| 3 | `#6b2fa5` | violet |
| 4 | `#b84888` | magenta |
| 5 | `#7f4413` | brown |
| other rules | `#a7b0bd` | grey |

On a map any two can touch, so they are checked all-pairs (`--pairs all`) on the basemap's land `#f2f3f0`, on Paper and
on Mist: worst colour-blind ΔE 11.9 (magenta ↔ violet, protan), worst normal-vision ΔE 17.8, all inside the lightness
band, all above the chroma floor. The grey adds no worse pair. The orange is 2.9:1 on the land and on Mist (relief: map
points keep their dark rim, every legend and table names the rule). This retune replaced the violet `#7a4fc4`, pink
`#e87ba4` and gold `#b07a00`, which failed all-pairs (gold ↔ orange ΔE 2.0 protan / 11.8 normal; violet ↔ blue 3.9 /
12.7).

**Class colours** (EAQI, ICA, NYC levels) are the official schemes' and stay as published.

**Single series and charts**

| Role | Value |
|---|---|
| A single series of marks (bars, variable bars, share rings, term glyphs) | Sienna `#5d2a1a` (term glyph fill `#a05339`) |
| Observed, next to a prediction | Ink `#17191c`, solid |
| Predicted | `#a05339`, dashed |
| Performance report | ExFuzzy Sienna `#5d2a1a`; baselines `#b8bbc2` with their value printed on each column; reference line Sienna, dashed |
| Gridline / track | `#e2e2e5` / `#e4e5e8` |

Marks are thin (columns at most 24 px; the report's columns and the horizontal bars end in a 4 px round), one axis per chart, a legend when there are two series or
more, values in text colours (never in the series colour).

### Diverging pair (contract v0.7 rule mixtures)

For bars of support (+) and suppression (−) per rule and class: a Sienna arm against a cool slate-blue arm, with a
neutral grey midpoint and equal lightness at equal steps (OKLCH L 0.90 / 0.73 / 0.53 / 0.35).

| Step | Support (+) | Suppression (−) |
|---|---|---|
| 1 | `#f5d7c8` | `#d2e0ee` |
| 2 | `#d3987f` | `#8babcd` |
| 3 — bar fill | `#a05339` | `#3a6fa3` |
| 4 | `#5d2a1a` (Sienna) | `#1a3c61` |
| midpoint | `#e7e8ea` | |

CSS tokens `--div-pos-1…4`, `--div-neg-1…4`, `--div-mid`. Validated: the two bar fills pass every categorical check on
Paper and Mist (colour-blind ΔE 16.1, normal-vision ΔE 20.2, 5.5:1 and 5.3:1 on white); steps 2–4 of each arm pass the
ordinal checks (monotone lightness, ΔL ≥ 0.06, one hue, light end ≥ 2:1). The bar fills sit about ΔE 8 from rule blue and
rule brown, so a mixture view names each rule by its id and sentence, not by its rule colour.

### Landing page

The bare URL opens a landing page (`components/Landing.tsx`, outside `App`): Steep's own hero, full screen.

- **Wash.** A full-bleed warm wash behind the hero: layered CSS radial gradients of peach `rgb(251 214 194)`, pink
  `rgb(246 205 221)` and lilac `rgb(220 212 243)` on `#fbfafa`, a coral core, an inline SVG `feTurbulence` grain at 7 %
  and a fade to Paper at the bottom. It drifts over 28 s; `prefers-reduced-motion` stops it. Nothing is fetched. The
  app's tabs carry a faint copy (the same three colours at 24–42 %, centred above the viewport) at the top of the page,
  behind the header and hero; `--muted` text keeps ≥ 4.5:1 even where two peaks overlap, 4.7:1 on the peach alone.
- **Type.** One h1: the serif at `clamp(44px, 6.2vw, 108px)`, weight 400, line-height 1.02, tracking −0.025em, its second
  line the italic phrase in terracotta. Subhead Inter 17–21 px in Ink (Slate fails 4.5:1 on the wash). The pill pair:
  «Empezar la demo» filled Ink and «Ver cómo funciona» ghost, 1.05 rem.
- **Floating artifacts.** Four white Floating Product Artifacts drawn by the app's own components from the API's data for
  the task the demo opens on: the performance report (big figure, columns, the table of models), the rule that decides
  most (its sentence, a term glyph and a ring of the share it decides), the stations coloured by the rule that decides
  most there, and one row of the rule matrix. The first two sit inside the landing's side gutter, no longer cropped by the viewport's edges (2026-11-10). They are
  `aria-hidden` (the page's text says everything) and absent when the API does not answer: no number is made up.
  Under 1100 px they line up below the actions, under 640 px in one column without the map.
- **Navy.** Steep's navy `#1d4e89` (`--navy`) is the landing's colour for figures and the baselines' bars, next to
  Sienna for ExFuzzy, rings and accents (8.4:1 on Paper, 7.6:1 on the rule card). Validated as a pair with the dataviz
  validator: colour-blind ΔE 17.5 (deutan), normal-vision ΔE 19.5, both ≥ 3:1; both sit below the categorical lightness
  band (they are dark), so the table beside the columns names every bar. Navy is not used inside the app.
- **Peach.** The rule card is the landing's one peach card, a lighter tint `#fdf1ea` so the sentence's Slate-text words
  keep 4.9:1 (on Blush `#fbe1d1` they would be 4.3:1).
- **Rhythm.** Below the hero, sections at 80 px gaps: how it works (what a fuzzy rule is), the three territories (Mist
  cards, each with a small static map of its published geometry on a white 12 px tile: points or zone outlines in Ink,
  no basemap; `npm run gen:landing-maps`), and a closing «Empezar la demo».
- **Gutter.** `--lp-gutter: clamp(20px, 5vw, 80px)` on every landing block (top bar, hero, sections, footer, floating
  artifacts): 20 px at 390 px, 72 px at 1440 px. The app's own `--gutter` (16–40 px) is unchanged.

### Conditions on a rule (contract v0.8, 2026-11-10)

- **Sentences.** «al menos» / «como mucho» (at least / at most) sit between the verb and the term in running text; a compound
  term is its display name in the same italic phrase as a term («es Noche larga»), with its constituents and, for an hour of
  the day, its hours («Tarde-noche o Noche, 17–5 h») in the tooltip or the rule detail. In the rule matrix and in compact
  lists they shrink to ≥ and ≤ before the term.
- **Partitions.** The shape of an ordinal or compound condition that a rule uses is the bounded sum of its terms' trapezoids,
  drawn as a dashed Ink line (2.4 px, 7/4) over the base terms and labelled in italic Ink. It is a drawing of the published
  parameters; a variable with no such condition looks as before.

### Not followed

- Signifier and Söhne themselves (commercial): the substitutes above.
- 64 / 90 px display sizes and 80 px section gaps inside the app (the landing page uses them; see Layout).
- Slate as text colour (see Text-safe greys).
- Avatar bubbles, the AI composer and the alternating Fog sections: Atlas has no such content.
