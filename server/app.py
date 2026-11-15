"""HTTP health + WebSocket room relay for Friends Badugi.

One Render instance hosts transient 4-digit rooms, up to four guests per host.
The game runs client-side; relay only forwards game-state messages.
"""
import asyncio
import json
import logging
import os
import re
import secrets
from aiohttp import web, WSMsgType, ClientSession, ClientTimeout

logging.basicConfig(level=logging.INFO)
LOG = logging.getLogger('badugi-relay')
PORT = int(os.environ.get('PORT', '8765'))
PEERS = {}
IDENTITIES = {}
LINKS = {}
SOCKET_LINKS = {}
HOST_ID = re.compile(r'^badugi222-[1-9][0-9]{3}$')
MAX_PLAYERS = 5
SELFTEST = {'status': 'pending'}

async def send(ws, obj):
    if ws.closed:
        return False
    try:
        await ws.send_json(obj, dumps=lambda x: json.dumps(x, ensure_ascii=False, separators=(',', ':')))
        return True
    except (ConnectionError, RuntimeError):
        return False

async def drop_link(cid, sender=None):
    pair = LINKS.pop(cid, None)
    if not pair:
        return
    for ws in pair:
        SOCKET_LINKS.get(ws, set()).discard(cid)
    for ws in pair:
        if ws is not sender:
            await send(ws, {'type': 'conn-close', 'connId': cid})

async def unregister(ws):
    identity = IDENTITIES.pop(ws, None)
    if identity and PEERS.get(identity) is ws:
        PEERS.pop(identity, None)
    for cid in list(SOCKET_LINKS.pop(ws, set())):
        await drop_link(cid, ws)

async def handle_packet(ws, packet):
    kind = packet.get('type')
    if kind == 'register':
        if ws in IDENTITIES:
            return
        peer_id = packet.get('id')
        if peer_id is None:
            peer_id = 'badugi-guest-' + secrets.token_hex(10)
        if not isinstance(peer_id, str) or not (HOST_ID.fullmatch(peer_id) or re.fullmatch(r'badugi-guest-[a-zA-Z0-9-]{8,60}', peer_id)):
            await send(ws, {'type':'peer-error','error':'invalid-id'})
            return
        if peer_id in PEERS:
            await send(ws, {'type':'peer-error','error':'unavailable-id'})
            return
        PEERS[peer_id] = ws
        IDENTITIES[ws] = peer_id
        SOCKET_LINKS[ws] = set()
        await send(ws, {'type':'registered','id':peer_id})
        return
    if ws not in IDENTITIES:
        await send(ws, {'type':'peer-error','error':'not-registered'})
        return
    if kind == 'connect':
        target_id, cid = packet.get('to'), packet.get('connId')
        if not isinstance(target_id, str) or not isinstance(cid, str) or not (4 <= len(cid) <= 100):
            await send(ws, {'type':'conn-error','connId':cid,'reason':'invalid-connect'})
            return
        target = PEERS.get(target_id)
        if target is None or target is ws or not HOST_ID.fullmatch(target_id):
            await send(ws, {'type':'conn-error','connId':cid,'reason':'peer-unavailable'})
            return
        if cid in LINKS or len(SOCKET_LINKS.get(target, ())) >= MAX_PLAYERS - 1:
            await send(ws, {'type':'conn-error','connId':cid,'reason':'room-full'})
            return
        if SOCKET_LINKS.get(ws):
            await send(ws, {'type':'conn-error','connId':cid,'reason':'already-connected'})
            return
        LINKS[cid] = (ws, target)
        SOCKET_LINKS[ws].add(cid)
        SOCKET_LINKS[target].add(cid)
        if not await send(target, {'type':'incoming','from':IDENTITIES[ws],'connId':cid}):
            await drop_link(cid)
            return
        await send(target, {'type':'conn-ready','connId':cid})
        await send(ws, {'type':'conn-ready','connId':cid})
        return
    if kind == 'relay':
        cid = packet.get('connId')
        pair = LINKS.get(cid)
        if not pair or ws not in pair or not isinstance(packet.get('content'), dict):
            return
        other = pair[1] if pair[0] is ws else pair[0]
        await send(other, {'type':'payload','connId':cid,'content':packet['content']})
        return
    if kind == 'close':
        cid = packet.get('connId')
        if ws in LINKS.get(cid, ()):
            await drop_link(cid, ws)

async def room_socket(request):
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=128_000, compress=False)
    await ws.prepare(request)
    try:
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                try:
                    packet = json.loads(message.data)
                except (ValueError, TypeError):
                    continue
                if isinstance(packet, dict):
                    await handle_packet(ws, packet)
            elif message.type == WSMsgType.ERROR:
                LOG.warning('WebSocket error: %s', ws.exception())
    except Exception:
        LOG.exception('Client connection failure')
    finally:
        await unregister(ws)
    return ws

async def health(_):
    return web.json_response({'status':'ok','liveRooms':sum(bool(HOST_ID.fullmatch(p)) for p in PEERS),
                              'activeConnections':len(LINKS),'selftest':SELFTEST},
                             headers={'Cache-Control':'no-store'})

async def remote_protocol_test():
    """Exercise the running WebSocket transport through its public hostname."""
    endpoint = os.environ.get('SELFTEST_WS_URL', 'wss://friends-badugi-rooms.onrender.com/ws')
    async with ClientSession(timeout=ClientTimeout(total=30)) as session:
        code = str(secrets.randbelow(9000)+1000)
        host = await session.ws_connect(endpoint, heartbeat=15)
        guest = await session.ws_connect(endpoint, heartbeat=15)
        try:
            async def got(sock, expected):
                packet = await asyncio.wait_for(sock.receive_json(),timeout=9)
                if packet.get('type') != expected:
                    raise AssertionError(f'expected {expected}, got {packet}')
                return packet
            await host.send_json({'type':'register','id':'badugi222-'+code})
            await got(host,'registered')
            await guest.send_json({'type':'register'})
            await got(guest,'registered')
            cid = 'test-'+secrets.token_hex(8)
            await guest.send_json({'type':'connect','to':'badugi222-'+code,'connId':cid})
            await got(host,'incoming')
            await got(host,'conn-ready')
            await got(guest,'conn-ready')
            await guest.send_json({'type':'relay','connId':cid,'content':{'kind':'hello','name':'검증 친구'}})
            hello = await got(host,'payload')
            assert hello['content']['name'] == '검증 친구'
            await host.send_json({'type':'relay','connId':cid,'content':{'kind':'welcome','seat':1}})
            welcome = await got(guest,'payload')
            assert welcome['content']['seat'] == 1
            await guest.close()
            await got(host,'conn-close')
            return {'status':'passed','scope':'public WebSocket hostname, registration, join, two-way relay, disconnect'}
        finally:
            await host.close()
            await guest.close()

async def check_at_start():
    global SELFTEST
    await asyncio.sleep(3)
    try:
        SELFTEST = await remote_protocol_test()
        LOG.info('Public WebSocket relay selftest PASSED: %s', SELFTEST)
    except Exception as error:
        SELFTEST = {'status':'failed','reason':str(error)[:200]}
        LOG.error('Public WebSocket relay selftest failed: %s', error)

async def app_startup(app):
    app['selfcheck_task'] = asyncio.create_task(check_at_start())

async def app_cleanup(app):
    app['selfcheck_task'].cancel()
    await asyncio.gather(app['selfcheck_task'], return_exceptions=True)

app = web.Application(client_max_size=128_000)
app.router.add_route('*','/healthz',health)
app.router.add_get('/ws',room_socket)
app.on_startup.append(app_startup)
app.on_cleanup.append(app_cleanup)

if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=PORT, access_log=None)
