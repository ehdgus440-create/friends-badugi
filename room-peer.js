/* 친구들끼리 바둑이: WebSocket relay-backed room connections. */
(function(){
'use strict';
const ENDPOINT='wss://friends-badugi-rooms.onrender.com/ws';
class Emitter {
 constructor(){this.events=Object.create(null)}
 on(type,callback){(this.events[type]||=[]).push(callback);return this}
 emit(type,...args){for(const cb of this.events[type]||[]){try{cb(...args)}catch(e){console.error('Badugi room listener:',e)}}}
}
class Connection extends Emitter {
 constructor(peer,remote,cid){super();this.provider=peer;this.peer=remote;this.connectionId=cid;this.open=false;this.closed=false;this.queue=[]}
 send(content){
  if(this.closed)return;
  if(!this.open){if(this.queue.length<20)this.queue.push(content);return}
  this.provider._send({type:'relay',connId:this.connectionId,content})
 }
 _ready(){if(this.closed||this.open)return;this.open=true;this.emit('open');for(const msg of this.queue.splice(0))this.send(msg)}
 _close(){if(this.closed)return;this.closed=true;this.open=false;this.queue.length=0;this.provider.connections.delete(this.connectionId);this.emit('close')}
 close(){if(this.closed)return;this.provider._send({type:'close',connId:this.connectionId});this._close()}
}
class BadugiRoomPeer extends Emitter {
 constructor(id,options={}){
  super();this.id=id||null;this.open=false;this.destroyed=false;this.connections=new Map();this.ws=null;
  if(typeof WebSocket!=='function'){queueMicrotask(()=>this.emit('error',{type:'unsupported-browser'}));return}
  try{this.ws=new WebSocket(window.BADUGI_ROOM_WS_URL||ENDPOINT)}
  catch(e){queueMicrotask(()=>this.emit('error',{type:'network',message:String(e)}));return}
  this.ws.addEventListener('open',()=>this._send({type:'register',id:this.id}));
  this.ws.addEventListener('message',event=>{
   if(this.destroyed)return;
   let msg;try{msg=JSON.parse(event.data)}catch(e){return}
   if(msg.type==='registered'){this.id=msg.id;this.open=true;this.emit('open',msg.id)}
   else if(msg.type==='peer-error')this.emit('error',{type:msg.error||'network'})
   else if(msg.type==='incoming'){
    const c=new Connection(this,msg.from,msg.connId);this.connections.set(msg.connId,c);this.emit('connection',c)
   }
   else if(msg.type==='conn-ready')this.connections.get(msg.connId)?._ready()
   else if(msg.type==='payload')this.connections.get(msg.connId)?.emit('data',msg.content)
   else if(msg.type==='conn-close')this.connections.get(msg.connId)?._close()
   else if(msg.type==='conn-error'){
    const c=this.connections.get(msg.connId);
    if(c){c.emit('error',{type:msg.reason||'network'});c._close()}
   }
  });
  this.ws.addEventListener('close',()=>{
   if(this.destroyed)return;
   this.open=false;for(const c of [...this.connections.values()])c._close();this.emit('disconnected',this.id)
  });
  this.ws.addEventListener('error',()=>{if(!this.destroyed)this.emit('error',{type:'network'})})
 }
 _send(message){if(!this.destroyed&&this.ws?.readyState===WebSocket.OPEN){try{this.ws.send(JSON.stringify(message))}catch(e){this.emit('error',{type:'network'})}}}
 connect(destination){
  const cid='c-'+Math.random().toString(36).slice(2)+'-'+Date.now().toString(36);
  const c=new Connection(this,destination,cid);this.connections.set(cid,c);this._send({type:'connect',to:destination,connId:cid});return c
 }
 destroy(){if(this.destroyed)return;this.destroyed=true;this.open=false;for(const c of [...this.connections.values()])c._close();this.connections.clear();try{this.ws?.close()}catch(e){}}
}
window.BadugiRoomPeer=BadugiRoomPeer;window.Peer=BadugiRoomPeer;
})();
