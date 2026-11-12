import threading, time
count = 0
def spin():
    global count
    while True:
        count += 1
threading.Thread(target=spin, daemon=True).start()
last = 0
def act(state):
    global last
    t0 = time.perf_counter(); before = count
    time.sleep(0.01)                       # 10 ms of its own turn
    during = count - before
    print("between my turns the thread counted", before - last, "| during 10 ms of my turn", during)
    last = count
    return "STAY"
