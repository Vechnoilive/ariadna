'use strict';
(() => {
 const unit=(frame,id)=>frame?.agents.find(agent=>agent.id===id);
 const target=(frame,kind)=>frame?.targets.find(item=>item.appearance?.kind===kind);
 const event=(frame,type)=>frame.events.find(item=>item.type===type&&item.status==='new');
 function crossed(before,after,door){
  if(!before||!after||!door)return false;
  const {min,max}=door.geometry;
  const axis=max[0]-min[0]<max[1]-min[1]?0:1;
  const middle=(min[axis]+max[axis])/2;
  const delta=after[axis]-before[axis];
  if(!delta)return false;
  const fraction=(middle-before[axis])/delta;
  const along=before[1-axis]+fraction*(after[1-axis]-before[1-axis]);
  return fraction>0&&fraction<=1&&along>=min[1-axis]&&along<=max[1-axis];
 }
 function beats(id,frames){
  const moments=[];
  function add(index,title,copy,agent){
   if(index>=0)moments.push({index,title,copy,agent});
  }
  const first=fn=>frames.findIndex(fn);
  const end=frames.length-1;
  if(id==='leak'){
   const carrier='carrier_b';
   add(0,'Ключ в прихожей','Термос забирает ключ. Вентиль находится в прачечной.',carrier);
   add(first(frame=>event(frame,'restricted_zone_appeared')),'Вход залит','Вода отрезала вход в прачечную из прихожей. На карте виден обход.',carrier);
   for(const [doorId,title,copy] of [
    ['door_study','Через кабинет','Термос проходит в кабинет через сухую дверь.'],
    ['door_service','Через служебную дверь','Из кабинета Термос спускается в прачечную к вентилю.'],
   ]){
    const door=frames[0]?.zones.find(zone=>zone.id===doorId);
    add(first((frame,index)=>crossed(unit(frames[index-1],carrier)?.position,unit(frame,carrier)?.position,door)),title,copy,carrier);
   }
   add(first(frame=>target(frame,'valve')?.status==='delivered'),'Ключ у вентиля','Термос довёз ключ. Залитый порог остался закрытым для роботов.',carrier);
  }else if(id==='blackout'){
   add(0,'Проверка сети','Шлюз и ретрансляторы держат связь между комнатами.');
   add(first(frame=>event(frame,'infrastructure_failure')),'Роутер отключился','В квартире погас свет. Подсветка на карте показывает доступные радиоканалы.');
   const lost=first(frame=>event(frame,'connectivity_loss'));
   const disconnected=lost>=0?frames[lost].agents.find(agent=>!agent.communication.connected&&unit(frames[lost-1],agent.id)?.communication.connected):null;
   if(disconnected){
    const label=disconnected.appearance.name;
    add(lost,'Связь прервалась',label+' выпал из сети.',disconnected.id);
    const restored=first((frame,index)=>index>lost&&unit(frame,disconnected.id)?.communication.connected);
    if(restored>=0){
     const relay=frames[restored].agents.find(agent=>agent.role==='relay'&&agent.position&&
      agent.position.some((value,index)=>value!==unit(frames[restored-1],agent.id)?.position?.[index]));
     add(restored,'Связь вернулась',relay?relay.appearance.name+' переместился. '+label+' снова на связи.':label+' снова на связи.',relay?.id??disconnected.id);
    }
   }
   add(first(frame=>event(frame,'contradictory_information')),'Нужна проверка','Штаб получил разные сигналы. Сначала нужно подтвердить цель, потом отправить курьера.');
   const lamp=first(frame=>target(frame,'kit')?.status==='delivered');
   add(lamp,'Фонарь доставлен','Курьер доставил фонарь и пауэрбанк в кабинет.',frames[lamp]?.agents.find(agent=>agent.role==='executor')?.id);
  }else if(id==='privacy'){
   add(0,'Доставка на кухне','Роботы обслуживают кухню. Из кабинета ещё нет подтверждённого запроса.');
   add(first(frame=>event(frame,'contradictory_information')),'Датчики не согласны','Штаб получил противоречивые сведения о жильце.');
   add(first(frame=>event(frame,'operator_directive')),'Жилец закрыл двери','Вход в кабинет и служебная дверь закрыты. Оператор отменил выезд.');
   if(frames[end]?.mission.status==='safe_stopped')add(end,'Рой остановился','После команды оператора роботы остались на своих местах.');
  }
  return moments.sort((a,b)=>a.index-b.index);
 }
 window.AriadnaHomeStory={beats};
})();
