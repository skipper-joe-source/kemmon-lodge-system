import ConfirmationPrompt from './ConfirmationPrompt';
import { cartReducer } from './barCart';
import { useEffect, useRef, useState, useReducer } from 'react';
import { createPortal } from 'react-dom';
const money=n=>`TZS ${Number(n).toLocaleString()}`;
const time=t=>new Date(t).toLocaleString('en-GB',{timeZone:'Africa/Dar_es_Salaam'});
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Africa/Dar_es_Salaam',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
export function BarReceiptContent({receipt:r}) {
  return <><p><strong>{r.receiptNumber}</strong></p><p>{time(r.soldAt)} (Tanzania) · Staff: {r.staff}</p>
    <p>{r.method==='room'?`Charged to ${r.guest} · Room ${r.roomNumber}`:r.method==='cash'?'Paid by cash':'Paid by mobile money'}</p>{r.reference&&<p>Transaction reference: {r.reference}</p>}
    <table><thead><tr><th>Product</th><th>Quantity</th><th>Unit price</th><th>Total</th></tr></thead><tbody>{r.items.map(i=><tr key={i.productId}><td>{i.name}</td><td>{i.quantity} {i.unit}</td><td>{money(i.unitPrice)}</td><td>{money(i.total)}</td></tr>)}</tbody></table>
    <p className="receipt-amount">{r.method==='room'?'Added to guest bill':'Amount received'}: <strong>{money(r.total)}</strong></p>
    {r.method==='room'&&<p>No payment received on this receipt. Settle through the guest payment account.</p>}</>;
}
function BarReceiptDialog({receipt,onClose}) {
  const ref=useRef(null);
  useEffect(()=>{ref.current?.showModal();return()=>ref.current?.close();},[]);
  return createPortal(<dialog className="receipt-dialog" ref={ref} onCancel={e=>{e.preventDefault();onClose();}} aria-label="Bar receipt"><div className="receipt-toolbar"><button onClick={()=>window.print()}>Print / Save as PDF</button><button onClick={onClose}>Close receipt</button></div><article className="guest-receipt"><h1>Kemmon Lodge</h1><h2>Bar sales receipt</h2><BarReceiptContent receipt={receipt}/></article></dialog>,document.body);
}
export function GuestBarCharges({api,reservationId,refreshKey}) {
  const [data,setData]=useState([]),[error,setError]=useState('');
  useEffect(()=>{let ignore=false;setData([]);setError('');api(`/reservations/${reservationId}/bar-sales`).then(r=>{if(!ignore)setData(r);}).catch(e=>{if(!ignore)setError(e.message);});return()=>{ignore=true;};},[reservationId,refreshKey]);
  return <div><h4>Bar charges on this guest bill</h4>{error&&<p role="alert">{error}</p>}{!error&&!data.length&&<p>No bar charges.</p>}{data.map(s=><details key={s.id}><summary>{time(s.soldAt)} · {money(s.total)} · {s.staff}</summary><BarReceiptContent receipt={s}/></details>)}</div>;
}
export function BarSalesReport({api,version=0}) {
  const [dates,setDates]=useState({start_date:today(),end_date:today()}),[loaded,setLoaded]=useState(null),[data,setData]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[receipt,setReceipt]=useState(null);
  async function load(range=dates,page=1){setBusy(true);setError('');try{const r=await api(`/bar/report?${new URLSearchParams({...range,page:String(page)})}`);setData(r);setLoaded(range);}catch(e){setError(e.message);}finally{setBusy(false);}}
  useEffect(()=>{load(loaded||dates);},[version]);
  return <section><h3>Bar sales report</h3><p>Sale dates in Tanzania time. Room charges are sales on credit; they enter collections only when the guest pays. Guest bill payments are not counted again as bar sales.</p>
    <form onSubmit={e=>{e.preventDefault();load();}}><label>From<input type="date" required value={dates.start_date} onChange={e=>setDates({...dates,start_date:e.target.value})}/></label><label>To<input type="date" required min={dates.start_date} value={dates.end_date} onChange={e=>setDates({...dates,end_date:e.target.value})}/></label><button disabled={busy}>View bar report</button></form>
    {error&&<p role="alert">{error}</p>}{data&&<><p>{data.startDate} to {data.endDate} · {data.count} sales</p><p>Cash: {money(data.cash)} · Mobile money: {money(data.mobile)} · Charged to rooms: {money(data.room)} · Total sales: {money(data.total)}</p>
      <h4>Sales by staff</h4><ul>{data.staff.map(s=><li key={s.username}>{s.username}: {money(s.total)} ({s.count} sales)</li>)}</ul>
      <div className="table-scroll"><table><thead><tr><th>Time (Tanzania)</th><th>Method</th><th>Room / guest</th><th>Amount</th><th>Staff</th><th>Receipt</th></tr></thead><tbody>{data.sales.map(s=><tr key={s.id}><td>{time(s.soldAt)}</td><td>{s.method==='room'?'Room charge':s.method==='cash'?'Cash':'Mobile money'}</td><td>{s.roomNumber?`${s.roomNumber} · ${s.guest}`:'Bar customer'}</td><td>{money(s.total)}</td><td>{s.staff}</td><td><button disabled={busy} onClick={()=>setReceipt(s)}>View receipt</button></td></tr>)}</tbody></table></div>
      {!data.sales.length&&<p>No bar sales for these dates.</p>}<button disabled={busy||data.page===1} onClick={()=>load(loaded,data.page-1)}>Previous</button><span> Page {data.page} </span><button disabled={busy||!data.hasMore} onClick={()=>load(loaded,data.page+1)}>Next</button></>}
    {receipt&&<BarReceiptDialog receipt={receipt} onClose={()=>setReceipt(null)}/>}</section>;
}
export default function BarPOS({api,can,onUpdated,userId}) {
  const [products,setProducts]=useState([]),[guests,setGuests]=useState([]),[cartState,dispatchCart]=useReducer(cartReducer,{cart:[],error:'',message:''}),[productId,setProductId]=useState(''),[quantity,setQuantity]=useState(1);
  const [method,setMethod]=useState('cash'),[reference,setReference]=useState(''),[reservationId,setReservationId]=useState('');
  const [priceProduct,setPriceProduct]=useState(''),[price,setPrice]=useState('');
  const cart=cartState.cart;
  const [barcode,setBarcode]=useState(''),[scanning,setScanning]=useState(0);
  const scanInput=useRef(null),scanQueue=useRef(Promise.resolve()),mounted=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const pendingKey=`kemmon_bar_sale_${userId}`;
  const [review,setReview]=useState(()=>{try {const p=JSON.parse(localStorage.getItem(pendingKey));return p?.type==='sale'&&p.body?.requestId?p:null;} catch{return null;}}),[receipt,setReceipt]=useState(null),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[version,setVersion]=useState(0);
  async function load(){const p=await api('/bar/products');setProducts(p);if(can('bar.charge'))setGuests(await api('/bar/guests'));}
  useEffect(()=>{load().catch(e=>setError(e.message));},[]);
  function add(e){e.preventDefault();const p=products.find(x=>x.id===productId);if(p){setError('');dispatchCart({type:'add',product:p,quantity:Number(quantity)});}}
  function scan(e) {
    e.preventDefault();
    const code=barcode.trim();
    if(!code){setError('Scan or enter a barcode.');return;}
    setBarcode('');setError('');setScanning(n=>n+1);
    scanQueue.current=scanQueue.current.then(async()=>{
      if(!mounted.current)return;
      try {
        const p=await api(`/bar/scan?${new URLSearchParams({barcode:code})}`);
        if(mounted.current){dispatchCart({type:'add',product:p,quantity:1});setProducts(items=>items.map(old=>old.id===p.id?p:old));}
      } catch(error){if(mounted.current)setError(error.message);}
      finally {if(mounted.current){setScanning(n=>n-1);scanInput.current?.focus();}}
    });
  }
  const total=cart.reduce((n,i)=>n+i.quantity*i.expectedPrice,0);
  useEffect(()=>{try {if(review?.type==='sale')localStorage.setItem(pendingKey,JSON.stringify(review));else localStorage.removeItem(pendingKey);}catch{}},[review,pendingKey]);
  async function save(){setBusy(true);setError('');setMessage('');try{if(review.type==='sale'){const s=await api('/bar/sales',{method:'POST',body:JSON.stringify(review.body)});try{localStorage.removeItem(pendingKey);}catch{}setReceipt(s);dispatchCart({type:'reset'});setReference('');setMessage('Sale recorded. Stock updated.');}else{await api(`/bar/products/${review.productId}/price`,{method:'POST',body:JSON.stringify(review.body)});setMessage('Selling price saved.');}setReview(null);await load();await onUpdated();setVersion(v=>v+1);}catch(e){setError(e.message);}finally{setBusy(false);}}
  return <section><h2>Bar POS</h2><p>Open your cashier shift before recording cash or mobile money. Record money already received, or add a sale to a checked-in guest’s bill. Mobile payment entry records a transfer received outside this app.</p>{error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
    <button disabled={busy||!!review||scanning>0} onClick={()=>load().catch(e=>setError(e.message))}>Refresh products and guests</button>
    {can('bar.prices')&&<form onSubmit={e=>{e.preventDefault();const p=products.find(x=>x.id===priceProduct);if(p)setReview({type:'price',productId:p.id,body:{requestId:crypto.randomUUID(),expectedPrice:p.price,price:Number(price)},summary:`Set ${p.name} selling price to ${money(price)} (currently ${money(p.price)}).`});}}><h3>Set selling price</h3><label>Product<select required value={priceProduct} disabled={busy||!!review||scanning>0} onChange={e=>{setPriceProduct(e.target.value);setPrice('');}}><option value="">Select product</option>{products.map(p=><option key={p.id} value={p.id}>{p.name} · {money(p.price)}</option>)}</select></label><label>Selling price per unit (TZS)<input required type="number" min="1" max="999999999999" value={price} disabled={busy||!!review||scanning>0} onChange={e=>setPrice(e.target.value)}/></label><button disabled={busy||!!review||scanning>0}>Review price</button></form>}
    {!products.length&&<p>Add products and opening stock in Inventory first.</p>}
    {can('bar.sell')&&<><form className="barcode-scan" onSubmit={scan}>
      <h3>Scan product</h3><p>Use a USB or Bluetooth scanner in keyboard mode with Enter after each barcode. Scanning adds one item; it does not complete the sale.</p>
      <label>Product barcode<input ref={scanInput} type="text" value={barcode} maxLength={80} autoComplete="off" spellCheck={false} disabled={busy||!!review} onChange={e=>setBarcode(e.target.value)}/></label>
      <button disabled={busy||!!review}>Add scanned product</button><button type="button" disabled={busy||!!review} onClick={()=>scanInput.current?.focus()}>Focus scanner</button>
      {scanning>0&&<p role="status">Looking up {scanning} barcode{scanning===1?'':'s'}…</p>}
      {cartState.error&&<p role="alert">{cartState.error}</p>}{cartState.message&&<p role="status">{cartState.message}</p>}
    </form><fieldset disabled={busy||!!review||scanning>0}><legend>Create sale</legend><form onSubmit={add}><label>Product<select required value={productId} onChange={e=>setProductId(e.target.value)}><option value="">Select product</option>{products.map(p=><option key={p.id} value={p.id} disabled={p.price<=0||p.stock<=0}>{p.name} · {p.stock} {p.unit} · {p.price>0?money(p.price):'Price not set'}</option>)}</select></label><label>Quantity<input required type="number" min="1" max="1000000" value={quantity} onChange={e=>setQuantity(e.target.value)}/></label><button>Add to sale</button></form>
      <ul>{cart.map(i=><li key={i.productId}>{i.name} · {i.quantity} × {money(i.expectedPrice)} = {money(i.quantity*i.expectedPrice)} <button onClick={()=>dispatchCart({type:'remove',id:i.productId})}>Remove</button></li>)}</ul><p><strong>Total: {money(total)}</strong></p>
      <form onSubmit={e=>{e.preventDefault();setReview({type:'sale',body:{requestId:crypto.randomUUID(),method,reference:method==='mobile_money'?reference:null,reservationId:method==='room'?reservationId:null,items:cart.map(({productId,quantity,expectedPrice})=>({productId,quantity,expectedPrice}))},summary:`Record ${cart.map(i=>`${i.quantity} ${i.name}`).join(', ')} for ${money(total)}. ${method==='room'?`Charge to ${guests.find(g=>g.id===reservationId)?.guest}, Room ${guests.find(g=>g.id===reservationId)?.roomNumber}; no payment received.`:method==='cash'?'Cash received.':`Mobile payment received: ${reference}.`}`});}}>
        <label>Payment / room charge<select value={method} onChange={e=>setMethod(e.target.value)}><option value="cash">Cash received</option><option value="mobile_money">Mobile money received</option>{can('bar.charge')&&<option value="room">Charge to room</option>}</select></label>
        {method==='mobile_money'&&<label>Transaction reference<input required maxLength={120} value={reference} onChange={e=>setReference(e.target.value)}/></label>}
        {method==='room'&&<label>Checked-in guest<select required value={reservationId} onChange={e=>setReservationId(e.target.value)}><option value="">Select guest</option>{guests.map(g=><option value={g.id} key={g.id}>Room {g.roomNumber} · {g.guest}</option>)}</select></label>}
        <button disabled={!cart.length}>Review sale</button></form></fieldset></>}
    {review&&<ConfirmationPrompt busy={busy} onDismiss={()=>setReview(null)} feedback={error}><h3>Confirm {review.type==='sale'?'bar sale':'selling price'}</h3><p>{review.summary}</p><p>If saving fails, retry here before creating another sale.</p><button disabled={busy} onClick={save}>{busy?'Saving…':'Confirm and save'}</button><button disabled={busy} onClick={()=>setReview(null)}>Go back</button></ConfirmationPrompt>}
    {receipt&&<BarReceiptDialog receipt={receipt} onClose={()=>setReceipt(null)}/>}<BarSalesReport api={api} version={version}/>
  </section>;
}
