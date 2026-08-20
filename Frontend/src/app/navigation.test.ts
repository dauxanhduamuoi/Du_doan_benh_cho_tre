import { describe, expect, it } from 'vitest';
import type { CurrentUser } from '@/lib/api';
import { canAccessTab, getMainNavItems } from './navigation';

function user(role: string): CurrentUser {
  return {
    id: 1,
    username: role,
    full_name: null,
    role,
    is_active: true,
    permissions: [],
  };
}

describe('medical knowledge navigation authorization', () => {
  it('adds a Medical Knowledge tab to the internal navigation', () => {
    const items = getMainNavItems((key) => key);
    expect(items.find((item) => item.id === 'medical-knowledge')?.label).toBe('sidebar.medicalKnowledge');
    expect(items.some((item) => item.id === ('parent' as never))).toBe(false);
  });

  it('allows admin and staff but hides the tab from other roles and anonymous users', () => {
    expect(canAccessTab(user('admin'), 'medical-knowledge')).toBe(true);
    expect(canAccessTab(user('staff'), 'medical-knowledge')).toBe(true);
    expect(canAccessTab(user('viewer'), 'medical-knowledge')).toBe(false);
    expect(canAccessTab(null, 'medical-knowledge')).toBe(false);
  });
});
