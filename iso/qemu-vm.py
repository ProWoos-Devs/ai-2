#!/usr/bin/env python3
"""Tiny QEMU driver: HMP commands, QMP mouse, keyboard typing, screenshots.

  vm.py hmp <cmd...>            run an HMP monitor command, print reply
  vm.py shot <name>             screendump -> <name>.png (in vm dir)
  vm.py type <text>             type ASCII text via sendkey (\\n = Enter)
  vm.py key <sendkey-name>      single key (e.g. ret, tab, ctrl-alt-f2)
  vm.py click <x> <y> [double]  absolute mouse move+click (screen coords)
  vm.py move <x> <y>
Screen size assumed 1024x768 unless VM_W/VM_H env set.
"""
import json, os, socket, subprocess, sys, time

D = "/tmp/claude-1000/ai2bt"
MON = f"{D}/mon"
QMP = f"{D}/qmp"
W = int(os.environ.get("VM_W", 1024)); H = int(os.environ.get("VM_H", 768))

def hmp(cmd):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(MON)
    s.settimeout(2)
    try: s.recv(4096)  # banner
    except socket.timeout: pass
    s.sendall((cmd + "\n").encode())
    out = b""
    t = time.time()
    while time.time() - t < 3:
        try:
            chunk = s.recv(65536)
            if not chunk: break
            out += chunk
        except socket.timeout:
            break
    s.close()
    txt = out.decode(errors="replace")
    # strip echo + prompt
    lines = [l for l in txt.splitlines() if l.strip() and not l.startswith("(qemu)") and l.strip() != cmd]
    return "\n".join(l.replace("(qemu) ", "") for l in lines)

def qmp_cmds(cmds):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(QMP)
    f = s.makefile("rwb", buffering=0)
    f.readline()  # greeting
    f.write(json.dumps({"execute": "qmp_capabilities"}).encode() + b"\n"); f.readline()
    for c in cmds:
        f.write(json.dumps(c).encode() + b"\n")
        r = f.readline()
        if b'"error"' in r: print(r.decode().strip(), file=sys.stderr)
    s.close()

def mouse(x, y, click=0):
    ax = int(x * 32767 / (W - 1)); ay = int(y * 32767 / (H - 1))
    ev = [{"type": "abs", "data": {"axis": "x", "value": ax}},
          {"type": "abs", "data": {"axis": "y", "value": ay}}]
    cmds = [{"execute": "input-send-event", "arguments": {"events": ev}}]
    qmp_cmds(cmds); time.sleep(0.15)
    for _ in range(click):
        qmp_cmds([{"execute": "input-send-event", "arguments": {"events": [
            {"type": "btn", "data": {"down": True, "button": "left"}}]}}])
        time.sleep(0.08)
        qmp_cmds([{"execute": "input-send-event", "arguments": {"events": [
            {"type": "btn", "data": {"down": False, "button": "left"}}]}}])
        time.sleep(0.12)

SHIFT = {'!':'1','@':'2','#':'3','$':'4','%':'5','^':'6','&':'7','*':'8','(':'9',')':'0',
         '_':'minus','+':'equal','{':'bracket_left','}':'bracket_right','|':'backslash',
         ':':'semicolon','"':'apostrophe','<':'comma','>':'dot','?':'slash','~':'grave_accent'}
PLAIN = {' ':'spc','-':'minus','=':'equal','[':'bracket_left',']':'bracket_right','\\':'backslash',
         ';':'semicolon',"'":'apostrophe',',':'comma','.':'dot','/':'slash','`':'grave_accent',
         '\n':'ret','\t':'tab'}

def keyname(ch):
    if ch.isalpha():
        return ("shift-" if ch.isupper() else "") + ch.lower()
    if ch.isdigit(): return ch
    if ch in PLAIN: return PLAIN[ch]
    if ch in SHIFT: return "shift-" + SHIFT[ch]
    raise ValueError(f"no key for {ch!r}")

def type_text(text, delay=0.06):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM); s.connect(MON)
    s.settimeout(0.5)
    try: s.recv(4096)
    except socket.timeout: pass
    for ch in text:
        s.sendall(("sendkey " + keyname(ch) + "\n").encode()); time.sleep(delay)
        try: s.recv(4096)
        except socket.timeout: pass
    time.sleep(0.3); s.close()

if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "hmp": print(hmp(" ".join(a[1:])))
    elif a[0] == "shot":
        ppm = f"{D}/{a[1]}.ppm"; png = f"{D}/{a[1]}.png"
        hmp(f"screendump {ppm}"); time.sleep(0.5)
        subprocess.run(["magick", ppm, png], check=True); os.remove(ppm); print(png)
    elif a[0] == "type": type_text(a[1].replace("\\n", "\n"))
    elif a[0] == "key": hmp("sendkey " + a[1])
    elif a[0] == "click": mouse(int(a[1]), int(a[2]), 2 if (len(a) > 3 and a[3] == "double") else 1)
    elif a[0] == "move": mouse(int(a[1]), int(a[2]), 0)
    else: print(__doc__)
