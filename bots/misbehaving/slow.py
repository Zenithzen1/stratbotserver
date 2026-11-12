import time
n = 0
def act(state):
    global n
    n += 1
    if n == 5:
        time.sleep(0.5)          # late once
    if n == 20:
        while True:              # stuck forever from here on
            pass
    return "STAY"
