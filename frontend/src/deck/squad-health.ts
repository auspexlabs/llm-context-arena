/** Tranched squad response health for breadcrumb coloring. Orange beats yellow. */

export type SquadHealth = 'ok' | 'warn' | 'bad';

export function squadHealth(responded: number, squad: number): SquadHealth | null {
  if (squad <= 0) return null;
  const missing = squad - responded;
  const ratio = responded / squad;

  if (ratio < 0.5) return 'bad';

  const warn =
    (squad > 8 && missing >= 3) || (squad >= 4 && squad <= 8 && missing >= 2);

  if (warn) return 'warn';
  return 'ok';
}

export function squadHealthLabel(responded: number, squad: number): string {
  return `${responded} answered / ${squad} squad`;
}