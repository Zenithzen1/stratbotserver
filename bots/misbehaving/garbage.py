n = 0
def act(state):
    global n
    n += 1
    return 42 if n % 2 else "north"
