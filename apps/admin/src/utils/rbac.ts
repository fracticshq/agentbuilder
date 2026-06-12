import type { AuthUser } from '../api/client';

const CONSOLE_ROLES = new Set([
  'admin',
  'super_admin',
  'org_admin',
  'organization_admin',
  'brand_admin',
  'operator',
]);

export function canAccessAgentConsole(user?: AuthUser | null): boolean {
  if (!user?.role) {
    return false;
  }
  return CONSOLE_ROLES.has(String(user.role).toLowerCase());
}
