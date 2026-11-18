/**
 * Creative primitives for the Omnicult redesign. Direction and "what to use where": omnicult-docs/redesign/CREATIVE_DIRECTION.md.
 * CSS they rely on (tokens, .bento, .reveal, .stagger, .tilt, .stamp-in, .dough, .tab-ink, tint-* roles) lives in
 * app/globals.css.
 */
export { AmbientBackground, ambientVariantFor, type AmbientVariant } from "./ambient-background";
export { ApiImage } from "./api-image";
export { ChipToggleGroup, TabInk, type ChipOption } from "./chip-toggle-group";
export { CompareSlider } from "./compare-slider";
export { CountUp } from "./count-up";
export { EmptyIllustration, type EmptyKind } from "./empty-illustration";
export { FilmStrip, type FilmFrame } from "./film-strip";
export { INDIA_TILES, IndiaTileMap, type TileDatum, type TileTone } from "./india-tile-map";
export { LazyMount } from "./lazy-mount";
export { roleColor, roleTint, useFinePointer, useReducedMotion, type RoleKey } from "./motion";
export { PersonaAvatar, ReactionBubble, type Mood } from "./persona-avatar";
export { Reveal, Stagger } from "./reveal";
export { RoleMark } from "./role-mark";
export { RingGauge } from "./ring-gauge";
export { MiniArea, Sparkline } from "./sparkline";
export { Swatch, contrastGrade, contrastRatio } from "./swatch";
export { TiltCard } from "./tilt-card";
export { TimelineRibbon, type RibbonItem } from "./timeline-ribbon";
export { VerdictStamp } from "./verdict-stamp";
