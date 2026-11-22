import kemmonLogo from './assets/kemmon-logo.png';
import {useState} from 'react';
const names={'Rooms':'Rooms & Suites','Bar POS':'Restaurant & Bar','Staff Management':'Staff & Roles','Reports':'Reports & Insights','Account':'My account'};
const symbols={'Dashboard':'grid','Rooms':'room','Reservations':'calendar','Availability calendar':'calendar','Walk-ins':'user','Payments':'card','Reports':'chart','Expenses':'card','Cash summary':'chart','Cashier shifts':'clock','Audit logs':'list','Owner alerts':'bell','Maintenance':'tool','Inventory':'box','Bar POS':'cup','Staff Management':'user','Backups':'box','Account':'settings'};
const paths={grid:'M3 3h7v18H3z M14 3h7v7h-7z M14 14h7v7h-7z',room:'M4 21V3h16v18 M2 21h20 M8 7h2 M14 7h2 M8 11h2 M14 11h2 M10 21v-6h4v6',calendar:'M4 5h16v16H4z M8 2v6 M16 2v6 M4 10h16 M8 14h2 M14 14h2',user:'M16 7a4 4 0 1 1-8 0a4 4 0 1 1 8 0 M4 22v-3a8 8 0 0 1 16 0v3',card:'M3 5h18v14H3z M3 10h18 M7 15h4',chart:'M3 3v18h19 M7 16v-4 M12 16V8 M17 16V5',clock:'M21 12a9 9 0 1 1-18 0a9 9 0 1 1 18 0 M12 6v6l4 2',list:'M4 3h16v18H4z M8 7h8 M8 12h8 M8 17h5',bell:'M5 17h14l-2-4V9a5 5 0 0 0-10 0v4z M10 21h4',tool:'M14 3a6 6 0 0 0-7 7L2 16l5 5l6-6a6 6 0 0 0 8-7l-5 4l-4-4z',box:'M3 6l9-4l9 4v12l-9 4l-9-4z M3 6l9 4l9-4 M12 10v12',cup:'M4 8h12v7a6 6 0 0 1-12 0z M16 9h2a3 3 0 0 1 0 6h-2 M6 2v3 M11 2v3 M2 22h18',settings:'M12 8a4 4 0 1 1 0 8a4 4 0 1 1 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2'};
export function LodgeIcon({name='grid'}){return <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]||paths.grid}/></svg>;}
export default function LodgeShell({user,pages,activePage,connected,alertCount,busy,onLogout,onNavigate,onNewReservation,children}) {
 const [open,setOpen]=useState(false);
 const date=new Date();
 const formatted=new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Dar_es_Salaam',day:'numeric',month:'short',year:'numeric'}).format(date);
 const hour=Number(new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Dar_es_Salaam',hour:'numeric',hourCycle:'h23'}).format(date));
 const admin=['Staff Management','Audit logs','Backups','Account'];
 const navigate=name=>{onNavigate(name);setOpen(false);};
 function menu(list){return list.map(name=><button type="button" key={name} aria-current={activePage===name?'page':undefined} onClick={()=>navigate(name)}><LodgeIcon name={symbols[name]}/><span>{names[name]||name}</span>{name==='Owner alerts'&&alertCount>0&&<b className="sidebar-badge">{alertCount}</b>}</button>);}
 return <div className="lodge-app">
 <a className="skip-link" href="#lodge-content">Skip to content</a>
 <button type="button" className="mobile-menu" aria-expanded={open} aria-controls="lodge-sidebar" onClick={()=>setOpen(!open)}>{open?'Close menu':'☰ Menu'}</button>
 {open&&<button className="sidebar-scrim" aria-label="Close navigation" onClick={()=>setOpen(false)}/>}
 <aside id="lodge-sidebar" className={`lodge-sidebar ${open?'is-open':''}`}>
 <div className="lodge-brand"><img className="lodge-logo" src={kemmonLogo} alt="Kemmon Lodge logo" width="76" height="76" /><div><strong>Kemmon<br/>Lodge</strong><small>HOSPITALITY &amp; RETREAT</small></div></div>
 <nav aria-label="Main navigation"><p className="nav-heading">Workspace</p>{menu(pages.filter(p=>!admin.includes(p)))}<p className="nav-heading">Administration</p>{menu(pages.filter(p=>admin.includes(p)))}</nav>
 <div className="sidebar-user"><span className="user-avatar">{user.username.slice(0,2).toUpperCase()}</span><div><strong>{user.username}</strong><small>{user.roleName}</small></div><button type="button" onClick={onLogout} disabled={busy} aria-label="Log out" title="Log out">↪</button></div>
 </aside>
 <main className="lodge-content" id="lodge-content" tabIndex={-1}>
 <header className="lodge-header"><div><p className="header-eyebrow">{new Intl.DateTimeFormat('en-GB',{timeZone:'Africa/Dar_es_Salaam',weekday:'long',day:'numeric',month:'long',year:'numeric'}).format(date)}</p><h1>{activePage==='Dashboard'?`Good ${hour<12?'morning':hour<17?'afternoon':'evening'}, ${user.username}`:names[activePage]||activePage}</h1><p>{activePage==='Dashboard'?"Here’s what’s happening at Kemmon Lodge today.":'Thoughtful hospitality. Everything in its place.'}</p></div>
 <div className="header-actions"><span className="date-chip"><LodgeIcon name="calendar"/>{formatted}</span>{pages.includes('Owner alerts')&&<button type="button" className="header-alert" aria-label={`Owner alerts${alertCount?`, ${alertCount} need review`:''}`} onClick={()=>navigate('Owner alerts')}><LodgeIcon name="bell"/>{alertCount>0&&<i/>}</button>}{onNewReservation&&<button type="button" onClick={onNewReservation}>＋ New reservation</button>}</div></header>
 <div className={`connection-indicator ${connected?'is-connected':''}`} role="status"><i/>{connected?'Lodge connected':'Connection unavailable'}<span>· Tanzania time</span></div>
 <div className="lodge-page">{children}</div><footer className="lodge-footer">Kemmon Lodge <span>Hospitality, thoughtfully managed.</span></footer>
 </main></div>;
}
