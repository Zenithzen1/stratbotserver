n = 0
def act(state):
    global n
    n += 1
    if n % 5 == 0:
        raise RuntimeError("crasher: boom on my call %d" % n)
    return "STAY"
