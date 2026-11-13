'use strict';
async function decodeAriadnaPacket(packet){
 if(!packet||packet.format!=='ariadna.gzip.v1'||!Number.isInteger(packet.bytes)||packet.bytes<1||packet.bytes>64*1024*1024)throw Error('Некорректный пакет операций');
 if(typeof DecompressionStream==='undefined')throw Error('Для просмотра операций нужен современный Chrome, Edge, Firefox или Safari.');
 const compressed=Uint8Array.from(atob(packet.data),c=>c.charCodeAt(0));
 const reader=new Blob([compressed]).stream().pipeThrough(new DecompressionStream('gzip')).getReader(),chunks=[];let length=0;
 while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>packet.bytes){await reader.cancel();throw Error('Превышен размер пакета');}chunks.push(value);}
 if(length!==packet.bytes)throw Error('Повреждён пакет операций');
 const bytes=new Uint8Array(length);let offset=0;for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
 if(globalThis.crypto?.subtle){const digest=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));if([...digest].map(v=>v.toString(16).padStart(2,'0')).join('')!==packet.sha256)throw Error('Контрольная сумма операций не совпала');}
 return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
}
if(window.ARIADNA_PACK||window.ARIADNA_DEMO)window.ARIADNA_READY=(async()=>{
 const data=window.ARIADNA_DEMO ?? await decodeAriadnaPacket(window.ARIADNA_PACK);
 if(window.ARIADNA_INCIDENT_PACK)data.incident=await decodeAriadnaPacket(window.ARIADNA_INCIDENT_PACK);
 if(window.ARIADNA_COSMIC_PACK){
  const cosmic=await decodeAriadnaPacket(window.ARIADNA_COSMIC_PACK);
  data.episodes.push(cosmic.episode);data.cosmic_research=cosmic.research;data.cosmic_comparison=cosmic.comparison;
  Object.assign(data.source_sha256,cosmic.source_sha256);
 }
 window.ARIADNA_DEMO=data;
 return data;
})();
