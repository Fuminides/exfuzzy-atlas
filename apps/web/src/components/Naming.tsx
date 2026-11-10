import { useMemo } from "react";
import type { LinguisticVariable, RuleDefinition, TargetScheme } from "../api/types";
import { useLang } from "../i18n";
import { LabelContext, labelerFor, NamesContext, namesFor } from "../lib/labels";

/**
 * Provides how a model's inputs, terms and classes are called on screen (published names first, readable fallbacks).
 * `target` (the task's target, e.g. `pickups`) completes the class names of a relative level («demanda alta»); `rules` give
 * the display names of the compound conditions (v0.8), which a rule trace does not carry.
 */
export function Naming({ variables, scheme, target, rules, children }: { variables: readonly LinguisticVariable[]; scheme: TargetScheme | null; target?: string | null; rules?: readonly RuleDefinition[]; children: React.ReactNode }) {
  // the language is a dependency so that a new language gives new functions and memoised readers render again
  const { lang } = useLang();
  const label = useMemo(() => labelerFor(variables), [variables, lang]); // eslint-disable-line react-hooks/exhaustive-deps
  const names = useMemo(() => namesFor(variables, scheme, target, rules), [variables, scheme, target, rules, lang]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <LabelContext.Provider value={label}>
      <NamesContext.Provider value={names}>{children}</NamesContext.Provider>
    </LabelContext.Provider>
  );
}
