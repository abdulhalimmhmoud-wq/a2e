import { useState } from "react";
import { api, type PropagationPlan, type Segment } from "../api";
import { useI18n } from "../i18n";

interface Props {
  source: Segment;
  plan: PropagationPlan;
  onClose: () => void;
  onApplied: (count: number) => void;
}

/**
 * حوار الانتشار: يعرض كل المواضع المرشّحة للتعديل قبل تطبيقه.
 *
 * الاعتماد على الموافقة مقصود — نفس الكلمة قد تكون لها ترجمة مختلفة
 * حسب السياق، فالتطبيق الأعمى على المستند كله يفسد أكثر مما يصلح.
 */
export default function PropagationDialog({ source, plan, onClose, onApplied }: Props) {
  const { t } = useI18n();
  const [selected, setSelected] = useState<Set<string>>(
    // المطابقات التامة مختارة مبدئيًا، ومطابقات المصطلح لا
    new Set(plan.needs_review.filter((t) => t.match_type === "exact").map((t) => t.segment_id))
  );
  const [busy, setBusy] = useState(false);

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const apply = async () => {
    setBusy(true);
    try {
      const ids = [...selected];
      const texts: Record<string, string> = {};
      plan.needs_review.forEach((target) => {
        if (selected.has(target.segment_id)) {
          texts[target.segment_id] = target.proposed_target;
        }
      });
      const result = await api.propagate(source.id, ids, texts);
      onApplied(result.applied);
    } finally {
      setBusy(false);
    }
  };

  const exact = plan.needs_review.filter((item) => item.match_type === "exact");
  const terms = plan.needs_review.filter((item) => item.match_type === "term");

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <header>
          <strong style={{ fontSize: 16 }}>{t("prop.title")}</strong>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
            {plan.auto_applied > 0 &&
              t("prop.autoApplied", { n: plan.auto_applied })}
            {t("prop.needsApproval")}
          </div>
        </header>

        <div className="body">
          {exact.length > 0 && (
            <>
              <div className="row" style={{ marginTop: 12 }}>
                <span className="badge accent">{t("prop.exactMatch")}</span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {t("prop.exactMatchHint")}
                </span>
              </div>
              {exact.map((target) => (
                <label key={target.segment_id} className="prop-item">
                  <input
                    type="checkbox"
                    style={{ width: 16, marginTop: 4 }}
                    checked={selected.has(target.segment_id)}
                    onChange={() => toggle(target.segment_id)}
                  />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="loc muted" style={{ fontSize: 11.5 }}>
                      {target.location}
                    </div>
                    <div className="ltr diff-before">{target.current_target}</div>
                    <div className="ltr diff-after">{target.proposed_target}</div>
                  </div>
                </label>
              ))}
            </>
          )}

          {terms.length > 0 && (
            <>
              <div className="row" style={{ marginTop: 18 }}>
                <span className="badge warn">{t("prop.termLevel")}</span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {t("prop.termLevelHint")}
                </span>
              </div>
              {terms.map((target) => (
                <label key={target.segment_id} className="prop-item">
                  <input
                    type="checkbox"
                    style={{ width: 16, marginTop: 4 }}
                    checked={selected.has(target.segment_id)}
                    onChange={() => toggle(target.segment_id)}
                  />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="loc muted" style={{ fontSize: 11.5 }}>
                      {target.location}
                    </div>
                    <div className="ltr diff-before">{target.current_target}</div>
                    <div className="ltr diff-after">{target.proposed_target}</div>
                  </div>
                </label>
              ))}
            </>
          )}

          {plan.needs_review.length === 0 && (
            <div className="empty">{t("prop.none")}</div>
          )}
        </div>

        <footer>
          <button className="btn primary" onClick={apply} disabled={busy || !selected.size}>
            {t("prop.apply", { n: selected.size })}
          </button>
          <button className="btn" onClick={onClose}>
            {t("prop.skip")}
          </button>
          <div className="spacer" />
          <button
            className="btn sm"
            onClick={() =>
              setSelected(new Set(plan.needs_review.map((item) => item.segment_id)))
            }
          >
            {t("prop.selectAll")}
          </button>
          <button className="btn sm" onClick={() => setSelected(new Set())}>
            {t("prop.selectNone")}
          </button>
        </footer>
      </div>
    </div>
  );
}
