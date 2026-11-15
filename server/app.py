"""WebSocket room relay for Friends Badugi, max five players per room."""
import asyncio
import json
import logging
import os
import re
import secrets
from http import HTTPStatus
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

logging.basicConfig(level=logging.INFO)
LOG=logging.getLogger("badugi")
PEERS={}
IDENTITIES={}
LINKS={}
SOCKET_LINKS={}
HOST_ID=re.compile(r"^badugi222-[1-9][0-9]{3}$")
MAX_PLAYERS=5

async def send(socket, data):
    try:
        await socket.send(json.dumps(data,ensure_ascii=False,separators=(",",":")))
        return True
    except ConnectionClosed:
        return False

async def drop_link(cid, sender=None):
    pair=LINKS.pop(cid,None)
    if not pair:
        return
    for ws in pair:
        SOCKET_LINKS.get(ws,set()).discard(cid)
    for ws in pair:
        if ws is not sender:
            await send(ws,{"type":"conn-close","connId":cid})

async def unregister(ws):
    peerid=IDENTITIES.pop(ws,None)
    if peerid and PEERS.get(peerid) is ws:
        PEERS.pop(peerid,None)
    for cid in list(SOCKET_LINKS.pop(ws,set())):
        await drop_link(cid,ws)

async def receive(ws,packet):
    kind=packet.get("type")
    if kind=="register":
        if ws in IDENTITIES:return
        peerid=packet.get("id")
        if peerid is None:peerid="badugi-guest-"+secrets.token_hex(10)
        if not isinstance(peerid,str) or not (HOST_ID.fullmatch(peerid) or peerid.startswith("badugi-guest-")):
            await send(ws,{"type":"peer-error","error":"invalid-id"});return
        if peerid in PEERS:
            await send(ws,{"type":"peer-error","error":"unavailable-id"});return
        PEERS[peerid]=ws;IDENTITIES[ws]=peerid;SOCKET_LINKS[ws]=set()
        await send(ws,{"type":"registered","id":peerid});return
    if ws not in IDENTITIES:
        await send(ws,{"type":"peer-error","error":"not-registered"});return
    if kind=="connect":
        target_id,cid=packet.get("to"),packet.get("connId")
        if not isinstance(target_id,str) or not isinstance(cid,str) or not 4<=len(cid)<=100:return
        target=PEERS.get(target_id)
        if target is None or target is ws or not HOST_ID.fullmatch(target_id):
            await send(ws,{"type":"conn-error","connId":cid,"reason":"peer-unavailable"});return
        if cid in LINKS or len(SOCKET_LINKS.get(target,()))>=MAX_PLAYERS-1:
            await send(ws,{"type":"conn-error","connId":cid,"reason":"room-full"});return
        if SOCKET_LINKS.get(ws):
            await send(ws,{"type":"conn-error","connId":cid,"reason":"already-connected"});return
        LINKS[cid]=(ws,target)
        SOCKET_LINKS[ws].add(cid);SOCKET_LINKS[target].add(cid)
        if not await send(target,{"type":"incoming","from":IDENTITIES[ws],"connId":cid}):
            await drop_link(cid);return
        await send(target,{"type":"conn-ready","connId":cid})
        await send(ws,{"type":"conn-ready","connId":cid});return
    if kind=="relay":
        cid=packet.get("connId");pair=LINKS.get(cid)
        if not pair or ws not in pair:return
        payload=packet.get("content")
        if not isinstance(payload,dict):return
        other=pair[1] if pair[0] is ws else pair[0]
        await send(other,{"type":"payload","connId":cid,"content":payload});return
    if kind=="close":
        cid=packet.get("connId")
        if ws in LINKS.get(cid,()):await drop_link(cid,ws)

async def client(ws):
    try:
        async for raw in ws:
            if len(raw)>128000:
                await ws.close(code=1009,reason="Message too large");break
            try:p=json.loads(raw)
            except (ValueError,TypeError):continue
            if isinstance(p,dict):await receive(ws,p)
    except ConnectionClosed:pass
    except Exception:LOG.exception("client")
    finally:await unregister(ws)

def health(conn,request):
    if request.path=="/healthz":return conn.respond(HTTPStatus.OK,"ok\n")
    if request.path!="/ws":return conn.respond(HTTPStatus.NOT_FOUND,"Not found\n")
    return None

async def main():
    port=int(os.environ.get("PORT","8765"))
    async with serve(client,"0.0.0.0",port,process_request=health,max_size=128000,ping_interval=25,ping_timeout=30):
        LOG.info("listening on %d",port)
        await asyncio.Future()

if __name__=="__main__":
    asyncio.run(main())
