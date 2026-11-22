# Operational workflows

## Staff access
Open website → login → verify account → load role permissions → open permitted dashboard. Failed login returns a generic error. Permissions are enforced by the backend on every protected action.

## Reservations and stay
1. Receive a walk-in, phone, or website booking request.
2. Enter dates and guest count; search availability for that date range.
3. If unavailable, offer alternative rooms or dates.
4. Record guest details and reservation; allocate rooms without overlapping active bookings.
5. Record any deposit as a payment associated with the guest folio.
6. At arrival, verify details and confirm the assigned room is ready.
7. Check in, record actual arrival, and open or reuse the folio.
8. Record room charges and additional services; apply the agreed rate snapshot.
9. Record payments and keep the remaining balance visible.
10. At departure, review final charges and settle the balance.
11. Issue receipt, close the stay, and mark the room dirty.
12. Create a housekeeping task; clean, inspect, and mark ready. Block the room if maintenance is needed.

Cancellation and no-show handling must follow the agreed deposit/refund policy. Amendments must recheck availability.

## Bar sale
Select products → check stock → confirm quantities and prices → receive payment or verify an active room folio → issue receipt or post folio charge → reduce stock and record movement. Related sale, charge, and stock changes must succeed together. Reversed sales require an auditable reversal; stock returns depend on whether products were actually returned.

## Inventory
Record supplier purchase → receive actual quantities → add stock movements → maintain stock balance → count physical stock → compare → record discrepancies → manager reviews adjustments.

## Expenses
Submit supplier/category/amount/payment method and receipt → manager approves or rejects → record payment when made → include in expense and cash reports. Approval and payment are separate states.

## Cashier shifts
Open shift with opening cash → record cash receipts and payouts → count closing cash → compare expected and actual cash → record variance and explanation → manager reviews discrepancies → close shift. Card, bank, and mobile money receipts are reported separately from physical cash.

## Oversight
Operational actions → PostgreSQL records and audit events → reports and applicable alerts → owner/manager review. Audit records must not be editable through ordinary staff functions.
