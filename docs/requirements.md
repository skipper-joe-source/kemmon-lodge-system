# Requirements

## Purpose
Give lodge staff a shared record of room availability, guest stays, payments, bar transactions, and stock. Give the owner visibility into operations and discrepancies.

## Phase 1: usable lodge workflow
- Staff login, active/inactive accounts, and role-based permissions.
- Room types, room numbers, default rates, cleaning status, and maintenance status.
- Guest contact details and reservation creation, changes, and cancellation.
- Availability by arrival and departure date; prevent overlapping room bookings.
- Check-in, room assignment, guest folio, charges, deposits, payments, receipts, and check-out.
- Housekeeping tasks and room readiness updates.
- Basic occupancy, charges, payments, and outstanding-balance reports.
- Audit records for important changes, including approvals and reversals.

## Phase 2: bar and inventory
- Bar orders, direct payments, and charges to active guest folios.
- Products, suppliers, purchases, stock receipts, sales movements, wastage, and adjustments.
- Physical stock counts and variance review.

## Phase 3: management controls
- Expenses with receipts and manager approval.
- Cashier opening balances, cash movements, shift closure, and reconciliation.
- Alerts for cash variance, stock variance, unusual activity, and system errors.
- Expanded operational and financial reports.

## Optional integrations
Card payment gateway, mobile money, email/WhatsApp notifications, and online travel agency booking connections. Initially record payment methods manually; recording a payment does not process it externally.

## Acceptance criteria for Phase 1
1. Two overlapping active bookings cannot allocate the same room, including simultaneous requests.
2. A guest cannot check into a room that is occupied, dirty, or blocked for maintenance.
3. Charges and payments remain separate; deposits and partial payments update the folio balance correctly.
4. Checkout requires a settled balance unless a manager explicitly authorizes an exception with a reason.
5. Checkout creates a cleaning task; only an authorized readiness update makes the room ready again.
6. API permissions enforce each role, even if users bypass the website controls.
7. Important actions identify the staff member, record, timestamp, and reason when required.

## Decisions to confirm before implementation
Currency and rounding; taxes; rate rules; check-in/out times; cancellation and refund policies; guest ID requirements and retention; receipt numbering; inventory units; permissions for exceptions; whether public guest booking is included in Phase 1.

## Operational requirements
Hash passwords, use HTTPS in deployment, protect sessions, restrict guest data by role, validate inputs, use database transactions for related changes, and verify backup restoration before live use. Optional manager two-factor authentication can be added later.
