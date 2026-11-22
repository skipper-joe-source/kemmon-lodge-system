# Proposed database design

This is a design sketch, not executable SQL. Review it before creating SQLAlchemy models and migrations.

## Phase 1 tables
| Table | Main fields / relationships |
|---|---|
| users | id, username (unique), password_hash, role, is_active, created_at |
| room_types | id, name, capacity, default_rate |
| rooms | id, room_number (unique), room_type_id, cleaning_status, maintenance_status |
| guests | id, full_name, phone, email, identification details only where needed |
| reservations | id, primary_guest_id, booking_source, status, created_by, created_at |
| reservation_rooms | id, reservation_id, room_id, arrival_date, departure_date, agreed_nightly_rate |
| stays | id, reservation_id, actual_check_in, actual_check_out, checked_in_by, checked_out_by |
| folios | id, reservation_id, status, opened_at, closed_at |
| charges | id, folio_id, description, quantity, unit_price, amount, posted_by, posted_at, reversal_of_id |
| payments | id, folio_id, amount, method, reference, status, received_by, received_at, reversal_of_id |
| housekeeping_tasks | id, room_id, assigned_to, status, created_at, completed_at |
| maintenance_issues | id, room_id, description, status, reported_by, resolved_at |
| audit_logs | id, actor_id, action, entity_type, entity_id, timestamp, reason, safe change summary |

## Relationships
- A room type has many rooms.
- A guest can have many reservations.
- A reservation has one or more room allocations, a stay record, and a folio.
- A folio has many charges and payments.
- A room has many cleaning tasks and maintenance issues over time.
- User references identify staff responsible for actions.

## Key rules
- Arrival must precede departure. Use half-open booking ranges: departure day can be the next booking's arrival day.
- Enforce non-overlapping active room allocations at the database level, with transactional handling for concurrent booking requests. Choose the exact PostgreSQL constraint design during implementation.
- Date-based availability is separate from cleaning status, maintenance status, and current occupancy.
- Store money as fixed-precision numeric values, never floating point; confirm currency and precision.
- Preserve agreed booking rates and charge prices when default rates change.
- Folio balance comes from posted charges minus successful payments, including properly recorded reversals/refunds; do not store a manually edited balance.
- Use foreign keys, required-field constraints, status validation, and indexes on relevant lookups.
- Store timestamps with timezone; use lodge-local dates for booking boundaries.
- Financial corrections use auditable reversals. Do not silently overwrite or delete historical financial records.
- Do not include passwords, secrets, or unnecessary guest ID data in audit logs.

## Later tables
products, suppliers, purchases, purchase_items, bar_sales, bar_sale_items, stock_movements, stock_counts, stock_count_items, expenses, expense_approvals, cashier_shifts, cash_movements, alerts.

Purchases increase stock when received. Sales reduce stock when confirmed. Stock movements are the traceable source for quantities. Bar sales charged to rooms link to the folio charge, avoiding duplicate revenue and payments.

## Migration plan
Initialize Alembic after configuring SQLAlchemy. Generate and review migrations for each feature. Keep migrations in version control; test upgrades on a development database before applying them to live data.
