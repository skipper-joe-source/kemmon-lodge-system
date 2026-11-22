import LodgeShell from './LodgeShell';
import LodgeDashboard from './LodgeDashboard';
import Backups from './Backups';
import RoomCalendar from './RoomCalendar';
import ConfirmationPrompt, {useConfirmationAnchors} from './ConfirmationPrompt';
import ReservationEditDialog from './ReservationEditDialog';
import OwnerAlerts from './OwnerAlerts';
import AuditLogs from './AuditLogs';
import CashierShifts from './CashierShifts';
import BarPOS, { BarReceiptContent, GuestBarCharges, BarSalesReport } from './BarPOS';
import InventoryPanel from './InventoryPanel';
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

const emptyBooking = { guest: "", phone: "", guestCount: 1, roomId: "1", checkIn: "", checkOut: "" };
const emptyWalkIn = { guest: "", phone: "", guestCount: 1, roomId: "", checkOut: "" };
function lodgeToday() {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Africa/Dar_es_Salaam", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(new Date());
  const value = (type) => parts.find((part) => part.type === type).value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}
const money = (amount) => `TZS ${amount.toLocaleString("en-US")}`;
const nightsBetween = (start, end) => start && end
  ? Math.round((Date.parse(end) - Date.parse(start)) / 86400000) : 0;
const validStay = (start, end) => Boolean(start && end && end >= start);
const chargeUnits = (start, end) => validStay(start, end) ? Math.max(1, nightsBetween(start, end)) : 0;
const stayDescription = (start, end) => start === end ? "Same-day stay" : `${nightsBetween(start, end)} night${nightsBetween(start, end) === 1 ? "" : "s"}`;
const timeInTanzania = (value) => value ? new Intl.DateTimeFormat("en-GB", {
  timeZone: "Africa/Dar_es_Salaam", day: "2-digit", month: "short", year: "numeric",
  hour: "2-digit", minute: "2-digit", hour12: true,
}).format(new Date(value)) : "—";
const effectiveEnd = (start, end) => start === end
  ? new Date(Date.parse(`${start}T00:00:00Z`) + 86400000).toISOString().slice(0, 10) : end;
const staysOverlap = (start, end, otherStart, otherEnd) =>
  validStay(start, end) && validStay(otherStart, otherEnd) &&
  start < effectiveEnd(otherStart, otherEnd) && effectiveEnd(start, end) > otherStart;
const statusLabels = {
  confirmed: "Booked", checked_in: "Checked in", checked_out: "Checked out", cancelled: "Cancelled",
};
const roomLabel = (room) => room.maintenanceStatus === "out_of_service" ? "Out of service" : room.taken ? "Taken"
  : room.cleaningStatus === "needs_cleaning" ? "Needs cleaning" : "Free";

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api${path}`, {
      ...options, headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch { throw new Error("Cannot reach the backend. Start FastAPI on port 8000 and retry."); }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = Array.isArray(body.detail)
      ? body.detail.map((item) => `${item.loc?.at(-1) || "Field"}: ${item.msg}`).join("; ")
      : body.detail;
    const error = new Error(typeof detail === "string" && detail !== "Not Found" ? detail
      : response.status === 404 ? "This API action was not found. Restart FastAPI after replacing backend/app/main.py with the latest code."
        : "Request failed. Check the backend terminal.");
    error.status = response.status;
    if (response.status === 401 && path !== "/auth/login") window.dispatchEvent(new Event("kemmon-session-ended"));
    throw error;
  }
  return response.status === 204 ? null : response.json();
}

const pendingPaymentKey = "kemmon-pending-payment-v1";
function readPendingPayment() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(pendingPaymentKey) || "null");
    return saved && saved.reservationId && saved.requestId && saved.amount ? saved : null;
  } catch { return null; }
}

function ReceiptViewer({ paymentId, onClose }) {
  const dialogRef = useRef(null);
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const dialog = dialogRef.current;
    dialog.showModal();
    return () => { if (dialog.open) dialog.close(); };
  }, []);

  useEffect(() => {
    let ignore = false;
    setLoading(true); setReceipt(null); setError("");
    api(`/receipts/${paymentId}`).then((data) => {
      if (!ignore) setReceipt(data);
    }).catch((error) => {
      if (!ignore) setError(error.message);
    }).finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [paymentId]);

  return createPortal(<dialog ref={dialogRef} className="receipt-dialog" aria-labelledby="receipt-title" onCancel={(event) => { event.preventDefault(); onClose(); }}>
    <div className="receipt-toolbar">
      <button type="button" onClick={() => window.print()} disabled={!receipt || loading}>Print / Save as PDF</button>
      <button type="button" onClick={onClose}>Close receipt</button>
    </div>
    <article className="guest-receipt">
      <header><h1 id="receipt-title">{receipt?.lodgeName || "Kemmon Lodge"}</h1><h2>{receipt?.type === "bar" ? "Bar sales receipt" : "Payment receipt"}</h2></header>
      {loading && <p role="status">Loading receipt…</p>}
      {error && <p role="alert">{error}</p>}
      {receipt?.type === "bar" ? <BarReceiptContent receipt={receipt} /> : receipt && <>
        <p className="receipt-number"><strong>Receipt number</strong><br />{receipt.receiptNumber}</p>
        <dl className="receipt-details">
          <dt>Payment received</dt><dd>{timeInTanzania(receipt.payment.paidAt)}</dd>
          <dt>Guest</dt><dd>{receipt.reservation.guest}</dd>
          <dt>Room at payment</dt><dd>{receipt.payment.roomNumberAtPayment ?? receipt.reservation.roomNumber}</dd>
          <dt>Arrival date</dt><dd>{receipt.reservation.checkIn}</dd>
          <dt>Departure date</dt><dd>{receipt.reservation.checkOut}</dd>
          <dt>Stay</dt><dd>{stayDescription(receipt.reservation.checkIn, receipt.reservation.checkOut)}</dd>
          <dt>Payment method</dt><dd>{receipt.payment.method === "cash" ? "Cash" : "Mobile money"}</dd>
          {receipt.payment.reference && <><dt>Transaction reference</dt><dd>{receipt.payment.reference}</dd></>}
          <dt>Received by</dt><dd>{receipt.payment.receivedBy}</dd>
        </dl>
        <p className="receipt-amount">Amount received on this receipt <strong>{money(receipt.payment.amount)}</strong></p>
        <h3>Current reservation balance</h3>
        {receipt.reservation.credit > 0 && <p><strong>Credit due: {money(receipt.reservation.credit)}</strong>. No automatic refund has been issued.</p>}
        <dl className="receipt-details">
          <dt>Room charges</dt><dd>{money(receipt.reservation.roomTotal)}</dd><dt>Bar charges</dt><dd>{money(receipt.reservation.barCharges)}</dd><dt>Total bill</dt><dd>{money(receipt.reservation.total)}</dd>
          <dt>Total paid to date</dt><dd>{money(receipt.reservation.paid)}</dd>
          <dt>Remaining balance</dt><dd><strong>{money(receipt.reservation.balance)}</strong></dd>
        </dl>
        <p className="receipt-note">Balance updated as of {timeInTanzania(receipt.issuedAt)}. It includes all payments recorded for this reservation, not only this receipt.</p>
        <footer><p>Thank you for staying at Kemmon Lodge.</p><p className="receipt-note">All times shown in Tanzania time.</p></footer>
      </>}
    </article>
  </dialog>, document.body);
}


function PaymentsPanel({ reservations, selectedId, setSelectedId, connected, onSaved, canRecord, onReceipt }) {
  const [pending, setPending] = useState(readPendingPayment);
  const [details, setDetails] = useState(null);
  const [draft, setDraft] = useState({ amount: "", method: "cash", reference: "" });
  const [review, setReview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const reservationId = pending?.reservationId || selectedId;
  const reservation = details?.reservation?.id === reservationId ? details.reservation : null;
  const locked = saving || Boolean(pending);

  useEffect(() => {
    let ignore = false;
    setDetails(null);
    setReview(null);
    setDraft({ amount: "", method: "cash", reference: "" });
    setMessage("");
    if (!reservationId || !connected) { setLoading(false); return; }
    setLoading(true);
    api(`/reservations/${reservationId}/payments`).then((data) => {
      if (!ignore) setDetails(data);
    }).catch((error) => {
      if (!ignore) setMessage(error.message);
    }).finally(() => { if (!ignore) setLoading(false); });
    return () => { ignore = true; };
  }, [reservationId, connected]);

  function updateDraft(event) {
    const { name, value } = event.target;
    setDraft((current) => ({ ...current, [name]: value, ...(name === "method" ? { reference: "" } : {}) }));
    setReview(null);
    setMessage("");
  }

  function reviewPayment(event) {
    event.preventDefault();
    if (!reservation || locked || !connected || !canRecord) return;
    if (!/^\d+$/.test(draft.amount) || Number(draft.amount) <= 0 || Number(draft.amount) > reservation.balance) {
      setMessage("Enter a whole TZS amount greater than zero and no more than the remaining balance.");
      return;
    }
    if (draft.method === "mobile_money" && !draft.reference.trim()) {
      setMessage("Enter the mobile-money transaction reference.");
      return;
    }
    setReview({
      reservationId, requestId: crypto.randomUUID(), amount: draft.amount,
      method: draft.method, reference: draft.method === "mobile_money" ? draft.reference.trim().toUpperCase() : null,
    });
  }

  async function savePayment(receipt) {
    if (!receipt || saving || !connected || !canRecord) return;
    setSaving(true);
    setMessage("");
    let submitted = false;
    try {
      // Keep the same request on a retry so a lost response cannot duplicate cash.
      sessionStorage.setItem(pendingPaymentKey, JSON.stringify(receipt));
      setPending(receipt);
      setReview(null);
      submitted = true;
      const result = await api(`/reservations/${receipt.reservationId}/payments`, {
        method: "POST", body: JSON.stringify({
          requestId: receipt.requestId, amount: receipt.amount,
          method: receipt.method, reference: receipt.reference,
        }),
      });
      sessionStorage.removeItem(pendingPaymentKey);
      setSelectedId(receipt.reservationId);
      setPending(null);
      setDraft({ amount: "", method: "cash", reference: "" });
      setDetails((current) => ({
        reservation: result.reservation,
        payments: [...(current?.payments || []).filter((item) => item.id !== result.payment.id), result.payment],
      }));
      setMessage("Payment recorded. The balance has been updated.");
      await onSaved();
    } catch (error) {
      if (error.status >= 400 && error.status < 500 && ![401, 403].includes(error.status)) {
        sessionStorage.removeItem(pendingPaymentKey);
        setPending(null);
        setMessage(error.message);
      } else {
        setMessage(submitted
          ? `Could not confirm whether the payment saved. Retry the same payment using the button below. ${error.message}`
          : "Could not prepare the payment safely. Allow browser session storage and try again.");
      }
    } finally { setSaving(false); }
  }

  async function refreshHistory() {
    setLoading(true);
    try {
      const data = await api(`/reservations/${reservationId}/payments`);
      setDetails(data);
      await onSaved();
      setMessage("Payment history refreshed.");
    } catch (error) { setMessage(error.message); }
    finally { setLoading(false); }
  }

  return <section>
    <h2>Payments</h2>
    <p>Record cash or mobile money already received. Mobile transfers must be confirmed separately before recording.</p>
    <label className="payment-selector">Reservation<select value={reservationId} disabled={locked || !connected} onChange={(event) => setSelectedId(event.target.value)}>
      <option value="">Choose a guest and room</option>
      {reservations.map((item) => <option value={item.id} key={item.id}>{item.guest} — Room {item.roomNumber} — {item.checkIn} — {statusLabels[item.status]}</option>)}
    </select></label>
    {message && <p role="status">{message}</p>}
    {loading && <p role="status">Loading payment history…</p>}
    {pending && canRecord && <div className="action-confirmation">
      <p>Finish confirming this payment before recording another: {money(Number(pending.amount))}, {pending.method === "cash" ? "Cash" : "Mobile money"}{pending.reference ? `, reference ${pending.reference}` : ""}.</p>
      <button type="button" disabled={saving || !connected} onClick={() => savePayment(pending)}>{saving ? "Saving…" : "Retry same payment"}</button>
    </div>}
    {reservation && <>
      <h3>{reservation.guest} · Room {reservation.roomNumber}</h3>
      <GuestBarCharges api={api} reservationId={reservation.id} refreshKey={reservation.barCharges} />
      <p>Open your shift in Cashier shifts before recording money received.</p>
      <div className="payment-summary"><p>Room charges: {money(reservation.roomTotal)} · Bar charges: {money(reservation.barCharges)}</p><p>Total cost: <strong>{money(reservation.total)}</strong></p><p>Amount paid: <strong>{money(reservation.paid)}</strong></p><p>Remaining balance: <strong>{money(reservation.balance)}</strong></p></div>
      <p>Payment status: {reservation.paymentStatus}</p>
      {reservation.credit > 0 && <p><strong>Credit due: {money(reservation.credit)}</strong>. No automatic refund has been issued.</p>}
      {reservation.status === "cancelled" ? <p>This reservation is cancelled. Payment recording is unavailable.</p> : reservation.balance === 0 ? <p>{reservation.credit > 0 ? "No remaining amount to collect. Credit due is shown above." : "Fully paid."}</p> : !canRecord ? <p>Your role can view payment history but cannot record payments.</p> : <form className="reservation-form" onSubmit={reviewPayment}>
        <label>Amount received (TZS)<input name="amount" type="number" min="1" max={reservation.balance} step="1" value={draft.amount} onChange={updateDraft} required disabled={locked || !connected} /></label>
        <label>Payment method<select name="method" value={draft.method} onChange={updateDraft} disabled={locked || !connected}><option value="cash">Cash</option><option value="mobile_money">Mobile money</option></select></label>
        {draft.method === "mobile_money" && <label>Transaction reference<input name="reference" value={draft.reference} onChange={updateDraft} required maxLength={120} disabled={locked || !connected} /></label>}
        <button type="submit" disabled={locked || !connected}>Review payment</button>
      </form>}
      {review && <ConfirmationPrompt busy={saving} onDismiss={()=>setReview(null)} feedback={message} role="group" aria-label="Confirm received payment">
        <p>Record {money(Number(review.amount))} received by {review.method === "cash" ? "Cash" : "Mobile money"} for {reservation.guest}?</p>
        {review.reference && <p>Transaction reference: {review.reference}</p>}
        <button type="button" disabled={saving || !connected} onClick={() => savePayment(review)}>Confirm payment received</button>{" "}
        <button type="button" disabled={saving} onClick={() => setReview(null)}>Go back</button>
      </ConfirmationPrompt>}
      <h3>Payment history</h3>
      <button type="button" disabled={saving || loading || !connected} onClick={refreshHistory}>Refresh history</button>
      {details.payments.length === 0 ? <p>No payments recorded yet.</p> : <div className="table-scroll"><table>
        <caption className="sr-only">Payment receipts</caption>
        <thead><tr><th scope="col">Date and time (Tanzania)</th><th scope="col">Amount</th><th scope="col">Method</th><th scope="col">Transaction reference</th><th scope="col">Received by</th><th scope="col">Receipt</th></tr></thead>
        <tbody>{details.payments.map((item) => <tr key={item.id}><td>{timeInTanzania(item.paidAt)}</td><td>{money(item.amount)}</td><td>{item.method === "cash" ? "Cash" : "Mobile money"}</td><td>{item.reference || "—"}</td><td>{item.receivedBy || "Not recorded"}</td><td><button type="button" disabled={saving || !connected} onClick={() => onReceipt(item.id)}>View receipt</button></td></tr>)}</tbody>
      </table></div>}
    </>}
  </section>;
}


function LoginPanel({ onLogin }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      const result = await api("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
      setPassword(""); onLogin(result.user);
    } catch (error) { setError(error.message); }
    finally { setBusy(false); }
  }
  return <main className="login-main"><section>
    <h1>Kemmon Lodge</h1><h2>Staff login</h2>
    <p>Use the account provided by the owner.</p>
    <form className="account-form" onSubmit={submit}>
      <label>Username<input value={username} onChange={(event) => setUsername(event.target.value)} required maxLength={80} autoComplete="username" disabled={busy} /></label>
      <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} required maxLength={1024} autoComplete="current-password" disabled={busy} /></label>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Log in"}</button>
    </form>
  </section></main>;
}

const hasPermission = (user, permission) => Boolean(user?.isOwner || user?.permissions?.includes(permission));

function StaffRow({ staff, roles, busy, onChange }) {
  const [roleId, setRoleId] = useState(staff.roleId || "");
  useEffect(() => { setRoleId(staff.roleId || ""); }, [staff.roleId]);
  return <tr><td>{staff.username}</td><td>{staff.isOwner ? "Owner" : <label>
    <span className="sr-only">Role for {staff.username}</span>
    <select value={roleId} disabled={busy} onChange={(event) => setRoleId(event.target.value)}>
      {roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
    </select>
  </label>}</td><td>{staff.isActive ? "Active" : "Disabled"}</td><td>{staff.isOwner ? "Owner account" : <div className="reservation-actions">
    <button type="button" disabled={busy || !roleId || roleId === staff.roleId} onClick={() => onChange(staff, roleId, staff.isActive)}>Save role</button>
    <button type="button" disabled={busy} onClick={() => onChange(staff, staff.roleId, !staff.isActive)}>{staff.isActive ? "Disable access" : "Enable access"}</button>
  </div>}</td></tr>;
}

function StaffPanel() {
  const [staff, setStaff] = useState([]);
  const [roles, setRoles] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [draft, setDraft] = useState({ username: "", password: "", confirm: "", roleId: "" });
  const [roleDraft, setRoleDraft] = useState({ id: null, name: "", permissions: [] });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [confirmation, setConfirmation] = useState(null);
  const [roleConfirmation, setRoleConfirmation] = useState(null);

  async function loadStaff() {
    const [accounts, roleDefinitions, permissionDefinitions] = await Promise.all([api("/staff"), api("/roles"), api("/permissions")]);
    setStaff(accounts); setRoles(roleDefinitions); setCatalog(permissionDefinitions);
  }
  useEffect(() => { loadStaff().catch((error) => setMessage(error.message)); }, []);
  const roleName = (id) => roles.find((role) => role.id === id)?.name || "Unknown role";
  const permissionName = (key) => catalog.find((item) => item.key === key)?.label || key;

  function edit(event) {
    setDraft((current) => ({ ...current, [event.target.name]: event.target.value }));
  }
  function togglePermission(permission) {
    setRoleDraft((current) => ({ ...current, permissions: current.permissions.includes(permission)
      ? current.permissions.filter((item) => item !== permission) : [...current.permissions, permission] }));
    setRoleConfirmation(null);
  }
  async function saveRole(definition) {
    if (busy) return;
    setBusy(true); setMessage("");
    try {
      await api(`/roles${definition.id ? `/${definition.id}` : ""}`, {
        method: definition.id ? "PATCH" : "POST",
        body: JSON.stringify({ name: definition.name.trim(), permissions: definition.permissions }),
      });
      setRoleDraft({ id: null, name: "", permissions: [] }); setRoleConfirmation(null);
      await loadStaff();
      setMessage(definition.id ? "Role updated. Assigned staff must log in again to use the updated permissions." : "Custom role created. You can now assign it to staff.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  function submitRole(event) {
    event.preventDefault();
    if (roleDraft.id) setRoleConfirmation({ ...roleDraft, permissions: [...roleDraft.permissions] });
    else saveRole(roleDraft);
  }
  async function create(event) {
    event.preventDefault(); if (busy) return;
    if (draft.password !== draft.confirm) { setMessage("Passwords do not match."); return; }
    setBusy(true); setMessage("");
    try {
      await api("/staff", { method: "POST", body: JSON.stringify({ username: draft.username.trim().toLowerCase(), password: draft.password, roleId: draft.roleId }) });
      setDraft({ username: "", password: "", confirm: "", roleId: "" });
      await loadStaff(); setMessage("Staff account created and active. Share the login details privately.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  async function changeAccess() {
    if (!confirmation || busy) return;
    setBusy(true); setMessage("");
    try {
      await api(`/staff/${confirmation.staff.id}`, { method: "PATCH", body: JSON.stringify({ roleId: confirmation.roleId, isActive: confirmation.active }) });
      setConfirmation(null); await loadStaff();
      setMessage("Access updated. Any affected active sessions have ended.");
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }

  return <section>
    <h2>Staff Management</h2><p>Only the owner can create roles, choose permissions, and decide which staff can log in.</p>
    {message && <p role="status">{message}</p>}
    <h3>{roleDraft.id ? "Edit role" : "Create your own role"}</h3>
    <form className="custom-role-form" onSubmit={submitRole}>
      <label>Role name<input value={roleDraft.name} onChange={(event) => { setRoleDraft((current) => ({ ...current, name: event.target.value })); setRoleConfirmation(null); }} required maxLength={80} placeholder="For example: Night receptionist" disabled={busy} /></label>
      <fieldset disabled={busy}><legend>What can this role do?</legend>
        <div className="permission-grid">{catalog.map((item) => <label className="permission-option" key={item.key}>
          <input type="checkbox" checked={roleDraft.permissions.includes(item.key)} onChange={() => togglePermission(item.key)} />
          <span>{item.label}</span>
        </label>)}</div>
      </fieldset>
      <p>Related viewing permissions are added automatically when saving. Walk-ins require both Create and cancel reservations, and Check guests in and out. A role with no permissions can access only its Account page.</p>
      <div className="reservation-actions"><button type="submit" disabled={busy || !catalog.length}>{roleDraft.id ? "Review role changes" : "Create role"}</button>
        {roleDraft.id && <button type="button" disabled={busy} onClick={() => { setRoleDraft({ id: null, name: "", permissions: [] }); setRoleConfirmation(null); }}>Cancel editing</button>}
      </div>
    </form>
    {roleConfirmation && <ConfirmationPrompt busy={busy} onDismiss={()=>setRoleConfirmation(null)} feedback={message} role="group" aria-label="Confirm role changes">
      <p>Update “{roleConfirmation.name}” for all staff assigned to this role? Their active sessions will end.</p>
      <p>Selected permissions: {roleConfirmation.permissions.map(permissionName).join(", ") || "Account access only"}.</p>
      <button type="button" disabled={busy} onClick={() => saveRole(roleConfirmation)}>Confirm role changes</button>{" "}
      <button type="button" disabled={busy} onClick={() => setRoleConfirmation(null)}>Go back</button>
    </ConfirmationPrompt>}
    <h3>Your roles</h3>
    <p>The original roles have been kept so existing staff retain their access. You can rename or change them.</p>
    <div className="role-list">{roles.map((role) => <article key={role.id} className="role-card">
      <h4>{role.name}</h4><p>{role.permissions.map(permissionName).join(" · ") || "Account access only"}</p>
      <button type="button" disabled={busy} onClick={() => { setRoleDraft({ ...role, permissions: [...role.permissions] }); setRoleConfirmation(null); }}>Edit {role.name}</button>
    </article>)}</div>
    <h3>Create staff account</h3>
    <form className="reservation-form" onSubmit={create}>
      <label>Username<input name="username" value={draft.username} onChange={edit} required minLength={3} maxLength={80} pattern="[a-z0-9][a-z0-9._-]*" autoComplete="off" disabled={busy} /></label>
      <label>Your role<select name="roleId" value={draft.roleId} onChange={edit} required disabled={busy}>
        <option value="">Choose a role you created</option>{roles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
      </select></label>
      <label>Initial password<input name="password" type="password" value={draft.password} onChange={edit} required minLength={12} maxLength={1024} autoComplete="new-password" disabled={busy} /></label>
      <label>Confirm password<input name="confirm" type="password" value={draft.confirm} onChange={edit} required minLength={12} maxLength={1024} autoComplete="new-password" disabled={busy} /></label>
      <p>Passwords must contain at least 12 characters. Staff can change their own password under Account.</p>
      <button type="submit" disabled={busy}>Create account</button>
    </form>
    <h3>Staff accounts</h3>
    {confirmation && <ConfirmationPrompt busy={busy} onDismiss={()=>setConfirmation(null)} feedback={message} role="group" aria-label="Confirm staff access change">
      <p>Set {confirmation.staff.username} to “{roleName(confirmation.roleId)}”, {confirmation.active ? "active" : "disabled"}?</p>
      <button type="button" disabled={busy} onClick={changeAccess}>Confirm access change</button>{" "}
      <button type="button" disabled={busy} onClick={() => setConfirmation(null)}>Go back</button>
    </ConfirmationPrompt>}
    <div className="table-scroll"><table><caption className="sr-only">Owner-managed staff accounts</caption>
      <thead><tr><th scope="col">Username</th><th scope="col">Role</th><th scope="col">Access</th><th scope="col">Action</th></tr></thead>
      <tbody>{staff.map((item) => <StaffRow key={item.id} staff={item} roles={roles} busy={busy} onChange={(staff, roleId, active) => setConfirmation({ staff, roleId, active })} />)}</tbody>
    </table></div>
  </section>;
}


function AccountPanel({ user, onPasswordChanged }) {
  const [currentPassword, setCurrent] = useState("");
  const [newPassword, setNew] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function submit(event) {
    event.preventDefault(); if (busy) return;
    if (newPassword !== confirm) { setMessage("New passwords do not match."); return; }
    setBusy(true); setMessage("");
    try {
      await api("/auth/password", { method: "POST", body: JSON.stringify({ currentPassword, newPassword }) });
      setCurrent(""); setNew(""); setConfirm(""); onPasswordChanged();
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <section><h2>Account</h2><p>{user.username} · {user.roleName}</p>
    <form className="account-form" onSubmit={submit}>
      <h3>Change your password</h3>
      <label>Current password<input type="password" value={currentPassword} onChange={(event) => setCurrent(event.target.value)} required maxLength={1024} autoComplete="current-password" disabled={busy} /></label>
      <label>New password<input type="password" value={newPassword} onChange={(event) => setNew(event.target.value)} required minLength={12} maxLength={1024} autoComplete="new-password" disabled={busy} /></label>
      <label>Confirm new password<input type="password" value={confirm} onChange={(event) => setConfirm(event.target.value)} required minLength={12} maxLength={1024} autoComplete="new-password" disabled={busy} /></label>
      <p>Changing your password signs out all your sessions. Log in again with the new password.</p>
      {message && <p role="status">{message}</p>}
      <button type="submit" disabled={busy}>Change password and sign out</button>
    </form>
  </section>;
}


function CollectionsReport({ onReceipt }) {
  const today = lodgeToday();
  const [filters, setFilters] = useState({ startDate: today, endDate: today });
  const [report, setReport] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function fetchReport(dates, page = 1, debtPage = 1) {
    if (busy) return;
    if (!dates.startDate || !dates.endDate || dates.endDate < dates.startDate) {
      setError("Choose an end date on or after the start date.");
      return;
    }
    setBusy(true); setError("");
    try {
      const params = new URLSearchParams({ start_date: dates.startDate, end_date: dates.endDate,
        page: String(page), debt_page: String(debtPage), page_size: "50" });
      const result = await api(`/reports/collections?${params}`);
      setReport(result);
    } catch (error) {
      setReport(null); setError(error.message);
    } finally { setBusy(false); }
  }
  useEffect(() => { fetchReport({ startDate: today, endDate: today }); }, []);

  function changeDate(event) {
    setFilters((current) => ({ ...current, [event.target.name]: event.target.value }));
  }
  const loadedDates = report ? { startDate: report.startDate, endDate: report.endDate } : null;

  return <section>
    <h2>Daily Collections Report</h2>
    <p>Collections use the date money was received, in Tanzania time. Both selected dates are included.</p>
    <form className="reservation-form report-filters" onSubmit={(event) => { event.preventDefault(); fetchReport(filters); }}>
      <label>From date<input name="startDate" type="date" value={filters.startDate} onChange={changeDate} required disabled={busy} /></label>
      <label>To date<input name="endDate" type="date" min={filters.startDate || undefined} value={filters.endDate} onChange={changeDate} required disabled={busy} /></label>
      <button type="submit" disabled={busy}>{busy ? "Loading…" : "View report"}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    {busy && <p role="status">Loading report…</p>}
    {report && <div aria-busy={busy}>
      <h3>Collections: {report.startDate} to {report.endDate}</h3>
      <p>{report.receiptCount} payment receipt{report.receiptCount === 1 ? "" : "s"} · Updated {timeInTanzania(report.asOf)}</p>
      <div className="report-summary">
        <article><h4>Cash collected</h4><p>{money(report.cash)}</p></article>
        <article><h4>Mobile money collected</h4><p>{money(report.mobileMoney)}</p></article>
        <article><h4>Total collected</h4><p>{money(report.total)}</p></article>
      </div>
      <h3>Collections by staff member</h3>
      {report.staff.length === 0 ? <p>No collections in this date range.</p> : <div className="table-scroll"><table>
        <caption className="sr-only">Collections by receiving staff member for the selected dates</caption>
        <thead><tr><th scope="col">Staff member</th><th scope="col">Cash</th><th scope="col">Mobile money</th><th scope="col">Total</th><th scope="col">Receipts</th></tr></thead>
        <tbody>{report.staff.map((item) => <tr key={item.id || "unassigned"}><td>{item.username}</td><td>{money(item.cash)}</td><td>{money(item.mobileMoney)}</td><td>{money(item.total)}</td><td>{item.receiptCount}</td></tr>)}</tbody>
      </table></div>}
      <h3>Individual receipts</h3>
      <p>Totals above include every matching receipt, across all pages.</p>
      {report.receipts.length === 0 ? <p>No receipts on this page.</p> : <div className="table-scroll"><table>
        <caption className="sr-only">Individual payment receipts for the selected dates</caption>
        <thead><tr>{["Received (Tanzania)", "Guest", "Room", "Method", "Amount", "Reference", "Received by", "Receipt ID", "Receipt"].map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{report.receipts.map((item) => <tr key={item.id}><td>{timeInTanzania(item.paidAt)}</td><td>{item.guest}</td><td>{item.roomNumber}</td><td>{item.method === "cash" ? "Cash" : "Mobile money"}</td><td>{money(item.amount)}</td><td>{item.reference || "—"}</td><td>{item.receivedBy}</td><td className="receipt-id">{item.id}</td><td><button type="button" disabled={busy} onClick={() => onReceipt(item.id)}>View receipt</button></td></tr>)}</tbody>
      </table></div>}
      <div className="report-pagination" aria-label="Receipt pages">
        <button type="button" disabled={busy || report.page <= 1} onClick={() => fetchReport(loadedDates, report.page - 1, report.outstanding.page)}>Previous receipts</button>
        <span>Page {report.page} of {report.pageCount}</span>
        <button type="button" disabled={busy || report.page >= report.pageCount} onClick={() => fetchReport(loadedDates, report.page + 1, report.outstanding.page)}>Next receipts</button>
      </div>
      <h3>Current outstanding guest balances</h3>
      <p>As of {timeInTanzania(report.outstanding.asOf)}, across all non-cancelled reservations, including future bookings. This section is not filtered by the collection dates above.</p>
      <p><strong>Total outstanding: {money(report.outstanding.totalBalance)}</strong> · {report.outstanding.count} reservation{report.outstanding.count === 1 ? "" : "s"}</p>
      {report.outstanding.reservations.length === 0 ? <p>No outstanding balances on this page.</p> : <div className="table-scroll"><table>
        <caption className="sr-only">Current outstanding balances for all non-cancelled reservations</caption>
        <thead><tr>{["Guest", "Phone", "Guests", "Room", "Arrival", "Departure", "Stay status", "Total cost", "Paid", "Balance"].map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{report.outstanding.reservations.map((item) => <tr key={item.id}><td>{item.guest}</td><td>{item.phone}</td><td>{item.roomNumber}</td><td>{item.checkIn}</td><td>{item.checkOut}</td><td>{statusLabels[item.status] || item.status}</td><td>{money(item.total)}</td><td>{money(item.paid)}</td><td>{money(item.balance)}</td></tr>)}</tbody>
      </table></div>}
      <div className="report-pagination" aria-label="Outstanding balance pages">
        <button type="button" disabled={busy || report.outstanding.page <= 1} onClick={() => fetchReport(loadedDates, report.page, report.outstanding.page - 1)}>Previous balances</button>
        <span>Page {report.outstanding.page} of {report.outstanding.pageCount}</span>
        <button type="button" disabled={busy || report.outstanding.page >= report.outstanding.pageCount} onClick={() => fetchReport(loadedDates, report.page, report.outstanding.page + 1)}>Next balances</button>
      </div>
    </div>}
  </section>;
}


function StayExtensionDialog({ reservation, canExtend, onUpdated, onClose }) {
  const dialogRef = useRef(null);
  const [current, setCurrent] = useState(reservation);
  const [departure, setDeparture] = useState("");
  const [reason, setReason] = useState("");
  const [review, setReview] = useState(null);
  const [history, setHistory] = useState([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [historyError, setHistoryError] = useState("");
  const editable = canExtend && ["confirmed", "checked_in"].includes(current.status);
  const units = chargeUnits(current.checkIn, departure);
  const newTotal = current.total + (units - current.billableUnits) * current.nightlyRate;
  const nextDate = new Date(Date.parse(`${current.checkOut}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);
  const minDeparture = nextDate > lodgeToday() ? nextDate : lodgeToday();

  useEffect(() => {
    const dialog = dialogRef.current; dialog.showModal();
    return () => { if (dialog.open) dialog.close(); };
  }, []);
  useEffect(() => {
    let ignore = false;
    api(`/reservations/${reservation.id}/extensions`).then((data) => {
      if (!ignore) setHistory(data);
    }).catch((error) => { if (!ignore) setHistoryError(error.message); });
    return () => { ignore = true; };
  }, [reservation.id]);

  function preview(event) {
    event.preventDefault();
    if (busy || !editable) return;
    if (!departure || departure <= current.checkOut || departure < lodgeToday() || !reason.trim()) {
      setMessage("Choose a later departure date and enter the reason for extending."); return;
    }
    setMessage("");
    setReview({ requestId: crypto.randomUUID(), expectedCheckOut: current.checkOut,
      newCheckOut: departure, reason: reason.trim() });
  }
  async function save() {
    if (!review || busy) return;
    setBusy(true); setMessage("");
    try {
      const result = await api(`/reservations/${current.id}/extend`, { method: "POST", body: JSON.stringify(review) });
      setCurrent(result.reservation);
      setHistory((items) => [result.extension, ...items.filter((item) => item.id !== result.extension.id)]);
      setReview(null); setDeparture(""); setReason("");
      setMessage(`Stay extended to ${result.reservation.checkOut}. Total: ${money(result.reservation.total)}. Remaining balance: ${money(result.reservation.balance)}.`);
      await onUpdated();
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }

  return createPortal(<dialog ref={dialogRef} className="stay-extension-dialog" aria-labelledby="extension-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="extension-toolbar"><h2 id="extension-title">Stay extension and history</h2><button type="button" disabled={busy} onClick={onClose}>Close</button></div>
    <div className="extension-content">
      <h3>{current.guest} · Room {current.roomNumber}</h3>
      <p>Arrival: {current.checkIn} · Current departure: {current.checkOut}</p>
      <p>Agreed room rate: {money(current.nightlyRate)} · Current total: {money(current.total)} · Paid: {money(current.paid)}</p>
      {message && <p role="status">{message}</p>}
      {editable && <form className="account-form" onSubmit={preview}>
        <label>New departure date<input type="date" min={minDeparture} value={departure} onChange={(event) => { setDeparture(event.target.value); setReview(null); }} required disabled={busy} /></label>
        <label>Reason for extension<textarea value={reason} onChange={(event) => { setReason(event.target.value); setReview(null); }} required maxLength={500} disabled={busy} /></label>
        <p>The agreed rate and recorded payments stay unchanged. We check room availability before saving. This action extends the stay; it does not shorten it.</p>
        {departure > current.checkOut && <div className="extension-costs">
          <p>New stay total: <strong>{money(newTotal)}</strong></p>
          <p>Additional cost: <strong>{money(newTotal - current.total)}</strong></p>
          <p>New balance based on payments shown above: <strong>{money(Math.max(0,newTotal - current.paid))}</strong></p>
          <p className="receipt-note">A same-day stay already costs one room rate. Extending it to the following day adds no charge; longer stays are charged per night.</p>
        </div>}
        <button type="submit" disabled={busy}>Review extension</button>
      </form>}
      {review && editable && <ConfirmationPrompt busy={busy} onDismiss={()=>setReview(null)} feedback={message} role="group" aria-label="Confirm stay extension">
        <p>Extend departure from {review.expectedCheckOut} to {review.newCheckOut}? New total: {money(newTotal)}.</p>
        <button type="button" disabled={busy} onClick={save}>{busy ? "Saving…" : "Confirm extension"}</button>{" "}
        <button type="button" disabled={busy} onClick={() => setReview(null)}>Go back</button>
      </ConfirmationPrompt>}
      {!editable && <p>{canExtend ? "Completed and cancelled stays cannot be extended." : "Your role can view history but cannot extend stays."}</p>}
      <h3>Extension history</h3>
      {historyError && <p role="alert">{historyError}</p>}
      {history.length === 0 ? <p>No extensions recorded.</p> : <div className="table-scroll"><table>
        <caption className="sr-only">Reservation departure extension history</caption>
        <thead><tr>{["Changed (Tanzania)", "Staff", "Old departure", "New departure", "Additional cost", "Reason"].map((label) => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{history.map((item) => <tr key={item.id}><td>{timeInTanzania(item.changedAt)}</td><td>{item.changedBy}</td><td>{item.oldCheckOut}</td><td>{item.newCheckOut}</td><td>{money(item.additionalCost)}</td><td className="extension-reason">{item.reason}</td></tr>)}</tbody>
      </table></div>}
    </div>
  </dialog>, document.body);
}


function RoomTransferDialog({ reservation, canTransfer, onUpdated, onClose }) {
  const dialogRef = useRef(null);
  const [current, setCurrent] = useState(reservation);
  const [options, setOptions] = useState([]);
  const [history, setHistory] = useState([]);
  const [targetId, setTargetId] = useState("");
  const [reason, setReason] = useState("");
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const quote = options.find((item) => String(item.targetRoomId) === targetId);
  const editable = canTransfer && current.status === "checked_in";
  async function refresh() {
    setBusy(true); setMessage("");
    try {
      setHistory(await api(`/reservations/${current.id}/transfers`));
      if (canTransfer && current.status === "checked_in") {
        const data = await api(`/reservations/${current.id}/transfer-options`);
        setCurrent(data.reservation); setOptions(data.options); setTargetId(""); setReview(null);
      }
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  useEffect(() => { const dialog = dialogRef.current; dialog.showModal(); return () => { if (dialog.open) dialog.close(); }; }, []);
  useEffect(() => { refresh(); }, []);
  function preview(event) {
    event.preventDefault(); if (!quote || !reason.trim() || busy) return;
    setReview({ requestId: crypto.randomUUID(), expectedRoomId: current.roomId,
      targetRoomId: quote.targetRoomId, quoteVersion: quote.quoteVersion, reason: reason.trim() });
  }
  async function save() {
    if (!review || busy) return;
    setBusy(true); setMessage("");
    try {
      const data = await api(`/reservations/${current.id}/transfer`, { method: "POST", body: JSON.stringify(review) });
      setCurrent(data.reservation); setOptions([]); setReview(null); setTargetId(""); setReason("");
      setHistory((items) => [data.transfer, ...items.filter((item) => item.id !== data.transfer.id)]);
      setMessage(`Transferred to Room ${data.reservation.roomNumber}. Total ${money(data.reservation.total)}; balance ${money(data.reservation.balance)}${data.reservation.credit ? `; credit due ${money(data.reservation.credit)}` : ""}. Old room needs cleaning.`);
      await onUpdated();
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return createPortal(<dialog ref={dialogRef} className="stay-extension-dialog" aria-labelledby="transfer-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <div className="extension-toolbar"><h2 id="transfer-title">Room transfer and history</h2><button type="button" onClick={onClose} disabled={busy}>Close</button></div>
    <div className="extension-content"><h3>{current.guest} · Room {current.roomNumber}</h3><p>Departure: {current.checkOut} · Current total: {money(current.total)}</p>
      {message && <p role="status">{message}</p>}
      {editable && <>
        <button type="button" disabled={busy} onClick={refresh}>Refresh available rooms</button>
        <form className="account-form" onSubmit={preview}>
          <label>New room<select value={targetId} onChange={(event) => { setTargetId(event.target.value); setReview(null); }} required disabled={busy}>
            <option value="">Choose a clean, available room</option>{options.map((item) => <option key={item.targetRoomId} value={item.targetRoomId}>Room {item.roomNumber} — usual rate {money(item.usualRate)}</option>)}
          </select></label>
          <label>Reason<textarea value={reason} onChange={(event) => { setReason(event.target.value); setReview(null); }} required maxLength={500} disabled={busy} /></label>
          {quote && <div className="extension-costs"><p>New rate for the remaining stay: <strong>{money(quote.newRate)}</strong></p><p>Bill change: <strong>{money(quote.priceChange)}</strong></p><p>New stay total: <strong>{money(quote.newTotal)}</strong></p><p>New balance: {money(Math.max(0, quote.newTotal - current.paid))}</p>
            {current.paid > quote.newTotal && <p><strong>Credit due: {money(current.paid - quote.newTotal)}</strong>. No automatic refund will be issued.</p>}
            <p>Same-priced rooms keep the agreed rate. Different-priced rooms use the new room rate for the remaining stay. Earlier charges and all payments are preserved.</p></div>}
          <button type="submit" disabled={busy || !quote}>Review transfer</button>
        </form>
        {options.length === 0 && !busy && <p>No target rooms loaded. Refresh availability or extend an overnight stay that is due to depart today.</p>}
      </>}
      {review && quote && <ConfirmationPrompt busy={busy} onDismiss={()=>setReview(null)} feedback={message}><p>Move {current.guest} to Room {quote.roomNumber}, with a new total of {money(quote.newTotal)}?</p><button type="button" disabled={busy} onClick={save}>Confirm transfer</button>{" "}<button type="button" disabled={busy} onClick={() => setReview(null)}>Go back</button></ConfirmationPrompt>}
      <h3>Transfer history</h3>{history.length === 0 ? <p>No transfers recorded.</p> : <div className="table-scroll"><table><thead><tr>{["Time (Tanzania)", "From", "To", "New rate", "Bill change", "Staff", "Reason"].map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{history.map((item) => <tr key={item.id}><td>{timeInTanzania(item.changedAt)}</td><td>{item.fromRoom}</td><td>{item.toRoom}</td><td>{money(item.newRate)}</td><td>{money(item.priceChange)}</td><td>{item.changedBy}</td><td>{item.reason}</td></tr>)}</tbody></table></div>}
    </div>
  </dialog>, document.body);
}

const pendingExpenseKey = "kemmon-pending-expense-v1";
function readPendingExpense() { try { return JSON.parse(sessionStorage.getItem(pendingExpenseKey) || "null"); } catch { return null; } }
function ExpensesPanel({ canRecord }) {
  const today = lodgeToday();
  const [filters, setFilters] = useState({ start: today, end: today });
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({ paidOn: today, category: "", description: "", amount: "", method: "cash", reference: "" });
  const [pending, setPending] = useState(readPendingExpense);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function load(dates = filters, page = 1) {
    if (!dates.start || !dates.end || dates.end < dates.start) { setMessage("Choose a valid date range."); return; }
    setBusy(true);
    try { setData(await api(`/expenses?${new URLSearchParams({ start_date: dates.start, end_date: dates.end, page: String(page) })}`)); }
    catch (error) { setData(null); setMessage(error.message); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, []);
  function edit(event) { const { name, value } = event.target; setDraft((current) => ({ ...current, [name]: value, ...(name === "method" ? { reference: "" } : {}) })); setReview(null); }
  function preview(event) {
    event.preventDefault(); if (busy || pending || !canRecord) return;
    if (!/^\d+$/.test(draft.amount) || Number(draft.amount) <= 0) { setMessage("Enter a positive whole TZS amount."); return; }
    setReview({ ...draft, category: draft.category.trim(), description: draft.description.trim(), reference: draft.method === "mobile_money" ? draft.reference.trim().toUpperCase() : null, requestId: crypto.randomUUID() });
  }
  async function save(receipt) {
    if (busy || !canRecord) return;
    setBusy(true); setMessage("");
    try {
      sessionStorage.setItem(pendingExpenseKey, JSON.stringify(receipt)); setPending(receipt); setReview(null);
      await api("/expenses", { method: "POST", body: JSON.stringify(receipt) });
      sessionStorage.removeItem(pendingExpenseKey); setPending(null);
      setDraft({ paidOn: today, category: "", description: "", amount: "", method: "cash", reference: "" });
      const dates = { start: receipt.paidOn, end: receipt.paidOn }; setFilters(dates);
      setData(await api(`/expenses?${new URLSearchParams({ start_date: dates.start, end_date: dates.end })}`));
      setMessage("Paid expense recorded.");
    } catch (error) {
      if (error.status >= 400 && error.status < 500 && ![401, 403].includes(error.status)) { sessionStorage.removeItem(pendingExpenseKey); setPending(null); setMessage(error.message); }
      else setMessage(`Could not confirm the expense save. Retry the same saved expense. ${error.message}`);
    } finally { setBusy(false); }
  }
  return <section><h2>Expenses</h2><p>Record expenses already paid. Cash and Mobile money are kept separate. Records cannot be edited or deleted here. Open your cashier shift before recording today’s paid expenses. Earlier paid dates are kept outside the current shift.</p>
    {message && <p role="status">{message}</p>}
    {pending && canRecord && <div className="action-confirmation"><p>Finish confirming the saved expense: {pending.category}, {money(Number(pending.amount))}.</p><button type="button" disabled={busy} onClick={() => save(pending)}>Retry same expense</button></div>}
    {canRecord && !pending && <form className="reservation-form" onSubmit={preview}>
      <label>Date paid<input type="date" name="paidOn" max={today} value={draft.paidOn} onChange={edit} required disabled={busy} /></label>
      <label>Category<input name="category" value={draft.category} onChange={edit} required maxLength={80} placeholder="For example: Electricity" disabled={busy} /></label>
      <label>Description<input name="description" value={draft.description} onChange={edit} required maxLength={500} disabled={busy} /></label>
      <label>Amount (TZS)<input type="number" min="1" step="1" name="amount" value={draft.amount} onChange={edit} required disabled={busy} /></label>
      <label>Paid using<select name="method" value={draft.method} onChange={edit} disabled={busy}><option value="cash">Cash</option><option value="mobile_money">Mobile money</option></select></label>
      {draft.method === "mobile_money" && <label>Transaction reference<input name="reference" value={draft.reference} onChange={edit} required maxLength={120} disabled={busy} /></label>}
      <button type="submit" disabled={busy}>Review expense</button>
    </form>}
    {review && <ConfirmationPrompt busy={busy} onDismiss={()=>setReview(null)} feedback={message}><p>Record {review.category}: {money(Number(review.amount))}, paid by {review.method === "cash" ? "Cash" : "Mobile money"} on {review.paidOn}?</p><button type="button" disabled={busy} onClick={() => save(review)}>Confirm paid expense</button>{" "}<button type="button" disabled={busy} onClick={() => setReview(null)}>Go back</button></ConfirmationPrompt>}
    <h3>Expense history</h3><form className="reservation-form report-filters" onSubmit={(event) => { event.preventDefault(); load(filters); }}>
      <label>From<input type="date" value={filters.start} onChange={(event) => setFilters((current) => ({ ...current, start: event.target.value }))} required disabled={busy} /></label>
      <label>To<input type="date" min={filters.start} value={filters.end} onChange={(event) => setFilters((current) => ({ ...current, end: event.target.value }))} required disabled={busy} /></label><button type="submit" disabled={busy}>View expenses</button>
    </form>
    {data && <><p>{data.startDate} to {data.endDate} · Cash: {money(data.cash)} · Mobile money: {money(data.mobileMoney)} · Total: {money(data.total)}</p>
      <div className="table-scroll"><table><thead><tr>{["Date paid", "Category", "Description", "Amount", "Method", "Reference", "Recorded by"].map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{data.expenses.map((item) => <tr key={item.id}><td>{item.paidOn}</td><td>{item.category}</td><td>{item.description}</td><td>{money(item.amount)}</td><td>{item.method === "cash" ? "Cash" : "Mobile money"}</td><td>{item.reference || "—"}</td><td>{item.recordedBy}</td></tr>)}</tbody></table></div>
      {data.count === 0 && <p>No expenses for these dates.</p>}<div className="report-pagination"><button type="button" disabled={busy || data.page <= 1} onClick={() => load({ start: data.startDate, end: data.endDate }, data.page - 1)}>Previous</button><span>Page {data.page} of {data.pageCount}</span><button type="button" disabled={busy || data.page >= data.pageCount} onClick={() => load({ start: data.startDate, end: data.endDate }, data.page + 1)}>Next</button></div>
    </>}
  </section>;
}

function CashSummaryPanel({ canManage }) {
  const [day, setDay] = useState(lodgeToday());
  const [data, setData] = useState(null);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  async function load(selected = day) {
    setBusy(true); setMessage(""); setReview(null);
    try { setData(await api(`/cash/summary?day=${encodeURIComponent(selected)}`)); setAmount(""); setReason(""); }
    catch (error) { setData(null); setMessage(error.message); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(); }, []);
  function preview(event) {
    event.preventDefault(); if (!data || !canManage || busy) return;
    if (!/^\d+$/.test(amount)) { setMessage("Enter a whole TZS opening amount, including zero if applicable."); return; }
    setReview({ requestId: crypto.randomUUID(), day: data.day, amount, expectedAmount: data.openingCash, reason: reason.trim() });
  }
  async function save() {
    if (!review || busy) return;
    setBusy(true); setMessage("");
    try { await api("/cash/opening", { method: "POST", body: JSON.stringify(review) }); setData(await api(`/cash/summary?day=${review.day}`)); setReview(null); setAmount(""); setReason(""); setMessage("Opening cash saved with an audit entry."); }
    catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <section><h2>Daily cash summary</h2><p>Expected cash on hand = opening cash + cash collected − cash expenses paid. Enter each day’s opening cash explicitly; it is not carried forward automatically.</p>
    <form className="reservation-form report-filters" onSubmit={(event) => { event.preventDefault(); load(day); }}><label>Date (Tanzania)<input type="date" value={day} onChange={(event) => setDay(event.target.value)} required disabled={busy} /></label><button type="submit" disabled={busy}>View summary</button></form>
    {message && <p role="status">{message}</p>}
    {data && <><h3>{data.day}</h3><div className="report-summary">
      <article><h4>Opening cash</h4><p>{data.openingCash === null ? "Not set" : money(data.openingCash)}</p></article><article><h4>Cash collected</h4><p>{money(data.cashCollected)}</p></article><article><h4>Cash expenses</h4><p>{money(data.cashExpenses)}</p></article><article><h4>Expected cash on hand</h4><p>{data.expectedCash === null ? "Set opening cash" : money(data.expectedCash)}</p></article>
    </div><p>Net cash movement: {money(data.cashMovement)}. Compare expected cash with the cash actually counted; unrecorded withdrawals or refunds are not included.</p>
      <h3>Mobile money — separate from cash</h3><p>Collected: {money(data.mobileCollected)} · Expenses: {money(data.mobileExpenses)} · Net movement: {money(data.mobileMovement)}</p>
      {canManage && <form className="account-form" onSubmit={preview}><h3>{data.openingCash === null ? "Set" : "Correct"} opening cash for {data.day}</h3><label>Opening cash (TZS)<input type="number" min="0" step="1" value={amount} onChange={(event) => { setAmount(event.target.value); setReview(null); }} required disabled={busy} /></label><label>Reason<input value={reason} onChange={(event) => { setReason(event.target.value); setReview(null); }} required maxLength={500} disabled={busy} /></label><button type="submit" disabled={busy}>Review opening cash</button></form>}
      {review && <ConfirmationPrompt busy={busy} onDismiss={()=>setReview(null)} feedback={message}><p>Set opening cash for {review.day} to {money(Number(review.amount))}?</p><button type="button" disabled={busy} onClick={save}>Confirm opening cash</button>{" "}<button type="button" disabled={busy} onClick={() => setReview(null)}>Go back</button></ConfirmationPrompt>}
      <h3>Opening cash history</h3>{data.changes.length === 0 ? <p>No opening cash entered.</p> : <div className="table-scroll"><table><thead><tr>{["Changed (Tanzania)", "Previous", "New opening", "Staff", "Reason"].map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{data.changes.map((item) => <tr key={item.id}><td>{timeInTanzania(item.changedAt)}</td><td>{item.previousAmount === null ? "Not set" : money(item.previousAmount)}</td><td>{money(item.amount)}</td><td>{item.changedBy}</td><td>{item.reason}</td></tr>)}</tbody></table></div>}
    </>}
  </section>;
}


function MaintenancePanel({ rooms, canManage, onUpdated }) {
  const [state, setState] = useState("open");
  const [data, setData] = useState(null);
  const [draft, setDraft] = useState({ roomId: "", title: "", description: "" });
  const [notes, setNotes] = useState({});
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const eligible = rooms.filter((room) => !room.taken && room.maintenanceStatus === "available");
  async function load(selected = state, page = 1) {
    setBusy(true);
    try { setData(await api(`/maintenance?${new URLSearchParams({ state: selected, page: String(page) })}`)); }
    catch (error) { setData(null); setMessage(error.message); }
    finally { setBusy(false); }
  }
  useEffect(() => { load(state); }, [state]);
  function edit(event) { setDraft((current) => ({ ...current, [event.target.name]: event.target.value })); setReview(null); }
  function preview(event) {
    event.preventDefault(); if (busy || !canManage) return;
    if (!draft.title.trim() || !draft.description.trim()) { setMessage("Enter the issue title and description."); return; }
    setReview({ action: "report", requestId: crypto.randomUUID(), ...draft, title: draft.title.trim(), description: draft.description.trim() });
  }
  async function save() {
    if (!review || busy || !canManage) return;
    setBusy(true); setMessage("");
    try {
      if (review.action === "report") {
        await api("/maintenance", { method: "POST", body: JSON.stringify({ requestId: review.requestId, roomId: Number(review.roomId), title: review.title, description: review.description }) });
        setDraft({ roomId: "", title: "", description: "" });
        setMessage("Room marked out of service. Existing affected bookings are flagged in Reservations.");
      } else {
        await api(`/maintenance/${review.issueId}/resolve`, { method: "POST", body: JSON.stringify({ requestId: review.requestId, notes: review.notes }) });
        setNotes((current) => ({ ...current, [review.issueId]: "" }));
        setMessage("Repairs completed. The room still needs cleaning before it can be used.");
      }
      setReview(null); await onUpdated();
      const updated = await api(`/maintenance?${new URLSearchParams({ state, page: "1" })}`); setData(updated);
    } catch (error) { setMessage(error.message); }
    finally { setBusy(false); }
  }
  return <section><h2>Room maintenance</h2>
    <p>Out-of-service rooms cannot accept new bookings, walk-ins, check-ins or incoming room transfers. Existing bookings stay saved and are flagged for attention.</p>
    {message && <p role="status">{message}</p>}
    {canManage && <form className="reservation-form" onSubmit={preview}>
      <label>Room<select name="roomId" value={eligible.some((room) => String(room.id) === draft.roomId) ? draft.roomId : ""} onChange={edit} required disabled={busy}>
        <option value="">Choose an unoccupied room</option>{eligible.map((room) => <option key={room.id} value={room.id}>{room.name}</option>)}
      </select></label>
      <label>Issue title<input name="title" value={draft.title} onChange={edit} required maxLength={200} placeholder="For example: Air conditioner needs repair" disabled={busy} /></label>
      <label>Issue description<textarea name="description" value={draft.description} onChange={edit} required maxLength={1000} disabled={busy} /></label>
      <button type="submit" disabled={busy}>Review out-of-service status</button>
    </form>}
    {review && <ConfirmationPrompt busy={busy} onDismiss={()=>setReview(null)} feedback={message} role="group" aria-label="Confirm maintenance action">
      <p>{review.action === "report" ? `Mark ${rooms.find((room) => String(room.id) === review.roomId)?.name || "this room"} out of service for “${review.title}”?` : `Mark repairs completed for Room ${review.roomNumber}? The room will still need cleaning.`}</p>
      <button type="button" disabled={busy} onClick={save}>Confirm</button>{" "}<button type="button" disabled={busy} onClick={() => setReview(null)}>Go back</button>
    </ConfirmationPrompt>}
    <h3>Maintenance history</h3>
    <div className="maintenance-filters"><label>Show issues<select value={state} onChange={(event) => { setState(event.target.value); setReview(null); }} disabled={busy}><option value="open">Open</option><option value="resolved">Repairs completed</option><option value="all">All issues</option></select></label><button type="button" disabled={busy} onClick={() => load(state)}>Refresh issues</button></div>
    {data && <><p>{data.count} issue{data.count === 1 ? "" : "s"}</p>
      {data.issues.length === 0 ? <p>No maintenance issues in this view.</p> : <div className="maintenance-list">{data.issues.map((issue) => <article className="maintenance-card" key={issue.id}>
        <h4>Room {issue.roomNumber} · {issue.title}</h4><p>{issue.description}</p><p>Reported by {issue.reportedBy} · {timeInTanzania(issue.reportedAt)}</p>
        {issue.resolvedAt ? <><p><strong>Repairs completed</strong> by {issue.resolvedBy} · {timeInTanzania(issue.resolvedAt)}</p><p>{issue.resolutionNotes}</p></> : <>
          <p className="maintenance-warning"><strong>Out of service</strong> · {issue.affectedBookings} existing booking{issue.affectedBookings === 1 ? "" : "s"} affected. Reservations are not automatically cancelled or moved.</p>
          {canManage && <div className="account-form"><label>Repairs completed / resolution notes<textarea value={notes[issue.id] || ""} onChange={(event) => { setNotes((current) => ({ ...current, [issue.id]: event.target.value })); setReview(null); }} maxLength={1000} disabled={busy} /></label>
            <button type="button" disabled={busy || !(notes[issue.id] || "").trim()} onClick={() => setReview({ action: "resolve", issueId: issue.id, roomNumber: issue.roomNumber, requestId: crypto.randomUUID(), notes: notes[issue.id].trim() })}>Review repair completion</button>
          </div>}
        </>}
      </article>)}</div>}
      <div className="report-pagination"><button type="button" disabled={busy || data.page <= 1} onClick={() => load(data.state, data.page - 1)}>Previous</button><span>Page {data.page} of {data.pageCount}</span><button type="button" disabled={busy || data.page >= data.pageCount} onClick={() => load(data.state, data.page + 1)}>Next</button></div>
    </>}
  </section>;
}


export default function App() {
  useConfirmationAnchors();
  const [transferReservation, setTransferReservation] = useState(null);
  const [editingReservation,setEditingReservation]=useState(null);
  const [extensionReservation, setExtensionReservation] = useState(null);
  const [receiptId, setReceiptId] = useState(null);
  const [user, setUser] = useState(null);
  const [alertCount,setAlertCount]=useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authMessage, setAuthMessage] = useState("");
  const [paymentReservationId, setPaymentReservationId] = useState(() => readPendingPayment()?.reservationId || "");
  const [page, setPage] = useState("Dashboard");
  const [rooms, setRooms] = useState([]);
  const [reservations, setReservations] = useState([]);
  const [reservationFilters, setReservationFilters] = useState({ search: "", status: "all", payment: "all", dates: "all" });
  const [booking, setBooking] = useState(emptyBooking);
  const [connected, setConnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [notice, setNotice] = useState("");
  const [walkIn, setWalkIn] = useState(emptyWalkIn);
  const [walkInReview, setWalkInReview] = useState(null);
  const [pendingConfirmation, setPendingConfirmation] = useState(null);

  useEffect(()=>{
    if(!hasPermission(user,"alerts.view")){setAlertCount(null);return;}
    let ignore=false;
    const refresh=()=>api('/alerts/summary').then(s=>{if(!ignore)setAlertCount(s.unreviewed);}).catch(()=>{if(!ignore)setAlertCount(null);});
    refresh();const timer=setInterval(refresh,60000);
    return()=>{ignore=true;clearInterval(timer);};
  },[user]);

  async function loadData() {
    try {
      const [loadedRooms, loadedReservations] = await Promise.all([
        hasPermission(user, "rooms.view") ? api("/rooms") : Promise.resolve([]),
        hasPermission(user, "reservations.view") ? api("/reservations") : Promise.resolve([]),
      ]);
      setRooms(loadedRooms);
      setReservations(loadedReservations);
      setConnected(true);
      setConnectionError("");
      return true;
    } catch (error) {
      setConnected(false);
      setConnectionError(error.message);
      return false;
    }
  }

  function clearSession() {
    setReservationFilters({ search: "", status: "all", payment: "all", dates: "all" });
    setTransferReservation(null);
    setExtensionReservation(null);
    setEditingReservation(null);
    setReceiptId(null);
    setUser(null); setRooms([]); setReservations([]); setConnected(false);
    setBooking(emptyBooking); setWalkIn(emptyWalkIn); setWalkInReview(null);
    setPendingConfirmation(null); setPaymentReservationId(""); setNotice("");
    setConnectionError(""); setPage("Dashboard");
  }

  useEffect(() => {
    const ended = () => { clearSession(); setAuthMessage("Please log in to continue."); };
    window.addEventListener("kemmon-session-ended", ended);
    api("/auth/me").then((result) => setUser(result.user)).catch((error) => {
      if (error.status !== 401) setAuthMessage(error.message);
    }).finally(() => setAuthLoading(false));
    return () => window.removeEventListener("kemmon-session-ended", ended);
  }, []);

  useEffect(() => { if (user) loadData(); }, [user?.id, user?.roleId]);

  async function logOut() {
    if (busy) return;
    setBusy(true);
    try {
      await api("/auth/logout", { method: "POST" });
      clearSession(); setAuthMessage("You have signed out.");
    } catch (error) { setNotice(`Could not complete sign-out. ${error.message}`); }
    finally { setBusy(false); }
  }

  const can = (permission) => hasPermission(user, permission);
  const allowedPages = [
    ...(can("rooms.view") ? ["Dashboard", "Rooms"] : []),
    ...(can("reservations.view") ? ["Reservations", "Availability calendar"] : []),
    ...(can("reservations.manage") && can("stays.manage") ? ["Walk-ins"] : []),
    ...(can("payments.view") ? ["Payments"] : []),
    ...(can("reports.view") ? ["Reports"] : []),
    ...(can("expenses.view") ? ["Expenses"] : []),
    ...(can("cash.view") ? ["Cash summary"] : []),
    ...(can("shifts.view") ? ["Cashier shifts"] : []),
    ...(can("audit.view") ? ["Audit logs"] : []),
    ...(can("alerts.view") ? ["Owner alerts"] : []),
    ...(can("maintenance.view") ? ["Maintenance"] : []),
    ...(can("inventory.view") ? ["Inventory"] : []),
    ...(can("bar.view") ? ["Bar POS"] : []),
    ...(user?.isOwner ? ["Staff Management", "Backups"] : []), "Account",
  ];
  const activePage = allowedPages.includes(page) ? page : allowedPages[0];

  const selectedRoom = rooms.find((room) => room.id === Number(booking.roomId));
  const bookingUnits = chargeUnits(booking.checkIn, booking.checkOut);
  const takenRooms = rooms.filter((room) => room.taken).length;
  const cleaningRooms = rooms.filter((room) => !room.taken && room.maintenanceStatus !== "out_of_service" && room.cleaningStatus === "needs_cleaning").length;
  const maintenanceRooms = rooms.filter((room) => room.maintenanceStatus === "out_of_service").length;
  const freeRooms = rooms.length - takenRooms - cleaningRooms - maintenanceRooms;
  const filteredReservations = reservations.filter((reservation) => {
    const { search, status, payment, dates } = reservationFilters;
    if (status !== "all" && reservation.status !== status) return false;
    if (payment !== "all" && reservation.paymentStatus !== payment) return false;
    const today = lodgeToday();
    if (dates !== "all" && reservation.status === "cancelled") return false;
    if (dates === "arrivals" && reservation.checkIn !== today) return false;
    if (dates === "departures" && reservation.checkOut !== today) return false;
    const query = search.trim().toLocaleLowerCase();
    if (!query) return true;
    const phoneDigits = String(reservation.phone || "").replace(/\D/g, "");
    if (/^[+\d\s()-]+$/.test(query)) {
      const digits = query.replace(/\D/g, "");
      if (digits && phoneDigits.includes(digits)) return true;
    }
    const haystack = `${reservation.guest} ${reservation.phone} ${phoneDigits} room ${reservation.roomNumber}`.toLocaleLowerCase();
    return query.split(/\s+/).every((word) => haystack.includes(word));
  });
  function changeReservationFilters(event) {
    const { name, value } = event.target;
    setReservationFilters((current) => ({ ...current, [name]: value }));
    setPendingConfirmation(null);
  }
  const activeReservations = reservations.filter((item) => ["confirmed", "checked_in"].includes(item.status));
  const disabled = !connected || busy;
  const today = lodgeToday();
  const walkInUnits = chargeUnits(today, walkIn.checkOut);
  const eligibleRooms = walkInUnits > 0 ? rooms.filter((room) =>
    !room.taken && room.maintenanceStatus === "available" && room.cleaningStatus === "ready" &&
    !activeReservations.some((item) => item.roomId === room.id &&
      staysOverlap(today, walkIn.checkOut, item.roomAllocationFrom || item.checkIn, item.checkOut))
  ) : [];
  const walkInRoom = eligibleRooms.find((room) => room.id === Number(walkIn.roomId));

  function changeWalkIn(event) {
    setWalkIn((current) => ({ ...current, [event.target.name]: event.target.value }));
    setWalkInReview(null);
    setNotice("");
  }

  function reviewWalkIn(event) {
    event.preventDefault();
    if (disabled) return;
    if (!walkIn.guest.trim() || !walkIn.phone.trim() || !walkInRoom || walkInUnits <= 0) {
      setNotice("Enter guest details, a departure today or later, and an available room.");
      return;
    }
    setWalkInReview({
      guest: walkIn.guest.trim(), phone: walkIn.phone.trim(), guestCount: Number(walkIn.guestCount),
      roomId: walkInRoom.id, roomNumber: walkInRoom.roomNumber,
      checkOut: walkIn.checkOut, arrival: today, total: walkInUnits * walkInRoom.price,
    });
  }

  async function confirmWalkIn() {
    if (disabled || !walkInReview) return;
    if (walkInReview.arrival !== lodgeToday()) {
      setWalkInReview(null);
      setNotice("The date has changed. Review the walk-in again before checking in.");
      return;
    }
    const { guest, phone, guestCount, roomId, checkOut } = walkInReview;
    const saved = await performAction("/walk-ins", {
      method: "POST", body: JSON.stringify({ guest, phone, guestCount, roomId, checkOut }),
    }, "Walk-in guest checked in. Room is now Taken. Find their Check out button in Reservations.");
    setWalkInReview(null);
    if (saved) {
      setWalkIn(emptyWalkIn);
      setPage("Reservations");
    }
  }

  function changeBooking(event) {
    setBooking((current) => ({ ...current, [event.target.name]: event.target.value }));
    setNotice("");
  }

  async function performAction(path, options, message) {
    setBusy(true);
    setNotice("");
    try {
      await api(path, options);
      const refreshed = await loadData();
      setNotice(refreshed ? message : `${message} Refresh failed; retry the connection to see the latest data.`);
      return true;
    } catch (error) {
      setNotice(error.message);
      return false;
    } finally { setBusy(false); }
  }

  async function createReservation(event) {
    event.preventDefault();
    if (disabled) return;
    if (!booking.guest.trim() || !booking.phone.trim() || !selectedRoom || bookingUnits <= 0) {
      setNotice("Enter guest details and choose a checkout date on or after check-in.");
      return;
    }
    if (selectedRoom.maintenanceStatus !== "available") {
      setNotice("This room is out of service. Choose another room."); return;
    }
    const overlap = activeReservations.some((item) => item.roomId === selectedRoom.id
      && staysOverlap(booking.checkIn, booking.checkOut, item.roomAllocationFrom || item.checkIn, item.checkOut));
    if (overlap) {
      setNotice("This room already has a reservation during those dates.");
      return;
    }
    const saved = await performAction("/reservations", {
      method: "POST", body: JSON.stringify({...booking,guestCount:Number(booking.guestCount),roomId:Number(booking.roomId)}),
    }, "Reservation saved in PostgreSQL.");
    if (saved) setBooking(emptyBooking);
  }

  function requestAction(reservation, action) {
    setPendingConfirmation({ reservation, action });
    setNotice("");
  }

  async function confirmAction() {
    const { reservation, action } = pendingConfirmation;
    const path = `/reservations/${reservation.id}${action === "cancel" ? "" : `/${action}`}`;
    setPendingConfirmation(null);
    await performAction(path, { method: action === "cancel" ? "DELETE" : "POST" },
      action === "check-in" ? "Guest checked in. Room is now Taken."
        : action === "check-out" ? "Guest checked out. Room now Needs cleaning."
          : "Reservation cancelled.");
  }

  if (authLoading) return <main><p role="status">Checking login…</p></main>;
  if (!user) return <><p className="auth-message" role="status">{authMessage}</p><LoginPanel onLogin={(account) => {
    setUser(account); setAuthMessage(""); setPage("Dashboard");
  }} /></>;

  return (
    <LodgeShell user={user} pages={allowedPages} activePage={activePage} connected={connected} alertCount={alertCount} busy={busy} onLogout={logOut}
      onNavigate={(name) => { setPage(name); setPendingConfirmation(null); setWalkInReview(null); }}
      onNewReservation={can("reservations.manage") ? () => { setPage("Reservations"); setTimeout(() => document.querySelector('input[name="guest"]')?.focus(), 0); } : null}>
      {connectionError && <p className="connection-banner" role="alert">{connectionError} <button type="button" disabled={busy} onClick={loadData}>Retry connection</button></p>}
      {notice && <p className="notice-banner" role="status">{notice}</p>}
      {activePage === "Dashboard" && <LodgeDashboard rooms={rooms} reservations={reservations} connected={connected} can={can} api={api} today={lodgeToday()} onNavigate={setPage} userId={user.id} />}

      {activePage === "Availability calendar" && <RoomCalendar rooms={rooms} reservations={reservations} connected={connected} today={lodgeToday()} onRefresh={loadData} formatTime={timeInTanzania} />}

      {activePage === "Rooms" && <section>
        <h2>Rooms</h2>
        <p>{connected ? `${freeRooms} free · ${takenRooms} taken · ${cleaningRooms} need cleaning · ${maintenanceRooms} out of service` : "Connect to load rooms."}</p>
        <div className="room-grid">{(connected ? rooms : []).map((room) => (
          <article className="room-card" key={room.id}>
            <h3>{room.name}</h3>
            <p>{money(room.price)} per night</p>
            <p className={room.maintenanceStatus === "out_of_service" ? "status-maintenance" : room.taken ? "status-taken" : room.cleaningStatus === "needs_cleaning" ? "status-cleaning" : "status-free"}>{roomLabel(room)}</p>
            {can("rooms.ready") && room.maintenanceStatus !== "out_of_service" && !room.taken && room.cleaningStatus === "needs_cleaning" && <button type="button" disabled={disabled}
              onClick={() => performAction(`/rooms/${room.id}/ready`, { method: "POST" }, `${room.name} is clean and ready.`)}>
              Mark ready after cleaning
            </button>}
          </article>
        ))}</div>
      </section>}

      {activePage === "Reservations" && <section>
        <h2>Reservations</h2>
        <p>Choose a room to see its rate. Same-day stays cost one full room rate; overnight stays are charged per night.</p>
        {can("reservations.manage") && <form className="reservation-form" onSubmit={createReservation}>
          <label>Guest name<input name="guest" value={booking.guest} onChange={changeBooking} required maxLength={120} autoComplete="name" disabled={disabled} /></label>
          <label>Phone number<input name="phone" type="tel" value={booking.phone} onChange={changeBooking} required maxLength={40} autoComplete="tel" disabled={disabled} /></label>
          <label>Number of guests<input name="guestCount" type="number" min="1" max="100" step="1" value={booking.guestCount} onChange={changeBooking} required disabled={disabled} /></label>
          <label>Room<select name="roomId" value={selectedRoom?.maintenanceStatus === "available" ? booking.roomId : ""} onChange={changeBooking} disabled={disabled}>
            <option value="" disabled>Choose an in-service room</option>
            {rooms.filter((room) => room.maintenanceStatus === "available").map((room) => <option key={room.id} value={room.id}>{room.name} — {money(room.price)} / night</option>)}
          </select></label>
          <label>Check-in date<input name="checkIn" type="date" value={booking.checkIn} onChange={changeBooking} required disabled={disabled} /></label>
          <label>Check-out date<input name="checkOut" type="date" min={booking.checkIn || undefined} value={booking.checkOut} onChange={changeBooking} required disabled={disabled} /></label>
          <p className="booking-total">{selectedRoom && bookingUnits > 0 ? `${stayDescription(booking.checkIn, booking.checkOut)} · ${money(bookingUnits * selectedRoom.price)}` : "Choose stay dates to calculate the total."}</p>
          <button type="submit" disabled={disabled}>Save reservation</button>
        </form>}
        <h3>Saved reservations</h3>
        <p>Check in when the guest arrives, and check out when they leave. Completed stays remain in the list.</p>
        <div className="reservation-search" role="search" aria-label="Find reservations">
          <label>Search guests, phone or room<input type="search" name="search" value={reservationFilters.search} onChange={changeReservationFilters} placeholder="Guest name, phone number, or Room 200" disabled={!connected} /></label>
          <label>Stay status<select name="status" value={reservationFilters.status} onChange={changeReservationFilters} disabled={!connected}>
            <option value="all">All stay statuses</option><option value="confirmed">Booked</option><option value="checked_in">Checked in</option><option value="checked_out">Checked out</option><option value="cancelled">Cancelled</option>
          </select></label>
          <label>Payment status<select name="payment" value={reservationFilters.payment} onChange={changeReservationFilters} disabled={!connected}>
            <option value="all">All payment statuses</option><option value="Unpaid">Unpaid</option><option value="Part paid">Part paid</option><option value="Paid">Paid</option><option value="Credit due">Credit due</option>
          </select></label>
          <label>Scheduled dates<select name="dates" value={reservationFilters.dates} onChange={changeReservationFilters} disabled={!connected}>
            <option value="all">All dates</option><option value="arrivals">Arrivals today</option><option value="departures">Departures today</option>
          </select></label>
          <button type="button" onClick={() => { setReservationFilters({ search: "", status: "all", payment: "all", dates: "all" }); setPendingConfirmation(null); }}>Clear filters</button>
        </div>
        <p className="reservation-filter-note">Today is {lodgeToday()} in Tanzania. Today views use scheduled dates and exclude cancelled bookings.</p>
        {connected && <p role="status">Showing {filteredReservations.length} of {reservations.length} reservations.</p>}
        {pendingConfirmation && <ConfirmationPrompt busy={busy} onDismiss={()=>setPendingConfirmation(null)} feedback={notice} role="group" aria-label="Confirm reservation action">
          <p>{pendingConfirmation.action === "check-in" ? "Check in" : pendingConfirmation.action === "check-out" ? "Check out" : "Cancel booking for"} {pendingConfirmation.reservation.guest}, Room {pendingConfirmation.reservation.roomNumber}?</p>
          <button type="button" disabled={disabled} onClick={confirmAction}>Confirm</button>{" "}
          <button type="button" disabled={busy} onClick={() => setPendingConfirmation(null)}>Go back</button>
        </ConfirmationPrompt>}
        {!connected ? <p>Connect to load reservations.</p> : reservations.length === 0 ? <p>No reservations yet.</p> : filteredReservations.length === 0 ? <p>No reservations match these filters. Try another search or clear the filters.</p> : <div className="table-scroll"><table>
          <caption className="sr-only">Reservations and stay actions</caption>
          <thead><tr>{["Guest", "Phone", "Guests", "Room", "Arrival", "Departure", "Stay", "Total", "Paid", "Balance", "Credit due", "Checked in (Tanzania)", "Checked out (Tanzania)", "Status", "Action"].map((name) => <th scope="col" key={name}>{name}</th>)}</tr></thead>
          <tbody>{filteredReservations.map((reservation) => <tr key={reservation.id}>
            <td>{reservation.guest}</td><td>{reservation.phone}</td><td>{reservation.guestCount ?? "Not recorded"}</td><td>Room {reservation.roomNumber}</td>
            <td>{reservation.checkIn}</td><td>{reservation.checkOut}</td><td>{stayDescription(reservation.checkIn, reservation.checkOut)}</td><td>{money(reservation.total)}{reservation.barCharges > 0 && <small className="bar-total-note">Includes bar: {money(reservation.barCharges)}</small>}</td><td>{money(reservation.paid)}</td><td>{money(reservation.balance)}</td><td>{money(reservation.credit || 0)}</td>
            <td>{timeInTanzania(reservation.checkedInAt)}</td><td>{timeInTanzania(reservation.checkedOutAt)}</td>
            <td>{statusLabels[reservation.status] || reservation.status}
              {reservation.roomOutOfService && reservation.status === "confirmed" && <p className="maintenance-warning">Room out of service — needs attention</p>}
            </td>
            <td><div className="reservation-actions">
              <button type="button" disabled={disabled} onClick={()=>setEditingReservation(reservation)}>{can("reservations.edit")?"Edit guest / Booking":"Edit history"}</button>
              <button type="button" disabled={disabled} onClick={() => setTransferReservation(reservation)}>
                {can("stays.transfer") && reservation.status === "checked_in" ? "Transfer room / History" : "Room history"}
              </button>
              <button type="button" disabled={disabled} onClick={() => setExtensionReservation(reservation)}>
                {can("reservations.extend") && ["confirmed", "checked_in"].includes(reservation.status) ? "Extend stay / History" : "Stay history"}
              </button>
              {can("payments.view") && <button type="button" disabled={disabled} onClick={() => { setPaymentReservationId(reservation.id); setPage("Payments"); }}>Payments</button>}
              {reservation.status === "confirmed" && <>
                {can("stays.manage") && <button type="button" disabled={disabled} aria-label={`Check in ${reservation.guest}`} onClick={() => requestAction(reservation, "check-in")}>Check in</button>}
                {can("reservations.manage") && <button type="button" disabled={disabled} aria-label={`Cancel booking for ${reservation.guest}`} onClick={() => requestAction(reservation, "cancel")}>Cancel</button>}
              </>}
              {can("stays.manage") && reservation.status === "checked_in" && <button type="button" disabled={disabled} aria-label={`Check out ${reservation.guest}`} onClick={() => requestAction(reservation, "check-out")}>Check out</button>}
              {["checked_out", "cancelled"].includes(reservation.status) && <span>Complete</span>}
            </div></td>
          </tr>)}</tbody>
        </table></div>}
      </section>}
      {activePage === "Walk-ins" && <section>
        <h2>Walk-in / Check in now</h2>
        <p>Register a guest arriving today. Departure can also be today. Same-day stays cost one full room rate. Only clean, unoccupied rooms available for the stay are shown.</p>
        <form className="reservation-form" onSubmit={reviewWalkIn}>
          <label>Guest name<input name="guest" value={walkIn.guest} onChange={changeWalkIn} required maxLength={120} autoComplete="name" disabled={disabled} /></label>
          <label>Phone number<input name="phone" type="tel" value={walkIn.phone} onChange={changeWalkIn} required maxLength={40} autoComplete="tel" disabled={disabled} /></label>
          <label>Number of guests<input name="guestCount" type="number" min="1" max="100" step="1" value={walkIn.guestCount} onChange={changeWalkIn} required disabled={disabled} /></label>
          <label>Arrival date<input type="date" value={today} readOnly /></label>
          <label>Departure date<input name="checkOut" type="date" min={today} value={walkIn.checkOut} onChange={changeWalkIn} required disabled={disabled} /></label>
          <label>Available room<select name="roomId" value={walkInRoom ? walkIn.roomId : ""} onChange={changeWalkIn} required disabled={disabled || walkInUnits <= 0}>
            <option value="">Choose a room</option>
            {eligibleRooms.map((room) => <option key={room.id} value={room.id}>{room.name} — {money(room.price)} / night</option>)}
          </select></label>
          <p className="booking-total">{walkInRoom && walkInUnits > 0 ? `${stayDescription(today, walkIn.checkOut)} · ${money(walkInUnits * walkInRoom.price)}` : "Choose a departure date and available room to calculate the total."}</p>
          <button type="submit" disabled={disabled || !walkInRoom}>Check in now</button>
        </form>
        {connected && walkInUnits > 0 && eligibleRooms.length === 0 && <p role="status">No clean, free room is available for those dates. Try an earlier departure or check room readiness.</p>}
        {walkInReview && <ConfirmationPrompt busy={busy} onDismiss={()=>setWalkInReview(null)} feedback={notice} role="group" aria-label="Confirm walk-in check-in">
          <p>Check in {walkInReview.guest} now in Room {walkInReview.roomNumber}?</p>
          <p>Guests: {walkInReview.guestCount} · Arrival: {walkInReview.arrival} · Departure: {walkInReview.checkOut} · Total: {money(walkInReview.total)}</p>
          <button type="button" disabled={disabled} onClick={confirmWalkIn}>Confirm check-in</button>{" "}
          <button type="button" disabled={busy} onClick={() => setWalkInReview(null)}>Go back</button>
        </ConfirmationPrompt>}
      </section>}
      {activePage === "Reports" && can("reports.view") && <><CollectionsReport onReceipt={setReceiptId} /><BarSalesReport api={api} /></>}
      {activePage === "Staff Management" && user.isOwner && <StaffPanel />}
      {activePage === "Backups" && user.isOwner && <Backups api={api} onRestored={() => { clearSession(); setAuthMessage("Backup restored successfully. Log in using an owner account from that backup."); }} />}
      {activePage === "Account" && <AccountPanel user={user} onPasswordChanged={() => {
        clearSession(); setAuthMessage("Password changed. Log in with your new password.");
      }} />}
      {activePage === "Payments" && <PaymentsPanel reservations={reservations}
        selectedId={paymentReservationId} setSelectedId={setPaymentReservationId}
        connected={connected} onSaved={loadData} canRecord={can("payments.record")} onReceipt={setReceiptId} />}
      {activePage === "Bar POS" && can("bar.view") && <BarPOS api={api} can={can} onUpdated={loadData} userId={user.id} />}
      {activePage === "Inventory" && can("inventory.view") && <InventoryPanel api={api} can={can} />}
      {activePage === "Maintenance" && can("maintenance.view") && <MaintenancePanel rooms={rooms} canManage={can("maintenance.manage")} onUpdated={loadData} />}
      {activePage === "Expenses" && can("expenses.view") && <ExpensesPanel canRecord={can("expenses.record")} />}
      {activePage === "Owner alerts" && can("alerts.view") && <OwnerAlerts api={api} can={can} user={user} onSummary={s=>setAlertCount(s.unreviewed)} onNavigate={setPage} />}
      {activePage === "Audit logs" && can("audit.view") && <AuditLogs api={api} />}
      {activePage === "Cashier shifts" && can("shifts.view") && <CashierShifts api={api} can={can} user={user} />}
      {activePage === "Cash summary" && can("cash.view") && <CashSummaryPanel canManage={can("cash.manage")} />}
      {transferReservation && <RoomTransferDialog reservation={transferReservation} canTransfer={can("stays.transfer")}
        onUpdated={loadData} onClose={() => setTransferReservation(null)} />}
      {editingReservation && <ReservationEditDialog reservation={editingReservation} api={api} canEdit={can("reservations.edit")} userId={user.id} onUpdated={loadData} onClose={()=>setEditingReservation(null)} />}
      {extensionReservation && <StayExtensionDialog reservation={extensionReservation}
        canExtend={can("reservations.extend")} onUpdated={loadData} onClose={() => setExtensionReservation(null)} />}
      {receiptId && <ReceiptViewer paymentId={receiptId} onClose={() => setReceiptId(null)} />}
    </LodgeShell>
  );
}
