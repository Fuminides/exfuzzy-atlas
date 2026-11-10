import { createContext, useContext, useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type ButtonHTMLAttributes, type CSSProperties, type MouseEvent, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";
import type { LinguisticVariable, ModelRules, RuleDefinition, RuleImportanceResponse, TargetScheme } from "../api/types";
import { tr } from "../i18n";
import { importancePeriod, rankedRules } from "../lib/importance";
import { ruleSentence, useFeatureLabel, useNames } from "../lib/labels";
import { colourOf, ruleColours } from "../lib/ruleColours";
import { ruleFigures } from "../lib/ruleFigures";
import { placeCard } from "../lib/ruleRefs";
import { OutcomePill } from "./OutcomePill";
import { ClassWeights } from "./ClassWeights";
import { weightScale } from "../lib/mixture";
import { RuleSentenceView } from "./RuleSentenceView";
import { ACCENT, columnRange, TermGlyph } from "./TermGlyph";

/** What any component needs to show a rule from its id alone: the model's rules, names, scheme, figures and colours. */
export interface RuleLookup {
  byId: ReadonlyMap<string, RuleDefinition>;
  variables: readonly LinguisticVariable[];
  scheme: TargetScheme | null;
  /** null while the importance is not loaded or not published. */
  importance: RuleImportanceResponse | null;
  /** The rule colours of the ranking (the map's); null when a view has none. */
  colours: ReadonlyMap<string, string> | null;
  weighting: ModelRules["inference"]["rule_weighting"] | undefined;
  unit: string;
  /** v0.7 rule mixture: the model's largest |centred weight| (the weight bars' common scale); 0 for other families. */
  weightScale: number;
}

const RuleLookupContext = createContext<RuleLookup | null>(null);
/** True inside a hovercard: a rule id there is plain text (no card inside a card). */
const InsideCard = createContext(false);

export const useRuleLookup = (): RuleLookup | null => useContext(RuleLookupContext);

interface ProviderProps {
  model: ModelRules;
  importance: RuleImportanceResponse | null;
  scheme: TargetScheme | null;
  unit: string;
  /** Colour the rules in the model's order when there is no ranking (as Predicción does while it is not published). */
  colourWithoutRanking?: boolean;
  children: ReactNode;
}

/** Provided where a model's rules (and, when published, its importance) are loaded, so `<RuleRef id="R10" />` works below. */
export function RuleLookupProvider({ model, importance, scheme, unit, colourWithoutRanking = false, children }: ProviderProps) {
  const value = useMemo<RuleLookup>(
    () => ({
      byId: new Map(model.rules.map((r) => [r.rule_id, r])),
      variables: model.variables,
      scheme,
      importance,
      colours: importance ? ruleColours(rankedRules(importance.rules).map((r) => r.rule_id)) : colourWithoutRanking ? ruleColours(model.rules.map((r) => r.rule_id)) : null,
      weighting: model.inference.rule_weighting,
      unit,
      weightScale: weightScale(model.rules),
    }),
    [model, importance, scheme, unit, colourWithoutRanking],
  );
  return <RuleLookupContext.Provider value={value}>{children}</RuleLookupContext.Provider>;
}

/** Hover this long before the card opens (a pointer passing over an id should not flash a card). */
export const HOVER_DELAY = 250;
/** Leaving the trigger closes after this, so the pointer can move into the card. */
const LEAVE_DELAY = 150;
/** Mouse events this soon after a touch are the browser's emulation of the tap: ignored. */
const TOUCH_WINDOW = 800;

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { [data: `data-${string}`]: string | undefined };

interface RuleRefProps {
  id: string;
  /** The trigger's own action (pick the rule on the map, open it in Patrones). Without one, a click or tap pins the card. */
  onClick?: (e: MouseEvent<HTMLButtonElement>) => void;
  /** Replaces the default chip's class (a legend button, a badge). */
  className?: string;
  /** Replaces the default content (swatch + id). */
  children?: ReactNode;
  /** More attributes for the button: aria-pressed, aria-label, data-*, focus and key handlers (they are chained). */
  buttonProps?: ButtonProps;
  /** What a click does, written at the foot of the card ("Ver la regla en Patrones"). */
  hint?: string;
}

/**
 * An inline rule id that shows the rule on a floating card, as card sites preview a card from its name: on hover (after
 * a short delay), on keyboard focus and on tap. Escape closes it. The trigger is a real button with `aria-describedby`
 * pointing at the card (role="tooltip"); without an action of its own it is a disclosure (`aria-expanded`). An id the
 * model does not have, or a page with no rule lookup, renders as plain text (or the plain button when it has an action).
 */
export function RuleRef({ id, onClick, className, children, buttonProps, hint }: RuleRefProps) {
  const lookup = useRuleLookup();
  const inside = useContext(InsideCard);
  const rule = lookup?.byId.get(id);
  const colour = lookup?.colours ? colourOf(lookup.colours, id) : null;
  const chipClass = className ?? `rule-ref${colour ? "" : " rule-ref--plain"}`;
  const style = !className && colour ? ({ "--rule-colour": colour } as CSSProperties) : undefined;
  const content = children ?? (
    <>
      {!className && colour && <span className="rule-ref-swatch" aria-hidden="true" />}
      {id}
    </>
  );
  if (!lookup || !rule || inside) {
    if (onClick || buttonProps)
      return (
        <button type="button" className={chipClass} style={style} onClick={onClick} {...buttonProps}>
          {content}
        </button>
      );
    return <span className="rule-ref-text">{children ?? id}</span>;
  }
  return (
    <LiveRuleRef id={id} rule={rule} lookup={lookup} colour={colour} onClick={onClick} className={chipClass} style={style} buttonProps={buttonProps} hint={hint}>
      {content}
    </LiveRuleRef>
  );
}

function LiveRuleRef({ id, rule, lookup, colour, onClick, className, style, buttonProps, hint, children }: { id: string; rule: RuleDefinition; lookup: RuleLookup; colour: string | null; onClick?: (e: MouseEvent<HTMLButtonElement>) => void; className: string; style?: CSSProperties; buttonProps?: ButtonProps; hint?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const lastTouch = useRef(0);
  const pointerFocus = useRef(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const cardId = useId();
  const clear = () => window.clearTimeout(timer.current);
  const close = () => {
    clear();
    setOpen(false);
    setPinned(false);
  };
  const later = (fn: () => void, ms: number) => {
    clear();
    timer.current = window.setTimeout(fn, ms);
  };
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => {
    if (!open) return;
    const shut = () => {
      window.clearTimeout(timer.current);
      setOpen(false);
      setPinned(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && shut();
    const onDown = (e: Event) => {
      const t = e.target as Node;
      if (!trigger.current?.contains(t) && !card.current?.contains(t)) shut();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("touchstart", onDown);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("touchstart", onDown);
    };
  }, [open]);

  const touched = () => Date.now() - lastTouch.current < TOUCH_WINDOW;
  const { onFocus, onBlur, onKeyDown, ...rest } = buttonProps ?? {};
  return (
    <>
      <button
        type="button"
        ref={trigger}
        className={className}
        style={style}
        aria-expanded={onClick ? undefined : open}
        aria-describedby={open ? cardId : undefined}
        data-rule-ref={id}
        {...rest}
        onMouseEnter={() => !touched() && later(() => setOpen(true), HOVER_DELAY)}
        onMouseLeave={() => !pinned && later(() => setOpen(false), LEAVE_DELAY)}
        onTouchStart={() => {
          lastTouch.current = Date.now();
          pointerFocus.current = true;
        }}
        onMouseDown={() => {
          pointerFocus.current = true;
        }}
        onFocus={(e) => {
          onFocus?.(e);
          // a click or tap focuses the button too: only the keyboard opens the card on focus
          if (pointerFocus.current) pointerFocus.current = false;
          else {
            clear();
            setOpen(true);
          }
        }}
        onBlur={(e) => {
          onBlur?.(e);
          if (!pinned) close();
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape" && open) {
            e.stopPropagation(); // the card closes, not the panel around the id
            close();
          }
          onKeyDown?.(e);
        }}
        onClick={(e) => {
          const tap = touched();
          onClick?.(e);
          if (onClick && !tap) return;
          if (pinned) close();
          else {
            clear();
            setPinned(true);
            setOpen(true);
          }
        }}
      >
        {children}
      </button>
      {open && (
        <RuleHovercard
          id={id}
          cardId={cardId}
          rule={rule}
          lookup={lookup}
          colour={colour}
          hint={hint}
          anchor={trigger}
          cardRef={card}
          onEnter={clear}
          onLeave={() => !pinned && later(() => setOpen(false), LEAVE_DELAY)}
        />
      )}
    </>
  );
}

interface CardProps {
  id: string;
  cardId: string;
  rule: RuleDefinition;
  lookup: RuleLookup;
  colour: string | null;
  hint?: string;
  anchor: RefObject<HTMLButtonElement | null>;
  cardRef: RefObject<HTMLDivElement | null>;
  onEnter: () => void;
  onLeave: () => void;
}

/** The floating card: id and colour, the rule's sentence, what it asks of each variable, its outcome and published figures. */
function RuleHovercard({ id, cardId, rule, lookup, colour, hint, anchor, cardRef, onEnter, onLeave }: CardProps) {
  const label = useFeatureLabel();
  const names = useNames();
  const [pos, setPos] = useState<{ top: number; left: number; side: "below" | "above" } | null>(null);
  useLayoutEffect(() => {
    const place = () => {
      const a = anchor.current?.getBoundingClientRect();
      const c = cardRef.current?.getBoundingClientRect();
      if (!a || !c) return;
      setPos(placeCard(a, { width: c.width, height: c.height }, { width: document.documentElement.clientWidth || window.innerWidth, height: window.innerHeight }));
    };
    place();
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
    };
  }, [anchor, cardRef]);
  const sentence = ruleSentence(rule, label, lookup.scheme, names);
  const variables = new Map(lookup.variables.map((v) => [v.feature, v]));
  const figures = ruleFigures({ rule, importance: lookup.importance, weighting: lookup.weighting, unit: lookup.unit });
  return createPortal(
    <InsideCard.Provider value={true}>
      <div
        ref={cardRef}
        id={cardId}
        role="tooltip"
        className="rule-hovercard"
        data-testid="rule-hovercard"
        data-rule={id}
        data-side={pos?.side ?? "below"}
        style={{ top: pos?.top ?? 0, left: pos?.left ?? 0, visibility: pos ? "visible" : "hidden", ...(colour ? ({ "--rule-colour": colour } as CSSProperties) : {}) }}
        onMouseEnter={onEnter}
        onMouseLeave={onLeave}
      >
        <header className="rhc-head">
          <span className="rhc-id">
            {colour && <span className="rule-ref-swatch" aria-hidden="true" />}
            {tr(`Regla ${id}`, `Rule ${id}`)}
          </span>
          <span className="rhc-out">
            {sentence.outcome.kind !== "mixture" && <span className="rmx-arrow" aria-hidden="true">→</span>}
            <OutcomePill outcome={sentence.outcome} />
          </span>
        </header>
        <RuleSentenceView sentence={sentence} testId="rule-hovercard-sentence" />
        {rule.class_weights_centred && lookup.scheme && (
          <ClassWeights
            values={rule.class_weights_centred}
            scheme={lookup.scheme}
            scale={lookup.weightScale}
            strongest={rule.strongest_class ?? null}
            label={tr(`Pesos centrados de ${id} por categoría: positivo, apoyo; negativo, supresión`, `Centred weights of ${id} by category: positive, support; negative, suppression`)}
            testId="rule-hovercard-weights"
          />
        )}
        <ul className="rhc-terms" aria-hidden="true">
          {rule.antecedents.map((a) => {
            const v = variables.get(a.feature);
            const range = columnRange(v);
            const part = sentence.parts.find((p) => p.feature === a.feature && p.term === a.term);
            return (
              <li key={`${a.feature}|${a.term}`} className="rhc-term">
                <span className="rhc-var">{label(a.feature)}</span>
                {v && range && <TermGlyph variable={v} term={a.term} range={range} fill={part?.color ?? ACCENT} />}
                <span className="rmx-term">
                  <em className="term-phrase">{names.phrase(a.feature, a.term)}</em>
                </span>
              </li>
            );
          })}
        </ul>
        {figures.length > 0 && (
          <dl className="rhc-figures" data-testid="rule-hovercard-figures">
            {figures.map((f) => (
              <div key={f.key} data-figure={f.key} title={f.title}>
                <dt>{f.label}</dt>
                <dd>{f.value}</dd>
              </div>
            ))}
          </dl>
        )}
        {lookup.importance ? (
          <p className="rhc-note">{tr(`Periodo publicado: ${importancePeriod(lookup.importance)}.`, `Published period: ${importancePeriod(lookup.importance)}.`)}</p>
        ) : (
          <p className="rhc-note">{rule.class_weights_centred ? tr("Todavía no hay cifras de esta regla.", "There are no figures yet for this rule.") : tr("Todavía no hay cifras de lo que decide esta regla.", "There are no figures yet for what this rule decides.")}</p>
        )}
        {hint && <p className="rhc-hint">{hint}</p>}
      </div>
    </InsideCard.Provider>,
    document.body,
  );
}
