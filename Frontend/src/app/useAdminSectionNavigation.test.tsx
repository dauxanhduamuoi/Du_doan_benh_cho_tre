import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { CurrentUser } from '@/lib/api';
import { useAdminSectionNavigation } from './useAdminSectionNavigation';

const admin: CurrentUser = {
  id: 1,
  username: 'admin',
  full_name: 'Admin',
  role: 'admin',
  is_active: true,
  permissions: [],
};

function NavigationHarness({ user = admin }: { user?: CurrentUser }) {
  const { activeTab, navigateToTab } = useAdminSectionNavigation(user);
  return <>
    <output aria-label="active section">{activeTab}</output>
    <button type="button" onClick={() => navigateToTab('medical-knowledge')}>Medical Knowledge</button>
    <button type="button" onClick={() => navigateToTab('reports')}>Reports</button>
  </>;
}

function setUrl(search = '') {
  window.history.replaceState({}, '', `/${search}`);
}

afterEach(() => setUrl());

describe('URL-backed Admin section navigation', () => {
  it('restores Medical Knowledge from a direct URL', () => {
    setUrl('?section=medical-knowledge');
    render(<NavigationHarness />);
    expect(screen.getByLabelText('active section')).toHaveTextContent('medical-knowledge');
  });

  it('updates the URL when a section is clicked', () => {
    setUrl();
    render(<NavigationHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Medical Knowledge' }));
    expect(screen.getByLabelText('active section')).toHaveTextContent('medical-knowledge');
    expect(new URLSearchParams(window.location.search).get('section')).toBe('medical-knowledge');
  });

  it('restores the selected section after remount', () => {
    setUrl();
    const first = render(<NavigationHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Medical Knowledge' }));
    first.unmount();

    render(<NavigationHarness />);
    expect(screen.getByLabelText('active section')).toHaveTextContent('medical-knowledge');
  });

  it('follows browser history through popstate', () => {
    setUrl('?section=medical-knowledge');
    render(<NavigationHarness />);
    fireEvent.click(screen.getByRole('button', { name: 'Reports' }));
    expect(screen.getByLabelText('active section')).toHaveTextContent('reports');

    act(() => {
      window.history.replaceState({}, '', '/?section=medical-knowledge');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });
    expect(screen.getByLabelText('active section')).toHaveTextContent('medical-knowledge');
  });

  it.each(['', '?section=unknown'])('falls back to Overview for a missing or invalid section: %s', (search) => {
    setUrl(search);
    render(<NavigationHarness />);
    expect(screen.getByLabelText('active section')).toHaveTextContent('dashboard');
  });

  it('does not restore or navigate to a section the current role cannot access', () => {
    const viewer: CurrentUser = {
      ...admin,
      username: 'viewer',
      role: 'viewer',
      permissions: ['feature.dashboard'],
    };
    setUrl('?section=medical-knowledge');
    render(<NavigationHarness user={viewer} />);
    expect(screen.getByLabelText('active section')).toHaveTextContent('dashboard');

    fireEvent.click(screen.getByRole('button', { name: 'Medical Knowledge' }));
    expect(screen.getByLabelText('active section')).toHaveTextContent('dashboard');
    expect(new URLSearchParams(window.location.search).get('section')).toBe('dashboard');
  });
});
