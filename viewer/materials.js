'use strict';
(() => {
 const size=128;
 const tau=2*Math.PI;
 const surfaces={
  oak: (x,y,n)=>{
   const plank=(x*6)%1,offset=(Math.floor(x*6)%2)*.5,join=(y*2+offset)%1;
   if(plank<.036||join<.022)return 95;
   const grain=Math.sin(tau*(x*43+.24*Math.sin(tau*y)));
   return 177+24*grain+11*Math.sin(tau*Math.floor(x*6)/6)+17*n;
  },
  terrazzo: (x,y,n)=>{
   const sx=Math.sin(tau*(x*37+y*13)),sy=Math.cos(tau*(y*39-x*17));
   return sx*sy>.72?132+60*n:217+24*n;
  },
  ceramic: (x,y,n)=>{
   const a=(x*5)%1,b=(y*5)%1;
   if(a<.044||b<.044)return 101;
   return 175+20*Math.sin(tau*(Math.floor(x*5)+2*Math.floor(y*5))/5)+12*n;
  },
  weave: (x,y,n)=>171+13*Math.sin(tau*x*32)*Math.cos(tau*y*32)+14*n,
  metal: (x,y,n)=>197+17*Math.sin(tau*y*48)+8*n,
  asphalt: (x,y,n)=>89+29*n+8*Math.sin(tau*(x+y)),
  planks: (x,y,n)=>{
   const board=Math.floor(x*8), edge=(x*8)%1;
   if(edge<.055||edge>.975)return 42;
   const grain=Math.sin(tau*(x*29+Math.sin(tau*y)*.32));
   return 162+(board%3)*13+18*grain+22*n;
  },
  water: (x,y,n)=>{
   const swell=Math.sin(tau*(y*4+.32*Math.sin(tau*(2*x+y))));
   const ripple=Math.sin(tau*(y*11+x*2));
   return 165+18*swell+9*ripple+6*n;
  },
  rubber: (x,y,n)=>{
   const groove=((x*6+Math.abs(.5-((y*4)%1))*2)%1)<.19;
   return (groove?55:137)+15*n;
  },
 };
 const textures=new Map();
 window.ariadnaSurfaceTexture=name=>{
  if(textures.has(name))return textures.get(name);
  const canvas=document.createElement('canvas');
  canvas.width=canvas.height=size;
  const ctx=canvas.getContext('2d');
  const pixels=ctx.createImageData(size,size);
  let seed=0x80f41;
  for(let y=0;y<size;y++){
   for(let x=0;x<size;x++){
    seed=(Math.imul(seed,1664525)+1013904223)>>>0;
    const tone=surfaces[name](x/size,y/size,seed/2**32-.5), i=(y*size+x)*4;
    pixels.data.set([tone,tone,tone,255],i);
   }
  }
  ctx.putImageData(pixels,0,0);
  const texture=new window.THREE.CanvasTexture(canvas);
  texture.wrapS=texture.wrapT=window.THREE.RepeatWrapping;
  texture.anisotropy=4;
  textures.set(name,texture);
  return texture;
 };
})();
