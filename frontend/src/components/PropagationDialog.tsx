import { useState } from "react";
import { api, type PropagationPlan, type Segment } from "../api";

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

  const exact = plan.needs_review.filter((t) => t.match_type === "exact");
  const terms = plan.needs_review.filter((t) => t.match_type === "term");

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" onClick={(e) => e.stopPropagation()}>
        <header>
          <strong style={{ fontSize: 16 }}>تطبيق التعديل على مواضع أخرى</strong>
          <div className="muted" style={{ fontSize: 12.5, marginTop: 4 }}>
            {plan.auto_applied > 0 && (
              <>طُبّق تلقائيًا على {plan.auto_applied} مقطع مطابق تمامًا. </>
            )}
            المواضع التالية تحتاج موافقتك لأن السياق قد يختلف.
          </div>
        </header>

        <div className="body">
          {exact.length > 0 && (
            <>
              <div className="row" style={{ marginTop: 12 }}>
                <span className="badge accent">مطابقة تامة</span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  نفس النص المصدر، لكن مُعدَّل يدويًا من قبل
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
                <span className="badge warn">على مستوى المصطلح</span>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  المصطلح نفسه يظهر في مقاطع أخرى — راجع كل موضع
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
            <div className="empty">لا توجد مواضع أخرى تحتاج مراجعة.</div>
          )}
        </div>

        <footer>
          <button className="btn primary" onClick={apply} disabled={busy || !selected.size}>
            تطبيق على {selected.size} موضع
          </button>
          <button className="btn" onClick={onClose}>
            تخطّي
          </button>
          <div className="spacer" />
          <button
            className="btn sm"
            onClick={() =>
              setSelected(new Set(plan.needs_review.map((t) => t.segment_id)))
            }
          >
            تحديد الكل
          </button>
          <button className="btn sm" onClick={() => setSelected(new Set())}>
            إلغاء التحديد
          </button>
        </footer>
      </div>
    </div>
  );
}
