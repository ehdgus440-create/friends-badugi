"""Verify public Internet room capacity: 4 friends, one rejection, then rejoin."""
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE="https://ehdgus440-create.github.io/friends-badugi/"
ART=Path("test-artifacts")
ART.mkdir(exist_ok=True)

def main():
    print("START 5-player public room capacity test",flush=True)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=["--no-sandbox"])
        contexts=[]
        pages=[]
        errors=[]
        def page_for(label):
            ctx=browser.new_context(viewport={"width":900,"height":520},service_workers="block")
            contexts.append(ctx)
            page=ctx.new_page()
            pages.append(page)
            page.on("pageerror",lambda err: errors.append(label+": "+str(err)))
            return page
        try:
            host=page_for("host")
            host.goto(BASE+"?verify=capacity-host",wait_until="domcontentloaded",timeout=60000)
            host.locator("#createRoom").click()
            host.locator("#hostNick").fill("5인검증방장")
            host.locator("#hostCreate").click()
            host.locator(".royalCode").wait_for(timeout=100000)
            code=host.locator(".royalCode").inner_text().strip()
            assert code.isdigit() and len(code)==4
            print("CAPACITY ROOM:",code,flush=True)
            friends=[]
            for index in range(4):
                friend=page_for("friend"+str(index+1))
                friend.goto(BASE+"?room="+code+"&verify=capacity-"+str(index),wait_until="domcontentloaded",timeout=60000)
                friend.locator("#guestNick").fill("검증친구"+str(index+1))
                friend.locator("#guestConnect").click()
                friend.locator(".royalCode").wait_for(timeout=30000)
                host.wait_for_function("(n)=>document.querySelectorAll('.royalPerson').length===n",arg=index+2,timeout=15000)
                friends.append(friend)
            assert host.locator(".royalPerson").count()==5
            print("PASS capacity: host and 4 friends actually entered public lobby",flush=True)
            overflow=page_for("overflow")
            overflow.goto(BASE+"?room="+code+"&verify=full",wait_until="domcontentloaded",timeout=60000)
            overflow.locator("#guestNick").fill("초과친구")
            overflow.locator("#guestConnect").click()
            overflow.locator("#connectTitle").wait_for(timeout=20000)
            overflow.wait_for_function("document.querySelector('#connectDescription')?.textContent.includes('정원')",timeout=15000)
            assert host.locator(".royalPerson").count()==5
            print("PASS capacity: 6th player correctly refused",flush=True)
            friends[1].locator("#leaveLobby").click()
            friends[1].locator("#confirmLeaveRoom").click()
            host.wait_for_function("document.querySelectorAll('.royalPerson').length===4",timeout=15000)
            print("PASS capacity: departed friend vacated a seat",flush=True)
            overflow.get_by_role("button",name="↻ 다시 시도").click()
            overflow.locator("#guestNick").fill("재입장친구")
            overflow.locator("#guestConnect").click()
            overflow.locator(".royalCode").wait_for(timeout=30000)
            host.wait_for_function("(n)=>document.querySelectorAll('.royalPerson').length===n",arg=5,timeout=15000)
            assert "재입장친구" in host.locator(".royalPeople").inner_text()
            print("PASS capacity: replacement friend joined the same public room",flush=True)
            host.locator("#startOnline").click()
            for friend in [friends[0],friends[2],friends[3],overflow]:
                friend.locator(".gameShell").wait_for(timeout=20000)
            assert "재입장친구" in overflow.locator(".heroDetails").inner_text()
            print("PASS capacity: live 5-player game started and all connected friends received state",flush=True)
            assert not errors,errors
            host.screenshot(path=str(ART/"capacity-host.png"))
            overflow.screenshot(path=str(ART/"capacity-rejoin.png"))
            print("ALL 5-PLAYER PUBLIC ROOM CAPACITY TESTS PASSED",flush=True)
        except BaseException as error:
            print("CAPACITY TEST FAILED:",str(error),flush=True)
            for i,page in enumerate(pages):
                try:
                    print("VIEW "+str(i)+":",page.locator("body").inner_text()[:600],flush=True)
                    page.screenshot(path=str(ART/f"capacity-failure-{i}.png"),full_page=True)
                except Exception:pass
            raise
        finally:
            for context in contexts:
                context.close()
            browser.close()

if __name__=="__main__":
    main()
