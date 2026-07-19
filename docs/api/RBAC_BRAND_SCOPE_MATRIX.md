# RBAC and brand-scope matrix

All dashboard routes require a signed dashboard JWT. A non-production
`X-Admin-Key` compatibility path is allowed only when explicitly enabled; it is
never a production tenant-RBAC bypass.

| Role | Scope | Core permissions | Privacy lifecycle |
| --- | --- | --- | --- |
| `super_admin`, `admin`, `org_admin` | Platform-wide | All brand, agent, document, message, API-key, and user operations | `privacy:read`, `privacy:write`, `privacy:delete` for every brand |
| `brand_admin` | IDs in `user.brands` | Brand/agent/document/message/API-key operations in assigned brands | Full privacy lifecycle only in assigned brands |
| `operator` | IDs in `user.brands` | Read-only brand/agent/document/message access; message write for human takeover | No privacy export, policy, or deletion permission |
| `viewer` | IDs in `user.brands` | Not admitted to the dashboard control plane | No privacy permission |
| `user` | Own account/API-key scope | Not admitted to the dashboard control plane | No privacy permission |

Brand-scoped routes call `ensure_brand_access`. They respond with `404` for an
unassigned brand so that a tenant cannot enumerate another tenant's resources.
The widget uses a different identity system: a signed session is checked
against an immutable Mongo conversation scope and the agent's current
`brand_id`/`brand_slug`. If an operator moves the agent to another brand, old
widget sessions fail closed instead of following that agent into the new tenant.

`privacy:*` is intentionally separate from `user:*`: dashboard-user account
management is not authority to export or erase an end user's conversation data.
