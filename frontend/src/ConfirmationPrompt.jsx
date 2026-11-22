import {Children,isValidElement,useEffect,useLayoutEffect,useRef} from 'react';
import {createPortal} from 'react-dom';
import {confirmationPosition} from './confirmationPosition';

let trigger = null;
let scrollLocks = 0;
let originalOverflow = '';
export function useConfirmationAnchors() {
  useEffect(()=>{
    const remember = event => {
      const element = event.type === 'submit'
        ? event.submitter || event.target.querySelector('button[type="submit"], button:not([type]), input[type="submit"]')
        : event.target.closest?.('button, input[type="submit"]');
      if (!element || element.closest('[data-confirmation-prompt]')) return;
      trigger = element.closest('nav') ? null : {element,at:Date.now()};
    };
    document.addEventListener('click',remember,true);
    document.addEventListener('submit',remember,true);
    return()=>{document.removeEventListener('click',remember,true);document.removeEventListener('submit',remember,true);trigger=null;};
  },[]);
}
export default function ConfirmationPrompt({children,busy=false,onDismiss,feedback,...props}) {
  const ref=useRef(null);
  const anchor=useRef(trigger && Date.now()-trigger.at<15000 ? trigger.element : null);
  useLayoutEffect(()=>{
    const dialog=ref.current;
    const previousFocus=document.activeElement;
    if(scrollLocks++===0){originalOverflow=document.body.style.overflow;document.body.style.overflow='hidden';}
    const position=()=>{
      if(!dialog.open)return;
      const box=dialog.getBoundingClientRect();
      const rect=anchor.current?.isConnected ? anchor.current.getBoundingClientRect() : null;
      const next=confirmationPosition(rect,{width:box.width,height:box.height},{width:window.innerWidth,height:window.innerHeight});
      dialog.style.left=`${next.left}px`;dialog.style.top=`${next.top}px`;
    };
    dialog.showModal();position();
    // Focus the summary, so the Enter used to request a review cannot also confirm it.
    dialog.focus({preventScroll:true});
    const observer=typeof ResizeObserver!=='undefined'?new ResizeObserver(position):null;
    observer?.observe(dialog);
    window.addEventListener('resize',position);
    window.addEventListener('scroll',position,true);
    return()=>{
      observer?.disconnect();window.removeEventListener('resize',position);window.removeEventListener('scroll',position,true);
      if(dialog.open)dialog.close();
      if(--scrollLocks===0)document.body.style.overflow=originalOverflow;
      requestAnimationFrame(()=>{
        const target=anchor.current?.isConnected&&!anchor.current.disabled?anchor.current:previousFocus;
        const modals=Array.from(document.querySelectorAll('dialog[open]'));
        const activeModal=modals.at(-1);
        if(target?.isConnected&&!target.disabled&&(!activeModal||activeModal.contains(target)))target.focus({preventScroll:true});
      });
    };
  },[]);
  const nodes=Children.toArray(children);
  const isAction=node=>isValidElement(node)&&node.type==='button';
  const actions=nodes.filter(isAction);
  return createPortal(<dialog {...props} ref={ref} className="action-confirmation confirmation-prompt" data-confirmation-prompt="true" role="alertdialog" aria-modal="true" aria-label={props['aria-label']||'Confirm action'} tabIndex={-1}
    onCancel={event=>{event.preventDefault();event.stopPropagation();if(!busy)onDismiss?.();}}>
    <div className="confirmation-summary">{nodes.filter(node=>!isAction(node))}</div>
    {feedback&&<p className="confirmation-feedback" role="alert">{feedback}</p>}
    {actions.length>0&&<div className="confirmation-actions">{actions}</div>}
  </dialog>,document.body);
}
