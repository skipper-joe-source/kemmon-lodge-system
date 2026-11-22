import ConfirmationPrompt from './ConfirmationPrompt';
import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
const money=n=>`TZS ${Number(n).toLocaleString()}`;
const time=t=>new Date(t).toLocaleString('en-GB',{timeZone:'Africa/Dar_es_Salaam'});
const fields={guest:'Guest name',phone:'Phone number',guestCount:'Number of guests',checkIn:'Arrival date',checkOut:'Departure date'};
const display=(value)=>value===null?'Not recorded':String(value);
function Changes({before,after,changedFields}) {
  return <div className="table-scroll"><table><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>{changedFields.map(key=><tr key={key}><td>{fields[key]||key}</td><td>{display(before[key])}</td><td>{display(after[key])}</td></tr>)}</tbody></table></div>;
}
export default function ReservationEditDialog({reservation,api,canEdit,userId,onUpdated,onClose}) {
  const ref=useRef(null),pendingKey=`kemmon_booking_edit_${userId}_${reservation.id}`;
  const [data,setData]=useState(null),[draft,setDraft]=useState(null),[version,setVersion]=useState(''),[review,setReview]=useState(null);
  const [loading,setLoading]=useState(true),[saving,setSaving]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('');
  useEffect(()=>{ref.current?.showModal();return()=>ref.current?.close();},[]);
  async function load(page=1,reset=true) {
    setLoading(true);setError('');
    try {const result=await api(`/reservations/${reservation.id}/edits?page=${page}`);setData(result);if(reset){setDraft({guest:result.reservation.guest,phone:result.reservation.phone,guestCount:result.reservation.guestCount??'',checkIn:result.reservation.checkIn,checkOut:result.reservation.checkOut,reason:''});setVersion(result.version);}}
    catch(e){setError(e.message);}finally{setLoading(false);}
  }
  useEffect(()=>{load();try{const p=JSON.parse(sessionStorage.getItem(pendingKey));if(p?.body?.requestId&&p?.preview?.after)setReview(p);}catch{}},[]);
  const locked=loading||saving||!!review;
  const current=data?.reservation;
  const datesEditable=canEdit&&current?.status==='confirmed';
  function change(e){setDraft({...draft,[e.target.name]:e.target.value});setMessage('');}
  async function prepare(e){e.preventDefault();setError('');setMessage('');setLoading(true);try{
    const body={...draft,guestCount:draft.guestCount===''?null:Number(draft.guestCount),expectedVersion:version};
    const result=await api(`/reservations/${reservation.id}/edit-preview`,{method:'POST',body:JSON.stringify(body)});
    setReview({body:{...body,requestId:crypto.randomUUID()},preview:result});
  }catch(e){setError(e.message);}finally{setLoading(false);}}
  async function save(){setSaving(true);setError('');try{try{sessionStorage.setItem(pendingKey,JSON.stringify(review));}catch{}
    const result=await api(`/reservations/${reservation.id}/edit`,{method:'POST',body:JSON.stringify(review.body)});
    try{sessionStorage.removeItem(pendingKey);}catch{}setReview(null);setMessage(`Booking updated. Total ${money(result.reservation.total)}; balance ${money(result.reservation.balance)}${result.reservation.credit?`; credit due ${money(result.reservation.credit)}`:''}.`);await load();await onUpdated();
  }catch(e){setError(e.message);}finally{setSaving(false);}}
  function back(){try{sessionStorage.removeItem(pendingKey);}catch{}setReview(null);}
  return createPortal(<dialog className="stay-extension-dialog" ref={ref} aria-labelledby="edit-booking-title" onCancel={e=>{e.preventDefault();if(!saving)onClose();}}>
    <div className="extension-toolbar"><h2 id="edit-booking-title">Guest details / Reservation editing</h2><button disabled={saving} onClick={onClose}>Close</button></div>
    <div className="extension-content"><p>Correct guest details with a reason. Date changes are available before check-in. Agreed room rate and recorded payments are preserved. Same-day stays cost one full room rate.</p>
      {loading&&<p role="status">Loading booking details…</p>}{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
      <button disabled={saving||!!review} onClick={()=>load()}>Refresh details</button>
      {current&&<><h3>{current.guest} · Room {current.roomNumber}</h3><p>Status: {current.status.replaceAll('_',' ')} · Agreed rate: {money(current.nightlyRate)} · Bill: {money(current.total)} · Paid: {money(current.paid)}</p>
      {!datesEditable&&<p>Dates are locked for this stay status. Use Extend stay for an active stay. Guest details can still be corrected by staff with edit permission.</p>}
      {canEdit&&draft&&<form className="reservation-form" onSubmit={prepare}>
        <label>Guest name<input name="guest" required maxLength={120} value={draft.guest} disabled={locked} onChange={change}/></label>
        <label>Phone number<input name="phone" type="tel" required maxLength={40} value={draft.phone} disabled={locked} onChange={change}/></label>
        <label>Number of guests{current.guestCount===null?' (leave blank if unknown)':''}<input name="guestCount" type="number" min="1" max="100" step="1" required={current.guestCount!==null} value={draft.guestCount} disabled={locked} onChange={change}/></label>
        <label>Arrival date<input name="checkIn" type="date" required value={draft.checkIn} disabled={locked||!datesEditable} onChange={change}/></label>
        <label>Departure date<input name="checkOut" type="date" min={draft.checkIn} required value={draft.checkOut} disabled={locked||!datesEditable} onChange={change}/></label>
        <label>Reason for correction<textarea name="reason" required maxLength={500} value={draft.reason} disabled={locked} onChange={change}/></label>
        <button disabled={locked}>Check availability and review changes</button>
      </form>}
      {!canEdit&&<p>Your role can view correction history. Ask the owner for reservation editing permission to make changes.</p>}</>}
      {review&&<ConfirmationPrompt busy={saving} onDismiss={back} feedback={error}><h3>Confirm booking correction</h3><Changes {...review.preview}/><p>Room charges: {money(review.preview.before.roomTotal)} → {money(review.preview.after.roomTotal)} · Bar charges: {money(review.preview.after.barCharges)}</p><p><strong>New total: {money(review.preview.after.total)}</strong> · Payments kept: {money(review.preview.after.paid)} · New balance: {money(review.preview.after.balance)}</p>
        {review.preview.after.credit>0&&<p><strong>Credit due: {money(review.preview.after.credit)}</strong>. No automatic refund will be issued.</p>}
        <p>Reason: {review.body.reason}</p><button disabled={loading||saving||!canEdit} onClick={save}>{saving?'Saving…':'Confirm and save'}</button><button disabled={saving} onClick={back}>Go back</button><p>If saving fails, retry this same correction before starting another. If the booking changed, go back and refresh details.</p>
      </ConfirmationPrompt>}
      <h3>Correction history</h3>{data&&<><p>{data.count} recorded corrections. Earlier corrections made before this feature may not have been recorded.</p>{data.edits.map(e=><article className="booking-edit-history" key={e.id}><h4>{time(e.changedAt)} (Tanzania) · {e.changedBy}</h4><p>Reason: {e.reason}</p><Changes {...e}/><p>Bill: {money(e.before.total)} → {money(e.after.total)} · Paid at correction: {money(e.after.paid)} · Credit due then: {money(e.after.credit)}</p></article>)}{data.count===0&&<p>No corrections recorded yet.</p>}
      <button disabled={locked||data.page<=1} onClick={()=>load(data.page-1,false)}>Previous corrections</button><span> Page {data.page} of {data.pageCount} </span><button disabled={locked||data.page>=data.pageCount} onClick={()=>load(data.page+1,false)}>Next corrections</button></>}
    </div>
  </dialog>,document.body);
}
