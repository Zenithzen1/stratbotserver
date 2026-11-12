import os, sys
n = 0
def act(state):
    global n
    n += 1
    print("exiter: call", n)
    if n == 3:
        sys.exit("exiter: sys.exit")
    if n == 6:
        os._exit(1)              # really kills the process
    return "STAY"
