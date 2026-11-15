"""End-to-end multiplayer verification against the public GitHub Pages + Render servers.

Uses independent Chromium browser contexts; does not mock WebSockets or game actions.
"""
import json
import os
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "https://ehdgus440-create.github.io/friends-badugi/"
HEALTH = "https://friends-badugi-rooms.onrender.com/healthz"
ARTIFACTS = Path("test-artifacts")
ARTIFACTS.mkdir(exist_ok=True)

def wait_health():
    last = None
    for attempt in range(25):
        try:
            req = urllib.request.Request(HEALTH,headers={"User-Agent":"Badugi-E2E/1.0"})
            with urllib.request.urlopen(req,timeout=18) as res:
                data=json.load(res)
            print("Live Render health:", data, flush=True)
            if data.get("status") == "ok":
                return data
            last=data
        except Exception as error:
            last=str(error)
        time.sleep(5)
    raise AssertionError(f"Live relay server did not become healthy: {last}")

def check():
    print("START online end-to-end test",flush=True)
    health = wait_health()
    problems=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,args=["--no-sandbox"])
        contextHost=browser.new_context(viewport={"width":900,"height":520},service_workers="block")
        contextGuest=browser.new_context(viewport={"width":900,"height":520},service_workers="block")
        host=contextHost.new_page()
        guest=contextGuest.new_page()
        host.on("pageerror",lambda error: problems.append("host page: "+str(error)))
        guest.on("pageerror",lambda error: problems.append("guest page: "+str(error)))
        try:
            host.goto(BASE+"?verify=live-room-host",wait_until="domcontentloaded",timeout=60000)
            host.locator("#createRoom").wait_for(timeout=20000)
            host.locator("#createRoom").click()
            host.locator("#hostNick").fill("검증방장")
            host.locator("#hostCreate").click()
            host.locator(".royalCode").wait_for(timeout=105000)
            code=host.locator(".royalCode").inner_text().strip()
            assert len(code)==4 and code.isdigit(),f"Bad room code: {code!r}"
            print("PASS 1: live room code",code,flush=True)
            # Guest must use a separate browser profile, with no host state.
            guest.goto(BASE+"?room="+code+"&verify=live-room-guest",wait_until="domcontentloaded",timeout=60000)
            guest.locator("#roomCode").wait_for(timeout=20000)
            assert guest.locator("#roomCode").input_value()==code
            guest.locator("#guestNick").fill("검증친구")
            guest.locator("#guestConnect").click()
            guest.locator(".royalCode").wait_for(timeout=105000)
            host.wait_for_function("document.querySelector('.royalPeople')?.textContent.includes('검증친구')",timeout=15000)
            assert "검증방장" in guest.locator(".royalPeople").inner_text()
            print("PASS 2: independent browser received room invite and joined lobby",flush=True)
            host.locator("#startOnline").click()
            guest.locator(".gameShell").wait_for(timeout=25000)
            assert "검증친구" in guest.locator(".heroDetails").inner_text()
            assert host.locator(".gameShell").count()==1
            print("PASS 3: host started real 2-player multiplayer game",flush=True)
            # Drive complete game: each betting stage is checked by both players;
            # each exchange stage is confirmed with zero selected cards.
            for betRound in range(4):
                host.locator("#call").wait_for(timeout=15000)
                host.locator("#call").click()
                guest.locator("#call").wait_for(timeout=15000)
                guest.locator("#call").click()
                print(f"PASS bet round {betRound+1}: host and guest actions synced",flush=True)
                if betRound<3:
                    host.locator("#drawConfirm").wait_for(timeout=15000)
                    host.locator("#drawConfirm").click()
                    guest.locator("#drawConfirm").wait_for(timeout=15000)
                    guest.locator("#drawConfirm").click()
                    print(f"PASS exchange {betRound+1}: guest state synchronized",flush=True)
            host.locator(".showdownCurtain").wait_for(timeout=15000)
            guest.locator(".showdownCurtain").wait_for(timeout=15000)
            assert guest.locator(".showdownCards .card").count()>=8
            assert guest.locator(".showdownTimer").is_visible()
            print("PASS 4: showdown and both players' cards shown on guest device",flush=True)
            assert not problems,"JavaScript errors: "+repr(problems)
            host.screenshot(path=str(ARTIFACTS/"host-success.png"))
            guest.screenshot(path=str(ARTIFACTS/"guest-success.png"))
            print("ALL PUBLIC ONLINE MULTIPLAYER END-TO-END TESTS PASSED",flush=True)
        except BaseException as exc:
            print("ONLINE E2E FAILURE:",str(exc),flush=True)
            print("Host UI:",host.locator("body").inner_text()[:1400],flush=True)
            print("Guest UI:",guest.locator("body").inner_text()[:1400],flush=True)
            try:host.screenshot(path=str(ARTIFACTS/"host-failure.png"),full_page=True)
            except Exception:pass
            try:guest.screenshot(path=str(ARTIFACTS/"guest-failure.png"),full_page=True)
            except Exception:pass
            raise
        finally:
            contextGuest.close()
            contextHost.close()
            browser.close()
    if health.get("selftest",{}).get("status")=="failed":
        print("WARNING: Relay public endpoint selftest failed:",health["selftest"],flush=True)

if __name__=="__main__":
    check()
