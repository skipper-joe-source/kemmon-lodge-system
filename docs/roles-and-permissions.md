# Roles and permissions

This is the proposed starting policy based on the supplied system diagram. Confirm it before implementation.

| Action | Owner / Manager | Receptionist | Bartender | Housekeeping |
|---|---|---|---|---|
| View management dashboard and all reports | Yes | No | No | No |
| Manage staff and permissions | Yes | No | No | No |
| Configure rooms and rates | Yes | No | No | No |
| View room readiness and availability | Yes | Yes | Limited room lookup | Assigned rooms |
| Manage guests and reservations | Yes | Yes | No | No |
| Check in and check out | Yes | Yes | No | No |
| View guest folios | Yes | Yes | Limited charge lookup | No |
| Record guest payments | Yes | Yes | Own bar sales only | No |
| Create bar sales and charge to room | Yes | No initially | Yes | No |
| Record stock movements | Yes | No | Allowed bar movements | No |
| Approve stock adjustments | Yes | No | No | No |
| Update cleaning tasks and readiness | Yes | View status | No | Assigned tasks |
| Report maintenance issues | Yes | Yes | Yes | Yes |
| Approve expenses, refunds, voids, and exceptions | Yes | No | No | No |
| Operate cashier shift | Yes | Own shift if assigned | Own shift if assigned | No |
| View audit logs and variance alerts | Yes | No | No | No |

## Enforcement
Deny unlisted actions by default. Enforce permission checks in the API and limit records by assignment or ownership when relevant. Hiding a button alone does not provide security. Manager actions remain audited. Staff account deactivation must prevent further access.
