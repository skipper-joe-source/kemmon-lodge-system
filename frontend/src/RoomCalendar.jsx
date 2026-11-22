import {useEffect,useRef,useState} from 'react';
import {addDays,bookingsOn} from './calendarDates';
const label=d=>new Intl.DateTimeFormat('en-GB',{timeZone:'UTC',weekday:'short',day:'numeric',month:'short'}).format(new Date(`${d}T00:00:00Z`));
const money=n=>`TZS ${Number(n).toLocaleString('en-US')}`;
function Details({stay,onClose,formatTime}) {
 const ref=useRef(null);
 useEffect(()=>{ref.current.showModal();},[]);
 return <dialog ref={ref} className="calendar-details" aria-labelledby="calendar-detail-title" onCancel={onClose}>
 <h3 id="calendar-detail-title">{stay.guest} · Room {stay.roomNumber}</h3>
 <p>{stay.status==='checked_in'?'Checked in':'Reserved'}</p>
 <dl>{[['Phone',stay.phone],['Guests',stay.guestCount??'Not recorded'],['Arrival',stay.checkIn],['Departure',stay.checkOut],['Current room allocated from',stay.roomAllocationFrom||stay.checkIn],['Actual check-in',formatTime(stay.checkedInAt)],['Actual check-out',formatTime(stay.checkedOutAt)],['Agreed room rate',money(stay.nightlyRate)],['Total bill',money(stay.total)],['Outstanding balance',money(stay.balance)]].map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
 <button type="button" onClick={onClose} autoFocus>Close details</button></dialog>;
}
export default function RoomCalendar({rooms,reservations,connected,today,onRefresh,formatTime}) {
 const [start,setStart]=useState(today),[length,setLength]=useState(14),[selectedId,setSelectedId]=useState(null),[refreshing,setRefreshing]=useState(false);
 const days=Array.from({length},(_,i)=>addDays(start,i));
 const selected=connected?reservations.find(s=>s.id===selectedId):null;
 const overdue=reservations.filter(s=>s.status==='checked_in'&&s.checkOut<=today);
 async function refresh(){setRefreshing(true);try{await onRefresh();}finally{setRefreshing(false);}}
 return <section><h2>Room availability calendar</h2>
 <p>Dates use Tanzania time. Checkout releases the room; same-day stays reserve one date. Select a booking for details.</p>
 <div className="calendar-controls"><label>Starting date<input type="date" required value={start} onChange={e=>{if(/^\d{4}-\d{2}-\d{2}$/.test(e.target.value))setStart(e.target.value);}}/></label>
 <label>Show<select value={length} onChange={e=>setLength(Number(e.target.value))}>{[7,14,30].map(n=><option key={n} value={n}>{n} days</option>)}</select></label>
 <button type="button" onClick={()=>setStart(addDays(start,-length))}>Previous</button><button type="button" onClick={()=>setStart(today)}>Today</button><button type="button" onClick={()=>setStart(addDays(start,length))}>Next</button><button type="button" disabled={refreshing} onClick={refresh}>{refreshing?'Refreshing…':'Refresh availability'}</button></div>
 <p className="calendar-legend"><span className="calendar-booked">Reserved</span><span className="calendar-occupied">Checked in</span><span>— No active booking</span></p>
 <p>Readiness shows the room’s current status, not a forecast. Check readiness before accepting a walk-in. Only active bookings in their current room are shown; completed stays and previous room assignments are excluded.</p>
 {connected&&overdue.length>0&&<p role="status">{overdue.length} checked-in stay(s) have reached their scheduled departure. These rooms remain occupied now. Confirm checkout or extend the stay before accepting another guest.</p>}
 {!connected?<p role="status">Connect to load availability.</p>:<div className="calendar-scroll" tabIndex={0} role="region" aria-label="Room availability; scroll horizontally to see more dates"><table className="availability-table"><caption>{label(start)} – {label(days.at(-1))} · {rooms.length} rooms</caption>
 <thead><tr><th scope="col">Room / current status</th>{days.map(day=><th scope="col" key={day} className={day===today?'calendar-today':''}>{label(day)}{day===today&&<small>Today</small>}</th>)}</tr></thead>
 <tbody>{[...rooms].sort((a,b)=>a.roomNumber-b.roomNumber).map(room=><tr key={room.id}><th scope="row">{room.name}<small>{money(room.price)}</small><small>{room.maintenanceStatus==='out_of_service'?'Out of service':room.taken?'Occupied now':room.cleaningStatus==='needs_cleaning'?'Needs cleaning now':'Ready now'}</small></th>
 {days.map(day=>{const stays=bookingsOn(reservations,room.id,day,today);return <td key={day} className={day===today?'calendar-today':''}>{stays.length?stays.map(s=><button key={s.id} type="button" className={s.status==='checked_in'?'calendar-occupied':'calendar-booked'} onClick={()=>setSelectedId(s.id)} aria-label={`${s.guest}, ${room.name}, ${label(day)}`}>
 {s.guest}<small>{s.status==='checked_in'?'Checked in':'Reserved'}{s.checkIn===s.checkOut?' · Same day':''}</small></button>):<span aria-label="No active booking">—</span>}</td>;})}</tr>)}</tbody></table></div>}
 {selected&&<Details key={selected.id} stay={selected} formatTime={formatTime} onClose={()=>setSelectedId(null)}/>}</section>;
}
