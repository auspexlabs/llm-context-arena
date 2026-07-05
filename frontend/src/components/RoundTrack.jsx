import { useMemo } from 'react';
import './RoundTrack.css';

const sanitizePrompt = (prompt = '') => {
  if (!prompt) return '';
  const text = typeof prompt === 'string' ? prompt : String(prompt);
  try {
    const withoutContext = text.replace(/# (relevant|manually selected)[\s\S]*?(?=User question:|$)/gi, '').trim();
    const target = withoutContext || text;
    const markerIdx = target.lastIndexOf('User question:');
    if (markerIdx !== -1) {
      return target.slice(markerIdx).trim();
    }
    return target.trim();
  } catch {
    return text;
  }
};

const normalizeRole = (role = '') => {
  const r = String(role || '').toLowerCase();
  // Strip common suffixes like _p1_t2
  return r.replace(/_p\d+_t\d+$/, '');
};

const labelForStep = (mode, role, model) => {
  const baseRole = normalizeRole(role);
  const chair = 'Chairman';
  const shortModel = (model || '').split('/').pop() || model || 'Model';

  switch (baseRole) {
    case 'answer':
    case 'stacks_answer':
    case 'draft':
      return { from: shortModel, to: 'User' };
    case 'critique':
    case 'stacks_critique':
      return { from: shortModel, to: 'Peers' };
    case 'defense':
    case 'stacks_defense':
      return { from: shortModel, to: 'Critics' };
    case 'stacks_merge':
      return { from: chair, to: 'Pair Answer' };
    case 'stacks_judge':
      return { from: chair, to: 'Merged Answer' };
    case 'extract':
      return { from: shortModel, to: 'Context Summary' };
    case 'expand':
      return { from: shortModel, to: 'Prior Extract' };
    case 'question_self':
      return { from: shortModel, to: 'Self-critique' };
    case 'muse':
      return { from: shortModel, to: 'Chair Brief' };
    case 'brief':
      return { from: chair, to: 'Models' };
    case 'chair_final':
      return { from: chair, to: 'User' };
    case 'rankings':
      return { from: 'Arena', to: 'Models' };
    default:
      return { from: shortModel || 'Model', to: 'Recipient' };
  }
};

const preview = (text = '', limit = 200) => {
  const t = (text || '').trim();
  if (!t) return '';
  return t.length > limit ? `${t.slice(0, limit)}…` : t;
};

const makeRoundStep = (mode, step) => {
  const safePrompt = step.prompt_preview || step.promptPreview || step.prompt_full || step.promptFull || '';
  const safeResponse = step.response || '';
  const { from, to } = labelForStep(mode, step.role, step.model);
  return {
    id: step.id || `${step.role || 'step'}-${step.model || 'model'}-${Math.random().toString(36).slice(2, 8)}`,
    role: step.role,
    model: step.model,
    fromLabel: from,
    toLabel: to,
    promptPreview: sanitizePrompt(safePrompt),
    responsePreview: sanitizePrompt(safeResponse),
    raw: step,
  };
};

const groupCouncil = (steps) => {
  const answers = steps.filter((s) => normalizeRole(s.role) === 'answer');
  const rankings = steps.filter((s) => normalizeRole(s.role) === 'rankings');
  const chair = steps.filter((s) => normalizeRole(s.role) === 'chair_final');
  const rounds = [];
  if (answers.length) {
    rounds.push({ id: 'council-answers', label: 'Round 1 – Answers', steps: answers });
  }
  if (rankings.length) {
    rounds.push({ id: 'council-rankings', label: 'Round 2 – Rankings', steps: rankings });
  }
  rounds.push({ id: 'council-chair', label: 'Round 3 – Chairman', steps: chair.length ? chair : [] });
  return rounds;
};

const groupFight = (steps) => {
  const answers = steps.filter((s) => normalizeRole(s.role) === 'answer');
  const critiques = steps.filter((s) => normalizeRole(s.role) === 'critique');
  const defenses = steps.filter((s) => normalizeRole(s.role) === 'defense');
  const chair = steps.filter((s) => normalizeRole(s.role) === 'chair_final');
  const rounds = [];
  if (answers.length) rounds.push({ id: 'fight-answers', label: 'Round 1 – Positions', steps: answers });
  if (critiques.length) rounds.push({ id: 'fight-critiques', label: 'Round 2 – Critiques', steps: critiques });
  if (defenses.length) rounds.push({ id: 'fight-defenses', label: 'Round 3 – Defenses', steps: defenses });
  rounds.push({ id: 'fight-chair', label: 'Round 4 – Summary', steps: chair.length ? chair : [] });
  return rounds;
};

const groupStacks = (steps) => {
  const round = (role) => steps.filter((s) => normalizeRole(s.role) === role);
  const rounds = [];
  const answers = round('stacks_answer');
  if (answers.length) rounds.push({ id: 'stacks-answers', label: 'Round 1 – Pair Answers', steps: answers });
  const merge = round('stacks_merge');
  if (merge.length) rounds.push({ id: 'stacks-merge', label: 'Round 2 – Merge', steps: merge });
  const critiques = round('stacks_critique');
  if (critiques.length) rounds.push({ id: 'stacks-critiques', label: 'Round 3 – Critiques', steps: critiques });
  const judge = round('stacks_judge');
  if (judge.length) rounds.push({ id: 'stacks-judge', label: 'Round 4 – Judge', steps: judge });
  const defenses = round('stacks_defense');
  if (defenses.length) rounds.push({ id: 'stacks-defenses', label: 'Round 5 – Defenses', steps: defenses });
  const chair = steps.filter((s) => normalizeRole(s.role) === 'chair_final');
  rounds.push({ id: 'stacks-chair', label: 'Round 6 – Final Report', steps: chair.length ? chair : [] });
  return rounds;
};

const groupRoundRobin = (steps) => {
  const drafts = steps.filter((s) => String(s.role || '').startsWith('draft_'));
  const chair = steps.filter((s) => normalizeRole(s.role) === 'chair_final');
  const byPass = {};
  for (const d of drafts) {
    const match = String(d.role || '').match(/draft_p(\d+)_t(\d+)/);
    const passNum = match ? parseInt(match[1], 10) : 1;
    const turn = match ? parseInt(match[2], 10) : 0;
    if (!byPass[passNum]) byPass[passNum] = [];
    byPass[passNum].push({ ...d, _turn: turn });
  }
  const rounds = Object.entries(byPass)
    .sort((a, b) => Number(a[0]) - Number(b[0]))
    .map(([passNum, passSteps]) => ({
      id: `rr-pass-${passNum}`,
      label: `Pass ${passNum}`,
      steps: passSteps.sort((a, b) => (a._turn || 0) - (b._turn || 0)),
    }));
  rounds.push({ id: 'rr-chair', label: 'Finalization', steps: chair.length ? chair : [] });
  return rounds;
};

const groupComplexIterative = (steps) => {
  let extractCount = 0;
  let expandCount = 0;
  const rounds = [];
  for (const step of steps) {
    const base = normalizeRole(step.role);
    if (base === 'extract') {
      extractCount += 1;
      rounds.push({ id: `ci-extract-${extractCount}`, label: `Extract ${extractCount}`, steps: [step] });
    } else if (base === 'expand') {
      expandCount += 1;
      rounds.push({ id: `ci-expand-${expandCount}`, label: `Expand ${expandCount}`, steps: [step] });
    }
  }
  const chair = steps.filter((s) => normalizeRole(s.role) === 'chair_final');
  rounds.push({ id: 'ci-chair', label: 'Chairman Final', steps: chair.length ? chair : [] });
  return rounds;
};

const groupComplexQuestioning = (steps) => {
  const round = (role) => steps.filter((s) => normalizeRole(s.role) === role);
  const rounds = [];
  const answers = round('answer');
  if (answers.length) rounds.push({ id: 'cq-answers', label: 'Round 1 – Initial Answers', steps: answers });
  const questions = round('question_self');
  if (questions.length) rounds.push({ id: 'cq-questions', label: 'Round 2 – Self-Questions', steps: questions });
  const brief = round('brief');
  if (brief.length) rounds.push({ id: 'cq-brief', label: 'Round 3 – Chair Brief', steps: brief });
  const muse = round('muse');
  if (muse.length) rounds.push({ id: 'cq-muse', label: 'Round 4 – Muse Round', steps: muse });
  const chair = round('chair_final');
  rounds.push({ id: 'cq-chair', label: 'Round 5 – Chairman Final', steps: chair.length ? chair : [] });
  return rounds;
};

const groupFallback = (steps) => {
  const byRole = {};
  for (const s of steps) {
    const key = normalizeRole(s.role) || 'step';
    if (!byRole[key]) byRole[key] = [];
    byRole[key].push(s);
  }
  return Object.entries(byRole).map(([role, grouped], idx) => ({
    id: `fallback-${role}-${idx}`,
    label: `Round – ${role}`,
    steps: grouped,
  }));
};

const buildRounds = (mode, steps) => {
  const safeSteps = steps || [];
  const m = (mode || 'council').toLowerCase();
  switch (m) {
    case 'council':
    case 'baseline':
      return groupCouncil(safeSteps);
    case 'fight':
      return groupFight(safeSteps);
    case 'stacks':
      return groupStacks(safeSteps);
    case 'round_robin':
      return groupRoundRobin(safeSteps);
    case 'complex_iterative':
      return groupComplexIterative(safeSteps);
    case 'complex_questioning':
      return groupComplexQuestioning(safeSteps);
    default:
      return groupFallback(safeSteps);
  }
};

export function RoundTrack({ mode, steps, onSelectStep }) {
  const rounds = useMemo(() => {
    const grouped = buildRounds(mode, steps || []);
    return grouped.map((round) => ({
      ...round,
      steps: round.steps.map((s) => makeRoundStep(mode, s)),
    }));
  }, [mode, steps]);

  if (!rounds.length) return null;

  return (
    <div className="roundtrack">
      <div className="roundtrack-title">Mode Timeline (Round view)</div>
      {rounds.map((round, idx) => {
        const visibleSteps = round.steps;
        return (
          <div className="roundtrack-round" key={round.id || idx}>
            <div className="roundtrack-round-header">
              <div className="roundtrack-round-label">{round.label}</div>
              <div className="roundtrack-round-order">Step {idx + 1} of {rounds.length}</div>
            </div>
            <div className="roundtrack-steps">
              {visibleSteps.map((step, i) => (
                <button
                  className="roundtrack-step-card"
                  key={step.id}
                  type="button"
                  onClick={() => onSelectStep && onSelectStep(step.raw?.__idx ?? step.raw?.index ?? null)}
                >
                  <div className="roundtrack-step-top">
                    <span className="roundtrack-step-model">{step.model?.split('/').pop() || step.model || 'Model'}</span>
                    <span className="roundtrack-step-role">{step.role || ''}</span>
                  </div>
                  {round.steps.length > 1 && (
                    <div className="roundtrack-step-badge">#{i + 1} / {round.steps.length}</div>
                  )}
                  <div className="roundtrack-step-flow">
                    <span>{step.fromLabel}</span>
                    <span className="roundtrack-arrow">→</span>
                    <span>{step.toLabel}</span>
                  </div>
                  <div className="roundtrack-step-text">
                    {preview(step.responsePreview || step.promptPreview || '', 260) || 'No content'}
                  </div>
                </button>
              ))}
            </div>
            {idx < rounds.length - 1 && <div className="roundtrack-connector">➜</div>}
          </div>
        );
      })}
    </div>
  );
}
