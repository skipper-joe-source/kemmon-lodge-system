import {useEffect,useState} from 'react';
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Africa/Dar_es_Salaam',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const time=t=>new Date(t).toLocaleString('en-GB',{timeZone:'Africa/Dar_es_Salaam'});
const label=s=>s.replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());
function AuditDetails({data}) {
  return <dl className="audit-details">{Object.entries(data).map(([key,value])=><div key={key}><dt>{label(key)}</dt><dd>{value===null?'Not recorded':typeof value==='boolean'?(value?'Yes':'No'):Array.isArray(value)?(value.length?value.map(String).join(', '):'None'):typeof value==='object'?<AuditDetails data={value}/>:String(value)}</dd></div>)}</dl>;
}
export default function AuditLogs({api}) {
  const [filters,setFilters]=useState({start_date:today(),end_date:today(),staff_id:'',action:''}),[loaded,setLoaded]=useState(null);
  const [options,setOptions]=useState(null),[data,setData]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(true);
  async function load(range=filters,page=1) {
    setBusy(true);setError('');
    const params=Object.fromEntries(Object.entries(range).filter(([,v])=>v!==''));
    try {const [o,d]=await Promise.all([api('/audit/options'),api(`/audit?${new URLSearchParams({...params,page:String(page)})}`)]);setOptions(o);setData(d);setLoaded(range);}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }
  useEffect(()=>{load();},[]);
  const change=e=>setFilters({...filters,[e.target.name]:e.target.value});
  return <section><h2>Audit logs</h2><p>Review successful staff actions. Records are read-only and cannot be edited or deleted here. All times and date filters use Tanzania time.</p>
    {options&&<p className="audit-coverage">Full change tracking started {time(options.trackingStartedAt)}. Older entries come from the history already recorded by the app. Earlier reservation and room-status changes may be missing; missing staff names are shown as “Not recorded”. Passwords, session tokens, guest names and phone numbers are excluded from captured account and reservation fields.</p>}
    <form className="shift-form" onSubmit={e=>{e.preventDefault();load();}}>
      <label>From<input required type="date" name="start_date" value={filters.start_date} disabled={busy} onChange={change}/></label>
      <label>To<input required type="date" name="end_date" min={filters.start_date} value={filters.end_date} disabled={busy} onChange={change}/></label>
      <label>Staff<select name="staff_id" value={filters.staff_id} disabled={busy} onChange={change}><option value="">All staff</option>{options?.staff.map(s=><option key={s.id} value={s.id}>{s.name}</option>)}{options?.hasUnknownStaff&&<option value="unknown">Not recorded</option>}</select></label>
      <label>Action<select name="action" value={filters.action} disabled={busy} onChange={change}><option value="">All actions</option>{options?.actions.map(a=><option key={a.key} value={a.key}>{a.label}</option>)}</select></label>
      <button disabled={busy}>{busy?'Loading…':'View audit logs'}</button><button type="button" disabled={busy} onClick={()=>load(loaded||filters,data?.page||1)}>Refresh current results</button>
    </form>
    {error&&<p role="alert">{error}</p>}
    {data&&<><p>{data.count} recorded actions · {data.startDate} to {data.endDate} · Page {data.page} of {data.pageCount}</p>
      <div className="table-scroll"><table><thead><tr><th>Time (Tanzania)</th><th>Staff</th><th>Action</th><th>Record</th><th>Details</th></tr></thead><tbody>{data.events.map(e=><tr key={e.id}><td>{time(e.at)}</td><td>{e.staff}</td><td>{e.label}{e.origin==='historical_record'&&<small className="audit-historical">Historical record</small>}</td><td>{label(e.entityType)}<br/><span className="audit-id">{e.entityId}</span></td><td><details><summary>View details</summary><AuditDetails data={e.details}/><p className="audit-id">Audit ID: {e.id} · Source: {e.source}{e.sourceId?` · ${e.sourceId}`:''}</p></details></td></tr>)}</tbody></table></div>
      {!data.events.length&&<p>No recorded actions match these filters.</p>}
      <button disabled={busy||data.page<=1} onClick={()=>load(loaded,data.page-1)}>Previous actions</button><span> Page {data.page} of {data.pageCount} </span><button disabled={busy||data.page>=data.pageCount} onClick={()=>load(loaded,data.page+1)}>Next actions</button>
    </>}
  </section>;
}
