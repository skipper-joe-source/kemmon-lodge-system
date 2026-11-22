import ConfirmationPrompt from './ConfirmationPrompt';
import { useEffect, useState } from 'react';
const today = () => new Intl.DateTimeFormat('en-CA', {timeZone:'Africa/Dar_es_Salaam',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const amount = (n) => Number(n).toLocaleString() + ' TZS';
export default function InventoryPanel({api, can}) {
  const [products,setProducts]=useState([]), [history,setHistory]=useState(null), [page,setPage]=useState(1);
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[review,setReview]=useState(null),[filter,setFilter]=useState('');
  const [product,setProduct]=useState({name:'',unit:'bottle',reorderLevel:5,barcode:''});
  const [barcodeProduct,setBarcodeProduct]=useState(''),[barcode,setBarcode]=useState('');
  const [form,setForm]=useState({productId:'',kind:can('inventory.purchase')?'purchase':'wastage',quantity:'',unitCost:'',supplier:'',notes:'',occurredOn:today()});
  async function load(selected=filter,p=page) {
    const [a,b]=await Promise.all([api('/inventory/products'),api(`/inventory/movements?${new URLSearchParams({page:String(p),...(selected?{product_id:selected}:{})})}`)]);
    setProducts(a);setHistory(b);
  }
  useEffect(()=>{load().catch(e=>setError(e.message));},[filter,page]);
  const selected=products.find(p=>p.id===form.productId);
  const change=e=>{setForm({...form,[e.target.name]:e.target.value});setReview(null);};
  async function save() {
    setBusy(true);setError('');
    try {await api(review.path,{method:'POST',body:JSON.stringify(review.body)});setReview(null);await load();setForm({...form,quantity:'',notes:''});}
    catch(e){setError(e.message);}finally{setBusy(false);}
  }
  function prepare(e) {
    e.preventDefault(); if(!selected)return;
    const q=Number(form.quantity),delta=form.kind==='purchase'?q:form.kind==='wastage'?-q:q-selected.stock;
    if(selected.stock+delta<0){setError('Not enough stock for this wastage.');return;}
    setError('');setReview({path:'/inventory/movements',body:{requestId:crypto.randomUUID(),productId:selected.id,kind:form.kind,quantity:q,expectedStock:selected.stock,unitCost:form.kind==='purchase'?Number(form.unitCost):null,supplier:form.kind==='purchase'?form.supplier:'',notes:form.notes,occurredOn:form.occurredOn},summary:`${selected.name}: ${form.kind}. Current ${selected.stock}; change ${delta>0?'+':''}${delta}; resulting stock ${selected.stock+delta} ${selected.unit}.${form.kind==='purchase'?` Purchase cost: ${amount(q*Number(form.unitCost))}.`:''}`});
  }
  return <section><h2>Inventory & purchases</h2><p>Quantities use individual units, such as bottles. Record opening stock using a stock count. Purchase costs do not automatically create paid expenses.</p>
    {error&&<p role="alert">{error}</p>}
    <button disabled={busy} onClick={()=>load().catch(e=>setError(e.message))}>Refresh inventory</button>
    {can('inventory.manage')&&<form onSubmit={e=>{e.preventDefault();setReview({path:'/inventory/products',body:{...product,reorderLevel:Number(product.reorderLevel),requestId:crypto.randomUUID()},summary:`Create ${product.name}, unit: ${product.unit}, low-stock threshold: ${product.reorderLevel}, barcode: ${product.barcode.trim()||'not assigned'}. Opening stock is zero.`});}}>
      <h3>Add product</h3><label>Product name<input required maxLength={120} value={product.name} onChange={e=>setProduct({...product,name:e.target.value})}/></label>
      <label>Barcode (optional)<input type="text" maxLength={80} autoComplete="off" spellCheck={false} value={product.barcode} onChange={e=>setProduct({...product,barcode:e.target.value})}/></label>
      <label>Unit<input required maxLength={30} value={product.unit} onChange={e=>setProduct({...product,unit:e.target.value})}/></label>
      <label>Low-stock threshold<input type="number" min="0" max="1000000" required value={product.reorderLevel} onChange={e=>setProduct({...product,reorderLevel:e.target.value})}/></label><button disabled={busy}>Review product</button>
    </form>}
    {can('inventory.manage')&&<form className="barcode-assignment" onSubmit={e=>{e.preventDefault();const p=products.find(x=>x.id===barcodeProduct);if(p)setReview({path:`/inventory/products/${p.id}/barcode`,body:{requestId:crypto.randomUUID(),expectedBarcode:p.barcode,barcode:barcode.trim()||null},summary:`${p.name}: change barcode from ${p.barcode||'not assigned'} to ${barcode.trim()||'not assigned'}.`});}}>
      <h3>Assign or change barcode</h3><p>Click the barcode box and scan the product, or type the code exactly as printed. Leading zeros are kept. Leave it blank to remove a barcode.</p>
      <label>Product<select required disabled={busy||!!review} value={barcodeProduct} onChange={e=>{setBarcodeProduct(e.target.value);setBarcode(products.find(p=>p.id===e.target.value)?.barcode||'');}}><option value="">Select product</option>{products.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
      <label>Barcode<input type="text" maxLength={80} autoComplete="off" spellCheck={false} value={barcode} disabled={busy||!!review} onChange={e=>setBarcode(e.target.value)}/></label><button disabled={busy||!!review||!barcodeProduct}>Review barcode</button>
    </form>}
    <h3>Current stock</h3><p>{products.filter(p=>p.low_stock).length} products at or below their low-stock threshold.</p>
    <div className="table-scroll"><table><thead><tr><th>Product</th><th>Unit</th><th>Barcode</th><th>In stock</th><th>Threshold</th><th>Status</th></tr></thead><tbody>{products.map(p=><tr key={p.id}><td>{p.name}</td><td>{p.unit}</td><td>{p.barcode||"Not assigned"}</td><td>{p.stock}</td><td>{p.reorder_level}</td><td>{p.low_stock?'Low stock':'Available'}</td></tr>)}</tbody></table></div>
    {!products.length&&<p>No products yet.</p>}
    {(can('inventory.purchase')||can('inventory.adjust'))&&<form onSubmit={prepare}><h3>Record stock movement</h3>
      <label>Product<select required name="productId" value={form.productId} onChange={change}><option value="">Select product</option>{products.map(p=><option value={p.id} key={p.id}>{p.name} — {p.stock} {p.unit}</option>)}</select></label>
      <label>Action<select name="kind" value={form.kind} onChange={change}><option value="" disabled>Select action</option>{can('inventory.purchase')&&<option value="purchase">Stock purchase</option>}{can('inventory.adjust')&&<><option value="wastage">Damage / wastage</option><option value="count">Physical stock count</option></>}</select></label>
      <label>{form.kind==='count'?'Actual quantity counted':'Quantity'}<input required type="number" name="quantity" min={form.kind==='count'?0:1} max="1000000" value={form.quantity} onChange={change}/></label>
      {form.kind==='purchase'&&<><label>Supplier<input required maxLength={160} name="supplier" value={form.supplier} onChange={change}/></label><label>Cost per unit (TZS)<input required type="number" min="0" max="999999999999" step="1" name="unitCost" value={form.unitCost} onChange={change}/></label></>}
      <label>Date (Tanzania)<input required type="date" max={today()} name="occurredOn" value={form.occurredOn} onChange={change}/></label>
      <label>Reason / purchase reference<input required maxLength={1000} name="notes" value={form.notes} onChange={change}/></label><button disabled={busy||!selected}>Review movement</button>
    </form>}
    {review&&<ConfirmationPrompt busy={busy} onDismiss={()=>setReview(null)} feedback={error}><h3>Confirm inventory action</h3><p>{review.summary}</p><button disabled={busy} onClick={save}>{busy?'Saving…':'Confirm and save'}</button><button disabled={busy} onClick={()=>setReview(null)}>Cancel</button></ConfirmationPrompt>}
    <h3>Stock history</h3><label>Product filter<select value={filter} onChange={e=>{setFilter(e.target.value);setPage(1);}}><option value="">All products</option>{products.map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
    <div className="table-scroll"><table><thead><tr><th>Date</th><th>Product</th><th>Action</th><th>Quantity</th><th>Change</th><th>Balance after</th><th>Supplier / cost</th><th>Reason</th><th>Staff / recorded time</th></tr></thead><tbody>{history?.items.map(m=><tr key={m.id}><td>{m.occurred_on}</td><td>{m.product_name}</td><td>{m.kind}</td><td>{m.quantity}</td><td>{m.delta}</td><td>{m.balance}</td><td>{m.kind==='purchase'?`${m.supplier} · ${amount(Number(m.unit_cost)*m.quantity)}`:'—'}</td><td>{m.notes}</td><td>{m.staff} · {new Date(m.created_at).toLocaleString('en-GB',{timeZone:'Africa/Dar_es_Salaam'})}</td></tr>)}</tbody></table></div>
    <button disabled={page===1||busy} onClick={()=>setPage(page-1)}>Previous</button><span> Page {page} </span><button disabled={!history?.hasMore||busy} onClick={()=>setPage(page+1)}>Next</button>
  </section>;
}
