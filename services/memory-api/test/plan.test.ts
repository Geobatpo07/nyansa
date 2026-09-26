import { describe, expect, it } from 'vitest';

import { planIngest } from '../src/ingest/plan.js';

const V = 'v1';

describe('planIngest', () => {
  const vault = [
    { path: 'new.md', hash: 'n' },
    { path: 'same.md', hash: 's' },
    { path: 'edited.md', hash: 'e2' },
    { path: 'old-version.md', hash: 'o' },
  ];
  const indexed = [
    { path: 'same.md', hash: 's', version: V },
    { path: 'edited.md', hash: 'e1', version: V },
    { path: 'old-version.md', hash: 'o', version: 'v0' },
    { path: 'deleted.md', hash: 'd', version: V },
  ];

  it('incremental: indexes new, modified and outdated notes only', () => {
    expect(planIngest(vault, indexed, 'incremental', V)).toEqual({
      toIndex: ['new.md', 'edited.md', 'old-version.md'],
      unchanged: ['same.md'],
      toDelete: ['deleted.md'],
    });
  });

  it('full: indexes every note and still removes deleted ones', () => {
    expect(planIngest(vault, indexed, 'full', V)).toEqual({
      toIndex: ['new.md', 'same.md', 'edited.md', 'old-version.md'],
      unchanged: [],
      toDelete: ['deleted.md'],
    });
  });

  it('empty index: everything is new', () => {
    expect(planIngest(vault, [], 'incremental', V).toIndex).toHaveLength(4);
  });

  it('empty vault: everything indexed is deleted', () => {
    expect(planIngest([], indexed, 'incremental', V)).toEqual({
      toIndex: [],
      unchanged: [],
      toDelete: ['deleted.md', 'edited.md', 'old-version.md', 'same.md'],
    });
  });
});
