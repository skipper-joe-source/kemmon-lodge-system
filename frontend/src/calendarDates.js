export const addDays = (date,n) => new Date(Date.parse(`${date}T00:00:00Z`)+n*86400000).toISOString().slice(0,10);
export function bookingsOn(stays,roomId,day,today) {
  return stays.filter(s => { const start=s.roomAllocationFrom||s.checkIn; const end=s.checkOut>start?s.checkOut:addDays(start,1);
    return s.roomId===roomId && ['confirmed','checked_in'].includes(s.status) && ((day>=start&&day<end)||(s.status==='checked_in'&&day===today&&s.checkOut<=today));
  });
}
